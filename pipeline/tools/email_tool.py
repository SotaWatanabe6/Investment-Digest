"""
send_email tool — the one write/action tool any agent can call (PRD Section
6, AI Product Decisions Stage 5). The max-1-send-per-day limit is enforced
here, in code, at the tool boundary itself — not just via a prompt
instruction — so a misbehaving or looping agent cannot spam the inbox
regardless of how it was prompted.
"""
from __future__ import annotations

import httpx

from db import get_sent_run_count_today


class SendLimitExceededError(RuntimeError):
    """Raised when the daily send limit has already been reached. This is
    access control, not a soft warning — the caller must not retry."""


def send_email(conn, resend_api_key: str, to_email: str, from_email: str, subject: str, html_body: str) -> None:
    if get_sent_run_count_today(conn) >= 1:
        raise SendLimitExceededError(
            "Daily send limit (1) already reached — refusing to send a second digest today."
        )

    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {resend_api_key}"},
        json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
