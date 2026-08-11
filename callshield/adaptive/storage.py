"""Bounded SQLite storage for derived Phase 8 behavioral intelligence."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..database import Database
from .models import BehaviorObservation, IntelligenceSnapshot


class BehaviorStorageError(RuntimeError):
    pass


class BehaviorStorage:
    _write_lock = threading.RLock()

    def __init__(self, database: Database, cfg: Any) -> None:
        self.database = database
        self.cfg = cfg

    def add_observation(
        self,
        *,
        number_hash: str,
        number_masked: str,
        event_id: str,
        timestamp: str,
        event_type: str,
        risk_score: int,
        confidence: int,
        recommended_action: str = "UNKNOWN",
        applied_action: str = "UNKNOWN",
        confirmed: bool = False,
        source: str = "SYSTEM",
        trust_state: str = "UNKNOWN",
        trust_expires: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> bool:
        risk = max(0, min(100, int(risk_score)))
        conf = max(0, min(100, int(confidence)))
        if recommended_action not in ("ALLOW", "BLOCK", "UNKNOWN"):
            recommended_action = "UNKNOWN"
        if applied_action not in ("ALLOW", "BLOCK", "UNKNOWN"):
            applied_action = "UNKNOWN"
        if trust_state not in ("TRUSTED", "UNTRUSTED", "EXPIRED", "UNKNOWN"):
            trust_state = "UNKNOWN"
        payload = _bounded_json(evidence or {}, 4096)
        with self._write_lock, self.database.transaction():
            cursor = self.database._conn.execute(
                """
                INSERT OR IGNORE INTO intelligence_observations
                    (number_hash, number_masked, event_id, timestamp, event_type,
                     risk_score, confidence, recommended_action, applied_action,
                     confirmed, source, trust_state, trust_expires, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(number_hash)[:64],
                    str(number_masked)[:64],
                    str(event_id)[:64],
                    str(timestamp)[:64],
                    str(event_type)[:64],
                    risk,
                    conf,
                    recommended_action,
                    applied_action,
                    int(bool(confirmed)),
                    str(source)[:64],
                    trust_state,
                    str(trust_expires)[:64] if trust_expires else None,
                    payload,
                ),
            )
            self._cleanup_locked(str(number_hash)[:64])
            return cursor.rowcount == 1

    def cleanup(self, number_hash: str) -> None:
        with self._write_lock, self.database.transaction():
            self._cleanup_locked(str(number_hash)[:64])
            self._prune_profiles_locked()

    def update_outcome(
        self,
        event_id: str,
        *,
        recommended_action: str,
        applied_action: str,
    ) -> bool:
        if recommended_action not in ("ALLOW", "BLOCK"):
            recommended_action = "ALLOW"
        if applied_action not in ("ALLOW", "BLOCK"):
            applied_action = "ALLOW"
        with self._write_lock, self.database.transaction():
            cursor = self.database._conn.execute(
                """
                UPDATE intelligence_observations
                   SET recommended_action=?, applied_action=?
                 WHERE event_id=?
                """,
                (recommended_action, applied_action, str(event_id)[:64]),
            )
            return cursor.rowcount == 1

    def confirm(self, event_id: str) -> bool:
        with self._write_lock, self.database.transaction():
            cursor = self.database._conn.execute(
                """
                UPDATE intelligence_observations SET confirmed=1
                 WHERE event_id=? AND applied_action='BLOCK' AND confirmed=0
                """,
                (str(event_id)[:64],),
            )
            return cursor.rowcount == 1

    def timeline(self, number_hash: str, limit: Optional[int] = None) -> List[BehaviorObservation]:
        bounded = max(
            1,
            min(
                int(limit or self.cfg.intelligence_query_limit),
                int(self.cfg.intelligence_query_limit),
            ),
        )
        rows = self.database._conn.execute(
            """
            SELECT event_id, timestamp, event_type, risk_score, confidence,
                   recommended_action, applied_action, confirmed, source,
                   trust_state, trust_expires, evidence_json
              FROM intelligence_observations
             WHERE number_hash=?
             ORDER BY timestamp DESC, id DESC
             LIMIT ?
            """,
            (str(number_hash)[:64], bounded),
        ).fetchall()
        observations = []  # type: List[BehaviorObservation]
        try:
            for row in reversed(rows):
                evidence = json.loads(row["evidence_json"])
                if not isinstance(evidence, dict):
                    raise ValueError("observation evidence is not an object")
                observations.append(
                    BehaviorObservation(
                        event_id=row["event_id"],
                        timestamp=row["timestamp"],
                        event_type=row["event_type"],
                        risk_score=int(row["risk_score"]),
                        confidence=int(row["confidence"]),
                        recommended_action=row["recommended_action"],
                        applied_action=row["applied_action"],
                        confirmed=bool(row["confirmed"]),
                        source=row["source"],
                        trust_state=row["trust_state"],
                        trust_expires=row["trust_expires"],
                        evidence=evidence,
                    )
                )
        except Exception as exc:
            raise BehaviorStorageError(f"Corrupt intelligence timeline: {exc}") from exc
        return observations

    def profile_state(self, number_hash: str) -> Optional[Dict[str, Any]]:
        row = self.database._conn.execute(
            "SELECT * FROM intelligence_profiles WHERE number_hash=?",
            (str(number_hash)[:64],),
        ).fetchone()
        if not row:
            return None
        try:
            snapshot = json.loads(row["snapshot_json"])
            if not isinstance(snapshot, dict):
                raise ValueError("snapshot JSON is not an object")
        except Exception as exc:
            raise BehaviorStorageError(f"Corrupt intelligence snapshot: {exc}") from exc
        value = dict(row)
        value["snapshot"] = snapshot
        return value

    def save_snapshot(self, snapshot: IntelligenceSnapshot) -> None:
        public = snapshot.to_public_dict(include_history=False)
        payload = _bounded_json(public, 16 * 1024)
        now = _now_iso()
        with self._write_lock, self.database.transaction():
            self.database._conn.execute(
                """
                INSERT INTO intelligence_profiles
                    (number_hash, number_masked, baseline_score, current_score,
                     confidence, trend, risk_delta, confidence_delta,
                     snapshot_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(number_hash) DO UPDATE SET
                    number_masked=excluded.number_masked,
                    baseline_score=excluded.baseline_score,
                    current_score=excluded.current_score,
                    confidence=excluded.confidence,
                    trend=excluded.trend,
                    risk_delta=excluded.risk_delta,
                    confidence_delta=excluded.confidence_delta,
                    snapshot_json=excluded.snapshot_json,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot.number_hash,
                    snapshot.number_masked,
                    snapshot.baseline_score,
                    snapshot.current_score,
                    snapshot.reputation_confidence,
                    snapshot.behavioral_trend,
                    snapshot.risk_delta,
                    snapshot.confidence_delta,
                    payload,
                    now,
                ),
            )
            self._prune_profiles_locked()

    def recent_profiles(self, limit: int = 50) -> List[Dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        rows = self.database._conn.execute(
            """
            SELECT number_masked, current_score, confidence, trend,
                   risk_delta, updated_at
              FROM intelligence_profiles
             ORDER BY updated_at DESC LIMIT ?
            """,
            (bounded,),
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_report_count(self, normalized_number: str, now: datetime) -> int:
        cutoff = now - timedelta(days=int(self.cfg.intelligence_history_days))
        row = self.database._conn.execute(
            """
            SELECT COUNT(*) FROM reports
             WHERE number=? AND julianday(created_at) >= julianday(?)
            """,
            (normalized_number, cutoff.isoformat(timespec="seconds")),
        ).fetchone()
        return int(row[0] if row else 0)

    def integrity_check(self) -> bool:
        observation_rows = self.database._conn.execute(
            "SELECT evidence_json FROM intelligence_observations LIMIT ?",
            (int(self.cfg.intelligence_profile_limit),),
        ).fetchall()
        profile_rows = self.database._conn.execute(
            "SELECT snapshot_json FROM intelligence_profiles LIMIT ?",
            (int(self.cfg.intelligence_profile_limit),),
        ).fetchall()
        try:
            return all(
                isinstance(json.loads(row[0]), dict)
                for row in list(observation_rows) + list(profile_rows)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

    def last_trust_expiry(self, observations: List[BehaviorObservation]) -> Optional[str]:
        for item in reversed(observations):
            if item.event_type == "TRUST_ADDED" and item.trust_expires:
                return item.trust_expires
        return None

    def _cleanup_locked(self, number_hash: str) -> None:
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=int(self.cfg.intelligence_history_days))
        ).isoformat(timespec="seconds")
        self.database._conn.execute(
            "DELETE FROM intelligence_observations WHERE timestamp < ?",
            (cutoff,),
        )
        limit = int(self.cfg.intelligence_observation_limit)
        self.database._conn.execute(
            """
            DELETE FROM intelligence_observations
             WHERE number_hash=? AND id NOT IN (
                 SELECT id FROM intelligence_observations
                  WHERE number_hash=? ORDER BY timestamp DESC, id DESC LIMIT ?
             )
            """,
            (number_hash, number_hash, limit),
        )

    def _prune_profiles_locked(self) -> None:
        limit = int(self.cfg.intelligence_profile_limit)
        count = int(
            self.database._conn.execute(
                "SELECT COUNT(*) FROM intelligence_profiles"
            ).fetchone()[0]
        )
        excess = count - limit
        if excess > 0:
            self.database._conn.execute(
                """
                DELETE FROM intelligence_profiles WHERE number_hash IN (
                    SELECT number_hash FROM intelligence_profiles
                     ORDER BY updated_at ASC, number_hash ASC LIMIT ?
                )
                """,
                (excess,),
            )


def _bounded_json(value: Any, maximum: int) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > maximum:
        raise BehaviorStorageError("Intelligence JSON exceeds storage limit")
    return encoded


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
