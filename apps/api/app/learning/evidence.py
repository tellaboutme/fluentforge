"""Evidence weighting and the evidence-to-mastery model.

Design (model version 0.1.0)
----------------------------
A learner's mastery of a skill is a Beta-Bernoulli posterior. Every observation
contributes a fractional pseudo-count rather than a whole one:

    alpha += weight * score
    beta  += weight * (1 - score)
    mastery_probability = alpha / (alpha + beta)

The whole design lives in that ``weight``. A correct answer is not one unit of
proof; it is worth as much as the conditions under which it was produced. The
factors are multiplied, each bounded, each independently testable:

1. **Evidence type** — recognising a word is weaker proof than using it in a new
   context. Recognition can never, on its own, establish productive mastery.
2. **Independence** — hints and scaffolding reduce weight (`docs/LEARNING_SCIENCE.md`).
3. **Novelty** — a previously seen item proves less than an unseen one.
4. **Difficulty relevance** — succeeding at a hard task is strong positive
   evidence; failing an easy task is strong negative evidence. The converse
   cases are discounted, not ignored.
5. **Evaluator confidence** — an unsure evaluator moves the estimate less.
6. **Repetition damping** — the nth observation in the same context within the
   same window is worth a fraction of the first, so drilling one item cannot
   manufacture mastery.

Beta-Bernoulli was chosen over Elo because the posterior carries its own
evidence mass, which is what `confidence` needs, and because every intermediate
number stays inspectable. Raw `evidence_events` are never discarded, so this
model can be replaced without losing history.

The constants below are starting values, not findings. `docs/LEARNING_SCIENCE.md`
requires that they be validated against usage data before being treated as more
than a defensible default.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models.enums import EvidenceType

MODEL_VERSION = "0.1.0"

#: How much each kind of observation can prove, at best.
#: Ordered by how much learner effort and generalisation it demonstrates.
EVIDENCE_TYPE_WEIGHTS: dict[EvidenceType, float] = {
    EvidenceType.SELF_REPORT: 0.15,
    EvidenceType.RECOGNITION: 0.35,
    EvidenceType.CONTROLLED_RECALL: 0.55,
    EvidenceType.COMPREHENSION: 0.60,
    EvidenceType.CONTEXTUAL_PRODUCTION: 0.90,
    EvidenceType.INTERACTION: 0.90,
    EvidenceType.TRANSFER: 1.00,
    EvidenceType.BENCHMARK: 1.00,
}


@dataclass(frozen=True)
class MasteryModelConfig:
    """Tunable parameters of the mastery model.

    Kept in one place, versioned with `MODEL_VERSION`, so a change is visible
    and a stored `SkillState` always records which version produced it.
    """

    #: Uniform Beta(1, 1) prior: no assumption about a new learner.
    prior_alpha: float = 1.0
    prior_beta: float = 1.0

    #: Weight retained by each successive observation in the same context.
    repetition_decay: float = 0.5
    #: Observations closer together than this count as repetition.
    repetition_window: timedelta = timedelta(days=1)

    #: Floor on the difficulty-relevance factor: mismatched difficulty is
    #: discounted, never discarded.
    min_difficulty_relevance: float = 0.5

    #: Evidence mass at which concentration reaches half its maximum.
    concentration_halflife: float = 1.5
    #: Confidence retained by a single context; breadth raises it to 1.0.
    min_breadth_factor: float = 0.4
    #: Days after which unrefreshed confidence halves. Mastery itself does not decay.
    confidence_halflife_days: float = 30.0

    #: Contexts needed before breadth stops limiting confidence.
    target_distinct_contexts: int = 3


DEFAULT_CONFIG = MasteryModelConfig()


@dataclass(frozen=True)
class Observation:
    """One evidence event, reduced to what the model needs.

    Decoupled from the ORM so the model can be unit-tested and replayed without
    a database.
    """

    evidence_type: EvidenceType
    score: float
    occurred_at: datetime
    weight: float = 1.0
    difficulty: float = 0.5
    confidence: float = 1.0
    independence: float = 1.0
    novelty: float = 1.0
    context_key: str | None = None


@dataclass(frozen=True)
class WeightBreakdown:
    """Why an observation counted for as much as it did.

    Returned alongside the result so the UI can answer "why did my skill
    estimate change?" without re-deriving anything.
    """

    base: float
    independence: float
    novelty: float
    difficulty_relevance: float
    evaluator_confidence: float
    repetition_damping: float
    declared_weight: float

    @property
    def effective(self) -> float:
        return (
            self.base
            * self.independence
            * self.novelty
            * self.difficulty_relevance
            * self.evaluator_confidence
            * self.repetition_damping
            * self.declared_weight
        )


@dataclass(frozen=True)
class MasteryResult:
    mastery_probability: float
    confidence: float
    stability: float
    evidence_count: int
    distinct_contexts: int
    last_observed_at: datetime | None
    model_version: str = MODEL_VERSION
    breakdowns: tuple[WeightBreakdown, ...] = field(default=())

    @property
    def evidence_mass(self) -> float:
        return sum(item.effective for item in self.breakdowns)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def difficulty_relevance(score: float, difficulty: float, config: MasteryModelConfig) -> float:
    """How diagnostic this result is, given how hard the task was.

    A success on a hard task and a failure on an easy task are both informative.
    A success on a trivial task says little; so does a failure on a very hard one.
    """
    difficulty = _clamp(difficulty)
    informativeness = difficulty if score >= 0.5 else 1.0 - difficulty
    floor = config.min_difficulty_relevance
    return floor + (1.0 - floor) * informativeness


def repetition_damping(
    observation: Observation,
    prior_in_context: list[Observation],
    config: MasteryModelConfig,
) -> float:
    """Diminishing returns for repeated practice of the same context.

    Only observations inside `repetition_window` count as repetition, so
    genuinely spaced retrieval keeps its full weight — which is the behaviour
    `docs/LEARNING_SCIENCE.md` asks for.
    """
    if observation.context_key is None:
        return 1.0

    recent = sum(
        1
        for earlier in prior_in_context
        if observation.occurred_at - earlier.occurred_at <= config.repetition_window
    )
    return float(config.repetition_decay**recent)


def weigh(
    observation: Observation,
    prior_in_context: list[Observation],
    config: MasteryModelConfig = DEFAULT_CONFIG,
) -> WeightBreakdown:
    """Compute the effective weight of one observation, with its components."""
    return WeightBreakdown(
        base=EVIDENCE_TYPE_WEIGHTS.get(observation.evidence_type, 0.5),
        independence=_clamp(observation.independence),
        novelty=_clamp(observation.novelty),
        difficulty_relevance=difficulty_relevance(
            observation.score, observation.difficulty, config
        ),
        evaluator_confidence=_clamp(observation.confidence),
        repetition_damping=repetition_damping(observation, prior_in_context, config),
        declared_weight=max(0.0, observation.weight),
    )


def compute_mastery(
    observations: list[Observation],
    *,
    now: datetime,
    config: MasteryModelConfig = DEFAULT_CONFIG,
) -> MasteryResult:
    """Fold every observation for one skill into a mastery estimate.

    Recomputed from full history rather than updated incrementally: the model is
    still changing, and replaying raw evidence keeps stored state reproducible.
    """
    if not observations:
        return MasteryResult(
            mastery_probability=0.0,
            confidence=0.0,
            stability=0.0,
            evidence_count=0,
            distinct_contexts=0,
            last_observed_at=None,
        )

    ordered = sorted(observations, key=lambda item: item.occurred_at)

    alpha = config.prior_alpha
    beta = config.prior_beta
    seen_by_context: dict[str, list[Observation]] = defaultdict(list)
    breakdowns: list[WeightBreakdown] = []

    for observation in ordered:
        context = observation.context_key
        prior_in_context = seen_by_context[context] if context is not None else []
        breakdown = weigh(observation, prior_in_context, config)
        breakdowns.append(breakdown)

        score = _clamp(observation.score)
        alpha += breakdown.effective * score
        beta += breakdown.effective * (1.0 - score)

        if context is not None:
            seen_by_context[context].append(observation)

    mastery_probability = alpha / (alpha + beta)
    evidence_mass = alpha + beta - config.prior_alpha - config.prior_beta
    distinct_contexts = len(seen_by_context)
    last_observed_at = ordered[-1].occurred_at

    return MasteryResult(
        mastery_probability=round(mastery_probability, 6),
        confidence=round(
            _confidence(
                evidence_mass=evidence_mass,
                distinct_contexts=distinct_contexts,
                last_observed_at=last_observed_at,
                now=now,
                config=config,
            ),
            6,
        ),
        stability=round(evidence_mass, 6),
        evidence_count=len(ordered),
        distinct_contexts=distinct_contexts,
        last_observed_at=last_observed_at,
        breakdowns=tuple(breakdowns),
    )


def _confidence(
    *,
    evidence_mass: float,
    distinct_contexts: int,
    last_observed_at: datetime,
    now: datetime,
    config: MasteryModelConfig,
) -> float:
    """How much the estimate can be trusted, independent of how high it is.

    Three limits, multiplied:

    - **concentration** — how much evidence there is;
    - **breadth** — across how many distinct contexts;
    - **recency** — how long since it was last observed.

    Recency is why confidence decays without practice while
    `mastery_probability` does not: the learner has not become worse, we have
    become less sure.
    """
    concentration = evidence_mass / (evidence_mass + config.concentration_halflife)

    breadth_ratio = _clamp(distinct_contexts / max(config.target_distinct_contexts, 1))
    breadth = config.min_breadth_factor + (1.0 - config.min_breadth_factor) * breadth_ratio

    elapsed_days = max((now - last_observed_at).total_seconds(), 0.0) / 86400.0
    recency = 0.5 ** (elapsed_days / config.confidence_halflife_days)

    return _clamp(concentration * breadth * recency)
