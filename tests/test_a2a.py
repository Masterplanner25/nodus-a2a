"""nodus-a2a tests."""
import time
import pytest

from nodus_a2a import (
    AgentCapabilitySet, AgentCoordinator, AgentHealthStatus,
    AgentRegistry, DeadLetterService, DelegationRequest,
    DelegationResult, ExecutionMode, StuckRunWatchdog,
)


def _agent(agent_id="main", capabilities=None, load=0.0, health=AgentHealthStatus.HEALTHY):
    return AgentCapabilitySet(
        agent_id=agent_id,
        capabilities=capabilities or ["memory.read"],
        load=load,
        health_status=health,
    )


def _request(capabilities=None, requesting="requester"):
    return DelegationRequest(
        operation={"type": "memory.read", "query": "test"},
        required_capabilities=capabilities or ["memory.read"],
        requesting_agent_id=requesting,
        user_id="user-1",
    )


# ── AgentRegistry ─────────────────────────────────────────────────────────────

def test_register_and_get():
    r = AgentRegistry()
    a = _agent("main")
    r.register(a)
    assert r.get("main") is a


def test_get_unknown():
    assert AgentRegistry().get("x") is None


def test_find_capable_all_caps():
    r = AgentRegistry()
    r.register(_agent("a", ["memory.read", "flow.run"]))
    r.register(_agent("b", ["memory.read"]))
    results = r.find_capable(["memory.read", "flow.run"])
    assert len(results) == 1
    assert results[0].agent_id == "a"


def test_find_capable_sorted_by_load():
    r = AgentRegistry()
    r.register(_agent("high", load=0.8))
    r.register(_agent("low",  load=0.1))
    results = r.find_capable(["memory.read"])
    assert results[0].agent_id == "low"


def test_find_capable_excludes_unavailable():
    r = AgentRegistry()
    r.register(_agent("a", health=AgentHealthStatus.UNAVAILABLE))
    r.register(_agent("b"))
    results = r.find_capable(["memory.read"])
    ids = [a.agent_id for a in results]
    assert "a" not in ids
    assert "b" in ids


def test_update_load():
    r = AgentRegistry()
    r.register(_agent("a"))
    assert r.update_load("a", 0.7) is True
    assert r.get("a").load == pytest.approx(0.7)


def test_update_load_unknown():
    assert AgentRegistry().update_load("x", 0.5) is False


def test_deregister():
    r = AgentRegistry()
    r.register(_agent("a"))
    assert r.deregister("a") is True
    assert r.get("a") is None


def test_len():
    r = AgentRegistry()
    assert len(r) == 0
    r.register(_agent("a"))
    assert len(r) == 1


def test_is_available_property():
    a = _agent(health=AgentHealthStatus.HEALTHY)
    assert a.is_available is True
    a.health_status = AgentHealthStatus.UNAVAILABLE
    assert a.is_available is False


# ── AgentCoordinator ──────────────────────────────────────────────────────────

def test_decide_mode_local_when_capable():
    r = AgentRegistry()
    r.register(_agent("local", ["memory.read"], load=0.5))
    coord = AgentCoordinator(r, local_agent_id="local")
    mode = coord.decide_mode(_request(["memory.read"]))
    assert mode == ExecutionMode.LOCAL


def test_decide_mode_delegate_when_lacking_capability():
    r = AgentRegistry()
    r.register(_agent("local", ["memory.read"], load=0.0))
    r.register(_agent("specialist", ["flow.run"], load=0.0))
    coord = AgentCoordinator(r, local_agent_id="local")
    mode = coord.decide_mode(_request(["flow.run"]))
    assert mode == ExecutionMode.DELEGATE


def test_decide_mode_local_no_local_registered():
    r = AgentRegistry()
    coord = AgentCoordinator(r, local_agent_id="local")
    mode = coord.decide_mode(_request())
    assert mode == ExecutionMode.LOCAL


def test_select_agent_returns_lowest_load():
    r = AgentRegistry()
    r.register(_agent("heavy", load=0.9))
    r.register(_agent("light", load=0.1))
    coord = AgentCoordinator(r, local_agent_id="self")
    result = coord.select_agent(_request())
    assert result is not None
    assert result.agent_id == "light"


def test_select_agent_none_when_no_candidates():
    r = AgentRegistry()
    coord = AgentCoordinator(r, local_agent_id="self")
    assert coord.select_agent(_request(["special.cap"])) is None


# ── DeadLetterService ─────────────────────────────────────────────────────────

def test_record_and_list():
    svc = DeadLetterService()
    req = _request()
    result = DelegationResult(request_id=req.id, success=False, error="timed out")
    svc.record(req, result)
    entries = svc.list()
    assert len(entries) == 1
    assert entries[0].request.id == req.id


def test_mark_replayed():
    svc = DeadLetterService()
    req = _request()
    svc.record(req, DelegationResult(req.id, success=False))
    assert svc.mark_replayed(req.id) is True
    entries = svc.list(replayed=True)
    assert len(entries) == 1


def test_drain():
    svc = DeadLetterService()
    for _ in range(3):
        req = _request()
        svc.record(req, DelegationResult(req.id, success=False))
    assert svc.drain() == 3
    assert len(svc) == 0


def test_on_record_callback():
    called = []
    svc = DeadLetterService(on_record=called.append)
    req = _request()
    svc.record(req, DelegationResult(req.id, success=False))
    assert len(called) == 1


# ── StuckRunWatchdog ──────────────────────────────────────────────────────────

def test_watchdog_track_and_complete():
    w = StuckRunWatchdog(timeout_seconds=60)
    w.track("run-1")
    assert len(w) == 1
    w.complete("run-1")
    assert len(w) == 0


def test_watchdog_check_once_detects_stuck():
    stuck = []
    w = StuckRunWatchdog(timeout_seconds=-1, on_stuck=stuck.append)  # instant timeout
    w.track("run-1")
    time.sleep(0.01)
    found = w.check_once()
    assert "run-1" in found
    assert "run-1" in stuck


def test_watchdog_check_not_stuck_within_timeout():
    stuck = []
    w = StuckRunWatchdog(timeout_seconds=9999, on_stuck=stuck.append)
    w.track("run-1")
    found = w.check_once()
    assert found == []
    assert stuck == []


def test_watchdog_complete_removes_from_tracking():
    w = StuckRunWatchdog(timeout_seconds=-1)
    w.track("run-1")
    w.complete("run-1")
    found = w.check_once()
    assert "run-1" not in found
