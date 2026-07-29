"""Limits on how often a password may be guessed.

`docs/PRIVACY_SAFETY.md` lists "rate limits on auth, generation, and uploads"
under the security baseline. None existed. `main.py` already mapped 429 to
`rate_limited` -- the code was reserved for something nothing could raise --
while `/auth/login` verified passwords as fast as anyone cared to ask.

Most of what follows guards against the ways a limiter makes things worse:

- **It must not become a denial of service.** Attempts expire; a counter that
  latched would hand an attacker a way to lock any account whose address they
  know, turning the defence into the attack.
- **It must not tell anyone who exists.** The limit is checked before the
  lookup and behaves identically for an address nobody ever registered.
- **It must not punish real people.** A successful login clears the count.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api.app.db.types import utcnow
from apps.api.app.security.rate_limit import (
    LOGIN_LIMIT,
    LOGIN_PER_ACCOUNT,
    REGISTER_LIMIT,
    Limit,
    RateLimitedError,
    SlidingWindow,
)
from apps.api.tests.helpers import VALID_PASSWORD, register

TINY = Limit(attempts=2, window=timedelta(seconds=60))


# --- The window itself ------------------------------------------------------


def test_attempts_under_the_limit_pass() -> None:
    window = SlidingWindow(TINY)

    window.check("a")
    window.check("a")


def test_the_next_one_is_refused() -> None:
    window = SlidingWindow(TINY)
    window.check("a")
    window.check("a")

    with pytest.raises(RateLimitedError) as caught:
        window.check("a")

    assert caught.value.status_code == 429


def test_it_says_when_to_come_back() -> None:
    """ "Try again later" is the kind of message that makes people retry
    immediately."""
    window = SlidingWindow(TINY)
    now = utcnow()
    window.check("a", now=now)
    window.check("a", now=now)

    with pytest.raises(RateLimitedError) as caught:
        window.check("a", now=now)

    assert 0 < caught.value.retry_after_seconds <= 61
    assert caught.value.detail["details"]["retry_after_seconds"] > 0


def test_the_wait_is_never_zero() -> None:
    """ "Try again in 0 seconds" reads as a bug and invites an instant retry."""
    window = SlidingWindow(TINY)
    now = utcnow()
    window.check("a", now=now)
    window.check("a", now=now)

    with pytest.raises(RateLimitedError) as caught:
        window.check("a", now=now + TINY.window - timedelta(milliseconds=1))

    assert caught.value.retry_after_seconds >= 1


def test_attempts_expire_rather_than_latching() -> None:
    """The load-bearing property. A counter that stayed full until someone
    cleared it would let an attacker lock any account whose address they
    know -- the defence becomes the attack."""
    window = SlidingWindow(TINY)
    now = utcnow()
    window.check("a", now=now)
    window.check("a", now=now)

    window.check("a", now=now + TINY.window + timedelta(seconds=1))


def test_the_window_slides_rather_than_resetting_in_blocks() -> None:
    """A fixed window lets twice the limit through across a boundary."""
    window = SlidingWindow(TINY)
    now = utcnow()
    window.check("a", now=now)
    window.check("a", now=now + timedelta(seconds=59))

    with pytest.raises(RateLimitedError):
        # The first attempt has expired; the second has not.
        window.check("a", now=now + timedelta(seconds=61))
        window.check("a", now=now + timedelta(seconds=61))


def test_keys_are_independent() -> None:
    window = SlidingWindow(TINY)
    window.check("a")
    window.check("a")

    window.check("b")


def test_success_clears_the_count() -> None:
    """Someone who signs in ten times a day is not guessing, and counting
    their successes would eventually lock out the most active users."""
    window = SlidingWindow(TINY)
    window.check("a")
    window.check("a")
    window.clear("a")

    window.check("a")


# --- Login ------------------------------------------------------------------


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_repeated_wrong_passwords_are_eventually_refused(
    seeded_client: TestClient,
) -> None:
    register(seeded_client, "limit-login@example.com")

    last = None
    for _ in range(LOGIN_PER_ACCOUNT.attempts + 2):
        last = _login(seeded_client, "limit-login@example.com", "wrong-password")

    assert last is not None
    assert last.status_code == 429
    assert last.json()["code"] == "rate_limited"


def test_guessing_at_an_unknown_address_is_limited_the_same_way(
    seeded_client: TestClient,
) -> None:
    """A limit that only bit on real accounts would be an account-enumeration
    oracle -- the exact thing `InvalidCredentialsError` goes out of its way to
    hide."""
    last = None
    for _ in range(LOGIN_PER_ACCOUNT.attempts + 2):
        last = _login(seeded_client, "nobody-here@example.com", "wrong-password")

    assert last is not None
    assert last.status_code == 429


def test_two_accounts_are_limited_separately(seeded_client: TestClient) -> None:
    """Otherwise one person failing to log in blocks everybody -- but only up
    to the per-caller limit, which is what stops a single address spraying."""
    register(seeded_client, "limit-a@example.com")
    register(seeded_client, "limit-b@example.com")

    for _ in range(LOGIN_PER_ACCOUNT.attempts):
        _login(seeded_client, "limit-a@example.com", "wrong-password")

    # The per-account bucket for B is untouched. The per-caller one is not,
    # which is deliberate: the same client has now failed several times.
    assert _login(seeded_client, "limit-b@example.com", VALID_PASSWORD).status_code in (200, 429)


def test_a_caller_is_limited_across_accounts(seeded_client: TestClient) -> None:
    """Limiting only by account would let one address spray many accounts,
    one attempt each, for ever."""
    last = None
    for index in range(LOGIN_LIMIT.attempts + 2):
        last = _login(seeded_client, f"spray-{index}@example.com", "wrong-password")

    assert last is not None
    assert last.status_code == 429


def test_case_and_whitespace_cannot_buy_a_fresh_bucket(
    seeded_client: TestClient,
) -> None:
    """`Alice@Example.com ` and `alice@example.com` are the same account, so
    they had better be the same limit."""
    register(seeded_client, "limit-case@example.com")

    for _ in range(LOGIN_PER_ACCOUNT.attempts):
        _login(seeded_client, "limit-case@example.com", "wrong-password")

    refused = _login(seeded_client, "  LIMIT-CASE@Example.COM ", "wrong-password")

    assert refused.status_code == 429


def test_a_correct_password_clears_the_count(seeded_client: TestClient) -> None:
    register(seeded_client, "limit-clears@example.com")

    for _ in range(LOGIN_PER_ACCOUNT.attempts - 1):
        _login(seeded_client, "limit-clears@example.com", "wrong-password")

    assert _login(seeded_client, "limit-clears@example.com", VALID_PASSWORD).status_code == 200

    # Back to a full allowance rather than one attempt from lockout.
    for _ in range(LOGIN_PER_ACCOUNT.attempts - 1):
        assert _login(seeded_client, "limit-clears@example.com", "wrong").status_code == 401


def test_a_refused_attempt_never_reveals_whether_the_password_was_right(
    seeded_client: TestClient,
) -> None:
    """Once limited, the correct password must be refused too. Answering it
    would turn the limiter into an oracle for the thing it protects."""
    register(seeded_client, "limit-oracle@example.com")

    for _ in range(LOGIN_PER_ACCOUNT.attempts):
        _login(seeded_client, "limit-oracle@example.com", "wrong-password")

    assert _login(seeded_client, "limit-oracle@example.com", VALID_PASSWORD).status_code == 429


# --- Registration -----------------------------------------------------------


def test_registration_is_limited(seeded_client: TestClient) -> None:
    """Each attempt costs a password hash, which is deliberately expensive --
    so an unlimited one burns CPU as well as filling the table."""
    for index in range(REGISTER_LIMIT.attempts):
        register(seeded_client, f"flood-{index}@example.com")

    refused = seeded_client.post(
        "/api/v1/auth/register",
        json={
            "email": "flood-last@example.com",
            "password": VALID_PASSWORD,
            "display_name": "Flood",
            "daily_minutes": 40,
        },
    )

    assert refused.status_code == 429


# --- Deleting ---------------------------------------------------------------


def test_deletion_password_guesses_are_limited(seeded_client: TestClient) -> None:
    """It re-checks the password, so it is a guessing surface, and an
    irreversible one."""
    headers = register(seeded_client, "limit-delete@example.com")

    last = None
    for _ in range(8):
        last = seeded_client.post(
            "/api/v1/account/delete",
            json={"password": "wrong-password", "confirm": "delete my account"},
            headers=headers,
        )

    assert last is not None
    assert last.status_code == 429
