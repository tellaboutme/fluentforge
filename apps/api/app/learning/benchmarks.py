"""When a benchmark may be taken, and what goes in it.

A benchmark is the only observation in the product that claims to *measure a
level* rather than record that something was practised. `EvidenceType.BENCHMARK`
has existed since the first commit, weighted 1.00 — the joint-highest in the
model — and until now nothing ever wrote one. The strongest evidence the
system can hold was a category with no way to produce it.

Four rules make the claim honest, and each is a refusal.

**Scheduled, never chosen.** A learner who takes a benchmark when they feel
ready measures their confidence, not their level, and the two diverge in
opposite directions for anxious and overconfident learners. Eligibility is
decided here, from the record, and `services/benchmarks.py` refuses a request
that arrives early.

**Unaided.** No hints, no explanation on screen, no second attempt. This is
the one place in the product where independence is 1.0 because nothing was
available to lean on, rather than because the learner happened not to lean.

**Unseen items only.** An item the learner has met before measures whether
they remember that item. Nothing here reuses one, and a benchmark that cannot
be filled with unseen items does not run — saying so is better than quietly
measuring memory.

**It can lower an estimate.** Everything else in the product accumulates:
practice adds evidence and mastery drifts up. A Beta-Bernoulli model moves in
both directions given a failed observation at full weight, and a benchmark is
the first observation strong enough to move it far. That is the point. A
measurement that can only agree with you is not one.

Pure: no database, no I/O. The service layer supplies the record and enforces
what this decides.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models.enums import CefrLevel
from .items import DiagnosticItem, ItemType

#: How often a benchmark is offered.
#:
#: Three weeks is a compromise between two failures. Too often and it becomes
#: practice — the items stop being unseen, and the learner is being tested
#: rather than taught. Too rarely and the profile spends months resting on
#: scaffolded evidence with nothing to check it. A defensible default, not a
#: finding; `docs/LEARNING_SCIENCE.md` asks for these to be validated.
CADENCE = timedelta(days=21)

#: Observations needed before a first benchmark is worth taking. Benchmarking
#: a learner the system has never watched measures the item bank, not them.
MIN_OBSERVATIONS = 12

#: How many items make a benchmark. Long enough that one unlucky item does not
#: swing it; short enough to sit inside a normal session.
ITEM_COUNT = 8

#: The fewest unseen items that will do. Below this the result is too thin to
#: carry the weight a benchmark is given, so it does not run.
MIN_ITEMS = 5

#: Item types a benchmark may use.
#:
#: Closed only, on purpose. A benchmark records evidence at full evaluator
#: confidence, and that is only honest where the answer is known in advance.
#: Written and spoken production stay provisional until a rubric judges them
#: (`docs/API_CONTRACTS.md`), so including them would mean either claiming
#: certainty the checks cannot support or recording a benchmark that is not
#: really one. Productive benchmarking waits for a judged deployment.
ALLOWED_ITEM_TYPES = frozenset(
    {
        ItemType.MULTIPLE_CHOICE,
        ItemType.GAP_FILL,
        ItemType.WORD_ORDER,
    }
)


@dataclass(frozen=True)
class Eligibility:
    """Whether a benchmark may be taken, and why not when it may not."""

    due: bool
    #: Learner-facing. Never "you are not allowed": always what has to happen.
    reason: str
    next_due_at: datetime | None = None

    @property
    def blocked(self) -> bool:
        return not self.due


def eligibility(
    *,
    now: datetime,
    observation_count: int,
    last_benchmark_at: datetime | None,
    unseen_item_count: int,
) -> Eligibility:
    """Decide whether this learner may take a benchmark now.

    Order matters: the reasons are checked from the one the learner can act on
    soonest to the one they cannot act on at all, so the message they get is
    the useful one rather than the first true one.
    """
    if observation_count < MIN_OBSERVATIONS:
        return Eligibility(
            due=False,
            reason=(
                f"A benchmark measures what you can do unaided, and there is not "
                f"enough here yet to check against. Work through "
                f"{MIN_OBSERVATIONS - observation_count} more activities first."
            ),
        )

    if last_benchmark_at is not None:
        next_due = last_benchmark_at + CADENCE
        if now < next_due:
            days = max(1, (next_due - now).days + 1)
            return Eligibility(
                due=False,
                reason=(
                    f"Your last benchmark was recent. The next one is in about "
                    f"{days} day{'' if days == 1 else 's'} — taking them closer "
                    f"together would measure the items rather than you."
                ),
                next_due_at=next_due,
            )

    if unseen_item_count < MIN_ITEMS:
        return Eligibility(
            due=False,
            reason=(
                "There is not enough material you have never seen to make a fair "
                "benchmark. Reusing items would measure whether you remember them."
            ),
        )

    return Eligibility(
        due=True,
        reason="A benchmark is due. It is unaided, and it can move your profile either way.",
    )


def _band_distance(item_level: CefrLevel, band: CefrLevel) -> int:
    return abs(item_level.rank - band.rank)


def select_items(
    bank: Sequence[DiagnosticItem],
    *,
    band: CefrLevel,
    seen_keys: Iterable[str],
    count: int = ITEM_COUNT,
) -> tuple[DiagnosticItem, ...]:
    """Choose the items for one benchmark.

    Three things at once, in priority order.

    **Never seen.** An item the learner has met measures recall of that item.

    **Near the band.** A benchmark of C2 items given to an A2 learner measures
    nothing but produces a very confident zero, and the mastery model would
    take it at full weight.

    **Spread across skills.** Eight items on one skill is a deep measurement of
    one thing, and a benchmark is supposed to be a wide one. So the first pass
    takes one item per skill before any skill gets a second.

    Deterministic throughout: the same learner in the same state gets the same
    benchmark, which is what makes a disputed result checkable.
    """
    already = set(seen_keys)
    candidates = [
        item for item in bank if item.key not in already and item.item_type in ALLOWED_ITEM_TYPES
    ]
    candidates.sort(key=lambda item: (_band_distance(item.cefr_level, band), item.key))

    chosen: list[DiagnosticItem] = []
    used_skills: set[str] = set()

    for item in candidates:
        if len(chosen) >= count:
            break
        if item.skill_key in used_skills:
            continue
        chosen.append(item)
        used_skills.add(item.skill_key)

    # Second pass: fill any remaining places, breadth having been served.
    for item in candidates:
        if len(chosen) >= count:
            break
        if item in chosen:
            continue
        chosen.append(item)

    return tuple(chosen)


__all__ = [
    "ALLOWED_ITEM_TYPES",
    "CADENCE",
    "ITEM_COUNT",
    "MIN_ITEMS",
    "MIN_OBSERVATIONS",
    "Eligibility",
    "eligibility",
    "select_items",
]
