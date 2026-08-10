"""Structured event model for CALLSHIELD Phase 3.

Every event has: event_id, event_type, timestamp, source, number, payload
Uses uuid4 for uniqueness, iso_now for timestamp.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from ..utils import iso_now, InvalidNumberError
from .types import VALID_EVENT_TYPES

# Payload size limit to prevent abuse
MAX_PAYLOAD_SIZE = 8 * 1024  # 8KB

@dataclass
class Event:
    """Structured event object for the daemon pipeline."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "SYSTEM"
    timestamp: str = field(default_factory=iso_now)
    source: str = "SYSTEM"
    number: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate event_type
        if self.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {self.event_type}. Valid: {VALID_EVENT_TYPES}")
        # Validate event_id is UUID-like (but allow any non-empty string for flexibility, we generate uuid4)
        if not self.event_id or not isinstance(self.event_id, str):
            raise ValueError("event_id must be a non-empty string")
        # Validate timestamp is non-empty
        if not self.timestamp or not isinstance(self.timestamp, str):
            raise ValueError("timestamp must be a non-empty string")
        # Validate source
        if not self.source or not isinstance(self.source, str):
            raise ValueError("source must be a non-empty string")
        # Validate payload size
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dict")
        # Rough size check via stringified length
        payload_str = str(self.payload)
        if len(payload_str) > MAX_PAYLOAD_SIZE:
            raise ValueError(f"payload too large: {len(payload_str)} > {MAX_PAYLOAD_SIZE}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "number": self.number,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        if not isinstance(data, dict):
            raise ValueError("event data must be a dict")
        # Validate required fields
        for field_name in ("event_type", "timestamp", "source"):
            if field_name not in data:
                raise ValueError(f"Missing required field: {field_name}")
        return cls(
            event_id=data.get("event_id") or str(uuid.uuid4()),
            event_type=data["event_type"],
            timestamp=data.get("timestamp") or iso_now(),
            source=data.get("source") or "SYSTEM",
            number=data.get("number"),
            payload=data.get("payload") or {},
        )

    def is_valid(self) -> bool:
        try:
            self.__post_init__()
            return True
        except Exception:
            return False


def create_event(
    event_type: str,
    *,
    number: Optional[str] = None,
    source: str = "SYSTEM",
    payload: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> Event:
    """Factory helper that validates and creates an Event."""
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}")
    return Event(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        timestamp=iso_now(),
        source=source,
        number=number,
        payload=payload or {},
    )
