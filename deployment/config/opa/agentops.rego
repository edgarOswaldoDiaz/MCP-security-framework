package agentops.authz

# Fail closed. These are starter policies: add tenant, role, risk, data-class,
# environment and tool-level constraints before exposing real capabilities.
default allow := false

# Change this set deliberately during client onboarding / governance review.
# Token `aud` is checked by the application; this set checks the caller identity.
approved_callers := {"agentops-cli"}

allow if {
  input.action == "mcp:invoke"
  input.client_id in approved_callers
  "mcp:invoke" in input.scopes
}

allow if {
  input.action == "a2a:invoke"
  input.client_id in approved_callers
  "agents:invoke" in input.scopes
}
