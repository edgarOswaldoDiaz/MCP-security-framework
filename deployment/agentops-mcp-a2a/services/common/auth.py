"""Shared Keycloak token introspection, OPA checks and audit persistence."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import asyncpg
import httpx
from opentelemetry import trace

logger = logging.getLogger("agentops.auth")
_pool: asyncpg.Pool | None = None


async def _db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("AGENTOPS_DB_HOST", "postgres"),
            port=int(os.getenv("AGENTOPS_DB_PORT", "5432")),
            database=os.getenv("AGENTOPS_DB_NAME", "agentops"),
            user=os.getenv("AGENTOPS_DB_USER", "agentops"),
            password=os.environ["AGENTOPS_DB_PASSWORD"],
            min_size=1,
            max_size=10,
            timeout=5,
            command_timeout=5,
        )
    return _pool


def _trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if span_context and span_context.is_valid:
        return format(span_context.trace_id, "032x")
    return None


async def record_audit_event(
    *,
    event_type: str,
    actor: str | None,
    action: str,
    target: str | None,
    decision: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit event; callers fail closed if persistence is unavailable."""
    pool = await _db_pool()
    await pool.execute(
        """INSERT INTO agentops.agent_audit
           (event_type, actor, action, target, decision, correlation_id, details)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)""",
        event_type,
        actor,
        action,
        target,
        decision,
        _trace_id(),
        json.dumps(details or {}, separators=(",", ":")),
    )


async def authenticate_and_authorize(token: str, action: str) -> dict[str, Any] | None:
    """Introspect a bearer token with Keycloak and evaluate the action in OPA.

    Returns a normalized identity only when the token is active and OPA permits
    the requested action. Any infrastructure error is raised so callers can
    fail closed (503 for A2A, 401 for the MCP verifier).
    """
    introspection_url = os.environ["KEYCLOAK_INTROSPECTION_URL"]
    client_id = os.environ["KEYCLOAK_CLIENT_ID"]
    client_secret = os.environ["KEYCLOAK_CLIENT_SECRET"]
    opa_url = os.environ["OPA_URL"]

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        response = await client.post(
            introspection_url,
            data={"token": token},
            auth=(client_id, client_secret),
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        claims = response.json()

        if claims.get("active") is not True:
            await record_audit_event(
                event_type="authentication",
                actor=None,
                action=action,
                target=None,
                decision="deny",
                details={"reason": "inactive_or_invalid_token"},
            )
            return None

        expected_audience = os.environ["KEYCLOAK_EXPECTED_AUDIENCE"]
        audience_claim = claims.get("aud", [])
        audiences = [audience_claim] if isinstance(audience_claim, str) else list(audience_claim or [])
        if expected_audience not in audiences:
            await record_audit_event(
                event_type="authentication",
                actor=claims.get("sub"),
                action=action,
                target=None,
                decision="deny",
                details={"reason": "audience_mismatch", "expected_audience": expected_audience},
            )
            return None

        scopes_value = claims.get("scope", "")
        scopes = scopes_value.split() if isinstance(scopes_value, str) else list(scopes_value or [])
        identity = {
            "subject": claims.get("sub"),
            "client_id": claims.get("client_id") or claims.get("azp") or "unknown-client",
            "issuer": claims.get("iss"),
            "scopes": scopes,
            "claims": claims,
        }

        policy_response = await client.post(
            opa_url,
            json={
                "input": {
                    "action": action,
                    "subject": identity["subject"],
                    "client_id": identity["client_id"],
                    "scopes": scopes,
                }
            },
        )
        policy_response.raise_for_status()
        allowed = policy_response.json().get("result") is True

    await record_audit_event(
        event_type="authorization",
        actor=identity["subject"] or identity["client_id"],
        action=action,
        target=None,
        decision="allow" if allowed else "deny",
        details={"client_id": identity["client_id"], "scopes": scopes},
    )
    return identity if allowed else None
