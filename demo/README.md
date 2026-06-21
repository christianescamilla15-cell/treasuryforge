# TreasuryForge Live Demo

Interactive browser demo of the 4-layer agent safety architecture documented in the parent repo.

## What this shows

- **AGENT** proposes Intent objects on each simulated tick (deterministic mean-reversion strategy that occasionally produces silly intents to trigger DENYs)
- **POLICY ENGINE** evaluates every intent against the 8 hard rules (kill_switch, circuit_breaker, staleness, allowlist, per_tx_cap, rate_limit, spend_budget, solvency). Rules that fire visually flash in the UI
- **EXECUTOR + WALLET** fills only approved intents; balances are mutated and rendered live
- **TAMPER-EVIDENT AUDIT** chain accumulates HMAC-SHA256 hash-linked entries; the demo verifies chain integrity every 5 entries

## Interactive controls

- **Run simulation** — auto-step through the 40-tick price track at 600ms/tick
- **Step 1 tick** — single-step manually
- **Trigger SIGKILL** — simulates a hard kill, journals state, restarts. The breaker survives if it was tripped (matches the real `os._exit(1)` subprocess test in `tests/core/test_journal.py`)
- **Reset** — back to zero

## How this maps to the Python code

| UI component | Source of truth |
|---|---|
| `policyEvaluate()` in demo.js | [`treasuryforge/policy.py::PolicyEngine.evaluate()`](../treasuryforge/policy.py) |
| The 8 rule pills | The 8 rules enforced in order in `policy.py` lines 82-155 |
| HMAC audit chain | [`treasuryforge/audit.py`](../treasuryforge/audit.py) — same canonical-JSON + chain pattern |
| SIGKILL recovery | [`treasuryforge/journal.py`](../treasuryforge/journal.py) WAL + atomic checkpoint via `os.replace()` |
| State `snapshot()/restore()` | `PolicyEngine.snapshot()` / `restore()` in `policy.py` lines 167-181 |

The Python implementation is the source of truth and is property-fuzzed with Hypothesis over the same 8 invariants. This JS port exists only so visitors can interact with the architecture without installing anything.

## Deploy

Static site — drop into Vercel from this folder:

```bash
vercel deploy demo/ --prod
```

Or via Vercel dashboard: Project Settings → Root Directory → `demo`. The `vercel.json` in the repo root already routes `/` to this folder.

## Stack

Zero dependencies. Vanilla HTML + CSS + JS. Web Crypto API for HMAC-SHA256.
