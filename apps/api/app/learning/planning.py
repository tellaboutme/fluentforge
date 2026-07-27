"""Daily plan generation.

Design
------
`docs/ADAPTIVE_ENGINE.md` is explicit: *do not hard-code one opaque magic
score*. So a candidate's priority is a sum of named, individually bounded
components, and every component value is stored on the plan item. The UI can
then answer "why is this in today's plan?" by reading data rather than by
guessing at intent.

Two stages, deliberately separate:

1. **Score** every candidate independently (`score_candidate`).
2. **Select** under constraints (`build_plan`) — a session template, a minute
   budget, at least one receptive and one productive task, and a cap on
   consecutive heavy work.

Scoring alone would happily fill a session with six grammar drills. The
constraints are what make the result a *plan* rather than a ranked list, and
they are the part `docs/LEARNING_SCIENCE.md` actually cares about.

This is engine v0.1.0. Milestone 6 replaces the weights with something
validated against outcomes; until then they are documented defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..models.enums import PlanReasonCode, SkillDomain
from .mastery import STATUS_INDEPENDENT, STATUS_UNOBSERVED

ENGINE_VERSION = "0.1.0"


class ActivityKind:
    """What a learner actually does. Drives the receptive/productive balance."""

    REVIEW = "review"
    INPUT = "input"
    STUDY = "study"
    OUTPUT = "output"
    SPEAKING = "speaking"
    REFLECTION = "reflection"


#: Which kinds satisfy the "at least one of each" constraint.
RECEPTIVE_KINDS = frozenset({ActivityKind.REVIEW, ActivityKind.INPUT, ActivityKind.STUDY})
PRODUCTIVE_KINDS = frozenset({ActivityKind.OUTPUT, ActivityKind.SPEAKING})

#: Kinds that demand sustained effort. No more than two may run consecutively.
HEAVY_KINDS = frozenset({ActivityKind.OUTPUT, ActivityKind.SPEAKING, ActivityKind.INPUT})

MAX_CONSECUTIVE_HEAVY = 2

#: Mastery level where practice is most productive: high enough to engage,
#: low enough to still be learning. A starting value, not a finding.
IDEAL_CHALLENGE = 0.55
#: How far from ideal before expected gain reaches zero.
IDEAL_CHALLENGE_WIDTH = 0.55

#: How much a never-assessed skill's uncertainty counts relative to a measured
#: one. Below 1.0 because unmeasured is not the same as known-to-be-weak.
UNASSESSED_DISCOUNT = 0.5


@dataclass(frozen=True)
class PriorityWeights:
    """Component weights. Named, bounded, and tunable in one place.

    Each component contributes at most its weight, so the numbers below are
    directly readable as "how much can this consideration matter".
    """

    due_review: float = 1.00
    weak_prerequisite: float = 0.80
    expected_gain: float = 0.75
    uncertainty: float = 0.60
    skill_balance: float = 0.50
    goal_relevance: float = 0.40
    error_follow_up: float = 0.70
    modality_diversity: float = 0.30
    transfer_check: float = 0.35
    #: Subtracted, not added: recently practised material is worth less today.
    repetition_penalty: float = 0.60


DEFAULT_WEIGHTS = PriorityWeights()


@dataclass(frozen=True)
class Candidate:
    """One thing the learner could do, with everything needed to rank it."""

    activity_key: str
    activity_type: str
    kind: str
    skill_key: str
    domain: SkillDomain
    estimated_minutes: int
    title: str

    #: 0..1 signals, all pre-normalised by the caller.
    due_pressure: float = 0.0
    mastery_probability: float = 0.0
    confidence: float = 0.0
    status: str = STATUS_UNOBSERVED
    prerequisite_weakness: float = 0.0
    goal_match: float = 0.0
    error_pressure: float = 0.0
    days_since_practised: float = 999.0
    is_transfer: bool = False
    #: Whether any evidence exists for this skill. Distinguishes "we measured
    #: this and it is shaky" from "we have never looked".
    has_evidence: bool = False
    #: False for reflection and other non-skill activities, which must not be
    #: scored as though they were competencies.
    targets_a_skill: bool = True
    #: Whether a learner can actually start this. Used to break ties: given two
    #: equally valuable options, offer the one that opens.
    is_openable: bool = False

    @property
    def is_receptive(self) -> bool:
        return self.kind in RECEPTIVE_KINDS

    @property
    def is_productive(self) -> bool:
        return self.kind in PRODUCTIVE_KINDS

    @property
    def is_heavy(self) -> bool:
        return self.kind in HEAVY_KINDS


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: Candidate
    components: dict[str, float]

    @property
    def priority(self) -> float:
        return round(sum(self.components.values()), 6)

    @property
    def reason_codes(self) -> tuple[PlanReasonCode, ...]:
        """The components that actually drove this choice.

        Only components contributing meaningfully are reported: a reason list
        containing every possible code explains nothing.
        """
        mapping = {
            "due_review": PlanReasonCode.DUE_REVIEW,
            "expected_gain": PlanReasonCode.EXPECTED_GAIN,
            "weak_prerequisite": PlanReasonCode.WEAK_PREREQUISITE,
            "uncertainty": PlanReasonCode.UNCERTAINTY,
            "skill_balance": PlanReasonCode.SKILL_BALANCE,
            "goal_relevance": PlanReasonCode.GOAL_RELEVANCE,
            "error_follow_up": PlanReasonCode.ERROR_FOLLOW_UP,
            "modality_diversity": PlanReasonCode.MODALITY_DIVERSITY,
            "transfer_check": PlanReasonCode.TRANSFER_CHECK,
        }
        ranked = sorted(
            ((name, value) for name, value in self.components.items() if value >= 0.1),
            key=lambda pair: pair[1],
            reverse=True,
        )
        codes = [mapping[name] for name, _ in ranked if name in mapping]
        return tuple(codes[:3])


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_candidate(
    candidate: Candidate,
    *,
    domain_share: float = 0.0,
    weights: PriorityWeights = DEFAULT_WEIGHTS,
) -> ScoredCandidate:
    """Score one candidate, returning every component separately.

    Args:
        domain_share: how much of the recent week this domain already took,
            0..1. Used to push back against one skill dominating.
    """
    components: dict[str, float] = {}

    # Overdue reviews are the most time-sensitive thing a plan can contain:
    # a review that slips loses the spacing effect it existed for.
    components["due_review"] = weights.due_review * _clamp(candidate.due_pressure)

    # A weak prerequisite blocks everything above it, so it outranks polish.
    components["weak_prerequisite"] = weights.weak_prerequisite * _clamp(
        candidate.prerequisite_weakness
    )

    # Expected learning gain peaks at moderate challenge, not at the extremes.
    # `docs/LEARNING_SCIENCE.md`: comfortable is not well calibrated, and
    # neither is hopeless. Requires evidence — without it, the mastery estimate
    # is a placeholder and this would be scoring a guess.
    if candidate.targets_a_skill and candidate.has_evidence:
        distance_from_ideal = abs(candidate.mastery_probability - IDEAL_CHALLENGE)
        components["expected_gain"] = weights.expected_gain * _clamp(
            1.0 - distance_from_ideal / IDEAL_CHALLENGE_WIDTH
        )
    else:
        components["expected_gain"] = 0.0

    # Practising what we are least sure about buys the most information.
    # An already-independent skill is excluded: re-confirming it teaches little.
    # A never-assessed skill counts for less than a measured-but-shaky one —
    # we cannot target what we have not looked at.
    if not candidate.targets_a_skill or candidate.status == STATUS_INDEPENDENT:
        uncertainty = 0.0
    else:
        uncertainty = (1.0 - candidate.confidence) * (
            1.0 if candidate.has_evidence else UNASSESSED_DISCOUNT
        )
    components["uncertainty"] = weights.uncertainty * _clamp(uncertainty)

    # Balance: the less a domain has been touched, the more it is worth.
    components["skill_balance"] = weights.skill_balance * _clamp(1.0 - domain_share)

    components["goal_relevance"] = weights.goal_relevance * _clamp(candidate.goal_match)
    components["error_follow_up"] = weights.error_follow_up * _clamp(candidate.error_pressure)

    # Speech is scheduled, not left to the learner to opt into.
    modality = 1.0 if candidate.kind == ActivityKind.SPEAKING else 0.0
    components["modality_diversity"] = weights.modality_diversity * modality

    components["transfer_check"] = weights.transfer_check * (1.0 if candidate.is_transfer else 0.0)

    # Something practised today is worth much less than something untouched
    # for a week. Decays to nothing after roughly three days.
    recency = _clamp(1.0 - candidate.days_since_practised / 3.0)
    components["repetition_penalty"] = -weights.repetition_penalty * recency

    return ScoredCandidate(candidate=candidate, components=components)


@dataclass(frozen=True)
class SessionTemplate:
    """A shape for the session, from `docs/ADAPTIVE_ENGINE.md`."""

    minutes: int
    #: Ordered slots. The planner fills each with the best matching candidate.
    slots: tuple[str, ...]

    @classmethod
    def for_minutes(cls, minutes: int) -> SessionTemplate:
        """Pick the closest template at or below the learner's budget."""
        if minutes >= 60:
            return TEMPLATE_60
        if minutes >= 40:
            return TEMPLATE_40
        return TEMPLATE_20


TEMPLATE_20 = SessionTemplate(
    minutes=20,
    slots=(
        ActivityKind.REVIEW,
        ActivityKind.STUDY,
        ActivityKind.OUTPUT,
        ActivityKind.REFLECTION,
    ),
)

TEMPLATE_40 = SessionTemplate(
    minutes=40,
    slots=(
        ActivityKind.REVIEW,
        ActivityKind.INPUT,
        ActivityKind.STUDY,
        ActivityKind.OUTPUT,
        ActivityKind.REFLECTION,
    ),
)

TEMPLATE_60 = SessionTemplate(
    minutes=60,
    slots=(
        ActivityKind.REVIEW,
        ActivityKind.INPUT,
        ActivityKind.STUDY,
        ActivityKind.OUTPUT,
        ActivityKind.SPEAKING,
        ActivityKind.REFLECTION,
    ),
)


@dataclass(frozen=True)
class PlannedItem:
    """One selected activity, with the scoring that chose it.

    Named apart from `models.planning.PlanItem` (the persisted row) so the
    domain object and its storage never get confused at a call site.
    """

    scored: ScoredCandidate
    sequence: int
    slot: str

    @property
    def candidate(self) -> Candidate:
        return self.scored.candidate


@dataclass(frozen=True)
class Plan:
    items: tuple[PlannedItem, ...]
    requested_minutes: int
    engine_version: str = ENGINE_VERSION
    #: Constraints that could not be met, stated plainly rather than hidden.
    unmet_constraints: tuple[str, ...] = field(default=())

    @property
    def total_minutes(self) -> int:
        return sum(item.candidate.estimated_minutes for item in self.items)

    @property
    def has_receptive(self) -> bool:
        return any(item.candidate.is_receptive for item in self.items)

    @property
    def has_productive(self) -> bool:
        return any(item.candidate.is_productive for item in self.items)


def build_plan(
    candidates: list[Candidate],
    *,
    requested_minutes: int,
    domain_shares: dict[str, float] | None = None,
    weights: PriorityWeights = DEFAULT_WEIGHTS,
) -> Plan:
    """Select and order a day's plan.

    Fills the session template slot by slot with the highest-priority
    candidate of the right kind, then enforces the balance constraints. When a
    constraint cannot be satisfied — usually because no candidate of that kind
    exists yet — it is recorded in `unmet_constraints` rather than silently
    dropped, so the gap is visible instead of looking like a complete plan.
    """
    if not candidates:
        return Plan(
            items=(),
            requested_minutes=requested_minutes,
            unmet_constraints=("no activities available",),
        )

    shares = domain_shares or {}
    scored = [
        score_candidate(
            candidate, domain_share=shares.get(candidate.domain.value, 0.0), weights=weights
        )
        for candidate in candidates
    ]

    template = SessionTemplate.for_minutes(requested_minutes)
    remaining = list(scored)
    chosen: list[tuple[ScoredCandidate, str]] = []
    minutes_used = 0

    for slot in template.slots:
        best = _best_for_slot(remaining, slot)
        if best is None:
            continue
        if minutes_used + best.candidate.estimated_minutes > requested_minutes:
            continue
        chosen.append((best, slot))
        remaining.remove(best)
        minutes_used += best.candidate.estimated_minutes

    unmet: list[str] = []

    # Balance constraints, repaired where possible.
    if chosen and not any(item.candidate.is_productive for item, _ in chosen):
        swapped = _swap_in_kind(chosen, remaining, PRODUCTIVE_KINDS, requested_minutes)
        if swapped:
            chosen = swapped
        else:
            unmet.append("no productive activity was available")

    if chosen and not any(item.candidate.is_receptive for item, _ in chosen):
        swapped = _swap_in_kind(chosen, remaining, RECEPTIVE_KINDS, requested_minutes)
        if swapped:
            chosen = swapped
        else:
            unmet.append("no receptive activity was available")

    ordered = _order_for_fatigue([item for item, _ in chosen], [slot for _, slot in chosen])

    items = tuple(
        PlannedItem(scored=scored_candidate, sequence=index, slot=slot)
        for index, (scored_candidate, slot) in enumerate(ordered)
    )

    if not items:
        unmet.append("nothing fitted the available time")

    return Plan(
        items=items,
        requested_minutes=requested_minutes,
        unmet_constraints=tuple(unmet),
    )


def _best_for_slot(scored: list[ScoredCandidate], slot: str) -> ScoredCandidate | None:
    matching = [item for item in scored if item.candidate.kind == slot]
    if not matching:
        return None
    # Ties break towards something the learner can actually start, then by
    # activity key so the same inputs always give the same plan.
    return max(
        matching,
        key=lambda item: (
            item.priority,
            item.candidate.is_openable,
            item.candidate.activity_key,
        ),
    )


def _swap_in_kind(
    chosen: list[tuple[ScoredCandidate, str]],
    remaining: list[ScoredCandidate],
    kinds: frozenset[str],
    budget: int,
) -> list[tuple[ScoredCandidate, str]] | None:
    """Replace the lowest-priority item with the best candidate of `kinds`.

    Used to repair a plan that violated the receptive/productive balance.
    Returns `None` when no swap fits the time budget.
    """
    options = [item for item in remaining if item.candidate.kind in kinds]
    if not options or not chosen:
        return None

    replacement = max(
        options,
        key=lambda item: (
            item.priority,
            item.candidate.is_openable,
            item.candidate.activity_key,
        ),
    )
    weakest_index = min(range(len(chosen)), key=lambda index: chosen[index][0].priority)
    weakest, slot = chosen[weakest_index]

    used = sum(item.candidate.estimated_minutes for item, _ in chosen)
    projected = used - weakest.candidate.estimated_minutes + replacement.candidate.estimated_minutes
    if projected > budget:
        return None

    repaired = list(chosen)
    repaired[weakest_index] = (replacement, slot)
    return repaired


def _order_for_fatigue(
    items: list[ScoredCandidate], slots: list[str]
) -> list[tuple[ScoredCandidate, str]]:
    """Re-order so no more than two heavy tasks run consecutively.

    The template already gives a sensible shape; this only intervenes when that
    shape would stack demanding work. A learner three heavy tasks deep is
    measuring their stamina, not their English.
    """
    pairs = list(zip(items, slots, strict=True))
    result: list[tuple[ScoredCandidate, str]] = []
    pending = list(pairs)
    consecutive_heavy = 0

    while pending:
        index = 0
        if consecutive_heavy >= MAX_CONSECUTIVE_HEAVY:
            light = next(
                (i for i, (item, _) in enumerate(pending) if not item.candidate.is_heavy),
                None,
            )
            if light is not None:
                index = light

        item, slot = pending.pop(index)
        result.append((item, slot))
        consecutive_heavy = consecutive_heavy + 1 if item.candidate.is_heavy else 0

    return result


def explain(item: PlannedItem) -> str:
    """A one-line, learner-facing reason for an item's presence."""
    reasons = {
        PlanReasonCode.DUE_REVIEW: "Due for review — revisiting this now is what makes it stick.",
        PlanReasonCode.EXPECTED_GAIN: "Right at the edge of what you can already do.",
        PlanReasonCode.WEAK_PREREQUISITE: "This underpins other things you are working towards.",
        PlanReasonCode.UNCERTAINTY: "We do not have much evidence here yet.",
        PlanReasonCode.SKILL_BALANCE: "You have not spent much time on this recently.",
        PlanReasonCode.GOAL_RELEVANCE: "This is close to the goal you set.",
        PlanReasonCode.ERROR_FOLLOW_UP: "This follows up a mistake that keeps recurring.",
        PlanReasonCode.MODALITY_DIVERSITY: "Speaking practice, scheduled rather than optional.",
        PlanReasonCode.TRANSFER_CHECK: "A chance to use this in a new situation.",
    }
    codes = item.scored.reason_codes
    if not codes:
        return "Part of a balanced session."
    return reasons[codes[0]]


def with_minutes(candidate: Candidate, minutes: int) -> Candidate:
    """Helper for callers fitting a candidate to a slot length."""
    return replace(candidate, estimated_minutes=minutes)
