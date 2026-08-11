"""SQLite database layer for CALLSHIELD.

All queries are parameterized. The schema is created automatically on first
connect. The layer exposes small, purpose-built methods used by the rest of the
engine — it is not a generic ORM.

Schema is migrated automatically through Phase 5 on first open.
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
from .utils import DatabaseError, ensure_parent, mask_number

DEFAULT_DB_PATH = DATA_DIR / "callshield.db"
SCHEMA_VERSION = 5


# ----- Schema --------------------------------------------------------------
# Current schema. Earlier databases are migrated on open.
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
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT NOT NULL,
    number               TEXT NOT NULL,
    number_masked        TEXT NOT NULL,
    number_hash          TEXT NOT NULL,
    risk                 INTEGER NOT NULL CHECK (risk BETWEEN 0 AND 100),
    confidence           INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    verdict              TEXT NOT NULL,
    recommended_action   TEXT NOT NULL
                           CHECK (recommended_action IN ('ALLOW','BLOCK')),
    applied_action       TEXT NOT NULL DEFAULT 'ALLOW'
                           CHECK (applied_action IN ('ALLOW','BLOCK')),
    reason               TEXT,
    latency_ms           INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    source               TEXT NOT NULL,
    event_id             TEXT NOT NULL,
    mode                 TEXT NOT NULL DEFAULT 'DRY_RUN'
                           CHECK (mode IN ('DRY_RUN','ACTIVE')),
    policy_action        TEXT NOT NULL DEFAULT 'ALLOW'
                           CHECK (policy_action IN ('ALLOW','BLOCK')),
    policy_name          TEXT NOT NULL DEFAULT 'BALANCED'
                           CHECK (policy_name IN ('RELAXED','BALANCED','STRICT')),
    threshold            INTEGER NOT NULL DEFAULT 85 CHECK (threshold BETWEEN 0 AND 100),
    confidence_threshold INTEGER NOT NULL DEFAULT 80
                           CHECK (confidence_threshold BETWEEN 0 AND 100),
    policy_reason        TEXT,
    emergency_off        INTEGER NOT NULL DEFAULT 0 CHECK (emergency_off IN (0,1)),
    actually_rejected    INTEGER NOT NULL DEFAULT 0 CHECK (actually_rejected IN (0,1)),
    rejection_confirmed_at TEXT,
    CHECK (applied_action = 'ALLOW' OR (mode = 'ACTIVE' AND policy_action = 'BLOCK'))
);

CREATE INDEX IF NOT EXISTS idx_screening_timestamp
    ON screening_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_screening_hash
    ON screening_events(number_hash);
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

    def __init__(
        self, path: Optional[Path] = None, *, timeout: float = 5.0
    ) -> None:
        self.path = Path(path) if path else DEFAULT_DB_PATH
        ensure_parent(self.path)
        connect_timeout = max(0.01, min(float(timeout), 30.0))
        try:
            self._conn = sqlite3.connect(
                str(self.path),
                check_same_thread=False,
                timeout=connect_timeout,
            )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Unable to open database at {self.path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute(f"PRAGMA busy_timeout = {int(connect_timeout * 1000)}")
            journal_row = self._conn.execute("PRAGMA journal_mode = WAL").fetchone()
            journal_mode = str(journal_row[0] if journal_row else "").lower()
            if journal_mode != "wal":
                raise DatabaseError(f"SQLite WAL mode unavailable at {self.path}")
            self._conn.execute("PRAGMA synchronous = FULL")
            self._initialize()
            self.validate_schema()
        except (sqlite3.Error, DatabaseError) as exc:
            self._conn.close()
            if isinstance(exc, DatabaseError):
                raise
            raise DatabaseError(f"Database setup failed at {self.path}: {exc}") from exc
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ----- setup & migrations --------------------------------------------
    def _initialize(self) -> None:
        try:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._ensure_phase6_indexes()
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
            if current_version <= 3:
                self._migrate_v3_to_v4()
            if current_version <= 4:
                self._migrate_v4_to_v5()
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
        """Add the Phase 4 dry-run screening audit table."""

        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS screening_events (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp          TEXT NOT NULL,
                    number             TEXT NOT NULL,
                    number_masked      TEXT NOT NULL,
                    number_hash        TEXT NOT NULL,
                    risk               INTEGER NOT NULL CHECK (risk BETWEEN 0 AND 100),
                    confidence         INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
                    verdict            TEXT NOT NULL,
                    recommended_action TEXT NOT NULL
                                         CHECK (recommended_action IN ('ALLOW','BLOCK','UNKNOWN')),
                    applied_action     TEXT NOT NULL DEFAULT 'ALLOW'
                                         CHECK (applied_action = 'ALLOW'),
                    reason             TEXT,
                    latency_ms         INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
                    source             TEXT NOT NULL,
                    event_id           TEXT NOT NULL,
                    mode               TEXT NOT NULL DEFAULT 'DRY_RUN'
                                         CHECK (mode = 'DRY_RUN')
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_timestamp "
                "ON screening_events(timestamp DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_hash "
                "ON screening_events(number_hash)"
            )

    def _migrate_v3_to_v4(self) -> None:
        """Rebuild Phase 4 screening rows with Phase 5 policy fields."""

        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(screening_events)")
        }
        if "policy_name" in columns and "actually_rejected" in columns:
            return
        with self._conn:
            self._conn.execute("DROP TABLE IF EXISTS screening_events_v4")
            self._conn.execute(
                """
                CREATE TABLE screening_events_v4 (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp            TEXT NOT NULL,
                    number               TEXT NOT NULL,
                    number_masked        TEXT NOT NULL,
                    number_hash          TEXT NOT NULL,
                    risk                 INTEGER NOT NULL CHECK (risk BETWEEN 0 AND 100),
                    confidence           INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
                    verdict              TEXT NOT NULL,
                    recommended_action   TEXT NOT NULL
                                             CHECK (recommended_action IN ('ALLOW','BLOCK')),
                    applied_action       TEXT NOT NULL DEFAULT 'ALLOW'
                                             CHECK (applied_action IN ('ALLOW','BLOCK')),
                    reason               TEXT,
                    latency_ms           INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
                    source               TEXT NOT NULL,
                    event_id             TEXT NOT NULL,
                    mode                 TEXT NOT NULL DEFAULT 'DRY_RUN'
                                             CHECK (mode IN ('DRY_RUN','ACTIVE')),
                    policy_action        TEXT NOT NULL DEFAULT 'ALLOW'
                                             CHECK (policy_action IN ('ALLOW','BLOCK')),
                    policy_name          TEXT NOT NULL DEFAULT 'BALANCED'
                                             CHECK (policy_name IN ('RELAXED','BALANCED','STRICT')),
                    threshold            INTEGER NOT NULL DEFAULT 85 CHECK (threshold BETWEEN 0 AND 100),
                    confidence_threshold INTEGER NOT NULL DEFAULT 80
                                             CHECK (confidence_threshold BETWEEN 0 AND 100),
                    policy_reason        TEXT,
                    emergency_off        INTEGER NOT NULL DEFAULT 0 CHECK (emergency_off IN (0,1)),
                    actually_rejected    INTEGER NOT NULL DEFAULT 0 CHECK (actually_rejected IN (0,1)),
                    rejection_confirmed_at TEXT,
                    CHECK (applied_action = 'ALLOW' OR (mode = 'ACTIVE' AND policy_action = 'BLOCK'))
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO screening_events_v4
                    (id, timestamp, number, number_masked, number_hash, risk,
                     confidence, verdict, recommended_action, applied_action,
                     reason, latency_ms, source, event_id, mode, policy_action,
                     policy_name, threshold, confidence_threshold, policy_reason,
                     emergency_off, actually_rejected)
                SELECT id, timestamp, number, number_masked, number_hash, risk,
                       confidence, verdict,
                       CASE WHEN recommended_action = 'BLOCK' THEN 'BLOCK' ELSE 'ALLOW' END,
                       'ALLOW', reason, latency_ms, source, event_id, 'DRY_RUN',
                       CASE WHEN recommended_action = 'BLOCK' THEN 'BLOCK' ELSE 'ALLOW' END,
                       'BALANCED', 85, 80, reason, 0, 0
                  FROM screening_events
                """
            )
            self._conn.execute("DROP TABLE screening_events")
            self._conn.execute(
                "ALTER TABLE screening_events_v4 RENAME TO screening_events"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_timestamp "
                "ON screening_events(timestamp DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_hash "
                "ON screening_events(number_hash)"
            )

    def _migrate_v4_to_v5(self) -> None:
        """Add Phase 6 lookup indexes without rewriting user rows."""

        self._ensure_phase6_indexes()

    def _ensure_phase6_indexes(self) -> None:
        with self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_event_id "
                "ON screening_events(event_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_applied "
                "ON screening_events(applied_action, timestamp DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screening_policy_action "
                "ON screening_events(policy_action, timestamp DESC)"
            )

    def integrity_check(self, *, quick: bool = False) -> bool:
        pragma = "quick_check" if quick else "integrity_check"
        try:
            rows = self._conn.execute(f"PRAGMA {pragma}").fetchall()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database integrity check failed: {exc}") from exc
        if not rows or any(str(row[0]).lower() != "ok" for row in rows):
            details = "; ".join(str(row[0]) for row in rows[:10]) or "no result"
            raise DatabaseError(f"Database corruption detected: {details}")
        return True

    def validate_schema(self) -> bool:
        required_tables = {
            "schema_version",
            "numbers",
            "events",
            "reports",
            "settings",
            "screening_events",
        }
        tables = {
            str(row[0])
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = required_tables - tables
        if missing:
            raise DatabaseError(f"Database schema missing tables: {', '.join(sorted(missing))}")
        version_row = self._conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        if not version_row or int(version_row[0]) != SCHEMA_VERSION:
            raise DatabaseError("Database schema version is invalid")
        screening_columns = {
            str(row[1])
            for row in self._conn.execute(
                "PRAGMA table_info(screening_events)"
            ).fetchall()
        }
        required_columns = {
            "id",
            "timestamp",
            "number_masked",
            "number_hash",
            "risk",
            "confidence",
            "policy_name",
            "policy_action",
            "applied_action",
            "event_id",
            "actually_rejected",
        }
        if required_columns - screening_columns:
            raise DatabaseError("Database screening schema is incomplete")
        screening_indexes = {
            str(row[1])
            for row in self._conn.execute(
                "PRAGMA index_list(screening_events)"
            ).fetchall()
        }
        required_indexes = {
            "idx_screening_timestamp",
            "idx_screening_hash",
            "idx_screening_event_id",
            "idx_screening_applied",
            "idx_screening_policy_action",
        }
        if required_indexes - screening_indexes:
            raise DatabaseError("Database screening indexes are incomplete")
        foreign_keys = self._conn.execute("PRAGMA foreign_keys").fetchone()
        if not foreign_keys or int(foreign_keys[0]) != 1:
            raise DatabaseError("SQLite foreign_keys is not enabled")
        journal = self._conn.execute("PRAGMA journal_mode").fetchone()
        if not journal or str(journal[0]).lower() != "wal":
            raise DatabaseError("SQLite WAL mode is not enabled")
        return True

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
        except Exception as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            if isinstance(exc, sqlite3.Error):
                raise DatabaseError(f"Database transaction failed: {exc}") from exc
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

    def event_metrics(self, high_risk_threshold: int = 60) -> Dict[str, int]:
        """Return persisted analysis counters for stopped-daemon reporting."""

        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE
                    WHEN risk_score >= ?
                      OR reputation IN ('HIGH_RISK', 'MALICIOUS')
                      OR risk_level IN ('HIGH', 'CRITICAL')
                    THEN 1 ELSE 0 END), 0) AS high_risk,
                COALESCE(SUM(CASE WHEN action = 'BLOCK' THEN 1 ELSE 0 END), 0)
                    AS block_recommendations
            FROM events
            """,
            (int(high_risk_threshold),),
        ).fetchone()
        return {
            "total": int(row["total"] if row else 0),
            "high_risk": int(row["high_risk"] if row else 0),
            "block_recommendations": int(
                row["block_recommendations"] if row else 0
            ),
        }

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

    # ----- screening events (Phase 4) ------------------------------------
    def add_screening_event(
        self,
        *,
        timestamp: str,
        number: str,
        risk_score: int,
        confidence: int,
        verdict: str,
        recommended_action: str,
        applied_action: str = "ALLOW",
        reason: Optional[str] = None,
        latency_ms: int = 0,
        source: str = "android_call_screening",
        event_id: str,
        mode: str = "DRY_RUN",
        policy_action: Optional[str] = None,
        policy_name: str = "BALANCED",
        threshold: int = 85,
        confidence_threshold: int = 80,
        policy_reason: Optional[str] = None,
        emergency_off: bool = False,
    ) -> int:
        """Persist one policy-screening result with privacy metadata."""

        recommendation = str(recommended_action)
        applied = str(applied_action)
        selected_mode = str(mode)
        selected_policy = str(policy_name)
        policy_recommendation = str(policy_action or recommendation)
        if recommendation not in ("ALLOW", "BLOCK"):
            raise ValueError("Invalid screening recommendation")
        if policy_recommendation not in ("ALLOW", "BLOCK"):
            raise ValueError("Invalid policy action")
        if applied not in ("ALLOW", "BLOCK"):
            raise ValueError("Invalid applied screening action")
        if selected_mode not in ("DRY_RUN", "ACTIVE"):
            raise ValueError("Invalid screening mode")
        if applied == "BLOCK" and selected_mode != "ACTIVE":
            raise ValueError("BLOCK may only be persisted in ACTIVE mode")
        if applied == "BLOCK" and (
            recommendation != "BLOCK" or policy_recommendation != "BLOCK"
        ):
            raise ValueError("Applied BLOCK requires a policy BLOCK recommendation")
        if applied == "BLOCK" and emergency_off:
            raise ValueError("Emergency-off cannot persist a BLOCK action")
        if selected_policy not in ("RELAXED", "BALANCED", "STRICT"):
            raise ValueError("Invalid policy name")
        risk = int(risk_score)
        conf = int(confidence)
        latency = int(latency_ms)
        active_threshold = int(threshold)
        confidence_limit = int(confidence_threshold)
        for value, label in (
            (risk, "risk"),
            (conf, "confidence"),
            (active_threshold, "threshold"),
            (confidence_limit, "confidence threshold"),
        ):
            if not (0 <= value <= 100):
                raise ValueError(f"Screening {label} must be between 0 and 100")
        if latency < 0:
            raise ValueError("Screening latency cannot be negative")
        raw_number = str(number or "")[:128]
        masked = mask_number(raw_number)
        number_hash = hashlib.sha256(raw_number.encode("utf-8")).hexdigest()
        clean_reason = str(reason or "")[:500] or None
        clean_policy_reason = str(policy_reason or clean_reason or "")[:500] or None
        clean_source = str(source or "android_call_screening")[:64]
        clean_event_id = str(event_id)[:64]
        with self.transaction():
            cursor = self._conn.execute(
                """
                INSERT INTO screening_events
                    (timestamp, number, number_masked, number_hash, risk,
                     confidence, verdict, recommended_action, applied_action,
                     reason, latency_ms, source, event_id, mode, policy_action,
                     policy_name, threshold, confidence_threshold, policy_reason,
                     emergency_off, actually_rejected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    timestamp,
                    raw_number,
                    masked,
                    number_hash,
                    risk,
                    conf,
                    str(verdict or "UNKNOWN")[:32],
                    recommendation,
                    applied,
                    clean_reason,
                    latency,
                    clean_source,
                    clean_event_id,
                    selected_mode,
                    policy_recommendation,
                    selected_policy,
                    active_threshold,
                    confidence_limit,
                    clean_policy_reason,
                    int(bool(emergency_off)),
                ),
            )
            return int(cursor.lastrowid)

    def recent_screening_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 1000))
        cursor = self._conn.execute(
            "SELECT * FROM screening_events ORDER BY timestamp DESC, id DESC LIMIT ?",
            (bounded_limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def count_screening_events(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM screening_events"
        ).fetchone()
        return int(row["count"] if row else 0)

    def screening_event_exists(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM screening_events WHERE event_id = ? LIMIT 1",
            (str(event_id)[:64],),
        ).fetchone()
        return row is not None

    def confirm_screening_rejection(
        self, event_id: str, confirmed_at: str
    ) -> bool:
        """Mark actual rejection only for a persisted ACTIVE applied block."""

        with self.transaction():
            cursor = self._conn.execute(
                """
                UPDATE screening_events
                   SET actually_rejected = 1,
                       rejection_confirmed_at = ?
                 WHERE event_id = ?
                   AND applied_action = 'BLOCK'
                   AND mode = 'ACTIVE'
                   AND actually_rejected = 0
                """,
                (confirmed_at, str(event_id)[:64]),
            )
            return cursor.rowcount == 1

    def screening_metrics(self) -> Dict[str, int]:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS incoming_calls,
                COUNT(*) AS screened,
                COALESCE(SUM(CASE WHEN reason = 'SCREENING_TIMEOUT' THEN 1 ELSE 0 END), 0)
                    AS timeouts,
                COALESCE(SUM(CASE WHEN policy_reason IN
                    ('INVALID_POLICY_CONFIG','INVALID_SCREENING_MODE','INVALID_ACTIVATION_STATE')
                    THEN 1 ELSE 0 END), 0) AS policy_errors,
                COALESCE(SUM(CASE WHEN reason IN ('ANALYSIS_ERROR','INTERNAL_ERROR') THEN 1 ELSE 0 END), 0)
                    AS bridge_errors,
                COALESCE(SUM(CASE WHEN verdict IN ('HIGH_RISK','MALICIOUS') THEN 1 ELSE 0 END), 0)
                    AS high_risk,
                COALESCE(SUM(CASE WHEN applied_action = 'ALLOW' THEN 1 ELSE 0 END), 0)
                    AS screening_allowed,
                COALESCE(SUM(CASE WHEN verdict = 'UNKNOWN' THEN 1 ELSE 0 END), 0)
                    AS screening_unknown,
                COALESCE(SUM(CASE WHEN policy_action = 'BLOCK' THEN 1 ELSE 0 END), 0)
                    AS screening_block_recommended,
                COALESCE(SUM(CASE WHEN applied_action = 'BLOCK' THEN 1 ELSE 0 END), 0)
                    AS screening_blocked,
                COALESCE(SUM(actually_rejected), 0) AS actually_rejected
            FROM screening_events
            """
        ).fetchone()
        keys = (
            "incoming_calls",
            "screened",
            "timeouts",
            "policy_errors",
            "bridge_errors",
            "high_risk",
            "screening_allowed",
            "screening_unknown",
            "screening_block_recommended",
            "screening_blocked",
            "actually_rejected",
        )
        metrics = {key: int(row[key] if row else 0) for key in keys}
        metrics["total"] = metrics["incoming_calls"]
        metrics["block_recommended"] = metrics["screening_block_recommended"]
        return metrics

    def recent_blocks(self, limit: int = 20) -> List[Dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        rows = self._conn.execute(
            """
            SELECT id, timestamp, number_masked, risk, confidence, policy_name,
                   recommended_action, applied_action, reason,
                   actually_rejected, rejection_confirmed_at
              FROM screening_events
             WHERE applied_action = 'BLOCK'
             ORDER BY timestamp DESC, id DESC
             LIMIT ?
            """,
            (bounded,),
        ).fetchall()
        return [dict(row) for row in rows]

    def inspect_block(self, block_id: int) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            """
            SELECT id, timestamp, number_masked, risk, confidence, policy_name,
                   threshold, confidence_threshold, recommended_action,
                   applied_action, reason, policy_reason, emergency_off,
                   actually_rejected, rejection_confirmed_at
              FROM screening_events
             WHERE id = ? AND applied_action = 'BLOCK'
             LIMIT 1
            """,
            (int(block_id),),
        ).fetchone()
        return dict(row) if row else None

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
