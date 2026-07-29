"""A rubric evaluator backed by somebody else's OpenAI-compatible API.

The mode exists for one reason: using `local` for a hosted service would make
that module's own promise false. `local` says the learner's writing never
leaves the deployment, and `evaluator_id` is stored on every attempt and shown
back to the learner. Stamping "local" on work that was sent to Groq is exactly
the kind of quiet untruth the rest of this product refuses.

So the tests here are mostly about refusing to send anything: no key, no
endpoint, or the shipped default endpoint all abstain, because each of those
means the operator has not actually chosen where a person's writing goes.
"""

from __future__ import annotations

import json

import httpx

from apps.api.app.providers import get_writing_evaluator
from apps.api.app.providers.base import WritingEvaluationRequest
from apps.api.app.providers.compatible import CompatibleWritingEvaluator
from apps.api.app.settings import settings

SAMPLE = (
    "Last weekend I visited my sister in another city. We walked by the river "
    "and talked about her new job, which she started in March."
)

REQUEST = WritingEvaluationRequest(
    task_prompt="Describe something you did recently.",
    target_level="B1",
    skill_key="written_production.everyday_texts",
    response_text=SAMPLE,
)


def _answer(**overrides: object) -> dict:
    body: dict = {
        "dimensions": [
            {
                "name": "task_achievement",
                "score": 0.8,
                "confidence": 0.7,
                "evidence": ["Last weekend I visited my sister"],
            }
        ],
        "priority_feedback": [],
        "confidence": 0.7,
    }
    body.update(overrides)
    return body


def _transport(payload: dict, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        handler.seen = request  # type: ignore[attr-defined]
        return httpx.Response(
            status,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Refusing to send anywhere ----------------------------------------------


def test_it_abstains_without_a_key(monkeypatch) -> None:
    """A public API with no key is a misconfiguration, and sending the
    request anyway would leak the learner's text to an unauthenticated
    endpoint before failing."""
    monkeypatch.setattr(settings, "ai_api_key", "")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.groq.com/openai/v1")

    assert CompatibleWritingEvaluator().evaluate(REQUEST) is None


def test_it_abstains_without_an_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_base_url", "")

    assert CompatibleWritingEvaluator().evaluate(REQUEST) is None


def test_the_shipped_default_endpoint_counts_as_unset(monkeypatch) -> None:
    """`ai_base_url` ships pointing at the hosted Anthropic API, which speaks
    a different protocol and is not what anybody configuring this mode meant.
    Treating it as configured would send a learner's writing somewhere the
    operator did not choose."""
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.anthropic.com")

    assert CompatibleWritingEvaluator().evaluate(REQUEST) is None


def test_it_never_falls_back_to_the_local_default(monkeypatch) -> None:
    """`local` defaults to localhost. Inheriting that here would mean a
    misconfigured hosted mode quietly talked to whatever is listening on the
    operator's own machine."""
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.anthropic.com")

    assert "localhost" not in CompatibleWritingEvaluator()._base_url()


# --- When it is configured --------------------------------------------------


def test_a_usable_judgement_comes_back(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "ai_model", "some-model")

    result = CompatibleWritingEvaluator(_transport(_answer())).evaluate(REQUEST)

    assert result is not None
    assert result.confidence == 0.7


def test_it_sends_the_key_and_hits_the_configured_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "secret-key")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.groq.com/openai/v1")
    client = _transport(_answer())

    CompatibleWritingEvaluator(client).evaluate(REQUEST)

    sent = client._transport.handler.seen  # type: ignore[attr-defined,union-attr]
    assert str(sent.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer secret-key"


def test_invented_quotations_are_still_refused(monkeypatch) -> None:
    """Inherited from the shared provider and worth pinning here: a hosted
    model that quotes text the learner never wrote is judging something
    else."""
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.groq.com/openai/v1")
    answer = _answer(
        dimensions=[
            {
                "name": "task_achievement",
                "score": 0.8,
                "confidence": 0.9,
                "evidence": ["a sentence the learner never wrote"],
            }
        ]
    )

    assert CompatibleWritingEvaluator(_transport(answer)).evaluate(REQUEST) is None


# --- Provenance -------------------------------------------------------------


def test_it_is_not_called_local(monkeypatch) -> None:
    """The whole reason this mode exists. A learner reading their own history
    is entitled to know whether their writing was sent anywhere."""
    assert CompatibleWritingEvaluator.name != "local"
    assert CompatibleWritingEvaluator.name == "compatible"


def test_the_mode_is_selectable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "compatible")
    get_writing_evaluator.cache_clear()
    try:
        assert isinstance(get_writing_evaluator(), CompatibleWritingEvaluator)
    finally:
        get_writing_evaluator.cache_clear()
