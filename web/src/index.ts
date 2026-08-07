import { Hono } from "hono";
import type { Env } from "./db";
import { verifySession } from "./auth";
import { loginRoutes } from "./routes/login";
import { watchlistRoutes } from "./routes/watchlist";
import { renderPage } from "./ui";

const app = new Hono<{ Bindings: Env }>();

// Every route except POST /login is behind the session-cookie gate (PRD
// Section 6: the deployment must stay private even though the repo is
// public). The login page itself is served unauthenticated so there's
// somewhere to submit the password from.
app.use("/*", async (c, next) => {
  if (c.req.path === "/login" || c.req.path === "/api/login") {
    return next();
  }
  const authed = await verifySession(c.req.header("Cookie") ?? null, c.env.SESSION_SECRET);
  if (!authed) {
    if (c.req.path.startsWith("/api/")) {
      return c.json({ error: "unauthorized" }, 401);
    }
    return c.redirect("/login");
  }
  return next();
});

app.route("/api", loginRoutes);
app.route("/api", watchlistRoutes);

app.get("/login", (c) => c.html(renderPage("login")));
app.get("/", (c) => c.html(renderPage("watchlist")));

export default app;
