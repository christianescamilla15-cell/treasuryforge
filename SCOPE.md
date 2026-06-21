# treasuryforge — Scope & Conduct

This document is the explicit, intentional boundary of what treasuryforge is and
is not. It exists because the legal/regulatory safety of the project depends on
staying inside this boundary (see `PHASE3_IMPLEMENTATION.md` §7).

## What this is

- A **single-user**, personal automation operating **only the owner's own funds**.
- Non-institutional, non-commercial. A solo builder's tool.

## The bright line — never cross

- ❌ **Never accept, pool, custody, or trade third-party funds.**
- ❌ **Never offer paid signals, copy-trading, or management-as-a-service.**
- ❌ **Never give investment advice to others for compensation.**

Crossing any of these can trigger CNBV "Asesor en Inversiones" registration
and/or the provider AML regime in Mexico. Trading one's own funds as an
individual is legal and unlicensed; managing others' money is a different legal
category entirely.

## Security posture (enforced in code, not by discipline)

- Exchange API keys are **trade-only, no-withdrawal, IP-allowlisted**.
- The executor has **zero withdrawal code path**.
- The policy engine bounds blast radius (caps, rate limit, spend budget, breaker).
- Funds stay in exchange custody at this size; rare manual withdrawals go through
  the authenticated web UI with 2FA + address allowlist — never the bot key.

## Tax & legal

- The owner is responsible for record-keeping from the first trade (per-fill,
  per-lot ledger; ~5-year retention).
- All tax/legal specifics must be confirmed with a Mexican **contador / primary
  SAT source** before selling or scaling. Nothing here is legal or tax advice.
