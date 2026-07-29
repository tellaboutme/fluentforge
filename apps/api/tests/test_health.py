"""Liveness and readiness behaviour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.app.settings import settings
from apps.api.tests.helpers import CURRICULUM_VERSION


def test_health_is_ok_without_database(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fluentforge-api"}


def test_health_returns_request_id_header(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["X-Request-ID"]


def test_health_echoes_supplied_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"


def test_ready_is_degraded_before_curriculum_is_loaded(client: TestClient) -> None:
    body = client.get("/ready").json()
    assert body["status"] == "degraded"
    assert body["database"] == "ok"
    assert body["curriculum_version"] is None


def test_ready_is_ok_once_curriculum_is_loaded(seeded_client: TestClient) -> None:
    body = seeded_client.get("/ready").json()
    assert body["status"] == "ok"
    assert body["curriculum_version"] == CURRICULUM_VERSION
    assert body["curriculum_versions_loaded"] == 1


def test_ready_reports_disabled_providers_by_default(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Core learning must work without a paid AI provider.

    The defaults are pinned rather than read from the ambient environment.
    Without this the test asserts whatever `.env` the developer happens to
    have, so following `docs/TESTING.md` and configuring a real provider
    turned the suite red -- a green build broken by a file that is not in
    this repository, which is the most confusing failure available.

    The claim being made is about the shipped defaults, and
    `test_settings.py` proves those separately.
    """
    monkeypatch.setattr(settings, "ai_provider", "disabled")
    monkeypatch.setattr(settings, "speech_provider", "disabled")

    body = seeded_client.get("/ready").json()

    assert body["ai_provider"] == "disabled"
    assert body["speech_provider"] == "disabled"
