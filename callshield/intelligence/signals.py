"""Modular signal engine.

Each signal is a pure, independently testable function that receives a
:class:`SignalContext` and returns an optional :class:`SignalResult`. The
aggregator :func:`evaluate_signals` gathers every signal result into a list.

Signals are deterministic and local only. They must never invent information
that CALLSHIELD does not actually possess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from .behavior import (
    BehaviorAnalysis,
    NumberIntelligence,
    analyze_behavior,
    number_intelligence,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config


@dataclass
class SignalResult:
    """Structured output of a single signal."""

    name: str
    score: int
    confidence: float  # 0.0 .. 1.0 — how much we trust this signal
    reason: str
    detail: Optional[str] = None
    positive: bool = True  # True = risk-increasing, False = safety/decreasing

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "score": int(self.score),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "detail": self.detail,
            "positive": bool(self.positive),
        }


@dataclass
class SignalContext:
    """Everything a signal may need to evaluate a number."""

    raw_number: str
    normalized: str
    digits: str
    db: object  # Database instance (typed loosely to avoid import cycles)
    cfg: Config
    in_blacklist: bool
    in_whitelist: bool
    blacklist_row: Optional[Dict[str, object]] = None
    whitelist_row: Optional[Dict[str, object]] = None
    behavior: Optional[BehaviorAnalysis] = None
    intel: Optional[NumberIntelligence] = None


# ----- individual signals ------------------------------------------------
def _signal_whitelist(ctx: SignalContext) -> Optional[SignalResult]:
    if ctx.in_whitelist:
        return SignalResult(
            name="whitelist_match",
            score=-100,
            confidence=1.0,
            reason="Number explicitly allowed by user whitelist",
            positive=False,
        )
    return None


def _signal_blacklist(ctx: SignalContext) -> Optional[SignalResult]:
    if ctx.in_blacklist:
        reason = "Number exists in local blacklist"
        bl_reason = (ctx.blacklist_row or {}).get("reason")
        if bl_reason:
            reason = f"{reason} ({bl_reason})"
        return SignalResult(
            name="blacklist_match",
            score=int(ctx.cfg.signal_weights.get("blacklist_match", 80)),
            confidence=1.0,
            reason=reason,
            detail="Explicit user block",
            positive=True,
        )
    return None


def _signal_previous_blocks(ctx: SignalContext) -> Optional[SignalResult]:
    weight = int(ctx.cfg.signal_weights.get("previous_block_events", 20))
    if weight <= 0:
        return None
    beh = ctx.behavior
    if not beh:
        return None
    count = beh.blocked_events
    if count <= 0:
        return None
    delta = min(weight, weight if count == 1 else weight)
    # Multiple blocks don't compound beyond the full weight.
    delta = min(weight, 10 + 5 * min(count, 4))
    return SignalResult(
        name="previous_block_events",
        score=delta,
        confidence=min(0.9, 0.5 + 0.1 * min(count, 4)),
        reason=f"Previously blocked {count} time{'s' if count != 1 else ''} in local history",
        detail=f"count={count}",
        positive=True,
    )


def _signal_repeated_suspicious(ctx: SignalContext) -> Optional[SignalResult]:
    weight = int(ctx.cfg.signal_weights.get("repeated_suspicious_events", 15))
    if weight <= 0:
        return None
    beh = ctx.behavior
    if not beh:
        return None
    count = beh.suspicious_events
    if count < 2:
        return None
    delta = min(weight, 3 * min(count, 8))
    return SignalResult(
        name="repeated_suspicious_events",
        score=delta,
        confidence=min(0.85, 0.4 + 0.07 * min(count, 8)),
        reason=f"Repeated suspicious activity in local history ({count} events)",
        detail=f"count={count}",
        positive=True,
    )


def _signal_rapid_repeat(ctx: SignalContext) -> Optional[SignalResult]:
    weight = int(ctx.cfg.signal_weights.get("rapid_repeat_events", 10))
    if weight <= 0:
        return None
    beh = ctx.behavior
    if not beh:
        return None
    if beh.recent_window_count < 3:
        return None
    delta = min(weight, 3 * min(beh.recent_window_count, 6))
    return SignalResult(
        name="rapid_repeat_events",
        score=delta,
        confidence=0.65,
        reason=(
            f"{beh.recent_window_count} recent scans for this number within "
            f"{beh.window_seconds // 60} minutes"
        ),
        positive=True,
    )


def _signal_user_reports(ctx: SignalContext) -> Optional[SignalResult]:
    weight = int(ctx.cfg.signal_weights.get("manual_user_report", 25))
    if weight <= 0:
        return None
    beh = ctx.behavior
    if not beh:
        return None
    count = beh.user_reports
    if count <= 0:
        return None
    # Reports are strong but not conclusive; cap per-report contribution.
    delta = min(weight, 8 * min(count, 6))
    conf = min(0.85, 0.4 + 0.15 * min(count, 4))
    return SignalResult(
        name="manual_user_report",
        score=delta,
        confidence=conf,
        reason=f"{count} local user report{'s' if count != 1 else ''} for this number",
        detail=f"reports={count}",
        positive=True,
    )


def _signal_reputation_history(ctx: SignalContext) -> Optional[SignalResult]:
    weight = int(ctx.cfg.signal_weights.get("reputation_history", 10))
    if weight <= 0:
        return None
    # If a previously-assigned reputation exists on any list entry, use it.
    rep = None
    for row in (ctx.blacklist_row, ctx.whitelist_row):
        if row and row.get("reputation"):
            rep = row["reputation"]
    if not rep or rep in ("UNKNOWN", "SAFE", "TRUSTED"):
        return None
    score_map = {
        "SUSPICIOUS": weight // 2,
        "HIGH_RISK": weight,
        "MALICIOUS": weight,
    }
    delta = score_map.get(rep, 0)
    if delta == 0:
        return None
    return SignalResult(
        name="reputation_history",
        score=delta,
        confidence=0.75,
        reason=f"Previously recorded reputation: {rep}",
        positive=True,
    )


def _signal_format_anomaly(ctx: SignalContext) -> Optional[SignalResult]:
    weight = int(ctx.cfg.signal_weights.get("format_anomaly", 5))
    if weight <= 0:
        return None
    intel = ctx.intel
    if not intel:
        return None
    if not intel.anomalies:
        return None
    # Weak signal — always contributes a small, low-confidence amount.
    delta = min(weight, 2 * len(intel.anomalies))
    return SignalResult(
        name="number_format_anomaly",
        score=delta,
        confidence=0.35,
        reason="Number-format anomaly detected: " + ", ".join(intel.anomalies),
        detail="weak signal; does not by itself indicate fraud",
        positive=True,
    )


def _signal_whitelist_conflict_marker(ctx: SignalContext) -> Optional[SignalResult]:
    """Non-scoring informational signal when a number appears on both lists."""
    if ctx.in_blacklist and ctx.in_whitelist:
        return SignalResult(
            name="list_conflict",
            score=0,
            confidence=1.0,
            reason=(
                "Number is in BOTH blacklist and whitelist; whitelist takes "
                "precedence (WHITELIST > BLACKLIST > REPUTATION)"
            ),
            positive=False,
        )
    return None


# ----- aggregator --------------------------------------------------------
SIGNAL_FUNCS: List[Callable[[SignalContext], Optional[SignalResult]]] = [
    _signal_whitelist,
    _signal_blacklist,
    _signal_whitelist_conflict_marker,
    _signal_previous_blocks,
    _signal_repeated_suspicious,
    _signal_rapid_repeat,
    _signal_user_reports,
    _signal_reputation_history,
    _signal_format_anomaly,
]


def evaluate_signals(
    raw_number: str,
    normalized: str,
    digits: str,
    db,
    cfg: Config,
    *,
    list_rows: Optional[Tuple[Optional[Dict[str, object]], Optional[Dict[str, object]]]] = None,
) -> Tuple[List[SignalResult], BehaviorAnalysis, NumberIntelligence]:
    """Evaluate all signals for ``normalized`` and return (signals, behavior, intel).

    Signals are always returned in deterministic order.
    """
    if list_rows is None:
        bl = db.get_list_entry(normalized, "blacklist")
        wl = db.get_list_entry(normalized, "whitelist")
    else:
        bl, wl = list_rows
    behavior = analyze_behavior(db, normalized, window_seconds=cfg.recent_window_seconds)
    intel = number_intelligence(raw_number, normalized, digits)

    ctx = SignalContext(
        raw_number=raw_number,
        normalized=normalized,
        digits=digits,
        db=db,
        cfg=cfg,
        in_blacklist=bl is not None,
        in_whitelist=wl is not None,
        blacklist_row=bl,
        whitelist_row=wl,
        behavior=behavior,
        intel=intel,
    )

    results: List[SignalResult] = []
    for fn in SIGNAL_FUNCS:
        try:
            r = fn(ctx)
        except Exception:
            # Defensive: a broken signal must never crash analysis.
            r = None
        if r is not None:
            results.append(r)
    return results, behavior, intel
