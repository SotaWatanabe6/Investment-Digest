"""
Turso (libSQL) database access for the pipeline side.

The web app (Cloudflare Workers) accesses the same database natively via the
JS libSQL client — see web/src/db.ts. Schema lives in db/schema.sql and is
the single source of truth for both sides.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import libsql_experimental as libsql

from config import Config


class _ResilientConnection:
    """Wraps a libsql connection and transparently reconnects on Turso's
    Hrana "stream not found" error.

    The pipeline holds one connection open across the whole run, but slow
    Anthropic API calls (many seconds each) create long idle gaps between
    database writes. Turso expires the underlying HTTP stream server-side
    after enough idle time, so the next write on the same connection object
    fails with a 404 even though nothing is actually wrong. Reconnecting is
    cheap (stateless HTTP), so retrying once after a fresh connection is
    sufficient rather than treating this as a hard pipeline failure.
    """

    def __init__(self, config: Config):
        self._config = config
        self._conn = self._new_conn()

    def _new_conn(self):
        return libsql.connect(
            database=self._config.turso_database_url,
            auth_token=self._config.turso_auth_token,
        )

    def execute(self, *args, **kwargs):
        try:
            return self._conn.execute(*args, **kwargs)
        except ValueError as e:
            if "stream not found" not in str(e):
                raise
            self._conn = self._new_conn()
            return self._conn.execute(*args, **kwargs)


def connect(config: Config):
    """Open a connection to the shared Turso database."""
    return _ResilientConnection(config)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Holding:
    id: int
    symbol: str
    type: str
    full_name: str


def get_active_holdings(conn) -> list[Holding]:
    rows = conn.execute(
        "SELECT id, symbol, type, full_name FROM holding WHERE active = 1 ORDER BY symbol"
    ).fetchall()
    return [Holding(id=r[0], symbol=r[1], type=r[2], full_name=r[3]) for r in rows]


def get_user_settings(conn) -> dict[str, Any]:
    row = conn.execute(
        "SELECT digest_send_time, global_pause_flag FROM user WHERE id = 1"
    ).fetchone()
    if row is None:
        # Phase 1 has no onboarding flow; a single user row must be seeded
        # manually via the web app's first-run setup (see README).
        raise RuntimeError("No user row found — run web app setup first to set a password.")
    return {"digest_send_time": row[0], "global_pause_flag": bool(row[1])}


def create_digest_run(conn, send_time: str) -> int:
    conn.execute(
        "INSERT INTO digest_run (run_date, send_time, status, started_at) VALUES (?, ?, 'failed', ?)",
        (today_str(), send_time, now_iso()),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def complete_digest_run(conn, run_id: int, status: str, total_cost_usd: float) -> None:
    conn.execute(
        "UPDATE digest_run SET status = ?, total_cost_usd = ?, completed_at = ? WHERE id = ?",
        (status, total_cost_usd, now_iso(), run_id),
    )


def get_sent_run_count_today(conn) -> int:
    """Backs the max-1-send-per-day safeguard (enforced again at the tool
    boundary in tools/email_tool.py — this is the DB-level check the tool
    consults, not a substitute for it)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM digest_run WHERE run_date = ? AND status = 'sent'",
        (today_str(),),
    ).fetchone()
    return row[0]


def save_holding_digest_entry(
    conn,
    digest_run_id: int,
    holding_id: int,
    hard_facts: list,
    subjective_info: list,
    discrepancy_analysis: list,
    macro_influence: dict,
    nothing_to_report: bool,
    low_confidence_flags: list,
) -> int:
    conn.execute(
        """
        INSERT INTO holding_digest_entry
            (digest_run_id, holding_id, hard_facts, subjective_info,
             discrepancy_analysis, macro_influence, nothing_to_report, low_confidence_flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            digest_run_id,
            holding_id,
            json.dumps(hard_facts),
            json.dumps(subjective_info),
            json.dumps(discrepancy_analysis),
            json.dumps(macro_influence),
            int(nothing_to_report),
            json.dumps(low_confidence_flags),
        ),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def save_source(conn, holding_digest_entry_id: int, name: str, url: str, published_at: str | None) -> None:
    conn.execute(
        "INSERT INTO source (holding_digest_entry_id, name, url, published_at) VALUES (?, ?, ?, ?)",
        (holding_digest_entry_id, name, url, published_at),
    )


def get_recent_daily_summaries(conn, holding_id: int, days: int = 7) -> list[str]:
    """Feeds the validation agent's 7-day recall (AI Product Decisions Stage 5:
    compact per-holding summaries, ~200 tokens/day cap, not full digest text)."""
    rows = conn.execute(
        """
        SELECT compact_summary FROM holding_daily_summary
        WHERE holding_id = ?
        ORDER BY summary_date DESC
        LIMIT ?
        """,
        (holding_id, days),
    ).fetchall()
    return [r[0] for r in rows]


def save_daily_summary(conn, holding_id: int, compact_summary: str, token_count: int) -> None:
    conn.execute(
        """
        INSERT INTO holding_daily_summary (holding_id, summary_date, compact_summary, token_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (holding_id, summary_date) DO UPDATE SET
            compact_summary = excluded.compact_summary,
            token_count = excluded.token_count
        """,
        (holding_id, today_str(), compact_summary, token_count),
    )


def log_agent_run(
    conn,
    digest_run_id: int,
    holding_id: int | None,
    agent_name: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    tool_calls: list,
    status: str,
    duration_ms: int,
) -> None:
    conn.execute(
        """
        INSERT INTO agent_run_log
            (digest_run_id, holding_id, agent_name, input_tokens, output_tokens,
             cost_usd, tool_calls, status, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            digest_run_id,
            holding_id,
            agent_name,
            input_tokens,
            output_tokens,
            cost_usd,
            json.dumps(tool_calls),
            status,
            duration_ms,
        ),
    )
