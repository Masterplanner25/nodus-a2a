# 04 — Discovery: Agent Card Assembly and Well-Known URI

**Phase:** 1 (Design)
**Status:** Complete
**Depends on:** `00-decisions.md` (D8, D9), `01-adapter-mapping.md` (AgentCard assembly rules, codec), `03-transport-http.md` (HTTP serving, Content-Type)
**Bytecode impact:** None — BYTECODE_VERSION stays 4 (D2).

---

## 1. Overview

This doc specifies how the Agent Card is assembled from config and the `std:tool`
registry, serialized to JSON, cached, and served at the 1.0 well-known URI.

**Verified wire value (doc 01 §1.1):**
- Well-known URI: `/.well-known/agent-card.json`
- Not `/.well-known/agent.json` — that is the 0.3-era path (standing assertion
  `no-legacy-wellknown`)

---

## 2. Agent Card Assembly

### 2.1 Full field mapping (authoritative)

This is the canonical assembly spec, combining doc 01 §3.1 with the codec from doc
01 §4 applied:

```python
def build_agent_card(
    config: ServerConfig,
    tool_registry: ToolRegistry,
) -> dict:
    """Returns the wire-ready camelCase JSON dict. Built once at startup."""
    skills = [project_skill(t) for t in tool_registry.all()]
    return {
        "name": config.agent_name,
        "description": config.agent_description,
        "version": config.agent_version,
        "supportedInterfaces": [
            {
                "url": config.base_url,
                "protocolBinding": "HTTP+JSON",
                "tenant": "",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "securitySchemes": {
            "bearer": {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer",
                    "description": "Bearer token authentication",
                }
            }
        },
        "securityRequirements": [{"bearer": []}],
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": skills,
        # Optional fields — omit when not configured:
        **({"provider": {
               "url": config.provider_url,
               "organization": config.provider_org,
           }} if config.provider_url or config.provider_org else {}),
        **({"documentationUrl": config.documentation_url}
           if config.documentation_url else {}),
        **({"iconUrl": config.icon_url}
           if config.icon_url else {}),
        "signatures": [],   # D8a: unsigned for v0.1
    }
```

### 2.2 AgentSkill assembly

```python
def project_skill(tool: ToolEntry) -> dict:
    """Projects a std:tool registry entry to an AgentSkill wire dict."""
    return {
        "id": tool.name,
        "name": tool.name,
        "description": tool.description,
        "tags": tool.tags if tool.tags else [tool.name],
        **({"examples": tool.examples} if tool.examples else {}),
        # inputModes/outputModes omitted → inherit from AgentCard defaults
    }
```

`securityRequirements` is omitted from the skill — security is declared at the card
level (D9). An empty list and an absent list are equivalent in ProtoJSON; omit for
compactness.

### 2.3 Capabilities field notes

- `capabilities.streaming: false` — `SendStreamingMessage` is not supported (D5).
- `capabilities.pushNotifications: false` — push notification config ops not
  supported (D10).
- `capabilities.extendedAgentCard: false` — authenticated extended card not served
  (D8b). Corollary: `GET /extendedAgentCard` returns `UnsupportedOperationError`
  (doc 03 §6.3).

Setting any of these to `true` without implementation is a violation of the
`capability-honesty` standing assertion. The test for this assertion reads the served
card and checks all three.

### 2.4 `securityRequirements` format

The wire format is a list of objects, each a map from scheme-name to scope-list:

```json
"securityRequirements": [{"bearer": []}]
```

An empty scope list `[]` means "any valid bearer token" — no specific scopes required.
This is the correct v0.1 semantics (token is valid or it isn't; no OAuth scope
infrastructure exists).

### 2.5 `signatures` field

`signatures: []` in v0.1 (D8a — card signing deferred). The field is included (as
empty array) rather than omitted so clients that expect the field don't get a
deserialization error. The `AgentCardSignature` message (JWS per RFC 7515) is a v0.2
concern.

---

## 3. Card Caching

### 3.1 Build-once at startup

The Agent Card is assembled once at server startup by calling `build_agent_card()`.
The result is stored as:
1. A Python dict (for in-process use).
2. A serialized JSON bytes object (`json.dumps(card).encode("utf-8")`) — cached for
   direct serving without re-serialization per request.

```python
class A2AServer:
    def __init__(self, config: ServerConfig, tool_registry: ToolRegistry):
        self._card_dict = build_agent_card(config, tool_registry)
        self._card_bytes = json.dumps(
            self._card_dict, ensure_ascii=False
        ).encode("utf-8")
```

### 3.2 No dynamic refresh

If the tool registry changes after server start (dynamic tool registration), the
cached card becomes stale. v0.1 does not support dynamic refresh — a server restart
is required. This is an acceptable constraint for a library targeting script-execution
use cases. Dynamic refresh is a v0.2 concern.

### 3.3 Caching headers

The spec §8.6 gives guidance on caching. v0.1 serves the card with:

```
Cache-Control: public, max-age=3600
```

One hour is a reasonable default — the card rarely changes (restart-only). Operators
who need shorter TTLs can configure a reverse proxy.

---

## 4. Well-Known URI Handler

### 4.1 Route

```
GET /.well-known/agent-card.json
```

No authentication required — the public Agent Card is unauthenticated per spec §8.
The `A2A-Version` header is NOT required for this endpoint — discovery is a
pre-negotiation step.

### 4.2 Handler

```python
def handle_agent_card(server: A2AServer) -> tuple[bytes, int, dict]:
    """Returns (body, status, headers)."""
    headers = {
        "Content-Type": "application/a2a+json",
        "Cache-Control": "public, max-age=3600",
    }
    return server._card_bytes, 200, headers
```

### 4.3 Method enforcement

Only `GET` is accepted at this path. `POST`, `PUT`, `DELETE`, etc. → 405 Method Not
Allowed with `Allow: GET`.

### 4.4 The `no-legacy-wellknown` assertion

The `no-legacy-wellknown` standing assertion requires that `GET /.well-known/agent.json`
is NOT served. The test for this assertion:

```python
def test_legacy_wellknown_not_served(client):
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code in (404, 405)
    # Must not return 200 with a card body
```

The server routing table must not register `/.well-known/agent.json`. A 404 is correct.

---

## 5. `AgentInterface.tenant` (v0.1: always empty)

`AgentInterface.tenant` is an optional opaque routing identifier for multi-agent
deployments behind a single endpoint. v0.1 is a single-agent deployment; tenant is
always `""`. The tenant-scoped REST paths (`/{tenant}/message:send` etc.) are not
registered in the v0.1 routing table. They return `UnsupportedOperationError` via the
catch-all route (doc 03 §6.3). Doc 05 records this as a named deferred feature.

---

## 6. `GetExtendedAgentCard` (v0.1: deferred)

`GET /extendedAgentCard` is defined in the proto and provides an authenticated,
potentially richer card. Deferred per D8b (`capabilities.extendedAgentCard = false`).
The handler returns `UnsupportedOperationError` (HTTP 501). The `no-legacy-wellknown`
assertion does not cover this path; the `capability-honesty` assertion does
(extendedAgentCard advertised false → any request that succeeds would be a violation).

---

## 7. Card JSON Completeness Checklist

Before Phase E implementation, verify the assembled card satisfies these spec §8
requirements:

- [ ] `name` present and non-empty
- [ ] `description` present and non-empty
- [ ] `supportedInterfaces` non-empty; first entry is preferred
- [ ] Each `AgentInterface` has `url` (HTTPS in prod), `protocolBinding`, `protocolVersion`
- [ ] `capabilities` present (required field)
- [ ] `defaultInputModes` non-empty
- [ ] `defaultOutputModes` non-empty
- [ ] `skills` non-empty (at least one tool registered)
- [ ] `securityRequirements` matches scheme names in `securitySchemes`
- [ ] No `kind` fields anywhere in the output

---

## 8. Bytecode Impact

None. Card assembly, caching, and HTTP serving are all Python host code.
BYTECODE_VERSION stays 4.

---

## 9. Standing Assertions Touched by This Doc

| Assertion | How this doc satisfies it |
|-----------|--------------------------|
| `no-legacy-wellknown` | §4.4: `agent.json` not registered; test explicitly checks 404 |
| `capability-honesty` | §2.3: streaming/push/extended all `False` in assembled card |
| `codec-name-mapping` | §2.1: all AgentCard fields output in camelCase; no snake_case on wire |
| `no-kind-discriminator` | §7 checklist item: verify no `kind` in card output |
