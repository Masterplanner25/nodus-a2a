# nodus-a2a — Design Notes

## What this package is

`nodus-a2a` is the **AgentCoordinator coordination layer** — a set of pure-Python
primitives for routing work between agents in a multi-agent system. It has no
external dependencies and no nodus-lang requirement.

### What it is not

This package does **not** implement the A2A 1.0.0 wire protocol (HTTP+JSON/REST,
Agent Card, tool-call dispatch). That implementation exists on GitHub at the
`v0.0.1-a2a-adapter` tag and is preserved for reference.

---

## Design decisions

### D1 — No external dependencies

All five modules use only stdlib (`threading`, `dataclasses`, `datetime`,
`uuid`, `logging`). Installable in any Python 3.11+ environment.

### D2 — No nodus-lang dependency

Operates at the Python level. Nodus scripts can delegate work through it, but
this package does not import `nodus` or any nodus-lang companion package.

### D3 — Thread-safe by default

`AgentRegistry` and `DeadLetterService` use `threading.Lock`. No external
synchronisation required.

### D4 — Capability matching is exact-set intersection

`find_capable(required)` returns agents whose declared capabilities are a
superset of `required`. Partial matches excluded.

### D5 — Load is a float 0.0–1.0, caller-managed

The registry stores load as declared by each agent. Nothing in this package
measures or infers load. Agents call `update_load()` themselves.

### D6 — DeadLetterService is in-process only

Stores entries in memory. For durable dead-letter persistence, back it with
`nodus-store-sql`'s `JobStore` at the application layer.

### D7 — StuckRunWatchdog polling is caller-driven

`check_once()` is a single scan. The application decides the poll interval.

---

## Package structure

```
nodus_a2a/
├── __init__.py     # public exports
├── registry.py     # AgentRegistry, AgentCapabilitySet, AgentHealthStatus
├── coordinator.py  # AgentCoordinator, ExecutionMode
├── delegation.py   # DelegationRequest, DelegationResult
├── deadletter.py   # DeadLetterEntry, DeadLetterService
└── watchdog.py     # StuckRunWatchdog
```
