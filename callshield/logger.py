"""Event and file logging for CALLSHIELD.

Two complementary logs are maintained:

  * The *event log* lives in the SQLite ``events`` table and powers
    ``callshield logs``.
  * A traditional line-based text log (in ``logs/callshield.log``) records
    engine/diagnostics information.

The module also provides a small wrapper so the rest of the code can call
``log_event(...)`` and ``log_info(...)`` without worrying about configuration.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .config import Config
from .database import Database
from .utils import iso_now, mask_number


_EVENT_LOGGER_NAME = "callshield.file"


def get_file_logger(log_path: Path) -> logging.Logger:
    """Return (and lazily configure) a rotating-safe file logger."""
    logger = logging.getLogger(_EVENT_LOGGER_NAME)
    if getattr(logger, "_callshield_configured", False):
        return logger
    logger.setLevel(logging.INFO)
    # Remove any existing handlers that may have leaked in (e.g. tests)
    logger.handlers = []
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_path.parent.chmod(0o700)
        except OSError:
            pass
        handler = logging.FileHandler(log_path, encoding="utf-8")
        try:
            os.chmod(log_path, 0o600)
        except OSError:
            pass
    except OSError:
        # Fall back to a stderr logger if the file is unwritable, so we don't
        # lose diagnostics.
        handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False
    logger._callshield_configured = True  # type: ignore[attr-defined]
    return logger


def log_info(cfg: Config, msg: str) -> None:
    """Append an informational line to the text log (when enabled)."""
    logger = get_file_logger(Path(cfg.log_file))
    logger.info(msg)


def log_warning(cfg: Config, msg: str) -> None:
    logger = get_file_logger(Path(cfg.log_file))
    logger.warning(msg)


def log_error(cfg: Config, msg: str) -> None:
    logger = get_file_logger(Path(cfg.log_file))
    logger.error(msg)


def log_event(
    db: Database,
    cfg: Config,
    *,
    number: str,
    risk_score: int,
    verdict: str,
    action: str,
    reason: Optional[str] = None,
    confidence: int = 0,
    reputation: str = "UNKNOWN",
    risk_level: Optional[str] = None,
) -> Optional[int]:
    """Record an analysis event in the database and text log.

    Returns the new event id, or ``None`` if logging is disabled.
    """
    if not cfg.logging_enabled:
        return None
    ts = iso_now()
    event_id = db.add_event(
        timestamp=ts,
        number=number,
        risk_score=int(risk_score),
        verdict=verdict,
        action=action,
        reason=reason,
        confidence=int(confidence),
        reputation=reputation,
        risk_level=risk_level,
    )
    try:
        get_file_logger(Path(cfg.log_file)).info(
            "event id=%s number=%s score=%s conf=%s rep=%s verdict=%s action=%s reason=%s",
            event_id, mask_number(number), risk_score, confidence, reputation,
            verdict, action, reason,
        )
    except Exception:  # pragma: no cover - logging must never break flow
        pass
    return event_id
