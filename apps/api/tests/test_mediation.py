"""Multi-source mediation: the analysis, the bank, and completing a task.

Mediation is the C-level work `docs/ROADMAP.md` Milestone 7 asks for, and the
thing it warns against substituting for it. So the tests are organised around
what makes this task different from writing rather than around what it shares
with it.

Two checks exist nowhere else, and both are here in detail:

- **Was every source drawn on?** Inferred from anchors — names, figures and
  dates that survive paraphrase. An approximation, and the tests hold it to
  being a *fair* one: distinctive, present in its own source, and never
  presented to the learner as certainty.
- **Was it restated or transcribed?** The longest run shared with a source,
  after marked quotations are removed. Quoting and attributing is legitimate
  mediation; passing someone else's sentence off as your own account is not,
  and the difference has to survive in the measurement.

What no test here asserts is that the sources were conveyed *accurately*.
Nothing in this module can know that, which is why mediation evidence carries
the lowest deterministic confidence in the system.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.mediation import MIN_SOURCES, parse_mediation_tasks
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.errors import ActivityNotFoundError
from apps.api.app.learning.mediation import (
    DETERMINISTIC_CONFIDENCE as MEDIATION_CONFIDENCE,
)
from apps.api.app.learning.mediation import (
    Source,
    analyse_mediation,
    longest_shared_run,
    sources_drawn_on,
    strip_quotations,
)
from apps.api.app.learning.writing import DETERMINISTIC_CONFIDENCE, WritingRequirements
from apps.api.app.models.enums import EvidenceType
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, EvidenceEvent
from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

TASK = "mediate.b1.moving_the_meeting"

#: Draws on both sources, copies neither, and says where they disagree.
GOOD = (
    "Two people have written about Thursday and they want opposite things. "
    "The first would prefer nine in the morning, since she must collect my "
    "son at four and the present arrangement leaves her nothing afterwards; "
    "if that cannot be done she would rather the whole thing moved to "
    "Tuesday. The second says no morning works for him at all, because he "
    "is at the warehouse until lunchtime each week this month, and he wants "
    "to keep the afternoon slot, which is the only one within his reach. So "
    "both requests cannot be met as things stand. What you need to decide "
    "is whether we keep the current time and accept that one of them leaves "
    "early, or move the meeting to another day entirely."
)

TWO = (
    Source("a", "First", "email", "The heating in room two failed on Tuesday.", ("heating",)),
    Source("b", "Second", "notice", "Bookings for March came to nine hundred.", ("bookings",)),
)


# --- Restating rather than transcribing -------------------------------------


def test_unrelated_texts_share_almost_nothing() -> None:
    assert longest_shared_run("the cat sat down", "an entirely different remark") <= 1


def test_a_copied_sentence_is_measured() -> None:
    source = "Total bookings for the period were nine thousand four hundred and twelve."
    response = f"She said this. {source} That is the figure."
    assert longest_shared_run(response, source) == 12


def test_repunctuating_a_copied_sentence_does_not_hide_it() -> None:
    """Compared on normalised words, so re-casing and re-punctuating fail."""
    source = "The break clause falls due in eleven months."
    disguised = "the BREAK clause, falls due in eleven months"
    assert longest_shared_run(disguised, source) >= 7


def test_scattering_dashes_through_a_lift_does_not_hide_it() -> None:
    """The obvious evasion, and one a learner could stumble into honestly.
    Punctuation-only tokens are dropped before comparing, so a copied
    sentence cannot be broken into unmatched fragments with stray dashes."""
    source = "The break clause falls due in eleven months."
    disguised = "the break clause -- falls due -- in eleven months"
    assert longest_shared_run(disguised, source) >= 7


def test_an_empty_response_shares_nothing() -> None:
    assert longest_shared_run("", "anything at all") == 0


def test_a_marked_quotation_is_not_counted_as_copying() -> None:
    """Quoting and attributing is legitimate mediation. Counting it would
    teach the learner to stop attributing, which is the opposite lesson."""
    source = "The break clause falls due in eleven months and cannot be exercised."
    quoted = f'The finance lead notes that "{source}" and this matters.'
    assert longest_shared_run(strip_quotations(quoted), source) <= 2


def test_an_unmarked_lift_is_still_counted() -> None:
    source = "The break clause falls due in eleven months and cannot be exercised."
    lifted = f"The finance lead notes that {source}"
    assert longest_shared_run(strip_quotations(lifted), source) >= 10


# --- Source coverage --------------------------------------------------------


def test_an_account_naming_both_sources_covers_both() -> None:
    used = sources_drawn_on("The heating failed and bookings were down.", TWO)
    assert set(used) == {"a", "b"}


def test_a_source_with_no_trace_is_reported() -> None:
    used = sources_drawn_on("The heating failed. Nothing else to add.", TWO)
    assert used == ("a",)


def test_one_anchor_is_enough() -> None:
    """Requiring all of them would mark down a learner who summarised a
    source well but selectively, which is what summarising is."""
    source = (Source("a", "T", "email", "Ana met Boris in Lisbon.", ("Ana", "Boris", "Lisbon")),)
    assert sources_drawn_on("Ana was there.", source) == ("a",)


def test_coverage_ignores_casing_and_punctuation() -> None:
    source = (Source("a", "T", "email", "Kestrel Road was closed.", ("Kestrel Road",)),)
    assert sources_drawn_on("...the closure of KESTREL ROAD, apparently.", source) == ("a",)


# --- The two together -------------------------------------------------------


def _analyse(text: str, *, limit: int = 8):
    return analyse_mediation(
        text,
        WritingRequirements(min_words=5, max_words=500, min_sentences=1, min_connectives=0),
        TWO,
        max_verbatim_words=limit,
    )


def test_a_good_account_passes_both_mediation_checks() -> None:
    analysis = _analyse("The heating gave out, and bookings fell in the same month.")
    assert analysis.drew_on_every_source
    assert not analysis.was_copied
    assert analysis.score == 1.0


def test_missing_a_source_costs_a_check_and_not_the_evidence() -> None:
    analysis = _analyse("The heating gave out. That is all I know about it.")
    assert analysis.unused_sources == ("b",)
    assert analysis.score < 1.0
    assert analysis.met_minimum, "still a substantial piece of writing"


def test_copying_is_named_with_the_source_it_came_from() -> None:
    analysis = _analyse(
        "Here is the note. The heating in room two failed on Tuesday. That is all.",
        limit=4,
    )
    assert analysis.was_copied
    assert analysis.copied_from == "a"
    assert analysis.longest_copied_run >= 8


def test_the_copying_message_says_what_to_do_instead() -> None:
    """Not an accusation: a rule with a remedy."""
    analysis = _analyse("Here is the note. The heating in room two failed on Tuesday.", limit=4)
    message = next(c.message for c in analysis.checks if c.code == "restated")
    assert "quote" in message.lower()
    assert "own words" in message.lower()


def test_the_run_is_reported_even_when_nothing_was_copied() -> None:
    """So a learner can see they were nowhere near the limit, rather than
    only hearing about it the moment they cross it."""
    analysis = _analyse("The heating gave out, and bookings fell in the same month.")
    message = next(c.message for c in analysis.checks if c.code == "restated")
    assert str(analysis.longest_copied_run) in message


def test_the_writing_checks_still_apply() -> None:
    """A mediation task is not a different standard of English, only an extra
    demand on top of one."""
    analysis = _analyse("The heating gave out, and bookings fell in the same month.")
    codes = {check.code for check in analysis.checks}
    assert {"length", "sentences", "connectives"} <= codes


def test_analysis_never_raises_on_anything_a_learner_can_type() -> None:
    for text in ("", "   ", "\n\n", "???", "a" * 5_000, '"""'):
        _analyse(text)


# --- The bank ---------------------------------------------------------------


def test_the_mediation_bank_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_mediation_tasks(curriculum_dir)) > 0


def test_every_task_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for task in parse_mediation_tasks(curriculum_dir, known_skill_keys=known):
        assert task.skill_key in known


def test_every_task_evidences_mediation(curriculum_dir: Path) -> None:
    """Recording a multi-source account as plain writing would lose exactly
    what makes the task hard."""
    for task in parse_mediation_tasks(curriculum_dir):
        assert task.skill_key.startswith("mediation."), task.key


def test_every_task_has_more_than_one_source(curriculum_dir: Path) -> None:
    for task in parse_mediation_tasks(curriculum_dir):
        assert len(task.sources) >= MIN_SOURCES, task.key


def test_the_bank_reaches_c2(curriculum_dir: Path) -> None:
    """Milestone 7 is about advanced work. A bank stopping at B2 has not done
    it, whatever else it contains."""
    levels = {task.cefr_level.value for task in parse_mediation_tasks(curriculum_dir)}
    assert "C2" in levels


def test_sources_get_more_numerous_or_varied_with_level(curriculum_dir: Path) -> None:
    tasks = parse_mediation_tasks(curriculum_dir)
    lowest = min(tasks, key=lambda task: task.cefr_level.rank)
    highest = max(tasks, key=lambda task: task.cefr_level.rank)
    assert len(highest.sources) > len(lowest.sources)


def test_at_least_one_task_mixes_kinds_of_source(curriculum_dir: Path) -> None:
    """Reconciling an email against a chart is harder, and more like real
    mediation, than reconciling three articles."""
    tasks = parse_mediation_tasks(curriculum_dir)
    assert any(len(task.source_kinds) > 1 for task in tasks)


def test_required_wording_is_always_stated(curriculum_dir: Path) -> None:
    for task in parse_mediation_tasks(curriculum_dir):
        stated = f"{task.brief} {' '.join(task.guidance)}".lower()
        for element in task.requirements.required_elements:
            assert element in stated, f"{task.key}: {element}"


def test_anchors_are_never_sent_to_the_client(curriculum_dir: Path) -> None:
    """Publishing them would turn a mediation task into a word hunt."""
    for task in parse_mediation_tasks(curriculum_dir):
        assert "anchors" not in repr(task.as_prompt())


def test_the_sources_themselves_are_sent(curriculum_dir: Path) -> None:
    """They are the material, not an answer key."""
    for task in parse_mediation_tasks(curriculum_dir):
        for source in task.as_prompt()["sources"]:
            assert source["text"]


# --- Refusals ---------------------------------------------------------------


def _bank(tmp_path: Path, body: str) -> Path:
    content = tmp_path / "content"
    content.mkdir(parents=True, exist_ok=True)
    (content / "mediation.yml").write_text(body, encoding="utf-8")
    return tmp_path


HEAD = (
    "tasks:\n"
    "  - key: m1\n"
    "    level: B1\n"
    "    skill: mediation.basic_summary\n"
    "    title: T\n"
    '    brief: "Write this for your colleague Dan, who has read neither."\n'
    '    guidance: ["Use your own words."]\n'
)

TWO_SOURCES = (
    "    sources:\n"
    "      - key: a\n"
    "        title: A\n"
    "        kind: email\n"
    '        text: "The heating in room two failed on Tuesday."\n'
    '        anchors: ["heating"]\n'
    "      - key: b\n"
    "        title: B\n"
    "        kind: notice\n"
    '        text: "Bookings for March came to nine hundred."\n'
    '        anchors: ["bookings"]\n'
)


def test_a_single_source_task_is_refused(tmp_path: Path) -> None:
    """That is a summary, and the writing bank already has those."""
    _bank(
        tmp_path,
        HEAD + "    sources:\n"
        "      - key: a\n"
        "        title: A\n"
        "        kind: email\n"
        '        text: "Only one."\n'
        '        anchors: ["one"]\n',
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("at least 2 sources" in error for error in exc_info.value.errors)


def test_an_anchor_missing_from_its_own_source_is_refused(tmp_path: Path) -> None:
    """A typo becomes a requirement no learner can ever satisfy."""
    _bank(
        tmp_path,
        HEAD + "    sources:\n"
        "      - key: a\n"
        "        title: A\n"
        "        kind: email\n"
        '        text: "The heating failed."\n'
        '        anchors: ["heeting"]\n'
        "      - key: b\n"
        "        title: B\n"
        "        kind: notice\n"
        '        text: "Bookings came to nine hundred."\n'
        '        anchors: ["bookings"]\n',
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("does not appear in its own text" in e for e in exc_info.value.errors)


def test_an_anchor_shared_between_sources_is_refused(tmp_path: Path) -> None:
    """It cannot show which source was read, so coverage built on it is not
    coverage."""
    _bank(
        tmp_path,
        HEAD + "    sources:\n"
        "      - key: a\n"
        "        title: A\n"
        "        kind: email\n"
        '        text: "The heating failed in March."\n'
        '        anchors: ["March"]\n'
        "      - key: b\n"
        "        title: B\n"
        "        kind: notice\n"
        '        text: "Bookings for March came to nine hundred."\n'
        '        anchors: ["bookings"]\n',
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("cannot show which source" in e for e in exc_info.value.errors)


def test_a_source_with_no_anchors_is_refused(tmp_path: Path) -> None:
    _bank(
        tmp_path,
        HEAD + "    sources:\n"
        "      - key: a\n"
        "        title: A\n"
        "        kind: email\n"
        '        text: "The heating failed."\n'
        "      - key: b\n"
        "        title: B\n"
        "        kind: notice\n"
        '        text: "Bookings came to nine hundred."\n'
        '        anchors: ["bookings"]\n',
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("declares no anchors" in e for e in exc_info.value.errors)


def test_a_brief_naming_no_reader_is_refused(tmp_path: Path) -> None:
    """Mediation without an audience is paraphrase."""
    _bank(
        tmp_path,
        HEAD.replace(
            '    brief: "Write this for your colleague Dan, who has read neither."\n',
            '    brief: "Summarise the material below."\n',
        )
        + TWO_SOURCES,
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("names no reader" in error for error in exc_info.value.errors)


def test_a_task_targeting_a_writing_skill_is_refused(tmp_path: Path) -> None:
    _bank(
        tmp_path,
        HEAD.replace("mediation.basic_summary", "writing.connected_genres") + TWO_SOURCES,
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("evidences mediation" in error for error in exc_info.value.errors)


def test_a_task_below_b1_is_refused(tmp_path: Path) -> None:
    """A learner has neither the reading to take in two sources nor the
    writing to reconcile them. The CEFR mediation scales start at B1."""
    _bank(tmp_path, HEAD.replace("level: B1", "level: A1") + TWO_SOURCES)
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("CEFR scales start at B1" in error for error in exc_info.value.errors)


def test_an_impossibly_tight_verbatim_limit_is_refused(tmp_path: Path) -> None:
    """Below four words, ordinary overlap — a name and a date — would be
    reported as copying."""
    _bank(tmp_path, HEAD + "    max_verbatim_words: 2\n" + TWO_SOURCES)
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("would be reported as copying" in error for error in exc_info.value.errors)


def test_required_wording_the_brief_never_uses_is_refused(tmp_path: Path) -> None:
    _bank(tmp_path, HEAD + '    required_elements: ["notwithstanding"]\n' + TWO_SOURCES)
    with pytest.raises(CurriculumError) as exc_info:
        parse_mediation_tasks(tmp_path)
    assert any("never use" in error for error in exc_info.value.errors)


# --- Resolving --------------------------------------------------------------


def test_a_mediation_key_resolves() -> None:
    task = service.mediation_tasks()[0]
    assert service.get_activity(service.mediation_key_for(task)) is task


def test_a_mediation_key_is_typed_as_a_mediation_task() -> None:
    task = service.mediation_tasks()[0]
    key = service.mediation_key_for(task)
    assert service.activity_type_for(key) == service.MEDIATION_TYPE


def test_an_unknown_mediation_key_is_rejected() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_activity("mediate:does.not.exist")


# --- Completing -------------------------------------------------------------


def _complete(session: Session, user_id: uuid.UUID, text: str = GOOD):
    task = service.mediation_by_key()[TASK]
    result = service.complete_mediation(
        session,
        user_id,
        activity_key=service.mediation_key_for(task),
        text=text,
    )
    session.commit()
    return result


def _events(session: Session) -> list[EvidenceEvent]:
    return list(session.execute(select(EvidenceEvent)).scalars())


def test_a_good_account_records_evidence(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id)

    assert result.evidence_recorded is True
    assert result.score == 1.0
    assert _events(db_session)[0].evidence_type is EvidenceType.CONTEXTUAL_PRODUCTION


def test_evidence_lands_on_a_mediation_skill(
    loaded_curriculum: Session, db_session: Session
) -> None:
    from apps.api.app.models.curriculum import SkillNode

    user = _user(db_session)
    _complete(db_session, user.id)

    node = db_session.get(SkillNode, _events(db_session)[0].skill_node_id)
    assert node is not None
    assert node.key.startswith("mediation.")


def test_mediation_is_weaker_evidence_than_writing(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The central claim of a mediation task — that the sources were conveyed
    faithfully — is precisely the one no countable check can reach. An anchor
    proves a figure was mentioned, not that it was reported correctly."""
    user = _user(db_session)
    _complete(db_session, user.id)

    event = _events(db_session)[0]
    assert event.confidence == MEDIATION_CONFIDENCE
    assert event.confidence < DETERMINISTIC_CONFIDENCE


def test_the_evidence_says_fidelity_was_not_assessed(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    _complete(db_session, user.id)

    assert _events(db_session)[0].metadata_json["fidelity_unassessed"] is True


def test_the_evidence_records_how_much_material_was_reconciled(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Two sources and four are not the same task, and a later reader should
    not have to guess which one this was."""
    user = _user(db_session)
    _complete(db_session, user.id)

    metadata = _events(db_session)[0].metadata_json
    assert metadata["source_count"] >= 2
    assert metadata["sources_used"] >= 1
    assert metadata["source_kinds"]


def test_a_copied_account_still_records_evidence_at_a_lower_score(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Copying is a real thing the learner did with language, and the
    deterministic pass caught it. Refusing to record would discard a
    measurement that worked."""
    task = service.mediation_by_key()[TASK]
    lifted = task.sources[0].text + " " + task.sources[1].text + " " + GOOD
    user = _user(db_session)
    result = _complete(db_session, user.id, lifted)

    assert result.analysis.was_copied
    assert result.evidence_recorded is True
    assert result.score < 1.0


def test_an_account_too_short_to_judge_records_nothing(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id, "They disagree.")

    assert result.evidence_recorded is False
    assert _events(db_session) == []


def test_the_attempt_is_kept_even_when_nothing_was_recorded(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    _complete(db_session, user.id, "They disagree.")

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.activity_type == service.MEDIATION_TYPE


def test_a_result_never_claims_the_sources_were_reported_correctly(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id)

    assert result.provisional is True
    assert "accurately" in result.explanation.lower()


# --- API --------------------------------------------------------------------


def test_opening_a_mediation_task_returns_every_source(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "mediator@example.com")
    task = service.mediation_by_key()[TASK]

    body = seeded_client.get(
        f"/api/v1/activities/{service.mediation_key_for(task)}", headers=headers
    ).json()

    assert body["activity_type"] == "mediation_task"
    assert body["brief"]
    assert len(body["sources"]) == len(task.sources)
    assert all(source["text"] for source in body["sources"])
    assert body["max_verbatim_words"] > 0


def test_opening_a_mediation_task_never_ships_its_anchors(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client, "mediator2@example.com")
    task = service.mediation_by_key()[TASK]

    raw = seeded_client.get(
        f"/api/v1/activities/{service.mediation_key_for(task)}", headers=headers
    ).text

    assert "anchors" not in raw
    for anchor in task.sources[0].anchors:
        # The anchor may legitimately appear inside the source text; what must
        # not appear is a field naming it as something to be matched.
        assert f'"{anchor}"' not in raw.replace(task.sources[0].text, "")


def test_completing_a_mediation_task_through_the_api(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "mediator3@example.com")
    task = service.mediation_by_key()[TASK]

    body = seeded_client.post(
        f"/api/v1/activities/{service.mediation_key_for(task)}/complete",
        headers=headers,
        json={"text": GOOD},
    ).json()

    assert body["activity_type"] == "mediation_task"
    assert body["evidence_recorded"] is True
    assert body["provisional"] is True
    assert body["unused_sources"] == []
    assert body["copied_from"] is None
    assert body["longest_copied_run"] >= 0


def test_the_api_names_the_source_that_was_copied(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "mediator4@example.com")
    task = service.mediation_by_key()[TASK]

    body = seeded_client.post(
        f"/api/v1/activities/{service.mediation_key_for(task)}/complete",
        headers=headers,
        json={"text": task.sources[0].text + " " + GOOD},
    ).json()

    assert body["copied_from"] == task.sources[0].key


def test_mediation_moves_a_mediation_skill(seeded_client: TestClient) -> None:
    """The point of the milestone: the mediation objectives had prerequisites
    pointing at them and nothing behind them."""
    headers = register(seeded_client, "mediator5@example.com")
    task = service.mediation_by_key()[TASK]

    before = seeded_client.get("/api/v1/profile", headers=headers).json()
    before_skill = next(s for s in before["skills"] if s["skill_key"] == task.skill_key)
    assert before_skill["evidence_count"] == 0

    seeded_client.post(
        f"/api/v1/activities/{service.mediation_key_for(task)}/complete",
        headers=headers,
        json={"text": GOOD},
    )

    after = seeded_client.get("/api/v1/profile", headers=headers).json()
    after_skill = next(s for s in after["skills"] if s["skill_key"] == task.skill_key)
    assert after_skill["evidence_count"] == 1


def _user(session: Session) -> User:
    user = User(email=f"mediate-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Mediator")
    session.add(user)
    session.commit()
    return user


def test_every_level_has_more_than_one_mediation_task(curriculum_dir: Path) -> None:
    """Once a learner knows where two sources disagree, finding it a second
    time is recall rather than mediation — so a repeated task measures less
    here than a repeated reading would."""
    from collections import Counter

    counts = Counter(task.cefr_level for task in parse_mediation_tasks(curriculum_dir))
    thin = [level.value for level, count in counts.items() if count < 2]
    assert not thin, f"only one mediation task at: {', '.join(sorted(thin))}"


def test_the_sources_in_a_task_disagree_about_something(curriculum_dir: Path) -> None:
    """Not checkable by machine, so this asserts the weaker thing that is:
    every task carries more than one source and every source contributes an
    anchor of its own. A learner reconciling two agreeing sources has
    summarised twice, and the interesting act is noticing the gap."""
    for task in parse_mediation_tasks(curriculum_dir):
        assert len(task.sources) >= 2, task.key
        for source in task.sources:
            assert source.anchors, f"{task.key}/{source.key}"
