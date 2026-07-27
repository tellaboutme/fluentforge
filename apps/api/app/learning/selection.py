"""Adaptive item selection for the diagnostic.

The diagnostic's job is to *reduce uncertainty* quickly, not to score the
learner. Selection therefore targets the item whose difficulty sits closest to
the current estimate of the learner's ability: an item they will almost
certainly pass, or almost certainly fail, teaches us very little.

The rule is a transparent staircase rather than a latent-trait model. With ~30
items a full IRT calibration would be false precision, and every decision here
has to stay explainable (`docs/ADAPTIVE_ENGINE.md`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..models.enums import CefrLevel
from .items import DiagnosticItem, ItemType

#: How far the ability estimate moves after one response.
STEP_UP = 0.12
STEP_DOWN = 0.15

#: Where an unknown learner is assumed to start. Deliberately low: the target
#: user is around A1-A2, and starting too hard is demoralising.
INITIAL_ABILITY = 0.25

#: Stop once this many items have been answered overall.
DEFAULT_MAX_ITEMS = 20

#: Closed items to answer before the writing task, so the prompt matches a
#: settled ability estimate rather than the starting guess.
PRODUCTIVE_AFTER = 8


@dataclass(frozen=True)
class SelectionState:
    """Running state of one diagnostic. Immutable; each response yields a new one."""

    ability: float = INITIAL_ABILITY
    answered_keys: frozenset[str] = frozenset()
    consecutive_failures: int = 0

    def after(self, item: DiagnosticItem, correct: bool) -> SelectionState:
        """Update the estimate after one response.

        Failure moves the estimate down further than success moves it up: it is
        cheaper to under-estimate and climb than to strand a learner on items
        they cannot access.
        """
        if not _drives_staircase(item):
            # Self-report seeds the starting point; a writing task is scored on
            # countable checks, not right/wrong. Neither should move a
            # difficulty estimate built from closed items.
            return replace(self, answered_keys=self.answered_keys | {item.key})

        if correct:
            ability = min(1.0, self.ability + STEP_UP)
            failures = 0
        else:
            ability = max(0.0, self.ability - STEP_DOWN)
            failures = self.consecutive_failures + 1

        return SelectionState(
            ability=round(ability, 4),
            answered_keys=self.answered_keys | {item.key},
            consecutive_failures=failures,
        )

    def seeded_with_self_rating(self, rating: float) -> SelectionState:
        """Blend a 0..1 self-rating into the starting estimate.

        Weighted lightly. Self-assessment is the least reliable evidence type in
        the model, and it should not be able to launch a learner into C1 items.
        """
        blended = 0.7 * self.ability + 0.3 * max(0.0, min(1.0, rating))
        return replace(self, ability=round(blended, 4))


def _drives_staircase(item: DiagnosticItem) -> bool:
    """Whether an item's outcome should move the difficulty estimate."""
    return item.item_type is not ItemType.SELF_ASSESSMENT and not item.item_type.is_productive


def select_next(
    items: list[DiagnosticItem],
    state: SelectionState,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> DiagnosticItem | None:
    """Pick the next item, or ``None`` when the diagnostic should stop.

    Order: self-assessments, then a difficulty staircase over closed items,
    then exactly one writing task.

    The writing task is held back until the estimate has settled, so the prompt
    matches the learner's level. It is offered even when the staircase has
    stopped on consecutive failures: production is the strongest evidence the
    model can collect, and a learner who found the closed items hard should
    still get the chance to write something.
    """
    if len(state.answered_keys) >= max_items:
        return None

    remaining = [item for item in items if item.key not in state.answered_keys]
    if not remaining:
        return None

    # Self-assessment items go first: they cost little and seed the estimate.
    self_ratings = [item for item in remaining if item.item_type is ItemType.SELF_ASSESSMENT]
    if self_ratings:
        return min(self_ratings, key=lambda item: item.key)

    staircase = [item for item in remaining if _drives_staircase(item)]
    answered_closed = sum(
        1 for item in items if _drives_staircase(item) and item.key in state.answered_keys
    )
    exhausted = not staircase or state.consecutive_failures >= 3
    settled = answered_closed >= PRODUCTIVE_AFTER

    if exhausted or settled:
        writing = [item for item in remaining if item.item_type.is_productive]
        already_written = any(
            item.item_type.is_productive and item.key in state.answered_keys for item in items
        )
        if writing and not already_written:
            return min(writing, key=lambda item: (abs(item.difficulty - state.ability), item.key))
        return None

    # Closest difficulty to current ability; ties broken by key for determinism.
    return min(staircase, key=lambda item: (abs(item.difficulty - state.ability), item.key))


def provisional_band(
    results: list[tuple[CefrLevel, bool]], *, min_items: int = 2, pass_rate: float = 0.5
) -> CefrLevel | None:
    """The highest level the learner handled well enough to start there.

    This is a *routing* decision — which content to open with — not a mastery
    claim and not a CEFR placement. A 20-item diagnostic cannot support either.
    Mastery statuses stay `emerging` until real evidence accumulates across
    contexts; this only stops the product from opening at A1 for a B1 learner.

    Returns ``None`` when no level has enough answered items to judge.
    """
    tally: dict[CefrLevel, list[bool]] = {}
    for level, correct in results:
        tally.setdefault(level, []).append(correct)

    best: CefrLevel | None = None
    for level in CefrLevel:
        outcomes = tally.get(level, [])
        if len(outcomes) < min_items:
            continue
        if sum(outcomes) / len(outcomes) >= pass_rate:
            best = level
    return best


def replay(
    items_by_key: dict[str, DiagnosticItem],
    responses: list[tuple[str, bool, float | None]],
) -> SelectionState:
    """Rebuild selection state from stored responses.

    The session's state lives in its attempts, not in memory, so a learner can
    close the tab and resume without the diagnostic losing its place.

    Args:
        responses: ``(item_key, correct, self_rating)`` in answer order.
    """
    state = SelectionState()
    for item_key, correct, self_rating in responses:
        item = items_by_key.get(item_key)
        if item is None:
            continue
        if item.item_type is ItemType.SELF_ASSESSMENT and self_rating is not None:
            state = state.seeded_with_self_rating(self_rating)
        state = state.after(item, correct)
    return state
