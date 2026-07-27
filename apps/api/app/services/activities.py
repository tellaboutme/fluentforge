"""Activities: opening a plan item and completing it.

This is what closes the loop. A plan that says "read something at your level"
but cannot be opened is a promise the product does not keep, so every activity
kind a plan can contain must resolve to something a learner can start.

Four kinds exist, covering every non-review slot in the session templates:

- ``read:``  a library text with comprehension questions. Receptive.
- ``study:`` one point explained, then practice on that point. Scaffolded:
             the explanation stays visible, so the evidence is recorded at
             reduced independence.
- ``write:`` a written output task, checked on countable properties only and
             recorded at reduced *evaluator confidence*.
- ``listen:`` a spoken clip with comprehension questions. Receptive, and
             the transcript stays hidden unless the learner asks for it.

Activities are derived from versioned source rather than stored as rows. That
keeps them immutable and reviewable in the same way the curriculum is; a
persisted `activities` table arrives when generation and imports do.

All four grade deterministically. `docs/PRODUCT_SPEC.md` requires the core
learning loop to work with AI disabled, and it does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.content import LibraryText, parse_library
from ..curriculum.listening import ListeningClip, parse_listening
from ..curriculum.loader import active_curriculum_version
from ..curriculum.study import StudyUnit, parse_study_units
from ..curriculum.tasks import WritingTask, parse_writing_tasks
from ..db.types import utcnow
from ..errors import ActivityNotFoundError, ActivityPayloadError, CurriculumNotLoadedError
from ..learning import taxonomy
from ..learning.writing import (
    DETERMINISTIC_CONFIDENCE,
    WritingAnalysis,
    analyse,
    summarise,
)
from ..models.curriculum import SkillNode
from ..models.enums import EvidenceType, SessionStatus
from ..models.learning import Attempt, LearningSession
from ..providers import (
    WritingEvaluation,
    WritingEvaluationRequest,
    WritingEvaluator,
    get_writing_evaluator,
)
from ..settings import settings
from .errors_log import record_error, sync_error_cards
from .evidence import recompute_skill_state, record_evidence

# --- Activity types, as they appear on the wire -----------------------------

READING_TYPE = "reading_task"
STUDY_TYPE = "study_task"
WRITING_TYPE = "writing_task"
LISTENING_TYPE = "listening_task"

#: Kept for callers written against the single-kind version of this module.
ACTIVITY_TYPE = READING_TYPE

READ_PREFIX = "read:"
STUDY_PREFIX = "study:"
WRITE_PREFIX = "write:"
LISTEN_PREFIX = "listen:"

READING_CONTEXT = "reading_lab"
STUDY_CONTEXT = "study_lab"
WRITING_CONTEXT = "writing_lab"
LISTENING_CONTEXT = "listening_lab"

EVALUATOR_ID = "deterministic/0.1.0"

# --- What each kind evidences -----------------------------------------------

#: Reading comprehension is receptive: it evidences understanding, not
#: production, whatever the learner scores.
READING_EVIDENCE = EvidenceType.COMPREHENSION

#: Study practice is retrieval, but guided retrieval: the rule is on screen.
STUDY_EVIDENCE = EvidenceType.CONTROLLED_RECALL

#: The learner composed the text themselves, so it is production — the
#: uncertainty is in the *grading*, and lives in evaluator confidence.
WRITING_EVIDENCE = EvidenceType.CONTEXTUAL_PRODUCTION

#: Listening evidences understanding by ear. Same evidence type as reading,
#: recorded against a listening skill, so the two never merge into one
#: undifferentiated "comprehension" number.
LISTENING_EVIDENCE = EvidenceType.COMPREHENSION

#: Replays a learner may take before the evidence weakens. Catching a clip
#: in two passes is stronger evidence than needing six, but replaying is a
#: normal part of listening and must not be punished as though it were
#: cheating.
FREE_PLAYS = 2
REPLAY_PENALTY = 0.1
MIN_LISTENING_INDEPENDENCE = 0.4

#: Independence for study practice with the explanation visible. Below 1.0
#: because `docs/LEARNING_SCIENCE.md` is explicit that a correct answer with
#: the rule in front of you is weaker evidence than unaided recall.
STUDY_INDEPENDENCE = 0.65

#: How much each revealed hint costs on top of that, and the floor it stops at.
#: A learner who revealed everything still produced *something*, so this never
#: reaches zero.
HINT_PENALTY = 0.15
MIN_INDEPENDENCE = 0.25

#: Evaluator confidence is capped before it reaches the mastery model. A model
#: that reports 0.95 has not earned the same trust as a closed item scored
#: against a known answer, and `docs/AI_TUTOR_BEHAVIOR.md` is explicit that AI
#: judgement is an accelerator rather than an authority.
MAX_RUBRIC_CONFIDENCE = 0.85

#: A study unit below this score means the point did not land. Above it, the
#: learner has it and the misses are worth naming individually.
STUDY_UNDERSTOOD = 0.6


# --- Loading versioned source -----------------------------------------------


@lru_cache(maxsize=4)
def _load_library(curriculum_dir: str) -> tuple[LibraryText, ...]:
    return parse_library(Path(curriculum_dir))


@lru_cache(maxsize=4)
def _load_study(curriculum_dir: str) -> tuple[StudyUnit, ...]:
    return parse_study_units(Path(curriculum_dir))


@lru_cache(maxsize=4)
def _load_tasks(curriculum_dir: str) -> tuple[WritingTask, ...]:
    return parse_writing_tasks(Path(curriculum_dir))


@lru_cache(maxsize=4)
def _load_listening(curriculum_dir: str) -> tuple[ListeningClip, ...]:
    return parse_listening(Path(curriculum_dir))


def library() -> tuple[LibraryText, ...]:
    return _load_library(str(settings.curriculum_dir))


def study_units() -> tuple[StudyUnit, ...]:
    return _load_study(str(settings.curriculum_dir))


def writing_tasks() -> tuple[WritingTask, ...]:
    return _load_tasks(str(settings.curriculum_dir))


def listening_clips() -> tuple[ListeningClip, ...]:
    return _load_listening(str(settings.curriculum_dir))


def library_by_key() -> dict[str, LibraryText]:
    return {text.key: text for text in library()}


def study_by_key() -> dict[str, StudyUnit]:
    return {unit.key: unit for unit in study_units()}


def tasks_by_key() -> dict[str, WritingTask]:
    return {task.key: task for task in writing_tasks()}


def listening_by_key() -> dict[str, ListeningClip]:
    return {clip.key: clip for clip in listening_clips()}


# --- Selection --------------------------------------------------------------


def texts_for_skill(skill_key: str) -> tuple[LibraryText, ...]:
    return tuple(text for text in library() if text.skill_key == skill_key)


def study_for_skill(skill_key: str) -> tuple[StudyUnit, ...]:
    return tuple(unit for unit in study_units() if unit.skill_key == skill_key)


def tasks_for_skill(skill_key: str) -> tuple[WritingTask, ...]:
    return tuple(task for task in writing_tasks() if task.skill_key == skill_key)


def clips_for_skill(skill_key: str) -> tuple[ListeningClip, ...]:
    return tuple(clip for clip in listening_clips() if clip.skill_key == skill_key)


def study_for_feature(feature_code: str) -> tuple[StudyUnit, ...]:
    """Units that practise a named linguistic feature.

    This is what turns a recurring error into something openable: the error
    log names a feature, and a study unit that drills that feature is a real
    answer to it rather than a reminder that the learner keeps getting it
    wrong.
    """
    return tuple(unit for unit in study_units() if unit.covers(feature_code))


def activity_key_for(text: LibraryText) -> str:
    """The stable key a plan item uses to point at this reading activity."""
    return f"{READ_PREFIX}{text.key}"


def study_key_for(unit: StudyUnit) -> str:
    return f"{STUDY_PREFIX}{unit.key}"


def writing_key_for(task: WritingTask) -> str:
    return f"{WRITE_PREFIX}{task.key}"


def listening_key_for(clip: ListeningClip) -> str:
    return f"{LISTEN_PREFIX}{clip.key}"


def activity_type_for(activity_key: str) -> str | None:
    """The wire type for a key, or None if nothing can open it."""
    if activity_key.startswith(READ_PREFIX):
        return READING_TYPE
    if activity_key.startswith(STUDY_PREFIX):
        return STUDY_TYPE
    if activity_key.startswith(WRITE_PREFIX):
        return WRITING_TYPE
    if activity_key.startswith(LISTEN_PREFIX):
        return LISTENING_TYPE
    return None


# --- Resolution -------------------------------------------------------------


def get_reading(activity_key: str) -> LibraryText:
    if not activity_key.startswith(READ_PREFIX):
        raise ActivityNotFoundError(activity_key)
    text = library_by_key().get(activity_key.removeprefix(READ_PREFIX))
    if text is None:
        raise ActivityNotFoundError(activity_key)
    return text


def get_study(activity_key: str) -> StudyUnit:
    if not activity_key.startswith(STUDY_PREFIX):
        raise ActivityNotFoundError(activity_key)
    unit = study_by_key().get(activity_key.removeprefix(STUDY_PREFIX))
    if unit is None:
        raise ActivityNotFoundError(activity_key)
    return unit


def get_writing(activity_key: str) -> WritingTask:
    if not activity_key.startswith(WRITE_PREFIX):
        raise ActivityNotFoundError(activity_key)
    task = tasks_by_key().get(activity_key.removeprefix(WRITE_PREFIX))
    if task is None:
        raise ActivityNotFoundError(activity_key)
    return task


def get_listening(activity_key: str) -> ListeningClip:
    if not activity_key.startswith(LISTEN_PREFIX):
        raise ActivityNotFoundError(activity_key)
    clip = listening_by_key().get(activity_key.removeprefix(LISTEN_PREFIX))
    if clip is None:
        raise ActivityNotFoundError(activity_key)
    return clip


def get_activity(activity_key: str) -> LibraryText | StudyUnit | WritingTask | ListeningClip:
    """Resolve a plan item's activity key to something openable."""
    kind = activity_type_for(activity_key)
    if kind == READING_TYPE:
        return get_reading(activity_key)
    if kind == STUDY_TYPE:
        return get_study(activity_key)
    if kind == WRITING_TYPE:
        return get_writing(activity_key)
    if kind == LISTENING_TYPE:
        return get_listening(activity_key)
    raise ActivityNotFoundError(activity_key)


def is_openable(activity_key: str) -> bool:
    """Whether this key resolves. Used by the planner to break ties."""
    try:
        get_activity(activity_key)
    except ActivityNotFoundError:
        return False
    return True


# --- Results ----------------------------------------------------------------


@dataclass(frozen=True)
class QuestionResult:
    key: str
    question_type: str
    correct: bool
    chosen: str
    expected: str


@dataclass(frozen=True)
class ActivityResult:
    activity_key: str
    score: float
    results: tuple[QuestionResult, ...]
    evidence_recorded: bool

    @property
    def correct_count(self) -> int:
        return sum(1 for result in self.results if result.correct)

    @property
    def explanation(self) -> str:
        """Learner-facing framing. Comprehension, not a mark out of ten."""
        total = len(self.results)
        if self.correct_count == total:
            return "You followed the whole text."
        gist = [r for r in self.results if r.question_type == "gist"]
        if gist and all(r.correct for r in gist):
            return (
                "You got the main idea. Some details were missed — that is "
                "normal, and worth another look."
            )
        return "The main idea did not quite come through. Try reading it once more."


@dataclass(frozen=True)
class StudyItemResult:
    key: str
    item_type: str
    feature: str
    correct: bool
    chosen: str
    expected: str
    #: The unit's own explanation of this item, shown right or wrong.
    note: str


@dataclass(frozen=True)
class StudyResult:
    activity_key: str
    score: float
    results: tuple[StudyItemResult, ...]
    evidence_recorded: bool
    independence: float
    #: Features that went wrong and are now logged as errors.
    logged_features: tuple[str, ...]

    @property
    def correct_count(self) -> int:
        return sum(1 for result in self.results if result.correct)

    @property
    def explanation(self) -> str:
        total = len(self.results)
        if self.correct_count == total:
            return "All correct. This point looks solid — a spaced review will confirm it."
        if self.score >= STUDY_UNDERSTOOD:
            missed = {taxonomy.label_for(r.feature) for r in self.results if not r.correct}
            return f"Mostly there. Worth another look at: {', '.join(sorted(missed))}."
        return (
            "This point has not settled yet. Read the explanation again — "
            "the notes below say what each answer turned on."
        )


@dataclass(frozen=True)
class ListeningResult:
    activity_key: str
    score: float
    results: tuple[QuestionResult, ...]
    evidence_recorded: bool
    plays: int
    independence: float
    #: Whether the learner read the transcript before answering.
    used_transcript: bool

    @property
    def correct_count(self) -> int:
        return sum(1 for result in self.results if result.correct)

    @property
    def explanation(self) -> str:
        """Learner-facing framing. Understanding by ear, not a mark."""
        if self.used_transcript:
            return (
                "You read the transcript, so this tells us about your reading "
                "rather than your listening. That is a fine way to work "
                "through a clip \u2014 it just cannot count as listening evidence."
            )
        total = len(self.results)
        if self.correct_count == total:
            if self.plays <= FREE_PLAYS:
                return "You caught all of it, and quickly."
            return "You caught all of it. It took a few passes, which is normal."
        gist = [r for r in self.results if r.question_type == "gist"]
        if gist and all(r.correct for r in gist):
            return (
                "You followed the overall message. Some details slipped past "
                "\u2014 that is the usual shape of listening, and it improves."
            )
        return "The main idea did not quite land. Listen once more before reading the transcript."


@dataclass(frozen=True)
class WritingResult:
    activity_key: str
    score: float
    analysis: WritingAnalysis
    evidence_recorded: bool
    #: A schema-valid rubric evaluation, or None when no evaluator was
    #: configured, it abstained, or it failed.
    evaluation: WritingEvaluation | None = None

    @property
    def judged(self) -> bool:
        """Whether anything actually assessed accuracy."""
        return self.evaluation is not None and self.evaluation.is_usable

    @property
    def provisional(self) -> bool:
        """True while nothing has judged accuracy.

        The day an evaluator runs, this becomes a real answer rather than a
        constant somebody forgot to revisit.
        """
        return not self.judged

    @property
    def explanation(self) -> str:
        if self.judged:
            return (
                "Checked for length, structure and content, and assessed for "
                "accuracy and range against a rubric."
            )
        return summarise(self.analysis)


# --- Completion: reading ----------------------------------------------------


def complete_reading(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    answers: dict[str, str],
    duration_ms: int | None = None,
) -> ActivityResult:
    """Score a completed reading task and record the evidence."""
    text = get_reading(activity_key)

    results = tuple(
        QuestionResult(
            key=question.key,
            question_type=question.question_type,
            correct=answers.get(question.key) == question.answer,
            chosen=answers.get(question.key, ""),
            expected=question.answer,
        )
        for question in text.questions
    )
    score = round(sum(1 for r in results if r.correct) / len(results), 4) if results else 0.0

    learning_session = _open_session(session, user_id, READING_CONTEXT)
    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=activity_key,
        activity_type=READING_TYPE,
        attempt_number=_next_attempt_number(session, user_id, activity_key),
        response={
            "answers": dict(answers),
            "score": score,
            "correct": score >= 0.5,
            "results": [
                {"key": r.key, "type": r.question_type, "correct": r.correct} for r in results
            ],
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id=EVALUATOR_ID,
    )
    session.add(attempt)
    session.flush()

    node = _skill_node(session, text.skill_key)
    recorded = False
    if node is not None:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=READING_EVIDENCE,
            score=score,
            difficulty=_difficulty_for(text.cefr_level.rank),
            confidence=1.0,
            independence=1.0,
            novelty=1.0,
            # The text is the context: reading three different texts is
            # broader evidence than answering three questions about one.
            context_key=f"text:{text.key}",
            metadata={"source": READING_CONTEXT, "question_count": len(text.questions)},
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    session.flush()
    return ActivityResult(
        activity_key=activity_key,
        score=score,
        results=results,
        evidence_recorded=recorded,
    )


# --- Completion: study ------------------------------------------------------


def complete_study(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    answers: dict[str, str],
    hints_used: int = 0,
    duration_ms: int | None = None,
) -> StudyResult:
    """Score a completed study unit, record evidence, and log what went wrong.

    Two things happen that reading does not do. Evidence is recorded at
    reduced independence, because the explanation was on screen. And each
    wrong item is logged against the *feature* it exercised, so a mistake
    becomes a named, practisable pattern rather than a lost point.
    """
    unit = get_study(activity_key)

    results = tuple(
        StudyItemResult(
            key=item.key,
            item_type=item.item_type,
            feature=item.feature,
            correct=item.matches(answers.get(item.key, "")),
            chosen=answers.get(item.key, ""),
            expected=item.answer,
            note=item.note,
        )
        for item in unit.items
    )
    score = round(sum(1 for r in results if r.correct) / len(results), 4) if results else 0.0

    # Hints are self-reported by the client. That is a real limitation, and it
    # is why hints reduce independence rather than invalidating the evidence:
    # the worst a miscount can do is mis-weight one observation.
    independence = round(
        max(MIN_INDEPENDENCE, STUDY_INDEPENDENCE - HINT_PENALTY * max(0, hints_used)),
        4,
    )

    learning_session = _open_session(session, user_id, STUDY_CONTEXT)
    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=activity_key,
        activity_type=STUDY_TYPE,
        attempt_number=_next_attempt_number(session, user_id, activity_key),
        response={
            "answers": dict(answers),
            "score": score,
            "correct": score >= STUDY_UNDERSTOOD,
            "results": [
                {
                    "key": r.key,
                    "type": r.item_type,
                    "feature": r.feature,
                    "correct": r.correct,
                }
                for r in results
            ],
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=max(0, hints_used),
        scaffolding_level=round(1.0 - independence, 4),
        evaluator_id=EVALUATOR_ID,
    )
    session.add(attempt)
    session.flush()

    logged = _log_study_errors(session, user_id, results)

    node = _skill_node(session, unit.skill_key)
    recorded = False
    if node is not None:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=STUDY_EVIDENCE,
            score=score,
            difficulty=_difficulty_for(unit.cefr_level.rank),
            confidence=1.0,
            independence=independence,
            novelty=1.0,
            # The unit is the context. Answering five items about one point is
            # one context, not five, whatever the item count.
            context_key=f"study:{unit.key}",
            metadata={
                "source": STUDY_CONTEXT,
                "item_count": len(unit.items),
                "hints_used": max(0, hints_used),
                "features": list(unit.features),
            },
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    session.flush()
    return StudyResult(
        activity_key=activity_key,
        score=score,
        results=results,
        evidence_recorded=recorded,
        independence=independence,
        logged_features=logged,
    )


def _log_study_errors(
    session: Session,
    user_id: uuid.UUID,
    results: tuple[StudyItemResult, ...],
) -> tuple[str, ...]:
    """Record one error per *feature* that went wrong, not per item.

    Two wrong items on the same feature in one sitting are one observation of
    that weakness, not two. Counting them separately would let a single unit
    push a feature past the recurrence threshold on its own, which is exactly
    the "recent repeated attempts cannot prove generalised mastery" invariant
    read backwards.
    """
    failed: list[str] = []
    for result in results:
        if not result.correct and result.feature not in failed:
            failed.append(result.feature)

    for feature in failed:
        record_error(
            session,
            user_id,
            taxonomy_code=feature,
            description=taxonomy.describe(feature),
            example=next(
                (r.chosen for r in results if r.feature == feature and not r.correct and r.chosen),
                None,
            ),
            blocks_meaning=taxonomy.blocks_meaning_default(feature),
        )
    if failed:
        sync_error_cards(session, user_id)
    return tuple(failed)


# --- Completion: listening --------------------------------------------------


def listening_independence(plays: int) -> float:
    """How unaided the comprehension was, given how many passes it took.

    Replaying is a normal part of listening, not cheating, so the first
    `FREE_PLAYS` cost nothing and the value never falls below a floor. What it
    does capture is that catching a clip in two passes is stronger evidence
    than needing six.
    """
    extra = max(0, plays - FREE_PLAYS)
    return round(max(MIN_LISTENING_INDEPENDENCE, 1.0 - REPLAY_PENALTY * extra), 4)


def complete_listening(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    answers: dict[str, str],
    plays: int = 1,
    used_transcript: bool = False,
    duration_ms: int | None = None,
) -> ListeningResult:
    """Score a completed listening task and record the evidence.

    The rule that matters: if the learner read the transcript before
    answering, **no listening evidence is recorded at all**. Reading a
    transcript is a legitimate and necessary way to work \u2014 it is the only way
    for a learner who cannot use audio \u2014 but it does not demonstrate
    understanding by ear, and the profile must not claim that it did. The
    attempt is still kept, and the learner is told plainly why it did not
    count.
    """
    clip = get_listening(activity_key)

    results = tuple(
        QuestionResult(
            key=question.key,
            question_type=question.question_type,
            correct=answers.get(question.key) == question.answer,
            chosen=answers.get(question.key, ""),
            expected=question.answer,
        )
        for question in clip.questions
    )
    score = round(sum(1 for r in results if r.correct) / len(results), 4) if results else 0.0
    plays = max(0, plays)
    independence = listening_independence(plays)

    learning_session = _open_session(session, user_id, LISTENING_CONTEXT)
    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=activity_key,
        activity_type=LISTENING_TYPE,
        attempt_number=_next_attempt_number(session, user_id, activity_key),
        response={
            "answers": dict(answers),
            "score": score,
            "correct": score >= 0.5,
            "plays": plays,
            "used_transcript": used_transcript,
            "results": [
                {"key": r.key, "type": r.question_type, "correct": r.correct} for r in results
            ],
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=1 if used_transcript else 0,
        scaffolding_level=1.0 if used_transcript else round(1.0 - independence, 4),
        evaluator_id=EVALUATOR_ID,
    )
    session.add(attempt)
    session.flush()

    node = _skill_node(session, clip.skill_key)
    recorded = False
    if node is not None and not used_transcript:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=LISTENING_EVIDENCE,
            score=score,
            difficulty=_difficulty_for(clip.cefr_level.rank),
            confidence=1.0,
            independence=independence,
            novelty=1.0,
            # The clip is the context, exactly as a text is for reading.
            context_key=f"clip:{clip.key}",
            metadata={
                "source": LISTENING_CONTEXT,
                "question_count": len(clip.questions),
                "plays": plays,
                # Synthetic speech under-represents the connected speech that
                # makes real listening hard. Recorded so a later audit can
                # tell which evidence was gathered this way.
                "synthesised": clip.is_synthesised,
            },
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    session.flush()
    return ListeningResult(
        activity_key=activity_key,
        score=score,
        results=results,
        evidence_recorded=recorded,
        plays=plays,
        independence=independence,
        used_transcript=used_transcript,
    )


# --- Completion: writing ----------------------------------------------------


def complete_writing(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    text: str,
    duration_ms: int | None = None,
    evaluator: WritingEvaluator | None = None,
) -> WritingResult:
    """Check a written response against countable requirements.

    Evidence is recorded at `DETERMINISTIC_CONFIDENCE`, not 1.0: the learner
    demonstrably produced connected language, but nothing here judged whether
    it was accurate. A response too short to be evidence records none at all
    rather than recording a bad score — "not enough to say" and "said badly"
    are different claims.

    When a rubric evaluator is configured and returns a usable judgement, it
    adds a **second** evidence event rather than replacing the first. The two
    say different things — one that language was produced, one about its
    quality — and overwriting would lose the distinction. Both share a context
    key, so judging one piece of writing never counts as two contexts.

    The evaluator is never allowed to break a submission. `docs/PRODUCT_SPEC.md`
    makes AI an accelerator, so a timeout, a quota error, or a malformed
    response all degrade to exactly what the learner would have got anyway.
    """
    task = get_writing(activity_key)
    analysis = analyse(text, task.requirements)

    learning_session = _open_session(session, user_id, WRITING_CONTEXT)
    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=activity_key,
        activity_type=WRITING_TYPE,
        attempt_number=_next_attempt_number(session, user_id, activity_key),
        response={
            "text": text,
            "score": analysis.score,
            "correct": analysis.met_minimum,
            "word_count": analysis.word_count,
            "sentence_count": analysis.sentence_count,
            "lexical_variety": analysis.lexical_variety,
            "connectives_used": list(analysis.connectives_used),
            "missing_elements": list(analysis.missing_elements),
            "checks": [
                {"code": c.code, "passed": c.passed, "message": c.message} for c in analysis.checks
            ],
            "provisional": True,
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id=EVALUATOR_ID,
    )
    session.add(attempt)
    session.flush()

    node = _skill_node(session, task.skill_key)
    recorded = False
    if node is not None and analysis.met_minimum:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=WRITING_EVIDENCE,
            score=analysis.score,
            difficulty=_difficulty_for(task.cefr_level.rank),
            # The honest number. Countable checks cannot judge writing.
            confidence=DETERMINISTIC_CONFIDENCE,
            independence=1.0,
            novelty=1.0,
            context_key=f"task:{task.key}",
            metadata={
                "source": WRITING_CONTEXT,
                "genre": task.genre,
                "provisional": True,
                "word_count": analysis.word_count,
                "unjudged_features": list(task.target_features),
            },
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    evaluation = _evaluate_writing(task, text, evaluator) if analysis.met_minimum else None
    if evaluation is not None and evaluation.is_usable and node is not None:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=WRITING_EVIDENCE,
            score=evaluation.overall_score,
            difficulty=_difficulty_for(task.cefr_level.rank),
            # Capped: a model reporting high confidence has not earned the
            # trust of a closed item scored against a known answer.
            confidence=min(evaluation.confidence, MAX_RUBRIC_CONFIDENCE),
            independence=1.0,
            novelty=1.0,
            # Same context as the deterministic event on purpose: this is one
            # piece of writing judged twice, not two pieces of evidence.
            context_key=f"task:{task.key}",
            metadata={
                "source": WRITING_CONTEXT,
                "rubric": True,
                "provider": evaluation.provider,
                "model": evaluation.model,
                "prompt_version": evaluation.prompt_version,
                "dimensions": {d.name: d.score for d in evaluation.dimensions},
            },
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    session.flush()
    return WritingResult(
        activity_key=activity_key,
        score=analysis.score,
        analysis=analysis,
        evidence_recorded=recorded,
        evaluation=evaluation,
    )


def _evaluate_writing(
    task: WritingTask,
    text: str,
    evaluator: WritingEvaluator | None,
) -> WritingEvaluation | None:
    """Ask the configured evaluator for a rubric judgement.

    Total by construction. The protocol says implementations return `None`
    rather than raising, but a provider is third-party code reached over a
    network, so the contract is enforced here rather than trusted. A learner's
    submission must never be lost to somebody else's exception.
    """
    chosen = evaluator or get_writing_evaluator()
    request = WritingEvaluationRequest(
        task_prompt=task.prompt,
        response_text=text,
        target_level=task.cefr_level.value,
        skill_key=task.skill_key,
    )
    try:
        return chosen.evaluate(request)
    except Exception:  # noqa: BLE001 - deliberately total; see docstring
        return None


# --- Dispatch ---------------------------------------------------------------


def complete(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    answers: dict[str, str] | None = None,
    text: str | None = None,
    hints_used: int = 0,
    plays: int = 1,
    used_transcript: bool = False,
    duration_ms: int | None = None,
) -> ActivityResult | StudyResult | WritingResult | ListeningResult:
    """Complete any activity, validating that the payload suits its kind."""
    kind = activity_type_for(activity_key)

    if kind == READING_TYPE:
        if answers is None:
            raise ActivityPayloadError(activity_key, "answers")
        return complete_reading(
            session,
            user_id,
            activity_key=activity_key,
            answers=answers,
            duration_ms=duration_ms,
        )

    if kind == STUDY_TYPE:
        if answers is None:
            raise ActivityPayloadError(activity_key, "answers")
        return complete_study(
            session,
            user_id,
            activity_key=activity_key,
            answers=answers,
            hints_used=hints_used,
            duration_ms=duration_ms,
        )

    if kind == LISTENING_TYPE:
        if answers is None:
            raise ActivityPayloadError(activity_key, "answers")
        return complete_listening(
            session,
            user_id,
            activity_key=activity_key,
            answers=answers,
            plays=plays,
            used_transcript=used_transcript,
            duration_ms=duration_ms,
        )

    if kind == WRITING_TYPE:
        if text is None:
            raise ActivityPayloadError(activity_key, "text")
        return complete_writing(
            session,
            user_id,
            activity_key=activity_key,
            text=text,
            duration_ms=duration_ms,
        )

    raise ActivityNotFoundError(activity_key)


# --- Shared plumbing --------------------------------------------------------


def _difficulty_for(level_rank: int) -> float:
    """Map a CEFR rank onto the 0..1 difficulty the mastery model expects."""
    return round((level_rank + 0.5) / 6, 4)


def _skill_node(session: Session, skill_key: str) -> SkillNode | None:
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()
    return session.execute(
        select(SkillNode).where(
            SkillNode.curriculum_version_id == version.id,
            SkillNode.key == skill_key,
        )
    ).scalar_one_or_none()


def _open_session(session: Session, user_id: uuid.UUID, kind: str) -> LearningSession:
    """Reuse an open session of this kind, or start one."""
    existing = session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.IN_PROGRESS,
        )
        .order_by(LearningSession.started_at.desc())
    ).scalars()
    for candidate in existing:
        if candidate.context.get("kind") == kind:
            return candidate

    learning_session = LearningSession(
        user_id=user_id,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": kind},
    )
    session.add(learning_session)
    session.flush()
    return learning_session


def _next_attempt_number(session: Session, user_id: uuid.UUID, activity_key: str) -> int:
    previous = session.execute(
        select(Attempt.id).where(Attempt.user_id == user_id, Attempt.activity_key == activity_key)
    ).scalars()
    return len(list(previous)) + 1


__all__ = [
    "ACTIVITY_TYPE",
    "LISTENING_TYPE",
    "READING_TYPE",
    "STUDY_TYPE",
    "WRITING_TYPE",
    "ActivityResult",
    "ListeningResult",
    "QuestionResult",
    "StudyItemResult",
    "StudyResult",
    "WritingResult",
    "activity_key_for",
    "activity_type_for",
    "clips_for_skill",
    "complete",
    "complete_listening",
    "complete_reading",
    "complete_study",
    "complete_writing",
    "get_activity",
    "get_listening",
    "get_reading",
    "get_study",
    "get_writing",
    "is_openable",
    "library",
    "listening_by_key",
    "listening_clips",
    "listening_independence",
    "listening_key_for",
    "study_for_feature",
    "study_for_skill",
    "study_key_for",
    "study_units",
    "tasks_for_skill",
    "texts_for_skill",
    "writing_key_for",
    "writing_tasks",
]
