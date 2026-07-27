"""The no-provider implementation.

This is the default and the one every test runs against. If the product is
pleasant to use with this provider selected, the AI layer is genuinely optional
rather than nominally so.
"""

from __future__ import annotations

from .base import WritingEvaluation, WritingEvaluationRequest


class DisabledWritingEvaluator:
    """Always abstains. Deterministic checks carry the whole experience."""

    name = "disabled"

    def evaluate(self, request: WritingEvaluationRequest) -> WritingEvaluation | None:
        return None
