"""The learner's own error log.

`GET /profile/errors` sat in the contract from the beginning and
unimplemented. The reflection screen shows the top three; this is the whole
list, because a learner should be able to see everything the system believes
about their mistakes rather than the three it chose to mention.

Most of these tests are about `no_remedy_reason`. An error with no practice
behind it is common and not always the same kind of gap, and collapsing the
kinds would make one of them look like a backlog item when it is not.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.app.routers.errors import NEEDS_SPEECH, NO_FEATURE, NOT_WRITTEN
from apps.api.app.services.errors_log import record_error
from apps.api.tests.helpers import register


def _log(client: TestClient, headers: dict[str, str]) -> dict:
    return client.get("/api/v1/profile/errors", headers=headers).json()


def test_a_new_learner_has_an_empty_log(seeded_client: TestClient) -> None:
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    body = _log(seeded_client, headers)

    assert body["items"] == []
    assert body["without_remedy"] == 0


def test_an_error_appears_with_a_rendered_label(seeded_client: TestClient, session_factory) -> None:
    """Clients must never show the raw code: it is a machine identifier and
    reads as one."""
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "grammar.tense.past_simple_form")

    item = _log(seeded_client, headers)["items"][0]
    assert item["code"] == "grammar.tense.past_simple_form"
    assert item["label"] and item["label"] != item["code"]


def test_an_error_with_a_study_unit_is_openable(seeded_client: TestClient, session_factory) -> None:
    """This is what turns a list of grievances into something a learner can
    act on."""
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "grammar.tense.past_simple_form")

    item = _log(seeded_client, headers)["items"][0]
    assert item["remedy_key"] is not None
    assert item["remedy_key"].startswith("study:")
    assert item["remedy_title"]
    assert item["no_remedy_reason"] is None


def test_a_legacy_code_can_have_no_remedy_by_construction(
    seeded_client: TestClient, session_factory
) -> None:
    """`item.<skill>` names a skill, not a practisable feature. Nothing could
    honestly claim to fix "something in grammar.connected_time_modality"."""
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "item.grammar.connected_time_modality")

    item = _log(seeded_client, headers)["items"][0]
    assert item["remedy_key"] is None
    assert item["no_remedy_reason"] == NO_FEATURE


def test_a_pronunciation_error_is_marked_as_needing_speech(
    seeded_client: TestClient, session_factory
) -> None:
    """The distinction this endpoint exists to keep. A study unit is read and
    typed; it cannot teach a sound contrast, so this is not a backlog item —
    it needs an audio pipeline the product does not have."""
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "pronunciation.segment.contrast")

    item = _log(seeded_client, headers)["items"][0]
    assert item["remedy_key"] is None
    assert item["no_remedy_reason"] == NEEDS_SPEECH


def test_the_three_kinds_of_gap_are_distinguishable() -> None:
    """Collapsing them would suggest a missing audio pipeline is a backlog
    item, and that a legacy code is merely unwritten."""
    assert len({NO_FEATURE, NEEDS_SPEECH, NOT_WRITTEN}) == 3


def test_errors_that_block_meaning_rank_first(seeded_client: TestClient, session_factory) -> None:
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "mechanics.spelling.common", blocks=False)
    _record(seeded_client, session_factory, headers, "grammar.word_order.question", blocks=True)

    items = _log(seeded_client, headers)["items"]
    assert items[0]["blocks_meaning"] is True


def test_a_single_slip_is_recorded_but_not_yet_drilled(
    seeded_client: TestClient, session_factory
) -> None:
    """`CLAUDE.md`: a recurring error earns practice, a one-off does not.
    Surfaced so a learner can see the difference rather than wondering why
    something in their list is not in their plan."""
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "mechanics.spelling.common", blocks=False)

    item = _log(seeded_client, headers)["items"][0]
    assert item["occurrences"] == 1
    assert item["scheduled"] is False


def test_the_count_without_a_remedy_is_reported(seeded_client: TestClient, session_factory) -> None:
    """A learner looking at a list of unanswerable errors deserves the count
    rather than having to work it out."""
    headers = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, headers, "pronunciation.stress.word")
    _record(seeded_client, session_factory, headers, "grammar.tense.past_simple_form")

    body = _log(seeded_client, headers)
    assert body["without_remedy"] == 1
    assert len(body["items"]) == 2


def test_the_log_needs_a_learner(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/profile/errors").status_code == 401


def test_one_learner_never_sees_another_s_errors(
    seeded_client: TestClient, session_factory
) -> None:
    mine = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    theirs = register(seeded_client, f"err-{uuid.uuid4().hex[:6]}@example.com")
    _record(seeded_client, session_factory, theirs, "grammar.tense.past_simple_form")

    assert _log(seeded_client, mine)["items"] == []


def _record(
    client: TestClient,
    session_factory,
    headers: dict[str, str],
    code: str,
    *,
    blocks: bool = True,
) -> None:
    """Log one error for whoever these headers belong to."""
    from sqlalchemy import select

    from apps.api.app.models.identity import User

    me = client.get("/api/v1/auth/me", headers=headers).json()
    session: Session = session_factory()
    try:
        user = session.execute(select(User).where(User.email == me["email"])).scalar_one()
        record_error(
            session,
            user.id,
            taxonomy_code=code,
            description=f"Difficulty with {code}",
            blocks_meaning=blocks,
        )
        session.commit()
    finally:
        session.close()
