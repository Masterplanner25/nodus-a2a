"""AgentRegistry — track agent capabilities, health, and load."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class AgentHealthStatus:
    HEALTHY     = "healthy"
    DEGRADED    = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class AgentCapabilitySet:
    """Registered capability declaration for one agent.

    Attributes
    ----------
    agent_id:      Unique agent identifier.
    capabilities:  List of capability strings this agent can handle.
    health_status: Current health (healthy | degraded | unavailable).
    load:          Current load fraction 0.0 (idle) – 1.0 (full).
    last_seen:     UTC timestamp of last registration or heartbeat.
    metadata:      Optional extra data (model, version, endpoint, etc.).
    """

    agent_id: str
    capabilities: list[str] = field(default_factory=list)
    health_status: str = AgentHealthStatus.HEALTHY
    load: float = 0.0
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.health_status != AgentHealthStatus.UNAVAILABLE

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities


class AgentRegistry:
    """Thread-safe registry of agent capability sets.

    Usage::

        registry = AgentRegistry()
        registry.register(AgentCapabilitySet(
            agent_id="main",
            capabilities=["memory.read", "flow.run"],
        ))
        agents = registry.find_capable(["memory.read"])
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentCapabilitySet] = {}
        self._lock = threading.Lock()

    def register(self, agent: AgentCapabilitySet) -> None:
        """Register or update an agent's capability set."""
        agent.last_seen = datetime.now(timezone.utc)
        with self._lock:
            self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> Optional[AgentCapabilitySet]:
        with self._lock:
            return self._agents.get(agent_id)

    def find_capable(
        self,
        required_capabilities: list[str],
        *,
        exclude_degraded: bool = False,
    ) -> list[AgentCapabilitySet]:
        """Return agents that have ALL required capabilities, sorted by load (ascending)."""
        cap_set = set(required_capabilities)
        with self._lock:
            candidates = list(self._agents.values())
        result = [
            a for a in candidates
            if a.is_available
            and (not exclude_degraded or a.health_status == AgentHealthStatus.HEALTHY)
            and cap_set.issubset(set(a.capabilities))
        ]
        result.sort(key=lambda a: a.load)
        return result

    def update_load(self, agent_id: str, load: float) -> bool:
        """Update the load fraction for *agent_id*.  Returns False if not found."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return False
            agent.load = max(0.0, min(1.0, load))
            return True

    def update_health(self, agent_id: str, status: str) -> bool:
        """Update health status for *agent_id*."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return False
            agent.health_status = status
            return True

    def deregister(self, agent_id: str) -> bool:
        with self._lock:
            return self._agents.pop(agent_id, None) is not None

    def list_all(self) -> list[AgentCapabilitySet]:
        with self._lock:
            return list(self._agents.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._agents)
