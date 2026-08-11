"""Bounded, thread-safe event queue used by the Phase 3 daemon."""

from __future__ import annotations

import queue
import threading
import time
from typing import List, Optional

from .models import Event


class EventQueue:
    """A finite FIFO queue with drop and peak metrics.

    The established ``put/get/qsize`` methods remain available for Phase 1/2
    compatibility; ``enqueue/dequeue/size/drain`` provide the explicit Phase 3
    API described by the daemon architecture.
    """

    def __init__(self, maxsize: int = 256) -> None:
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self.maxsize = maxsize
        self._queue = queue.Queue(maxsize=maxsize)  # type: queue.Queue[Event]
        self._lock = threading.Lock()
        self._dropped = 0
        self._peak = 0
        self._received = 0
        self._closed = False

    def put(
        self,
        event: Event,
        block: bool = False,
        timeout: Optional[float] = None,
    ) -> bool:
        """Enqueue an event, returning ``False`` when closed or full."""

        if not isinstance(event, Event):
            raise ValueError("event must be an Event instance")
        with self._lock:
            self._received += 1
            if self._closed:
                self._dropped += 1
                return False
        try:
            if block:
                self._queue.put(event, block=True, timeout=timeout)
            else:
                self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False
        with self._lock:
            current = self._queue.qsize()
            if current > self._peak:
                self._peak = current
        return True

    def enqueue(
        self,
        event: Event,
        block: bool = False,
        timeout: Optional[float] = None,
    ) -> bool:
        return self.put(event, block=block, timeout=timeout)

    def get(
        self, block: bool = True, timeout: Optional[float] = None
    ) -> Optional[Event]:
        """Return the next event, or ``None`` for empty/timeout."""

        try:
            if block:
                return self._queue.get(block=True, timeout=timeout)
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def dequeue(
        self, block: bool = True, timeout: Optional[float] = None
    ) -> Optional[Event]:
        return self.get(block=block, timeout=timeout)

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def size(self) -> int:
        return self.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def close(self) -> None:
        """Stop accepting new events; queued work remains available to drain."""

        with self._lock:
            self._closed = True

    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def drain(self, limit: Optional[int] = None) -> List[Event]:
        """Remove and return queued events without blocking.

        This helper is primarily useful for controlled recovery and tests. The
        daemon's graceful shutdown drains by processing events, not discarding
        them.
        """

        drained = []  # type: List[Event]
        while limit is None or len(drained) < limit:
            event = self.get(block=False)
            if event is None:
                break
            drained.append(event)
            self.task_done()
        return drained

    def wait_until_done(self, timeout: float) -> bool:
        """Wait until queued and in-flight tasks finish, with a finite timeout."""

        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return self._queue.unfinished_tasks == 0

    def metrics(self) -> dict:
        with self._lock:
            return {
                "size": self._queue.qsize(),
                "maxsize": self.maxsize,
                "received": self._received,
                "dropped": self._dropped,
                "peak": self._peak,
                "closed": self._closed,
            }

    def stats(self) -> dict:
        return self.metrics()
