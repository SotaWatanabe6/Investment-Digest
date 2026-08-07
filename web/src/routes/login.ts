import { Hono } from "hono";
import type { Env } from "../db";
import { createSessionCookie, verifyPassword, CLEAR_SESSION_COOKIE } from "../auth";

export const loginRoutes = new Hono<{ Bindings: Env }>();

loginRoutes.post("/login", async (c) => {
  const body = await c.req.json<{ password?: string }>().catch(() => null);
  if (!body?.password) {
    return c.json({ error: "password required" }, 400);
  }

  const valid = await verifyPassword(body.password, c.env.PASSWORD_HASH);
  if (!valid) {
    return c.json({ error: "invalid password" }, 401);
  }

  const cookie = await createSessionCookie(c.env.SESSION_SECRET);
  c.header("Set-Cookie", cookie);
  return c.json({ ok: true });
});

loginRoutes.post("/logout", (c) => {
  c.header("Set-Cookie", CLEAR_SESSION_COOKIE);
  return c.json({ ok: true });
});
