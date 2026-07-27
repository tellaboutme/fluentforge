"""The self-hosted rubric evaluator.

Same job as the cloud one, and the tests are organised around the three
places it deliberately differs — no key required, its own default address,
a longer timeout — plus the properties it must **not** differ on.

That second group is the more important one. Two rubric providers that
disagreed about what counts as a usable judgement would make the mastery
model's numbers incomparable between deployments: the same essay, judged by
the same prompt, would land differently depending on where the operator
chose to run the model. So the fabricated-quotation check, the schema, and
the abstain-on-everything rule are asserted here as well, not assumed.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from apps.api.app.providers import ProviderNotAvailableError, get_writing_evaluator
from apps.api.app.providers.base import WritingEvaluationRequest
from apps.api.app.providers.cloud import CloudWritingEvaluator
from apps.api.app.providers.local import (
    DEFAULT_BASE_URL,
    TIMEOUT_SECONDS,
    LocalWritingEvaluator,
)
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
    """A response shaped like OpenAI chat completions."""
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}]}


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
    """A local runtime with no key, which is the ordinary case."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "ai_model", "test-model", raising=False)
    monkeypatch.setattr(settings, "ai_base_url", "http://localhost:11434", raising=False)
    yield


# --- The happy path --------------------------------------------------------------


def test_a_valid_judgement_is_returned() -> None:
    evaluator = LocalWritingEvaluator(client=_responds(_body(_valid_payload())))
    result = evaluator.evaluate(REQUEST)

    assert result is not None
    assert result.is_usable
    assert result.provider == "local"
    assert result.dimensions[0].name == "accuracy"


def test_the_prompt_version_travels_with_the_judgement() -> None:
    """The same versioned prompt as the cloud provider, so a judgement can be
    compared across deployments."""
    evaluator = LocalWritingEvaluator(client=_responds(_body(_valid_payload())))
    result = evaluator.evaluate(REQUEST)

    assert result is not None
    assert result.prompt_version != "unknown"


def test_both_providers_read_the_same_prompt() -> None:
    """Not an implementation detail. If the two prompts drifted, the same
    essay would be judged differently depending on where the model runs."""
    local = LocalWritingEvaluator(client=_responds(_body(_valid_payload())))
    cloud_body = {"content": [{"type": "text", "text": json.dumps(_valid_payload())}]}
    cloud = CloudWritingEvaluator(client=_responds(cloud_body))

    from apps.api.app.settings import settings as live

    original = live.ai_api_key
    try:
        live.ai_api_key = "test-key"
        cloud_result = cloud.evaluate(REQUEST)
    finally:
        live.ai_api_key = original
    local_result = local.evaluate(REQUEST)

    assert local_result is not None
    assert cloud_result is not None
    assert local_result.prompt_version == cloud_result.prompt_version


def test_json_wrapped_in_prose_is_still_read() -> None:
    """Small models fence and preface their JSON constantly, so rejecting on
    that alone would throw away most of what a local model produces."""
    wrapped = {
        "choices": [
            {
                "message": {
                    "content": "Sure! Here is the assessment:\n```json\n"
                    + json.dumps(_valid_payload())
                    + "\n```\nHope that helps.",
                }
            }
        ]
    }
    result = LocalWritingEvaluator(client=_responds(wrapped)).evaluate(REQUEST)
    assert result is not None


# --- No key, which is normal here ------------------------------------------------


def test_no_key_is_not_a_failure() -> None:
    """A model on a private network usually has no authentication. Abstaining
    over a missing key — as the cloud provider correctly does — would make
    this provider unusable."""
    evaluator = LocalWritingEvaluator(client=_responds(_body(_valid_payload())))
    assert evaluator.evaluate(REQUEST) is not None


def test_no_authorization_header_is_sent_without_a_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    assert "authorization" not in seen


def test_a_key_is_sent_when_one_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some deployments put a gateway in front of a local model."""
    monkeypatch.setattr(settings, "ai_api_key", "gateway-token", raising=False)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    assert seen["authorization"] == "Bearer gateway-token"


# --- Where the text goes ---------------------------------------------------------


def test_the_request_goes_to_the_configured_local_address() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    assert seen == ["http://localhost:11434/v1/chat/completions"]


def test_the_hosted_default_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """The load-bearing test of this provider. `ai_base_url` defaults to the
    hosted API, and sending a learner's writing there would defeat the single
    reason to run a model yourself."""
    monkeypatch.setattr(settings, "ai_base_url", "https://api.anthropic.com", raising=False)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    assert seen[0].startswith(DEFAULT_BASE_URL)
    assert "anthropic.com" not in seen[0]


def test_a_trailing_slash_does_not_double_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_base_url", "http://gpu-box:8000/", raising=False)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    assert seen == ["http://gpu-box:8000/v1/chat/completions"]


def test_it_waits_longer_than_the_hosted_provider() -> None:
    """A 7B model on a CPU is slow, and the learner already has their
    deterministic feedback on screen while it thinks."""
    from apps.api.app.providers.cloud import TIMEOUT_SECONDS as CLOUD_TIMEOUT

    assert TIMEOUT_SECONDS > CLOUD_TIMEOUT


# --- Judgement, not composition --------------------------------------------------


def test_sampling_is_turned_off() -> None:
    """A rubric score that changes between identical submissions is not a
    measurement. Local runtimes default to sampling, so this is stated."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    assert seen["temperature"] == 0.0


def test_the_learners_text_is_sent_and_nothing_else_is() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_body(_valid_payload()))

    LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST)
    sent = json.loads(seen["messages"][1]["content"])
    assert sent["response_text"] == RESPONSE_TEXT
    assert set(sent) == {"task_prompt", "target_level", "skill_key", "response_text"}


# --- Every way it can go wrong ---------------------------------------------------


def test_a_fabricated_quotation_is_rejected() -> None:
    """More load-bearing here than for the cloud provider, not less: a small
    model invents quotations more often. Schema-valid is not honest."""
    payload = _valid_payload(
        dimensions=[
            {
                "name": "accuracy",
                "score": 0.9,
                "confidence": 0.9,
                "evidence": ["a sentence the learner never wrote"],
            }
        ]
    )
    assert LocalWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None


def test_nothing_listening_on_the_port_is_not_an_error() -> None:
    """The ordinary case: an operator who has not started their model. The
    learner gets deterministic feedback, not a stack trace."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    assert LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST) is None


def test_a_timeout_abstains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    assert LocalWritingEvaluator(client=_client(handler)).evaluate(REQUEST) is None


def test_an_http_error_abstains() -> None:
    evaluator = LocalWritingEvaluator(client=_responds({"error": "no such model"}, status=404))
    assert evaluator.evaluate(REQUEST) is None


def test_a_response_with_no_choices_abstains() -> None:
    assert LocalWritingEvaluator(client=_responds({"choices": []})).evaluate(REQUEST) is None


def test_a_response_with_no_content_abstains() -> None:
    body = {"choices": [{"message": {"role": "assistant"}}]}
    assert LocalWritingEvaluator(client=_responds(body)).evaluate(REQUEST) is None


def test_non_text_content_abstains() -> None:
    """Some runtimes return a list of content parts. Unrecognised is not the
    same as usable."""
    body = {"choices": [{"message": {"content": [{"type": "text", "text": "{}"}]}}]}
    assert LocalWritingEvaluator(client=_responds(body)).evaluate(REQUEST) is None


def test_prose_with_no_json_abstains() -> None:
    body = {"choices": [{"message": {"content": "I think the writing is quite good!"}}]}
    assert LocalWritingEvaluator(client=_responds(body)).evaluate(REQUEST) is None


def test_a_body_that_fails_the_schema_abstains() -> None:
    payload = _valid_payload(dimensions=[{"name": "accuracy", "score": "very good"}])
    assert LocalWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None


def test_a_dimension_with_no_evidence_abstains() -> None:
    """A score with nothing behind it is a guess, whatever produced it.

    Enforced in the schema, so both providers behave the same way. Until
    this test existed the rule was written in a comment and in
    `docs/DECISION_LOG.md` and enforced nowhere: an uncited dimension
    validated cleanly and reached the mastery model.
    """
    payload = _valid_payload(
        dimensions=[{"name": "accuracy", "score": 0.9, "confidence": 0.9, "evidence": []}]
    )
    assert LocalWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST) is None


def test_a_low_confidence_judgement_is_returned_but_not_usable() -> None:
    """Abstention and low confidence are different facts, and the service
    layer needs to be able to tell them apart."""
    payload = _valid_payload(confidence=0.2)
    result = LocalWritingEvaluator(client=_responds(_body(payload))).evaluate(REQUEST)

    assert result is not None
    assert not result.is_usable


# --- Selection -------------------------------------------------------------------


def test_local_mode_now_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "local", raising=False)
    get_writing_evaluator.cache_clear()
    try:
        assert isinstance(get_writing_evaluator(), LocalWritingEvaluator)
    finally:
        get_writing_evaluator.cache_clear()


def test_local_mode_starts_with_no_model_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing must not reach the network. A model that is not up yet is
    the ordinary case, not a reason to refuse to start the API."""
    monkeypatch.setattr(settings, "ai_provider", "local", raising=False)
    monkeypatch.setattr(settings, "ai_base_url", "http://127.0.0.1:1", raising=False)
    get_writing_evaluator.cache_clear()
    try:
        assert get_writing_evaluator() is not None
    finally:
        get_writing_evaluator.cache_clear()


def test_an_unknown_mode_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in configuration is not a degraded capability, and falling back
    silently would hide it."""
    monkeypatch.setattr(settings, "ai_provider", "clould", raising=False)
    get_writing_evaluator.cache_clear()
    try:
        with pytest.raises(ProviderNotAvailableError):
            get_writing_evaluator()
    finally:
        get_writing_evaluator.cache_clear()
