"""Capture real API payloads for the web app's contract tests.

Run with `make capture-fixtures` after changing any API response shape. The
committed fixture is what stops the hand-written TypeScript client from
silently drifting away from what FastAPI actually sends.

The output has to be **byte-identical for the same API**, because CI proves
the committed copy is current by re-capturing and diffing. Two things would
otherwise make that impossible, and both are handled below:

- Generated identifiers and timestamps differ on every run. They are
  replaced with stable placeholders that preserve *shape* and *identity*:
  two fields holding the same real UUID still hold the same placeholder,
  so a client asserting they match keeps working.
- Line endings differ by platform. Python's text mode would write CRLF on
  Windows and LF on Linux, so the newline is pinned explicitly.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUTPUT = REPO_ROOT / "apps" / "web" / "fixtures" / "api-payloads.json"

#: Anything matching these is regenerated per run and must be neutralised.
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STABLE_DATE = "2026-01-01"
STABLE_TIMESTAMP = "2026-01-01T00:00:00Z"

SAMPLE_WRITING = (
    "Last weekend I visited my sister in another city. We walked around the "
    "old town and then we had lunch near the river. I enjoyed it because the "
    "weather was warm and we had time to talk properly. On Sunday I travelled "
    "home and rested before work."
)


def main() -> int:
    # A throwaway database keeps the fixture reproducible and leaves no state.
    #
    # `ignore_cleanup_errors` is for Windows. POSIX happily unlinks a file that
    # is still open; Windows refuses, so an undisposed SQLite connection turns
    # tidying up a scratch directory into a crash *after* every payload has
    # already been captured. The engine is disposed below, which fixes the
    # cause; this makes the failure mode a leaked temp file rather than a lost
    # run either way.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workspace:
        import os

        os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{Path(workspace) / 'fixture.db'}"

        from fastapi.testclient import TestClient
        from sqlalchemy.orm import sessionmaker

        from apps.api.app import models  # noqa: F401
        from apps.api.app.curriculum import load_curriculum
        from apps.api.app.db.base import Base
        from apps.api.app.db.session import create_app_engine, get_session
        from apps.api.app.main import create_app
        from apps.api.app.settings import settings

        engine = create_app_engine(settings.database_url)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)

        with factory() as session:
            load_curriculum(session, settings.curriculum_dir, publish=True)
            session.commit()

        app = create_app()

        def override() -> Iterator[object]:
            session = factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_session] = override
        client = TestClient(app)

        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": "fixture@example.com",
                "password": "correct-horse-9",
                "display_name": "Fixture Learner",
                "daily_minutes": 40,
            },
        )
        headers = {"Authorization": f"Bearer {registered.json()['token']['access_token']}"}

        session_payload = client.post("/api/v1/diagnostics", headers=headers).json()
        session_id = session_payload["id"]
        next_payload = client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        submit_payload = client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": next_payload["item"]["key"], "response": "2"},
        ).json()
        # A written response is captured explicitly: it is the only item type
        # carrying `min_words`, `checks` and `provisional`, and the web app
        # renders all three.
        from apps.api.app.learning.items import ItemType
        from apps.api.app.services.diagnostics import item_bank

        writing_item = next(
            item for item in item_bank() if item.item_type is ItemType.WRITTEN_RESPONSE
        )
        writing_prompt_payload = writing_item.as_prompt()
        writing_submit_payload = client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": writing_item.key, "response": SAMPLE_WRITING},
        ).json()

        report_payload = client.post(
            f"/api/v1/diagnostics/{session_id}/complete", headers=headers
        ).json()
        profile_payload = client.get("/api/v1/profile", headers=headers).json()
        plan_payload = client.get("/api/v1/plans/today", headers=headers).json()

        # All four activity kinds, opened and completed. These are the
        # shapes the activity player switches on, so a rename in any of them
        # has to fail the web contract test rather than the browser.
        from apps.api.app.services import activities as activity_service

        reading = activity_service.library()[0]
        study = activity_service.study_units()[0]
        writing = activity_service.writing_tasks()[0]
        listening = activity_service.listening_clips()[0]

        reading_key = activity_service.activity_key_for(reading)
        study_key = activity_service.study_key_for(study)
        writing_key = activity_service.writing_key_for(writing)
        listening_key = activity_service.listening_key_for(listening)

        reading_activity_payload = client.get(
            f"/api/v1/activities/{reading_key}", headers=headers
        ).json()
        reading_result_payload = client.post(
            f"/api/v1/activities/{reading_key}/complete",
            headers=headers,
            json={"answers": {q.key: q.answer for q in reading.questions}},
        ).json()

        study_activity_payload = client.get(
            f"/api/v1/activities/{study_key}", headers=headers
        ).json()
        # One item deliberately wrong, so the fixture carries a `note`, a
        # failed outcome, and a non-empty `logged_features`.
        study_answers = {item.key: item.answer for item in study.items}
        study_answers[study.items[-1].key] = "not the answer"
        study_result_payload = client.post(
            f"/api/v1/activities/{study_key}/complete",
            headers=headers,
            json={"answers": study_answers, "hints_used": 1},
        ).json()

        writing_activity_payload = client.get(
            f"/api/v1/activities/{writing_key}", headers=headers
        ).json()
        writing_result_payload = client.post(
            f"/api/v1/activities/{writing_key}/complete",
            headers=headers,
            json={"text": SAMPLE_WRITING},
        ).json()

        listening_activity_payload = client.get(
            f"/api/v1/activities/{listening_key}", headers=headers
        ).json()
        # Answered by ear, so the fixture carries recorded listening evidence
        # rather than the transcript-was-read case.
        listening_result_payload = client.post(
            f"/api/v1/activities/{listening_key}/complete",
            headers=headers,
            json={
                "answers": {q.key: q.answer for q in listening.questions},
                "plays": 2,
                "used_transcript": False,
            },
        ).json()

        # Release every database handle before the scratch directory goes.
        # SQLAlchemy pools connections, so without this the SQLite file stays
        # open and Windows cannot delete it.
        client.close()
        engine.dispose()

    fixtures = {
        "register": _redact(registered.json()),
        "session": session_payload,
        "next": next_payload,
        "submit": submit_payload,
        "report": report_payload,
        "profile": profile_payload,
        "writing_prompt": writing_prompt_payload,
        "writing_submit": writing_submit_payload,
        "plan": plan_payload,
        "reading_activity": reading_activity_payload,
        "reading_result": reading_result_payload,
        "study_activity": study_activity_payload,
        "study_result": study_result_payload,
        "writing_activity": writing_activity_payload,
        "writing_result": writing_result_payload,
        "listening_activity": listening_activity_payload,
        "listening_result": listening_result_payload,
    }

    stable = _stabilise(fixtures, {})

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # `newline` is pinned: without it Python writes CRLF on Windows and LF
    # on Linux, and CI would diff every line of a file nobody had changed.
    OUTPUT.write_text(
        json.dumps(stable, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


def _placeholder(index: int) -> str:
    """A syntactically valid UUID that is obviously not a real one."""
    return f"00000000-0000-4000-8000-{index:012d}"


def _stabilise(value: Any, identities: dict[str, str]) -> Any:
    """Replace per-run values with deterministic stand-ins.

    `identities` maps each real UUID to its placeholder, so the same
    identifier appearing in three payloads still appears as one value in the
    fixture. Losing that would let a genuine bug — two fields that should
    agree drifting apart — pass unnoticed.

    Dictionaries are walked in key order so the numbering depends only on the
    content, never on the order FastAPI happened to serialise it in.
    """
    if isinstance(value, dict):
        return {key: _stabilise(value[key], identities) for key in sorted(value)}
    if isinstance(value, list):
        return [_stabilise(entry, identities) for entry in value]
    if not isinstance(value, str):
        return value

    if _TIMESTAMP.match(value):
        return STABLE_TIMESTAMP
    if _DATE.match(value):
        return STABLE_DATE

    def swap(match: re.Match[str]) -> str:
        found = match.group(0)
        if found not in identities:
            identities[found] = _placeholder(len(identities) + 1)
        return identities[found]

    # `sub`, not a full-string match: an identifier can be embedded in a key
    # or a URL as well as standing alone.
    return _UUID.sub(swap, value)


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Never commit a real token, even a throwaway one."""
    result = dict(payload)
    token = result.get("token")
    if isinstance(token, dict):
        result["token"] = {**token, "access_token": "redacted.for.fixtures"}
    return result


if __name__ == "__main__":
    raise SystemExit(main())
