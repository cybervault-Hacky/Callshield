"""Bounded SQLite storage for privacy-preserving reputation and trust."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..database import Database
from ..utils import DatabaseError
from .history import history_trigger, meaningful_change
from .models import (
    ReputationHistoryEntry,
    ReputationProfile,
    ReputationSignal,
    TrustedRecord,
)


class ReputationStorageError(RuntimeError):
    pass


def number_fingerprint(normalized_number: str) -> str:
    return hashlib.sha256(normalized_number.encode("utf-8")).hexdigest()


def trust_expiry(duration: str, max_seconds: int) -> str:
    """Parse a bounded duration such as 30m, 24h, or 7d."""

    if not isinstance(duration, str) or len(duration) < 2:
        raise ValueError("Trust duration must use m, h, or d (for example 24h)")
    unit = duration[-1].lower()
    try:
        amount = int(duration[:-1])
    except ValueError as exc:
        raise ValueError("Trust duration must use m, h, or d") from exc
    factors = {"m": 60, "h": 3600, "d": 86400}
    if unit not in factors or amount <= 0:
        raise ValueError("Trust duration must be positive and use m, h, or d")
    seconds = amount * factors[unit]
    if seconds > int(max_seconds):
        raise ValueError("Trust duration exceeds the configured maximum")
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


class ReputationStorage:
    def __init__(self, database: Database, cfg: Any) -> None:
        self.database = database
        self.cfg = cfg

    def measurements(self, normalized_number: str, now_iso: str) -> Dict[str, Any]:
        """Use indexed aggregates plus a bounded recent-score query."""

        number_hash = number_fingerprint(normalized_number)
        limit = int(self.cfg.reputation_query_limit)
        screening = self.database._conn.execute(
            """
            SELECT COUNT(*) AS calls_seen,
                   COALESCE(SUM(CASE WHEN applied_action='ALLOW' THEN 1 ELSE 0 END),0) AS allowed,
                   COALESCE(SUM(actually_rejected),0) AS rejected,
                   COALESCE(SUM(CASE WHEN policy_action='BLOCK' THEN 1 ELSE 0 END),0) AS blocks,
                   COALESCE(SUM(CASE WHEN verdict IN ('HIGH_RISK','MALICIOUS') THEN 1 ELSE 0 END),0) AS high_risk,
                   COALESCE(SUM(CASE WHEN julianday(timestamp) >= julianday(?) - 1 THEN 1 ELSE 0 END),0) AS recent_24h,
                   MIN(timestamp) AS first_seen,
                   MAX(timestamp) AS last_seen
              FROM screening_events
             WHERE number_hash = ?
            """,
            (now_iso, number_hash),
        ).fetchone()
        screening_count = int(screening["calls_seen"] if screening else 0)

        if screening_count:
            recent_rows = self.database._conn.execute(
                """
                SELECT risk AS score, confidence, timestamp
                  FROM screening_events
                 WHERE number_hash = ?
                 ORDER BY timestamp DESC, id DESC
                 LIMIT ?
                """,
                (number_hash, limit),
            ).fetchall()
            values = {
                "calls_seen": screening_count,
                "calls_allowed": int(screening["allowed"]),
                "calls_rejected": int(screening["rejected"]),
                "block_recommendations": int(screening["blocks"]),
                "high_risk_detections": int(screening["high_risk"]),
                "recent_calls_24h": int(screening["recent_24h"]),
                "first_seen": screening["first_seen"],
                "last_seen": screening["last_seen"],
            }
        else:
            event = self.database._conn.execute(
                """
                SELECT COUNT(*) AS calls_seen,
                       COALESCE(SUM(CASE WHEN action='ALLOW' THEN 1 ELSE 0 END),0) AS allowed,
                       COALESCE(SUM(CASE WHEN action='BLOCK' THEN 1 ELSE 0 END),0) AS blocks,
                       COALESCE(SUM(CASE WHEN verdict IN ('HIGH_RISK','MALICIOUS') THEN 1 ELSE 0 END),0) AS high_risk,
                       COALESCE(SUM(CASE WHEN julianday(timestamp) >= julianday(?) - 1 THEN 1 ELSE 0 END),0) AS recent_24h,
                       MIN(timestamp) AS first_seen,
                       MAX(timestamp) AS last_seen
                  FROM events
                 WHERE number = ?
                """,
                (now_iso, normalized_number),
            ).fetchone()
            recent_rows = self.database._conn.execute(
                """
                SELECT risk_score AS score, confidence, timestamp
                  FROM events
                 WHERE number = ?
                 ORDER BY timestamp DESC, id DESC
                 LIMIT ?
                """,
                (normalized_number, limit),
            ).fetchall()
            values = {
                "calls_seen": int(event["calls_seen"] if event else 0),
                "calls_allowed": int(event["allowed"] if event else 0),
                "calls_rejected": 0,
                "block_recommendations": int(event["blocks"] if event else 0),
                "high_risk_detections": int(event["high_risk"] if event else 0),
                "recent_calls_24h": int(event["recent_24h"] if event else 0),
                "first_seen": event["first_seen"] if event else None,
                "last_seen": event["last_seen"] if event else None,
            }

        report_row = self.database._conn.execute(
            """
            SELECT COUNT(*) AS count, MIN(created_at) AS first_seen,
                   MAX(created_at) AS last_seen
              FROM reports WHERE number = ?
            """,
            (normalized_number,),
        ).fetchone()
        values["user_reports"] = int(report_row["count"] if report_row else 0)
        values["calls_answered"] = 0  # No call-duration/answer telemetry exists.
        values["recent_scores"] = [int(row["score"]) for row in recent_rows]
        values["recent_confidences"] = [int(row["confidence"]) for row in recent_rows]
        values["first_seen"] = _earliest(
            values.get("first_seen"), report_row["first_seen"] if report_row else None
        )
        values["last_seen"] = _latest(
            values.get("last_seen"), report_row["last_seen"] if report_row else None
        )
        return values

    def get_profile(self, number_hash: str) -> Optional[ReputationProfile]:
        row = self.database._conn.execute(
            "SELECT * FROM reputation_profiles WHERE number_hash = ?",
            (number_hash,),
        ).fetchone()
        if not row:
            return None
        try:
            signal_values = json.loads(row["signals_json"])
            reasons = json.loads(row["reasons_json"])
            if not isinstance(signal_values, list) or not isinstance(reasons, list):
                raise ValueError("profile JSON is not a list")
            signals = [ReputationSignal(**value) for value in signal_values[:20]]
        except Exception as exc:
            raise ReputationStorageError(f"Corrupt reputation profile: {exc}") from exc
        trust = self.get_trust(number_hash)
        return ReputationProfile(
            number_hash=row["number_hash"],
            number_masked=row["number_masked"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            calls_seen=int(row["calls_seen"]),
            calls_answered=int(row["calls_answered"]),
            calls_rejected=int(row["calls_rejected"]),
            calls_allowed=int(row["calls_allowed"]),
            block_recommendations=int(row["block_recommendations"]),
            user_reports=int(row["user_reports"]),
            risk_score=int(row["risk_score"]),
            confidence=int(row["confidence"]),
            risk=row["risk"],
            trend=row["trend"],
            trusted=trust is not None,
            trusted_until=trust.expires_at if trust else None,
            signals=signals,
            reasons=[str(reason) for reason in reasons[:20]],
        )

    def save_profile(self, profile: ReputationProfile, trigger: str) -> None:
        previous = self.get_profile(profile.number_hash)
        signals_json = json.dumps(
            [signal.to_dict() for signal in profile.signals[:20]],
            separators=(",", ":"),
            sort_keys=True,
        )
        reasons_json = json.dumps(profile.reasons[:20], separators=(",", ":"))
        if len(signals_json.encode("utf-8")) > 8192 or len(reasons_json.encode("utf-8")) > 4096:
            raise ReputationStorageError("Reputation explanation exceeds storage limits")

        with self.database.transaction():
            self.database._conn.execute(
                """
                INSERT INTO reputation_profiles
                    (number_hash, number_masked, first_seen, last_seen,
                     calls_seen, calls_answered, calls_rejected, calls_allowed,
                     block_recommendations, user_reports, risk_score, confidence,
                     risk, trend, signals_json, reasons_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(number_hash) DO UPDATE SET
                    number_masked=excluded.number_masked,
                    first_seen=excluded.first_seen,
                    last_seen=excluded.last_seen,
                    calls_seen=excluded.calls_seen,
                    calls_answered=excluded.calls_answered,
                    calls_rejected=excluded.calls_rejected,
                    calls_allowed=excluded.calls_allowed,
                    block_recommendations=excluded.block_recommendations,
                    user_reports=excluded.user_reports,
                    risk_score=excluded.risk_score,
                    confidence=excluded.confidence,
                    risk=excluded.risk,
                    trend=excluded.trend,
                    signals_json=excluded.signals_json,
                    reasons_json=excluded.reasons_json,
                    updated_at=excluded.updated_at
                """,
                (
                    profile.number_hash,
                    profile.number_masked,
                    profile.first_seen,
                    profile.last_seen,
                    profile.calls_seen,
                    profile.calls_answered,
                    profile.calls_rejected,
                    profile.calls_allowed,
                    profile.block_recommendations,
                    profile.user_reports,
                    profile.risk_score,
                    profile.confidence,
                    profile.risk,
                    profile.trend,
                    signals_json,
                    reasons_json,
                    _now_iso(),
                ),
            )
            old_score = previous.risk_score if previous else None
            old_risk = previous.risk if previous else None
            if meaningful_change(old_score, profile.risk_score, old_risk, profile.risk):
                self.database._conn.execute(
                    """
                    INSERT INTO reputation_history
                        (number_hash, timestamp, old_score, new_score,
                         risk_before, risk_after, trigger)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.number_hash,
                        _now_iso(),
                        old_score,
                        profile.risk_score,
                        old_risk,
                        profile.risk,
                        str(trigger)[:200],
                    ),
                )
            self._prune_history_locked(profile.number_hash)
            self._prune_profiles_locked()

    def history(self, number_hash: str, limit: Optional[int] = None) -> List[ReputationHistoryEntry]:
        bounded = min(
            int(limit or self.cfg.reputation_history_limit),
            int(self.cfg.reputation_history_limit),
        )
        rows = self.database._conn.execute(
            """
            SELECT timestamp, old_score, new_score, risk_before, risk_after, trigger
              FROM reputation_history
             WHERE number_hash = ?
             ORDER BY timestamp DESC, id DESC
             LIMIT ?
            """,
            (number_hash, max(1, bounded)),
        ).fetchall()
        return [
            ReputationHistoryEntry(
                timestamp=row["timestamp"],
                old_score=row["old_score"],
                new_score=int(row["new_score"]),
                risk_before=row["risk_before"],
                risk_after=row["risk_after"],
                trigger=row["trigger"],
            )
            for row in rows
        ]

    def recent_profiles(self, limit: int = 50) -> List[Dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        rows = self.database._conn.execute(
            """
            SELECT number_masked, risk, risk_score, confidence, trend, updated_at
              FROM reputation_profiles
             ORDER BY updated_at DESC
             LIMIT ?
            """,
            (bounded,),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_trust(
        self,
        number_hash: str,
        number_masked: str,
        *,
        expires_at: Optional[str],
        note: Optional[str] = None,
    ) -> TrustedRecord:
        now = _now_iso()
        with self.database.transaction():
            self._purge_expired_trust_locked(now)
            exists = self.database._conn.execute(
                "SELECT 1 FROM trusted_numbers WHERE number_hash = ?",
                (number_hash,),
            ).fetchone()
            if not exists:
                count = int(
                    self.database._conn.execute(
                        "SELECT COUNT(*) FROM trusted_numbers"
                    ).fetchone()[0]
                )
                if count >= int(self.cfg.trust_record_limit):
                    raise ReputationStorageError("Trust record limit reached")
            self.database._conn.execute(
                """
                INSERT INTO trusted_numbers
                    (number_hash, number_masked, created_at, expires_at, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(number_hash) DO UPDATE SET
                    number_masked=excluded.number_masked,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    note=excluded.note
                """,
                (
                    number_hash,
                    number_masked,
                    now,
                    expires_at,
                    str(note)[:200] if note else None,
                ),
            )
        return TrustedRecord(number_hash, number_masked, now, expires_at, note)

    def remove_trust(self, number_hash: str) -> bool:
        with self.database.transaction():
            cursor = self.database._conn.execute(
                "DELETE FROM trusted_numbers WHERE number_hash = ?", (number_hash,)
            )
            return cursor.rowcount == 1

    def get_trust(self, number_hash: str, now_iso: Optional[str] = None) -> Optional[TrustedRecord]:
        now = now_iso or _now_iso()
        row = self.database._conn.execute(
            "SELECT * FROM trusted_numbers WHERE number_hash = ?",
            (number_hash,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] is not None and row["expires_at"] <= now:
            with self.database.transaction():
                self.database._conn.execute(
                    "DELETE FROM trusted_numbers WHERE number_hash = ? AND expires_at <= ?",
                    (number_hash, now),
                )
            return None
        return TrustedRecord(
            number_hash=row["number_hash"],
            number_masked=row["number_masked"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            note=row["note"],
        )

    def integrity_check(self) -> bool:
        rows = self.database._conn.execute(
            "SELECT signals_json, reasons_json FROM reputation_profiles LIMIT ?",
            (int(self.cfg.reputation_profile_limit),),
        ).fetchall()
        try:
            for row in rows:
                signals = json.loads(row["signals_json"])
                reasons = json.loads(row["reasons_json"])
                if not isinstance(signals, list) or len(signals) > 20:
                    return False
                if not isinstance(reasons, list) or len(reasons) > 20:
                    return False
                if any(not isinstance(value, dict) for value in signals):
                    return False
                if any(not isinstance(value, str) for value in reasons):
                    return False
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        return True

    def _purge_expired_trust_locked(self, now: str) -> None:
        self.database._conn.execute(
            "DELETE FROM trusted_numbers WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )

    def _prune_history_locked(self, number_hash: str) -> None:
        limit = int(self.cfg.reputation_history_limit)
        self.database._conn.execute(
            """
            DELETE FROM reputation_history
             WHERE number_hash = ? AND id NOT IN (
                 SELECT id FROM reputation_history
                  WHERE number_hash = ? ORDER BY timestamp DESC, id DESC LIMIT ?
             )
            """,
            (number_hash, number_hash, limit),
        )

    def _prune_profiles_locked(self) -> None:
        limit = int(self.cfg.reputation_profile_limit)
        count = int(
            self.database._conn.execute(
                "SELECT COUNT(*) FROM reputation_profiles"
            ).fetchone()[0]
        )
        excess = count - limit
        if excess <= 0:
            return
        self.database._conn.execute(
            """
            DELETE FROM reputation_profiles
             WHERE number_hash IN (
                 SELECT p.number_hash FROM reputation_profiles p
                 LEFT JOIN trusted_numbers t ON t.number_hash = p.number_hash
                 WHERE t.number_hash IS NULL
                 ORDER BY p.updated_at ASC LIMIT ?
             )
            """,
            (excess,),
        )


def _earliest(*values: Optional[str]) -> Optional[str]:
    present = [value for value in values if value]
    return min(present) if present else None


def _latest(*values: Optional[str]) -> Optional[str]:
    present = [value for value in values if value]
    return max(present) if present else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
