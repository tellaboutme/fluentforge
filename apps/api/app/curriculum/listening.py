"""Parse and validate the listening library.

How this works without audio files
----------------------------------
A clip carries a **transcript** and an optional `audio` path. Nothing in this
repository ships recorded audio: recordings are large, they carry licensing
questions the rest of the curriculum deliberately avoids, and generating them
would need a paid service that `docs/PRODUCT_SPEC.md` says the core loop must
work without.

So the transcript is the source of truth, and the client speaks it using the
browser's own speech synthesis. That is a real compromise and it is worth
naming precisely:

- Synthetic speech has cleaner connected speech than a human speaker. Weak
  forms, elision and assimilation — the things that actually make listening
  hard — are under-represented. A learner who copes here has not proved they
  cope with a recording of two people in a café.
- Voice quality and availability vary by platform, so two learners are not
  hearing quite the same thing.

`audio` exists so a deployment can point at real recordings without a
migration or a schema change; when it is set, the client should prefer it.
Until then, `docs/CURRENT_STATUS.md` records the limitation rather than
letting the profile quietly overstate what was measured.

Why the transcript is still sent to the client
----------------------------------------------
It has to be: it is the stimulus that gets spoken, and a learner who cannot
use audio at all must still be able to do the activity. Withholding it would
make the lab inaccessible, which is not a trade this project makes. What
protects the measurement is not secrecy but honesty — revealing the transcript
before answering is recorded, and the attempt then evidences reading rather
than listening (see `services/activities.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..models.enums import CefrLevel
from .parser import CurriculumError
from .questions import Question, parse_questions

LISTENING_RELATIVE_PATH = Path("content") / "listening.yml"

#: How fast the clip should be spoken, relative to the voice's normal rate.
#: Slower at low levels, because an A1 learner needs processing time more than
#: they need authentic pace. Never below this floor: speech slowed past it
#: stops sounding like language and starts sounding like a fault.
MIN_SPEECH_RATE = 0.6
MAX_SPEECH_RATE = 1.2

#: A clip shorter than this cannot carry a gist question worth asking.
MIN_TRANSCRIPT_WORDS = 15


@dataclass(frozen=True)
class ListeningClip:
    key: str
    cefr_level: CefrLevel
    skill_key: str
    title: str
    #: Who is speaking, and where. Real listening always has context; taking
    #: it away tests something other than comprehension.
    setting: str
    transcript: str
    minutes: int
    speech_rate: float
    #: A path to real audio, or None to synthesise from the transcript.
    audio: str | None
    questions: tuple[Question, ...]

    @property
    def word_count(self) -> int:
        return len(self.transcript.split())

    @property
    def is_synthesised(self) -> bool:
        return self.audio is None

    def as_prompt(self) -> dict[str, Any]:
        """Client-safe view.

        The transcript *is* included — the client speaks it, and a learner
        who cannot use audio needs it. Answers are still withheld, exactly as
        for reading.
        """
        return {
            "key": self.key,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "title": self.title,
            "setting": self.setting,
            "transcript": self.transcript,
            "minutes": self.minutes,
            "speech_rate": self.speech_rate,
            "audio": self.audio,
            "questions": [question.as_prompt() for question in self.questions],
        }


def parse_listening(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[ListeningClip, ...]:
    """Parse the listening library, reporting every problem at once."""
    path = curriculum_dir / LISTENING_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"listening library not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_clips = document.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise CurriculumError([f"{path.name}: no clips"])

    errors: list[str] = []
    clips: list[ListeningClip] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_clips):
        clip = _parse_clip(raw, index, path.name, known_skill_keys, errors)
        if clip is None:
            continue
        if clip.key in seen:
            errors.append(f"{path.name}: duplicate clip {clip.key}")
            continue
        seen.add(clip.key)
        clips.append(clip)

    if errors:
        raise CurriculumError(errors)

    return tuple(clips)


def _parse_clip(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> ListeningClip | None:
    where = f"{filename}: clip {index}"

    if not isinstance(raw, dict):
        errors.append(f"{where} is not a mapping")
        return None

    key = raw.get("key")
    if not isinstance(key, str) or not key:
        errors.append(f"{where} has no key")
        return None
    where = f"{filename}: {key}"

    try:
        level = CefrLevel(str(raw.get("level", "")).upper())
    except ValueError:
        errors.append(f"{where} has invalid level {raw.get('level')!r}")
        return None

    skill_key = raw.get("skill")
    if not isinstance(skill_key, str) or not skill_key:
        errors.append(f"{where} has no skill")
        return None
    if known_skill_keys is not None and skill_key not in known_skill_keys:
        errors.append(f"{where} references unknown skill {skill_key!r}")
        return None

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{where} has no title")
        return None

    setting = raw.get("setting")
    if not isinstance(setting, str) or not setting.strip():
        errors.append(f"{where} has no setting")
        return None

    transcript = raw.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        errors.append(f"{where} has no transcript")
        return None
    if len(transcript.split()) < MIN_TRANSCRIPT_WORDS:
        errors.append(f"{where} transcript is under {MIN_TRANSCRIPT_WORDS} words")
        return None

    minutes = raw.get("minutes", 5)
    if not isinstance(minutes, int) or minutes < 1:
        errors.append(f"{where} has invalid minutes {minutes!r}")
        return None

    speech_rate = raw.get("speech_rate", 1.0)
    if not isinstance(speech_rate, (int, float)) or isinstance(speech_rate, bool):
        errors.append(f"{where} has invalid speech_rate {speech_rate!r}")
        return None
    if not MIN_SPEECH_RATE <= float(speech_rate) <= MAX_SPEECH_RATE:
        errors.append(
            f"{where} speech_rate {speech_rate} is outside {MIN_SPEECH_RATE}-{MAX_SPEECH_RATE}"
        )
        return None

    audio = raw.get("audio")
    if audio is not None and (not isinstance(audio, str) or not audio.strip()):
        errors.append(f"{where} has an empty audio path; omit it to synthesise instead")
        return None

    questions = parse_questions(raw.get("questions"), where, errors)
    if questions is None:
        return None

    return ListeningClip(
        key=key,
        cefr_level=level,
        skill_key=skill_key,
        title=title.strip(),
        setting=" ".join(setting.split()),
        transcript=transcript.strip(),
        minutes=minutes,
        speech_rate=round(float(speech_rate), 2),
        audio=audio.strip() if isinstance(audio, str) else None,
        questions=questions,
    )


__all__ = [
    "LISTENING_RELATIVE_PATH",
    "MAX_SPEECH_RATE",
    "MIN_SPEECH_RATE",
    "MIN_TRANSCRIPT_WORDS",
    "ListeningClip",
    "parse_listening",
]
