"""Point the rubric evaluator at a real model and report what it does.

Nothing in this repository has ever called a language model. Every test runs
against `AI_PROVIDER=disabled`, which is correct -- the learning loop must work
without AI -- but it means the rubric path has been exercised only against
stubs that answer perfectly.

This script answers the one question that decides whether a given model is
usable: **how often does it abstain?**

Abstention is designed for and is never an error. The provider returns `None`
rather than guessing when the model times out, breaks the response schema, or
quotes text the learner did not write. A learner then gets exactly the
deterministic feedback they would have had. But a model that abstains on
nine samples out of ten is not doing anything, and the only way to find out
is to ask it.

The samples below are deliberately uneven: two competent, two weak, one
off-task, one very short. A model that judges all six identically has not
read them.

Usage:
    uv run python scripts/ai_smoke.py

Reads `.env` like the API does. Prints a summary and exits non-zero if
everything abstained, because that is a configuration failure worth noticing
in a script's exit code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.api.app.providers import get_writing_evaluator
from apps.api.app.providers.base import (
    MIN_USABLE_CONFIDENCE,
    WritingEvaluationRequest,
)
from apps.api.app.settings import settings


@dataclass(frozen=True)
class Sample:
    """One submission, and what a competent reader would say about it."""

    label: str
    level: str
    prompt: str
    text: str
    #: What a human marker would expect. Not asserted -- the point is to read
    #: the model's answer beside it, not to grade the model automatically.
    expectation: str


SAMPLES: tuple[Sample, ...] = (
    Sample(
        label="B1 competent",
        level="B1",
        prompt="Write to a friend about something you did last weekend.",
        text=(
            "Hi Marta, last weekend I finally visited my sister in Gdansk. "
            "We walked along the coast on Saturday even though it was cold, "
            "and on Sunday she showed me the shipyard museum. She has been "
            "working there since March and she loves it. Next time you should "
            "come with me."
        ),
        expectation="Task achieved, accurate, well linked. Should score high.",
    ),
    Sample(
        label="B1 weak grammar",
        level="B1",
        prompt="Write to a friend about something you did last weekend.",
        text=(
            "Hi, last weekend I go to my sister house. We was walking in city "
            "and after we eat pizza. She work there since two years. It was "
            "very nice and I am happy for see her."
        ),
        expectation=(
            "Task achieved, repeated tense and agreement errors. A good "
            "evaluator names the past simple and 'since/for', and quotes them."
        ),
    ),
    Sample(
        label="B2 argument",
        level="B2",
        prompt="Some employers expect staff to be reachable outside working hours. Discuss.",
        text=(
            "Employers who expect availability outside contracted hours often "
            "defend it as flexibility, but the flexibility runs one way. The "
            "argument that modern work is simply faster ignores that response "
            "time is a choice about staffing, not a fact about technology. "
            "That said, a blanket ban would penalise the people who genuinely "
            "prefer to answer a message at nine in the evening and finish "
            "early on Friday."
        ),
        expectation="Strong: concession, hedging, clear stance. Should score high.",
    ),
    Sample(
        label="B2 unstructured",
        level="B2",
        prompt="Some employers expect staff to be reachable outside working hours. Discuss.",
        text=(
            "I think it is bad. People need rest. Also companies want more "
            "work for same money. But sometimes it is necessary for example "
            "emergency. Also some people like it. In conclusion it depends on "
            "the situation and the person."
        ),
        expectation=(
            "On task, but assertions without development and no cohesion "
            "beyond 'also'. A good evaluator names organisation, not grammar."
        ),
    ),
    Sample(
        label="off task",
        level="B1",
        prompt="Write to a friend about something you did last weekend.",
        text=(
            "The capital of Poland is Warsaw. It has a population of about "
            "1.8 million people and is located on the Vistula river."
        ),
        expectation=(
            "Fluent and entirely off task. A model that scores this well is "
            "grading language and ignoring the rubric."
        ),
    ),
    Sample(
        label="too short to judge",
        level="A2",
        prompt="Write about your typical morning.",
        text="I wake up. I drink coffee.",
        expectation=(
            "Abstaining here is the *right* answer. There is not enough to "
            "judge, and a confident verdict on eight words is worse than none."
        ),
    ),
)


def main() -> int:
    print(f"provider : {settings.ai_provider}")
    print(f"endpoint : {settings.ai_base_url or '(unset)'}")
    print(f"model    : {settings.ai_model}")
    print(f"key      : {'set' if settings.ai_api_key else 'NOT SET'}")
    print()

    if settings.ai_provider == "disabled":
        print("AI_PROVIDER is 'disabled', so nothing will be called.")
        print("See docs/TESTING.md part 4.")
        return 1

    evaluator = get_writing_evaluator()
    abstained = 0
    unusable = 0
    usable = 0

    for sample in SAMPLES:
        print(f"--- {sample.label} ({sample.level}) " + "-" * (48 - len(sample.label)))
        print(f"expected: {sample.expectation}")

        result = evaluator.evaluate(
            WritingEvaluationRequest(
                task_prompt=sample.prompt,
                target_level=sample.level,
                skill_key="written_production.everyday_texts",
                response_text=sample.text,
            )
        )

        if result is None:
            # The provider already refused this: a timeout, a schema
            # violation, or a quotation the learner never wrote.
            abstained += 1
            print("got     : ABSTAINED (no usable judgement returned)")
            print()
            continue

        if not result.is_usable:
            # A judgement came back but is too uncertain to become evidence.
            # A different outcome from abstaining, and worth separating.
            unusable += 1
            print(
                f"got     : returned, but confidence {result.confidence} "
                f"is below {MIN_USABLE_CONFIDENCE} so it evidences nothing"
            )
        else:
            usable += 1
            print(f"got     : usable, confidence {result.confidence}")

        for dimension in result.dimensions:
            print(f"  {dimension.name}: {dimension.score}")
            for quote in dimension.evidence:
                print(f"    quoted: {quote!r}")
        for item in result.priority_feedback:
            # The shape the rubric actually asks for: what the learner wrote,
            # what it should be, and why. A correction with no `original` is
            # advice rather than feedback.
            print(f"  priority [{item.category}]")
            print(f"    wrote   : {item.original!r}")
            print(f"    better  : {item.improved!r}")
            print(f"    because : {item.explanation}")
        print()

    total = len(SAMPLES)
    print("=" * 60)
    print(f"usable   : {usable}/{total}")
    print(f"returned but too uncertain: {unusable}/{total}")
    print(f"abstained: {abstained}/{total}  ({abstained / total:.0%})")
    print()
    print("How to read this:")
    print("  - Some abstention is correct. 'too short to judge' should abstain.")
    print("  - Abstaining on everything means the model cannot hold the output")
    print("    schema, or is inventing quotations. Try a larger model.")
    print("  - Check the quoted text appears in the sample. If a quote looks")
    print("    plausible but is not there, the provider caught it and the")
    print("    sample shows as abstained rather than as bad feedback.")

    # Every sample abstaining is a configuration or model-capability failure,
    # not a verdict about the samples.
    return 1 if abstained == total else 0


if __name__ == "__main__":
    raise SystemExit(main())
