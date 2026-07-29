"""A rubric evaluator backed by a model the operator runs themselves.

Same job as `cloud.py`, one difference that matters: a learner's writing
never leaves the deployment. Ollama, llama.cpp's server, vLLM, LM Studio and
most other self-hosted runtimes speak the OpenAI chat-completions shape, so
this targets that rather than any one product.

Everything else is deliberately identical to the cloud provider, and shares
its code where sharing is honest — the same versioned prompt, the same
schema, the same balanced-brace JSON scan, the same refusal to accept a
judgement whose quotations do not appear in the learner's text. Two rubric
providers that disagreed about what counts as a usable judgement would make
the mastery model's numbers incomparable between deployments.

Three differences follow from being self-hosted, and each is a decision
rather than an oversight.

**No key is required.** A local runtime on a private network usually has no
authentication at all, so an absent key is normal here and abstaining over
it would make the provider unusable. `ai_api_key` is still sent when set,
because some gateways in front of a local model do want one.

**The timeout is longer.** A 7B model on a CPU is slow, and the learner
already has their deterministic feedback on screen while it thinks. Waiting
is not blocking them.

**A small model is expected to fail more often**, and every one of those
failures already degrades to `None`. That is not a compromise made for this
provider; it is the same rule `docs/PRODUCT_SPEC.md` applies to all of them.
The abstention rate is worth watching, and the honest position is that a
weak local model judging nothing is better than a weak local model judging
badly.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from ..settings import settings
from .base import WritingEvaluation, WritingEvaluationRequest
from .cloud import (
    MAX_RESPONSE_BYTES,
    _extract_json,
    _prompt,
    _quotes_are_real,
)

#: Longer than the cloud provider's 20s. Self-hosted models run on whatever
#: hardware the operator has, and the learner is not waiting on this: the
#: deterministic checks are already on screen.
TIMEOUT_SECONDS = 120.0

#: Where an OpenAI-compatible runtime listens. Ollama's default; vLLM and
#: LM Studio use the same path on a different port.
DEFAULT_BASE_URL = "http://localhost:11434"


class LocalWritingEvaluator:
    """Calls a self-hosted, OpenAI-compatible model. Abstains on anything."""

    name = "local"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injectable so tests exercise the real parsing and validation path
        # against a stub transport rather than mocking the class away.
        self._client = client

    def build_payload(self, request: WritingEvaluationRequest) -> dict[str, Any]:
        """The exact request this provider sends.

        Public so `scripts/ai_smoke.py` can replay it verbatim when
        diagnosing an abstention. A diagnostic that rebuilt the payload by
        hand would drift from this one and eventually explain a request
        nobody makes.
        """
        prompt, _ = _prompt()
        return {
            "model": settings.ai_model,
            # Judgement, not composition: a rubric score that changes between
            # identical submissions is not a measurement. Local runtimes
            # default to sampling, so this is stated rather than assumed.
            "temperature": 0.0,
            "max_tokens": settings.ai_max_output_tokens,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task_prompt": request.task_prompt,
                            "target_level": request.target_level,
                            "skill_key": request.skill_key,
                            "response_text": request.response_text,
                        }
                    ),
                },
            ],
        }

    def evaluate(self, request: WritingEvaluationRequest) -> WritingEvaluation | None:
        _, prompt_version = _prompt()
        payload = self.build_payload(request)

        try:
            body = self._post(payload)
        except (httpx.HTTPError, OSError):
            # Includes the ordinary case of nothing listening on the port.
            # An operator who has not started their model gets deterministic
            # feedback, not an error on a learner's submission.
            return None

        evaluation = self._parse(body, prompt_version)
        if evaluation is None:
            return None

        # A small model invents quotations more often than a large one, which
        # makes this check more load-bearing here, not less.
        if not _quotes_are_real(evaluation, request.response_text):
            return None

        return evaluation

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        # Optional on purpose: a local runtime usually has no auth, but a
        # gateway in front of one might.
        if settings.ai_api_key:
            headers["authorization"] = f"Bearer {settings.ai_api_key}"

        client = self._client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            response = client.post(
                f"{self._base_url()}/v1/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise httpx.HTTPError("response too large")
            result: dict[str, Any] = response.json()
            return result
        finally:
            if self._client is None:
                client.close()

    def _base_url(self) -> str:
        """Where to find the model.

        `ai_base_url` defaults to the hosted API, which would be exactly the
        wrong place to send a learner's text when the point of this provider
        is that it does not leave the machine. So the default is only used
        when the operator has actually changed it.
        """
        configured = settings.ai_base_url.rstrip("/")
        if not configured or "api.anthropic.com" in configured:
            return DEFAULT_BASE_URL
        return configured

    def _parse(self, body: dict[str, Any], prompt_version: str) -> WritingEvaluation | None:
        """Turn a chat-completions response into a validated evaluation.

        Forgiving about where the JSON is, unforgiving about what it says —
        the same split the cloud provider makes, and for the same reason.
        Small models wrap JSON in prose and fences constantly.
        """
        try:
            choices = body.get("choices") or []
            first = choices[0] if choices else {}
            message = first.get("message") or {}
            text = message.get("content") or ""
        except (AttributeError, IndexError, TypeError):
            return None

        if not isinstance(text, str):
            return None

        raw = _extract_json(text)
        if raw is None:
            return None

        try:
            return WritingEvaluation.model_validate(
                {**raw, "provider": self.name, "prompt_version": prompt_version}
            )
        except ValidationError:
            return None


__all__ = ["DEFAULT_BASE_URL", "TIMEOUT_SECONDS", "LocalWritingEvaluator"]
