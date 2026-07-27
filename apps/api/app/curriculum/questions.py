"""Comprehension questions, shared by every receptive activity.

A gist question about a text and a gist question about a recording are the
same object asking the same thing about a different stimulus. Keeping one
definition means the reading lab and the listening lab cannot drift apart in
what they accept, what they validate, or what they withhold from the client.

Validation is strict on purpose: a question whose answer is not among its
options teaches the learner that the system is unreliable, which costs more
than the question was worth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: What a question is testing. Mirrors `docs/SKILL_MATRIX.md` section 5.
#:
#: ``gist``      — the overall message. Always required: a meaning-focused
#:                 activity that never asks what it was about is a quiz.
#: ``detail``    — a specific stated fact.
#: ``inference`` — something the stimulus implies but never states.
QUESTION_TYPES = frozenset({"gist", "detail", "inference"})


@dataclass(frozen=True)
class Question:
    key: str
    question_type: str
    prompt: str
    options: tuple[str, ...]
    answer: str

    def as_prompt(self) -> dict[str, Any]:
        """Client-safe view. Deliberately excludes `answer`."""
        return {
            "key": self.key,
            "question_type": self.question_type,
            "prompt": self.prompt,
            "options": list(self.options),
        }


def parse_question(raw: Any, position: int, where: str, errors: list[str]) -> Question | None:
    """Parse one question, appending to `errors` rather than raising.

    Returning `None` and collecting the problem lets a caller report every
    fault in a file at once, which is what makes fixing content a single pass
    instead of a guessing game.
    """
    if not isinstance(raw, dict):
        errors.append(f"{where} question {position} is not a mapping")
        return None

    key = raw.get("key")
    if not isinstance(key, str) or not key:
        errors.append(f"{where} question {position} has no key")
        return None

    question_type = str(raw.get("type", "")).strip()
    if question_type not in QUESTION_TYPES:
        errors.append(f"{where}/{key} has unknown question type {question_type!r}")
        return None

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{where}/{key} has no prompt")
        return None

    raw_options = raw.get("options")
    if not isinstance(raw_options, list) or len(raw_options) < 2:
        errors.append(f"{where}/{key} needs at least two options")
        return None
    options = tuple(str(option) for option in raw_options)
    if len(set(options)) != len(options):
        errors.append(f"{where}/{key} has duplicate options")
        return None

    answer = raw.get("answer")
    if not isinstance(answer, str) or answer not in options:
        errors.append(f"{where}/{key} has an answer that is not among its options")
        return None

    return Question(
        key=key,
        question_type=question_type,
        prompt=" ".join(prompt.split()),
        options=options,
        answer=answer,
    )


def parse_questions(
    raw_questions: Any,
    where: str,
    errors: list[str],
    *,
    require_gist: bool = True,
) -> tuple[Question, ...] | None:
    """Parse a stimulus's whole question list.

    `require_gist` enforces the meaning-first rule: an activity a learner is
    asked to understand should ask what it was about before it asks for
    details out of it.
    """
    if not isinstance(raw_questions, list) or not raw_questions:
        errors.append(f"{where} has no questions")
        return None

    questions: list[Question] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_questions):
        question = parse_question(raw, position, where, errors)
        if question is None:
            continue
        if question.key in seen:
            errors.append(f"{where} has duplicate question key {question.key}")
            continue
        seen.add(question.key)
        questions.append(question)

    if not questions:
        return None

    if require_gist and not any(q.question_type == "gist" for q in questions):
        errors.append(f"{where} has no gist question")
        return None

    return tuple(questions)


__all__ = ["QUESTION_TYPES", "Question", "parse_question", "parse_questions"]
