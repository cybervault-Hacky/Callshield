"""Thread-safe, bounded request replay protection."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ReplayStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    INVALID_ID = "INVALID_REQUEST_ID"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    EXPIRED = "EXPIRED_REQUEST"
    DUPLICATE = "DUPLICATE_REQUEST"


def parse_request_timestamp(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).timestamp()


class ReplayCache:
    """Record fresh UUIDs for a finite window with deterministic eviction."""

    def __init__(self, *, lifetime_seconds: int = 300, max_entries: int = 4096) -> None:
        if not isinstance(lifetime_seconds, int) or not (30 <= lifetime_seconds <= 900):
            raise ValueError("replay lifetime must be between 30 and 900 seconds")
        if not isinstance(max_entries, int) or not (128 <= max_entries <= 16384):
            raise ValueError("replay cache size must be between 128 and 16384")
        self.lifetime_seconds = lifetime_seconds
        self.max_entries = max_entries
        self._entries = OrderedDict()  # type: OrderedDict[str, float]
        self._lock = threading.Lock()

    def check_and_store(
        self,
        request_id: Any,
        timestamp: Any,
        *,
        now: Optional[float] = None,
    ) -> ReplayStatus:
        if not isinstance(request_id, str) or not _valid_uuid(request_id):
            return ReplayStatus.INVALID_ID
        request_time = parse_request_timestamp(timestamp)
        if request_time is None:
            return ReplayStatus.INVALID_TIMESTAMP
        current = time.time() if now is None else float(now)
        if abs(current - request_time) > self.lifetime_seconds:
            return ReplayStatus.EXPIRED

        with self._lock:
            self._expire_locked(current)
            if request_id in self._entries:
                return ReplayStatus.DUPLICATE
            while len(self._entries) >= self.max_entries:
                self._entries.popitem(last=False)
            self._entries[request_id] = current + self.lifetime_seconds
        return ReplayStatus.ACCEPTED

    def size(self, *, now: Optional[float] = None) -> int:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._expire_locked(current)
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _expire_locked(self, current: float) -> None:
        expired = [
            request_id
            for request_id, expires_at in self._entries.items()
            if expires_at <= current
        ]
        for request_id in expired:
            self._entries.pop(request_id, None)


def _valid_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return str(parsed) == value.lower()
