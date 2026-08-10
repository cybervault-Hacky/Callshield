"""Data models used across CALLSHIELD.

These are re-exports from their respective modules so that external
consumers can do:

    from callshield.models import AnalysisResult

without having to import from internal packages. New code should prefer
importing directly from the module that defines the type.
"""

from __future__ import annotations

from .detector import AnalysisResult
from .intelligence.behavior import BehaviorAnalysis, NumberIntelligence
from .intelligence.signals import SignalResult
from .rules.engine import DetectionResult

__all__ = [
    "AnalysisResult",
    "BehaviorAnalysis",
    "DetectionResult",
    "NumberIntelligence",
    "SignalResult",
]
