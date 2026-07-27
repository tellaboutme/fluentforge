"""Provider selection.

Modes follow `docs/ARCHITECTURE.md`: disabled, local, and cloud. Only
`disabled` exists today; the others raise a clear error rather than silently
degrading, so a misconfigured deployment fails loudly at startup.
"""

from __future__ import annotations

from functools import lru_cache

from ..settings import settings
from .base import (
    MIN_USABLE_CONFIDENCE,
    PriorityFeedback,
    RubricDimension,
    WritingEvaluation,
    WritingEvaluationRequest,
    WritingEvaluator,
)
from .disabled import DisabledWritingEvaluator

KNOWN_MODES = {"disabled", "local", "cloud"}


class ProviderNotAvailableError(RuntimeError):
    """Raised when a configured provider mode has no implementation yet."""


@lru_cache(maxsize=1)
def get_writing_evaluator() -> WritingEvaluator:
    mode = settings.ai_provider

    if mode == "disabled":
        return DisabledWritingEvaluator()

    if mode in KNOWN_MODES:
        raise ProviderNotAvailableError(
            f"AI_PROVIDER={mode!r} is planned but not implemented. "
            "Use 'disabled' until it is; the diagnostic works without it."
        )

    raise ProviderNotAvailableError(
        f"AI_PROVIDER={mode!r} is not a known mode (expected one of {sorted(KNOWN_MODES)})."
    )


__all__ = [
    "MIN_USABLE_CONFIDENCE",
    "DisabledWritingEvaluator",
    "PriorityFeedback",
    "ProviderNotAvailableError",
    "RubricDimension",
    "WritingEvaluation",
    "WritingEvaluationRequest",
    "WritingEvaluator",
    "get_writing_evaluator",
]
