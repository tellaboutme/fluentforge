"""Taking your data with you, and making it stop existing.

`docs/PRIVACY_SAFETY.md` commits to both and neither existed. See
`app/services/account_data.py` for the two decisions that shape them: the
export is the stored rows rather than a report, and deletion is real and
re-asks for the password.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from ..db.types import utcnow
from ..deps import CurrentUser, SessionDep
from ..services import account_data

router = APIRouter(prefix="/account", tags=["account"])


class DeleteAccountRequest(BaseModel):
    #: Re-authorisation. A session token is not enough to destroy a year of
    #: somebody's work: a leaked token should cost a learner their privacy,
    #: not everything they have done as well.
    password: str = Field(min_length=1)
    #: Typed by the learner, not a checkbox. A checkbox is one stray click;
    #: this cannot be reached by accident.
    confirm: str = Field(min_length=1)


#: What `confirm` has to be. Deliberately a word rather than the email
#: address: an email is on screen and can be copied without reading anything.
CONFIRM_PHRASE = "delete my account"


@router.get("/export")
def export_account(user: CurrentUser, session: SessionDep) -> Response:
    """Everything stored about this learner, as a JSON file.

    Returned as a download rather than a JSON body so a learner gets a file
    they can keep, rather than a wall of text in a browser tab. The filename
    carries the date, because the point of an export is having a copy from a
    particular moment.
    """
    payload = account_data.export_account(session, user)
    stamp = utcnow().date().isoformat()

    return Response(
        content=_dump(payload),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="fluentforge-export-{stamp}.json"',
            # Never cached anywhere. This is the most sensitive response the
            # product produces and a shared or proxy cache holding it would
            # be a straightforward leak.
            "Cache-Control": "no-store",
        },
    )


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: DeleteAccountRequest, user: CurrentUser, session: SessionDep
) -> Response:
    """Delete the account and everything attached to it. Irreversible.

    `POST` rather than `DELETE` because it carries a body, and a request body
    on `DELETE` is poorly supported by intermediaries -- an authorisation
    silently dropped in transit is the last thing this endpoint needs.
    """
    if payload.confirm.strip().lower() != CONFIRM_PHRASE:
        raise account_data.NotConfirmedError(CONFIRM_PHRASE)

    account_data.delete_account(session, user, password=payload.password)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _dump(payload: dict[str, object]) -> str:
    import json

    # Indented because a person may well open this in a text editor, and
    # `ensure_ascii=False` because a learner's own writing is not ASCII.
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
