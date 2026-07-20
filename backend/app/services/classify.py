"""LLM classification of a single inbound reply.

Pure LLM call (gpt-4o) per the spec — no rule-based pre-filter. Returns one of:
recruiter_reply | interview_request | rejection | other.
"""

from __future__ import annotations

import json

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
