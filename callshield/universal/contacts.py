"""Explicit, user-controlled local contact import (no Android access)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..database import Database
from ..normalizer import normalize
from ..reputation.storage import number_fingerprint
from ..utils import InvalidNumberError, iso_now, mask_number

CONTACT_IMPORT_LIMIT = 5000
CONTACT_NAME_MAX = 80
MAX_IMPORT_BYTES = 1024 * 1024


class ContactImportError(ValueError):
    """Malformed or oversized contact import."""


@dataclass(frozen=True)
class ContactRecord:
    number_hash: str
    number_masked: str
    display_name: str
    imported_at: str

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "number_masked": self.number_masked,
            "display_name": self.display_name,
            "imported_at": self.imported_at,
            "source": "Local Contacts",
        }


def _clean_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:CONTACT_NAME_MAX]


def _row_fields(item: Any) -> Optional[Tuple[str, str]]:
    if isinstance(item, dict):
        number = item.get("number") or item.get("phone") or item.get("msisdn")
        name = item.get("name") or item.get("display_name") or ""
        if number is None:
            return None
        return str(number), _clean_name(name)
    return None


def parse_contact_file(path: Path) -> List[Tuple[str, str]]:
    """Parse CSV or JSON into (raw_number, name) pairs. No network."""

    target = Path(path)
    if not target.is_file():
        raise ContactImportError("Import file was not found.")
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise ContactImportError(f"Unable to read import file: {exc}") from exc
    if size > MAX_IMPORT_BYTES:
        raise ContactImportError("Import file exceeds the 1 MiB size limit.")
    suffix = target.suffix.lower()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContactImportError(f"Unable to read import file: {exc}") from exc
    if suffix == ".json":
        return _parse_json(text)
    if suffix == ".csv":
        return _parse_csv(text)
    raise ContactImportError("Supported import formats are CSV and JSON.")


def _parse_json(text: str) -> List[Tuple[str, str]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContactImportError("Import JSON is malformed.") from exc
    rows: List[Any]
    if isinstance(payload, dict) and isinstance(payload.get("contacts"), list):
        rows = payload["contacts"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ContactImportError("Import JSON must be a list or {\"contacts\": [...]}.")
    if len(rows) > CONTACT_IMPORT_LIMIT:
        raise ContactImportError(
            f"Import exceeds the {CONTACT_IMPORT_LIMIT} contact limit."
        )
    parsed: List[Tuple[str, str]] = []
    for item in rows:
        fields = _row_fields(item)
        if fields is None:
            continue
        parsed.append(fields)
    return parsed


def _parse_csv(text: str) -> List[Tuple[str, str]]:
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ContactImportError("CSV import requires a header row.")
    headers = [str(name or "").strip().lower() for name in reader.fieldnames]
    if "number" not in headers and "phone" not in headers:
        raise ContactImportError("CSV import requires a number column.")
    parsed: List[Tuple[str, str]] = []
    for index, row in enumerate(reader):
        if index >= CONTACT_IMPORT_LIMIT:
            raise ContactImportError(
                f"Import exceeds the {CONTACT_IMPORT_LIMIT} contact limit."
            )
        lowered = {str(k or "").strip().lower(): v for k, v in row.items()}
        number = lowered.get("number") or lowered.get("phone")
        if not number:
            continue
        name = lowered.get("name") or lowered.get("display_name") or ""
        parsed.append((str(number), _clean_name(name)))
    return parsed


class ContactStore:
    """Privacy-preserving local contact storage (hash + mask + name)."""

    def __init__(self, database: Database, cfg: Any) -> None:
        self.database = database
        self.cfg = cfg
        self.limit = int(getattr(cfg, "contact_record_limit", CONTACT_IMPORT_LIMIT))

    def lookup(self, normalized_number: str) -> Optional[ContactRecord]:
        digest = number_fingerprint(normalized_number)
        row = self.database._conn.execute(
            "SELECT number_hash, number_masked, display_name, imported_at "
            "FROM local_contacts WHERE number_hash = ?",
            (digest,),
        ).fetchone()
        if not row:
            return None
        return ContactRecord(
            number_hash=row["number_hash"],
            number_masked=row["number_masked"],
            display_name=row["display_name"],
            imported_at=row["imported_at"],
        )

    def list_contacts(self, limit: int = 200) -> List[ContactRecord]:
        bounded = max(1, min(int(limit), self.limit))
        rows = self.database._conn.execute(
            "SELECT number_hash, number_masked, display_name, imported_at "
            "FROM local_contacts ORDER BY imported_at DESC LIMIT ?",
            (bounded,),
        ).fetchall()
        return [
            ContactRecord(
                number_hash=row["number_hash"],
                number_masked=row["number_masked"],
                display_name=row["display_name"],
                imported_at=row["imported_at"],
            )
            for row in rows
        ]

    def count(self) -> int:
        row = self.database._conn.execute(
            "SELECT COUNT(*) AS n FROM local_contacts"
        ).fetchone()
        return int(row["n"] if row else 0)

    def upsert(
        self,
        normalized_number: str,
        display_name: str,
        *,
        imported_at: Optional[str] = None,
    ) -> str:
        digest = number_fingerprint(normalized_number)
        masked = mask_number(normalized_number)
        name = _clean_name(display_name) or "UNNAMED"
        now = imported_at or iso_now()
        existing = self.lookup(normalized_number)
        with self.database.transaction():
            if existing is None:
                count = self.count()
                if count >= self.limit:
                    raise ContactImportError("Contact storage limit reached.")
            self.database._conn.execute(
                """
                INSERT INTO local_contacts
                    (number_hash, number_masked, display_name, imported_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(number_hash) DO UPDATE SET
                    number_masked=excluded.number_masked,
                    display_name=excluded.display_name,
                    imported_at=excluded.imported_at
                """,
                (digest, masked, name, now),
            )
        return "updated" if existing else "inserted"

    def remove(self, normalized_number: str) -> bool:
        digest = number_fingerprint(normalized_number)
        with self.database.transaction():
            cursor = self.database._conn.execute(
                "DELETE FROM local_contacts WHERE number_hash = ?",
                (digest,),
            )
            return cursor.rowcount > 0

    def clear(self) -> int:
        with self.database.transaction():
            cursor = self.database._conn.execute("DELETE FROM local_contacts")
            return int(cursor.rowcount)

    def import_pairs(
        self,
        pairs: Sequence[Tuple[str, str]],
        default_country: Optional[str],
    ) -> Dict[str, int]:
        inserted = 0
        updated = 0
        skipped = 0
        invalid = 0
        seen: Dict[str, str] = {}
        for raw_number, name in pairs:
            try:
                parsed = normalize(raw_number, default_country=default_country)
            except InvalidNumberError:
                invalid += 1
                continue
            if parsed.normalized in seen:
                skipped += 1
                seen[parsed.normalized] = name or seen[parsed.normalized]
                continue
            seen[parsed.normalized] = name
        for normalized_number, name in seen.items():
            try:
                result = self.upsert(normalized_number, name)
            except ContactImportError:
                skipped += 1
                continue
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "invalid": invalid,
            "accepted": inserted + updated,
            "total_rows": len(pairs),
        }
