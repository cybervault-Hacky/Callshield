"""Detection engine — the core, CLI-independent analysis API.

Future phases (including a live Android call-screening layer) will call
:func:`analyze_number` exactly as the CLI does. This module must have no CLI
imports.

Phase 2 upgrades the engine to use the rules engine + modular signals while
preserving the public API.
"""

from __future__ import annotations

from dataclasses import dataclass, replace, field
from typing import Any, Dict, List, Optional

from . import normalizer as norm
from .config import Config, load_config
from .database import Database
from .logger import log_event
from .rules.engine import DetectionResult, evaluate
from .utils import InvalidNumberError


@dataclass
class AnalysisResult:
    """Structured result of :func:`analyze_number`.

    Phase 2 adds ``confidence``, ``reputation``, ``behavior``, and
    ``number_intelligence`` fields. Phase 1 fields remain in place so existing
    callers (and tests) keep working.
    """

    input_number: str
    normalized_number: str
    risk_score: int
    risk_level: str
    verdict: str
    recommended_action: str
    reason: str
    signals: List[Dict[str, Any]] = field(default_factory=list)
    list_conflict: bool = False
    confidence: int = 0
    reputation: str = "UNKNOWN"
    behavior: Dict[str, Any] = field(default_factory=dict)
    number_intelligence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "number": self.normalized_number,
            "input": self.input_number,
            "risk_score": int(self.risk_score),
            "risk_level": self.risk_level,
            "confidence": int(self.confidence),
            "reputation": self.reputation,
            "verdict": self.verdict,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "signals": self.signals,
            "behavior": self.behavior,
            "number_intelligence": self.number_intelligence,
            "list_conflict": bool(self.list_conflict),
        }


def _from_detection(dr: DetectionResult, raw_number: str) -> AnalysisResult:
    """Map a Phase 2 DetectionResult into the (Phase 1 compatible) AnalysisResult."""
    return AnalysisResult(
        input_number=raw_number,
        normalized_number=dr.normalized_number,
        risk_score=int(dr.risk_score),
        risk_level=dr.risk_level,
        verdict=dr.verdict,
        recommended_action=dr.recommended_action,
        reason=dr.reason,
        signals=dr.signals,
        list_conflict=dr.list_conflict,
        confidence=int(dr.confidence),
        reputation=dr.reputation,
        behavior=dr.behavior,
        number_intelligence=dr.number_intelligence,
    )


def analyze_number(
    raw_number: str,
    *,
    db: Optional[Database] = None,
    cfg: Optional[Config] = None,
    record_event: bool = True,
) -> AnalysisResult:
    """Analyze a phone number using the local reputation + scoring engine.

    Returns an :class:`AnalysisResult`. Raises :class:`InvalidNumberError` for
    numbers that cannot be normalized.
    """
    own_db = db is None
    own_cfg = cfg is None
    if cfg is None:
        cfg = load_config()
    if db is None:
        db = Database(cfg.database_path)
    try:
        n = norm.normalize(raw_number, default_country=cfg.default_country)
    except InvalidNumberError:
        raise
    try:
        # Apply per-run weight multipliers from config. We mutate a *copy* of
        # signal weights so the on-disk config is never modified.
        effective_cfg = _apply_weight_multipliers(cfg)
        dr: DetectionResult = evaluate(
            raw_number=raw_number,
            normalized=n.normalized,
            digits=n.digits,
            db=db,
            cfg=effective_cfg,
        )
        result = _from_detection(dr, raw_number)

        # Phase 1 compatibility: if verdict is UNKNOWN and score is 0, level is UNKNOWN.
        if result.verdict == "UNKNOWN" and result.risk_score == 0:
            result.risk_level = "UNKNOWN"

        if record_event and cfg.logging_enabled:
            log_event(
                db,
                cfg,
                number=result.normalized_number,
                risk_score=result.risk_score,
                verdict=result.verdict,
                action=result.recommended_action,
                reason=result.reason,
                confidence=result.confidence,
                reputation=result.reputation,
                risk_level=result.risk_level,
            )
        return result
    finally:
        if own_db:
            db.close()


def _apply_weight_multipliers(cfg: Config) -> Config:
    """Return a (shallow) Config copy with weights scaled by config multipliers."""
    # Build a new Config instance sharing most fields but with adjusted weights.
    weights = dict(cfg.signal_weights)
    # history_weight affects prior-blocks, repeated-suspicious, rapid-repeat
    for key in ("previous_block_events", "repeated_suspicious_events", "previous_suspicious_events",
                "rapid_repeat_events", "reputation_history"):
        if key in weights:
            weights[key] = max(0, int(round(weights[key] * cfg.history_weight)))
    if "manual_user_report" in weights:
        weights["manual_user_report"] = max(
            0, int(round(weights["manual_user_report"] * cfg.report_weight))
        )
    for k in ("format_anomaly", "number_format_anomaly"):
        if k in weights:
            weights[k] = max(
                0, int(round(weights[k] * cfg.pattern_weight))
            )
    # Never mutate the shared daemon configuration: Phase 4 may analyze
    # several screening requests concurrently.
    return replace(cfg, signal_weights=weights)


def open_database(cfg: Config) -> Database:
    return Database(cfg.database_path)
