"""
Daily pipeline entrypoint — triggered by the GitHub Actions cron workflow
(.github/workflows/daily-pipeline.yml). Implements the fixed backbone
(screening -> extraction -> validation -> compose -> send) described in
technical-prd.md Section 4.2, with two agent-directed steps: news
extraction depth (agent decides what's noteworthy from a wider raw pull)
and validation's ability to request one extra round of context.

Architecture note: agents/*.py call `agents.common.call_structured`, which
forces Claude to return structured output directly rather than looping
through live MCP tool calls. Data fetching (SEC EDGAR / Finnhub) happens in
Python via tools/*.py *before* each agent call, and results are handed to
the agent as text to analyze. This is the "code-coordinated" architecture
confirmed in ai-product-decisions.md Stage 5 (no agent-to-agent handoff,
orchestration code sequences each step) — mcp_server.py wraps the same
underlying functions as a standalone MCP tool surface (per that decision),
available for a future live-tool-calling agent loop, but Phase 1's
orchestrator calls tools/*.py directly rather than via the MCP JSON-RPC
transport, since nothing in this fixed-backbone design requires an agent to
autonomously choose which tool to call next.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import anthropic

import db
from config import Config
from agents import composer, extraction, screening, validation
from tools.email_tool import SendLimitExceededError, send_email
from tools.finnhub_adapter import FinnhubProvider


def run_daily_pipeline() -> None:
    config = Config.from_env()
    conn = db.connect(config)
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    news_provider = FinnhubProvider(config.finnhub_api_key)

    settings = db.get_user_settings(conn)
    # Pause-flag enforcement is Phase 2 (see feature-implementation-plan.md
    # Step 3 scope note) — global_pause_flag exists in the schema already
    # so Phase 2 doesn't need a migration, but Phase 1 always runs.

    # BACKFILL_PERIOD_DATE (optional, set via workflow_dispatch input for a
    # manually-triggered backfill run — see .github/workflows/daily-pipeline.yml)
    # makes this run cover exactly one historical day (since_date == until_date
    # == that day) instead of "since the last sent digest through now."
    # period_date drives both the recorded digest_run.run_date and the
    # send-limit check, so several backfill runs can each send once, one per
    # distinct historical day, without weakening the normal "max 1 send per
    # real day" protection a scheduled run still gets (period_date is None
    # there, so everything defaults to today as before).
    backfill_date = os.environ.get("BACKFILL_PERIOD_DATE") or None
    since_date = backfill_date or _last_covered_date(conn)
    until_date = backfill_date  # None for normal runs — unbounded through "now"
    period_date = backfill_date  # None for normal runs — db.py defaults to today

    holdings = db.get_active_holdings(conn)
    run_id = db.create_digest_run(conn, settings["digest_send_time"], period_date=period_date)

    total_cost_usd = 0.0
    holdings_payload = []

    try:
        for holding in holdings:
            if total_cost_usd >= config.daily_spend_ceiling_usd:
                print(
                    f"Daily spend ceiling (${config.daily_spend_ceiling_usd}) reached — "
                    f"aborting before processing {holding.symbol}.",
                    file=sys.stderr,
                )
                db.complete_digest_run(conn, run_id, "aborted_cost_ceiling", total_cost_usd)
                return

            entry, cost = _process_holding(
                conn, client, config, run_id, holding, since_date, news_provider, until_date
            )
            total_cost_usd += cost
            holdings_payload.append(entry)

        period_end = until_date or db.today_str()
        compose_result, compose_ms = composer.compose_digest(
            client, config.reasoning_model, holdings_payload, since_date, period_end, total_cost_usd
        )
        total_cost_usd += compose_result.cost_usd
        db.log_agent_run(
            conn, run_id, None, "composer",
            compose_result.input_tokens, compose_result.output_tokens,
            compose_result.cost_usd, [], "success", compose_ms,
        )

        daily_summaries = compose_result.data.get("daily_summary_by_holding", {})
        for holding in holdings:
            summary = daily_summaries.get(str(holding.id), "")
            if summary:
                db.save_daily_summary(conn, holding.id, summary, len(summary.split()), summary_date=period_date)

        try:
            send_email(
                conn, config.resend_api_key, config.digest_to_email, config.digest_from_email,
                compose_result.data.get("subject_line", "Your Investment Digest"),
                compose_result.data.get("html_body", "<p>No content generated for this run.</p>"),
                period_date=period_date,
            )
            db.complete_digest_run(conn, run_id, "sent", total_cost_usd)
        except SendLimitExceededError as e:
            print(f"Send blocked: {e}", file=sys.stderr)
            db.complete_digest_run(conn, run_id, "failed", total_cost_usd)

    except Exception:
        db.complete_digest_run(conn, run_id, "failed", total_cost_usd)
        raise


def _process_holding(conn, client, config, run_id, holding, since_date, news_provider, until_date=None):
    cost = 0.0

    screen_result, screen_ms = screening.run_screening(
        client, config.screening_model, holding, since_date, news_provider, until_date=until_date
    )
    cost += screen_result.cost_usd
    db.log_agent_run(
        conn, run_id, holding.id, "screening",
        screen_result.input_tokens, screen_result.output_tokens,
        screen_result.cost_usd, [], "success", screen_ms,
    )

    if not screen_result.data.get("has_new_activity", False):
        db.save_holding_digest_entry(conn, run_id, holding.id, [], [], [], {}, True, [])
        return _entry_payload(holding, since_date, [], [], [], {}, True, []), cost

    # The three extraction calls are independent (different sources, no
    # data dependency between them) and each is a several-second LLM
    # round trip — running them concurrently rather than sequentially cuts
    # this phase's wall-clock time roughly 3x per active holding. Only the
    # Anthropic calls themselves run in threads; the resulting DB writes
    # below still happen sequentially on the main thread's connection, so
    # there's no concurrent access to the shared _ResilientConnection.
    with ThreadPoolExecutor(max_workers=3) as executor:
        filings_future = executor.submit(
            extraction.extract_filings, client, config.reasoning_model, holding, since_date, until_date=until_date
        )
        news_future = executor.submit(
            extraction.extract_news, client, config.reasoning_model, holding, since_date, news_provider, until_date=until_date
        )
        macro_future = executor.submit(
            extraction.extract_macro, client, config.reasoning_model, holding, since_date, news_provider
        )
        filings_result, filings_ms = filings_future.result()
        news_result, news_ms = news_future.result()
        macro_result, macro_ms = macro_future.result()

    cost += filings_result.cost_usd + news_result.cost_usd + macro_result.cost_usd

    db.log_agent_runs(
        conn,
        [
            (run_id, holding.id, "extraction_filings", filings_result.input_tokens, filings_result.output_tokens, filings_result.cost_usd, [], "success", filings_ms),
            (run_id, holding.id, "extraction_news", news_result.input_tokens, news_result.output_tokens, news_result.cost_usd, [], "success", news_ms),
            (run_id, holding.id, "extraction_macro", macro_result.input_tokens, macro_result.output_tokens, macro_result.cost_usd, [], "success", macro_ms),
        ],
    )

    # Every .data.get(...) below defaults to an empty/falsy value rather
    # than indexing directly — Claude's forced tool-use is a strong hint
    # toward the schema, not a hard guarantee every "required" field is
    # populated. A single incomplete agent response should degrade that
    # field to empty, not crash the whole run (PRD reliability
    # requirement) — this is exactly what happened here: a news extraction
    # response came back without "subjective_info" and took down an entire
    # backfill day before this fix.
    hard_facts = filings_result.data.get("hard_facts", [])
    subjective_info = news_result.data.get("subjective_info", [])
    filings_low_confidence = filings_result.data.get("low_confidence_flags", [])
    news_low_confidence = news_result.data.get("low_confidence_flags", [])

    val_result, val_ms = validation.run_validation(
        conn, client, config.reasoning_model, holding, hard_facts, subjective_info,
    )
    cost += val_result.cost_usd
    db.log_agent_run(
        conn, run_id, holding.id, "validation",
        val_result.input_tokens, val_result.output_tokens, val_result.cost_usd, [], "success", val_ms,
    )

    # Agent-directed step: validation may request one extra round of
    # context if the initial pull was too thin/contradictory. Capped at a
    # single retry so a persistently-uncertain agent can't loop indefinitely
    # and blow through the spend ceiling.
    if val_result.data.get("needs_more_context"):
        deeper_news = news_provider.get_news(holding.symbol, since_date, max_articles=25, until_date=until_date)
        extra_context = "\n".join(f"- {a.headline}: {a.summary}" for a in deeper_news)
        val_result, val_ms = validation.run_validation(
            conn, client, config.reasoning_model, holding, hard_facts, subjective_info,
            extra_context=extra_context,
        )
        cost += val_result.cost_usd
        db.log_agent_run(
            conn, run_id, holding.id, "validation",
            val_result.input_tokens, val_result.output_tokens, val_result.cost_usd, [], "success", val_ms,
        )

    discrepancy_analysis = val_result.data.get("discrepancy_analysis", [])
    low_confidence = filings_low_confidence + news_low_confidence

    entry_id = db.save_holding_digest_entry(
        conn, run_id, holding.id,
        hard_facts, subjective_info, discrepancy_analysis, macro_result.data, False, low_confidence,
    )
    sources = [
        (item.get("source_name"), item.get("source_url"), item.get("published_at"))
        for item in subjective_info
        if item.get("source_name") and item.get("source_url")
    ]
    db.save_sources(conn, entry_id, sources)

    return (
        _entry_payload(
            holding, since_date, hard_facts, subjective_info,
            discrepancy_analysis, macro_result.data, False, low_confidence,
        ),
        cost,
    )


def _entry_payload(holding, since_date, hard_facts, subjective_info, discrepancy_analysis, macro_influence, nothing_to_report, low_confidence_flags):
    return {
        "holding_id": holding.id,
        "full_name": holding.full_name,
        "symbol": holding.symbol,
        "period_since": since_date,
        "hard_facts": hard_facts,
        "subjective_info": subjective_info,
        "discrepancy_analysis": discrepancy_analysis,
        "macro_influence": macro_influence,
        "nothing_to_report": nothing_to_report,
        "low_confidence_flags": low_confidence_flags,
    }


def _last_covered_date(conn) -> str:
    """The period start for this run: the most recent prior run's date, or
    a 7-day lookback if this is the first run ever.

    Falling back to *today's date* here would give every agent a same-day
    window to search — for a first run with no prior digest, that's
    effectively asking "did anything happen in the last few hours?", which
    is almost always empty regardless of how good the data sources are.
    A 7-day window gives the first digest something real to report on;
    every subsequent run naturally narrows back down to "since the last
    sent digest," which is the correct steady-state behavior.
    """
    row = conn.execute(
        "SELECT run_date FROM digest_run WHERE status = 'sent' ORDER BY run_date DESC LIMIT 1"
    ).fetchone()
    if row:
        return row[0]

    return (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")


if __name__ == "__main__":
    run_daily_pipeline()
