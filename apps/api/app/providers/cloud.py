"""A rubric evaluator backed by a hosted model.

This is the first provider that actually judges writing. Everything about it
is built around one rule from `docs/PRODUCT_SPEC.md`: AI is an accelerator,
never a dependency. So every failure mode — no key, timeout, quota, a
malformed body, a model that ignored the schema, a model that invented
evidence — degrades to `None`, and the learner gets exactly the deterministic
feedback they would have had.

The prompt is read from `prompts/evaluators/writing.md` rather than embedded
here. `CLAUDE.md` treats prompts as versioned product logic: the version in
that file's front matter travels onto every evidence event, so a later change
of prompt is visible in the history rather than silently reinterpreting past
judgements.

One check goes beyond schema validation. A dimension is required to cite
evidence, and the citation is verified to actually appear in the learner's
text. A model that fabricates a quotation is not making a judgement about
this piece of writing, and `docs/AI_TUTOR_BEHAVIOR.md` does not allow that to
reach the mastery model.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from ..settings import settings
from .base import WritingEvaluation, WritingEvaluationRequest

#: Where the versioned prompt lives, relative to the repository root.
PROMPT_PATH = Path("prompts") / "evaluators" / "writing.md"

#: A model that takes longer than this is not worth a learner waiting for.
#: They already have their deterministic feedback on screen.
TIMEOUT_SECONDS = 20.0

#: Guards against a runaway response being parsed at all.
MAX_RESPONSE_BYTES = 200_000

_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_VERSION = re.compile(r"^version:\s*(\S+)\s*$", re.MULTILINE)


@lru_cache(maxsize=1)
def _prompt() -> tuple[str, str]:
    """The evaluator prompt and its declared version.

    Cached: the file is versioned source, so re-reading it per request would
    buy nothing and cost a syscall on every submission.
    """
    path = Path(settings.curriculum_dir).parent / PROMPT_PATH
    text = path.read_text(encoding="utf-8")

    version = "unknown"
    match = _FRONT_MATTER.match(text)
    if match:
        found = _VERSION.search(match.group(1))
        if found:
            version = found.group(1)
        text = text[match.end() :]

    return text.strip(), version


def _quotes_are_real(evaluation: WritingEvaluation, response_text: str) -> bool:
    """Whether every cited quotation actually appears in the learner's text.

    Compared on collapsed whitespace so a model that reflows a line is not
    punished for formatting. Case-insensitive for the same reason.
    """
    haystack = " ".join(response_text.split()).casefold()
    for dimension in evaluation.dimensions:
        for quote in dimension.evidence:
            needle = " ".join(quote.split()).casefold()
            if needle and needle not in haystack:
                return False
    return True


class CloudWritingEvaluator:
    """Calls a hosted model, and abstains on anything at all going wrong."""

    name = "cloud"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injectable so tests exercise the real parsing and validation path
        # against a stub transport rather than mocking this class away.
        self._client = client

    def evaluate(self, request: WritingEvaluationRequest) -> WritingEvaluation | None:
        api_key = settings.ai_api_key
        if not api_key:
            # Configured as `cloud` but never given a key. Abstaining is the
            # honest response: the alternative is a stack trace on a learner's
            # submission.
            return None

        prompt, prompt_version = _prompt()
        payload = {
            "model": settings.ai_model,
            "max_tokens": 1500,
            "system": prompt,
            "messages": [
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
                }
            ],
        }

        try:
            body = self._post(api_key, payload)
        except (httpx.HTTPError, OSError):
            return None

        evaluation = self._parse(body, prompt_version)
        if evaluation is None:
            return None

        # Schema-valid but fabricated is still fabricated.
        if not _quotes_are_real(evaluation, request.response_text):
            return None

        return evaluation

    def _post(self, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        client = self._client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            response = client.post(
                f"{settings.ai_base_url}/v1/messages", json=payload, headers=headers
            )
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise httpx.HTTPError("response too large")
            result: dict[str, Any] = response.json()
            return result
        finally:
            if self._client is None:
                client.close()

    def _parse(self, body: dict[str, Any], prompt_version: str) -> WritingEvaluation | None:
        """Turn a model response into a validated evaluation, or nothing.

        Deliberately forgiving about *where* the JSON is and unforgiving about
        *what it says*: models wrap JSON in prose or fences often enough that
        rejecting on that alone would waste usable judgements, but a body that
        does not satisfy the schema is discarded without negotiation.
        """
        try:
            blocks = body.get("content") or []
            text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
        except AttributeError:
            return None

        raw = _extract_json(text)
        if raw is None:
            return None

        try:
            evaluation = WritingEvaluation.model_validate(
                {**raw, "provider": self.name, "prompt_version": prompt_version}
            )
        except ValidationError:
            return None

        return evaluation


def _extract_json(text: str) -> dict[str, Any] | None:
    """The first JSON object in a string, or None.

    Scans for a balanced object rather than regex-matching braces, because a
    quoted brace inside the learner's own text would break the naive version.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


__all__ = ["MAX_RESPONSE_BYTES", "TIMEOUT_SECONDS", "CloudWritingEvaluator"]
