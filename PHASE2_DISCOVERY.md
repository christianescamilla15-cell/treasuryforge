# treasuryforge — Phase-2 Discovery Report

*Scope: best currently-real (2026) techniques to empower an autonomous, local-first, stdlib-only crypto treasury agent across strategy, safety, execution, custody and ops — actionable for a solo builder, validated before any real funds. Findings below are drawn only from the per-theme synthesis and the adversarial verdicts; maturity and risk are stated honestly, and a recommendation of "high impact" in the raw synthesis is downgraded wherever a verdict refuted it.*

---

## 1. Executive Summary

- **The existing architecture is the finding.** Across all ten themes the load-bearing conclusion is that `agent PROPOSES → hard-rule POLICY disposes → wallet EXECUTES within enforced limits` is exactly the de-facto production safety pattern for 2026 money-handling agents, independently vindicated by real exploit post-mortems (Grok-Bankr $150K Morse-code injection; the malicious-LLM-router ETH drain; ElizaOS memory-poisoning). **Keep it untouched; harden it. Do not move safety into the LLM layer — prompt injection is unsolvable at the model level.**

- **Mechanical/quant beats LLM-discretionary for THIS agent — decisively.** Every agent that touched the strategy question lands on rule-expressible signals (funding carry, vol-scaled momentum, cointegration pairs) and relegates any LLM to an *optional, noisy feature* feeding PROPOSE, never a trigger and never a safety layer. A verdict makes this self-enforcing: the overfitting promotion gate (DSR/CPCV) is *structurally incompatible* with LLM-discretionary strategies (uncountable trials), so adopting the gate is itself a vote for mechanical.

- **The decisive deliverable is a validation discipline, not a model.** A causal, friction-and-liquidation-aware backtest + cost model, gated by purged-CV + Deflated Sharpe Ratio, is the single most-repeated, highest-confidence recommendation. Verdicts rate it `adopt-now`. Nearly every published edge evaporates under realistic fees/slippage/borrow/liquidations; this gate is what stops the agent acting on a backtest mirage and makes "validated before real funds" honest.

- **Several "high-impact" headline numbers are fabricated or misattributed and must not be trusted.** Adversarial verification found: the vol-targeting "DD −31%→−14% / Sharpe 0.99→1.54" figures appear in *no cited source* (likely fabricated; the real source shows −31%→−19% / 0.90→1.34 on a *stock-bond* portfolio, not crypto); the TSMOM "Sharpe ~1.83 OOS" is cherry-picked (plain vol-scaled TSMOM is ~0.65 net-of-cost in 2022–24); the funding-arb reference repo (aoki-h-jp) is unmaintained since 2023, CCXT-based, and does not even support Hyperliquid; the "PAL 95% first-retry" and "15c3-5/Reg-AT compliance match" claims are invented or invoke a withdrawn rule (CFTC Reg-AT). **Re-derive every number on your own out-of-sample data.**

- **A real correctness BUG exists in the current build.** `PolicyEngine._tripped / _starting_equity / _recent_ts` and the run ledger are in-memory only. A crash/restart silently *un-trips* a latched drawdown circuit-breaker and re-anchors the drawdown floor to post-loss equity. This is a money-relevant defect and is `adopt-now` to fix (WAL journal + snapshot/restore + startup reconciliation).

- **The three Phase-2 decisions partially answer themselves.** Strategy → **mechanical** (strongly). Chain/exchange → **CEX-first (Kraken paper) as the live-money rung, EVM/Base wired in parallel behind it** — the validation tooling, dead-man switch, and scoped no-withdraw keys are all more mature on the CEX path. Custody → genuinely **unresolved** (managed-MPC lower-friction vs self-hosted smart-account self-custodial); this is the one decision the owner must make, not the research.

- **Cheap, stdlib-only, zero-risk wins dominate the near term.** Vol-targeting sizing (~20 lines), a staleness gate, an HMAC hash-chained audit log, cumulative spend budgets, Hypothesis stateful fuzzing of the policy engine, and a Page-Hinkley degradation detector are all pure-stdlib, validatable entirely in SimExecutor, and carry near-zero downside (their failure mode is *fail-safe*: deny/halt, never a bad trade).

- **Honesty about evidence is unanimous.** The agentic-trading field is empirically immature (0/19 studies fully reproducible; most LLM agents fail to beat buy-and-hold; multi-agent committees help in ~20% of configs). Keep real-fund notional caps tiny, treat all discretionary strategy as experimental, and prove every added component in Sim before promoting.

---

## 2. The Three Phase-2 Decisions

### Decision 1 — Chain / Exchange: **CEX-first (Kraken) for live money; EVM/Base (Hyperliquid + curator vaults) wired in parallel, gated behind it.**

**Recommendation.** Make the first real-money rung a **CEX path on Kraken**, because every guardrail that matters at the "validate-before-funds" stage is more mature there: trade-only/no-withdraw/IP-whitelisted API keys (a venue-enforced custody boundary), an exchange-native dead-man switch (`cancelAllOrdersAfter`), pure-stdlib HMAC signing, and a real public archive for backtesting. Wire the **EVM/Base** path (Hyperliquid keyless funding feed for signal; curator-managed ERC-4626 stablecoin vaults for yield) in parallel as the *next* venue, validated on Base Sepolia.

**Strongest evidence.** Funding-carry signal is named by 3 independent agents and confirmed real (Hyperliquid `/info fundingHistory` is genuinely keyless, no-auth, pure-`urllib`). Curator ERC-4626 vaults are the most-endorsed on-chain primitive. Scoped no-withdraw Kraken keys are confirmed first-party (withdraw permission off + IP whitelist for *spot*, contradicting older guides).

**Main tradeoff / honest caveats.**
- **Kraken has NO self-serve spot paper environment.** The only free programmatic sandbox is *futures* (`demo-futures.kraken.com`); spot test access is gated to "qualified clients," and the keyless Kraken CLI paper engine models neither slippage nor partial fills and uses no API keys. So "Kraken paper" cleanly exists only on futures (a different, leveraged product). The spot wiring is code-reviewed-but-not-live-tested until tiny-cap mainnet — Base Sepolia is actually a *cleaner* free testnet.
- IP-whitelisting needs a *static* egress; the residential MX IP drifts (documented in project history) → route through the existing Netcup VPS or the whitelist self-DoSes.
- On the EVM path, the curator-vault "curators absorb the risk" thesis is **refuted** by the 2025–26 curator reckoning (Stream/xUSD ~$285M, Euler $137M, Elixir deUSD collapse; MEV Capital / Re7 took direct hits). Allowlisting a curator is risk-*transfer*, not elimination — restrict to conservative blue-chip-collateral vaults, single-digit yield, per-curator AND per-collateral caps.

---

### Decision 2 — Strategy: **Mechanical / quant. Not LLM-discretionary.**

**Recommendation.** Build the strategy layer as deterministic IntentGenerators behind the existing PROPOSE seam. Sequence: (1) funding-carry (signal first, live last), (2) vol-scaled time-series momentum, (3) Engle-Granger cointegration pairs — or, on the EVM path, mechanical stablecoin-vault yield. Reserve any LLM as an *optional, sanditized, local* feature feeding intent confidence — never a trigger, never the disposer.

**Strongest evidence.** Unanimous across themes; reinforced by the survey (0/19 reproducible, most LLM agents fail to beat buy-and-hold) and the "Alpha Illusion" finding (committees help ~20% of the time, add correlated not independent agents). The clinching argument is structural: the DSR/CPCV promotion gate can only be made honest for a strategy with a *countable, finite* config space — i.e. mechanical. Verdicts on the cost-aware backtest gate, point-in-time discipline, and overfitting gate are all `adopt-now`.

**Main tradeoff / honest caveats.**
- The *durability* of the mechanical alpha is unproven and the headline Sharpes are inflated (see §1). Treat every strategy as a backtest hypothesis to re-validate net-of-cost on your own venue. Plain vol-scaled TSMOM is ~0.65 Sharpe net, concentrated in bull trends.
- Market-neutral legs (pairs, BTC-residual reversion) require **shorting**, which a spot-only SimExecutor/Base-Sepolia path cannot do; the "long-only fallback" is *not* market-neutral. Resolve the short-leg venue (spot-vs-perp or two perps, with funding+borrow modeled) before claiming neutrality.
- LLM-discretionary is not forbidden — it is *gated*: it may only ship behind grammar-constrained decoding, an abstain/HOLD escape value, a fail-closed validator, and a Page-Hinkley return-stream auto-halt. For a solo builder watching token spend, it is almost certainly not worth it for v1.

---

### Decision 3 — Custody: **Genuinely unresolved — owner must choose. Default near-term to self-hosted keystore baseline + scoped CEX keys; defer the MPC-vs-smart-account fork to the on-chain phase.**

**Recommendation.** For the *current* phase there is a clear, low-controversy baseline regardless of the eventual fork: (a) **kill the env-var/plaintext key anti-pattern** with an OS-keystore + scrypt-encrypted keyfile loaded only inside the Executor; (b) on the CEX rung, use **trade-only, no-withdraw, IP-whitelisted, expiring keys** as a venue-enforced second boundary. The strategic fork — **managed MPC (Coinbase CDP/AgentKit)** vs **self-hosted ERC-4337 smart account + scoped session key** — is the one decision the corpus does *not* resolve and the owner must make.

**Strongest evidence & the real tradeoff.**
- **Self-hosted smart-account** (ERC-4337 + audited spend-limit/session-key modules, or a Coinbase SpendPermission with a human-held owner key) preserves self-custody and gives on-chain-enforced limits that survive a full host compromise — best fit for a high-autonomy, local-first, zero-cloud builder. *But*: ERC-4337 mandates a third-party bundler+RPC (a cloud dependency that dents zero-cloud); the "kill-switch via revoke()" only works if the owner key lives on a **separate factor** offline (an unstated, non-trivial prerequisite); SpendPermission's `allowance` is a **per-period total**, not a per-tx cap (a full period is drainable in one tx — per-tx granularity must stay in the policy engine); ERC-7715 is still **draft**; and SmartSession is self-labeled beta with a loss-of-funds disclaimer. Use *audited* modules only, never bespoke Solidity.
- **Managed MPC (CDP/AgentKit)** is the lowest-friction Base path with the only real Python SDK, an identical testnet→mainnet code path, and keys never in-process. *But*: it is custodial (Coinbase co-holds a keyshare), enforcement is off-chain/non-verifiable, it breaks stdlib-only + zero-cloud, the enclave enforces only tx-*shape* rules (drawdown/solvency/rate **must** stay local), `netUSDChange` USD caps are **mainnet-only** (untestable on Sepolia), and it ships **no** default policies (silent-allow until configured). It also quietly *pre-commits* custody to managed — vendor-neutral faucets keep the self-hosted option open.

**Bottom line:** this is a values-vs-friction call, not a factual one. Given the documented local-first / zero-cloud / high-autonomy preference, the self-hosted smart-account leans correct — but it is a project of its own, so the keystore baseline + scoped CEX keys carry the near-term while the owner decides.

---

## 3. Prioritized Adoption Roadmap

### ADOPT NOW — zero/low risk, pure-stdlib, validatable in SimExecutor, fail-safe

| Technique | Why | Concrete codebase change |
|---|---|---|
| **Crash-only WAL ledger + journaled policy state + startup reconciliation** | Fixes a real bug: in-memory `_tripped/_starting_equity/_recent_ts` + ledger reset on restart → silently un-trips the drawdown breaker. `adopt-now`. | New `journal.py`: persist ledger + latched PolicyEngine state via `json` + atomic `os.replace` (+ `fsync`, `PRAGMA synchronous=FULL` if sqlite). Add `snapshot()/restore()` to `PolicyEngine`; re-run kill-switch/drawdown/solvency on startup before resuming. Kill-the-process crash test to *prove* atomicity on Windows. |
| **Cost-aware backtest + CostModel + DSR/purged-CV promotion gate** | The decisive "validated before funds" deliverable; near-stdlib math. Ship plain purged-CV + conservative DSR (raw trial count as N) first; defer CPCV/ONC. `adopt-now`. | New `backtest/` package: one shared `CostModel` (spread + sqrt-impact `η·σ·√(Q/V)` + maker/taker fees, advisory only — may only ADD conservatism, never relax a hard cap) used by Sim/Paper/Live; `costmodel`, `metrics.py` (DSR via `math.erf`), `cv.py` (`itertools.combinations`). **Append-only run-ledger logging every config tried** (without it DSR is a vanity metric). |
| **Point-in-time inputs + fill-at-t+1** | Kills the #1 backtest bug (signal-on-close/fill-on-same-close); crypto close→next-open gap (~0.5–2%) is often the whole edge. `adopt-now`. | In `market.py`/SimExecutor: gate agent inputs to `knowable_at ≤ t`, fill at next tick. Falsification test: a deliberate look-ahead strategy must collapse post-fix. Pair with conservative slippage. Treat the ~100–200ms latency knob as a forward-compatible no-op on bar data. |
| **Vol-targeting sizing layer** (EWMA RiskMetrics λ=0.94, √-annualized) | Real, canonical, ~20 lines; monotone-shrinking so it can NEVER breach the cap. `pilot` per verdict (impact numbers are fabricated — measure your own). | New pure function between PROPOSE and the cap: `final_size = min(vol_target_size, notional_cap)`, behind a flag, SimExecutor-replayable. Add a vol floor to avoid div-by-zero. **Watch the mean-reversion failure mode**: vol-scaling cuts size exactly when a dip-buyer wants more. |
| **Cumulative time-windowed spend budget** (`max_notional_per_window`) | Closes the most-cited *gap*: current policy caps per-tx notional + trade *count* but NOT total value/window → drip-drain stays in-cap. `adopt-now`. | New rule in `PolicyEngine.evaluate`; extend `register_fill(ts, notional)`; deque of `(ts, notional)`, debit on **executed fills only** (never at evaluate-time). Maps 1:1 to ERC-7715 period allowance later. |
| **Staleness gate** (`STALE_DATA` rule) | A frozen-but-open feed is the deadliest unattended failure; fail-closed. `adopt-now` (wired-but-inert now). | New 7th rule in `evaluate()` (right after the breaker). **Do NOT compare against `MarketTick.ts`** (it's an integer step, "no wall-clock"); add a real received-at timestamp on the live-feed adapter and compare via `time.monotonic_ns()`. Inert vs the deterministic sim; goes hot with the live feed. |
| **HMAC-SHA256 hash-chained JSONL audit log** | Tamper-evident `(intent, verdict, state-hash, prev_hash)` trail; pure `hashlib`+`hmac`+`json`. `adopt-now` (mechanism only). | New `audit.py` emitting one canonical-JSON line per `evaluate()`, sealed with HMAC; `verify_chain()`; key/log stored outside the agent's writable path. **Drop the 15c3-5/Reg-AT framing (doesn't apply / withdrawn).** Claim tamper-*evidence*, not non-repudiation. |
| **Hypothesis stateful fuzzing of the policy engine** | Operationalizes "validate before funds": asserts kill-switch/drawdown/notional/allowlist/solvency invariants across *arbitrary* histories, auto-shrinks repros. `adopt-now`. | `requirements-dev.txt` += `hypothesis` (tests-only, no runtime violation). New `tests/test_policy_stateful.py`: `RuleBasedStateMachine` modeling the real `intent→evaluate→execute→register_fill` ordering + 1e-9 tolerances. Derive invariants from first principles, not by copying `policy.py`. |
| **Read-only P&L/solvency/drawdown** | Blocks reward-hacking/spec-gaming: the agent must never write the metric it's judged on. `adopt-now`. | Ledger recomputes equity/drawdown solely from the execution log; pass the agent a frozen snapshot; verify the agent has zero write path to any value the policy gates on. |
| **Harden the in-process gate** | Structured-intent-only input + agent-immutable (`frozen=True`) config + persisted audit log; the parameterized-query barrier vs encoded injection. `adopt-now`. | Make `PolicyConfig` `frozen=True`; confirm `Intent.reason` is never read by any rule (it isn't); persist the currently in-memory ledger. **Defer encoding/adversarial tests until an LLM strategy ingests untrusted text.** |
| **Tiered ALLOW/DENY/ESCALATE + dedicated low-balance account** | The low-balance account caps worst-case loss regardless of any rule bug — adopt unconditionally and first. `adopt-now`. | Config: hard rule rejecting non-owner accounts/counterparties; route high/irreversible/anomalous intents to an out-of-band **signed** confirm (reuse the phone→PC push, key off-host), default-DENY on timeout, render *decoded* tx fields (defeats Lies-in-the-Loop). |

### PILOT NEXT — on paper / testnet, validate before trusting

| Technique | Why | Concrete change |
|---|---|---|
| **Funding-carry IntentGenerator** (Hyperliquid `/info`) | Highest-leverage, most-accessible signal; keyless pure-`urllib`. Build the poller + net-carry calc + delta-band invariant NOW; route real funds LAST. `pilot`. | New `signals/funding.py` → emit paired `(spot_buy, perp_short)` intents under a hard `|spot_qty − perp_qty| ≤ ε` policy invariant + a fee-aware net-carry check + auto-flatten on funding-flip. Hit `api.hyperliquid.xyz/info` (NOT Quicknode/Chainstack — they 422). **Drop the aoki-h-jp repo.** |
| **Vol-scaled TSMOM (+ regime gate)** | Strongest durable academic class; pure arithmetic. `pilot` — re-derive net-of-cost Sharpe (~0.65, not 1.83). | New `signals/tsmom.py`; pre-register params, switch only on 3–5 confirmed bars (ADX lags 5–15 bars → whipsaw). |
| **Engle-Granger cointegration pairs → Kalman → OU** | Best architectural fit for a hard-rule disposer; stdlib-feasible. `pilot` — resolve the short leg; require an economic rationale per pair (~30/595 cointegrate by chance). | New `signals/pairs.py`: OLS + tabulated ADF + z-bands; later online Kalman (~30 lines). Mandatory hard stop + time-stop (structural break is the unhedgeable risk). |
| **Net-of-cost spread gate (volume-aware)** | Execution-quality as a testable veto. `pilot` — reframe as *volume*-aware (the depth-aware citation is non-authoritative); veto/down-size only. | New 8th policy rule fed by the shared `CostModel`; needs `MarketTick.volume` first; fixture test that a phantom-slippage spike gets clamped. |
| **Post-only (ALO) default + repeg→taker fallback** | Exchange-enforced "never cross the spread"; maker/taker spread is the real win (~0.1–0.25%/round-trip, NOT zero-fee). `pilot` (CEX path). | `OrderType` enum on Intent; policy mandates `post_only=True` for normal-priority, `urgent` gate **policy-bounded** (breaker/kill-switch unwinds only). Open-order reconciliation rule so unfilled orders don't accumulate/double-count. |
| **Transactional-outbox idempotency + reconcile-before-retry** | Closes the crash/timeout-after-order seam (double exposure). `pilot` — build with the first PaperExecutor, not before. | sqlite outbox keyed by a new `Intent.intent_id`; `cl_ord_id`(CEX)/nonce(EVM) anchor; cumulative-filled ledger. **Reconcile by querying the venue before resubmit** — neither anchor gives exactly-once. |
| **Page-Hinkley/CUSUM degradation gate** | Earliest "strategy stopped working" alarm; ~30 lines O(1). `pilot` — shadow-mode first to measure false-alarm rate. | Observer over executed fills raising a degradation event → halt-to-human (K-of-M hysteresis). Must ONLY freeze + alert, never auto-trade; calibrate on paper history. |
| **Graded 3-stage circuit breaker** (Yellow throttle → Orange read-only → Red latch) | Extends the binary breaker; fails soft, hard Red floor, manual re-arm. `pilot` — cutoffs unsourced, must backtest. | State enum replacing `_tripped: bool` in `PolicyEngine`; mark-to-market drawdown; Orange must emit a LOUD audited signal (no silent degraded mode); forbid auto de-escalation. Ship Yellow+Red first. |
| **Deterministic stress-scenario veto** (BTC/ETH −70%/wk, 2022/COVID replay, depeg, corr→1) | Forward-looking tail veto; needs zero statistical power. `pilot` (the working half of the CVaR rec). | New config-driven rule in `evaluate()`; flash-crash fixtures asserting the kill-switch actually fires. *Defer* the rolling-CVaR/Kupiec self-audit — undefined at zero violations, understates tails at small N. |
| **Robust multi-source price ingestion** (median + Hampel/MAD) | Defense vs poisoned/fat-finger feeds. `pilot` — needs ≥3 *independent* sources for fault-tolerance; at 2 sources it can only DETECT disagreement → must fail-closed, never auto-pick. | New `feed/` adapter layer behind `ticks()`; `data_unhealthy` veto wired to the kill-switch; flag-don't-drop (Databento discipline). |
| **Exchange-native dead-man switch** (Kraken `cancelAllOrdersAfter`) | Survives the agent hanging/crashing. `pilot` — validate on futures-demo; cancels resting orders ONLY (pair with a flatten step). | Periodic stdlib HTTPS POST (60s timeout, ping 15–30s); kill-switch flip sets `timeout=0` + stops heartbeat. CEX-path only (N/A on-chain). |
| **Pre-trade slippage/liquidity guard** | Per-tx slippage cap, same `SlippageGuard` interface both venues. `pilot`. | Kraken L2 book-walk (fully stdlib) first; DeFi `getAmountOut`/Quoter later (needs Ethereum keccak + ABI codec — a stdlib dent; `eth_call` for the non-view Quoter). Enforce atomically via `minAmountOut`+deadline / post-only. |
| **Three-layer liveness** (NSSM supervisor + in-process watchdog + off-box Healthchecks.io) | Covers crash / silent-freeze / host-loss. `adopt-now` per verdict, piloted here because restart must re-enter behind the gates. | NSSM throttled restart; stdlib daemon-thread last-tick watchdog (Windows has no `sd_notify`; escalate via `os._exit`); self-host Healthchecks.io on the *other* VPS. Restart must fail-closed behind kill-switch/solvency. |

### DEFER — needs real funds, scale, or an unresolved decision

- **OnchainExecutor on Base** (AgentKit managed-MPC *or* self-hosted ERC-4337) + **ForkExecutor** (Anvil/Hardhat mainnet-fork harness, the "missing rung"): both gated on Decision 1 picking EVM and Decision 3 picking a custody model. AgentKit ships native Aave/Compound/Morpho actions — *don't* hand-roll calldata.
- **Health-Factor monitoring / soft-liquidation**: only if the agent ever *borrows* (skip for deposit-only v1).
- **MEV-protected RPC** (bloXroute BackRunMe — NOT Flashbots/MEV-Blocker, which are Ethereum-mainnet-only): on-chain leg only.
- **Custody-layer cap mirroring** (ERC-7715 session keys / SpendPermission revoke): Base Sepolia phase; off-chain policy stays line-one.
- **Hardware signer** (Ledger/Keystone) for human-confirmed first mainnet funds.
- **Multi-agent committee, restaking/LRTs, concentrated-LP, foundation models (TimesFM/Chronos), heavyweight LOB sims (ABIDES), Tenderly/Forta SaaS monitoring**: all research-only or scale-gated.

---

## 4. Per-Theme Highlights

1. **Strategy & Alpha.** Mechanical wins unanimously. The most accessible edge is the perpetual funding rate (keyless Hyperliquid feed); delta-neutral cash-and-carry is the best architectural fit because its ~zero net delta makes the breaker/solvency checks trivial. Durable academic alpha = vol-scaled TSMOM (gated by regime) and Engle-Granger pairs. The decisive deliverable is the cost-and-overfitting-aware backtest gate, not any model. Honest caveat: nearly every headline Sharpe is single-study/vendor/blog and inflated — re-validate on your own OOS data.

2. **LLM Agent Architecture.** The LLM is a *pure proposer*, on the slow loop only; account state and risk limits are read-only to it. Plan-and-Execute (one plan call/cycle) beats chatty ReAct for a slow treasury. Never let the LLM be the calculator (use decimals/integer minor-units) or the JSON formatter (grammar-constrained decoding + fail-closed validator). FinMem-style embargo-aware advisory memory is the best *blueprint* — adopt the architecture, never the reported P&L. The field is immature (0/19 reproducible).

3. **Risk Management.** Sizing belongs in PROPOSE as a *ceiling* (`min(proposed, hard_cap)`); the policy engine stays sole disposer. Vol-targeting is the highest-leverage drawdown reducer; fractional Kelly (0.1–0.25) as a ceiling only. Upgrade the binary kill-switch to a graded out-of-band breaker, add a three-layer dead-man switch, and validate the disposer with Hypothesis. Every dynamic method shares one failure: it lags fast crashes and correlations spike to 1 — so the hard cap + kill-switch are non-negotiable backstops.

4. **Custody & Key Security.** Enforce spend limits at a boundary the agent cannot reason or be injected past — exactly the existing policy engine, vindicated by the 2026 Grok/router heists. Build a layered ladder; mirror caps a second time at the custody layer. Hold only a scoped, short-lived, revocable credential — never a master key. Kill the env-var anti-pattern. No managed wallet enforces *your* notional caps by default, and only Coinbase ships a real Python SDK — so the local policy engine stays authoritative.

5. **Execution & Microstructure.** Execution is an *architecture* choice, not a latency race. Be a maker (post-only default). Model cost as a hard pre-trade veto. On EVM, don't build a router — use intent-based execution (CoW signed min-out = the policy limit). MEV protection is a config knob (Base-aware: bloXroute, not Flashbots). Idempotency + reconcile-before-retry is non-negotiable before real funds. CCXT lives only in the Executor adapter.

6. **Backtesting & Simulation.** One deterministic event-driven loop reused everywhere makes look-ahead structurally impossible and guarantees backtest-to-live parity. *Note: the current `runner.py` is already event-driven and look-ahead-free — the "high-impact refactor" is mostly re-labeling; formalize a typed event stream only when async Paper/Onchain fills arrive.* Replace flat slippage with a decomposed cost model; gate promotion on DSR + purged-CV; calibrate the breaker from Monte-Carlo/block-bootstrap percentiles (block length ~n^(1/3), report a human — don't auto-tighten).

7. **Data & Market Feeds.** Market data is a pluggable adapter behind `ticks()`; data-quality failures become first-class hard-rule inputs (staleness budget, integrity gate). Match the feed to the venue (Kraken REST for CEX; Pyth Hermes for DeFi — note bearer-token from 31 Jul 2026). Start keyless/stdlib; treat CCXT/web3/aggregators as optional adapters. One feature definition, point-in-time correct, one immutable snapshot into PROPOSE and DISPOSE.

8. **Monitoring & Ops.** Stacked independent layers: OS supervisor + in-process watchdog + off-box dead-man heartbeat. Append-only HMAC hash-chained JSONL audit log. Statistical anomaly detection stays *advisory*; only Page-Hinkley on the return stream earns an auto-halt-to-human. No auto-restart may bypass the policy engine or silently un-trip a latched breaker — pair restart with idempotent startup reconciliation. Self-hosted ntfy alerting; blameless post-mortems whose action items become new hard rules + replay regression tests.

9. **On-chain / DeFi.** Safest automatable path = mechanical curator-managed ERC-4626 stablecoin yield + defense-in-depth, not speculative trading. Project the policy engine down into the chain (session-key caps). Make Health-Factor + peg-health deterministic policy invariants. Base + AgentKit is the consensus target (sub-cent fees, free faucet). Add a mainnet-fork harness as the missing rung. Honest correction: the curator-vetting "risk absorption" thesis was refuted by 2025–26 vault blowups — risk-transfer, not elimination.

10. **Safety, Adversarial & Governance.** Treat the LLM as structurally untrusted; the real guarantee lives in the deterministic layer. Prompt injection is unsolvable at the model level (~50% success even on strong models) — minimize blast radius. The dominant attack surface is the *data feed*. The agent must never self-report the metric it's judged on. Approval channels must be authenticated, signed, out-of-band, rendering raw decoded tx fields. Caps enforced twice (policy + custody). An adversarial replay harness as a CI promotion gate.

---

## 5. Anti-Recommendations (Avoid / Hype for a Solo Local-First Builder)

- **Do NOT trust the fabricated/misattributed headline metrics.** Vol-targeting "−31%→−14% / Sharpe 0.99→1.54" is in no source (real figures: −31%→−19%, 0.90→1.34, on stocks/bonds). TSMOM "Sharpe ~1.83 OOS" is cherry-picked (~0.65 net). The PAL "95% first-retry" figure is invented. Measure everything yourself.
- **Do NOT vendor the funding-arb reference repo (aoki-h-jp).** Unmaintained since 2023, CCXT-based, CEX-only, detection-only, and doesn't support Hyperliquid. Port logic from official Hyperliquid docs instead.
- **Do NOT build a PAL/Program-of-Thought sandbox.** Verdict: `defer`. It is redundant (the policy engine + wallet already recompute every money number deterministically) and a DIY stdlib AST allowlist is the canonical *broken-sandbox* anti-pattern (RCE surface via `__subclasses__`/format-string escapes). **Adopt only the cheap half: migrate money math to `decimal.Decimal`/integer minor-units.**
- **Do NOT invoke regulatory cosplay.** SEC Rule 15c3-5 applies only to broker-dealers (not you); CFTC Reg-AT was *withdrawn in 2020*. Keep the git/audit trail as engineering hygiene and the "own-funds, no pooling, no advice" rule as documented conduct — but confirm the legal premise with a real lawyer before real funds.
- **Do NOT auto-unwind on a market-anomaly breaker.** Verdict refuted the framing: forced liquidation into thin/crashing liquidity is an attacker-trippable DoS that can be worse than holding. FREEZE + alert-human; justify the breaker as flash-crash/feed-integrity protection, not as a defense against a same-market RL adversary (which doesn't fit a tiny treasury).
- **Do NOT build a multi-agent committee for v1.** "Alpha Illusion": added agents are correlated, debate wins ~20% of configs. Gate behind net-of-friction ablations; almost certainly not worth the token spend.
- **Do NOT adopt time-series foundation models** (TimesFM/Chronos) for the core return signal — documented non-fit (negative R², sub-chance direction).
- **Do NOT over-invest in heavyweight sims** (ABIDES/NautilusTrader L2 fill models) — equities-shaped, non-stdlib, directional-not-ground-truth.
- **Do NOT treat the keystore as a high-impact keystone.** Verdict downgraded it to *medium hygiene*: at-rest encryption gives ~zero protection against same-user/in-process malware on an unattended daemon, and the cited source argues the *opposite* architecture (keys never in the agent's process). Do it (it kills trivial leaks), but don't let it justify loosening caps; it must not block testnet progress.
- **Do NOT over-claim the SimExecutor event-loop refactor or the single-feature/Freqtrade-audit refactor as high-impact** — `runner.py` is already event-driven and look-ahead-free; those refactors edit working money-handling code for properties it already has. Keep only the cheap residue (a written point-in-time invariant + one perturbation test).

---

## 6. Open Questions for the Owner

1. **Custody fork (the one the research can't make for you):** managed-MPC (CDP/AgentKit — lower friction, breaks zero-cloud, custodial) vs self-hosted ERC-4337 smart account (self-custodial, on-chain-enforced, but needs a separate-factor owner key + a bundler/RPC dependency + audited modules only). Which way, given your stated local-first / zero-cloud / high-autonomy values?

2. **Chain commitment:** is the long-term venue CEX (Kraken — better near-term tooling, no clean spot paper), EVM/Base DeFi (curator vaults + Hyperliquid signal — better free testnet, contract/curator risk), or genuinely both? This unlocks or defers the entire on-chain bucket (ForkExecutor, MEV, HF monitoring, session keys).

3. **Strategy v1 concrete pick:** funding-carry, vol-scaled TSMOM, cointegration pairs, or mechanical stablecoin-vault yield? And do any need a **short leg** you're willing to support (spot-vs-perp), or is v1 long-only (which kills market-neutrality)?

4. **stdlib-only exceptions:** are you willing to admit (a) `hypothesis` as a tests-only dev dependency, (b) one local embedding model / `eth_account` / `web3` quarantined behind the Executor adapter, (c) `keyring`/`pywin32` for DPAPI? Each is a deliberate, scoped concession the corpus flags.

5. **LLM in the loop at all?** The corpus says mechanical for the action path. Do you want an optional, sanitized, local LLM *feature* feeding intent confidence (with grammar-constrained decoding + abstain value + Page-Hinkley auto-halt), or none for v1?

6. **Risk thresholds to backtest before they govern funds:** graded-breaker cutoffs (e.g. −10%/−20%), Kelly fraction, staleness budget, DSR cutoff, vol-target. All are illustrative defaults requiring calibration on *your* data — what are your starting priors and acceptable single-period blast radius?

7. **Legal/jurisdiction:** confirm the personal-funds / no-pooling / no-advice exemption with a lawyer for your jurisdiction before any real capital. Not legal advice; the corpus's regulatory citations were partly wrong.
