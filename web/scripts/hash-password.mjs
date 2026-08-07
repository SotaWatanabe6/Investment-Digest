#!/usr/bin/env node
// Generates a PASSWORD_HASH value to set as a Worker secret. Run locally,
// never commit the output anywhere in the repo — it goes straight into
// `wrangler secret put PASSWORD_HASH`.
//
// Usage: node scripts/hash-password.mjs "your-chosen-password"

import { webcrypto as crypto } from "node:crypto";

// Must match web/src/auth.ts exactly — the Workers runtime's PBKDF2
// implementation hard-caps at 100,000 iterations.
const PBKDF2_ITERATIONS = 100_000;

function toHex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function hashPassword(password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const derived = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    keyMaterial,
    256
  );
  return `pbkdf2$${PBKDF2_ITERATIONS}$${toHex(salt)}$${toHex(derived)}`;
}

const password = process.argv[2];
if (!password) {
  console.error("Usage: node scripts/hash-password.mjs \"your-chosen-password\"");
  process.exit(1);
}

const hash = await hashPassword(password);
console.log(hash);
