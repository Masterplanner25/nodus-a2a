# nodus-a2a v0.1 — Phase 0 Decisions

**Status:** SETTLED — all D1–D10 ratified 2026-05-29.
**Target:** A2A Protocol **≥1.0.0, <2.0.0** (Linux Foundation); wire dialect 1.0.
**Normative source:** `specification/a2a.proto` in `a2aproject/A2A` (proto package `lf.a2a.v1`)
**Companion to:** nodus-mcp v0.1.0 (parked), nodus-lang 4.0.0 (parked)
**Launch posture:** prepare-not-release. All three artifacts ship together or not at all.

> **Protocol note:** Phase 0 referenced `spec/a2a.proto` and `google/A2A` — both are wrong.
> The repo transferred to `a2aproject/A2A`; the proto lives at `specification/a2a.proto`.
> v1.0.1 (patch, 2026-05-28) was released after Phase 0 was written; no breaking changes.
> These corrections are absorbed here; all Phase 0 reasoning remains valid.

---

## A. Decisions that carry from nodus-mcp UNCHANGED

**D1 — Entry-point contract.** `nodus.nd` entry-point group; local `.nodus/modules/`
wins over pip-installed. Permanent rule. Inherited verbatim from lang/mcp.

**D2 — Protocols-are-adapters thesis.** A2A is an adapter over the `std:tool` registry.
**Zero new opcodes. BYTECODE_VERSION stays 4.** `AgentSkill` is purely descriptive
(id/name/description/tags/modes), so a std:tool projects onto an AgentSkill without
touching the language. No language-side change across any a2a phase.

**D3 — Process discipline.** Design-first; standing-assertions per phase; mandatory
bytecode-impact section per design doc; std:tool registry is single source of truth;
prepare-not-release coordination. All inherited.

---

## B. Decisions that DIFFER or INVERT from mcp

**D4 — Versioning: two sub-decisions.**

- **D4a (normative target):** ≥1.0.0, <2.0.0 / `lf.a2a.v1`. No RC. Patch releases
  (1.0.1) are adopted automatically; next major requires an explicit decision.
- **D4b (wire dialect):** v0.1 speaks **1.0 wire format only**. 0.3 is explicitly OUT.
  No `kind` discriminator on parts/payloads. No `agent.json` discovery path.
- **Mechanism:** declare `protocol_version: "1.0"` in each `AgentInterface` in the
  Agent Card; read inbound `A2A-Version` header; reject mismatch with
  `VersionNotSupportedError`. Converts dialect skew from silent hazard to explicit,
  testable contract.
- **Standing assertion (RC-purity analog):** no 0.3-era shape may be reintroduced —
  specifically, no `kind` discriminator, and no `agent.json` legacy path.

**D5 — KEYSTONE: agent archetype = MESSAGE-ONLY for v0.1.** RATIFIED 2026-05-29.

The proto pins the choice: `SendMessageResponse` is `oneof payload { Task task = 1;
Message message = 2; }`. Message-only means nodus-a2a always returns a `Message`
carrying the std:tool result and NEVER persists a `Task`.

Three independent lines of evidence:
1. The `oneof payload` structure: message and task are the only two options.
2. Spec §3.6: `return_immediately` "has no effect when the operation returns a direct
   Message response." Message-only is immune to blocking-by-default.
3. HelloWorld AgentExecutor pattern: enqueue one `new_agent_text_message(result)` and
   return. Maps almost exactly onto std:tool invocation → single terminal Message → done.

Cost (all deferred behind declared-false capabilities): no long-running work, no
`input-required`, no streaming, no push. All `AgentCapabilities` optional bools
advertised false; client adapts honestly.

**Standing assertion:** server NEVER emits a `Task` payload in v0.1
(proto-enforceable on the response oneof).

**D6 — `input-required` inversion. Document explicitly.**

A2A's `TASK_STATE_INPUT_REQUIRED` / `TASK_STATE_AUTH_REQUIRED` are interrupted states:
the task persists and resumes when the client sends another Message with the same
`task_id`. This IS the parked-and-resumed model — the exact opposite of mcp's
`test_l_no_thread_parks` rule.

Under D5 (message-only) this does not arise in v0.1, which is the cleanest reason to
pick message-only. But Phase 0 records the inversion so a future maintainer building
v0.2 Task lifecycle does NOT import mcp's no-park assertion.

**D7 — Transport: HTTP+JSON/REST only for v0.1.**

- `AgentInterface.protocol_binding = "HTTP+JSON"`
- JSON-RPC binding: deferred to v0.1-stretch / v0.2.
- gRPC: OUT for v0.1.
- stdio: N/A — does not exist in A2A anywhere.
- Content-Type: `application/a2a+json` (adopted from v1.0.1; was `application/json` in 1.0.0).

REST path set (from `specification/a2a.proto` HTTP options — all verified):

| Operation | Method | Path | v0.1 scope |
|-----------|--------|------|-----------|
| SendMessage | POST | `/message:send` | **IN SCOPE** |
| SendStreamingMessage | POST | `/message:stream` | deferred (D5) |
| GetTask | GET | `/tasks/{id=*}` | deferred (D10) |
| ListTasks | GET | `/tasks` | deferred (D10) |
| CancelTask | POST | `/tasks/{id=*}:cancel` | deferred (D10) |
| SubscribeToTask | GET | `/tasks/{id=*}:subscribe` | deferred (streaming) |
| CreateTaskPushNotificationConfig | POST | `/tasks/{task_id=*}/pushNotificationConfigs` | deferred (D10) |
| GetTaskPushNotificationConfig | GET | `/tasks/{task_id=*}/pushNotificationConfigs/{id=*}` | deferred (D10) |
| ListTaskPushNotificationConfigs | GET | `/tasks/{task_id=*}/pushNotificationConfigs` | deferred (D10) |
| DeleteTaskPushNotificationConfig | DELETE | `/tasks/{task_id=*}/pushNotificationConfigs/{id=*}` | deferred (D10) |
| GetExtendedAgentCard | GET | `/extendedAgentCard` | deferred (D8b) |

Tenant-scoped variants (`/{tenant}/message:send` etc.) exist for all operations;
v0.1 leaves `tenant` empty — a single-agent deployment with no routing.

JSON-RPC method strings (§9.4): deferred — HTTP+REST path set is sufficient for v0.1.

**D8 — Discovery: unsigned Agent Card at the 1.0 well-known URI.**

- Well-known URI (resolved from spec §8.2): `/.well-known/agent-card.json`
  NOT `agent.json` — that is the 0.3-era path and is covered by the
  `no-legacy-wellknown` standing assertion.
- Extended Agent Card (authenticated): `GET /extendedAgentCard` — deferred (D8b).
- **D8a:** Card signing via `AgentCardSignature` (JWS / RFC 7515) — unsigned for v0.1,
  signing in v0.2.
- **D8b:** `capabilities.extended_agent_card = false` for v0.1.

**D9 — Auth: bearer-token only, declared via `HTTPAuthSecurityScheme`.**

Proto `SecurityScheme` oneof offers five choices: api_key, http_auth, oauth2, oidc, mtls.
v0.1 supports **bearer only**, advertised in `AgentCard.security_schemes`.
`HTTPAuthSecurityScheme.scheme = "Bearer"`.

**D10 — Task-management operations: OUT for v0.1 (consequence of D5).**

All task-management RPCs (GetTask, ListTasks, CancelTask, SubscribeToTask, and all
push-notification-config ops) presuppose a persisted Task. Under message-only they
return `UnsupportedOperationError` and are declared unsupported via capabilities.

---

## C. v0.1 scope summary

**In scope:**
- Agent Card at `/.well-known/agent-card.json` (unsigned).
- `SendMessage` returning a `Message` (message-only archetype).
- `Part` handling: text (string), raw bytes (base64 on wire), url (string), data
  (`google.protobuf.Value` / JSON value).
- std:tool → `AgentSkill` projection.
- HTTP+JSON/REST binding, `application/a2a+json` Content-Type.
- Bearer auth via `HTTPAuthSecurityScheme`.
- `A2A-Version` negotiation with `VersionNotSupportedError` on mismatch.
- Proto↔JSON codec: snake_case proto ↔ camelCase wire.
- Capability honesty: streaming / push / extended-card all declared false/absent.

**Deferred (v0.2+):**
- Task lifecycle + state machine + task store (D5/D6/D10).
- Streaming / SSE (`SendStreamingMessage`, `SubscribeToTask`).
- Push webhooks.
- JSON-RPC binding, gRPC binding.
- Agent Card signing (D8a), extended/authenticated card (D8b).
- OAuth2 / OIDC / mTLS (D9).
- Tenant routing (`AgentInterface.tenant`).
- 0.3 wire-dialect compat (D4b).

---

## D. Standing-assertions inventory

| Assertion | Protects | Fails if... |
|-----------|----------|-------------|
| `no-new-opcodes` | D2 | Any a2a phase touches the language / BYTECODE_VERSION |
| `no-task-emitted` | D5 | Server ever returns a `Task` in the response payload |
| `no-kind-discriminator` | D4b | A `kind` field appears on any part or payload |
| `no-legacy-wellknown` | D4b | The `agent.json` path is served |
| `version-negotiation` | D4 | Inbound `A2A-Version` != "1.0" is not rejected |
| `codec-name-mapping` | C/codec | Proto field names appear unmapped on the wire |
| `capability-honesty` | D5/D10 | streaming/push/extended-card advertised true but unimplemented |
| `inversion-note` | D6 | D6 is undocumented and a future maintainer imports mcp's no-park rule |

All 8 must be tested in `tests/test_invariants.py`.
