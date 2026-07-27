"""Activity endpoints: open a plan item and complete it.

Five activity kinds share these two endpoints. They are modelled as a
discriminated union on `activity_type` rather than as one shape with many
optional fields: a reading task has no word limit and a writing task has no
options, and a response that admits both invites a client to render nonsense.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..curriculum.content import LibraryText
from ..curriculum.listening import ListeningClip
from ..curriculum.speaking import SpeakingTask
from ..curriculum.study import StudyUnit
from ..curriculum.tasks import WritingTask
from ..deps import CurrentUser, SessionDep
from ..learning import taxonomy
from ..models.enums import CefrLevel
from ..services import activities as service

router = APIRouter(prefix="/activities", tags=["activities"])


# --- Opening ----------------------------------------------------------------


class QuestionPrompt(BaseModel):
    key: str
    question_type: str
    prompt: str
    options: list[str]


class ReadingActivity(BaseModel):
    activity_type: Literal["reading_task"] = "reading_task"
    activity_key: str
    title: str
    cefr_level: CefrLevel
    skill_key: str
    estimated_minutes: int
    body: str
    word_count: int
    questions: list[QuestionPrompt]


class StudyItemPrompt(BaseModel):
    key: str
    item_type: str
    feature: str
    #: The learner-facing name of what this item practises.
    feature_label: str
    prompt: str
    #: Empty for gap-fill items, which are typed rather than chosen.
    options: list[str]


class StudyActivity(BaseModel):
    activity_type: Literal["study_task"] = "study_task"
    activity_key: str
    title: str
    cefr_level: CefrLevel
    skill_key: str
    estimated_minutes: int
    explanation: str
    examples: list[str]
    items: list[StudyItemPrompt]


class WritingActivity(BaseModel):
    activity_type: Literal["writing_task"] = "writing_task"
    activity_key: str
    title: str
    cefr_level: CefrLevel
    skill_key: str
    estimated_minutes: int
    genre: str
    prompt: str
    guidance: list[str]
    min_words: int
    max_words: int
    min_sentences: int
    #: Content the task asks the learner to include. Shown, not hidden: this
    #: is a task requirement, not a trick.
    required_elements: list[str]


class ListeningActivity(BaseModel):
    activity_type: Literal["listening_task"] = "listening_task"
    activity_key: str
    title: str
    cefr_level: CefrLevel
    skill_key: str
    estimated_minutes: int
    #: Who is speaking and where. Real listening always has context.
    setting: str
    #: The words of the clip. Sent because the client speaks them, and
    #: because a learner who cannot use audio must still be able to take
    #: part. The UI hides it until asked; revealing it is recorded and costs
    #: the listening evidence.
    transcript: str
    word_count: int
    #: Playback speed for synthesised speech, relative to normal.
    speech_rate: float
    #: A recording to prefer over synthesis, when a deployment has one.
    audio: str | None
    questions: list[QuestionPrompt]


class SpeakingActivity(BaseModel):
    activity_type: Literal["speaking_task"] = "speaking_task"
    activity_key: str
    title: str
    cefr_level: CefrLevel
    skill_key: str
    estimated_minutes: int
    format: str
    prompt: str
    guidance: list[str]
    #: Planning time changes what a speaking task measures, so it is part of
    #: the task rather than a UI choice.
    preparation_seconds: int
    min_seconds: int
    max_seconds: int
    min_words: int
    required_elements: list[str]


ActivityResponse = Annotated[
    ReadingActivity | StudyActivity | WritingActivity | ListeningActivity | SpeakingActivity,
    Field(discriminator="activity_type"),
]


# --- Completing -------------------------------------------------------------


class CompleteActivityRequest(BaseModel):
    """One request shape, validated against the activity's kind server-side.

    Kept as a single model with optional fields rather than a union so a
    mismatch produces a domain error naming the field it wanted, instead of a
    generic union-discrimination failure the client cannot act on.
    """

    model_config = ConfigDict(extra="forbid")

    #: Reading and study: question or item key to the learner's answer.
    answers: dict[str, str] | None = None
    #: Writing: the composed response.
    text: str | None = None
    #: Study: how many item explanations the learner revealed before
    #: answering. Self-reported, and reduces the weight of the evidence.
    hints_used: int = Field(default=0, ge=0)
    #: Listening: how many times the clip was played.
    plays: int = Field(default=1, ge=0)
    #: Listening: whether the transcript was read before answering. When
    #: true no listening evidence is recorded at all.
    used_transcript: bool = False
    #: Speaking: how long the learner actually spoke for.
    spoken_seconds: int = Field(default=0, ge=0)
    #: Speaking: the recogniser's own confidence. Stored for audit, never
    #: scored — see `curriculum/speaking.py`.
    recognition_confidence: float | None = Field(default=None, ge=0, le=1)
    #: Speaking: whether the learner typed instead of speaking. When true no
    #: speaking evidence is recorded at all.
    typed_instead: bool = False
    duration_ms: int | None = Field(default=None, ge=0)


class QuestionOutcome(BaseModel):
    key: str
    question_type: str
    correct: bool
    expected: str = Field(description="Revealed only after submission.")


class ReadingOutcome(BaseModel):
    activity_type: Literal["reading_task"] = "reading_task"
    activity_key: str
    score: float
    correct_count: int
    total: int
    explanation: str
    results: list[QuestionOutcome]
    evidence_recorded: bool


class StudyItemOutcome(BaseModel):
    key: str
    feature: str
    feature_label: str
    correct: bool
    expected: str = Field(description="Revealed only after submission.")
    note: str


class StudyOutcome(BaseModel):
    activity_type: Literal["study_task"] = "study_task"
    activity_key: str
    score: float
    correct_count: int
    total: int
    explanation: str
    results: list[StudyItemOutcome]
    evidence_recorded: bool
    #: How much this counted as unaided recall. Below 1.0 because the
    #: explanation was on screen; surfaced so the learner can see why a
    #: perfect study score does not settle a skill on its own.
    independence: float
    #: Features now being tracked as errors because they went wrong here.
    logged_features: list[str]


class WritingCheckOutcome(BaseModel):
    code: str
    passed: bool
    message: str


class RubricDimensionOutcome(BaseModel):
    name: str
    score: float
    confidence: float
    #: Short quotations from the learner's own text. An evaluator that cannot
    #: cite evidence is guessing, so this travels with the score.
    evidence: list[str]


class PriorityFeedbackOutcome(BaseModel):
    category: str
    original: str
    improved: str
    explanation: str


class WritingOutcome(BaseModel):
    activity_type: Literal["writing_task"] = "writing_task"
    activity_key: str
    score: float
    explanation: str
    checks: list[WritingCheckOutcome]
    word_count: int
    sentence_count: int
    lexical_variety: float
    connectives_used: list[str]
    missing_elements: list[str]
    evidence_recorded: bool
    #: True while no rubric evaluator has judged accuracy. The client must
    #: show this: claiming a piece of writing is fine when only its length was
    #: checked is the dishonesty `docs/AI_TUTOR_BEHAVIOR.md` forbids.
    provisional: bool
    #: Empty unless a rubric actually ran and was trusted.
    rubric: list[RubricDimensionOutcome] = []
    #: At most three. Correcting everything teaches nothing.
    priority_feedback: list[PriorityFeedbackOutcome] = []
    #: Which evaluator judged this, or None. Surfaced so a learner can tell
    #: machine judgement from a countable check.
    evaluated_by: str | None = None


class ListeningOutcome(BaseModel):
    activity_type: Literal["listening_task"] = "listening_task"
    activity_key: str
    score: float
    correct_count: int
    total: int
    explanation: str
    results: list[QuestionOutcome]
    evidence_recorded: bool
    plays: int
    #: Lower when the clip took many passes. Surfaced so the learner can see
    #: that needing six replays is not the same as catching it in two.
    independence: float
    #: True when the transcript was read before answering, in which case
    #: nothing was recorded as listening evidence.
    used_transcript: bool


class SpeakingOutcome(BaseModel):
    activity_type: Literal["speaking_task"] = "speaking_task"
    activity_key: str
    score: float
    explanation: str
    checks: list[WritingCheckOutcome]
    word_count: int
    spoken_seconds: int
    #: What the browser heard. Shown so the learner can judge for themselves
    #: whether the recogniser got them right.
    transcript: str
    #: Displayed, never scored.
    recognition_confidence: float | None
    evidence_recorded: bool
    typed_instead: bool
    #: Always true: nothing here judged delivery. Clients must surface it.
    provisional: bool


CompleteActivityResponse = Annotated[
    ReadingOutcome | StudyOutcome | WritingOutcome | ListeningOutcome | SpeakingOutcome,
    Field(discriminator="activity_type"),
]


# --- Endpoints --------------------------------------------------------------


@router.get("/{activity_key:path}", response_model=ActivityResponse)
def read_activity(activity_key: str, user: CurrentUser, session: SessionDep) -> ActivityResponse:
    """Open an activity. Answers are never included."""
    del user, session
    activity = service.get_activity(activity_key)

    if isinstance(activity, LibraryText):
        prompt = activity.as_prompt()
        return ReadingActivity(
            activity_key=activity_key,
            title=activity.title,
            cefr_level=activity.cefr_level,
            skill_key=activity.skill_key,
            estimated_minutes=activity.minutes,
            body=activity.body,
            word_count=activity.word_count,
            questions=[QuestionPrompt(**question) for question in prompt["questions"]],
        )

    if isinstance(activity, StudyUnit):
        return StudyActivity(
            activity_key=activity_key,
            title=activity.title,
            cefr_level=activity.cefr_level,
            skill_key=activity.skill_key,
            estimated_minutes=activity.minutes,
            explanation=activity.explanation,
            examples=list(activity.examples),
            items=[
                StudyItemPrompt(
                    key=item.key,
                    item_type=item.item_type,
                    feature=item.feature,
                    feature_label=taxonomy.label_for(item.feature),
                    prompt=item.prompt,
                    options=list(item.options),
                )
                for item in activity.items
            ],
        )

    if isinstance(activity, ListeningClip):
        prompt = activity.as_prompt()
        return ListeningActivity(
            activity_key=activity_key,
            title=activity.title,
            cefr_level=activity.cefr_level,
            skill_key=activity.skill_key,
            estimated_minutes=activity.minutes,
            setting=activity.setting,
            transcript=activity.transcript,
            word_count=activity.word_count,
            speech_rate=activity.speech_rate,
            audio=activity.audio,
            questions=[QuestionPrompt(**question) for question in prompt["questions"]],
        )

    if isinstance(activity, SpeakingTask):
        return SpeakingActivity(
            activity_key=activity_key,
            title=activity.title,
            cefr_level=activity.cefr_level,
            skill_key=activity.skill_key,
            estimated_minutes=activity.minutes,
            format=activity.speaking_format,
            prompt=activity.prompt,
            guidance=list(activity.guidance),
            preparation_seconds=activity.preparation_seconds,
            min_seconds=activity.min_seconds,
            max_seconds=activity.max_seconds,
            min_words=activity.requirements.min_words,
            required_elements=list(activity.requirements.required_elements),
        )

    task: WritingTask = activity
    return WritingActivity(
        activity_key=activity_key,
        title=task.title,
        cefr_level=task.cefr_level,
        skill_key=task.skill_key,
        estimated_minutes=task.minutes,
        genre=task.genre,
        prompt=task.prompt,
        guidance=list(task.guidance),
        min_words=task.requirements.min_words,
        max_words=task.requirements.max_words,
        min_sentences=task.requirements.min_sentences,
        required_elements=list(task.requirements.required_elements),
    )


@router.post("/{activity_key:path}/complete", response_model=CompleteActivityResponse)
def complete_activity(
    activity_key: str,
    payload: CompleteActivityRequest,
    user: CurrentUser,
    session: SessionDep,
) -> CompleteActivityResponse:
    result = service.complete(
        session,
        user.id,
        activity_key=activity_key,
        answers=payload.answers,
        text=payload.text,
        hints_used=payload.hints_used,
        plays=payload.plays,
        spoken_seconds=payload.spoken_seconds,
        recognition_confidence=payload.recognition_confidence,
        typed_instead=payload.typed_instead,
        used_transcript=payload.used_transcript,
        duration_ms=payload.duration_ms,
    )
    session.commit()

    if isinstance(result, service.ActivityResult):
        return ReadingOutcome(
            activity_key=result.activity_key,
            score=result.score,
            correct_count=result.correct_count,
            total=len(result.results),
            explanation=result.explanation,
            results=[
                QuestionOutcome(
                    key=item.key,
                    question_type=item.question_type,
                    correct=item.correct,
                    expected=item.expected,
                )
                for item in result.results
            ],
            evidence_recorded=result.evidence_recorded,
        )

    if isinstance(result, service.StudyResult):
        return StudyOutcome(
            activity_key=result.activity_key,
            score=result.score,
            correct_count=result.correct_count,
            total=len(result.results),
            explanation=result.explanation,
            results=[
                StudyItemOutcome(
                    key=item.key,
                    feature=item.feature,
                    feature_label=taxonomy.label_for(item.feature),
                    correct=item.correct,
                    expected=item.expected,
                    note=item.note,
                )
                for item in result.results
            ],
            evidence_recorded=result.evidence_recorded,
            independence=result.independence,
            logged_features=list(result.logged_features),
        )

    if isinstance(result, service.SpeakingResult):
        return SpeakingOutcome(
            activity_key=result.activity_key,
            score=result.score,
            explanation=result.explanation,
            checks=[
                WritingCheckOutcome(code=c.code, passed=c.passed, message=c.message)
                for c in result.analysis.checks
            ],
            word_count=result.analysis.word_count,
            spoken_seconds=result.spoken_seconds,
            transcript=result.transcript,
            recognition_confidence=result.recognition_confidence,
            evidence_recorded=result.evidence_recorded,
            typed_instead=result.typed_instead,
            provisional=result.provisional,
        )

    if isinstance(result, service.ListeningResult):
        return ListeningOutcome(
            activity_key=result.activity_key,
            score=result.score,
            correct_count=result.correct_count,
            total=len(result.results),
            explanation=result.explanation,
            results=[
                QuestionOutcome(
                    key=item.key,
                    question_type=item.question_type,
                    correct=item.correct,
                    expected=item.expected,
                )
                for item in result.results
            ],
            evidence_recorded=result.evidence_recorded,
            plays=result.plays,
            independence=result.independence,
            used_transcript=result.used_transcript,
        )

    analysis = result.analysis
    evaluation = result.evaluation
    judged = result.judged
    return WritingOutcome(
        activity_key=result.activity_key,
        score=result.score,
        explanation=result.explanation,
        checks=[
            WritingCheckOutcome(code=check.code, passed=check.passed, message=check.message)
            for check in analysis.checks
        ],
        word_count=analysis.word_count,
        sentence_count=analysis.sentence_count,
        lexical_variety=analysis.lexical_variety,
        connectives_used=list(analysis.connectives_used),
        missing_elements=list(analysis.missing_elements),
        evidence_recorded=result.evidence_recorded,
        provisional=result.provisional,
        rubric=[
            RubricDimensionOutcome(
                name=dimension.name,
                score=dimension.score,
                confidence=dimension.confidence,
                evidence=list(dimension.evidence),
            )
            for dimension in (evaluation.dimensions if judged and evaluation else [])
        ],
        priority_feedback=[
            PriorityFeedbackOutcome(
                category=item.category,
                original=item.original,
                improved=item.improved,
                explanation=item.explanation,
            )
            for item in (evaluation.priority_feedback if judged and evaluation else [])
        ],
        evaluated_by=evaluation.provider if judged and evaluation else None,
    )
