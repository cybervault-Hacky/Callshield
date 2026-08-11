"""Validated event model for the CALLSHIELD Phase 3 pipeline."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from ..utils import iso_now
from .types import VALID_EVENT_TYPES

MAX_PAYLOAD_SIZE = 8 * 1024
MAX_SOURCE_LENGTH = 64
MAX_NUMBER_LENGTH = 128
MAX_TIMESTAMP_LENGTH = 64


def _payload_size(payload: Dict[str, Any]) -> int:
    """Return deterministic UTF-8 JSON size, rejecting non-JSON payloads."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(f"payload must contain only valid JSON values: {exc}") from exc
    return len(encoded)


def _validate_timestamp(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_TIMESTAMP_LENGTH:
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be a valid ISO-8601 value") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")


@dataclass
class Event:
    """A bounded, serializable daemon event.

    ``number`` is optional because SYSTEM and HEARTBEAT events do not represent
    number analysis. Phone-call semantics are deliberately absent in Phase 3.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "SYSTEM"
    timestamp: str = field(default_factory=iso_now)
    source: str = "SYSTEM"
    number: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self, payload_limit: int = MAX_PAYLOAD_SIZE) -> None:
        if not isinstance(self.event_type, str) or self.event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type: {self.event_type}. Valid: {VALID_EVENT_TYPES}"
            )
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id must be a UUID string")
        try:
            uuid.UUID(self.event_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("event_id must be a valid UUID") from exc
        _validate_timestamp(self.timestamp)
        if (
            not isinstance(self.source, str)
            or not self.source
            or len(self.source) > MAX_SOURCE_LENGTH
            or any(ord(char) < 32 for char in self.source)
        ):
            raise ValueError(
                f"source must be 1-{MAX_SOURCE_LENGTH} printable characters"
            )
        if self.number is not None and (
            not isinstance(self.number, str) or len(self.number) > MAX_NUMBER_LENGTH
        ):
            raise ValueError(
                f"number must be a string no longer than {MAX_NUMBER_LENGTH} characters"
            )
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a JSON object")
        if isinstance(payload_limit, bool) or not isinstance(payload_limit, int) or payload_limit <= 0:
            raise ValueError("payload_limit must be a positive integer")
        size = _payload_size(self.payload)
        if size > payload_limit:
            raise ValueError(f"payload too large: {size} bytes > {payload_limit} bytes")

    @property
    def payload_size(self) -> int:
        return _payload_size(self.payload)

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
    def from_dict(
        cls, data: Dict[str, Any], payload_limit: int = MAX_PAYLOAD_SIZE
    ) -> "Event":
        if not isinstance(data, dict):
            raise ValueError("event data must be a JSON object")
        for field_name in ("event_type", "timestamp", "source"):
            if field_name not in data:
                raise ValueError(f"Missing required field: {field_name}")
        event = cls(
            event_id=data.get("event_id") or str(uuid.uuid4()),
            event_type=data["event_type"],
            timestamp=data["timestamp"],
            source=data["source"],
            number=data.get("number"),
            payload=data["payload"] if "payload" in data else {},
        )
        event.validate(payload_limit=payload_limit)
        return event

    def is_valid(self, payload_limit: int = MAX_PAYLOAD_SIZE) -> bool:
        try:
            self.validate(payload_limit=payload_limit)
            return True
        except (TypeError, ValueError):
            return False


def create_event(
    event_type: str,
    *,
    number: Optional[str] = None,
    source: str = "SYSTEM",
    payload: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> Event:
    """Create a validated event with a UUID and current UTC timestamp."""

    return Event(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        timestamp=iso_now(),
        source=source,
        number=number,
        payload={} if payload is None else payload,
    )
