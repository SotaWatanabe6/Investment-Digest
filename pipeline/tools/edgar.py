"""
SEC EDGAR client — the mandatory, non-swappable primary-source data feed for
hard facts (Form 4 buys/sells, 8-Ks, earnings releases). Free, public,
authoritative by definition; unlike news/macro, this is not behind an
adapter interface (see technical-prd.md Section 4.5).
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

EDGAR_BASE_URL = "https://data.sec.gov"
# SEC EDGAR requires a descriptive User-Agent identifying the requester —
# requests without one are rejected. Update the contact email before deploying.
USER_AGENT = "watchlist-tool/1.0 (contact: your-email@example.com)"


@dataclass
class Filing:
    form_type: str  # "4", "8-K", or an earnings-release designation
    filed_at: str
    summary: str
    url: str
    # Form 4-specific fields, empty for other form types.
    insider_name: str | None = None
    transaction_type: str | None = None  # "buy" or "sell" — both are tracked, per Product Plan
    shares: float | None = None
    price_per_share: float | None = None


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0)


def _cik_for_symbol(client: httpx.Client, symbol: str) -> str | None:
    """EDGAR indexes filings by CIK, not ticker — resolve via the company
    tickers lookup file (also SEC-hosted, cached indefinitely per SEC's own
    update cadence of roughly daily)."""
    resp = client.get("https://www.sec.gov/files/company_tickers.json")
    resp.raise_for_status()
    for entry in resp.json().values():
        if entry["ticker"].upper() == symbol.upper():
            return str(entry["cik_str"]).zfill(10)
    return None


def get_filings(symbol: str, since_date: str) -> list[Filing]:
    """Fetch Form 4 (buys and sells), 8-K, and earnings-related filings for
    a symbol since the given date (YYYY-MM-DD). This is the `get_filings`
    MCP tool's underlying implementation."""
    with _client() as client:
        cik = _cik_for_symbol(client, symbol)
        if cik is None:
            return []

        resp = client.get(f"{EDGAR_BASE_URL}/submissions/CIK{cik}.json")
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        filings: list[Filing] = []
        for i, form_type in enumerate(forms):
            if dates[i] < since_date:
                continue
            if form_type not in ("4", "8-K"):
                # Earnings releases typically surface as 8-K Item 2.02;
                # narrower earnings-specific parsing is a Phase 2 refinement.
                continue

            accession = accession_numbers[i].replace("-", "")
            doc_url = (
                f"{EDGAR_BASE_URL}/Archives/edgar/data/{int(cik)}/"
                f"{accession}/{primary_documents[i]}"
            )
            filings.append(
                Filing(
                    form_type=form_type,
                    filed_at=dates[i],
                    summary=f"{form_type} filed {dates[i]}",
                    url=doc_url,
                )
            )
        return filings
