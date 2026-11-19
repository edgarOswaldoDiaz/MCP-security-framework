from __future__ import annotations

import logging
import os

from telemetry import configure_telemetry

configure_telemetry()

from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    TaskState,
)
from opentelemetry.instrumentation.starlette import StarletteInstrumentor
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

from auth import authenticate_and_authorize, record_audit_event

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("agentops.a2a")


class AgentOpsEchoExecutor(AgentExecutor):
    """Minimal A2A executor; replace with a bounded, task-aware agent runtime."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Procesando la solicitud..."),
        )

        user_text = get_message_text(context.message) or ""
        # This sample intentionally echoes text. Treat all remote agent input as
        # untrusted and add content filtering, tool allowlists and quotas in prod.
        answer = f"AgentOps A2A recibió: {user_text[:4000]}"
        await updater.add_artifact(
            parts=[new_text_part(text=answer, media_type="text/plain")]
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Tarea completada."),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not implemented by this sample agent")


agent_skill = AgentSkill(
    id="echo",
    name="Echo / connectivity test",
    description="Receives a text message and returns a bounded echo response.",
    tags=["agentops", "smoke-test"],
    examples=["Hola, valida la conexión A2A"],
    input_modes=["text/plain"],
    output_modes=["text/plain"],
)

public_url = os.getenv("A2A_PUBLIC_URL", "http://localhost:9001/")
agent_card = AgentCard(
    name="AgentOps A2A Agent",
    description="Reference A2A agent secured by Keycloak and OPA.",
    version="0.1.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url=public_url,
            protocol_version="1.0",
        )
    ],
    security_schemes={
        "BearerAuth": SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer",
                bearer_format="JWT",
                description="Keycloak access token with the agents:invoke scope and the configured audience.",
            )
        )
    },
    security_requirements=[
        SecurityRequirement(schemes={"BearerAuth": StringList(list=["agents:invoke"])})
    ],
    skills=[agent_skill],
)

handler = DefaultRequestHandler(
    agent_executor=AgentOpsEchoExecutor(),
    task_store=InMemoryTaskStore(),  # Replace with a durable task store in production.
    agent_card=agent_card,
)


async def healthz(request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "agentops-a2a", "version": "0.1.0"})


app = Starlette(
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        *create_agent_card_routes(agent_card),
        *create_jsonrpc_routes(handler, rpc_url="/"),
    ]
)
StarletteInstrumentor().instrument_app(app)


@app.middleware("http")
async def keycloak_opa_audit_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "GET" and path in {"/healthz", "/.well-known/agent-card.json"}:
        return await call_next(request)

    allowed_origins = {
        item.strip()
        for item in os.getenv("A2A_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins:
        return JSONResponse({"error": "origin_not_allowed"}, status_code=403)

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        try:
            await record_audit_event(
                event_type="authentication",
                actor=None,
                action="a2a:invoke",
                target=path,
                decision="deny",
                details={"reason": "missing_bearer_token"},
            )
        except Exception:
            logger.exception("Unable to persist missing-token audit event")
            return JSONResponse({"error": "audit_unavailable"}, status_code=503)
        return JSONResponse({"error": "bearer_token_required"}, status_code=401)

    try:
        identity = await authenticate_and_authorize(token.strip(), "a2a:invoke")
    except Exception:
        logger.exception("A2A authentication, policy or audit backend unavailable")
        return JSONResponse({"error": "authorization_service_unavailable"}, status_code=503)

    if identity is None:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    request.state.identity = identity
    return await call_next(request)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000, proxy_headers=False, server_header=False)
