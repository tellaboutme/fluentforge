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

It runs in two stages, and the first one exists because of a lesson learned
the hard way. The provider collapses *every* failure into `None` -- a 404, a
rate limit, a truncated answer, an invented quotation. That is exactly right
for a learner, who must never see a stack trace because a model was busy. It
is useless for working out what went wrong, and the first version of this
script confidently advised "try a larger model" at somebody staring at a
100% abstention rate from a 120-billion-parameter one.

So stage one talks to the endpoint directly and prints what came back. Stage
two runs the real provider. If stage one fails, nothing about stage two is
informative.

Reads `.env` like the API does. Prints a summary and exits non-zero if
everything abstained, because that is a configuration failure worth noticing
in a script's exit code.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.api.app.providers import get_writing_evaluator
from apps.api.app.providers.base import (
    MIN_USABLE_CONFIDENCE,
    WritingEvaluationRequest,
)
from apps.api.app.providers.cloud import _extract_json
from apps.api.app.providers.compatible import CompatibleWritingEvaluator
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


def probe() -> bool:
    """Talk to the endpoint directly and print exactly what comes back.

    Deliberately not routed through the provider. The provider's job is to
    swallow every failure so a learner never sees one; this function's job is
    the opposite, and using the provider here would reproduce the blindness
    that made the first version of this script give bad advice.

    Returns False when the exchange itself failed, in which case nothing the
    provider does afterwards is worth interpreting.
    """
    if not isinstance(get_writing_evaluator(), CompatibleWritingEvaluator):
        # `local` and `cloud` have their own shapes and their own defaults.
        # Probing them would mean guessing at a URL, and a wrong guess would
        # be reported as a broken deployment.
        print("(probe skipped: only the `compatible` provider is probed directly)\n")
        return True

    base = CompatibleWritingEvaluator._configured_base_url()
    if base is None:
        print("AI_BASE_URL is not set to anything usable. See docs/TESTING.md part 4.")
        return False

    url = f"{base}/v1/chat/completions"
    print(f"probing  : {url}")

    payload = {
        "model": settings.ai_model,
        "temperature": 0.0,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": 'Reply with only this JSON: {"ok": true}'},
            {"role": "user", "content": "Reply now."},
        ],
    }

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {settings.ai_api_key}",
            },
            timeout=60.0,
        )
    except (httpx.HTTPError, OSError) as exc:
        print(f"FAILED   : could not reach it at all -- {exc!r}")
        return False

    print(f"status   : {response.status_code}")

    if response.status_code != 200:
        # The whole reason for this stage. A 404 from a doubled path and a
        # 429 from a spent quota are completely different problems that the
        # provider reports identically, which is to say not at all.
        print(f"body     : {response.text[:800]}")
        print()
        if response.status_code == 404:
            print("A 404 usually means the path is wrong. Check AI_BASE_URL.")
        elif response.status_code in (401, 403):
            print("Check the key. It may have been revoked or mistyped.")
        elif response.status_code == 429:
            print("Rate limited or out of quota. Wait, or use another provider.")
        elif response.status_code == 400:
            print("The model rejected the request. Often an unknown model id.")
        return False

    body = response.json()
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    finish = choice.get("finish_reason")

    print(f"finish   : {finish}")
    print(f"content  : {content[:300]!r}")

    # Reasoning models put their working somewhere else and can spend the
    # whole token budget on it, returning an empty `content` with a perfectly
    # successful 200. That looks identical to a broken model from outside.
    reasoning = message.get("reasoning")
    if reasoning:
        print(f"reasoning: {str(reasoning)[:200]!r} ...")
    usage = body.get("usage") or {}
    if usage:
        print(f"usage    : {json.dumps(usage)}")

    if not content.strip():
        print()
        print("The model returned 200 with empty content.")
        if finish == "length":
            print("`finish_reason: length` means it ran out of tokens before")
            print("writing anything. Reasoning models spend the budget on")
            print("thinking; raise max_tokens or choose a non-reasoning model.")
        elif reasoning:
            print("It put everything in a `reasoning` field. This provider")
            print("reads `message.content`, so a reasoning-only answer is")
            print("indistinguishable from no answer.")
        return False

    if _extract_json(content) is None:
        print()
        print("Content came back but no JSON object could be found in it.")
        print("The evaluator needs a JSON object; prose alone abstains.")
        return False

    print("probe OK : the endpoint answers and the answer parses.\n")
    return True


def explain(sample: Sample) -> None:
    """Re-send one sample's real request and say why it produced nothing.

    Stage one proves the endpoint answers a trivial prompt. That is a
    different question from whether it answers *this* one, and the gap
    between them is where the first two versions of this script left the
    reader guessing.

    The payload comes from the provider itself rather than being rebuilt
    here. A diagnostic that constructed its own would drift and would
    eventually explain a request nobody makes.
    """
    evaluator = get_writing_evaluator()
    if not isinstance(evaluator, CompatibleWritingEvaluator):
        return

    base = CompatibleWritingEvaluator._configured_base_url()
    if base is None:
        return

    payload = evaluator.build_payload(
        WritingEvaluationRequest(
            task_prompt=sample.prompt,
            target_level=sample.level,
            skill_key="written_production.everyday_texts",
            response_text=sample.text,
        )
    )

    try:
        response = httpx.post(
            f"{base}/v1/chat/completions",
            json=payload,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {settings.ai_api_key}",
            },
            timeout=120.0,
        )
    except (httpx.HTTPError, OSError) as exc:
        print(f"  why     : the request failed -- {exc!r}")
        return

    if response.status_code != 200:
        print(f"  why     : HTTP {response.status_code} -- {response.text[:200]}")
        return

    body = response.json()
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    finish = choice.get("finish_reason")
    usage = body.get("usage") or {}
    reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")

    detail = f"finish={finish} completion={usage.get('completion_tokens')}"
    if reasoning_tokens is not None:
        detail += f" of which reasoning={reasoning_tokens}"
    print(f"  why     : {detail}")

    if finish == "length":
        # The most likely cause with a reasoning model, and the one that is
        # invisible without asking: thinking and answering share one budget.
        budget = settings.ai_max_output_tokens
        print(f"            The answer was cut off at AI_MAX_OUTPUT_TOKENS={budget}.")
        if reasoning_tokens:
            print(f"            {reasoning_tokens} of those went on reasoning, not output.")
            print("            Raise AI_MAX_OUTPUT_TOKENS, or use a model that")
            print("            does not think before answering.")
        else:
            print("            Raise AI_MAX_OUTPUT_TOKENS.")
        return

    if not content.strip():
        print("            200 with empty content. Nothing to parse.")
        return

    raw = _extract_json(content)
    if raw is None:
        print(f"            No JSON object in the answer: {content[:200]!r}")
        return

    print("            JSON parsed but the rubric schema rejected it, or a")
    print(f"            quotation was not in the learner's text. Keys: {sorted(raw)}")


def main() -> int:
    print(f"provider : {settings.ai_provider}")
    print(f"endpoint : {settings.ai_base_url or '(unset)'}")
    print(f"model    : {settings.ai_model}")
    print(f"max out  : {settings.ai_max_output_tokens} tokens")
    print(f"key      : {'set' if settings.ai_api_key else 'NOT SET'}")
    print()

    if settings.ai_provider == "disabled":
        print("AI_PROVIDER is 'disabled', so nothing will be called.")
        print("See docs/TESTING.md part 4.")
        return 1

    if not probe():
        print()
        print("Stage one failed, so the rubric samples below would tell you")
        print("nothing beyond what you already know. Fix the above first.")
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
            # violation, or a quotation the learner never wrote. It cannot
            # say which, by design, so ask the endpoint again and look.
            abstained += 1
            print("got     : ABSTAINED (no usable judgement returned)")
            explain(sample)
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
    print("  - Stage one passed, so the endpoint works and the model can")
    print("    answer. Abstaining on everything therefore means it cannot")
    print("    hold the *rubric* schema, or is inventing quotations -- not")
    print("    that it is broken or too small.")
    print("  - Check the quoted text appears in the sample. If a quote looks")
    print("    plausible but is not there, the provider caught it and the")
    print("    sample shows as abstained rather than as bad feedback.")

    # Every sample abstaining is a configuration or model-capability failure,
    # not a verdict about the samples.
    return 1 if abstained == total else 0


if __name__ == "__main__":
    raise SystemExit(main())
