"""Mastery interpretation.

This module turns a stored `SkillState` into a learner-facing status. It does
not compute mastery — that is the assessment engine's job (Milestone 1). It
only applies the thresholds declared in `curriculum/framework.yml`, which are
snapshotted onto the curriculum version at load time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.enums import CefrLevel

#: Fallbacks used only when a curriculum version predates the `mastery` block.
DEFAULT_THRESHOLDS = {
    "supported_threshold": 0.70,
    "independent_threshold": 0.82,
    "high_confidence_threshold": 0.75,
    "minimum_distinct_contexts": 3,
}

STATUS_UNOBSERVED = "unobserved"
STATUS_EMERGING = "emerging"
STATUS_SUPPORTED = "supported"
STATUS_INDEPENDENT = "independent"


@dataclass(frozen=True)
class MasteryThresholds:
    supported: float
    independent: float
    high_confidence: float
    minimum_distinct_contexts: int

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> MasteryThresholds:
        raw = dict(DEFAULT_THRESHOLDS)
        if metadata:
            for key, value in (metadata.get("mastery") or {}).items():
                if key in raw and isinstance(value, int | float):
                    raw[key] = value
        return cls(
            supported=float(raw["supported_threshold"]),
            independent=float(raw["independent_threshold"]),
            high_confidence=float(raw["high_confidence_threshold"]),
            minimum_distinct_contexts=int(raw["minimum_distinct_contexts"]),
        )


def classify_status(
    *,
    mastery_probability: float,
    confidence: float,
    distinct_contexts: int,
    evidence_count: int,
    thresholds: MasteryThresholds,
) -> str:
    """Classify a skill state.

    A high probability alone is never enough. "Independent" additionally
    requires confident evidence across several distinct contexts, so repeated
    attempts on one item cannot manufacture mastery.
    """
    if evidence_count <= 0:
        return STATUS_UNOBSERVED

    has_breadth = distinct_contexts >= thresholds.minimum_distinct_contexts
    is_confident = confidence >= thresholds.high_confidence

    if mastery_probability >= thresholds.independent and has_breadth and is_confident:
        return STATUS_INDEPENDENT
    if mastery_probability >= thresholds.supported and has_breadth:
        return STATUS_SUPPORTED
    return STATUS_EMERGING


def cefr_estimate_for(status: str, node_level: CefrLevel) -> CefrLevel | None:
    """A skill is only placed at a CEFR level once evidence supports it.

    Returning ``None`` is deliberate: an unplaced skill must render as "needs
    evidence" rather than as a low level the learner has not been assessed at.
    """
    if status in (STATUS_SUPPORTED, STATUS_INDEPENDENT):
        return node_level
    return None
