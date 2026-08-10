"""Bounded, thread-safe event queue for CALLSHIELD daemon.

Uses Python's queue.Queue (standard library) with configurable maxsize,
metrics, and graceful shutdown handling.
"""

from __future__ import annotations

import queue
import threading
from typing import Optional

from .models import Event


class EventQueue:
    """Thread-safe bounded queue with metrics."""

    def __init__(self, maxsize: int = 256) -> None:
        if not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self.maxsize = maxsize
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._dropped = 0
        self._peak = 0
        self._received = 0
        self._closed = False

    def put(self, event: Event, block: bool = False, timeout: Optional[float] = None) -> bool:
        """Try to enqueue without blocking by default. Returns True if enqueued, False if full."""
        if not isinstance(event, Event):
            raise ValueError("event must be an Event instance")
        with self._lock:
            if self._closed:
                return False
            self._received += 1
        try:
            if block:
                self._queue.put(event, block=True, timeout=timeout)
            else:
                self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False
        # Update peak
        with self._lock:
            current = self._queue.qsize()
            if current > self._peak:
                self._peak = current
        return True

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[Event]:
        """Dequeue an event, or None if empty/timeout."""
        try:
            if block:
                return self._queue.get(block=True, timeout=timeout)
            else:
                return self._queue.get_nowait()
        except queue.Empty:
            return None

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    # Metrics
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
