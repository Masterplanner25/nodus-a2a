"""DeadLetterService — capture and replay failed delegations."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .delegation import DelegationRequest, DelegationResult


@dataclass
class DeadLetterEntry:
    request: DelegationRequest
    result: DelegationResult
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    replayed: bool = False


class DeadLetterService:
    """Capture failed delegations for inspection and replay.

    Provides an in-memory store suitable for tests and single-process apps.
    For production use a persistent backend via the ``on_record`` callback.
    """

    def __init__(
        self,
        on_record=None,
    ) -> None:
        self._entries: list[DeadLetterEntry] = []
        self._lock = threading.Lock()
        self._on_record = on_record   # optional callback(entry)

    def record(self, request: DelegationRequest, result: DelegationResult) -> None:
        """Record a failed delegation."""
        entry = DeadLetterEntry(request=request, result=result)
        with self._lock:
            self._entries.append(entry)
        if self._on_record is not None:
            try:
                self._on_record(entry)
            except Exception:
                pass

    def list(self, *, replayed: Optional[bool] = None) -> list[DeadLetterEntry]:
        with self._lock:
            entries = list(self._entries)
        if replayed is not None:
            entries = [e for e in entries if e.replayed is replayed]
        return entries

    def mark_replayed(self, request_id: str) -> bool:
        with self._lock:
            for entry in self._entries:
                if entry.request.id == request_id:
                    entry.replayed = True
                    return True
        return False

    def drain(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
