from __future__ import annotations

import logging
import os

from telemetry import configure_telemetry

configure_telemetry()

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from auth import authenticate_and_authorize

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("agentops.mcp")


class KeycloakAndOPAVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            identity = await authenticate_and_authorize(token, "mcp:invoke")
        except Exception:
            logger.exception("MCP token verification or policy/audit service failed")
            return None
        if not identity:
            return None
        claims = identity["claims"]
        return AccessToken(
            token=token,
            client_id=identity["client_id"],
            scopes=identity["scopes"],
            expires_at=claims.get("exp"),
            subject=identity["subject"],
            claims=claims,
        )


mcp = MCPServer(
    "AgentOps MCP Server",
    instructions=(
        "Reference MCP server for AgentOps. Tools are authenticated by Keycloak, "
        "authorized by OPA and audited in PostgreSQL."
    ),
    token_verifier=KeycloakAndOPAVerifier(),
    auth=AuthSettings(
        issuer_url=os.environ["MCP_ISSUER_URL"],
        resource_server_url=os.environ["MCP_PUBLIC_URL"],
        required_scopes=["mcp:invoke"],
        # Keycloak's `aud` is not automatically the RFC 8707 resource URL in this
        # starter realm. The verifier still validates active status and OPA scopes.
        validate_token_resource=False,
    ),
)


@mcp.tool()
async def echo(message: str) -> str:
    """Return a message, useful for connectivity and authorization smoke tests."""
    return message


@mcp.tool()
async def agentops_metadata() -> dict[str, str]:
    """Return non-sensitive server metadata for client discovery and diagnostics."""
    return {
        "service": "agentops-mcp",
        "version": "0.1.0",
        "transport": "Streamable HTTP",
        "governance": "Keycloak + OPA + PostgreSQL audit",
    }


if __name__ == "__main__":
    allowed_hosts = [v.strip() for v in os.getenv("MCP_ALLOWED_HOSTS", "localhost:8000").split(",") if v.strip()]
    allowed_origins = [v.strip() for v in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if v.strip()]
    security = TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000,
        json_response=True,
        transport_security=security,
    )
