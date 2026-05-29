# 05 — Deferred Features and the D6 Inversion

**Phase:** 1 (Design)
**Status:** Complete
**Depends on:** `00-decisions.md` (D4–D10), all other Phase 1 docs
**Bytecode impact:** None — BYTECODE_VERSION stays 4 (D2).

---

## 1. Purpose of This Document

Phase 0 made explicit deferral decisions for every feature that is not in the v0.1
message-only scope. This document is the authoritative record of what is deferred,
why, and — critically — what must NOT be silently suppressed when v0.2 implements it.

**The D6 inversion note is the most important entry in this document.** Read §2
before anything else.

---

## 2. D6 — The Inversion: `input-required` and Park-and-Resume

### 2.1 What the inversion is

nodus-mcp established a `test_l_no_thread_parks` standing assertion: MCP's stateless
call model forbids thread parking. That assertion was correct for mcp.

**It is WRONG for A2A.** Do not import it.

A2A's `TASK_STATE_INPUT_REQUIRED` and `TASK_STATE_AUTH_REQUIRED` are explicitly
*interrupted states*. A task in `INPUT_REQUIRED` is parked — it persists, waits for
the client to send a follow-up Message with the same `task_id`, and then resumes. This
is park-and-resume by design. The spec models it as a first-class task lifecycle
state, not an error or workaround.

The full task lifecycle (from `00-decisions.md` D6, repeated here for permanence):

```
SUBMITTED → WORKING → COMPLETED (terminal)
                    → FAILED (terminal)
                    → CANCELED (terminal)
                    → REJECTED (terminal)
                    → INPUT_REQUIRED (interrupted — waits for client Message)
                    → AUTH_REQUIRED  (interrupted — waits for auth)
```

An interrupted task resumes when the client sends `SendMessage` with the same
`task_id`. The server retrieves the parked task, provides the requested input, and
the task transitions back to WORKING.

### 2.2 Why v0.1 does not exercise this

D5 (message-only archetype) means the server never creates a Task. No Task → no
`INPUT_REQUIRED` → no park-and-resume. The inversion is latent in v0.1 and fully
deferred to v0.2 (Task lifecycle).

### 2.3 The load-bearing warning for v0.2

When v0.2 implements Task lifecycle:

1. **Do NOT add a `test_l_no_thread_parks` assertion** or any analog. Parking IS
   the implementation. The correct v0.2 behavior is to park the coroutine / suspend
   the task state machine until `INPUT_REQUIRED` is resolved.
2. **Do NOT inherit the mcp-side assumption that all tool calls are one-shot.** A2A
   tasks may make multiple round-trips. The tool handler must be able to yield control,
   persist state, and resume.
3. The v0.2 Task store must be thread-safe and durable enough to survive
   `INPUT_REQUIRED` across multiple HTTP requests (not just within a single connection).
4. `blocking-by-default` applies to task-generating responses: `return_immediately`
   defaults to `false`, meaning a standard `SendMessage` that creates a Task will block
   until the task reaches terminal or interrupted state. This is NOT a concern for
   message-only (D5), but IS the default for task-generating v0.2.

### 2.4 The `inversion-note` standing assertion

The eighth standing assertion (`inversion-note`) is a documentation assertion: it
passes if and only if this section exists and records the inversion. The test is:

```python
def test_inversion_note_documented():
    """D6 inversion must be recorded in 05-deferred-features.md."""
    doc = Path("docs/design/05-deferred-features.md").read_text()
    assert "INPUT_REQUIRED" in doc
    assert "no_thread_parks" in doc or "no-thread-parks" in doc or "park" in doc
    assert "inversion" in doc.lower()
```

This test never expires — it is as permanent as `test_no_new_opcodes`.

---

## 3. Deferred Feature Inventory

### 3.1 Task lifecycle (v0.2 — consequence of D5/D6/D10)

| Feature | Why deferred | v0.2 entry point |
|---------|-------------|-----------------|
| Task creation (`SendMessage` returning Task) | D5: message-only | Change `SendMessageResponse` to emit Task |
| Task state machine (SUBMITTED → WORKING → …) | D5 | TaskState enum + state transition table |
| `INPUT_REQUIRED` / park-and-resume | D6 inversion | See §2 — do NOT suppress |
| `AUTH_REQUIRED` | D6 inversion | Same — park-and-resume with auth challenge |
| Task store | D10 | Persistent store keyed by `task_id` |
| `GetTask` (`GET /tasks/{id}`) | D10 | Phase D10 transport + task store |
| `ListTasks` (`GET /tasks`) | D10 | Phase D10 + pagination |
| `CancelTask` (`POST /tasks/{id}:cancel`) | D10 | Phase D10 |
| Task history (`Message[]` on Task) | D10 | Part of task store |
| Task artifacts (`Artifact[]` on Task) | D10 | Part of task store |
| `contextId` across multiple Tasks | D10 | Linked by `context_id` in task store |

`UnsupportedOperationError` returned in v0.1 for all task operation paths (doc 03 §6.3).

### 3.2 Streaming and SSE (v0.2)

| Feature | Why deferred | v0.2 entry point |
|---------|-------------|-----------------|
| `SendStreamingMessage` (`POST /message:stream`) | D5 | New handler returning SSE stream |
| `SubscribeToTask` (`GET /tasks/{id}:subscribe`) | D5 + D10 | SSE on task state changes |
| `StreamResponse` oneof (Task / Message / StatusUpdate / ArtifactUpdate) | D5 | New response type |

`capabilities.streaming = false` in v0.1 card (capability-honesty).

### 3.3 Push notifications (v0.2)

| Feature | Why deferred | v0.2 entry point |
|---------|-------------|-----------------|
| `CreateTaskPushNotificationConfig` | D10 | Webhook registration |
| `GetTaskPushNotificationConfig` | D10 | Webhook retrieval |
| `ListTaskPushNotificationConfigs` | D10 | Webhook listing |
| `DeleteTaskPushNotificationConfig` | D10 | Webhook deletion |
| Outbound webhook delivery | D10 | Server-initiated HTTP POST to client URL |

`capabilities.pushNotifications = false` in v0.1 card.

### 3.4 Agent Card signing (v0.2 — D8a)

`AgentCardSignature` (JWS / RFC 7515): unsigned in v0.1 (`signatures: []`). v0.2
populates `signatures` with at least one JWS signature over the card JSON.

Key management, key rotation, and the `AgentCardSignature.protected` header format
are v0.2 design questions. Do not pre-solve them in v0.1.

### 3.5 Extended / authenticated Agent Card (v0.2 — D8b)

`GET /extendedAgentCard`: returns `UnsupportedOperationError` in v0.1.
`capabilities.extendedAgentCard = false`.

v0.2: implement `GetExtendedAgentCard` behind auth (bearer token) returning a
potentially richer card (additional skills, private endpoints). Requires the extended
card content to be defined (v0.2 design).

### 3.6 JSON-RPC binding (v0.1-stretch / v0.2 — D7)

| Feature | Why deferred | Notes |
|---------|-------------|-------|
| JSON-RPC method strings (§9.4) | Not needed for HTTP+REST | Near-zero marginal cost once transport layer exists |
| `jsonrpc: "2.0"` envelope | D7 | Same payloads, different envelope |

When implemented: the same `SendMessage` handler and AgentCard serving work; only
the request envelope and response envelope change. The method string for `SendMessage`
in JSON-RPC 1.0 must be verified from §9.4 (not assumed from 0.3) — guilty-until-verified,
same audit discipline as doc 01.

### 3.7 gRPC binding (v0.2 — D7)

OUT for v0.1. `buf.gen.yaml` (proto code generation) in `a2aproject/A2A` provides
the toolchain. Adds a dependency on `grpcio`. Not worth the weight for v0.1.

### 3.8 OAuth2 / OIDC / mTLS auth (v0.2 — D9)

Only bearer token in v0.1. The proto's `SecurityScheme` oneof supports all five
schemes; the `AgentCard.securitySchemes` map can declare any. v0.2 design question:
which OAuth flow (Authorization Code + PKCE is recommended by the proto comments;
Device Code for CLI use cases).

### 3.9 Richer auth: accepted_output_modes transcoding (v0.2)

The `SendMessageConfiguration.accepted_output_modes` field is parsed in v0.1 but
ignored (doc 02 §3.2). v0.2 should honor it by transcoding the tool result Part
to a MIME type the client accepts (e.g., render a dict as `text/plain` if the client
only accepts `text/plain`).

### 3.10 Multi-part responses (v0.2)

v0.1 always emits exactly one Part per response Message. Multi-part is legal per
spec and useful for rich responses (e.g., text summary + JSON data + image). v0.2.

### 3.11 Tenant routing (v0.2)

`AgentInterface.tenant` and the tenant-scoped REST paths (`/{tenant}/message:send`)
are absent from v0.1 routing. Single-agent, no tenant. v0.2 adds tenant-aware
routing for multi-agent gateway deployments.

### 3.12 0.3 wire-dialect compat (explicitly OUT — D4b)

0.3-era shapes are NOT a v0.2 target without an explicit new decision:

| 0.3 shape | Status |
|-----------|--------|
| `kind` discriminator on parts | OUT — `no-kind-discriminator` standing assertion blocks it |
| `/.well-known/agent.json` | OUT — `no-legacy-wellknown` standing assertion blocks it |
| `message/send` JSON-RPC method | Unverified — guilty-until-checked against 1.0 §9.4 |

0.3-compat is a named v0.2+ path that requires a deliberate decision to relax one or
more standing assertions. It is not a bug fix or default migration.

---

## 4. Feature Flag Proposal (for v0.2 Planning)

When v0.2 ships Task lifecycle, the server should default to message-only and opt in
to task-generating via a flag, so existing v0.1 callers are not broken:

```python
@dataclass
class ServerConfig:
    ...
    enable_tasks: bool = False   # v0.2: set True to enable Task lifecycle
```

This is a placeholder for v0.2 design. Do not implement in v0.1.

---

## 5. Standing Assertions Touched by This Doc

| Assertion | How this doc satisfies it |
|-----------|--------------------------|
| `inversion-note` | §2: D6 inversion fully recorded; `INPUT_REQUIRED` park-and-resume documented; explicit warning against importing mcp's no-park rule |
| All 7 others | §3: all deferred features recorded with explicit `UnsupportedOperationError` or capability=false entries; no feature is silently absent |
