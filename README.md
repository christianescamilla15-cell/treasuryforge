# treasuryforge

Local-first sandbox to validate an **autonomous treasury agent** — one that runs a
decision loop, manages a balance, and executes trades — **with zero keys, zero
funds and zero network calls**. The whole point of this phase is to prove the
*architecture* is correct and safe before a single real dollar is at risk.

## The one idea that matters

```
  AGENT  (brain / strategy / LLM)        can be wrong, can hallucinate
     │   proposes an Intent (never acts directly)
     ▼
  POLICY ENGINE  (hard, non-negotiable rules)   DOES NOT TRUST THE AGENT
     │   approves or denies
     ▼
  EXECUTOR + WALLET  (executes only within enforced limits)
```

The agent never touches the wallet. It only *proposes*. A separate policy layer
applies hard limits (max per trade, allowlist, rate limit, drawdown breaker,
kill switch, solvency) and only approved intents ever reach execution. In the
real system the policy is enforced by the wallet itself (MPC session caps /
smart-account policy); here it's enforced in code so we can validate the logic
risk-free.

## Run it

```bash
python -m pytest -q          # 20 validation gates
python run_demo.py --steps 120            # normal market
python run_demo.py --crash --steps 80     # crash -> circuit breaker trips
python run_demo.py --crash --ledger       # print the full audit ledger
```

## Modules

| File | Role | Real-world counterpart |
|------|------|------------------------|
| `agent.py` | brain — proposes intents (deterministic mean-reversion) | LLM / strategy engine |
| `policy.py` | **the guardrail** — 8 hard rules, trusts nothing, crash-safe state | wallet session caps / smart-contract policy |
| `executor.py` | fills an approved intent (the **swap point**) | Kraken paper mode / Coinbase AgentKit on testnet |
| `wallet.py` | balances, never goes negative, never mints value | MPC / agentic wallet |
| `market.py` | deterministic seeded price feed | real market data feed |
| `runner.py` | the 24/7 loop, t+1 fills, journal + audit hooks | service loop (nssm / VPS) |
| `journal.py` | crash-only WAL + atomic state checkpoints | durable ops state |
| `audit.py` | HMAC hash-chained tamper-evident decision log | compliance / forensics |
| `sizing.py` | vol-targeting size ceiling (never breaches the cap) | risk sizing |
| `backtest/` | CostModel + Sharpe/DSR + purged-CV promotion gate | "validate before funds" gate |

### Phase-2 hardening (implemented, all validated in Sim)

Driven by a 164-agent deep-research pass (see `PHASE2_DISCOVERY.md`). The policy
engine now enforces **8 rules** in order: kill-switch → drawdown breaker →
staleness → allowlist → per-tx notional cap → rate limit → **cumulative spend
budget** → solvency. Key additions:

- **Crash-safe latched state** — fixes a real bug the research found: the breaker
  and drawdown anchor were in-memory, so a restart silently un-tripped the
  breaker. State is now journaled (atomic `os.replace`) and restored on startup.
  A subprocess `os._exit(1)` crash test proves the breaker survives a hard kill.
- **Spend budget** (`max_notional_per_window`) closes the drip-drain gap a
  count-only rate limit leaves open.
- **Point-in-time / t+1 fills** — the agent decides on tick *t* but fills at *t+1*,
  so it can never trade on the bar it is still forming (the #1 backtest bug).
- **Tamper-evident audit log**, **vol-targeting sizing ceiling**, and a
  **cost-and-overfitting-aware backtest gate** (Deflated Sharpe Ratio +
  purged/embargoed CV) — the discovery's highest-confidence "validate before
  funds" deliverable.
- **Property-based fuzzing** (`hypothesis`, tests-only) drives thousands of
  arbitrary histories through the real loop and asserts every safety invariant.

## Validation gates (what "it works correctly" means here)

- **Deterministic** — same seed → identical fills and final equity (bit-exact).
- **Conservation** — final equity reconciles exactly to fills + fees; the system
  can only bleed friction, never create value out of thin air.
- **No negative balances** — ever, across full runs.
- **Every guardrail provably fires** — kill switch, allowlist, notional cap, rate
  limit, drawdown breaker (trips and stays tripped), solvency.

Note: the circuit breaker *stops further trading*; it does not reverse a loss on
a position already held while the market falls. That's realistic — a breaker
limits additional damage, it doesn't undo the market.

## Going real later (separate, deeper discovery — do NOT skip the gates)

The only file that changes is `executor.py`. Add a new class with the same
`execute(intent, tick, wallet)` signature:

1. **Paper** — `PaperExecutor` backed by Kraken CLI paper mode. Still no funds.
2. **Testnet** — `OnchainExecutor` via Coinbase AgentKit + an MPC/agentic wallet
   on Base Sepolia. Real signing, fake money. Caps set ridiculously low.
3. **Mainnet** — same, tiny caps first, scaled only after on-chain proof that the
   limits and kill switch hold.

The agent, policy engine, wallet abstraction, runner and every test stay
unchanged. That's the payoff of validating the architecture first.
