import { Hono } from "hono";
import { getDb, type Env } from "../db";
import { createSessionCookie, verifyPassword, CLEAR_SESSION_COOKIE } from "../auth";

export const loginRoutes = new Hono<{ Bindings: Env }>();

const MAX_FAILED_ATTEMPTS = 5;
const LOCKOUT_MINUTES = 15;

loginRoutes.post("/login", async (c) => {
  const body = await c.req.json<{ password?: string }>().catch(() => null);
  if (!body?.password) {
    return c.json({ error: "password required" }, 400);
  }

  const db = getDb(c.env);

  // Rate limiting: PBKDF2 adds some per-attempt cost on its own, but
  // nothing was actually stopping unlimited automated password guessing
  // against a publicly reachable endpoint. Tracked in the single user row
  // rather than a separate table/KV namespace, since there's exactly one
  // account and this DB connection already exists.
  const userRow = await db.execute("SELECT failed_login_attempts, lockout_until FROM user WHERE id = 1");
  const row = userRow.rows[0];
  const lockoutUntil = row?.lockout_until as string | null;
  if (lockoutUntil && new Date(lockoutUntil).getTime() > Date.now()) {
    return c.json({ error: "Too many failed attempts. Try again later." }, 429);
  }

  const valid = await verifyPassword(body.password, c.env.PASSWORD_HASH);
  if (!valid) {
    const failedAttempts = ((row?.failed_login_attempts as number) ?? 0) + 1;
    if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
      const lockUntil = new Date(Date.now() + LOCKOUT_MINUTES * 60 * 1000).toISOString();
      await db.execute({
        sql: "UPDATE user SET failed_login_attempts = 0, lockout_until = ? WHERE id = 1",
        args: [lockUntil],
      });
    } else {
      await db.execute({
        sql: "UPDATE user SET failed_login_attempts = ? WHERE id = 1",
        args: [failedAttempts],
      });
    }
    return c.json({ error: "invalid password" }, 401);
  }

  await db.execute("UPDATE user SET failed_login_attempts = 0, lockout_until = NULL WHERE id = 1");

  const cookie = await createSessionCookie(c.env.SESSION_SECRET);
  c.header("Set-Cookie", cookie);
  return c.json({ ok: true });
});

loginRoutes.post("/logout", (c) => {
  c.header("Set-Cookie", CLEAR_SESSION_COOKIE);
  return c.json({ ok: true });
});
