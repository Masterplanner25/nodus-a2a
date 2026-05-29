# 01 — Adapter Mapping: std:tool → AgentSkill / AgentCard

**Phase:** 1 (Design)
**Status:** Complete
**Depends on:** `00-decisions.md` (D1–D10 all settled)
**Bytecode impact:** None — zero new opcodes, BYTECODE_VERSION stays 4 (D2).

---

## 1. Protocol Audit (guilty-until-verified)

All 1.0 wire values treated as unverified until checked against
`specification/a2a.proto` (in `a2aproject/A2A`) and `docs/specification.md`.
Phase 0 had two stale references; both corrected here.

### 1.1 Findings table

| Wire value | Phase 0 assumption | Verified 1.0 value | Source | Status |
|------------|--------------------|--------------------|--------|--------|
| Repo location | `google/A2A` (implicit) | `a2aproject/A2A` | GitHub | CORRECTION |
| Proto path | `spec/a2a.proto` | `specification/a2a.proto` | Repo tree | CORRECTION |
| Proto package | `lf.a2a.v1` | `lf.a2a.v1` | Proto line 3 | CONFIRMED |
| Well-known URI | §14.3 (unknown) | `/.well-known/agent-card.json` | Spec §8.2 | RESOLVED |
| `agent.json` path | confirmed 0.3-era | absent from 1.0 spec | Spec §8.2 | CONFIRMED OUT |
| SendMessage REST path | `/message:send` | `POST /message:send` | Proto `google.api.http` | CONFIRMED |
| Protocol binding string | unknown | `"HTTP+JSON"` | `AgentInterface.protocol_binding` | RESOLVED |
| Protocol version string | `"1.0"` | `"1.0"` (in `AgentInterface.protocol_version`) | Proto field | CONFIRMED |
| Content-Type | `application/json` (assumed) | `application/a2a+json` | v1.0.1 patch #1753 | RESOLVED (adopt) |
| Part type discriminator | no `kind` field (D4b) | `oneof content {text, raw, url, data}` — no `kind` | Proto `Part` | CONFIRMED |
| SendMessageResponse shape | `oneof {Task, Message}` | `oneof payload {Task task=1; Message message=2;}` | Proto line 780 | CONFIRMED |
| `AgentCapabilities.streaming` | `optional bool` | `optional bool streaming = 1` | Proto line 413 | CONFIRMED |
| `AgentCapabilities.push_notifications` | `optional bool` | `optional bool push_notifications = 2` | Proto line 415 | CONFIRMED |
| `AgentCapabilities.extended_agent_card` | `optional bool` | `optional bool extended_agent_card = 4` | Proto line 419 | CONFIRMED |

### 1.2 Version note: v1.0.1 (2026-05-28, patch)

Three spec bugs fixed; no breaking changes:

1. **Content-Type:** prefer `application/a2a+json` over `application/json`. We adopt
   this immediately — it's a required header, not optional.
2. Transcoding error changes (affect task operations — all deferred under D10).
3. `TaskStatus` value fixes (affect task operations — all deferred under D10).

D4a pin updated from "1.0.0" to "≥1.0.0, <2.0.0". Wire dialect stays 1.0
(that's the `A2A-Version` header value, unchanged by the patch).

### 1.3 Deferred values (not needed for v0.1)

JSON-RPC method strings (§9.4): D7 scopes v0.1 to HTTP+JSON/REST only. The REST
path set is fully resolved above. JSON-RPC strings are load-bearing only if the
JSON-RPC binding is pulled forward from its v0.1-stretch / v0.2 slot.

### 1.4 Audit summary

All values needed for v0.1 are now resolved. No open wire values block Phase 1
design or Phase A–J implementation.

---

## 2. std:tool → AgentSkill Projection

### 2.1 Source: std:tool registry entry

A `std:tool` registration in nodus-lang provides:

```python
{
    "name": str,          # tool identifier (e.g. "search", "calculate")
    "description": str,   # human-readable description
    "parameters": dict,   # JSON Schema for input (used for Nodus dispatch only)
    "handler": callable,  # the Python function
    # optional:
    "tags": list[str],    # capability keywords
    "examples": list[str],# example invocations
}
```

### 2.2 Projection rules: std:tool → AgentSkill

```
AgentSkill.id          ←  tool["name"]
AgentSkill.name        ←  tool["name"]   (human-readable; same as id for now)
AgentSkill.description ←  tool["description"]
AgentSkill.tags        ←  tool.get("tags", [tool["name"]])
                          # fallback: single-element list containing the tool name
AgentSkill.examples    ←  tool.get("examples", [])
AgentSkill.input_modes ←  []   # inherit from AgentCard.default_input_modes
AgentSkill.output_modes←  []   # inherit from AgentCard.default_output_modes
```

`AgentSkill.security_requirements` is left empty; security is declared at the card
level (D9: bearer token in `AgentCard.security_schemes`).

### 2.3 Design constraint

The projection is intentionally lossy on `parameters` — A2A's AgentSkill has no
parameter schema field. The std:tool parameter schema is used only by the Nodus
dispatch layer, not exposed to the A2A wire. This is correct: A2A is a message-passing
protocol; the client sends a free-form `Message`, not a typed parameter object.

---

## 3. std:tool Registry → AgentCard Projection

### 3.1 Assembly rules

The Agent Card is assembled once at startup from:
- Runtime metadata (configured by the operator)
- The `std:tool` registry (iterating all registered tools → AgentSkill list)

```
AgentCard.name               ←  config["agent_name"]       (required; operator-supplied)
AgentCard.description        ←  config["agent_description"] (required; operator-supplied)
AgentCard.version            ←  nodus_a2a.__version__       ("0.1.0")
AgentCard.documentation_url  ←  config.get("documentation_url")  (optional)
AgentCard.icon_url           ←  config.get("icon_url")           (optional)
AgentCard.provider           ←  AgentProvider {
                                    url = config.get("provider_url", ""),
                                    organization = config.get("provider_org", "")
                                }
AgentCard.supported_interfaces ← [AgentInterface {
                                    url = config["base_url"],   # e.g. "https://myagent.example.com"
                                    protocol_binding = "HTTP+JSON",
                                    tenant = "",                # single-agent deployment
                                    protocol_version = "1.0"
                                }]
AgentCard.capabilities       ←  AgentCapabilities {
                                    streaming = False,          # D5
                                    push_notifications = False, # D10
                                    extended_agent_card = False,# D8b
                                    extensions = []
                                }
AgentCard.security_schemes   ←  {"bearer": SecurityScheme {
                                    http_auth_security_scheme = HTTPAuthSecurityScheme {
                                        scheme = "Bearer",
                                        description = "Bearer token authentication"
                                    }
                                }}
AgentCard.security_requirements ← [SecurityRequirement {schemes: {"bearer": []}}]
AgentCard.default_input_modes  ← ["text/plain", "application/json"]
AgentCard.default_output_modes ← ["text/plain", "application/json"]
AgentCard.skills               ← [project_tool(t) for t in tool_registry.all()]
AgentCard.signatures           ← []   # D8a: unsigned for v0.1
```

### 3.2 AgentCard lifecycle

- Built once at server startup; **not rebuilt per request**.
- Cached as an immutable dict (the JSON-serialized camelCase form — see §4).
- Served as-is at `GET /.well-known/agent-card.json` with
  `Content-Type: application/a2a+json`.
- If the tool registry changes (dynamic tool registration), the server must be
  restarted. Dynamic card refresh is a v0.2 concern.

### 3.3 `AgentCard.supported_interfaces` ordering

Spec §8.3.1: first entry is preferred. v0.1 has exactly one interface (HTTP+JSON),
so ordering is trivial. v0.2 (if JSON-RPC is added) would prepend the preferred
binding as a second entry.

---

## 4. Codec: Proto snake_case ↔ Wire camelCase

### 4.1 Rule

All proto field names use `snake_case`. All A2A JSON wire values use `camelCase`
per spec §5.5 (ProtoJSON name mapping). The codec layer MUST translate every field
name crossing the wire boundary. Proto field names must never appear unmapped on the
wire. This is covered by the `codec-name-mapping` standing assertion.

### 4.2 Canonical mapping table (fields relevant to v0.1)

| Proto (snake_case) | Wire JSON (camelCase) | Message |
|--------------------|-----------------------|---------|
| `message_id` | `messageId` | Message |
| `context_id` | `contextId` | Message, Task |
| `task_id` | `taskId` | Message |
| `role` | `role` | Message |
| `parts` | `parts` | Message |
| `reference_task_ids` | `referenceTaskIds` | Message |
| `media_type` | `mediaType` | Part |
| `supported_interfaces` | `supportedInterfaces` | AgentCard |
| `protocol_binding` | `protocolBinding` | AgentInterface |
| `protocol_version` | `protocolVersion` | AgentInterface |
| `default_input_modes` | `defaultInputModes` | AgentCard |
| `default_output_modes` | `defaultOutputModes` | AgentCard |
| `security_schemes` | `securitySchemes` | AgentCard |
| `security_requirements` | `securityRequirements` | AgentCard, AgentSkill |
| `push_notifications` | `pushNotifications` | AgentCapabilities |
| `extended_agent_card` | `extendedAgentCard` | AgentCapabilities |
| `http_auth_security_scheme` | `httpAuthSecurityScheme` | SecurityScheme |
| `bearer_format` | `bearerFormat` | HTTPAuthSecurityScheme |
| `input_modes` | `inputModes` | AgentSkill |
| `output_modes` | `outputModes` | AgentSkill |
| `accepted_output_modes` | `acceptedOutputModes` | SendMessageConfiguration |
| `return_immediately` | `returnImmediately` | SendMessageConfiguration |

### 4.3 Implementation approach

Use a recursive `snake_to_camel` pass on dict output before serialization, and a
`camel_to_snake` pass on dict input after deserialization. Do NOT hand-code field
names on the wire — always go through the codec. This ensures the standing assertion
can be enforced mechanically (deserialize → re-serialize → compare).

The ProtoJSON rules for the `oneof` fields in `SendMessageResponse` and `Part`:
- `oneof payload { Task task; Message message; }` — the JSON key is the field name
  of whichever variant is set: `{"task": ...}` or `{"message": ...}`.
- `oneof content { string text; bytes raw; string url; Value data; }` — similarly:
  `{"text": "..."}` or `{"raw": "..."}` (base64) or `{"url": "..."}` or `{"data": ...}`.
  In both cases camelCase applies to the field name (all are already camelCase here).

### 4.4 `bytes raw` encoding

`Part.raw` is `bytes` in proto. In ProtoJSON, `bytes` fields are base64-encoded
strings (standard base64, not URL-safe). The codec must encode on serialization and
decode on deserialization. `filename` and `media_type` provide the hint for clients.

---

## 5. Bytecode Impact

None. The entire adapter mapping runs in Python host code. `std:tool` handlers are
invoked via the existing `NodusRuntime.call_tool()` path — no new opcodes, no VM
changes, BYTECODE_VERSION stays 4. (D2 standing assertion.)

---

## 6. Standing Assertions Touched by This Doc

| Assertion | How this doc satisfies it |
|-----------|--------------------------|
| `no-new-opcodes` | §5 confirms zero VM change |
| `no-task-emitted` | Response path: AgentCard serving + SendMessage always return Message, never Task |
| `no-kind-discriminator` | §4.3: oneof content has no `kind` field; codec never adds one |
| `no-legacy-wellknown` | §1.1 audit: `agent.json` confirmed absent; only `agent-card.json` served |
| `codec-name-mapping` | §4.1–4.3: mechanical camelCase translation on every wire boundary |
| `capability-honesty` | §3.1: streaming/push/extended-card all `False` in card assembly |

---

## 7. Open Questions for Later Phases

None blocking Phase 1. The following are noted for implementation docs:

- **Phase D (transport):** decide whether to use `http.server` or a lightweight ASGI
  framework (FastAPI / Starlette). The routing surface is small (two endpoints for v0.1:
  `POST /message:send` and `GET /.well-known/agent-card.json`).
- **Phase C (SendMessage handler):** confirm Part variant dispatch order — proto
  `oneof` does not imply priority; the handler should inspect whichever field is set
  (text/raw/url/data) and route accordingly.
- **Phase A (foundation):** decide whether to use `betterproto` for proto-to-Python
  generation or hand-write the data classes. Hand-written dataclasses are lighter and
  avoid a code-gen step; the message surface for v0.1 is small enough to do this safely.
