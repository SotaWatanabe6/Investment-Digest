"""
Per-token pricing for cost tracking (feeds the per-digest cost footer and
the daily spend ceiling — Product Plan "cost transparency" requirement).

Pricing is looked up here rather than hardcoded per call site, so a rate
change only needs updating in one place. Verified against Anthropic's
published rates as of 2026-08-07 (see ai-product-decisions.md, Model &
Vendor Research) — Sonnet 5 is on introductory pricing through 2026-08-31
and reverts to $3/$15 afterward. RE-VERIFY before relying on this if the
build is delayed past that date.
"""
from __future__ import annotations

# (input_usd_per_million, output_usd_per_million)
_RATES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),  # intro pricing through 2026-08-31; $3/$15 after
}


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in _RATES:
        raise ValueError(f"Unknown model for pricing: {model}. Update pricing.py._RATES.")
    input_rate, output_rate = _RATES[model]
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
