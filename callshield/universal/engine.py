"""Compose existing engines into a UniversalNumberProfile.

Does not score risk itself. Never queries the network. Never invents identity.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..adaptive import BehaviorEngine
from ..database import Database
from ..detector import analyze_number
from ..normalizer import normalize
from ..reputation import ReputationEngine
from ..utils import InvalidNumberError, mask_number
from .contacts import ContactStore
from .models import (
    UniversalNumberProfile,
    available,
    not_verified,
    unavailable,
    unknown,
)

# Conservative ITU calling-code prefixes (same set as the normalizer).
_PREFIX_TO_COUNTRY = {
    "1": "US/CA",
    "7": "RU",
    "20": "EG",
    "27": "ZA",
    "31": "NL",
    "32": "BE",
    "33": "FR",
    "34": "ES",
    "39": "IT",
    "41": "CH",
    "43": "AT",
    "44": "GB",
    "45": "DK",
    "46": "SE",
    "47": "NO",
    "49": "DE",
    "52": "MX",
    "55": "BR",
    "61": "AU",
    "64": "NZ",
    "81": "JP",
    "82": "KR",
    "86": "CN",
    "91": "IN",
    "234": "NG",
    "351": "PT",
    "358": "FI",
}


def detect_country(digits: str, applied_cc: Optional[str]) -> Optional[str]:
    """Return a country label only when a conservative prefix matches."""

    if applied_cc:
        return _PREFIX_TO_COUNTRY.get(applied_cc, applied_cc)
    matches = [
        (prefix, label)
        for prefix, label in _PREFIX_TO_COUNTRY.items()
        if digits.startswith(prefix)
    ]
    if not matches:
        return None
    prefix, label = max(matches, key=lambda item: len(item[0]))
    return label


class UniversalNumberEngine:
    def __init__(self, database: Database, cfg: Any) -> None:
        self.database = database
        self.cfg = cfg
        self.contacts = ContactStore(database, cfg)

    def profile(self, number: str, *, persist: bool = False) -> UniversalNumberProfile:
        try:
            parsed = normalize(number, default_country=getattr(self.cfg, "default_country", None))
        except InvalidNumberError as exc:
            return UniversalNumberProfile.invalid(exc.message)

        try:
            analysis = analyze_number(
                parsed.normalized, db=self.database, cfg=self.cfg, record_event=False
            )
        except Exception as exc:  # noqa: BLE001 - fail-open profile
            return UniversalNumberProfile.invalid(str(exc))

        try:
            reputation = ReputationEngine(self.database, self.cfg).calculate(
                parsed.normalized, analysis=analysis, persist=persist
            )
        except Exception:
            reputation = None

        try:
            snapshot = BehaviorEngine(self.database, self.cfg).snapshot(
                parsed.normalized,
                reputation=reputation,
                detection=analysis,
                persist=persist,
            )
        except Exception:
            snapshot = None

        contact = self.contacts.lookup(parsed.normalized)
        country = detect_country(parsed.digits, parsed.country_code)

        if contact is not None:
            contact_status = available("SAVED")
            contact_name = available(contact.display_name)
            identity = not_verified("NOT VERIFIED")
            # Name is user-provided; identity is still not independently verified.
            contact_source = available("Local Contacts")
        else:
            contact_status = available("NOT SAVED")
            contact_name = unavailable("NOT AVAILABLE")
            identity = not_verified("NOT VERIFIED")
            contact_source = unavailable("NOT AVAILABLE")

        patterns: List[str] = []
        evidence: List[str] = []
        trend_value = "UNKNOWN"
        trend_avail = "UNKNOWN"
        if snapshot is not None and getattr(snapshot, "available", True):
            trend_value = snapshot.behavioral_trend or "UNKNOWN"
            trend_avail = "AVAILABLE" if snapshot.behavioral_trend else "UNKNOWN"
            for pattern in list(getattr(snapshot, "patterns", None) or [])[:10]:
                explanation = getattr(pattern, "explanation", None) or str(pattern)
                if explanation:
                    patterns.append(str(explanation)[:200])
            if snapshot.recent_block_recommendations:
                evidence.append("Previous local BLOCK recommendation")
            if snapshot.recent_high_risk_count:
                evidence.append("Measured local high-risk observations")
            if snapshot.risk_delta and int(snapshot.risk_delta) > 0:
                evidence.append("Recent measured risk increase")
            if snapshot.recent_user_reports:
                evidence.append("Local user reports recorded")
        if reputation is not None and getattr(reputation, "available", False):
            for reason in list(reputation.reasons or [])[:5]:
                if reason and reason not in evidence:
                    evidence.append(str(reason)[:200])

        sources = ["LOCAL ONLY", "Normalization", "ReputationEngine", "BehaviorEngine"]
        if contact is not None:
            sources.append("Local Contacts")

        rec = getattr(analysis, "recommended_action", "ALLOW") or "ALLOW"
        score = int(getattr(analysis, "risk_score", 0) or 0)
        conf = int(getattr(analysis, "confidence", 0) or 0)
        if reputation is not None and getattr(reputation, "available", False):
            score = int(reputation.risk_score)
            conf = int(reputation.confidence)

        first_seen = None
        last_seen = None
        calls = 0
        reports = 0
        blocks = 0
        trust_state = "UNKNOWN"
        if reputation is not None and getattr(reputation, "available", False):
            first_seen = reputation.first_seen
            last_seen = reputation.last_seen
            calls = int(reputation.calls_seen)
            reports = int(reputation.user_reports)
            blocks = int(reputation.block_recommendations)
            trust_state = "TRUSTED" if reputation.trusted else "NO"
        if snapshot is not None and getattr(snapshot, "trust_state", None):
            trust_state = snapshot.trust_state

        return UniversalNumberProfile(
            normalized_number=available(parsed.normalized),
            masked_number=available(mask_number(parsed.normalized)),
            country=available(country) if country else unavailable("NOT AVAILABLE"),
            region=unavailable("NOT AVAILABLE"),
            local_contact_status=contact_status,
            contact_name=contact_name,
            age=unavailable("NOT AVAILABLE"),
            owner_identity=identity,
            reputation_score=available(score),
            reputation_confidence=available(conf),
            risk_level=available(getattr(analysis, "risk_level", "UNKNOWN") or "UNKNOWN"),
            verdict=available(getattr(analysis, "verdict", "UNKNOWN") or "UNKNOWN"),
            recommendation=available(rec),
            trust_state=available(trust_state) if trust_state != "UNKNOWN" else unknown("UNKNOWN"),
            first_seen=available(first_seen) if first_seen else unavailable("NOT AVAILABLE"),
            last_seen=available(last_seen) if last_seen else unavailable("NOT AVAILABLE"),
            calls_observed=available(calls),
            reports=available(reports),
            historical_block_recommendations=available(blocks),
            behavioral_trend=(
                available(trend_value) if trend_avail == "AVAILABLE" else unknown(trend_value)
            ),
            intelligence_patterns=(
                available(patterns) if patterns else unavailable("NOT AVAILABLE")
            ),
            measured_evidence=(
                available(evidence) if evidence else unavailable("NOT AVAILABLE")
            ),
            data_sources=available(sources),
            contact_source=contact_source,
            valid=True,
            available=True,
        )

    def scan_contacts(self, *, persist: bool = False) -> Dict[str, Any]:
        rows = self.contacts.list_contacts(limit=self.contacts.limit)
        buckets = {
            "total": len(rows),
            "valid": 0,
            "invalid": 0,
            "known_contacts": 0,
            "unknown_numbers": 0,
            "high_risk": 0,
            "medium_risk": 0,
            "low_risk": 0,
            "unknown": 0,
            "trusted": 0,
            "profiles": [],
        }
        # Contacts are already normalized at import; we only have hashes.
        # Scan uses stored masked identities plus reputation by re-walking
        # imported hashes through stored profiles — without plaintext.
        for record in rows:
            buckets["known_contacts"] += 1
            buckets["valid"] += 1
            # Risk comes from the existing reputation table keyed by the same hash.
            risk_row = self.database._conn.execute(
                "SELECT risk, risk_score, trend FROM reputation_profiles "
                "WHERE number_hash = ?",
                (record.number_hash,),
            ).fetchone()
            trust_row = self.database._conn.execute(
                "SELECT 1 FROM trusted_numbers WHERE number_hash = ?",
                (record.number_hash,),
            ).fetchone()
            if trust_row:
                buckets["trusted"] += 1
            if risk_row is None:
                buckets["unknown"] += 1
                level = "UNKNOWN"
            else:
                level = str(risk_row["risk"] or "UNKNOWN")
                if level in ("HIGH", "CRITICAL"):
                    buckets["high_risk"] += 1
                elif level in ("MODERATE", "MEDIUM"):
                    buckets["medium_risk"] += 1
                elif level in ("LOW", "TRUSTED"):
                    buckets["low_risk"] += 1
                else:
                    buckets["unknown"] += 1
            buckets["profiles"].append(
                {
                    "number_masked": record.number_masked,
                    "display_name": record.display_name,
                    "source": "Local Contacts",
                    "risk": level,
                }
            )
        buckets["unknown_numbers"] = 0
        return buckets


__all__ = ["UniversalNumberEngine", "detect_country"]
