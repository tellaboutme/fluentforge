"""The hosted rubric evaluator.

Every test here is a way the outside world can misbehave. The evaluator's
whole job is to turn each of them into `None`, because `docs/PRODUCT_SPEC.md`
makes AI an accelerator and a learner's submission must survive a bad day at
someone else's API.

The one test that is not about failure is the one that matters most: a
schema-valid judgement whose quotations do not appear in the learner's text is
**rejected**. A model that invents evidence is not judging this piece of
writing, and `docs/AI_TUTOR_BEHAVIOR.md` does not let that reach the mastery
model.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from apps.api.app.providers.base import WritingEvaluationRequest
from apps.api.app.providers.cloud import CloudWritingEvaluator, _extract_json
from apps.api.app.settings import settings

RESPONSE_TEXT = (
    "Hi Sam, I am very sorry but I will be late tomorrow. My train was "
    "cancelled, so I have to wait for the next one."
)

REQUEST = WritingEvaluationRequest(
    task_prompt="Write an email saying you will be late.",
    response_text=RESPONSE_TEXT,
    target_level="A2",
    skill_key="writing.linked_messages",
)


def _body(payload: dict[str, Any]) -> dict[str, Any]:
    """A response shaped like the Messages API, carrying `payload` as JSON."""
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dimensions": [
            {
                "name": "accuracy",
                "score": 0.7,
                "confidence": 0.8,
                "evidence": ["My train was cancelled"],
            }
        ],
        "priority_feedback": [],
        "confidence": 0.8,
    }
    payload.update(overrides)
    return payload


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _responds(payload: dict[str, Any], status: int = 200) -> httpx.Client:
    return _client(lambda request: httpx.Response(status, json=payload))


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch):
    """Give the evaluator a key. Its absence is tested explicitly below."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "ai_model", "test-model", raising=False)
    yield


# --- The happy path --------------------------------------------------------------


def test_a_valid_judgement_is_returned() -> None:
    evaluator = CloudWritingEvaluator(client=_responds(_body(_valid_payload())))
    result = evaluator.evaluate(REQUEST)

    assert result is not None
    assert result.is_usable
    assert result.provider == "cloud"
    assert result.dimensions[0].name == "accuracy"


def test_the_prompt_version_travels_with_the_judgement() -> None:
    """So a later prompt change is visible in history rather than silently
    reinterpreting past evidence."""
    evaluator = CloudWritingEvaluator(client=_responds(_body(_valid_payload())))
    result = evaluator.evaluate(REQUEST)

    assert result is not None
    assert result.prompt_version
    assert result.prompt_version != "unknown"


def test_json_wrapped_in_prose_is_still_read() -> None:
    """Models fence or preface their JSON often enough that rejecting on that
    alone would throw away usable judgements."""
    wrapped = {
        "content": [
            {
                "type": "text",
                "text": "Here is my assessment:\n```json\n"
                + json.dumps(_valid_payload())
                + "\n```\nHope that helps.",
            }
        ]
    }
    evaluator = CloudWritingEvaluator(client=_responds(wrapped))
    assert evaluator.evaluate(REQUEST) is not None


def test_the_learner_text_and_level_are_actually_sent() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_body(_valid_payload()))

    CloudWritingEvaluator(client=_client(handler)).evaluate(REQUEST)

    sent = json.loads(seen["messages"][0]["content"])
    assert sent["response_text"] == RESPONSE_TEXT
    assert sent["target_level"] == "A2"
    assert seen["model"] == "test-model"
    assert seen["system"]


# --- Fabricated evidence ---------------------------------------------------------


def test_an_invented_quotation_is_rejected() -> None:
    """The load-bearing test. Schema-valid is not the same as honest."""
    payload = _valid_payload(
        dimensions=[
            {
                "name": "accuracy",
                "score": 0.9,
                "confidence": 0.9,
                "evidence": ["I regret to inform you of the delay"],
            }
        ]
    )
    evaluator = CloudWritingEvaluator(client=_responds(_body(payload)))
    assert evaluator.evaluate(REQUEST) is None


def test_a_quotation_reflowed_across_lines_is_accepted() -> None:
    """Whitespace and case are formatting, not fabrication."""
    payload = _valid_payload(
        dimensions=[
            {
                "name": "accuracy",
                "score": 0.7,
                "confidence": 0.8,
                "evidence": ["my   train\nwas CANCELLED"],
            }
        ]
    )
    evaluator = CloudWritingEvaluator(client=_responds(_body(payload)))
    assert evaluator.evaluate(REQUEST) is not None


# --- Everything that can go wrong ------------------------------------------------


def test_no_api_key_abstains(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured as cloud but never given a key. A stack trace on a
    learner's submission is not an acceptable way to report that."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    evaluator = CloudWritingEvaluator(client=_responds(_body(_valid_payload())))
    assert evaluator.evaluate(REQUEST) is None


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_an_http_error_abstains(status: int) -> None:
    evaluator = CloudWritingEvaluator(client=_responds({"error": "no"}, status=status))
    assert evaluator.evaluate(REQUEST) is None


def test_a_timeout_abstains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    assert CloudWritingEvaluator(client=_client(handler)).evaluate(REQUEST) is None


def test_a_transport_failure_abstains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    assert CloudWritingEvaluator(client=_client(handler)).evaluate(REQUEST) is None


def test_a_response_with_no_json_abstains() -> None:
    body = {"content": [{"type": "text", "text": "I would rather not."}]}
    assert CloudWritingEvaluator(client=_responds(body)).evaluate(REQUEST) is None


def test_malformed_json_abstains() -> None:
    body = {"content": [{"type": "text", "text": '{"dimensions": [ oh dear'}]}
    assert CloudWritingEvaluator(client=_responds(body)).evaluate(REQUEST) is None


def test_a_schema_violation_abstains() -> None:
    """Score outside 0..1. Forgiving about where the JSON is, unforgiving
    about what it says."""
    payload = _valid_payload(
        dimensions=[{"name": "accuracy", "score": 7.0, "confidence": 0.8, "evidence": ["My train"]}]
    )
    assert CloudWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None


def test_an_unexpected_extra_field_abstains() -> None:
    """The schema forbids extras, so a model inventing a field is discarded
    rather than half-trusted."""
    payload = _valid_payload(overall_grade="B+")
    assert CloudWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None


def test_an_empty_content_array_abstains() -> None:
    assert CloudWritingEvaluator(client=_responds({"content": []})).evaluate(REQUEST) is None


def test_more_than_three_corrections_is_refused() -> None:
    """`docs/LEARNING_SCIENCE.md`: correcting everything teaches nothing. The
    cap is in the schema, so a model ignoring it loses the whole judgement."""
    payload = _valid_payload(
        priority_feedback=[
            {"category": "grammar", "original": "a", "improved": "b", "explanation": "c"}
            for _ in range(4)
        ]
    )
    assert CloudWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None


def test_an_explicit_abstention_is_passed_through_as_unusable() -> None:
    payload = {
        "dimensions": [],
        "priority_feedback": [],
        "confidence": 0.9,
        "abstain_reason": "the response is off-topic",
    }
    result = CloudWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST)

    # Returned, not discarded: an abstention with a reason is information.
    assert result is not None
    assert result.abstained
    assert result.is_usable is False


# --- The JSON extractor ----------------------------------------------------------


def test_extractor_handles_braces_inside_strings() -> None:
    """A learner writing about JSON must not break the parser."""
    text = 'prose {"a": "a } brace", "b": 1} trailing'
    assert _extract_json(text) == {"a": "a } brace", "b": 1}


def test_extractor_handles_escaped_quotes() -> None:
    text = r'{"a": "she said \"hello\"", "b": 2}'
    assert _extract_json(text) == {"a": 'she said "hello"', "b": 2}


def test_extractor_handles_nesting() -> None:
    assert _extract_json('{"a": {"b": {"c": 1}}}') == {"a": {"b": {"c": 1}}}


def test_extractor_returns_none_without_json() -> None:
    assert _extract_json("no object here") is None
    assert _extract_json('{"unclosed": ') is None


def test_extractor_rejects_a_bare_array() -> None:
    assert _extract_json("[1, 2, 3]") is None


# --- Selection -------------------------------------------------------------------


def test_cloud_mode_selects_this_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app import providers

    monkeypatch.setattr(settings, "ai_provider", "cloud", raising=False)
    providers.get_writing_evaluator.cache_clear()
    try:
        assert isinstance(providers.get_writing_evaluator(), CloudWritingEvaluator)
    finally:
        providers.get_writing_evaluator.cache_clear()


def test_cloud_mode_starts_even_with_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misconfigured deployment degrades to deterministic feedback rather
    than failing at startup and taking the whole API with it."""
    from apps.api.app import providers

    monkeypatch.setattr(settings, "ai_provider", "cloud", raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    providers.get_writing_evaluator.cache_clear()
    try:
        evaluator = providers.get_writing_evaluator()
        assert evaluator.evaluate(REQUEST) is None
    finally:
        providers.get_writing_evaluator.cache_clear()


def test_a_dimension_with_no_evidence_is_rejected_here_too() -> None:
    """The same rule as the local provider, asserted for both. Two rubric
    providers disagreeing about what counts as a usable judgement would make
    the mastery model's numbers incomparable between deployments."""
    payload = _valid_payload(
        dimensions=[{"name": "accuracy", "score": 0.9, "confidence": 0.9, "evidence": []}]
    )
    assert CloudWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None
