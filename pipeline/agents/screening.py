"""
Screening agent — the token-usage optimization gate (Product Plan). Runs a
lightweight, cheap-model pass per holding to decide whether the expensive
extraction/validation/composition steps are worth running at all.
"""
from __future__ import annotations

import anthropic

from agents.common import call_structured
from db import Holding
from models import SCREENING_SCHEMA, AgentCallResult
from prompts.system_prompts import SAFETY_PREAMBLE, SCREENING_INSTRUCTION
from tools import edgar
from tools.finnhub_adapter import FinnhubProvider


def run_screening(
    client: anthropic.Anthropic,
    model: str,
    holding: Holding,
    since_date: str,
    news_provider: FinnhubProvider,
) -> tuple[AgentCallResult, int]:
    """Cheap raw-activity check (a small filings/news pull, not a full
    extraction pass) feeds the screening decision. Full extraction only
    runs downstream if this agent says yes."""
    filings = edgar.get_filings(holding.symbol, since_date)
    news = news_provider.get_news(holding.symbol, since_date, max_articles=3)

    user_content = (
        f"Holding: {holding.full_name} ({holding.symbol})\n"
        f"Since: {since_date}\n\n"
        f"Recent filings count: {len(filings)}\n"
        f"Recent news headlines: {[a.headline for a in news]}\n"
    )

    return call_structured(
        client=client,
        model=model,
        system_prompt=SAFETY_PREAMBLE + "\n" + SCREENING_INSTRUCTION,
        user_content=user_content,
        schema=SCREENING_SCHEMA,
        max_tokens=256,
    )
