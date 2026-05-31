# nodus-a2a

**Agent-to-Agent coordination primitives for Nodus AI systems.**

`nodus-a2a` provides the coordination layer between agents: capability-based
routing, load-aware delegation, dead-letter recovery, and stuck-run detection.
No external dependencies — stdlib only.

> **Status:** v0.1.0 — prepared, not yet published.

---

## Install

```bash
pip install nodus-a2a
```

---

## What it provides

| Component | Purpose |
|---|---|
| `AgentRegistry` | Thread-safe registry of agents with capability declarations and load |
| `AgentCoordinator` | Decides LOCAL vs DELEGATE execution; selects the best available agent |
| `DelegationRequest` / `DelegationResult` | Typed delegation envelopes |
| `DeadLetterService` | Records failed delegations; supports replay and drain |
| `StuckRunWatchdog` | Tracks in-flight runs; fires a callback when timeout elapses |

---

## Quick start

```python
from nodus_a2a import (
    AgentRegistry, AgentCapabilitySet, AgentHealthStatus,
    AgentCoordinator, DelegationRequest, ExecutionMode,
)

registry = AgentRegistry()
registry.register(AgentCapabilitySet(
    agent_id="memory-agent",
    capabilities=["memory.read", "memory.write"],
    load=0.2,
    health_status=AgentHealthStatus.HEALTHY,
))
registry.register(AgentCapabilitySet(
    agent_id="flow-agent",
    capabilities=["flow.run"],
    load=0.5,
    health_status=AgentHealthStatus.HEALTHY,
))

coordinator = AgentCoordinator(registry, local_agent_id="memory-agent")
req = DelegationRequest(
    operation={"type": "flow.run", "flow": "my-flow"},
    required_capabilities=["flow.run"],
    requesting_agent_id="memory-agent",
)

mode = coordinator.decide_mode(req)        # ExecutionMode.DELEGATE
target = coordinator.select_agent(req)     # flow-agent (lowest load with capability)
```

---

## AgentRegistry

```python
registry = AgentRegistry()
registry.register(agent)
registry.update_load("agent-id", 0.7)     # returns False if unknown
registry.deregister("agent-id")
registry.get("agent-id")                  # AgentCapabilitySet | None
registry.find_capable(["cap.a", "cap.b"]) # sorted by load, UNAVAILABLE excluded
len(registry)
```

---

## AgentCoordinator

```python
coordinator = AgentCoordinator(registry, local_agent_id="my-agent")
mode = coordinator.decide_mode(request)    # ExecutionMode.LOCAL or DELEGATE
agent = coordinator.select_agent(request)  # AgentCapabilitySet | None (lowest load)
```

---

## DeadLetterService

```python
dlq = DeadLetterService(on_record=my_alert_fn)
dlq.record(request, result)
dlq.list()                # all entries
dlq.list(replayed=True)
dlq.mark_replayed(req_id) # True if found
dlq.drain()               # removes all; returns count
```

---

## StuckRunWatchdog

```python
watchdog = StuckRunWatchdog(
    timeout_seconds=300,
    on_stuck=lambda run_id: logger.warning("stuck: %s", run_id),
)
watchdog.track("run-abc")
watchdog.complete("run-abc")
stuck = watchdog.check_once()   # list of stuck IDs; fires on_stuck for each
len(watchdog)
```

---

## Health statuses

| Status | Eligible for delegation? |
|---|---|
| `HEALTHY` | Yes |
| `DEGRADED` | Yes (deprioritised by load sort) |
| `UNAVAILABLE` | No — excluded from `find_capable` |

---

## Design

- **No external dependencies.** Five modules; stdlib only (`threading`,
  `dataclasses`, `datetime`, `uuid`, `logging`).
- **Thread-safe.** `AgentRegistry` and `DeadLetterService` use `threading.Lock`.
- **No nodus-lang dependency.** Coordinates agents; does not execute Nodus scripts.

See `docs/design.md` for design decisions.

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

---

## License

MIT — see [LICENSE](LICENSE).
