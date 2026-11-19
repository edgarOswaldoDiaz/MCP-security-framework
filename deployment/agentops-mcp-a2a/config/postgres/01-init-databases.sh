#!/usr/bin/env bash
set -euo pipefail

# Use psql's quoted variable expansion so generated passwords are not embedded
# in this script or interpolated as raw SQL.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=kc_password="$KC_DB_PASSWORD" \
  --set=agentops_password="$AGENTOPS_DB_PASSWORD" <<'SQL'
CREATE ROLE keycloak LOGIN PASSWORD :'kc_password';
CREATE DATABASE keycloak OWNER keycloak;
CREATE ROLE agentops LOGIN PASSWORD :'agentops_password';
CREATE DATABASE agentops OWNER agentops;
SQL

PGPASSWORD="$AGENTOPS_DB_PASSWORD" psql -v ON_ERROR_STOP=1 \
  --username agentops --dbname agentops <<'SQL'
CREATE SCHEMA IF NOT EXISTS agentops AUTHORIZATION agentops;

CREATE TABLE IF NOT EXISTS agentops.agent_registry (
  agent_id       text PRIMARY KEY,
  name           text NOT NULL,
  description    text NOT NULL DEFAULT '',
  protocol       text NOT NULL CHECK (protocol IN ('MCP', 'A2A')),
  version        text NOT NULL,
  endpoint       text NOT NULL,
  owner_team     text NOT NULL DEFAULT 'unassigned',
  status         text NOT NULL CHECK (status IN ('draft', 'active', 'deprecated', 'disabled')),
  risk_level     text NOT NULL DEFAULT 'unassessed',
  metadata       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agentops.agent_audit (
  id             bigserial PRIMARY KEY,
  event_time     timestamptz NOT NULL DEFAULT now(),
  event_type     text NOT NULL,
  actor          text,
  action         text NOT NULL,
  target         text,
  decision       text NOT NULL CHECK (decision IN ('allow', 'deny', 'error')),
  correlation_id text,
  details        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS agent_audit_time_idx ON agentops.agent_audit (event_time DESC);
CREATE INDEX IF NOT EXISTS agent_audit_actor_idx ON agentops.agent_audit (actor);
CREATE INDEX IF NOT EXISTS agent_audit_action_idx ON agentops.agent_audit (action);

CREATE TABLE IF NOT EXISTS agentops.agent_evaluation_runs (
  id             bigserial PRIMARY KEY,
  agent_id       text NOT NULL REFERENCES agentops.agent_registry(agent_id),
  agent_version  text NOT NULL,
  suite          text NOT NULL,
  dataset_ref    text,
  dataset_hash   text,
  score          numeric(6,5),
  passed         boolean NOT NULL,
  run_at         timestamptz NOT NULL DEFAULT now(),
  report_uri     text,
  metadata       jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS agent_evaluation_agent_time_idx
  ON agentops.agent_evaluation_runs (agent_id, run_at DESC);

INSERT INTO agentops.agent_registry
  (agent_id, name, description, protocol, version, endpoint, status)
VALUES
  ('agentops-mcp', 'AgentOps MCP Server', 'MCP tools exposed over Streamable HTTP', 'MCP', '0.1.0', 'http://localhost:8000/mcp', 'active'),
  ('agentops-a2a', 'AgentOps A2A Agent', 'A2A JSON-RPC sample agent', 'A2A', '0.1.0', 'http://localhost:9001/', 'active')
ON CONFLICT (agent_id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  protocol = EXCLUDED.protocol,
  version = EXCLUDED.version,
  endpoint = EXCLUDED.endpoint,
  updated_at = now();
SQL
