"""
Swappable interface for news + macro data providers.

Finnhub is the v1 implementation (tools/finnhub_adapter.py). Per
technical-prd.md Section 4.5, this interface exists so a future swap to
NewsAPI.org (news) or FRED (macro) doesn't touch agent/orchestration code —
only a new class implementing this protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class NewsArticle:
    headline: str
    summary: str
    source: str  # publication name — mandatory attribution per Product Plan
    url: str
    published_at: str


@dataclass
class MacroSnapshot:
    tier: str  # "global" | "us" | "sector"
    label: str  # e.g. "S&P 500", "US 10Y Treasury Yield", "Semiconductors sector index"
    summary: str


class NewsProvider(Protocol):
    def get_news(self, symbol: str, since_date: str, max_articles: int = 10) -> list[NewsArticle]:
        """Return attributed news articles for a symbol since the given date.
        Explicitly excludes social sentiment sources (Reddit, social media)
        per the Product Plan's settled scope."""
        ...

    def get_macro(self, symbol: str, sector: str | None, since_date: str) -> list[MacroSnapshot]:
        """Return global, US, and sector-tier macro context relevant to the symbol."""
        ...
