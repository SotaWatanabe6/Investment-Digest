"""
Composer agent — assembles the final digest email from every holding's
structured output, computes the total run cost, and calls the send_email
tool (its one write/action capability, safeguarded in tools/email_tool.py).
"""
from __future__ import annotations

import anthropic

from agents.common import call_structured
from models import COMPOSER_SCHEMA, AgentCallResult
from prompts.system_prompts import COMPOSER_INSTRUCTION, SAFETY_PREAMBLE


def compose_digest(
    client: anthropic.Anthropic,
    model: str,
    holdings_payload: list[dict],
    period_start: str,
    period_end: str,
    total_cost_so_far_usd: float,
) -> tuple[AgentCallResult, int]:
    """holdings_payload: one dict per holding with its full_name, period,
    hard_facts, subjective_info, discrepancy_analysis, macro_influence, and
    nothing_to_report flag — the composer's job is presentation, not
    re-analysis.

    period_start/period_end are both passed explicitly (rather than a
    single date) so the composer never has to guess the other end of the
    "covering X to Y" range — previously, given only one date, it would
    infer a plausible-looking (but wrong) start date on its own, e.g.
    rendering "covering 2026-08-01 to 2026-08-02" for a single-day backfill
    that actually only covered 2026-08-02.
    """
    period_label = period_start if period_start == period_end else f"{period_start} to {period_end}"
    user_content = (
        f"Digest period: covering {period_label}\n"
        f"Use exactly this period in the header line for every holding — "
        f"do not infer or adjust the start or end date yourself.\n"
        f"Running LLM/API cost so far this run (composer's own cost will add "
        f"a small amount more, include this figure as an estimate in the footer): "
        f"${total_cost_so_far_usd:.4f}\n\n"
        f"Holdings data:\n{holdings_payload}\n"
    )

    return call_structured(
        client=client,
        model=model,
        system_prompt=SAFETY_PREAMBLE + "\n" + COMPOSER_INSTRUCTION,
        user_content=user_content,
        schema=COMPOSER_SCHEMA,
        max_tokens=8192,
    )
