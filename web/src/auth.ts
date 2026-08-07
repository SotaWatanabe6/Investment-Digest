/**
 * Password verification and signed session cookies for the single-user
 * login gate (PRD Section 6: repo is public, deployment must stay
 * private). Uses only Web Crypto APIs available in the Workers runtime —
 * no native bcrypt/argon2 binding is available there, so PBKDF2-SHA256
 * (also Web Crypto native) is the password hash, and HMAC-SHA256 signs
 * the session cookie.
 */
import type { Env } from "./db";

const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7; // 7-day idle expiry
// OWASP recommends 210,000+ for PBKDF2-SHA256 as of 2026, but the Workers
// runtime's Web Crypto implementation hard-caps PBKDF2 at 100,000
// iterations (throws NotSupportedError above that) — this is the max
// usable value here, not a security choice.
const PBKDF2_ITERATIONS = 100_000;

function toHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function fromHex(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

/**
 * Format: pbkdf2$<iterations>$<salt-hex>$<hash-hex>
 * Generate this once via `node scripts/hash-password.mjs` (see README) and
 * store the result as the PASSWORD_HASH Worker secret — never the raw
 * password itself.
 */
export async function hashPassword(password: string, salt?: Uint8Array): Promise<string> {
  const saltBytes = salt ?? crypto.getRandomValues(new Uint8Array(16));
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const derived = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: saltBytes, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    keyMaterial,
    256
  );
  return `pbkdf2$${PBKDF2_ITERATIONS}$${toHex(saltBytes.buffer as ArrayBuffer)}$${toHex(derived)}`;
}

export async function verifyPassword(password: string, storedHash: string): Promise<boolean> {
  const [scheme, iterationsStr, saltHex] = storedHash.split("$");
  if (scheme !== "pbkdf2") return false;
  const salt = fromHex(saltHex);
  const candidate = await hashPassword(password, salt);
  // Constant-time-ish comparison: compare full strings rather than
  // short-circuiting, to avoid leaking hash-length timing information.
  return candidate.length === storedHash.length && candidate === storedHash;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

export async function createSessionCookie(secret: string): Promise<string> {
  const expiresAt = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const payload = `${expiresAt}`;
  const key = await hmacKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  const token = `${payload}.${toHex(signature)}`;
  return `session=${token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${SESSION_TTL_SECONDS}`;
}

export async function verifySession(cookieHeader: string | null, secret: string): Promise<boolean> {
  if (!cookieHeader) return false;
  const match = cookieHeader.match(/session=([^;]+)/);
  if (!match) return false;

  const [payload, signatureHex] = match[1].split(".");
  if (!payload || !signatureHex) return false;

  const key = await hmacKey(secret);
  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    fromHex(signatureHex),
    new TextEncoder().encode(payload)
  );
  if (!valid) return false;

  const expiresAt = parseInt(payload, 10);
  return Number.isFinite(expiresAt) && expiresAt > Math.floor(Date.now() / 1000);
}

export const CLEAR_SESSION_COOKIE =
  "session=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0";

export type { Env };
