"""SQLite database layer for CALLSHIELD.

All queries are parameterized. The schema is created automatically on first
connect. The layer exposes small, purpose-built methods used by the rest of the
engine — it is not a generic ORM.

Schema is migrated automatically from Phase 1 -> Phase 2 on first open.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from . import DATA_DIR
from .utils import DatabaseError, ensure_parent

DEFAULT_DB_PATH = DATA_DIR / "callshield.db"
SCHEMA_VERSION = 3


# ----- Schema --------------------------------------------------------------
# Phase 2 schema. Phase 1 databases are migrated on open.
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version  INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS numbers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       TEXT NOT NULL,
    list_type    TEXT NOT NULL CHECK (list_type IN ('blacklist','whitelist')),
    reputation   TEXT NOT NULL DEFAULT 'UNKNOWN'
                  CHECK (reputation IN ('UNKNOWN','SAFE','TRUSTED','SUSPICIOUS','HIGH_RISK','MALICIOUS','LOW','MEDIUM','HIGH','CRITICAL')),
    risk_score   INTEGER NOT NULL DEFAULT 0,
    reason       TEXT,
    first_seen   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (number, list_type)
);

CREATE INDEX IF NOT EXISTS idx_numbers_list_type ON numbers(list_type);
CREATE INDEX IF NOT EXISTS idx_numbers_number    ON numbers(number);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    number       TEXT NOT NULL,
    risk_score   INTEGER NOT NULL,
    confidence   INTEGER NOT NULL DEFAULT 0,
    reputation   TEXT NOT NULL DEFAULT 'UNKNOWN',
    risk_level   TEXT,
    verdict      TEXT NOT NULL,
    action       TEXT NOT NULL,
    reason       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_number    ON events(number);
CREATE INDEX IF NOT EXISTS idx_events_number_ts ON events(number, timestamp DESC);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       TEXT NOT NULL,
    reason       TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_number ON reports(number);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp          TEXT NOT NULL,
    number             TEXT NOT NULL,
    number_masked      TEXT,
    number_hash        TEXT,
    risk_score         INTEGER NOT NULL,
    confidence         INTEGER NOT NULL DEFAULT 0,
    verdict            TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    applied_action     TEXT NOT NULL,
    result_reason      TEXT,
    latency_ms         INTEGER,
    source             TEXT,
    event_id           TEXT
);

CREATE INDEX IF NOT EXISTS idx_screening_timestamp ON screening_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_screening_number    ON screening_events(number);

"""


# Phase 1 reputation labels -> Phase 2 labels.
_P1_REPUTATION_MAP = {
    "LOW": "SAFE",
    "MEDIUM": "SUSPICIOUS",
    "HIGH": "HIGH_RISK",
    "CRITICAL": "MALICIOUS",
    "UNKNOWN": "UNKNOWN",
}


class Database:
    """Thin wrapper around a SQLite connection with CALLSHIELD schema helpers."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB_PATH
        ensure_parent(self.path)
        try:
            self._conn = sqlite3.connect(
                str(self.path),
                check_same_thread=False,
            )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Unable to open database at {self.path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize()
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ----- setup & migrations --------------------------------------------
    def _initialize(self) -> None:
        try:
            self._conn.executescript(SCHEMA)
            self._migrate()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database initialization failed: {exc}") from exc

    def _migrate(self) -> None:
        """Bring the schema up to SCHEMA_VERSION. Preserves all user data."""
        cur = self._conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        current_version = int(row["version"]) if row else 0

        # If no version recorded, detect Phase-1-shaped DB (numbers table
        # exists but lacks first_seen).
        needs_detection = (current_version == 0)
        if needs_detection:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(numbers)")}
            if cols and "first_seen" not in cols:
                current_version = 1
            else:
                # Brand-new or already-current DB. Stamp and exit.
                with self._conn:
                    self._conn.execute("DELETE FROM schema_version")
                    self._conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                return

        if current_version >= SCHEMA_VERSION:
            return

        # Safety: make a backup before migrating.
        try:
            backup_path = self.path.with_suffix(self.path.suffix + f".v{current_version}.bak")
            if not backup_path.exists():
                shutil.copy2(self.path, backup_path)
        except OSError:
            pass

        try:
            if current_version <= 1:
                self._migrate_v1_to_v2()
            if current_version <= 2:
                self._migrate_v2_to_v3()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database migration to v{SCHEMA_VERSION} failed: {exc}") from exc

        with self._conn:
            self._conn.execute("DELETE FROM schema_version")
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def _migrate_v1_to_v2(self) -> None:
        # 1. The `numbers` table's reputation CHECK constraint needs expanding.
        #    SQLite doesn't support ALTER COLUMN CHECK, so rebuild the table.
        #    Also adds `first_seen` column.
        assert self._conn is not None
        existing_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(numbers)")}

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with self._conn:
            # Create new numbers table.
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS numbers_new (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    number       TEXT NOT NULL,
                    list_type    TEXT NOT NULL CHECK (list_type IN ('blacklist','whitelist')),
                    reputation   TEXT NOT NULL DEFAULT 'UNKNOWN',
                    risk_score   INTEGER NOT NULL DEFAULT 0,
                    reason       TEXT,
                    first_seen   TEXT,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    UNIQUE (number, list_type)
                )
                """
            )
            # Copy rows, mapping old reputation values to new labels. Fill
            # first_seen with created_at if present, else now.
            rows = self._conn.execute(
                "SELECT id, number, list_type, reputation, risk_score, reason, created_at, updated_at FROM numbers"
            ).fetchall()
            for r in rows:
                new_rep = _P1_REPUTATION_MAP.get(r["reputation"], "UNKNOWN")
                # Whitelisted numbers should be TRUSTED/SAFE.
                if r["list_type"] == "whitelist":
                    new_rep = "TRUSTED"
                first_seen = r["created_at"] or now_iso
                self._conn.execute(
                    """
                    INSERT INTO numbers_new
                        (id, number, list_type, reputation, risk_score, reason, first_seen, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["id"], r["number"], r["list_type"], new_rep,
                        r["risk_score"], r["reason"], first_seen,
                        r["created_at"] or now_iso, r["updated_at"] or now_iso,
                    ),
                )
            self._conn.execute("DROP TABLE numbers")
            self._conn.execute("ALTER TABLE numbers_new RENAME TO numbers")
            # Recreate indexes.
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_numbers_list_type ON numbers(list_type)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_numbers_number ON numbers(number)"
            )

            # 2. Expand events table with `confidence`, `reputation`, `risk_level`.
            events_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)")}
            if "confidence" not in events_cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN confidence INTEGER NOT NULL DEFAULT 0"
                )
            if "reputation" not in events_cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN reputation TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )
            if "risk_level" not in events_cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN risk_level TEXT"
                )
            # Back-fill reputation / risk_level for any existing rows that
            # still have the defaults (i.e. Phase 1 rows).
            self._conn.execute(
                """
                UPDATE events SET reputation = CASE
                    WHEN verdict = 'SAFE'                            THEN 'SAFE'
                    WHEN verdict IN ('UNKNOWN','LOW_RISK')           THEN 'UNKNOWN'
                    WHEN verdict = 'MEDIUM_RISK'                     THEN 'SUSPICIOUS'
                    WHEN verdict = 'HIGH_RISK'                       THEN 'HIGH_RISK'
                    WHEN verdict IN ('MALICIOUS','CRITICAL')         THEN 'MALICIOUS'
                    ELSE reputation
                END
                WHERE reputation = 'UNKNOWN'
                """
            )
            self._conn.execute(
                """
                UPDATE events SET risk_level = CASE
                    WHEN risk_score >= 80 THEN 'CRITICAL'
                    WHEN risk_score >= 60 THEN 'HIGH'
                    WHEN risk_score >= 30 THEN 'MEDIUM'
                    WHEN risk_score >   0 THEN 'LOW'
                    ELSE 'UNKNOWN'
                END
                WHERE risk_level IS NULL
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_number_ts ON events(number, timestamp DESC)"
            )

    def _migrate_v2_to_v3(self) -> None:
        # Add screening_events table for Phase 4
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS screening_events (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp          TEXT NOT NULL,
                    number             TEXT NOT NULL,
                    number_masked      TEXT,
                    number_hash        TEXT,
                    risk_score         INTEGER NOT NULL,
                    confidence         INTEGER NOT NULL DEFAULT 0,
                    verdict            TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    applied_action     TEXT NOT NULL,
                    result_reason      TEXT,
                    latency_ms         INTEGER,
                    source             TEXT,
                    event_id           TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_timestamp ON screening_events(timestamp DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_number ON screening_events(number)"
            )

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    # ----- numbers --------------------------------------------------------
    def upsert_list_entry(
        self,
        number: str,
        list_type: str,
        reason: Optional[str],
        now_iso: str,
    ) -> str:
        """Insert or refresh a number in the specified list.

        A number may exist in BOTH lists simultaneously (the detector applies
        WHITELIST > BLACKLIST precedence and reports the conflict).

        Returns ``"inserted"`` or ``"exists"``.
        """
        assert list_type in ("blacklist", "whitelist")
        existing_in_list = self._get_number_in_list(number, list_type)
        with self.transaction():
            if existing_in_list:
                self._conn.execute(
                    "UPDATE numbers SET reason = COALESCE(?, reason), updated_at = ? "
                    "WHERE number = ? AND list_type = ?",
                    (reason, now_iso, number, list_type),
                )
                return "exists"
            default_rep = "TRUSTED" if list_type == "whitelist" else "MALICIOUS"
            default_score = 0 if list_type == "whitelist" else 100
            self._conn.execute(
                """
                INSERT INTO numbers
                    (number, list_type, reputation, risk_score, reason, first_seen, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    number, list_type, default_rep, default_score, reason,
                    now_iso, now_iso, now_iso,
                ),
            )
            return "inserted"

    def _get_number_in_list(self, number: str, list_type: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM numbers WHERE number = ? AND list_type = ?",
            (number, list_type),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def remove_from_list(self, number: str, list_type: str) -> bool:
        assert list_type in ("blacklist", "whitelist")
        with self.transaction():
            cur = self._conn.execute(
                "DELETE FROM numbers WHERE number = ? AND list_type = ?",
                (number, list_type),
            )
            return cur.rowcount > 0

    def get_list_entry(self, number: str, list_type: str) -> Optional[Dict[str, Any]]:
        return self._get_number_in_list(number, list_type)

    def get_number(self, number: str) -> Optional[Dict[str, Any]]:
        # Backwards-compat: return any row for the number (prefer blacklist
        # over whitelist only because Phase 1 used a UNIQUE constraint — since
        # Phase 2 allows coexistence we return the "most recent by updated_at").
        cur = self._conn.execute(
            "SELECT * FROM numbers WHERE number = ? ORDER BY updated_at DESC LIMIT 1",
            (number,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_numbers(self, list_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if list_type:
            cur = self._conn.execute(
                "SELECT * FROM numbers WHERE list_type = ? ORDER BY updated_at DESC",
                (list_type,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM numbers ORDER BY list_type, updated_at DESC"
            )
        return [dict(r) for r in cur.fetchall()]

    def get_first_seen(self, number: str) -> Optional[str]:
        """Return earliest known timestamp for a number (from numbers or events)."""
        cur = self._conn.execute(
            "SELECT MIN(ts) AS earliest FROM ("
            "  SELECT MIN(first_seen) AS ts FROM numbers WHERE number = ?"
            "  UNION ALL"
            "  SELECT MIN(created_at) AS ts FROM numbers WHERE number = ?"
            "  UNION ALL"
            "  SELECT MIN(timestamp) AS ts FROM events WHERE number = ?"
            "  UNION ALL"
            "  SELECT MIN(created_at) AS ts FROM reports WHERE number = ?"
            ")",
            (number, number, number, number),
        )
        row = cur.fetchone()
        return row["earliest"] if row and row["earliest"] else None

    def get_last_seen(self, number: str) -> Optional[str]:
        cur = self._conn.execute(
            "SELECT MAX(ts) AS latest FROM ("
            "  SELECT MAX(updated_at) AS ts FROM numbers WHERE number = ?"
            "  UNION ALL"
            "  SELECT MAX(timestamp) AS ts FROM events WHERE number = ?"
            "  UNION ALL"
            "  SELECT MAX(created_at) AS ts FROM reports WHERE number = ?"
            ")",
            (number, number, number),
        )
        row = cur.fetchone()
        return row["latest"] if row and row["latest"] else None

    # ----- events ---------------------------------------------------------
    def add_event(
        self,
        timestamp: str,
        number: str,
        risk_score: int,
        verdict: str,
        action: str,
        reason: Optional[str],
        *,
        confidence: int = 0,
        reputation: str = "UNKNOWN",
        risk_level: Optional[str] = None,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO events
                    (timestamp, number, risk_score, confidence, reputation, risk_level, verdict, action, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, number, int(risk_score), int(confidence),
                 reputation, risk_level, verdict, action, reason),
            )
            return int(cur.lastrowid)

    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        cur = self._conn.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_events_for_number(
        self, number: str, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 10000))
        cur = self._conn.execute(
            "SELECT * FROM events WHERE number = ? ORDER BY timestamp DESC LIMIT ?",
            (number, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_events_for_number(
        self, number: str, verdict_match: Optional[Sequence[str]] = None
    ) -> int:
        if verdict_match:
            placeholders = ",".join("?" * len(verdict_match))
            cur = self._conn.execute(
                f"SELECT COUNT(*) FROM events WHERE number = ? AND verdict IN ({placeholders})",
                (number, *verdict_match),
            )
        else:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE number = ?", (number,)
            )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def recent_event_window_count(
        self, number: str, window_seconds: int, reference_ts: Optional[str] = None
    ) -> int:
        """Count events for ``number`` within ``window_seconds`` before ``reference_ts``."""
        # Implemented portably using julianday timestamps so we don't depend on
        # SQLite being built with a particular date format.
        ref = reference_ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self._conn.execute(
            """
            SELECT COUNT(*) FROM events
             WHERE number = ?
               AND julianday(?) - julianday(timestamp) < ?
            """,
            (number, ref, window_seconds / 86400.0),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    # ----- reports --------------------------------------------------------
    def add_report(self, number: str, reason: Optional[str], now_iso: str) -> int:
        reason_clean = (reason or "").strip()
        reason_clean = reason_clean[:500] if reason_clean else None
        with self.transaction():
            cur = self._conn.execute(
                "INSERT INTO reports (number, reason, created_at) VALUES (?, ?, ?)",
                (number, reason_clean, now_iso),
            )
            return int(cur.lastrowid)

    def count_reports(self, number: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM reports WHERE number = ?", (number,)
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_reports(self, number: str, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM reports WHERE number = ? ORDER BY created_at DESC LIMIT ?",
            (number, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    # ----- screening events (Phase 4) ---------------------------------------
    def add_screening_event(
        self,
        timestamp: str,
        number: str,
        risk_score: int,
        confidence: int,
        verdict: str,
        recommended_action: str,
        applied_action: str,
        result_reason: Optional[str] = None,
        latency_ms: Optional[int] = None,
        source: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> int:
        # Mask and hash for privacy
        try:
            from .utils import mask_number
            masked = mask_number(number)
        except Exception:
            masked = number[:4] + "***" + number[-4:] if len(number) > 8 else "***"
        try:
            h = hashlib.sha256(number.encode()).hexdigest()[:16]
        except Exception:
            h = None
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO screening_events
                    (timestamp, number, number_masked, number_hash, risk_score, confidence, verdict, recommended_action, applied_action, result_reason, latency_ms, source, event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, number, masked, h, int(risk_score), int(confidence), verdict, recommended_action, applied_action, result_reason, latency_ms, source, event_id),
            )
            return int(cur.lastrowid)

    def recent_screening_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        cur = self._conn.execute(
            "SELECT * FROM screening_events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_screening_events(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM screening_events")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def screening_metrics(self) -> Dict[str, Any]:
        cur = self._conn.execute("SELECT COUNT(*) as total FROM screening_events")
        total = int(cur.fetchone()[0] or 0)
        cur = self._conn.execute("SELECT COUNT(*) FROM screening_events WHERE verdict IN ('HIGH_RISK','MALICIOUS','CRITICAL')")
        high = int(cur.fetchone()[0] or 0)
        cur = self._conn.execute("SELECT COUNT(*) FROM screening_events WHERE recommended_action='BLOCK'")
        block_rec = int(cur.fetchone()[0] or 0)
        cur = self._conn.execute("SELECT COUNT(*) FROM screening_events WHERE applied_action='BLOCK'")
        actually_rejected = int(cur.fetchone()[0] or 0)
        cur = self._conn.execute("SELECT COUNT(*) FROM screening_events WHERE result_reason='SCREENING_TIMEOUT'")
        timeouts = int(cur.fetchone()[0] or 0)
        return {
            "total": total,
            "high_risk": high,
            "block_recommended": block_rec,
            "actually_rejected": actually_rejected,
            "timeouts": timeouts,
        }

    # ----- settings -------------------------------------------------------
    def get_setting(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction():
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
