"""
Validation/cross-reference agent — compares subjective-source claims
against each other and against hard facts to produce the discrepancy/
agreement analysis. Agent-directed: may request one additional round of
context if the initial data is too thin to analyze meaningfully (AI
Product Decisions Stage 1/5).
"""
from __future__ import annotations

import anthropic

from agents.common import call_structured
from db import Holding, get_recent_daily_summaries
from models import VALIDATION_SCHEMA, AgentCallResult
from prompts.system_prompts import SAFETY_PREAMBLE, VALIDATION_INSTRUCTION


def run_validation(
    conn,
    client: anthropic.Anthropic,
    model: str,
    holding: Holding,
    hard_facts: list,
    subjective_info: list,
    extra_context: str | None = None,
) -> tuple[AgentCallResult, int]:
    history = get_recent_daily_summaries(conn, holding.id, days=7)
    history_block = (
        "\n".join(f"- {day}" for day in history) if history else "No prior history available."
    )

    user_content = (
        f"Holding: {holding.full_name} ({holding.symbol})\n\n"
        f"Hard facts (from filings):\n{hard_facts}\n\n"
        f"Subjective info (from news):\n{subjective_info}\n\n"
        f"Prior 7-day compact summaries (context only, not evidence for today):\n{history_block}\n"
    )
    if extra_context:
        user_content += f"\nAdditional requested context:\n{extra_context}\n"

    return call_structured(
        client=client,
        model=model,
        system_prompt=SAFETY_PREAMBLE + "\n" + VALIDATION_INSTRUCTION,
        user_content=user_content,
        schema=VALIDATION_SCHEMA,
    )
