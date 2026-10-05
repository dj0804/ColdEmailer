"""Classification of a single inbound reply.

Two machine-generated kinds are recognised by rules first, without the LLM:
``bounce`` (delivery failure) and ``auto_reply`` (autoresponder / "we received
your email"). They are unambiguous from headers and boilerplate, and handling
them without the LLM means a bounce is still caught when the OpenAI account is
out of credit. Everything else goes to the LLM, which returns one of
recruiter_reply | interview_request | rejection | other.
"""

from __future__ import annotations

import json
import re

from ..config import settings
from . import llm

LABELS = {"recruiter_reply", "interview_request", "rejection", "other"}

SYSTEM = """You classify a single email reply that someone sent in response to a \
student's cold internship-outreach email. Choose EXACTLY ONE label:

- "interview_request": the sender wants to move forward — proposes a call/interview, \
asks for the candidate's availability, shares a scheduling link, or asks them to \
book a slot.
- "recruiter_reply": a genuine human reply that engages but is not (yet) scheduling \
an interview — asks for more info, forwards internally, points to a job posting, \
asks the candidate to apply/send details, or gives an encouraging "we'll keep you \
in mind".
- "rejection": an explicit decline — "we're not hiring interns", "not a fit", \
"we've filled the role", "pursuing other candidates", or a clear no.
- "other": anything that isn't a real personal reply — automated out-of-office/\
vacation autoreplies, delivery-failure/bounce notices, unrelated mail, newsletters, \
spam, or read receipts.

CRITICAL — do not infer a rejection that wasn't stated. A sender who replies \
with a CONDITION or REQUIREMENT rather than a refusal is engaging, so that is \
"recruiter_reply", NOT "rejection". Examples that are recruiter_reply:
- "Our internships are in person." (a constraint the candidate may well meet)
- "We only take interns for 6-month durations."
- "Hiring runs through campus placements / our careers portal."
- "We consider interns who can start in January."
- "Send your CV to X" / "speak to Y instead".
Classify "rejection" ONLY when the sender actually declines. If you are weighing \
rejection against recruiter_reply and the message contains no explicit "no", \
choose recruiter_reply — a real opportunity wrongly closed costs far more than \
one kept open.

Return ONLY JSON: {"label": "<one of the four>", "reason": "<short reason>"}."""


_BOUNCE_SENDER = re.compile(r"mailer-daemon|postmaster|mail delivery (subsystem|system)", re.I)
_BOUNCE_BODY = re.compile(
    r"address not found|delivery has failed|couldn't be delivered|could not be delivered"
    r"|undeliverable|permanent fatal errors|message blocked|recipient address rejected"
    r"|\b55[0-4] ?5\.\d\.\d",
    re.I,
)
_AUTO_SENDER = re.compile(r"no-?reply|do-?not-?reply|donotreply", re.I)
_AUTO_BODY = re.compile(
    r"this is an automat|auto-?generated|automatic reply|out of (the )?office"
    r"|(we('ve| have)|has been) received your (message|email|application)"
    r"|someone will review your email|unable to (answer|respond to) every",
    re.I,
)


def rule_label(sender: str, body: str, headers: dict[str, str]) -> str | None:
    """'bounce' | 'auto_reply' for machine-generated mail, else None (ask the LLM).

    ``headers`` holds the lower-cased names Auto-Submitted, X-Autoreply,
    X-Autorespond and Precedence (missing ones may be absent or empty).
    """
    if _BOUNCE_SENDER.search(sender) or _BOUNCE_BODY.search(body[:1500]):
        return "bounce"
    auto_submitted = headers.get("auto-submitted", "").lower()
    if (
        (auto_submitted and auto_submitted != "no")
        or headers.get("x-autoreply") or headers.get("x-autorespond")
        or headers.get("precedence", "").lower() in ("auto_reply", "bulk", "junk")
        or _AUTO_SENDER.search(sender)
        or _AUTO_BODY.search(body[:1500])
    ):
        return "auto_reply"
    return None


def classify_reply(sender: str, body: str) -> dict:
    user = f"FROM: {sender}\n\nREPLY BODY:\n{body}\n\nClassify this reply."
    raw = llm.chat(
        model=settings.openai_model,  # cheap/fast (gpt-4o)
        system=SYSTEM,
        user=user,
        max_tokens=200,
        temperature=0,
        json_mode=True,
    )
    try:
        data = json.loads(raw)
        label = data.get("label", "other")
        reason = data.get("reason", "")
    except (json.JSONDecodeError, AttributeError):
        label, reason = "other", "unparseable classifier output"
    if label not in LABELS:
        label = "other"
    return {"label": label, "reason": reason}
