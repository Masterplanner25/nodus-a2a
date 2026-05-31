"""DelegationRequest and DelegationResult — typed A2A delegation contracts."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class DelegationRequest:
    """A request to delegate an operation to a capable agent.

    Attributes
    ----------
    operation:               The operation to perform (dict with type + params).
    required_capabilities:   Capabilities the target agent must have.
    requesting_agent_id:     The agent making the delegation request.
    user_id:                 The user/tenant context.
    id:                      Unique delegation ID.
    correlation_id:          Optional chain ID for distributed tracing.
    metadata:                Extra data passed to the target agent.
    created_at:              UTC creation timestamp.
    """

    operation: dict[str, Any]
    required_capabilities: list[str]
    requesting_agent_id: str
    user_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DelegationResult:
    """The outcome of an A2A delegation.

    Attributes
    ----------
    request_id:   ID of the corresponding ``DelegationRequest``.
    success:      True if delegation completed without error.
    target_agent: Agent that handled the delegation.
    result:       Operation output on success.
    error:        Error message on failure.
    duration_ms:  Time taken in milliseconds.
    """

    request_id: str
    success: bool
    target_agent: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
