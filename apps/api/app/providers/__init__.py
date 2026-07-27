"""Provider selection.

Modes follow `docs/ARCHITECTURE.md`: disabled, local, and cloud, and all
three now exist.

`disabled` is the default, and every test suite runs against it: the core
learning loop has to work with no AI configured, so that is the path proved
on every commit.

`cloud` and `local` do the same job and differ in where the learner's text
goes. Neither is constructed lazily or guarded at startup, because both
abstain on their own: a missing key, an unreachable model, or a malformed
answer degrades to the deterministic feedback the learner would have had.
Failing at startup over an optional feature would take the whole API down
with it.

An unknown mode still raises. That is a typo in configuration, not a
degraded capability, and silently falling back would hide it.
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
from .cloud import CloudWritingEvaluator
from .disabled import DisabledWritingEvaluator
from .local import LocalWritingEvaluator

KNOWN_MODES = {"disabled", "local", "cloud"}


class ProviderNotAvailableError(RuntimeError):
    """Raised when a configured provider mode is not a mode at all."""


@lru_cache(maxsize=1)
def get_writing_evaluator() -> WritingEvaluator:
    mode = settings.ai_provider

    if mode == "disabled":
        return DisabledWritingEvaluator()

    if mode == "cloud":
        # Deliberately constructed even with no key. The evaluator abstains
        # on its own, so a misconfigured deployment degrades to deterministic
        # feedback instead of failing at startup and taking the API with it.
        return CloudWritingEvaluator()

    if mode == "local":
        # Same reasoning, and more of it: a self-hosted model that is simply
        # not running yet is the ordinary case, not an error worth refusing
        # to start over.
        return LocalWritingEvaluator()

    raise ProviderNotAvailableError(
        f"AI_PROVIDER={mode!r} is not a known mode (expected one of {sorted(KNOWN_MODES)})."
    )


__all__ = [
    "MIN_USABLE_CONFIDENCE",
    "CloudWritingEvaluator",
    "DisabledWritingEvaluator",
    "LocalWritingEvaluator",
    "PriorityFeedback",
    "ProviderNotAvailableError",
    "RubricDimension",
    "WritingEvaluation",
    "WritingEvaluationRequest",
    "WritingEvaluator",
    "get_writing_evaluator",
]
