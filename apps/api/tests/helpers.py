"""Test helpers shared across modules.

Kept out of `conftest.py` so test modules can import them normally.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

VALID_PASSWORD = "correct-horse-9"

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Read from source rather than hardcoded: bumping the curriculum version is a
#: normal authoring action and must not require editing tests.
CURRICULUM_VERSION: str = yaml.safe_load(
    (REPO_ROOT / "curriculum" / "framework.yml").read_text(encoding="utf-8")
)["version"]


def register(client: TestClient, email: str = "learner@example.com") -> dict[str, str]:
    """Register an account and return an Authorization header."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": VALID_PASSWORD,
            "display_name": "Test Learner",
            "daily_minutes": 40,
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
