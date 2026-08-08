"""
Extraction agents — one per distinct source (filings, news, macro), kept as
separate pulls rather than one blended query, per Product Plan. Only
invoked when the screening agent finds new activity.
"""
from __future__ import annotations

import anthropic

from agents.common import call_structured
from db import Holding
from models import (
    FILINGS_EXTRACTION_SCHEMA,
    MACRO_EXTRACTION_SCHEMA,
    NEWS_EXTRACTION_SCHEMA,
    AgentCallResult,
)
from prompts.system_prompts import (
    FILINGS_EXTRACTION_INSTRUCTION,
    MACRO_EXTRACTION_INSTRUCTION,
    NEWS_EXTRACTION_INSTRUCTION,
    SAFETY_PREAMBLE,
)
from tools import edgar
from tools.finnhub_adapter import FinnhubProvider


def extract_filings(
    client: anthropic.Anthropic, model: str, holding: Holding, since_date: str, until_date: str | None = None
) -> tuple[AgentCallResult, int]:
    filings = edgar.get_filings(holding.symbol, since_date, until_date=until_date)
    raw = "\n".join(
        f"- [{f.form_type}] filed {f.filed_at}: {f.summary} ({f.url})" for f in filings
    ) or "No filings found in this period."

    return call_structured(
        client=client,
        model=model,
        system_prompt=SAFETY_PREAMBLE + "\n" + FILINGS_EXTRACTION_INSTRUCTION,
        user_content=f"Holding: {holding.full_name} ({holding.symbol})\n\nRaw filings data:\n{raw}",
        schema=FILINGS_EXTRACTION_SCHEMA,
    )


def extract_news(
    client: anthropic.Anthropic,
    model: str,
    holding: Holding,
    since_date: str,
    news_provider: FinnhubProvider,
    until_date: str | None = None,
) -> tuple[AgentCallResult, int]:
    # Adaptive pull depth (AI Product Decisions Stage 1): a wider initial
    # pull than the screening pass, letting the extraction agent itself
    # decide in its output how much of it is actually noteworthy.
    articles = news_provider.get_news(holding.symbol, since_date, max_articles=15, until_date=until_date)
    raw = "\n".join(
        f"- \"{a.headline}\" ({a.source}, {a.published_at}): {a.summary} [{a.url}]" for a in articles
    ) or "No news articles found in this period."

    return call_structured(
        client=client,
        model=model,
        system_prompt=SAFETY_PREAMBLE + "\n" + NEWS_EXTRACTION_INSTRUCTION,
        user_content=f"Holding: {holding.full_name} ({holding.symbol})\n\nRaw news data:\n{raw}",
        schema=NEWS_EXTRACTION_SCHEMA,
    )


def extract_macro(
    client: anthropic.Anthropic,
    model: str,
    holding: Holding,
    since_date: str,
    news_provider: FinnhubProvider,
    sector: str | None = None,
) -> tuple[AgentCallResult, int]:
    snapshots = news_provider.get_macro(holding.symbol, sector, since_date)
    raw = "\n".join(f"- [{s.tier}] {s.label}: {s.summary}" for s in snapshots) or "No macro data found."

    return call_structured(
        client=client,
        model=model,
        system_prompt=SAFETY_PREAMBLE + "\n" + MACRO_EXTRACTION_INSTRUCTION,
        user_content=f"Holding: {holding.full_name} ({holding.symbol})\n\nRaw macro data:\n{raw}",
        schema=MACRO_EXTRACTION_SCHEMA,
    )
