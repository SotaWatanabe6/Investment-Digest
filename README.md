# Investment Digest

## TL;DR

Investment Digest is a daily-email tool that watches a personal investment
watchlist — stocks, ETFs, mutual funds — and sends one consolidated digest
per holding combining SEC filing facts, financial news, a discrepancy
analysis between the two, and macro context. It's built as a multi-agent AI
pipeline (screening → extraction → validation → composition) that runs
once a day, costs under $1/month to operate, and is deliberately scoped as
an **aggregation tool, not a prediction tool** — it never scores, ranks, or
recommends.

---

## The Problem

Actually tracking a watchlist properly means checking SEC EDGAR for insider
filings, several financial news sites, and macro/sector context — every
day, for every holding — and then manually cross-referencing whether what
the news is saying actually lines up with what the primary-source filings
say. In practice, nobody does this consistently. Existing tools either
alert on raw filing events with no synthesis, or lean toward prediction and
scoring (which introduces a different problem: false confidence dressed up
as signal).

## Who It's For, and How It's Used

This is a personal tool, built for a single user tracking a small,
real watchlist. The entire "how you use it" surface is deliberately thin:

1. **A minimal private web page** — log in, add or remove holdings
   (ticker, type, full name). That's the whole UI. It is not a dashboard
   you're meant to check regularly.
2. **One email a day.** The product's real interface is your inbox. Every
   morning, one digest arrives covering the full watchlist — one section
   per holding, in a fixed order, ending with "nothing to report" for any
   holding with no new activity in the period (never silently omitted).

There is no chat interface, no notifications feed, no mobile app. The
entire point is that the tool disappears except for the one email.

---

## The How

Everything below was a deliberate decision made *before* writing code, not
a default reached for out of convenience. Each choice has a reason, and
several reasons only became fully validated once real bugs surfaced during
build and testing (noted where relevant).

### Platform & Scope

**Decision:** Server-side pipeline + a lightweight web page for watchlist
management only. No browser extension.

**Why:** A Chrome extension was explicitly considered and rejected. The
actual data-gathering work has to run server-side regardless of what the
front end looks like (it needs to hit SEC EDGAR and news APIs on a
schedule, independent of whether a browser is open), and a browser
extension adds app-store/permission overhead for zero benefit once that's
true. A plain web page works identically from a phone or laptop with none
of that overhead.

**Decision:** Aggregation and categorization only — explicitly not a
prediction, scoring, or advice product. No backtesting. No confidence
scores. Comparison output uses descriptive language only
("agreement" / "disagreement" / "unsupported by primary data").

**Why:** This is the single most load-bearing decision in the whole
product. A tool that aggregates primary-source facts and flags where
narratives diverge is defensible and genuinely useful. A tool that scores
or predicts is a different (and much riskier, both practically and
in terms of liability) product entirely. Every downstream architecture
decision — prompt design, schema design, even variable naming
(`discrepancy_analysis`, never `confidence_score`) — traces back to this.

### Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Pipeline language | Python | Strongest ecosystem for LLM agent orchestration (SDKs for Anthropic, structured data handling), and the best fit for the team's own strengths. |
| Web app | Cloudflare Workers | The watchlist page is visited rarely (add/remove a holding, check in occasionally) — serverless wakes-on-request hosting is a natural fit, and it's genuinely free at this scale, unlike an always-on PaaS box that bills whether or not anyone visits. |
| Database | Turso (libSQL) | The pipeline (Python, GitHub Actions) and the web app (Cloudflare Workers, TypeScript) are two completely different runtimes that both need to read/write the same data. Turso is accessible natively from both without an API-bridge layer in between (unlike Cloudflare D1, which would require the Python side to go through an HTTP wrapper for every query). |
| Scheduling | GitHub Actions cron | Free scheduled-workflow minutes on a public repo — no server needs to stay running for a once-a-day job. |
| LLM provider | Anthropic (Claude) | Strong structured-output reliability for the schema-enforced multi-agent design below (see Model Choices). |
| News + macro data | Finnhub, behind a swappable adapter | Single vendor, generous free tier, sufficient coverage — but wrapped behind an interface (`NewsProvider`) so swapping to NewsAPI.org or FRED later doesn't touch any agent or orchestration code. |
| Filings data | SEC EDGAR directly | Free, authoritative, and the actual primary source — not behind an adapter, because there's no "alternative" to the ground truth. |
| Email delivery | Resend, free tier | Sufficient volume for one recipient/day at zero cost. |
| Auth | Password + signed session cookie (PBKDF2 + HMAC, Web Crypto only) | The repo is public — the code being visible doesn't matter, but the *running deployment* has to stay private. A single-user password gate is the minimum viable protection for that; anything more (OAuth, multi-user accounts) would be solving a problem that doesn't exist here. |

### AI Agent Architecture

The pipeline is a **fixed four-stage backbone** — screening → extraction →
validation → composition — with two narrowly-scoped agent-directed steps
inside it, not an open-ended autonomous agent loop.

```
Screening (cheap model, per holding)
  → "has anything changed since the last digest?"
  → if no: skip straight to "nothing to report," at near-zero cost

Extraction (3 parallel calls, only if screening says yes)
  → filings (SEC EDGAR)   → news (Finnhub)   → macro (Finnhub)
  → each is a *separate* pull, not one blended query

Validation (cross-reference)
  → compares news claims against each other and against the hard facts
  → can request one additional round of context if the initial pull
    is too thin to say anything meaningful — the one place the agent
    is allowed to redirect its own next step

Composition
  → assembles the fixed email template, computes the run's total cost,
    and is the only agent with a real side-effect (sending the email)
```

**Why a fixed backbone instead of a free-roaming agent:** an
open-ended agent deciding what to do next is harder to reason about,
harder to cost-cap, and unnecessary here — the actual task ("gather from
these three sources, compare them, write a summary") doesn't benefit from
letting a model improvise its own plan. The two agent-directed exceptions
(news extraction pull depth, validation's one context-request retry) were
added deliberately and narrowly, not as a general capability.

**Why the screening gate specifically:** it's the token-cost optimization
that makes the whole thing affordable. Running full extraction + validation
on every holding, every day, regardless of whether anything happened,
would multiply cost for no benefit — most holdings on most days have no
new activity at all.

**Why extraction is three separate calls, not one combined prompt:** hard
facts, news, and macro context are fundamentally different categories of
information from different sources, and blending them into one prompt
would blur the "primary source vs. subjective" distinction that the whole
discrepancy-analysis step depends on downstream. Keeping them separate
also means one source's failure (see Data Strategy below) only degrades
one part of the output, not the whole holding.

**Why the validation agent gets a limited retry, capped at one:** letting
it request more context when the initial pull is genuinely too thin to
say anything useful improves output quality on real edge cases (a quiet
news day with one ambiguous headline, for example) — but capping it at a
single retry means a persistently uncertain agent can't loop indefinitely
and blow through the cost ceiling.

**Why the orchestration code coordinates every step, rather than agents
calling each other as tools:** simpler to reason about, debug, and
cost-track. Every LLM call's token usage and cost is logged individually
regardless of what the model decided to do, which wouldn't be as clean if
agents were freely handing off to each other.

### Model Choices

**Decision:** Claude Haiku 4.5 for the screening gate; Claude Sonnet 5 for
extraction, validation, and composition.

**Why:** Screening is a cheap binary decision ("did anything happen?") —
it doesn't need a strong model, and running the cheapest capable model on
*every single holding, every single day* (the highest-frequency call in
the whole pipeline) is where model tier actually matters for cost.
Extraction, validation, and composition need real reasoning quality —
correctly identifying a buy vs. a sell in a filing, or noticing that a
news claim isn't actually supported by the filing it's citing — so a
stronger model is worth the cost there, especially since those calls only
fire when screening has already confirmed there's something worth
analyzing.

**Why not a single model tier for everything:** would either overpay for
the screening gate (running Sonnet on every holding daily regardless of
activity) or underpower the actual analysis (running Haiku on the
discrepancy-detection step, where reasoning quality is the entire point).

**Why every agent enforces structured (JSON-schema) output instead of
free text:** reliable parsing between pipeline stages and deterministic
final-email assembly. A composer that has to re-parse loosely-formatted
free text from four upstream agents is a fragile design; forcing schema
compliance via tool-use means each stage's output is a typed contract, not
a string to interpret.

### Data Strategy

**Decision:** No RAG, no fine-tuning.

**Why:** There's no proprietary knowledge base to retrieve over — every
data point (a filing, a news article, a macro snapshot) is fetched fresh
from an external API each run and handed to the model as text to analyze
in that same call. RAG solves "search over a large corpus of our own
data," which isn't the problem here. Fine-tuning solves tone/format/latency
problems that a well-structured prompt and forced schema output already
solve more cheaply.

**Decision:** A 7-day rolling "compact summary" per holding, capped at
~200 tokens/day, feeds the validation agent — not full historical digest
text.

**Why:** The validation agent benefits from noticing patterns across days
(a cluster of insider buys building over a week reads differently than one
isolated buy), but feeding it full prior digests would be expensive and
mostly redundant. A capped, dense summary gives it pattern-level context
at near-zero marginal cost.

**Decision:** External data sources degrade independently and gracefully
— one source failing returns an empty result for that holding rather than
crashing the run.

**Why, concretely:** this wasn't a hypothetical design principle — it's
exactly what happened in practice. Finnhub's free news endpoint 403s on
mutual fund symbols (it's stock-only), and a malformed agent response
crashed an entire run before this was corrected. Every external call is
now wrapped so a bad response from one source degrades *that piece* of
*that holding*, never the whole digest.

### Evaluation & Observability

**Decision:** Structured per-agent logging of every call (tokens, cost,
duration, status), an audit trail of every digest's exact output, and
automated eval against known historical filings as the pipeline matures
past MVP.

**Why:** A financial-data product that can't show its own work isn't
trustworthy, even to its own single user. Every digest's cost is broken
down per holding and per agent stage, queryable after the fact — which is
also what made it possible to actually diagnose real production issues
(a $0.17 run's cost breakdown showing PLTR's news extraction as the
expensive outlier, for instance) rather than treating the pipeline as a
black box.

### Governance & Safety Design

**Decision:** Ingested external content (filing text, news articles) is
explicitly treated as untrusted data, never instructions, via a shared
system-prompt preamble every agent uses.

**Why:** Any pipeline that feeds scraped/fetched external text into an LLM
prompt has a prompt-injection surface — a malicious or malformed article
could contain text attempting to redirect the model's behavior. The blast
radius here is low (no trading actions, no write access beyond composing
an email), but the mitigation is cheap enough that there's no reason to
skip it.

**Decision:** The one agent capability with a real side effect — sending
the email — is hard-capped at one send per covered period, enforced in
code at the tool boundary, not just via a system-prompt instruction.

**Why:** A prompted instruction is a suggestion; a code-level check is
actual access control. If an agent ever misbehaves or a run gets triggered
twice, the send limit means the worst case is a silently-dropped digest,
never a duplicate or a spam loop — this is deliberately designed to fail
safe.

**Decision:** A hard daily spend ceiling aborts a run mid-flight rather
than letting cost run unbounded.

**Why:** Same principle as the send cap — a runaway loop or an unexpected
pricing change should have a hard, code-enforced stop, not just a
best-effort budget target.

---

## The What

**This tool is a working, self-hosted daily digest pipeline**: a
multi-agent Claude pipeline (screening, extraction, validation,
composition) that reads real SEC filings and real financial news for a
watchlist, cross-references what it finds, and emails one consolidated,
non-predictive summary every day — running end-to-end on free-tier
infrastructure for well under $1/month, with cost tracking, an audit
trail, and safety-critical actions enforced as real access control rather
than prompt suggestions.

---

## Getting Started

Provisioning the actual accounts (Turso, Anthropic, Finnhub, Resend,
Cloudflare, GitHub) and running the first real digest is a one-time setup
covered here.

### 1. Provision accounts (all free tier at this volume)

- **Turso**: create a database via [app.turso.tech](https://app.turso.tech) or `turso db create investment-digest` — note the database URL and create an auth token.
- **Anthropic**: create an API key at [console.anthropic.com](https://console.anthropic.com).
- **Finnhub**: free API key at [finnhub.io](https://finnhub.io).
- **Resend**: free API key at [resend.com](https://resend.com); either use the shared `onboarding@resend.dev` sender or verify your own domain.
- **Cloudflare**: a Workers-enabled account (free tier).
- **GitHub**: this repo, with Actions enabled.

### 2. Set up the database

```bash
turso db shell investment-digest < db/schema.sql
turso db shell investment-digest "INSERT INTO user (id) VALUES (1);"
```

Add holdings directly via SQL, or once the web app is deployed, through its UI:

```bash
turso db shell investment-digest "INSERT INTO holding (symbol, type, full_name) VALUES ('AAPL', 'stock', 'Apple Inc.');"
```

### 3. Configure pipeline secrets (GitHub Actions)

As repo **secrets**: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`,
`ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `RESEND_API_KEY`,
`DIGEST_TO_EMAIL`, `DIGEST_FROM_EMAIL`.

As a repo **variable**: `DAILY_SPEND_CEILING_USD` (e.g. `2.0`).

The cron schedule lives in `.github/workflows/daily-pipeline.yml` —
GitHub Actions cron only runs on fixed UTC times, so adjust for your
timezone (and re-adjust manually across daylight saving, since cron can't
do that automatically).

### 4. Deploy the web app (Cloudflare Workers)

```bash
cd web
npm install
node scripts/hash-password.mjs "your-chosen-password"   # copy the output hash
wrangler secret put PASSWORD_HASH        # paste the hash from above
wrangler secret put SESSION_SECRET       # paste any long random string
wrangler secret put TURSO_DATABASE_URL
wrangler secret put TURSO_AUTH_TOKEN
npm run deploy
```

Visit the deployed URL, log in, and confirm you can add/remove a holding.

### 5. End-to-end verification

1. Manually trigger **Daily Digest Pipeline** from the Actions tab
   (`workflow_dispatch`) rather than waiting for the cron.
2. Confirm the digest email arrives: holdings in the fixed order (Hard
   Facts → Subjective Info → Discrepancies → Macro Influence), "nothing to
   report" shown rather than omitted where applicable, and a footer with
   total cost + the not-investment-advice disclaimer.
3. Check the `digest_run` and `agent_run_log` tables in Turso to confirm
   cost tracking and the audit trail are populating correctly.
4. Trigger the workflow a second time the same day and confirm the second
   send is refused — the max-1-send-per-period safeguard working as
   designed.

## What's Deliberately Not Here Yet (Phase 2)

Configurable send time via the UI, global pause/resume, a cost-history
view, and a fuller observability stack are explicitly out of scope for
this build — see `technical-prd.md` for the full phased plan.

## Project Layout

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
