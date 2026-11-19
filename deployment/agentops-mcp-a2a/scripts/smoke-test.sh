#!/usr/bin/env bash
set -euo pipefail

: "${ACCESS_TOKEN:?Export ACCESS_TOKEN with a Keycloak token carrying mcp:invoke and agents:invoke}"

printf '\n== MCP: list tools via Inspector CLI ==\n'
npx --yes @modelcontextprotocol/inspector --cli \
  http://localhost:8000/mcp --transport http \
  --header "Authorization: Bearer ${ACCESS_TOKEN}" \
  --method tools/list

printf '\n== A2A: fetch public Agent Card ==\n'
curl --fail --silent --show-error \
  http://localhost:9001/.well-known/agent-card.json | python -m json.tool

printf '\n== A2A: invoke SendMessage via JSON-RPC ==\n'
curl --fail --silent --show-error \
  -X POST http://localhost:9001/ \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"smoke-1","method":"SendMessage","params":{"message":{"messageId":"smoke-msg-1","role":"ROLE_USER","parts":[{"text":"Hola desde el smoke test"}]}}}' \
  | python -m json.tool
