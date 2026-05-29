<!-- Authored by Codex during non coding session. Needs review before repo commit and push. -->

# nodus-a2a Tech Debt

**Version:** 0.1.0
**Status:** Working document
**Maintainer:** Shawn Knight (Masterplanner25)

---

## TD-A2A-001: Message-only scope (D5) — Task lifecycle deferred

**Status:** By-design deferral. Not a debt item — a scoped decision.
**Decision:** D5 (message-only archetype). The server never creates or persists A2A Tasks.
**Remove when:** v0.2 implements Task lifecycle.
**Doc:** `docs/design/05-deferred-features.md §3.1`
**Impact:** All task-management operations (`GetTask`, `ListTasks`, `CancelTask`, streaming,
push notifications) return HTTP 501 `UnsupportedOperationError`. The Agent Card declares
`streaming: false, pushNotifications: false, extendedAgentCard: false`.

---

## TD-A2A-002: D6 inversion — park-and-resume semantics not yet exercised

**Status:** Documented constraint. Standing assertion `inversion-note` ensures it stays documented.
**Description:** A2A's `INPUT_REQUIRED` / `AUTH_REQUIRED` are park-and-resume states. This is
the OPPOSITE of nodus-mcp's no-thread-parks rule. v0.1 does not exercise this because the
server never creates Tasks (D5). v0.2 must NOT import the no-park rule when implementing Task
lifecycle.
**Doc:** `docs/design/05-deferred-features.md §2` (permanent — read before implementing v0.2)
**Standing assertion:** `test_inversion_note_documented` must always pass.

---

## TD-A2A-003: No token validator → dev mode

**Status:** By-design default. Production risk if not configured.
**Description:** Without a `token_validator` on `ServerConfig`, the server runs in dev mode
and accepts all requests. This is intentional for development but dangerous in production.
**Contract:** Production deployments MUST configure `token_validator`. The README warns about
this; the warning should be in the first screen.
**Fix direction:** Consider making `token_validator=None` raise a warning in v0.2, and
require explicit `token_validator=None` with a `dev_mode=True` flag for safety.

---

## TD-A2A-004: Single-part responses only

**Status:** v0.2 target.
**Description:** v0.1 always emits exactly one Part per response Message. The A2A spec permits
multi-part responses (e.g., text summary + JSON data). Multi-part is deferred to v0.2.
**Doc:** `docs/design/05-deferred-features.md §3.10`

---

## TD-A2A-005: accepted_output_modes ignored

**Status:** v0.2 target.
**Description:** `SendMessageConfiguration.accepted_output_modes` is parsed but not honored.
v0.1 always returns the natural Part type for the tool return value. v0.2 should transcode
if the client only accepts a MIME type different from the natural type.
**Doc:** `docs/design/05-deferred-features.md §3.9`

---

## TD-A2A-006: pyproject.toml metadata incomplete

**Status:** Open. Fix before publication.
**Description:** `pyproject.toml` is missing `authors`, `license`, `readme`, `classifiers`,
and `license-files`. These are required for a proper PyPI presentation.
**Fix:** Add standard PyPI metadata before publishing.

---

## TD-A2A-007: No OAuth / mTLS support

**Status:** v0.2 target (D9).
**Description:** Only bearer token in v0.1. The A2A spec supports OAuth2, OIDC, mTLS.
Production deployments that require OAuth cannot use nodus-a2a v0.1.
**Doc:** `docs/design/05-deferred-features.md §3.8`

---

## TD-A2A-008: Agent Card signing not implemented

**Status:** v0.2 target (D8a).
**Description:** `AgentCardSignature` (JWS / RFC 7515) is not implemented. v0.1 serves an
unsigned Agent Card (`signatures: []`).
**Doc:** `docs/design/05-deferred-features.md §3.4`

---

## TD-A2A-009: No operational runbook

**Status:** Open. Create before production deployment.
**Description:** No document covers monitoring, upgrade, failure handling, or troubleshooting
for a deployed nodus-a2a server. The nodus-lang repo has an `OPERATOR_OR_EMBEDDER_RUNBOOK.md`
for core embedding; nodus-a2a needs an equivalent for its server operation.
**Fix:** Create `docs/operational/RUNBOOK.md` before v0.2.

---

## Closed items

| Item | Resolved in | Notes |
|------|------------|-------|
| D6 inversion documented | v0.1.0 | `05-deferred-features.md §2` + standing assertion |
| `inversion-note` standing assertion | v0.1.0 | `test_inversion_note_documented` always runs |
| All deferred features documented | v0.1.0 | `05-deferred-features.md §3` inventory |
