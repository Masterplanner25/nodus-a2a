"""StuckRunWatchdog — detect and recover hung delegations."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class StuckRunWatchdog:
    """Periodic check for delegations that have been in-flight too long.

    Calls *on_stuck* for each run_id that exceeds *timeout_seconds*
    without completing.

    Usage::

        watchdog = StuckRunWatchdog(timeout_seconds=300, on_stuck=handle_stuck)
        watchdog.track("run-123")
        watchdog.start()
        # ... later:
        watchdog.complete("run-123")
    """

    def __init__(
        self,
        timeout_seconds: int = 300,
        check_interval_seconds: float = 30.0,
        on_stuck: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._interval = check_interval_seconds
        self._on_stuck = on_stuck or (lambda run_id: logger.warning("[Watchdog] stuck run: %s", run_id))
        self._runs: dict[str, datetime] = {}   # run_id → started_at
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def track(self, run_id: str) -> None:
        """Begin tracking *run_id*."""
        with self._lock:
            self._runs[run_id] = datetime.now(timezone.utc)

    def complete(self, run_id: str) -> bool:
        """Stop tracking *run_id*. Returns True if it was tracked."""
        with self._lock:
            return self._runs.pop(run_id, None) is not None

    def check_once(self) -> list[str]:
        """Check for stuck runs and call *on_stuck* for each. Returns stuck IDs."""
        threshold = datetime.now(timezone.utc) - timedelta(seconds=self._timeout)
        with self._lock:
            stuck = [rid for rid, started in self._runs.items() if started < threshold]
        for run_id in stuck:
            try:
                self._on_stuck(run_id)
            except Exception as exc:
                logger.warning("[Watchdog] on_stuck callback failed: %s", exc)
        return stuck

    def start(self) -> None:
        """Start the background watchdog thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="nodus-a2a-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(timeout=self._interval):
            self.check_once()

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)
