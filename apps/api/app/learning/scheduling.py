"""Spaced review scheduling.

Design
------
A stability/difficulty model in the family of modern spaced-repetition systems,
kept deliberately simple and independently testable. `docs/ADAPTIVE_ENGINE.md`
permits exactly this and adds a caution this module takes seriously: it *must
not claim perfect memory prediction*. What it does is far narrower — it turns an
outcome into a next interval, monotonically and explainably.

Two stored numbers per memory object per mode:

- **stability** — roughly how many days the item should survive before recall
  becomes uncertain. Grows on success, shrinks on failure.
- **difficulty** — 0..1, how resistant this item is for this learner. Drifts up
  on lapses and down on easy successes, and damps stability growth.

Why per *mode*: recognising a word, recalling it, hearing it, and producing it
are different memories. `docs/SKILL_MATRIX.md` and the review queue's unique
constraint both treat them separately, so the scheduler must too. Passing a
recognition review says nothing about whether the word is available for speech.

The interval is deterministic given (stability, difficulty, grade). No
randomness, no fuzzing — a learner who reports the same thing twice gets the
same schedule, and a test can assert on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ..models.enums import ReviewMode

SCHEDULER_VERSION = "0.1.0"


class Grade(str, Enum):
    """How the retrieval went, from the learner's own report plus correctness.

    Four levels rather than a binary: "wrong" and "right but slow" call for
    different intervals, and collapsing them loses the signal that matters most.
    """

    FORGOT = "forgot"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"

    @property
    def is_lapse(self) -> bool:
        return self is Grade.FORGOT


@dataclass(frozen=True)
class SchedulerConfig:
    """Tunable parameters, in one place and versioned with the scheduler.

    Starting values informed by common spaced-repetition practice, not by data
    from this product. `docs/LEARNING_SCIENCE.md` requires validation against
    usage before they are treated as more than defaults.
    """

    #: Stability, in days, granted by a first successful review.
    initial_stability: float = 1.0
    #: Stability after forgetting. Not zero — some trace survives a lapse.
    lapse_stability: float = 0.5
    #: Multipliers applied to stability per grade.
    hard_multiplier: float = 1.2
    good_multiplier: float = 2.3
    easy_multiplier: float = 3.4
    #: A hard item grows more slowly; a difficulty of 1.0 halves the gain.
    difficulty_damping: float = 0.5
    #: How far difficulty moves per review.
    difficulty_step: float = 0.15
    #: Difficulty of a brand-new item, before anything is known about it.
    initial_difficulty: float = 0.35
    #: Never schedule further out than this. Beyond a year the estimate is
    #: fiction, and a learner deserves to see the item again eventually.
    max_interval_days: float = 365.0
    #: Minimum gap, so a failed item is not shown twice in the same minute.
    min_interval_days: float = 10.0 / (60 * 24)

    #: Modes that are harder to sustain get a shorter first interval: being
    #: able to produce a word decays faster than being able to recognise it.
    mode_factors: tuple[tuple[ReviewMode, float], ...] = (
        (ReviewMode.MEANING_RECOGNITION, 1.3),
        (ReviewMode.FORM_RECOGNITION, 1.2),
        (ReviewMode.LISTENING_RECOGNITION, 1.0),
        (ReviewMode.MEANING_RECALL, 0.9),
        (ReviewMode.FORM_RECALL, 0.8),
        (ReviewMode.PRONUNCIATION_PRODUCTION, 0.7),
        (ReviewMode.CONTEXTUAL_PRODUCTION, 0.7),
    )

    def factor_for(self, mode: ReviewMode) -> float:
        for candidate, factor in self.mode_factors:
            if candidate is mode:
                return factor
        return 1.0


DEFAULT_CONFIG = SchedulerConfig()


@dataclass(frozen=True)
class MemoryState:
    """The stored state of one memory object in one retrieval mode."""

    stability: float = 0.0
    difficulty: float = DEFAULT_CONFIG.initial_difficulty
    repetitions: int = 0
    lapses: int = 0

    @property
    def is_new(self) -> bool:
        return self.repetitions == 0


@dataclass(frozen=True)
class ScheduleResult:
    state: MemoryState
    interval_days: float
    due_at: datetime
    scheduler_version: str = SCHEDULER_VERSION

    @property
    def explanation(self) -> str:
        """Why the item comes back when it does — the UI must be able to say."""
        if self.interval_days < 1:
            return "You will see this again shortly."
        if self.interval_days < 2:
            return "Back tomorrow."
        return f"Back in about {round(self.interval_days)} days."


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _multiplier(grade: Grade, config: SchedulerConfig) -> float:
    return {
        Grade.FORGOT: 0.0,
        Grade.HARD: config.hard_multiplier,
        Grade.GOOD: config.good_multiplier,
        Grade.EASY: config.easy_multiplier,
    }[grade]


def next_difficulty(state: MemoryState, grade: Grade, config: SchedulerConfig) -> float:
    """Difficulty drifts with outcomes and never leaves 0..1.

    Forgetting moves it up by a full step; an easy success moves it down. Hard
    and good nudge it slightly, so difficulty tracks a trend rather than
    swinging on a single answer.
    """
    delta = {
        Grade.FORGOT: config.difficulty_step,
        Grade.HARD: config.difficulty_step * 0.5,
        Grade.GOOD: -config.difficulty_step * 0.2,
        Grade.EASY: -config.difficulty_step,
    }[grade]
    return round(_clamp(state.difficulty + delta, 0.0, 1.0), 6)


def review(
    state: MemoryState,
    grade: Grade,
    *,
    mode: ReviewMode = ReviewMode.MEANING_RECOGNITION,
    now: datetime,
    config: SchedulerConfig = DEFAULT_CONFIG,
) -> ScheduleResult:
    """Apply one review outcome and return the new state and due date.

    Deterministic: the same inputs always produce the same schedule.
    """
    difficulty = next_difficulty(state, grade, config)

    if grade.is_lapse:
        # A lapse resets stability but keeps a trace: relearning is faster
        # than learning, and pretending otherwise wastes the learner's time.
        stability = config.lapse_stability
        repetitions = state.repetitions
        lapses = state.lapses + 1
    elif state.is_new:
        stability = config.initial_stability * _multiplier(grade, config) / config.good_multiplier
        repetitions = 1
        lapses = state.lapses
    else:
        # Growth is damped by difficulty: a stubborn item earns shorter gaps
        # than an easy one even when both are answered correctly.
        damping = 1.0 - config.difficulty_damping * difficulty
        stability = state.stability * _multiplier(grade, config) * damping
        repetitions = state.repetitions + 1
        lapses = state.lapses

    stability = max(stability, config.lapse_stability)

    interval = _clamp(
        stability * config.factor_for(mode),
        config.min_interval_days,
        config.max_interval_days,
    )

    return ScheduleResult(
        state=MemoryState(
            stability=round(stability, 6),
            difficulty=difficulty,
            repetitions=repetitions,
            lapses=lapses,
        ),
        interval_days=round(interval, 6),
        due_at=now + timedelta(days=interval),
    )


def grade_from(correct: bool, *, hesitated: bool = False, effortless: bool = False) -> Grade:
    """Map an observed outcome onto a grade.

    Kept here so callers cannot invent their own mapping and quietly change
    what a grade means.
    """
    if not correct:
        return Grade.FORGOT
    if hesitated:
        return Grade.HARD
    if effortless:
        return Grade.EASY
    return Grade.GOOD


def initial_due(now: datetime, *, mode: ReviewMode = ReviewMode.MEANING_RECOGNITION) -> datetime:
    """When a newly created card should first appear: immediately.

    A card made from a mistake the learner just made is most useful now, while
    the context is still fresh.
    """
    del mode
    return now
