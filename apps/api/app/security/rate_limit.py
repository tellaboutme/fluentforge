"""Limits on how often a password may be guessed.

`docs/PRIVACY_SAFETY.md` lists "rate limits on auth, generation, and uploads"
under the security baseline. None existed. `main.py` even mapped 429 to
`rate_limited`, so the code was reserved for a thing nothing could raise --
`/auth/login` verified passwords as fast as anyone cared to ask.

What this is, and what it is not
--------------------------------
**In-process.** One dictionary per worker. Behind N replicas the effective
limit is N times what is configured, and that is stated here rather than
implied away, because a limiter that quietly does a fraction of its job is
worse than none: it invites everyone to stop thinking about the problem. The
answer at deployment is a shared counter in Redis, which the compose stack
already provides; this is the floor, not the ceiling.

Even so, the floor matters. It turns unlimited online guessing into a few
attempts per minute per replica, which is the difference between a feasible
attack and an infeasible one.

**A sliding window, not a lockout.** Attempts expire. A counter that latches
until an administrator clears it hands an attacker a denial-of-service against
any account whose email address they know -- the defence becomes the attack.

**Keyed on both the caller and the account.** Limiting only by address lets
someone rotate through addresses against one account; limiting only by account
lets one address spray many accounts. Neither alone is a limit.

**Silent about who exists.** The limiter is consulted before the lookup and
behaves identically for an address nobody has ever registered, because a limit
that only bites on real accounts is an account-enumeration oracle.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..db.types import utcnow
from ..errors import AppError
from ..settings import settings


@dataclass(frozen=True)
class Limit:
    """How many attempts, over how long."""

    attempts: int
    window: timedelta


#: Failed password checks tolerated from one caller. Generous enough that a
#: person who has genuinely forgotten which of their passwords it is does not
#: meet it, tight enough that guessing is pointless.
LOGIN_LIMIT = Limit(attempts=10, window=timedelta(minutes=15))

#: Per account, across every caller. Lower, because ten people failing to log
#: into the *same* account in fifteen minutes is not a thing that happens by
#: accident.
LOGIN_PER_ACCOUNT = Limit(attempts=8, window=timedelta(minutes=15))

#: Registration, and the weakest of these on purpose.
#:
#: A tight per-address limit is hostile to the people this product is for. A
#: classroom, an office and a language school all share one address, and
#: thirty learners signing up together is a normal Tuesday -- while an
#: attacker with a proxy pool barely notices the limit at all. So the trade
#: goes the other way: high enough that a class of thirty works twice over,
#: low enough that one address cannot create thousands.
#:
#: What this bounds is the CPU cost. Each attempt runs a password hash, which
#: is deliberately expensive, so an unlimited endpoint is a way to burn the
#: server. Real abuse prevention needs email verification, which this product
#: does not have; pretending a small number here substitutes for that would be
#: the more comfortable mistake.
REGISTER_LIMIT = Limit(attempts=60, window=timedelta(hours=1))

#: Deleting an account re-checks the password, so it is a guessing surface
#: too, and an irreversible one. Tighter than login: nobody deletes their
#: account five times.
DELETE_LIMIT = Limit(attempts=5, window=timedelta(minutes=15))


class RateLimitedError(AppError):
    """Too many attempts.

    Carries `retry_after` so a client can say when rather than "try again
    later", which is the kind of message that makes people retry immediately.
    """

    code = "rate_limited"
    status_code_default = 429

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Too many attempts. Try again in {retry_after_seconds} seconds.",
            details={"retry_after_seconds": retry_after_seconds},
        )


class SlidingWindow:
    """Attempts per key over a rolling window.

    Thread-safe because the API runs sync endpoints in a worker thread pool,
    so two requests genuinely do touch this at once -- and a limiter with a
    race in it fails open, which is the direction that matters.
    """

    def __init__(self, limit: Limit) -> None:
        self._limit = limit
        self._hits: dict[str, deque[datetime]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, now: datetime | None = None) -> None:
        """Record an attempt against `key`, or refuse it.

        Raises:
            RateLimitedError: the window is full.
        """
        if not settings.auth_rate_limits_enabled:
            return

        moment = now or utcnow()
        with self._lock:
            window = self._hits.setdefault(key, deque())
            cutoff = moment - self._limit.window
            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= self._limit.attempts:
                # Time until the oldest attempt falls out of the window. At
                # least a second, because "try again in 0 seconds" reads as a
                # bug and invites an immediate retry.
                wait = (window[0] + self._limit.window - moment).total_seconds()
                raise RateLimitedError(max(1, int(wait) + 1))

            window.append(moment)

    def clear(self, key: str) -> None:
        """Forget this key's attempts.

        Called after a *successful* login: someone who signs in correctly ten
        times a day is not an attacker, and counting their successes towards a
        guessing limit would eventually lock out the product's most active
        users.
        """
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        """Drop everything. For tests and for a process that has just started."""
        with self._lock:
            self._hits.clear()


#: One instance per protected surface, created at import. Module-level because
#: the limit has to outlive a request; that is also exactly why this is
#: per-process and cannot be otherwise without a shared store.
login_by_caller = SlidingWindow(LOGIN_LIMIT)
login_by_account = SlidingWindow(LOGIN_PER_ACCOUNT)
register_by_caller = SlidingWindow(REGISTER_LIMIT)
delete_by_account = SlidingWindow(DELETE_LIMIT)


def reset_all() -> None:
    """Clear every limiter. Used between tests so they do not leak into each
    other, and never called by the application."""
    for window in (login_by_caller, login_by_account, register_by_caller, delete_by_account):
        window.reset()


__all__ = [
    "DELETE_LIMIT",
    "LOGIN_LIMIT",
    "LOGIN_PER_ACCOUNT",
    "REGISTER_LIMIT",
    "Limit",
    "RateLimitedError",
    "SlidingWindow",
    "delete_by_account",
    "login_by_account",
    "login_by_caller",
    "register_by_caller",
    "reset_all",
]
