# 03 — Transport: HTTP+JSON/REST Binding

**Phase:** 1 (Design)
**Status:** Complete
**Depends on:** `00-decisions.md` (D4, D7, D9), `01-adapter-mapping.md` (REST paths, Content-Type), `02-message-model.md` (codec, error types)
**Bytecode impact:** None — BYTECODE_VERSION stays 4 (D2).

---

## 1. Overview

This doc specifies the HTTP+JSON/REST transport layer for v0.1:
request routing, Content-Type handling, bearer auth wiring, `A2A-Version`
negotiation, error response format, and framework choice.

v0.1 has exactly two HTTP endpoints:

| Method | Path | Handler | Phase |
|--------|------|---------|-------|
| `POST` | `/message:send` | `SendMessage` | C (handler) |
| `GET` | `/.well-known/agent-card.json` | Discovery | E (discovery) |

All other operations (task ops, streaming, push, extended card) return
`UnsupportedOperationError` per D10. The transport layer is responsible for
routing them to a shared "unsupported" handler rather than 404ing.

---

## 2. Framework Choice

**Decision: use Python's `http.server` + manual routing for v0.1, or a minimal
ASGI framework.**

Evaluation:

| Option | Weight | Notes |
|--------|--------|-------|
| `http.server.BaseHTTPRequestHandler` | Light, stdlib | Single-threaded; fine for a library, not for production server use |
| `wsgiref.simple_server` | Light, stdlib | Also single-threaded |
| FastAPI / Starlette | ~5 MB, ASGI | Async, production-grade, OpenAPI docs auto-generated (irrelevant here), routing is trivial |
| Flask | ~3 MB, WSGI | Sync; well-known; route registration is 2 lines |

**Recommendation: Flask.** Rationale:
- The routing surface is 2 endpoints (v0.1). Flask adds no meaningful abstraction overhead.
- Flask is already in the nodus-lang venv (used by nodus-mcp Phase G). Reuses existing
  dependency, no new install.
- Sync is fine: std:tool handlers are synchronous; the message-only path is
  request-response with no blocking. Async (Starlette/FastAPI) buys nothing here.
- Does NOT add FastAPI's Pydantic/OpenAPI machinery — that's unnecessary weight.

**Confirmed in Phase D implementation:** use Flask. If the venv does NOT have Flask,
fall back to `http.server.ThreadingHTTPServer` (stdlib, avoids the dependency).
Phase D resolves this by checking the venv.

---

## 3. Request/Response Format

### 3.1 Content-Type

All requests and responses use `Content-Type: application/a2a+json` (v1.0.1 §,
adopted in doc 01 §1.2). The server:

- On inbound request: accepts `application/a2a+json` and `application/json` (for
  client compatibility). Neither is required in v0.1 — parse any body that is valid
  JSON.
- On all responses: always set `Content-Type: application/a2a+json`.

### 3.2 Request parsing

```python
def parse_body(request_body: bytes) -> dict:
    try:
        return json.loads(request_body)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}")
```

The parsed dict is then passed through the camelCase → snake_case codec and
deserialized into `SendMessageRequest` (doc 02 §5).

### 3.3 Response serialization

```python
def make_response(payload: dict, status: int = 200) -> tuple[dict, int]:
    body = json.dumps(payload, ensure_ascii=False)
    return body, status
```

All 2xx responses use status 200.

---

## 4. `A2A-Version` Negotiation

### 4.1 Spec requirement

Spec §3.6.1: clients MUST send `A2A-Version` header. Spec §3.6.2: servers must
reject unsupported versions with `VersionNotSupportedError`.

v0.1 supports exactly one version: `"1.0"`.

### 4.2 Negotiation algorithm

```python
SUPPORTED_VERSION = "1.0"

def negotiate_version(headers: dict) -> None:
    version = headers.get("A2A-Version") or headers.get("a2a-version")
    if version is None:
        # Spec says MUST send; be lenient on missing header in v0.1
        # (many clients in the wild may not yet send it)
        return
    # Match on Major.Minor only (ignore patch)
    major_minor = ".".join(version.split(".")[:2])
    if major_minor != SUPPORTED_VERSION:
        raise VersionNotSupportedError(
            f"A2A version '{version}' is not supported. "
            f"This server supports {SUPPORTED_VERSION}."
        )
```

**Leniency on missing header:** the spec says MUST, but silently accepting requests
without the header is safer for initial deployment. Log a warning. This matches
common practice in early adopters and can be tightened in v0.2.

**Match on Major.Minor:** a client sending `"1.0.1"` should be accepted — patch
versions within the same major.minor are compatible. Split on `.`, take first two
components, join as `"1.0"`.

### 4.3 `VersionNotSupportedError` wire format

The spec defines A2A-specific errors (§3.3.2) but delegates error format to each
binding. For HTTP+JSON/REST (spec §11.6 — extrapolated from spec structure):

```json
{
  "error": {
    "code": "VERSION_NOT_SUPPORTED",
    "message": "A2A version '0.3' is not supported. This server supports 1.0.",
    "details": []
  }
}
```

HTTP status: **400 Bad Request**.

---

## 5. Bearer Auth Wiring

### 5.1 Token extraction

```python
def extract_bearer_token(headers: dict) -> str | None:
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth and auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return None
```

### 5.2 Auth enforcement

The server operator provides an optional `token_validator` callable:

```python
def validate_auth(
    token: str | None,
    validator: Callable[[str], bool] | None,
) -> None:
    if validator is None:
        return  # auth not configured; allow all (dev mode)
    if token is None:
        raise AuthError("Authorization header required")
    if not validator(token):
        raise AuthError("Invalid or expired bearer token")
```

**Auth not configured → allow all:** this is intentional for dev/local use. Production
deployments MUST pass a `token_validator`. The README must call this out prominently.

### 5.3 `AuthError` wire format

HTTP status: **401 Unauthorized** with `WWW-Authenticate: Bearer` header.

```json
{
  "error": {
    "code": "AUTHENTICATION_REQUIRED",
    "message": "Authorization header required",
    "details": []
  }
}
```

---

## 6. Error Response Format

### 6.1 Canonical error shape

All errors use the same envelope:

```json
{
  "error": {
    "code": "<ErrorCode>",
    "message": "<human-readable string>",
    "details": []
  }
}
```

`details` is always an empty array in v0.1 (no structured error details). v0.2 can
populate it with `google.rpc` types (`ErrorInfo`, `BadRequest`, etc.).

### 6.2 Error code → HTTP status mapping

| Python exception | Error code | HTTP status |
|------------------|------------|-------------|
| `VersionNotSupportedError` | `VERSION_NOT_SUPPORTED` | 400 |
| `ParseError` | `INVALID_ARGUMENT` | 400 |
| `ValidationError` | `INVALID_ARGUMENT` | 400 |
| `AuthError` | `AUTHENTICATION_REQUIRED` | 401 |
| `UnsupportedOperationError` | `UNSUPPORTED_OPERATION` | 501 |
| `ToolNotFoundError` | `NOT_FOUND` | 404 |
| Unhandled Python exception | `INTERNAL` | 500 |

### 6.3 `UnsupportedOperationError` for deferred operations

Any request to a task-management path (D10) or a path not in the v0.1 routing table
returns `UnsupportedOperationError` with HTTP 501. The routing table does NOT 404
these — the spec names `UnsupportedOperationError` specifically for this case.

Paths that must return `UnsupportedOperationError`:
- `GET /tasks/{id}`, `GET /tasks`, `POST /tasks/{id}:cancel`,
  `GET /tasks/{id}:subscribe`, `POST /tasks/{task_id}/pushNotificationConfigs`,
  and variants.
- `GET /extendedAgentCard` (D8b).
- `POST /message:stream` (deferred streaming).

Implementation: a single catch-all route in the Flask app handles all of these
with a `UnsupportedOperationError` response.

---

## 7. Request Lifecycle

Full lifecycle for `POST /message:send`:

```
1. Extract A2A-Version header → negotiate_version()
2. Extract Authorization header → extract_bearer_token() → validate_auth()
3. Read request body → parse_body()
4. camelCase → snake_case codec → build SendMessageRequest
5. Validate Message (message_id, role, parts) → ValidationError if invalid
6. Invoke tool handler (Phase C detail)
7. Dispatch tool result to Part → build response Message
8. Encode response Message → {"message": {camelCase dict}}
9. Return HTTP 200 with body, Content-Type: application/a2a+json
```

Steps 1–3 are transport concerns (this doc). Steps 4–8 are message/handler concerns
(docs 02 and the Phase C design). Step 9 returns to transport.

---

## 8. Server Configuration

The server is configured at construction time:

```python
@dataclass
class ServerConfig:
    base_url: str              # e.g. "https://myagent.example.com"
    agent_name: str
    agent_description: str
    agent_version: str = "0.1.0"
    token_validator: Callable[[str], bool] | None = None
    provider_url: str = ""
    provider_org: str = ""
    documentation_url: str | None = None
    icon_url: str | None = None
    host: str = "0.0.0.0"
    port: int = 8080
```

This config feeds:
- AgentCard assembly (doc 01 §3.1): `base_url`, `agent_name`, `agent_description`,
  `agent_version`, `provider_url`, `provider_org`, `documentation_url`, `icon_url`.
- Auth wiring (§5.2): `token_validator`.
- HTTP server binding: `host`, `port`.

---

## 9. Bytecode Impact

None. All transport handling is Python host code. BYTECODE_VERSION stays 4.

---

## 10. Standing Assertions Touched by This Doc

| Assertion | How this doc satisfies it |
|-----------|--------------------------|
| `no-task-emitted` | §6.3: task paths return `UnsupportedOperationError`, not a Task |
| `version-negotiation` | §4.2: `A2A-Version` header parsed; mismatch → `VersionNotSupportedError` |
| `capability-honesty` | §6.3: `/message:stream` and task paths all return 501; no capability advertised as available that isn't |

---

## 11. Open Questions for Phase D

- **Flask vs. stdlib:** confirm Flask is in the shared venv before Phase D starts.
  If not, use `http.server.ThreadingHTTPServer` with manual routing.
- **HTTPS enforcement:** the spec says base URL "MUST be a valid absolute HTTPS URL
  in production." In v0.1 dev mode, HTTP is acceptable for local testing. The server
  does not enforce HTTPS at the Python level; TLS termination is the operator's
  responsibility (reverse proxy). Document this in README.
- **Thread safety of the tool registry:** Flask's dev server is single-threaded.
  If `ThreadingHTTPServer` is used, confirm the std:tool registry is read-only after
  startup (no concurrent writes). It is — tool registration happens at import time,
  not during request handling.
