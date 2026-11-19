#### **AgentOps MCP + A2A**

#### Arquitectura y endpoints

| Componente | Endpoint local | Función |
|---|---|---|
| MCP | `http://localhost:8000/mcp` | MCP Streamable HTTP, OAuth bearer y CLI |
| A2A | `http://localhost:9001/` | JSON-RPC A2A 1.0 |
| Agent Card | `http://localhost:9001/.well-known/agent-card.json` | Descubrimiento del agente y esquema Bearer JWT / scope `agents:invoke` |
| Keycloak | `http://localhost:8080` | Identidad, OAuth/OIDC e introspección |
| OPA | Solo red interna Docker | Decisiones de autorización (fail closed) |
| PostgreSQL | Solo red interna Docker | BD de Keycloak, auditoría, catálogo y evaluaciones |
| Prometheus | `http://localhost:9090` | Métricas |
| Grafana | `http://localhost:3000` | Paneles (datasource Prometheus provisionado) |
| Jaeger | `http://localhost:16686` | Trazas distribuidas |
| OTLP Collector | `localhost:4317` / `localhost:4318` | Recepción OTLP gRPC/HTTP |

Los puertos publicados están ligados a `127.0.0.1` intencionalmente. Para acceso remoto, coloca un ingress/API gateway con TLS, autenticación, límites de tasa y protección de red delante de MCP/A2A; no cambies los bind addresses a `0.0.0.0` sin ese control.

#### Arranque

```bash
cp .env.example .env
# Edita .env y sustituye todos los valores replace-with-... por secretos únicos.
docker compose config
docker compose up --build -d
docker compose ps
```

El volumen de PostgreSQL 18 se monta en `/var/lib/postgresql` (no en la ruta antigua `/var/lib/postgresql/data`). Los scripts SQL de inicialización solo corren cuando el volumen `postgres_data` se crea por primera vez. No ejecutes `docker compose down -v` en un entorno con datos que quieras conservar.

#### Configuración de Keycloak (paso necesario)

El realm no se precrea deliberadamente para evitar empaquetar secretos de muestra.

1. Abre `http://localhost:8080` e inicia sesión con `KEYCLOAK_ADMIN_USERNAME` y `KEYCLOAK_ADMIN_PASSWORD`.
2. Crea el realm `agentops`.
3. Crea un cliente confidencial `agentops-resource-server`, activa autenticación de cliente y copia su secreto a `KEYCLOAK_RESOURCE_CLIENT_SECRET` en `.env`. Ese cliente autentica la llamada de introspección desde los servidores.
4. Crea los client scopes `mcp:invoke` y `agents:invoke` y asígnalos como scopes permitidos al/los cliente(s) que usarán las APIs. El token introspectado debe incluir esos valores en el claim `scope`.
5. Crea clientes de consumo separados (por ejemplo `agentops-cli`) con el flujo de cliente/usuario adecuado y concede solo los scopes necesarios. No uses el cliente de introspección como identidad de todos los usuarios en producción.
6. En el cliente de consumo, agrega un **Audience mapper** al access token cuyo audience sea `agentops-resource-server`. La introspección debe devolver `aud` incluyendo ese valor; el middleware lo exige y falla cerrado si falta.
7. La política OPA de ejemplo solo admite el `client_id` `agentops-cli` en `config/opa/agentops.rego`. Para incorporar otro consumidor, actualiza `approved_callers` mediante revisión de cambios y reinicia OPA.
8. Verifica que el issuer público sea exactamente el valor de `KEYCLOAK_ISSUER_URL` y reinicia `mcp-server` y `a2a-agent` después de modificar `.env`:

```bash
docker compose up -d --force-recreate mcp-server a2a-agent
```

Para un token de prueba con client credentials, usa las credenciales del cliente de consumo habilitado para ese flujo:

```bash
export TOKEN_URL='http://localhost:8080/realms/agentops/protocol/openid-connect/token'
export CALLER_CLIENT_ID='agentops-cli'
export CALLER_CLIENT_SECRET='secreto-del-cliente-cli'
export ACCESS_TOKEN="$(curl -fsS -u "$CALLER_CLIENT_ID:$CALLER_CLIENT_SECRET" \
  -d grant_type=client_credentials \
  -d 'scope=mcp:invoke agents:invoke' \
  "$TOKEN_URL" | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
```

La forma de obtener scopes depende de cómo se configuren los client scopes y los mappers en Keycloak. Confirma el claim `scope` en el token/introspection antes de probar OPA.

#### Acceso MCP por API y CLI

El endpoint MCP usa Streamable HTTP. Los clientes HTTP deben seguir la negociación MCP; no es una API REST arbitraria. Para inspección con CLI:

```bash
npx --yes @modelcontextprotocol/inspector --cli \
  http://localhost:8000/mcp --transport http \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --method tools/list

npx --yes @modelcontextprotocol/inspector --cli \
  http://localhost:8000/mcp --transport http \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --method tools/call --tool-name echo --tool-arg message='hola AgentOps'
```

También puede probarse la API con un cliente MCP SDK. Los clientes deben usar el header `Authorization: Bearer ...` y el endpoint `/mcp`.

### Acceso A2A por API y CLI

Consulta pública de la tarjeta del agente:

```bash
curl -fsS http://localhost:9001/.well-known/agent-card.json | python -m json.tool
```

Invocación JSON-RPC A2A 1.0 desde CLI (`curl`):

```bash
curl -fsS -X POST http://localhost:9001/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": "req-1",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "msg-1",
        "role": "ROLE_USER",
        "parts": [{"text": "Hola, valida la conexión A2A"}]
      }
    }
  }' | python -m json.tool
```

Smoke test combinado:

```bash
ACCESS_TOKEN="$ACCESS_TOKEN" ./scripts/smoke-test.sh
```

#### Controles 

| Dominio | Base incluida | Pendiente antes de producción |
|---|---|---|
| Seguridad | OAuth bearer mediante introspección Keycloak; OPA fail-closed; puertos locales; contenedores de agentes sin root, read-only y sin capabilities | TLS/ingress, mTLS entre servicios cuando aplique, rate limits, secret manager, escaneo de imágenes/SBOM, allowlist de herramientas y protección contra prompt injection |
| Gobernanza | Reglas Rego y campos de owner/risk/status en catálogo | Flujo formal de aprobación, políticas por tenant/rol/datos, separación de funciones y revisión de cambios |
| Trazabilidad | Correlation/trace ID cuando exista; auditoría de autorización en PostgreSQL; trazas OTLP/Jaeger | Eventos de negocio y de cada herramienta, retención/WORM, exportación a SIEM y auditoría de cambios de configuración |
| Evaluación | Tabla `agent_evaluation_runs` y smoke tests de contrato MCP/A2A | Suites offline/online, datasets versionados, evaluaciones de seguridad/calidad, umbrales de promoción y publicación de reportes |
| Identidad | Keycloak OIDC y `sub`/`client_id` de tokens introspectados | Identidad workload por agente, rotación de credenciales, federation/SSO y mapeo de grupos/roles |
| Observabilidad | OTel Collector, Prometheus, Grafana y Jaeger | Alertas/SLO, paneles por agente, métricas de costo/tokens, muestreo y almacenamiento persistente de trazas |
| Catálogo | Tabla PostgreSQL `agent_registry` y Agent Card A2A | API/UI de catálogo, clasificación de datos, owner aprobado, dependencias, capacidades MCP, estado y versionado de contratos |
| Registro | Inserción inicial de MCP y A2A en la tabla de catálogo; auditoría de autorización insert-only desde la aplicación (sin inmutabilidad WORM) | Registro de versiones, artefactos firmados, eventos de acceso a recursos y evidencia de aprobación |
| Ciclo de vida | Imágenes etiquetadas, healthchecks, `restart: unless-stopped` y volúmenes | CI/CD GitOps, promoción por ambientes, rollback, canary, revocación/retirada y gestión de tareas persistentes |
| Cumplimientos normativos | Controles técnicos de referencia y trazas/auditoría base | Matriz de controles y evidencias para la norma aplicable (p. ej., ISO 27001, SOC 2, privacidad local); esto no constituye certificación ni garantiza cumplimiento |

#### Notas 

- Este Compose usa Keycloak `start-dev`, Jaeger con almacenamiento en memoria e imágenes auxiliares con tag `latest` por defecto. Son decisiones para laboratorio, no para producción. Fija versiones/digests, genera lockfiles, usa Keycloak optimizado con HTTPS y un backend persistente de trazas antes de promover. La instrumentación Python inicializa un `TracerProvider` y exporta spans por OTLP al Collector.
- A2A usa `InMemoryTaskStore` como ejemplo funcional. Sustitúyelo por un task store persistente y define expiración, retención, aislamiento por tenant y límites de concurrencia.
- El servidor MCP aplica scopes mínimos y audiencia OAuth de ejemplo a nivel de conexión; OPA valida el `client_id` aprobado y el scope. Extiende las políticas y las herramientas con autorización por operación, recurso, tenant, rol y clasificación de datos.
- No registres prompts, tokens ni datos sensibles completos en auditoría. El esquema actual conserva actor, acción, decisión, trace ID y metadata acotada.
- La tabla de evaluaciones es solo un registro de resultados; aún no existe un motor de evaluación LLM conectado en este starter.
- Ajusta `MCP_PUBLIC_URL`, `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS`, `A2A_PUBLIC_URL`, `A2A_ALLOWED_ORIGINS` e `KEYCLOAK_ISSUER_URL` al dominio HTTPS de tu ingress en cada ambiente.

#### Operación

```bash
# Logs de un componente
docker compose logs -f mcp-server a2a-agent

# Consultar salud / configuración
docker compose ps
docker compose config

# Detener sin borrar datos
docker compose down
```

______________________

> CISO | oswaldo.diaz@inegi.org.mx 
