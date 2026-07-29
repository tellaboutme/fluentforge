"""A rubric evaluator backed by a third-party OpenAI-compatible API.

This exists because using `local` for a hosted service would make that
module's own promise false. `local.py` says a learner's writing never leaves
the deployment, and `evaluator_id` is recorded on every attempt and returned
by `GET /attempts/{id}/feedback` -- so pointing `local` at Groq, Together or
OpenRouter would stamp "local" on work that was sent to somebody else's
server. The provenance a learner can read has to be true.

Mechanically this is the same request: nearly every hosted inference provider
speaks the OpenAI chat-completions shape, which is why one mode covers all of
them rather than one module per vendor.

Two things it insists on that `local` does not, and both follow from the text
leaving the building.

**A base URL must be set explicitly.** No default. `ai_base_url` ships
pointing at the hosted Anthropic API, and a mode that quietly fell back to
*any* default would risk sending a learner's writing somewhere the operator
did not choose. An unset base URL abstains.

**A key must be set.** A local runtime on a private network legitimately has
no authentication; a public API without a key is a misconfiguration, and
sending the request anyway would leak the learner's text to an unauthenticated
endpoint before failing.
"""

from __future__ import annotations

from ..settings import settings
from .base import WritingEvaluation, WritingEvaluationRequest
from .local import LocalWritingEvaluator


class CompatibleWritingEvaluator(LocalWritingEvaluator):
    """Calls a hosted OpenAI-compatible API. Abstains on anything."""

    #: Recorded on every attempt this judges. Distinct from `local` because a
    #: learner reading their own history is entitled to know whether their
    #: writing was sent anywhere.
    name = "compatible"

    def evaluate(self, request: WritingEvaluationRequest) -> WritingEvaluation | None:
        if not settings.ai_api_key:
            return None
        if not self._configured_base_url():
            return None
        return super().evaluate(request)

    def _base_url(self) -> str:
        # Never the local default, and never the shipped Anthropic one. The
        # caller has already checked this is set; the fallback is here only
        # so the type is honest.
        return self._configured_base_url() or ""

    @staticmethod
    def _configured_base_url() -> str | None:
        """The operator's endpoint, or `None` if they have not chosen one.

        The shipped default is treated as unset. It points at the hosted
        Anthropic API, which speaks a different protocol and is not what
        anybody configuring this mode meant.
        """
        configured = settings.ai_base_url.rstrip("/")
        if not configured or "api.anthropic.com" in configured:
            return None
        # Every provider documents its endpoint with the `/v1` on the end,
        # and the request path adds one. Without this, the value an operator
        # copies straight out of Groq's or Together's docs produces
        # `/v1/v1/chat/completions` and a 404 that looks like a broken key.
        if configured.endswith("/v1"):
            configured = configured[: -len("/v1")]
        return configured


__all__ = ["CompatibleWritingEvaluator"]
