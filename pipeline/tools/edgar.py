"""
SEC EDGAR client — the mandatory, non-swappable primary-source data feed for
hard facts (Form 4 buys/sells, 8-Ks, earnings releases). Free, public,
authoritative by definition; unlike news/macro, this is not behind an
adapter interface (see technical-prd.md Section 4.5).
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

EDGAR_BASE_URL = "https://data.sec.gov"  # submissions JSON API only
# The actual filing documents (Archives paths) live on a *different*
# subdomain than the submissions API — data.sec.gov 404s on /Archives/...
# paths. This was previously undetected because doc_url was never
# fetched, only handed to the LLM as a citation link; the Form 4 XML
# detail-fetch added here is what surfaced it.
EDGAR_ARCHIVES_BASE_URL = "https://www.sec.gov"
# SEC EDGAR requires a descriptive User-Agent identifying the requester —
# requests without one are rejected. Update the contact email before deploying.
USER_AGENT = "watchlist-tool/1.0 (contact: your-email@example.com)"

# Form 4 transaction codes we care about per the Product Plan's explicit
# "both open-market buys AND sells" requirement. Other codes (grants,
# option exercises, gifts, tax withholding, etc.) still get surfaced —
# labeled generically rather than silently dropped — since they're still
# primary-source hard facts, just not the buy/sell signal the product is
# centered on.
_TRANSACTION_CODE_LABELS = {"P": "buy", "S": "sell"}


@dataclass
class Filing:
    form_type: str  # "4", "8-K", or an earnings-release designation
    filed_at: str
    summary: str
    url: str
    # Form 4-specific fields, empty for other form types or when the
    # transaction document couldn't be fetched/parsed.
    insider_name: str | None = None
    transaction_type: str | None = None  # "buy", "sell", or "other (<code>)"
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


def _find_form4_xml_url(client: httpx.Client, cik: str, accession_no_dashes: str) -> str | None:
    """Form 4 filings are submitted as structured XML, but the submissions
    index's `primaryDocument` field usually points at the XSLT-rendered
    human-readable .htm view, not the raw XML the actual transaction data
    lives in. The accession folder's machine-readable directory listing is
    the reliable way to find the real XML file regardless of the filer's
    naming convention (it isn't consistently "primary_doc.xml")."""
    resp = client.get(
        f"{EDGAR_ARCHIVES_BASE_URL}/Archives/edgar/data/{int(cik)}/{accession_no_dashes}/index.json"
    )
    resp.raise_for_status()
    items = resp.json().get("directory", {}).get("item", [])
    for item in items:
        name = item.get("name", "")
        if name.endswith(".xml"):
            return f"{EDGAR_ARCHIVES_BASE_URL}/Archives/edgar/data/{int(cik)}/{accession_no_dashes}/{name}"
    return None


def _parse_form4_transactions(xml_text: str) -> list[dict]:
    """Parse a Form 4 ownership XML document into individual non-derivative
    transactions (direct open-market activity — the Product Plan's
    explicit scope). Returns an empty list on any parse failure rather
    than raising, since a malformed document from one filing shouldn't
    take down extraction for the whole holding."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    owner_name = None
    owner_el = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
    if owner_el is not None:
        owner_name = owner_el.text

    transactions = []
    for txn in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code_el = txn.find("transactionCoding/transactionCode")
        shares_el = txn.find("transactionAmounts/transactionShares/value")
        price_el = txn.find("transactionAmounts/transactionPricePerShare/value")

        code = code_el.text if code_el is not None else None
        shares = float(shares_el.text) if shares_el is not None and shares_el.text else None
        price = float(price_el.text) if price_el is not None and price_el.text else None

        transactions.append(
            {
                "insider_name": owner_name,
                "transaction_type": _TRANSACTION_CODE_LABELS.get(code, f"other ({code})" if code else "unknown"),
                "shares": shares,
                "price_per_share": price,
            }
        )
    return transactions


def _fetch_form4_filings(client: httpx.Client, cik: str, accession_no_dashes: str, filed_at: str, doc_url: str) -> list[Filing]:
    """Fetch and parse one Form 4 filing's actual transaction detail.
    Falls back to a single generic "filed, detail unavailable" entry
    (rather than dropping the filing entirely) if the document can't be
    located, fetched, or parsed — a missing detail-fetch shouldn't erase
    the fact that a filing happened."""
    try:
        xml_url = _find_form4_xml_url(client, cik, accession_no_dashes)
        if xml_url:
            xml_resp = client.get(xml_url)
            xml_resp.raise_for_status()
            transactions = _parse_form4_transactions(xml_resp.text)
        else:
            transactions = []
    except httpx.HTTPStatusError as e:
        print(f"SEC EDGAR Form 4 detail fetch failed for accession {accession_no_dashes}: {e}", file=sys.stderr)
        transactions = []

    if not transactions:
        return [
            Filing(
                form_type="4",
                filed_at=filed_at,
                summary=f"Form 4 filed {filed_at} (transaction detail unavailable)",
                url=doc_url,
            )
        ]

    return [
        Filing(
            form_type="4",
            filed_at=filed_at,
            summary=(
                f"Form 4: {t['insider_name'] or 'insider'} {t['transaction_type']} "
                f"{t['shares'] if t['shares'] is not None else '?'} shares"
                + (f" @ ${t['price_per_share']}" if t["price_per_share"] is not None else "")
            ),
            url=doc_url,
            insider_name=t["insider_name"],
            transaction_type=t["transaction_type"],
            shares=t["shares"],
            price_per_share=t["price_per_share"],
        )
        for t in transactions
    ]


def get_filings(symbol: str, since_date: str, until_date: str | None = None) -> list[Filing]:
    """Fetch Form 4 (buys and sells, with real transaction detail — see
    _fetch_form4_filings), 8-K, and earnings-related filings for a symbol
    since the given date (YYYY-MM-DD), optionally bounded above by
    until_date. This is the `get_filings` MCP tool's underlying
    implementation.

    until_date defaults to unbounded (normal operation always wants
    "through now"); a backfill run passes a specific upper bound so each
    historical day's digest covers exactly that day, not everything up to
    the real present.

    Per the PRD's reliability requirement, an EDGAR outage or lookup
    failure degrades this holding to "no filings found" rather than
    crashing the whole pipeline run — mutual fund symbols in particular
    won't resolve to a CIK at all (they don't file via the equity ticker
    registry), which is expected, not an error.
    """
    try:
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
                if until_date is not None and dates[i] > until_date:
                    continue
                if form_type not in ("4", "8-K"):
                    # Earnings releases typically surface as 8-K Item 2.02;
                    # narrower earnings-specific parsing is a Phase 2 refinement.
                    continue

                accession = accession_numbers[i].replace("-", "")
                doc_url = (
                    f"{EDGAR_ARCHIVES_BASE_URL}/Archives/edgar/data/{int(cik)}/"
                    f"{accession}/{primary_documents[i]}"
                )

                if form_type == "4":
                    filings.extend(_fetch_form4_filings(client, cik, accession, dates[i], doc_url))
                else:
                    filings.append(
                        Filing(
                            form_type=form_type,
                            filed_at=dates[i],
                            summary=f"{form_type} filed {dates[i]}",
                            url=doc_url,
                        )
                    )
            return filings
    except httpx.HTTPStatusError as e:
        print(f"SEC EDGAR get_filings failed for {symbol}: {e}", file=sys.stderr)
        return []
