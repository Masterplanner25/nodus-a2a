# nodus-a2a

**A2A 1.0.0 (Linux Foundation) protocol adapter for the [Nodus](https://github.com/Masterplanner25/Nodus) scripting language.**

nodus-a2a exposes `std:tool`-registered tools from a Nodus runtime as an A2A
message-only agent over HTTP+JSON/REST.  It is the third artifact in the
coordinated launch with **nodus-lang 4.0.0** and **nodus-mcp 0.1.0**.

> **Status:** v0.1.0 — prepared, not yet published (three-artifact launch).

---

## Quick start

```python
from nodus.runtime.embedding import NodusRuntime
from nodus_a2a import A2AHttpServer, ServerConfig

# 1. Create a NodusRuntime and register tools
runtime = NodusRuntime()
runtime.register_tool(
    name="myapp.greet",
    description="Greet someone by name",
    handler=lambda args: f"Hello, {args.get('name', 'world')}!",
)

# 2. Configure the server
config = ServerConfig(
    base_url="https://myagent.example.com",
    agent_name="My Greeter Agent",
    agent_description="Greets people by name via A2A",
)

# 3. Build the tool list and start the server
tools = runtime.tool_registry.list_tools()
tool_names = [t["name"] for t in tools if not t.get("deprecated")]

server = A2AHttpServer(
    config=config,
    invoke=runtime.tool_registry.invoke,
    tool_names=tool_names,
    tools=tools,
)
server.serve()  # blocks; use serve_in_thread() for background use
```

### Calling the agent

Send a tool-call envelope in a DataPart:

```http
POST /message:send HTTP/1.1
Content-Type: application/a2a+json
A2A-Version: 1.0

{
  "message": {
    "messageId": "msg-001",
    "role": "ROLE_USER",
    "parts": [{"data": {"tool": "myapp.greet", "args": {"name": "Alice"}}}]
  }
}
```

Response:

```json
{
  "message": {
    "messageId": "...",
    "role": "ROLE_AGENT",
    "contextId": "...",
    "parts": [{"text": "Hello, Alice!", "mediaType": "text/plain"}]
  }
}
```

### Single-tool shortcut

If the agent has exactly one tool registered, any `Message` (even a plain `TextPart`)
dispatches to that tool with empty args:

```json
{"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "hello"}]}}
```

### Agent Card discovery

The Agent Card is served at `/.well-known/agent-card.json` (A2A 1.0 URI).
No authentication required.

---

## Authentication

```python
config = ServerConfig(
    ...
    token_validator=lambda token: token == "my-secret-token",
)
```

Without a `token_validator`, the server runs in dev mode and accepts all requests.
**Production deployments must configure a validator.**

---

## Part type dispatch

Tool return values are mapped to A2A Part variants automatically:

| Python type | A2A Part | `mediaType` |
|-------------|----------|-------------|
| `str` | TextPart | `text/plain` |
| `bytes` | RawPart (base64) | `application/octet-stream` |
| dict / list / int / float / bool / None | DataPart | `application/json` |

The `url` Part variant is not used in automatic dispatch (reserved for v0.2+).

---

## Error handling

Tool exceptions are returned as an error DataPart in an HTTP 200 response:

```json
{
  "message": {
    "role": "ROLE_AGENT",
    "parts": [{"data": {"error": "tool exploded", "type": "RuntimeError"},
               "mediaType": "application/json"}]
  }
}
```

Protocol errors (malformed JSON, invalid A2A-Version, missing auth) return
HTTP 4xx with a structured error body.

---

## Design notes

### v0.1 is message-only (D5)

The server never creates or persists A2A Tasks.  All task-management operations
(`GetTask`, `ListTasks`, `CancelTask`, streaming, push notifications) return
HTTP 501 `UnsupportedOperationError`.  The Agent Card declares:

```json
"capabilities": {"streaming": false, "pushNotifications": false, "extendedAgentCard": false}
```

### v0.2 Task lifecycle: D6 inversion warning

A2A `INPUT_REQUIRED` / `AUTH_REQUIRED` are **park-and-resume** states — the
opposite of nodus-mcp's no-thread-parks rule.  When implementing Task lifecycle
in v0.2, do **not** import the nodus-mcp no-park assertion.  See
`docs/design/05-deferred-features.md §2` for the full inversion note.

---

## CLI

```
python -m nodus_a2a --version
python -m nodus_a2a serve --name "My Agent" --description "..." --port 8080
```

The `serve` command starts a server with no tools — useful for smoke-testing
network connectivity and verifying the Agent Card format.

---

## Wire format

- **Spec:** A2A 1.0.0 / `lf.a2a.v1` (proto package)
- **Transport:** HTTP+JSON/REST only (`protocolBinding: "HTTP+JSON"`)
- **Content-Type:** `application/a2a+json`
- **Discovery:** `/.well-known/agent-card.json`
- **Version negotiation:** `A2A-Version` request header; mismatch → HTTP 400
- **Codec:** proto `snake_case` ↔ wire `camelCase` (ProtoJSON)
- **Signing:** unsigned (v0.1); JWS signing planned for v0.2

---

## Deferred features (v0.2+)

Task lifecycle and state machine, streaming (`SendStreamingMessage`),
push notification webhooks, Agent Card signing (JWS/RFC 7515), extended
authenticated card, JSON-RPC binding, gRPC binding, OAuth2/OIDC/mTLS,
tenant routing, 0.3 wire-dialect compatibility.

See `docs/design/05-deferred-features.md` for the full inventory.
