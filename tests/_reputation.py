from callshield.utils import iso_now


def analysis(risk=0, confidence=0, signals=None, reputation="UNKNOWN", reason="test"):
    return {
        "risk_score": risk,
        "confidence": confidence,
        "signals": signals or [],
        "reputation": reputation,
        "reason": reason,
    }


def measured_signal(name="measured", score=10, confidence=80, reason="measured signal"):
    return {
        "name": name,
        "score": score,
        "confidence": confidence,
        "reason": reason,
    }


def add_event(db, number, risk=0, confidence=25, verdict="UNKNOWN", action="ALLOW", timestamp=None):
    return db.add_event(
        timestamp=timestamp or iso_now(),
        number=number,
        risk_score=risk,
        confidence=confidence,
        reputation="UNKNOWN",
        risk_level="UNKNOWN" if risk == 0 else "HIGH",
        verdict=verdict,
        action=action,
        reason="test event",
    )
