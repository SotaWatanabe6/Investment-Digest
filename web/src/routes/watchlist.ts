import { Hono } from "hono";
import { getDb, type Env } from "../db";

export const watchlistRoutes = new Hono<{ Bindings: Env }>();

const VALID_TYPES = new Set(["stock", "mutual_fund", "etf"]);
// Loose ticker validation: 1-5 letters, optionally with a single dot
// (e.g. BRK.B) — real-world validation (does this symbol actually exist)
// happens implicitly the first time the pipeline queries SEC EDGAR/Finnhub
// for it; this route just guards against obviously malformed input.
const SYMBOL_PATTERN = /^[A-Z]{1,5}(\.[A-Z])?$/;

watchlistRoutes.get("/watchlist", async (c) => {
  const db = getDb(c.env);
  const result = await db.execute(
    "SELECT id, symbol, type, full_name, added_at FROM holding WHERE active = 1 ORDER BY symbol"
  );
  return c.json({ holdings: result.rows });
});

watchlistRoutes.post("/watchlist", async (c) => {
  const body = await c.req.json<{ symbol?: string; type?: string; full_name?: string }>().catch(() => null);
  if (!body?.symbol || !body?.type || !body?.full_name) {
    return c.json({ error: "symbol, type, and full_name are required" }, 400);
  }

  const symbol = body.symbol.trim().toUpperCase();
  if (!SYMBOL_PATTERN.test(symbol)) {
    return c.json({ error: "invalid symbol format" }, 400);
  }
  if (!VALID_TYPES.has(body.type)) {
    return c.json({ error: "type must be one of: stock, mutual_fund, etf" }, 400);
  }

  const db = getDb(c.env);
  try {
    await db.execute({
      sql: "INSERT INTO holding (symbol, type, full_name) VALUES (?, ?, ?)",
      args: [symbol, body.type, body.full_name.trim()],
    });
  } catch (err) {
    // UNIQUE constraint on symbol is the duplicate-prevention mechanism
    // (US-1 acceptance criteria) — surface it as a clean 409 rather than a
    // raw DB error.
    if (String(err).includes("UNIQUE")) {
      return c.json({ error: `${symbol} is already on the watchlist` }, 409);
    }
    throw err;
  }

  return c.json({ ok: true }, 201);
});

watchlistRoutes.delete("/watchlist/:id", async (c) => {
  const id = Number(c.req.param("id"));
  if (!Number.isInteger(id)) {
    return c.json({ error: "invalid id" }, 400);
  }

  const db = getDb(c.env);
  // Soft delete: historical digest_history/holding_digest_entry rows for
  // this holding are retained for audit purposes (US-2 acceptance
  // criteria), only future pipeline runs stop including it.
  await db.execute({ sql: "UPDATE holding SET active = 0 WHERE id = ?", args: [id] });

  return c.json({ ok: true });
});
