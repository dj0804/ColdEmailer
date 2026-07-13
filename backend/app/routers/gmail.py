"""Gmail connection status + a guarded self-test draft (Phase 1 verification)."""

from fastapi import APIRouter, HTTPException

from ..services import gmail

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


@router.get("/status")
def status():
    try:
        profile = gmail.get_profile()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - surface auth issues to the caller
        raise HTTPException(
            status_code=401,
            detail=f"Not authorized. Run authorize_gmail.py. ({e})",
        )
    return {
        "connected": True,
        "email": profile.get("emailAddress"),
        "messages_total": profile.get("messagesTotal"),
    }


@router.post("/test-draft")
def test_draft():
    """Create a draft (NOT sent) in the connected account to prove write access."""
    profile = gmail.get_profile()
    me = profile.get("emailAddress")
    draft = gmail.create_draft(
        to=me,
        subject="[Applier] Test draft — Phase 1",
        body="This is a test draft created by Applier. It was not sent.",
    )
    return {"draft_id": draft.get("id"), "created_in": me}
