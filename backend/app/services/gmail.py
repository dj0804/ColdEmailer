"""Gmail integration: installed-app OAuth + thin wrappers.

The OAuth client file (Desktop app) lives at ``settings.gmail_credentials_file``.
The user-authorization token is cached next to it as ``token.json`` and reused
across restarts. Both files are gitignored.

Only ``send_draft`` actually sends mail. The approval invariant that gates it
lives in the send service (Phase 3), not here.
"""

from __future__ import annotations

import base64
import os
from email.message import EmailMessage
from mimetypes import guess_type
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config import settings

# Scopes: read threads/messages, create drafts, send, and manage labels.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

SENT_LABEL = "GhostWatch/Sent"


def _token_path() -> Path:
    creds_path = Path(settings.gmail_credentials_file)
    return creds_path.parent / "token.json"


def get_credentials() -> Credentials:
    """Load cached credentials, refreshing or running the browser flow as needed."""
    token_path = _token_path()
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        creds_file = settings.gmail_credentials_file
        if not os.path.exists(creds_file):
            raise FileNotFoundError(
                f"Gmail OAuth client file not found at '{creds_file}'. "
                "Download the Desktop-app credentials JSON from Google Cloud."
            )
        flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json())
    return creds


def get_service():
    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def get_profile() -> dict:
    """Return the connected account's profile (email address, message counts)."""
    svc = get_service()
    return svc.users().getProfile(userId="me").execute()


def _build_message(
    to: str,
    subject: str,
    body: str,
    attachments: list[str] | None = None,
    thread_headers: dict | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if thread_headers:
        for k, v in thread_headers.items():
            msg[k] = v
    for path in attachments or []:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Attachment not found: {path}")
        ctype, _ = guess_type(str(p))
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name
        )
    return msg


def _encode(msg: EmailMessage) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(
    to: str,
    subject: str,
    body: str,
    attachments: list[str] | None = None,
    thread_id: str | None = None,
) -> dict:
    """Create a Gmail draft (does not send). Returns the draft resource."""
    svc = get_service()
    msg = _build_message(to, subject, body, attachments)
    message: dict = {"raw": _encode(msg)}
    if thread_id:
        message["threadId"] = thread_id
    return (
        svc.users()
        .drafts()
        .create(userId="me", body={"message": message})
        .execute()
    )


def send_draft(draft_id: str) -> dict:
    """Send an existing Gmail draft. Returns the sent message resource."""
    svc = get_service()
    return svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()


def send_message(
    to: str,
    subject: str,
    body: str,
    attachments: list[str] | None = None,
    thread_id: str | None = None,
) -> dict:
    """Compose and send in one step. Returns the sent message resource."""
    svc = get_service()
    msg = _build_message(to, subject, body, attachments)
    message: dict = {"raw": _encode(msg)}
    if thread_id:
        message["threadId"] = thread_id
    return svc.users().messages().send(userId="me", body=message).execute()


def list_thread_messages(thread_id: str) -> list[dict]:
    """Return full message resources for a thread (oldest first)."""
    svc = get_service()
    thread = (
        svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    )
    return thread.get("messages", [])


def _ensure_label(svc, name: str) -> str:
    existing = svc.users().labels().list(userId="me").execute().get("labels", [])
    for lbl in existing:
        if lbl["name"] == name:
            return lbl["id"]
    created = (
        svc.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def apply_label(message_id: str, label_name: str = SENT_LABEL) -> dict:
    """Apply a label (creating it if missing) to a message."""
    svc = get_service()
    label_id = _ensure_label(svc, label_name)
    return (
        svc.users()
        .messages()
        .modify(userId="me", id=message_id, body={"addLabelIds": [label_id]})
        .execute()
    )
