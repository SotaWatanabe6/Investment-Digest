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
    run_date: str,
    total_cost_so_far_usd: float,
) -> tuple[AgentCallResult, int]:
    """holdings_payload: one dict per holding with its full_name, period,
    hard_facts, subjective_info, discrepancy_analysis, macro_influence, and
    nothing_to_report flag — the composer's job is presentation, not
    re-analysis."""
    user_content = (
        f"Digest period: covering {run_date}\n"
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
