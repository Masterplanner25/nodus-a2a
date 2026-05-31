"""nodus-a2a — Agent-to-Agent coordination for Nodus AI systems.

Registry:
    AgentHealthStatus       — HEALTHY | DEGRADED | UNAVAILABLE constants
    AgentCapabilitySet      — agent_id, capabilities, health, load
    AgentRegistry           — thread-safe; register, find_capable, update_load

Delegation:
    DelegationRequest       — operation, required_capabilities, requesting_agent_id
    DelegationResult        — success, target_agent, result/error

Coordination:
    ExecutionMode           — LOCAL | DELEGATE constants
    AgentCoordinator        — decide_mode(), select_agent()

Dead letter:
    DeadLetterEntry         — request + result + replayed flag
    DeadLetterService       — record, list, mark_replayed, drain

Watchdog:
    StuckRunWatchdog        — track, complete, check_once, start/stop
"""
from .coordinator import AgentCoordinator, ExecutionMode
from .deadletter import DeadLetterEntry, DeadLetterService
from .delegation import DelegationRequest, DelegationResult
from .registry import AgentCapabilitySet, AgentHealthStatus, AgentRegistry
from .watchdog import StuckRunWatchdog

__all__ = [
    "AgentHealthStatus",
    "AgentCapabilitySet",
    "AgentRegistry",
    "DelegationRequest",
    "DelegationResult",
    "ExecutionMode",
    "AgentCoordinator",
    "DeadLetterEntry",
    "DeadLetterService",
    "StuckRunWatchdog",
]
