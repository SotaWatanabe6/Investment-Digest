"""
Environment-variable-based configuration for the daily pipeline.

All secrets are loaded from the environment (set as GitHub Actions repo
secrets in production; a local .env for development, gitignored). Nothing
here is ever hardcoded, since this repo is public. See technical-prd.md
Section 6 (Security & auth model).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is not set."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(
            f"Missing required environment variable: {name}. "
            f"See .env.example for the full list."
        )
    return value


@dataclass(frozen=True)
class Config:
    # Turso (libSQL) — shared DB, also used natively by the Cloudflare web app.
    turso_database_url: str
    turso_auth_token: str

    # Anthropic — Haiku 4.5 for screening, Sonnet 5 for extraction/validation/composition.
    anthropic_api_key: str
    screening_model: str
    reasoning_model: str

    # Finnhub — news + macro data, behind the swappable adapter interface.
    finnhub_api_key: str

    # Resend — email delivery.
    resend_api_key: str
    digest_to_email: str
    digest_from_email: str

    # Safety ceilings (PRD Section 6 / AI Product Decisions Stage 7).
    # A run that would exceed this aborts instead of completing.
    daily_spend_ceiling_usd: float

    @staticmethod
    def from_env() -> "Config":
        return Config(
            turso_database_url=_require("TURSO_DATABASE_URL"),
            turso_auth_token=_require("TURSO_AUTH_TOKEN"),
            anthropic_api_key=_require("ANTHROPIC_API_KEY"),
            screening_model=os.environ.get("SCREENING_MODEL", "claude-haiku-4-5-20251001"),
            reasoning_model=os.environ.get("REASONING_MODEL", "claude-sonnet-5"),
            finnhub_api_key=_require("FINNHUB_API_KEY"),
            resend_api_key=_require("RESEND_API_KEY"),
            digest_to_email=_require("DIGEST_TO_EMAIL"),
            digest_from_email=_require("DIGEST_FROM_EMAIL"),
            daily_spend_ceiling_usd=float(os.environ.get("DAILY_SPEND_CEILING_USD", "2.0")),
        )
