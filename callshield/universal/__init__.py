"""Phase 8.5.2 Universal Number Intelligence (local-first)."""

from .contacts import (
    CONTACT_IMPORT_LIMIT,
    CONTACT_NAME_MAX,
    ContactImportError,
    ContactRecord,
    ContactStore,
    parse_contact_file,
)
from .engine import UniversalNumberEngine
from .models import (
    AVAILABILITY,
    FieldValue,
    UniversalNumberProfile,
)

__all__ = [
    "AVAILABILITY",
    "CONTACT_IMPORT_LIMIT",
    "CONTACT_NAME_MAX",
    "ContactImportError",
    "ContactRecord",
    "ContactStore",
    "FieldValue",
    "UniversalNumberEngine",
    "UniversalNumberProfile",
    "parse_contact_file",
]
