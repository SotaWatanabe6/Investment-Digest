-- Insider & Market Watchlist Tool -- schema
-- Turso (libSQL / SQLite dialect). Single shared DB, accessed natively by
-- both the Python pipeline (GitHub Actions) and the Cloudflare Workers web app.
-- See technical-prd.md Section 4.3 for the entity definitions this implements.

-- Single-row table: v1 is single-user by design (see Product Plan / PRD).
-- The login password itself is NOT stored here — it lives as the
-- PASSWORD_HASH Worker secret (web/src/auth.ts), consistent with "secrets
-- live in env vars, never in the DB or repo" (PRD Section 6). This table
-- only holds user-configurable settings.
CREATE TABLE IF NOT EXISTS user (
  id INTEGER PRIMARY KEY CHECK (id = 1), -- enforces exactly one row
  digest_send_time TEXT NOT NULL DEFAULT '07:00', -- HH:MM, 24h, UTC. Phase 2 makes this user-editable.
  global_pause_flag INTEGER NOT NULL DEFAULT 0, -- Phase 2 control surface; present now so schema doesn't change shape later.
  failed_login_attempts INTEGER NOT NULL DEFAULT 0, -- login rate-limiting (web/src/routes/login.ts)
  lockout_until TEXT -- ISO timestamp; NULL when not locked out
);

CREATE TABLE IF NOT EXISTS holding (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('stock', 'mutual_fund', 'etf')),
  full_name TEXT NOT NULL,
  added_at TEXT NOT NULL DEFAULT (datetime('now')),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (symbol)
);

CREATE TABLE IF NOT EXISTS digest_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL, -- YYYY-MM-DD, the period this run covers
  send_time TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('sent', 'skipped_paused', 'failed', 'aborted_cost_ceiling')),
  total_cost_usd REAL NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS holding_digest_entry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  digest_run_id INTEGER NOT NULL REFERENCES digest_run(id),
  holding_id INTEGER NOT NULL REFERENCES holding(id),
  hard_facts TEXT NOT NULL DEFAULT '[]', -- JSON array, structured extraction output
  subjective_info TEXT NOT NULL DEFAULT '[]', -- JSON array, structured extraction output
  discrepancy_analysis TEXT NOT NULL DEFAULT '[]', -- JSON array, descriptive agreement/disagreement notes
  macro_influence TEXT NOT NULL DEFAULT '{}', -- JSON object: { global, us, sector }
  nothing_to_report INTEGER NOT NULL DEFAULT 0,
  low_confidence_flags TEXT NOT NULL DEFAULT '[]' -- JSON array of { field, note } surfaced plainly per PRD NFRs
);

-- Feeds the validation agent's 7-day rolling recall (AI Product Decisions, Stage 5).
-- Kept separate from holding_digest_entry so recall stays cheap (~200 token cap)
-- even as the full digest entries grow richer over time.
CREATE TABLE IF NOT EXISTS holding_daily_summary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  holding_id INTEGER NOT NULL REFERENCES holding(id),
  summary_date TEXT NOT NULL, -- YYYY-MM-DD
  compact_summary TEXT NOT NULL, -- plain text, capped at ~200 tokens by the composer that writes it
  token_count INTEGER NOT NULL,
  UNIQUE (holding_id, summary_date)
);

CREATE TABLE IF NOT EXISTS source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  holding_digest_entry_id INTEGER NOT NULL REFERENCES holding_digest_entry(id),
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  published_at TEXT
);

-- Audit trail + observability data (PRD Section 6, Stage 7 of AI Product Decisions).
CREATE TABLE IF NOT EXISTS agent_run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  digest_run_id INTEGER NOT NULL REFERENCES digest_run(id),
  holding_id INTEGER, -- nullable: composer-level entries aren't tied to one holding
  agent_name TEXT NOT NULL CHECK (agent_name IN ('screening', 'extraction_filings', 'extraction_news', 'extraction_macro', 'validation', 'composer')),
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  tool_calls TEXT NOT NULL DEFAULT '[]', -- JSON array of tool call summaries
  status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_holding_digest_entry_run ON holding_digest_entry(digest_run_id);
CREATE INDEX IF NOT EXISTS idx_holding_daily_summary_holding_date ON holding_daily_summary(holding_id, summary_date);
CREATE INDEX IF NOT EXISTS idx_agent_run_log_run ON agent_run_log(digest_run_id);
