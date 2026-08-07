# Insider & Market Watchlist Tool

Phase 1 (MVP) implementation per `technical-prd.md` and
`feature-implementation-plan.md`. A daily multi-agent pipeline (screening →
extraction → validation → composition → send) that emails one consolidated
digest covering your watchlist, plus a minimal private web page to manage
that watchlist.

This step (`/execute`) built all application code. **What it could not do**
— since it has no access to your accounts — is create the actual Turso
database, Anthropic/Finnhub/Resend accounts, or Cloudflare deployment.
Those are real, external actions with billing/access implications, so they
need to happen under your control. The checklist below is everything left
to go from this code to a running system.

## 1. Provision accounts (all free tier at this volume)

- **Turso**: `turso db create watchlist-tool` → note the DB URL (`turso db show watchlist-tool --url`) and create an auth token (`turso db tokens create watchlist-tool`).
- **Anthropic**: create an API key at console.anthropic.com.
- **Finnhub**: free API key at finnhub.io.
- **Resend**: free API key at resend.com; verify a sending domain/address for `DIGEST_FROM_EMAIL`.
- **Cloudflare**: a Workers-enabled account (free tier).
- **GitHub**: this repo pushed to GitHub (public, per the Product Plan) with Actions enabled.

## 2. Set up the database

```bash
turso db shell watchlist-tool < db/schema.sql
turso db shell watchlist-tool "INSERT INTO user (id) VALUES (1);"
```

Then add your holdings — either directly via SQL for the first run, or once the web app is deployed, through its UI:

```bash
turso db shell watchlist-tool "INSERT INTO holding (symbol, type, full_name) VALUES ('AAPL', 'stock', 'Apple Inc.');"
```

## 3. Configure pipeline secrets (GitHub Actions)

In the repo's Settings → Secrets and variables → Actions, add as **secrets**:
`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`,
`RESEND_API_KEY`, `DIGEST_TO_EMAIL`, `DIGEST_FROM_EMAIL`.

Add as a **variable**: `DAILY_SPEND_CEILING_USD` (e.g. `2.0`).

Edit the cron schedule in `.github/workflows/daily-pipeline.yml` to your
preferred send time (Phase 1 has a fixed schedule — per-user configurable
send time is Phase 2).

## 4. Deploy the web app (Cloudflare Workers)

```bash
cd web
npm install
node scripts/hash-password.mjs "your-chosen-password"   # copy the output
wrangler secret put PASSWORD_HASH        # paste the hash from above
wrangler secret put SESSION_SECRET       # paste any long random string
wrangler secret put TURSO_DATABASE_URL
wrangler secret put TURSO_AUTH_TOKEN
npm run deploy
```

Visit the deployed URL, log in with the password you chose, and confirm
you can add/remove a holding.

## 5. End-to-end verification (do this before trusting the digest)

1. In the GitHub repo's Actions tab, manually trigger **Daily Digest
   Pipeline** (`workflow_dispatch`) rather than waiting for the cron.
2. Confirm the run completes and check its logs for which holdings
   triggered full extraction vs. "nothing to report."
3. Confirm the digest email arrives, and check:
   - Holdings appear in the fixed order (Hard Facts → Subjective Info →
     Discrepancies → Macro Influence) with full name + period header.
   - Any inactive holding shows the abbreviated "nothing to report" line,
     not an omission.
   - The footer shows a total cost figure and the not-investment-advice
     disclaimer.
4. Check the `digest_run` and `agent_run_log` tables in Turso to confirm
   cost tracking and the audit trail are populating as expected.
5. Manually re-trigger the workflow a second time on the same day and
   confirm the second send is refused (`SendLimitExceededError` in the
   logs) — this is the max-1-send/day safeguard working correctly.

## What's deliberately not here yet (Phase 2)

Configurable send time (US-3), global pause/resume (US-4), cost history
view (US-7), the full observability stack, and the automated eval harness
are out of scope for this Phase 1 build — see `technical-prd.md` Section 8
and `feature-implementation-plan.md` for what's next.

## Project layout

```
pipeline/       Python daily pipeline (GitHub Actions cron)
  agents/       screening, extraction, validation, composer
  tools/        SEC EDGAR, Finnhub adapter, send_email — MCP-exposed
  prompts/      shared system prompt fragments
  orchestrator.py   entrypoint
web/            Cloudflare Workers app (login + watchlist CRUD)
db/schema.sql   shared schema, source of truth for both sides
.github/workflows/daily-pipeline.yml   cron trigger
```
