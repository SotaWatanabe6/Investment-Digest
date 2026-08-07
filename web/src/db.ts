/**
 * Turso (libSQL) client for the web app.
 *
 * Talks to the same database as the Python pipeline (pipeline/db.py) —
 * schema is defined once in db/schema.sql and is the shared contract
 * between both sides. See technical-prd.md Section 4.3.
 */
import { createClient, type Client } from "@libsql/client/web";

export interface Env {
  TURSO_DATABASE_URL: string;
  TURSO_AUTH_TOKEN: string;
  SESSION_SECRET: string;
  PASSWORD_HASH: string;
}

export function getDb(env: Env): Client {
  return createClient({
    url: env.TURSO_DATABASE_URL,
    authToken: env.TURSO_AUTH_TOKEN,
  });
}
