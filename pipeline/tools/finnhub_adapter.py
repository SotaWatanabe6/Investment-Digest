"""
Finnhub implementation of the NewsProvider interface (v1 vendor choice,
free tier — see ai-product-decisions.md Stage 2). Swappable for
NewsAPI.org / FRED later without touching agents or orchestration.
"""
from __future__ import annotations

import httpx

from tools.news_provider import MacroSnapshot, NewsArticle

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def _client(self) -> httpx.Client:
        return httpx.Client(params={"token": self._api_key}, timeout=15.0)

    def get_news(self, symbol: str, since_date: str, max_articles: int = 10) -> list[NewsArticle]:
        with self._client() as client:
            resp = client.get(
                f"{FINNHUB_BASE_URL}/company-news",
                params={"symbol": symbol, "from": since_date, "to": _today()},
            )
            resp.raise_for_status()
            articles = resp.json()

        # Adaptive pull depth: the extraction agent decides how many of these
        # to actually use downstream (AI Product Decisions Stage 1); this
        # tool caps the raw pull at max_articles to bound cost regardless.
        return [
            NewsArticle(
                headline=a.get("headline", ""),
                summary=a.get("summary", ""),
                source=a.get("source", "unknown"),
                url=a.get("url", ""),
                published_at=a.get("datetime", ""),
            )
            for a in articles[:max_articles]
        ]

    def get_macro(self, symbol: str, sector: str | None, since_date: str) -> list[MacroSnapshot]:
        snapshots: list[MacroSnapshot] = []
        with self._client() as client:
            # Global/US tier: general market news as a proxy for conditions
            # (Finnhub's free tier doesn't expose a dedicated indices-summary
            # endpoint) — general category covers major index-moving stories.
            resp = client.get(f"{FINNHUB_BASE_URL}/news", params={"category": "general"})
            resp.raise_for_status()
            for item in resp.json()[:5]:
                snapshots.append(
                    MacroSnapshot(tier="us", label="US market conditions", summary=item.get("headline", ""))
                )

            if sector:
                # Sector tier: peer performance via Finnhub's sector-mapped
                # quote data is a Phase 2 refinement; v1 surfaces sector-tagged
                # general news as a lighter-weight approximation.
                snapshots.append(
                    MacroSnapshot(
                        tier="sector",
                        label=f"{sector} sector",
                        summary=f"Sector-level detail for {sector} — Phase 2 will replace this with quantitative sector index data.",
                    )
                )

        return snapshots


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
