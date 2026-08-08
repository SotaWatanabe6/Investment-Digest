"""
send_email tool — the one write/action tool any agent can call (PRD Section
6, AI Product Decisions Stage 5). The max-1-send-per-covered-period limit
is enforced here, in code, at the tool boundary itself — not just via a
prompt instruction — so a misbehaving or looping agent cannot spam the
inbox regardless of how it was prompted.
"""
from __future__ import annotations

import httpx

from db import get_sent_run_count_for_period, today_str


class SendLimitExceededError(RuntimeError):
    """Raised when the send limit for this covered period has already been
    reached. This is access control, not a soft warning — the caller must
    not retry."""


def send_email(
    conn,
    resend_api_key: str,
    to_email: str,
    from_email: str,
    subject: str,
    html_body: str,
    period_date: str | None = None,
) -> None:
    # period_date defaults to today, so a normal scheduled run still gets
    # exactly "max 1 send per real day." A backfill run passes the specific
    # historical day it's generating a digest for, so it isn't blocked by
    # sends already made for other days within the same real day.
    period = period_date or today_str()
    if get_sent_run_count_for_period(conn, period) >= 1:
        raise SendLimitExceededError(
            f"Send limit (1) already reached for period {period} — refusing to send a duplicate digest."
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
