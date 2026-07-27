"""Evaluator provider contract.

AI evaluation is an *accelerator*, never a dependency: `docs/PRODUCT_SPEC.md`
requires the core learning loop to work with no provider configured. Every
consumer therefore treats a `None` result as normal, not as an error.

The output shape mirrors `packages/contracts/schemas/writing-evaluation.schema.json`
and the prompt in `prompts/evaluators/writing.md`. Validation happens here, at
the boundary, so a malformed model response can never reach the mastery model.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

#: An evaluation below this confidence is not allowed to produce evidence.
#: `CLAUDE.md`: AI feedback must not update mastery without rubric evidence and
#: confidence thresholds.
MIN_USABLE_CONFIDENCE = 0.6


class RubricDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    #: Short quotations from the learner's own text. An evaluator that cannot
    #: cite evidence is guessing.
    evidence: list[str] = Field(default_factory=list)


class PriorityFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    original: str
    improved: str
    explanation: str


class WritingEvaluation(BaseModel):
    """A schema-valid rubric evaluation, or an abstention."""

    model_config = ConfigDict(extra="forbid")

    dimensions: list[RubricDimension] = Field(default_factory=list)
    #: At most three, per `docs/LEARNING_SCIENCE.md`: correcting everything
    #: teaches nothing.
    priority_feedback: list[PriorityFeedback] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1)
    abstain_reason: str | None = None

    provider: str = "unknown"
    model: str | None = None
    prompt_version: str | None = None

    @property
    def abstained(self) -> bool:
        return self.abstain_reason is not None or not self.dimensions

    @property
    def is_usable(self) -> bool:
        """Whether this evaluation may contribute evidence at all."""
        return not self.abstained and self.confidence >= MIN_USABLE_CONFIDENCE

    @property
    def overall_score(self) -> float:
        """Confidence-weighted mean across dimensions."""
        weighted = sum(d.score * d.confidence for d in self.dimensions)
        total = sum(d.confidence for d in self.dimensions)
        return round(weighted / total, 4) if total > 0 else 0.0


class WritingEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_prompt: str
    response_text: str
    target_level: str
    skill_key: str


@runtime_checkable
class WritingEvaluator(Protocol):
    """Evaluates a written response against a rubric.

    Implementations must never raise for an ordinary failure (timeout, quota,
    malformed output). They return `None`, and the learner still gets their
    deterministic feedback.
    """

    name: str

    def evaluate(self, request: WritingEvaluationRequest) -> WritingEvaluation | None: ...
