# Changelog

All notable changes to nodus-a2a are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2026-05-30

Initial release of the AgentCoordinator coordination layer.

> **Note:** An earlier iteration of this repo contained an A2A 1.0.0 wire
> protocol adapter (HTTP+JSON/REST server, Agent Card, tool-call dispatch).
> That implementation is preserved on GitHub at the `v0.0.1-a2a-adapter`
> tag. This release replaces it with the coordination primitives below,
> which have no external dependencies and no nodus-lang requirement.

### Added

- **AgentRegistry** — thread-safe registry of agents keyed by `agent_id`.
  Stores `AgentCapabilitySet` (capabilities list, load 0–1, health status).
  `find_capable(caps)` returns agents sorted by load, excluding `UNAVAILABLE`.
  `update_load`, `deregister`, `get`, `len`.

- **AgentCoordinator** — decides `ExecutionMode.LOCAL` vs `DELEGATE` for a
  `DelegationRequest`. Selects the lowest-load capable agent via `select_agent`.

- **DelegationRequest / DelegationResult** — typed delegation envelopes.
  `DelegationRequest` carries `operation`, `required_capabilities`,
  `requesting_agent_id`, `user_id`, and a UUID `id`. `DelegationResult`
  carries `success`, optional `result` / `error`, and `target_agent`.

- **DeadLetterService** — records failed `DelegationResult`s with their
  originating request. `list(replayed?)`, `mark_replayed(id)`, `drain()`,
  optional `on_record` callback, `len`.

- **StuckRunWatchdog** — tracks in-flight runs by ID; `check_once()` returns
  run IDs that have exceeded `timeout_seconds` and fires the `on_stuck`
  callback for each.

- **23 tests** in `tests/test_a2a.py` covering all five components.

- **No external dependencies** — stdlib only (`threading`, `dataclasses`,
  `datetime`, `uuid`, `logging`).

[0.1.0]: https://github.com/Masterplanner25/nodus-a2a/releases/tag/v0.1.0
