"""Provider selection.

Modes follow `docs/ARCHITECTURE.md`: disabled, local, cloud, and compatible.

`compatible` is a fourth because using `local` for a hosted service would
make that module's promise false. `local` says the learner's writing never
leaves the deployment, and `evaluator_id` is stored on every attempt and
shown to the learner -- so the provenance has to distinguish "a model on this
machine" from "somebody else's API that happens to speak the same protocol".

`disabled` is the default, and every test suite runs against it: the core
learning loop has to work with no AI configured, so that is the path proved
on every commit.

`cloud`, `local` and `compatible` do the same job and differ in where the
learner's text goes. Neither is constructed lazily or guarded at startup, because both
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
from .compatible import CompatibleWritingEvaluator
from .disabled import DisabledWritingEvaluator
from .local import LocalWritingEvaluator

KNOWN_MODES = {"disabled", "local", "cloud", "compatible"}


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

    if mode == "compatible":
        # Abstains without a key or an explicit base URL rather than raising,
        # for the same reason as the others: a misconfigured optional feature
        # must not take the API down.
        return CompatibleWritingEvaluator()

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
    "CompatibleWritingEvaluator",
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
