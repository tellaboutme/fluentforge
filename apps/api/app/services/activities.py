"""Activities: opening a plan item and completing it.

This is what closes the loop. A plan that says "read something at your level"
but cannot be opened is a promise the product does not keep, so every activity
kind a plan can contain must resolve to something a learner can start.

Six kinds exist, covering every non-review slot in the session templates:

- ``read:``  a library text with comprehension questions. Receptive.
- ``study:`` one point explained, then practice on that point. Scaffolded:
             the explanation stays visible, so the evidence is recorded at
             reduced independence.
- ``write:`` a written output task, checked on countable properties only and
             recorded at reduced *evaluator confidence*.
- ``listen:`` a spoken clip with comprehension questions. Receptive, and
             the transcript stays hidden unless the learner asks for it.
- ``speak:`` a spoken output task. The browser transcribes; the transcript
             evidences speaking and never pronunciation.
- ``mediate:`` several sources in, one account out, for a reader who has not
             seen them. The advanced kind: it adds two checks nothing else
             makes -- was every source drawn on, and was it restated rather
             than transcribed.

Activities are derived from versioned source rather than stored as rows. That
keeps them immutable and reviewable in the same way the curriculum is; a
persisted `activities` table arrives when generation and imports do.

All six grade deterministically. `docs/PRODUCT_SPEC.md` requires the core
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
from ..curriculum.mediation import MediationTask, parse_mediation_tasks
from ..curriculum.speaking import SpeakingTask, parse_speaking_tasks
from ..curriculum.study import StudyUnit, parse_study_units
from ..curriculum.tasks import WritingTask, parse_writing_tasks
from ..db.types import utcnow
from ..errors import ActivityNotFoundError, ActivityPayloadError, CurriculumNotLoadedError
from ..learning import taxonomy
from ..learning.mediation import (
    DETERMINISTIC_CONFIDENCE as MEDIATION_CONFIDENCE,
)
from ..learning.mediation import (
    MediationAnalysis,
    analyse_mediation,
)
from ..learning.mediation import (
    summarise as summarise_mediation,
)
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
from .sessions import SITTING_KIND

# --- Activity types, as they appear on the wire -----------------------------

READING_TYPE = "reading_task"
STUDY_TYPE = "study_task"
WRITING_TYPE = "writing_task"
LISTENING_TYPE = "listening_task"
SPEAKING_TYPE = "speaking_task"
MEDIATION_TYPE = "mediation_task"

#: Kept for callers written against the single-kind version of this module.
ACTIVITY_TYPE = READING_TYPE

READ_PREFIX = "read:"
STUDY_PREFIX = "study:"
WRITE_PREFIX = "write:"
LISTEN_PREFIX = "listen:"
SPEAK_PREFIX = "speak:"
MEDIATE_PREFIX = "mediate:"

READING_CONTEXT = "reading_lab"
STUDY_CONTEXT = "study_lab"
WRITING_CONTEXT = "writing_lab"
LISTENING_CONTEXT = "listening_lab"
SPEAKING_CONTEXT = "speaking_lab"
MEDIATION_CONTEXT = "mediation_lab"

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

#: Speech evidences production, like writing. The learner composed and
#: delivered it; what is uncertain is the record, not the act.
SPEAKING_EVIDENCE = EvidenceType.CONTEXTUAL_PRODUCTION

#: Mediation is production too, and specifically production *from* material
#: the learner had to take in first. `EvidenceType.TRANSFER` is reserved for
#: applying a skill in an unfamiliar setting, which is a different claim.
MEDIATION_EVIDENCE = EvidenceType.CONTEXTUAL_PRODUCTION

#: Lower than writing's 0.45 because a transcript is a *lossy* record: the
#: recogniser may have misheard, dropped, or silently corrected what was
#: said. Countable checks on writing at least see exactly what was written.
TRANSCRIPT_CONFIDENCE = 0.35

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


@lru_cache(maxsize=4)
def _load_speaking(curriculum_dir: str) -> tuple[SpeakingTask, ...]:
    return parse_speaking_tasks(Path(curriculum_dir))


@lru_cache(maxsize=4)
def _load_mediation(curriculum_dir: str) -> tuple[MediationTask, ...]:
    return parse_mediation_tasks(Path(curriculum_dir))


def library() -> tuple[LibraryText, ...]:
    return _load_library(str(settings.curriculum_dir))


def study_units() -> tuple[StudyUnit, ...]:
    return _load_study(str(settings.curriculum_dir))


def writing_tasks() -> tuple[WritingTask, ...]:
    return _load_tasks(str(settings.curriculum_dir))


def listening_clips() -> tuple[ListeningClip, ...]:
    return _load_listening(str(settings.curriculum_dir))


def speaking_tasks() -> tuple[SpeakingTask, ...]:
    return _load_speaking(str(settings.curriculum_dir))


def mediation_tasks() -> tuple[MediationTask, ...]:
    return _load_mediation(str(settings.curriculum_dir))


def library_by_key() -> dict[str, LibraryText]:
    return {text.key: text for text in library()}


def study_by_key() -> dict[str, StudyUnit]:
    return {unit.key: unit for unit in study_units()}


def tasks_by_key() -> dict[str, WritingTask]:
    return {task.key: task for task in writing_tasks()}


def listening_by_key() -> dict[str, ListeningClip]:
    return {clip.key: clip for clip in listening_clips()}


def speaking_by_key() -> dict[str, SpeakingTask]:
    return {task.key: task for task in speaking_tasks()}


def mediation_by_key() -> dict[str, MediationTask]:
    return {task.key: task for task in mediation_tasks()}


# --- Selection --------------------------------------------------------------


def texts_for_skill(skill_key: str) -> tuple[LibraryText, ...]:
    return tuple(text for text in library() if text.skill_key == skill_key)


def study_for_skill(skill_key: str) -> tuple[StudyUnit, ...]:
    return tuple(unit for unit in study_units() if unit.skill_key == skill_key)


def tasks_for_skill(skill_key: str) -> tuple[WritingTask, ...]:
    return tuple(task for task in writing_tasks() if task.skill_key == skill_key)


def clips_for_skill(skill_key: str) -> tuple[ListeningClip, ...]:
    return tuple(clip for clip in listening_clips() if clip.skill_key == skill_key)


def speaking_for_skill(skill_key: str) -> tuple[SpeakingTask, ...]:
    return tuple(task for task in speaking_tasks() if task.skill_key == skill_key)


def mediation_for_skill(skill_key: str) -> tuple[MediationTask, ...]:
    return tuple(task for task in mediation_tasks() if task.skill_key == skill_key)


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


def speaking_key_for(task: SpeakingTask) -> str:
    return f"{SPEAK_PREFIX}{task.key}"


def mediation_key_for(task: MediationTask) -> str:
    return f"{MEDIATE_PREFIX}{task.key}"


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
    if activity_key.startswith(SPEAK_PREFIX):
        return SPEAKING_TYPE
    if activity_key.startswith(MEDIATE_PREFIX):
        return MEDIATION_TYPE
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


def get_speaking(activity_key: str) -> SpeakingTask:
    if not activity_key.startswith(SPEAK_PREFIX):
        raise ActivityNotFoundError(activity_key)
    task = speaking_by_key().get(activity_key.removeprefix(SPEAK_PREFIX))
    if task is None:
        raise ActivityNotFoundError(activity_key)
    return task


def get_mediation(activity_key: str) -> MediationTask:
    if not activity_key.startswith(MEDIATE_PREFIX):
        raise ActivityNotFoundError(activity_key)
    task = mediation_by_key().get(activity_key.removeprefix(MEDIATE_PREFIX))
    if task is None:
        raise ActivityNotFoundError(activity_key)
    return task


def get_activity(
    activity_key: str,
) -> LibraryText | StudyUnit | WritingTask | ListeningClip | SpeakingTask | MediationTask:
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
    if kind == SPEAKING_TYPE:
        return get_speaking(activity_key)
    if kind == MEDIATION_TYPE:
        return get_mediation(activity_key)
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
class _Remedy:
    """Something openable that answers a recurring error.

    Deliberately not a `StudyUnit`: the answer to a comprehension error is a
    text or a clip, and a return type that could only be a study unit is what
    kept reading and listening errors unanswerable.
    """

    activity_key: str
    activity_type: str
    title: str
    minutes: int
    #: The curriculum skill this activity evidences. The planner needs it to
    #: place the candidate against a skill node rather than against a
    #: taxonomy code, which names a feature and not a skill.
    skill_key: str


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
class SpeakingResult:
    activity_key: str
    score: float
    analysis: WritingAnalysis
    evidence_recorded: bool
    spoken_seconds: int
    #: What the browser heard. Returned so the learner can see it and judge
    #: for themselves whether the recogniser got them right.
    transcript: str
    #: The recogniser's own confidence, stored and displayed but never
    #: scored. See `curriculum/speaking.py` for why.
    recognition_confidence: float | None
    #: True when the learner typed instead of speaking.
    typed_instead: bool

    @property
    def provisional(self) -> bool:
        """Always true. Nothing here judged delivery, only the transcript."""
        return True

    @property
    def explanation(self) -> str:
        if self.typed_instead:
            return (
                "You typed this rather than saying it, so it tells us about "
                "your writing, not your speaking. That is a perfectly good "
                "way to do the task \u2014 it just cannot count as speaking."
            )
        if not self.analysis.met_minimum:
            return (
                "That was too short to tell us much. Try again and keep "
                "going a little longer than feels comfortable."
            )
        return (
            "These are automatic checks on length and content, made from what "
            "the browser heard. Nothing here has judged your pronunciation."
        )


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


@dataclass(frozen=True)
class MediationResult:
    activity_key: str
    score: float
    analysis: MediationAnalysis
    evidence_recorded: bool
    #: A schema-valid rubric evaluation, or None when no evaluator was
    #: configured, it abstained, or it failed.
    evaluation: WritingEvaluation | None = None

    @property
    def judged(self) -> bool:
        return self.evaluation is not None and self.evaluation.is_usable

    @property
    def provisional(self) -> bool:
        """True while nothing has judged whether the sources were conveyed
        faithfully -- which is the whole point of the task, and the one thing
        a countable check cannot reach."""
        return not self.judged

    @property
    def explanation(self) -> str:
        if self.judged:
            return (
                "Checked for length, structure, source coverage and restating, "
                "and assessed against a rubric."
            )
        return summarise_mediation(self.analysis)


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

    _log_comprehension_errors(
        session, user_id, results, domain="reading", source=f"the text '{text.title}'"
    )

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

    if not used_transcript:
        # A learner who read the transcript answered a reading task. Logging
        # a listening error there would name the wrong skill, and the error
        # log would fill with listening patterns from work done by eye.
        _log_comprehension_errors(
            session, user_id, results, domain="listening", source=f"the clip '{clip.title}'"
        )

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


# --- Completion: speaking ---------------------------------------------------


def complete_speaking(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    transcript: str,
    spoken_seconds: int = 0,
    recognition_confidence: float | None = None,
    typed_instead: bool = False,
    duration_ms: int | None = None,
) -> SpeakingResult:
    """Score a spoken task from its transcript.

    Three rules, each of them a refusal:

    **No pronunciation claim.** Evidence lands on the task's speaking skill
    and never on a `pronunciation.*` skill. The curriculum parser already
    refuses a task that aims at one; this is the same rule at the other end.

    **Recognition confidence is never scored.** It is recorded for audit and
    shown to the learner, because a recogniser is measurably worse on
    accented speech and penalising that would be discrimination rather than
    assessment.

    **Typing is not speaking.** The fallback exists so a learner without a
    microphone, or with a browser that cannot listen, can still do the task.
    It records no speaking evidence, exactly as reading a listening
    transcript records no listening evidence.
    """
    task = get_speaking(activity_key)
    analysis = analyse(transcript, task.requirements)
    spoken_seconds = max(0, spoken_seconds)

    learning_session = _open_session(session, user_id, SPEAKING_CONTEXT)
    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=activity_key,
        activity_type=SPEAKING_TYPE,
        attempt_number=_next_attempt_number(session, user_id, activity_key),
        response={
            "transcript": transcript,
            "score": analysis.score,
            "correct": analysis.met_minimum,
            "word_count": analysis.word_count,
            "spoken_seconds": spoken_seconds,
            "recognition_confidence": recognition_confidence,
            "typed_instead": typed_instead,
            "checks": [
                {"code": c.code, "passed": c.passed, "message": c.message} for c in analysis.checks
            ],
            "provisional": True,
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=0,
        scaffolding_level=1.0 if typed_instead else 0.0,
        evaluator_id=EVALUATOR_ID,
    )
    session.add(attempt)
    session.flush()

    long_enough = spoken_seconds >= task.min_seconds
    node = _skill_node(session, task.skill_key)
    recorded = False

    if node is not None and analysis.met_minimum and long_enough and not typed_instead:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=SPEAKING_EVIDENCE,
            score=analysis.score,
            difficulty=_difficulty_for(task.cefr_level.rank),
            confidence=TRANSCRIPT_CONFIDENCE,
            independence=1.0,
            novelty=1.0,
            context_key=f"speak:{task.key}",
            metadata={
                "source": SPEAKING_CONTEXT,
                "format": task.speaking_format,
                "provisional": True,
                "spoken_seconds": spoken_seconds,
                "word_count": analysis.word_count,
                # Recorded so a later audit can ask whether recognition
                # quality correlated with scores. Never used to score.
                "recognition_confidence": recognition_confidence,
                "unjudged_features": list(task.target_features),
                # Named explicitly: this evidence says nothing about how the
                # learner sounded, and a future reader should not assume it.
                "pronunciation_unassessed": True,
            },
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    session.flush()
    return SpeakingResult(
        activity_key=activity_key,
        score=analysis.score,
        analysis=analysis,
        evidence_recorded=recorded,
        spoken_seconds=spoken_seconds,
        transcript=transcript,
        recognition_confidence=recognition_confidence,
        typed_instead=typed_instead,
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


# --- Completion: mediation --------------------------------------------------


def complete_mediation(
    session: Session,
    user_id: uuid.UUID,
    *,
    activity_key: str,
    text: str,
    duration_ms: int | None = None,
    evaluator: WritingEvaluator | None = None,
) -> MediationResult:
    """Check a multi-source account against countable requirements.

    Everything `complete_writing` does, plus the two checks that are specific
    to mediation: whether every source was drawn on, and whether the account
    was restated rather than transcribed.

    Evidence lands on a `mediation.*` skill -- the curriculum parser refuses a
    task that targets anything else -- at `MEDIATION_CONFIDENCE`, which is
    below writing's. The extra checks make this a *stricter* test of writing
    and a *weaker* test of mediation: an anchor proves a figure was mentioned,
    not that it was reported correctly, and a learner can name the number
    while misrepresenting it entirely.

    A copied response still records evidence, at the lower score its failed
    check produces. Copying is a real thing the learner did with language and
    the deterministic pass caught it; refusing to record would discard a
    measurement that worked.
    """
    task = get_mediation(activity_key)
    analysis = analyse_mediation(
        text,
        task.requirements,
        task.sources,
        max_verbatim_words=task.max_verbatim_words,
    )

    learning_session = _open_session(session, user_id, MEDIATION_CONTEXT)
    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=activity_key,
        activity_type=MEDIATION_TYPE,
        attempt_number=_next_attempt_number(session, user_id, activity_key),
        response={
            "text": text,
            "score": analysis.score,
            "correct": analysis.met_minimum,
            "word_count": analysis.word_count,
            "used_sources": list(analysis.used_sources),
            "unused_sources": list(analysis.unused_sources),
            "longest_copied_run": analysis.longest_copied_run,
            "copied_from": analysis.copied_from,
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
            evidence_type=MEDIATION_EVIDENCE,
            score=analysis.score,
            difficulty=_difficulty_for(task.cefr_level.rank),
            confidence=MEDIATION_CONFIDENCE,
            independence=1.0,
            novelty=1.0,
            context_key=f"mediate:{task.key}",
            metadata={
                "source": MEDIATION_CONTEXT,
                "provisional": True,
                "word_count": analysis.word_count,
                "source_count": len(task.sources),
                "source_kinds": list(task.source_kinds),
                "sources_used": len(analysis.used_sources),
                "longest_copied_run": analysis.longest_copied_run,
                # Named explicitly, because the obvious misreading of this
                # evidence is that it says the sources were conveyed
                # correctly. It does not.
                "fidelity_unassessed": True,
                "unjudged_features": list(task.target_features),
            },
        )
        recompute_skill_state(session, user_id=user_id, skill_node_id=node.id)
        recorded = True

    evaluation = _evaluate_mediation(task, text, evaluator) if analysis.met_minimum else None
    if evaluation is not None and evaluation.is_usable and node is not None:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=MEDIATION_EVIDENCE,
            score=evaluation.overall_score,
            difficulty=_difficulty_for(task.cefr_level.rank),
            confidence=min(evaluation.confidence, MAX_RUBRIC_CONFIDENCE),
            independence=1.0,
            novelty=1.0,
            # One account judged twice, not two contexts.
            context_key=f"mediate:{task.key}",
            metadata={
                "source": MEDIATION_CONTEXT,
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
    return MediationResult(
        activity_key=activity_key,
        score=analysis.score,
        analysis=analysis,
        evidence_recorded=recorded,
        evaluation=evaluation,
    )


def _evaluate_mediation(
    task: MediationTask,
    text: str,
    evaluator: WritingEvaluator | None,
) -> WritingEvaluation | None:
    """Ask the configured evaluator to judge a mediation account.

    The brief and every source travel in the prompt. An evaluator shown only
    the response could not tell a faithful account from an invented one,
    which is the single thing worth judging here.
    """
    chosen = evaluator or get_writing_evaluator()
    material = "\n\n".join(
        f"SOURCE ({source.kind}) {source.title}:\n{source.text}" for source in task.sources
    )
    request = WritingEvaluationRequest(
        task_prompt=f"{task.brief}\n\n{material}",
        response_text=text,
        target_level=task.cefr_level.value,
        skill_key=task.skill_key,
    )
    try:
        return chosen.evaluate(request)
    except Exception:  # noqa: BLE001 - deliberately total; see complete_writing
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
    spoken_seconds: int = 0,
    recognition_confidence: float | None = None,
    typed_instead: bool = False,
    duration_ms: int | None = None,
) -> (
    ActivityResult
    | StudyResult
    | WritingResult
    | ListeningResult
    | SpeakingResult
    | MediationResult
):
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

    if kind == MEDIATION_TYPE:
        if text is None:
            raise ActivityPayloadError(activity_key, "text")
        return complete_mediation(
            session,
            user_id,
            activity_key=activity_key,
            text=text,
            duration_ms=duration_ms,
        )

    if kind == SPEAKING_TYPE:
        if text is None:
            raise ActivityPayloadError(activity_key, "text")
        return complete_speaking(
            session,
            user_id,
            activity_key=activity_key,
            transcript=text,
            spoken_seconds=spoken_seconds,
            recognition_confidence=recognition_confidence,
            typed_instead=typed_instead,
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


#: Question types the content carries, and the comprehension feature each
#: maps to. A type outside this map is logged as nothing rather than guessed
#: at: the closed taxonomy is the point, and inventing a code from a typo in
#: curriculum source is the failure it exists to prevent.
COMPREHENSION_TYPES = ("gist", "detail", "inference")


def _log_comprehension_errors(
    session: Session,
    user_id: uuid.UUID,
    results: tuple[QuestionResult, ...],
    *,
    domain: str,
    source: str,
) -> None:
    """Record what kind of comprehension question the learner missed.

    Before this, the error log had nothing at all to say about reading or
    listening: someone could work through a dozen texts, miss every inference
    question, and see an empty list. Whether a reader gets the facts and
    misses what is implied is one of the more useful things anyone could tell
    them, and it was sitting unused in the stored results.

    **Once per question type, not once per question.** A text with four
    inference questions would otherwise push that feature past the recurrence
    threshold on its own, and the whole point of the threshold is that one bad
    afternoon is not a pattern. This matches how wrong study items are logged.
    """
    missed = {
        result.question_type
        for result in results
        if not result.correct and result.question_type in COMPREHENSION_TYPES
    }
    if not missed:
        return

    for question_type in sorted(missed):
        code = f"{domain}.comprehension.{question_type}"
        record_error(
            session,
            user_id,
            taxonomy_code=code,
            description=taxonomy.describe(code),
            example=source,
            blocks_meaning=taxonomy.blocks_meaning_default(code),
        )
    sync_error_cards(session, user_id)


def remedy_for_feature(feature_code: str) -> _Remedy | None:
    """Something the learner can open that answers this error.

    Two kinds of answer, because two kinds of error. A production feature is
    answered by a study unit: there is a rule, and explaining it then drilling
    it is what helps. A comprehension feature has no rule to explain — the
    answer is another text or clip that asks that kind of question, so the
    learner meets it again with a fresh passage rather than reading about
    inference in the abstract.

    Returns `None` where nothing exists, which the error log reports as
    `not_written` rather than passing off an unrelated activity as a remedy.
    """
    if not taxonomy.is_known(feature_code):
        return None

    domain, _, question_type = feature_code.partition(".comprehension.")
    if question_type in COMPREHENSION_TYPES:
        return _comprehension_remedy(domain, question_type)

    units = study_for_feature(feature_code)
    if not units:
        return None
    unit = min(units, key=lambda item: (item.minutes, item.key))
    return _Remedy(
        activity_key=study_key_for(unit),
        activity_type=STUDY_TYPE,
        title=unit.title,
        minutes=unit.minutes,
        skill_key=unit.skill_key,
    )


def _comprehension_remedy(domain: str, question_type: str) -> _Remedy | None:
    """The shortest text or clip that asks this kind of question.

    Shortest rather than most relevant: the learner is being sent back to a
    skill they just got wrong, and a twenty-minute C1 article is a poor place
    to try again. Ties break on key so the same error always opens the same
    thing.
    """
    if domain == "reading":
        candidates = [
            (
                _Remedy(
                    activity_key=activity_key_for(text),
                    activity_type=READING_TYPE,
                    title=text.title,
                    minutes=text.minutes,
                    skill_key=text.skill_key,
                ),
                text.minutes,
                text.key,
            )
            for text in library()
            if any(question.question_type == question_type for question in text.questions)
        ]
    elif domain == "listening":
        candidates = [
            (
                _Remedy(
                    activity_key=listening_key_for(clip),
                    activity_type=LISTENING_TYPE,
                    title=clip.title,
                    minutes=clip.minutes,
                    skill_key=clip.skill_key,
                ),
                clip.minutes,
                clip.key,
            )
            for clip in listening_clips()
            if any(question.question_type == question_type for question in clip.questions)
        ]
    else:
        return None

    if not candidates:
        return None
    return min(candidates, key=lambda pair: (pair[1], pair[2]))[0]


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
    """The session this attempt belongs to.

    A sitting the learner opened deliberately wins, so that work done during
    one is attributable to it rather than scattered across a session per
    activity kind.

    Failing that, an open session of this kind *started today*. The day check
    is load-bearing: without it a session opened in March was still collecting
    attempts in July, `ended_at` was null on every row, and `started_at` meant
    nothing. `services.sessions.start` abandons the leftovers.
    """
    today = utcnow().date()
    candidates = list(
        session.execute(
            select(LearningSession)
            .where(
                LearningSession.user_id == user_id,
                LearningSession.status == SessionStatus.IN_PROGRESS,
            )
            .order_by(LearningSession.started_at.desc())
        ).scalars()
    )
    for candidate in candidates:
        if candidate.context.get("kind") == SITTING_KIND and candidate.started_at.date() == today:
            return candidate
    for candidate in candidates:
        if candidate.context.get("kind") == kind and candidate.started_at.date() == today:
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
    "MEDIATION_TYPE",
    "READING_TYPE",
    "SPEAKING_TYPE",
    "STUDY_TYPE",
    "WRITING_TYPE",
    "ActivityResult",
    "ListeningResult",
    "MediationResult",
    "QuestionResult",
    "SpeakingResult",
    "StudyItemResult",
    "StudyResult",
    "WritingResult",
    "activity_key_for",
    "activity_type_for",
    "clips_for_skill",
    "complete",
    "complete_listening",
    "complete_mediation",
    "complete_reading",
    "complete_speaking",
    "complete_study",
    "complete_writing",
    "get_activity",
    "get_listening",
    "get_mediation",
    "get_reading",
    "get_speaking",
    "get_study",
    "get_writing",
    "is_openable",
    "library",
    "listening_by_key",
    "listening_clips",
    "listening_independence",
    "listening_key_for",
    "mediation_by_key",
    "mediation_for_skill",
    "mediation_key_for",
    "mediation_tasks",
    "speaking_by_key",
    "speaking_for_skill",
    "speaking_key_for",
    "speaking_tasks",
    "study_for_feature",
    "study_for_skill",
    "study_key_for",
    "study_units",
    "tasks_for_skill",
    "texts_for_skill",
    "writing_key_for",
    "writing_tasks",
]
