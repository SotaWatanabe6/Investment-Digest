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
            result = self._conn.execute(*args, **kwargs)
        except ValueError as e:
            if "stream not found" not in str(e):
                raise
            self._conn = self._new_conn()
            result = self._conn.execute(*args, **kwargs)

        # libsql_experimental follows Python's DB-API 2.0 convention of
        # requiring an explicit commit — it does not autocommit. Without
        # this, every write in a run (digest_run, holding_digest_entry,
        # agent_run_log, etc.) was silently discarded when the process
        # exited: reads within the same connection saw the "written" data
        # (visible inside the open transaction), but nothing was ever
        # actually persisted to Turso, so a separate connection querying
        # afterward found the tables empty even after a fully "successful"
        # run. Committing after every statement (cheap no-op if there's
        # nothing pending) fixes this without needing to track read vs.
        # write statements separately.
        self._conn.commit()
        return result


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


def create_digest_run(conn, send_time: str, period_date: str | None = None) -> int:
    # RETURNING id in the same statement, rather than a separate
    # `SELECT last_insert_rowid()` call — over Turso's stateless HTTP
    # (Hrana) protocol, a follow-up call isn't guaranteed to land on the
    # same session as the INSERT, so last_insert_rowid() can silently
    # return a stale/wrong value (this caused a real FOREIGN KEY failure
    # downstream when the wrong id got used as a foreign key).
    #
    # period_date defaults to today (normal scheduled operation always
    # covers "today"); a backfill run passes the specific historical day
    # it's generating a digest for instead.
    result = conn.execute(
        "INSERT INTO digest_run (run_date, send_time, status, started_at) VALUES (?, ?, 'failed', ?) RETURNING id",
        (period_date or today_str(), send_time, now_iso()),
    )
    return result.fetchone()[0]


def complete_digest_run(conn, run_id: int, status: str, total_cost_usd: float) -> None:
    conn.execute(
        "UPDATE digest_run SET status = ?, total_cost_usd = ?, completed_at = ? WHERE id = ?",
        (status, total_cost_usd, now_iso(), run_id),
    )


def get_sent_run_count_for_period(conn, period_date: str) -> int:
    """Backs the max-1-send-per-covered-period safeguard (enforced again at
    the tool boundary in tools/email_tool.py — this is the DB-level check
    the tool consults, not a substitute for it).

    For a normal scheduled run, period_date is always today's real date, so
    this is exactly "max 1 send per real day" — the original runaway-loop
    protection is unchanged. A deliberate backfill run passes a specific
    historical period_date instead, which allows one send per distinct
    historical day even when several backfill runs happen within the same
    real day — while still refusing to double-send for the *same* period,
    which is what the safeguard actually exists to prevent.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM digest_run WHERE run_date = ? AND status = 'sent'",
        (period_date,),
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
    result = conn.execute(
        """
        INSERT INTO holding_digest_entry
            (digest_run_id, holding_id, hard_facts, subjective_info,
             discrepancy_analysis, macro_influence, nothing_to_report, low_confidence_flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
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
    return result.fetchone()[0]


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


def save_daily_summary(
    conn, holding_id: int, compact_summary: str, token_count: int, summary_date: str | None = None
) -> None:
    # summary_date defaults to today; a backfill run passes the historical
    # day it's writing a summary for, so the 7-day recall window stays
    # dated correctly rather than every backfilled summary landing on
    # today's date.
    conn.execute(
        """
        INSERT INTO holding_daily_summary (holding_id, summary_date, compact_summary, token_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (holding_id, summary_date) DO UPDATE SET
            compact_summary = excluded.compact_summary,
            token_count = excluded.token_count
        """,
        (holding_id, summary_date or today_str(), compact_summary, token_count),
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
