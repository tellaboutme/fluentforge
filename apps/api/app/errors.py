"""Application errors with stable machine codes.

Every failure the client can act on gets a code that never changes and a
message safe to show a learner. Messages must not leak secrets, hashes, or
whether a given email is registered.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


class AppError(HTTPException):
    code: str = "internal_error"
    status_code_default: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            status_code=self.status_code_default,
            detail={"code": self.code, "message": message, "details": details or {}},
        )


class InvalidCredentialsError(AppError):
    code = "invalid_credentials"
    status_code_default = status.HTTP_401_UNAUTHORIZED

    def __init__(self) -> None:
        # Deliberately identical for unknown email and wrong password.
        super().__init__("Email or password is incorrect.")


class NotAuthenticatedError(AppError):
    code = "not_authenticated"
    status_code_default = status.HTTP_401_UNAUTHORIZED

    def __init__(self, message: str = "Sign in to continue.") -> None:
        super().__init__(message)


class AccountInactiveError(AppError):
    code = "account_inactive"
    status_code_default = status.HTTP_403_FORBIDDEN

    def __init__(self) -> None:
        super().__init__("This account is not active.")


class EmailAlreadyRegisteredError(AppError):
    code = "email_already_registered"
    status_code_default = status.HTTP_409_CONFLICT

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class WeakPasswordError(AppError):
    code = "weak_password"
    status_code_default = 422


class ProfileNotFoundError(AppError):
    code = "profile_not_found"
    status_code_default = status.HTTP_404_NOT_FOUND

    def __init__(self) -> None:
        super().__init__("No learner profile exists for this account yet.")


class SessionNotFoundError(AppError):
    code = "session_not_found"
    status_code_default = status.HTTP_404_NOT_FOUND

    def __init__(self) -> None:
        # Also returned for another learner's session: existence is not leaked.
        super().__init__("That session does not exist.")


class DiagnosticCompleteError(AppError):
    code = "diagnostic_complete"
    status_code_default = status.HTTP_409_CONFLICT

    def __init__(self) -> None:
        super().__init__("This diagnostic is already finished.")


class ItemNotFoundError(AppError):
    code = "item_not_found"
    status_code_default = status.HTTP_404_NOT_FOUND

    def __init__(self, item_key: str) -> None:
        super().__init__("That item is not part of the diagnostic.", details={"key": item_key})


class ActivityNotFoundError(AppError):
    code = "activity_not_found"
    status_code_default = status.HTTP_404_NOT_FOUND

    def __init__(self, activity_key: str) -> None:
        super().__init__("That activity is not available.", details={"activity_key": activity_key})


class ActivityPayloadError(AppError):
    """The submission does not match what this kind of activity expects.

    A reading or study task is completed with `answers`; a writing task is
    completed with `text`. Sending the wrong one is a client bug, and saying
    which field was missing is what makes it a fixable one.
    """

    code = "activity_payload_mismatch"
    status_code_default = 422

    def __init__(self, activity_key: str, expected_field: str) -> None:
        super().__init__(
            f"This activity is completed by sending '{expected_field}'.",
            details={"activity_key": activity_key, "expected_field": expected_field},
        )


class ReviewNotFoundError(AppError):
    code = "review_not_found"
    status_code_default = status.HTTP_404_NOT_FOUND

    def __init__(self) -> None:
        super().__init__("That review card does not exist.")


class PlanNotFoundError(AppError):
    code = "plan_not_found"
    status_code_default = status.HTTP_404_NOT_FOUND

    def __init__(self) -> None:
        super().__init__("That plan does not exist.")


class CurriculumNotLoadedError(AppError):
    code = "curriculum_not_loaded"
    status_code_default = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("No curriculum version is loaded. Run `make load-curriculum` to seed it.")
