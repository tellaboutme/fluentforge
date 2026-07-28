"""What the learner is learning English *for*.

`curriculum/tracks/` has held three tracks since the beginning. They were
parsed, validated, hashed into every curriculum version — and nothing selected
one, so the answer to "what is this for?" existed as data and never reached a
learner or a plan.

That absence has a cost that shows up in one place: a junior engineer who
needs to survive a standup and a postgraduate who needs to summarise three
papers were being offered exactly the same plan, and the product had the
information to know better.

What a track does, and what it must never do
--------------------------------------------
A track raises `goal_match` on candidates in its priority domains. That
component already existed in `learning/planning.py` with a weight of 0.40 and
had never once been non-zero, because nothing populated it.

**It is additive and bounded, never a filter.** Nothing is removed from
consideration for being off-track. A learner on the technology track with weak
A2 grammar still gets A2 grammar, and gets it ahead of a speaking task,
because `prerequisite_weakness` and `due_pressure` are scored independently
and a track cannot reach them. A track that could suppress a weak
prerequisite would be a way of avoiding the very thing holding someone back,
dressed up as personalisation.

**A track's `levels` bound its scenarios, not the learner.** The academic
track runs B1 to C2; that says where academic scenarios live, not that someone
on it may only study B1 and above.

**An unknown key falls back to general.** Curriculum is versioned and tracks
can be withdrawn. A learner whose track disappeared should get a sensible plan
and a chance to choose again, not a 500 on their own profile.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..curriculum.maps import Track, parse_maps
from ..models.enums import SkillDomain
from ..settings import settings

#: The track a learner has if they have not chosen, and the fallback for a key
#: the curriculum no longer defines.
DEFAULT_TRACK = "general"

#: How much being in a track's priority domains contributes to `goal_match`.
#: Not 1.0: a track is a statement about purpose, not about what the learner
#: is ready for, and letting it max out the component would put a C1 speaking
#: task above a due review for someone who picked the career track this
#: morning. `learning/planning.py` then weights the component itself.
IN_TRACK_MATCH = 0.75

#: What a candidate outside the track scores. Deliberately not zero. General
#: English is not irrelevant to someone learning it for work, and a plan that
#: treated it as worthless would narrow into the track and stay there.
OFF_TRACK_MATCH = 0.25


@lru_cache(maxsize=4)
def _load(curriculum_dir: str) -> tuple[Track, ...]:
    return parse_maps(Path(curriculum_dir)).tracks


def available() -> tuple[Track, ...]:
    """Every track a learner may choose, in a stable order."""
    return tuple(sorted(_load(str(settings.curriculum_dir)), key=lambda track: track.key))


def get(key: str | None) -> Track | None:
    """One track by key, or `None` when nothing matches.

    Callers that need a track regardless should use `priority_domains`, which
    falls back. This returns `None` so that a *display* of the learner's
    choice can say honestly that the track they picked is gone.
    """
    for track in available():
        if track.key == key:
            return track
    return None


def resolve(key: str | None) -> Track | None:
    """The track to plan with: the learner's, or general, or nothing."""
    return get(key) or get(DEFAULT_TRACK)


def priority_domains(key: str | None) -> frozenset[SkillDomain]:
    """Domains this track raises. Empty when no track resolves at all.

    Empty is a real outcome rather than a defensive one: a curriculum without
    a `general` track and without the learner's own is a curriculum where no
    honest boost exists, and returning nothing leaves the plan driven entirely
    by evidence — which is the right failure.
    """
    track = resolve(key)
    if track is None:
        return frozenset()
    return frozenset(SkillDomain(domain) for domain in track.priority_domains if _is_domain(domain))


def goal_match_for(domain: SkillDomain, key: str | None) -> float:
    """How well a candidate in this domain matches the learner's purpose.

    Never 0.0 and never 1.0. The floor is there because off-track work still
    counts; the ceiling because a track states a purpose, not a readiness, and
    the planner has better-founded signals for the latter.
    """
    domains = priority_domains(key)
    if not domains:
        return 0.0
    return IN_TRACK_MATCH if domain in domains else OFF_TRACK_MATCH


def _is_domain(value: str) -> bool:
    return value in {member.value for member in SkillDomain}


__all__ = [
    "DEFAULT_TRACK",
    "IN_TRACK_MATCH",
    "OFF_TRACK_MATCH",
    "available",
    "get",
    "goal_match_for",
    "priority_domains",
    "resolve",
]
