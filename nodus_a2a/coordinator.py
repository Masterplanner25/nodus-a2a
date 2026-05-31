"""AgentCoordinator — decide whether to delegate or execute locally."""
from __future__ import annotations

import logging
from typing import Optional

from .delegation import DelegationRequest
from .registry import AgentCapabilitySet, AgentRegistry

logger = logging.getLogger(__name__)


class ExecutionMode:
    LOCAL    = "local"    # execute on this agent
    DELEGATE = "delegate" # send to a more suitable agent


class AgentCoordinator:
    """Decide how to route an operation: locally or via delegation.

    Args:
        registry:        Registry of available agents.
        local_agent_id:  This agent's own ID (excluded from delegation targets).
        event_bus:       Optional event bus for emitting coordination events.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        local_agent_id: str = "local",
        event_bus=None,
    ) -> None:
        self._registry = registry
        self._local_agent_id = local_agent_id
        self._event_bus = event_bus

    def decide_mode(self, request: DelegationRequest) -> str:
        """Return ``ExecutionMode.LOCAL`` or ``ExecutionMode.DELEGATE``.

        Returns LOCAL when:
        - The local agent has all required capabilities
        - No other capable, lower-load agent is available

        Returns DELEGATE when:
        - The local agent lacks required capabilities, OR
        - A more suitable (lower-load) agent is available
        """
        local = self._registry.get(self._local_agent_id)
        if local is None:
            return ExecutionMode.LOCAL

        has_all = all(
            local.has_capability(c) for c in request.required_capabilities
        )
        if not has_all:
            return ExecutionMode.DELEGATE

        # Check if a better (lower-load) agent is available
        candidates = self._registry.find_capable(request.required_capabilities)
        external = [a for a in candidates if a.agent_id != self._local_agent_id]
        if external and external[0].load < local.load * 0.8:
            return ExecutionMode.DELEGATE

        return ExecutionMode.LOCAL

    def select_agent(
        self,
        request: DelegationRequest,
    ) -> Optional[AgentCapabilitySet]:
        """Select the best agent to handle *request*.

        Returns None if no capable agent is available (caller should fail-local).
        """
        candidates = self._registry.find_capable(request.required_capabilities)
        external = [a for a in candidates if a.agent_id != self._local_agent_id]
        if not external:
            return None
        return external[0]  # lowest-load capable agent
