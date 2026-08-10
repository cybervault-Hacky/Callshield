"""Rule engine for CALLSHIELD Phase 2."""

from .engine import DetectionResult, evaluate
from . import defaults

__all__ = ["DetectionResult", "evaluate", "defaults"]
