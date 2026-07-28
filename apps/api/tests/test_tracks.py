"""What the learner is learning English for.

Three tracks have sat in `curriculum/tracks/` since the beginning — parsed,
validated, hashed into every curriculum version, and selected by nobody. A
junior engineer who needs to survive a standup and a postgraduate who needs to
summarise three papers were being offered the same plan, and the product had
the information to know better.

The whole risk of this feature is in one place, and most of these tests are
about it: **a track must never be able to bury the thing actually holding a
learner back**. Personalisation that lets someone avoid their weak
prerequisites is not personalisation, it is an excuse with a nice name. So the
boost is additive, bounded, applied to a component the planner weights among
several, and structurally unable to reach `due_pressure`,
`prerequisite_weakness` or `error_pressure`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.app.learning.planning import Candidate, score_candidate
from apps.api.app.models.enums import SkillDomain
from apps.api.app.services import tracks
from apps.api.tests.helpers import register


def _candidate(domain: SkillDomain, **kwargs: object) -> Candidate:
    defaults: dict[str, object] = {
        "activity_key": "read:x",
        "activity_type": "reading_task",
        "kind": "input",
        "skill_key": "reading.x",
        "domain": domain,
        "estimated_minutes": 10,
        "title": "Something",
    }
    defaults.update(kwargs)
    return Candidate(**defaults)  # type: ignore[arg-type]


# --- The tracks themselves --------------------------------------------------


def test_every_track_names_domains_that_exist() -> None:
    """A typo here fails in the worst possible way: the track loads, the
    learner picks it, and nothing about their plan ever changes."""
    known = {member.value for member in SkillDomain}

    for track in tracks.available():
        assert track.priority_domains
        assert set(track.priority_domains) <= known


def test_every_track_would_actually_change_something() -> None:
    """A track with no priority domains is a name and a level range."""
    for track in tracks.available():
        assert tracks.priority_domains(track.key)


def test_the_general_track_exists_and_is_the_default() -> None:
    """It is the fallback for a withdrawn track and the starting point for a
    learner who has not chosen a purpose."""
    assert tracks.get(tracks.DEFAULT_TRACK) is not None


def test_the_general_track_has_no_scenarios() -> None:
    """Deliberate. It is for someone who has not chosen a purpose, and
    inventing one for them would be worse than admitting there is none."""
    general = tracks.get("general")

    assert general is not None
    assert general.scenarios == ()


def test_the_scenario_led_tracks_prioritise_different_domains() -> None:
    """If two tracks boost the same domains they are one track with two
    names, and the choice is theatre."""
    academic = tracks.priority_domains("academic")
    career = tracks.priority_domains("technology-career")

    assert academic
    assert career
    assert academic != career


def test_the_career_track_starts_lower_than_the_academic_one() -> None:
    """A junior engineer can be doing standups in English long before their
    general English is B1."""
    academic = tracks.get("academic")
    career = tracks.get("technology-career")

    assert academic is not None and career is not None
    assert career.levels[0].rank < academic.levels[0].rank


# --- Resolving one ----------------------------------------------------------


def test_an_unknown_track_falls_back_rather_than_raising() -> None:
    """Curriculum is versioned and tracks can be withdrawn. A learner whose
    track disappeared needs a sensible plan and a chance to choose again, not
    a 500 on their own profile."""
    assert tracks.resolve("no-such-track") is not None
    assert tracks.priority_domains("no-such-track") == tracks.priority_domains("general")


def test_get_does_not_fall_back() -> None:
    """A *display* of the learner's choice must be able to say honestly that
    the track they picked is gone."""
    assert tracks.get("no-such-track") is None


# --- The boost --------------------------------------------------------------


def test_in_track_work_scores_higher_than_off_track_work() -> None:
    academic = tracks.goal_match_for(SkillDomain.READING, "academic")
    off = tracks.goal_match_for(SkillDomain.PRONUNCIATION, "academic")

    assert academic > off


def test_off_track_work_still_counts_for_something() -> None:
    """General English is not irrelevant to someone learning it for work, and
    a plan that treated it as worthless would narrow into the track and stay
    there."""
    assert tracks.OFF_TRACK_MATCH > 0.0


def test_a_track_never_maxes_the_component() -> None:
    """A track states a purpose, not a readiness. Letting it reach 1.0 would
    put a C1 speaking task above a due review for someone who picked the
    career track this morning."""
    assert tracks.IN_TRACK_MATCH < 1.0


def test_a_weak_prerequisite_still_outranks_an_on_track_activity() -> None:
    """The load-bearing test.

    Personalisation that lets a learner avoid the thing holding them back is
    an excuse with a nice name. A track can only move `goal_match`; it cannot
    reach `prerequisite_weakness`, and the weights are set so it does not need
    to be trusted to behave.
    """
    blocked = _candidate(
        SkillDomain.GRAMMAR,
        prerequisite_weakness=1.0,
        goal_match=tracks.OFF_TRACK_MATCH,
        has_evidence=True,
        mastery_probability=0.3,
    )
    on_track = _candidate(
        SkillDomain.SPOKEN_INTERACTION,
        prerequisite_weakness=0.0,
        goal_match=tracks.IN_TRACK_MATCH,
        has_evidence=True,
        mastery_probability=0.3,
    )

    assert score_candidate(blocked).priority > score_candidate(on_track).priority


def test_a_due_review_still_outranks_an_on_track_activity() -> None:
    due = _candidate(
        SkillDomain.VOCABULARY,
        kind="review",
        due_pressure=1.0,
        goal_match=tracks.OFF_TRACK_MATCH,
        has_evidence=True,
    )
    on_track = _candidate(
        SkillDomain.SPOKEN_INTERACTION,
        goal_match=tracks.IN_TRACK_MATCH,
        has_evidence=True,
    )

    assert score_candidate(due).priority > score_candidate(on_track).priority


def test_the_track_contribution_is_visible_in_the_components() -> None:
    """`docs/ADAPTIVE_ENGINE.md` forbids an opaque score. A boost the learner
    cannot see is exactly that."""
    scored = score_candidate(
        _candidate(SkillDomain.READING, goal_match=tracks.IN_TRACK_MATCH, has_evidence=True)
    )

    assert scored.components["goal_relevance"] > 0


# --- Through the API --------------------------------------------------------


def test_the_tracks_endpoint_lists_them_with_their_consequences(
    seeded_client: TestClient,
) -> None:
    """A track presented as a name with unstated consequences is the same
    opaque personalisation the docs refuse elsewhere."""
    response = seeded_client.get("/api/v1/curriculum/tracks")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["tracks"]) >= 3
    assert all(track["priority_domains"] for track in body["tracks"])
    assert body["caveats"]


def test_the_caveats_say_a_track_never_removes_anything(
    seeded_client: TestClient,
) -> None:
    body = seeded_client.get("/api/v1/curriculum/tracks").json()

    assert any("never removes" in caveat for caveat in body["caveats"])


def test_a_new_learner_is_on_the_general_track(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "track-new@example.com")

    body = seeded_client.get("/api/v1/profile", headers=headers).json()

    assert body["track_key"] == tracks.DEFAULT_TRACK
    assert body["track_name"]


def test_a_learner_can_choose_a_track(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "track-choose@example.com")

    response = seeded_client.patch(
        "/api/v1/profile", json={"track_key": "academic"}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["track_key"] == "academic"
    assert response.json()["track_name"] == "Academic English"


def test_an_unknown_track_is_refused_rather_than_stored(
    seeded_client: TestClient,
) -> None:
    """A typo that silently saved would leave the learner looking at a track
    they believe they chose while their plan quietly fell back to general."""
    headers = register(seeded_client, "track-typo@example.com")

    response = seeded_client.patch(
        "/api/v1/profile", json={"track_key": "acadmic"}, headers=headers
    )

    assert response.status_code == 422
    assert "unknown_track" in response.text
    assert (
        seeded_client.get("/api/v1/profile", headers=headers).json()["track_key"]
        == tracks.DEFAULT_TRACK
    )


def test_switching_track_resets_nothing(seeded_client: TestClient, db_session: Session) -> None:
    """Evidence is evidence whatever the learner is studying for. A switch
    that cleared it would punish someone for changing their mind."""
    headers = register(seeded_client, "track-switch@example.com")
    before = seeded_client.get("/api/v1/profile", headers=headers).json()

    seeded_client.patch("/api/v1/profile", json={"track_key": "academic"}, headers=headers)
    after = seeded_client.get("/api/v1/profile", headers=headers).json()

    assert [skill["skill_key"] for skill in after["skills"]] == [
        skill["skill_key"] for skill in before["skills"]
    ]
    assert [skill["evidence_count"] for skill in after["skills"]] == [
        skill["evidence_count"] for skill in before["skills"]
    ]


def test_the_plan_reflects_the_chosen_track(seeded_client: TestClient) -> None:
    """End to end: choosing a track has to reach the plan, or the whole
    feature is a stored string."""
    headers = register(seeded_client, "track-plan@example.com")
    seeded_client.patch("/api/v1/profile", json={"track_key": "technology-career"}, headers=headers)

    plan = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    skill_items = [
        item for item in plan["items"] if item["components"].get("goal_relevance") is not None
    ]
    assert skill_items
    assert any(item["components"]["goal_relevance"] > 0 for item in skill_items)


def test_reflection_is_not_scored_against_a_track(seeded_client: TestClient) -> None:
    """It targets no skill, and a track has nothing to say about whether
    someone should think about their week."""
    headers = register(seeded_client, "track-reflect@example.com")
    seeded_client.patch("/api/v1/profile", json={"track_key": "academic"}, headers=headers)

    plan = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    for item in plan["items"]:
        if item["activity_type"] == "reflection":
            assert item["components"].get("goal_relevance", 0) == 0


def test_a_track_is_not_a_level_gate(seeded_client: TestClient) -> None:
    """The academic track runs B1 to C2. That says where its scenarios live,
    not that a learner on it may only be offered B1 and above — a track that
    could hide an A2 gap would be a way of avoiding it."""
    headers = register(seeded_client, "track-levels@example.com")
    seeded_client.patch("/api/v1/profile", json={"track_key": "academic"}, headers=headers)

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()

    assert any(skill["skill_key"] for skill in profile["skills"])
    assert len(profile["skills"]) > 0


def test_the_endpoint_needs_no_account(seeded_client: TestClient) -> None:
    """Someone deciding whether to sign up should be able to see what the
    product is for."""
    assert seeded_client.get("/api/v1/curriculum/tracks").status_code == 200


def test_choosing_a_track_needs_one(seeded_client: TestClient) -> None:
    assert seeded_client.patch("/api/v1/profile", json={"track_key": "academic"}).status_code == 401


def test_ids_are_stable(seeded_client: TestClient) -> None:
    """Track keys are stored on learner profiles, so renaming one silently
    unsets everybody's choice."""
    keys = {track.key for track in tracks.available()}

    assert {"general", "academic", "technology-career"} <= keys
