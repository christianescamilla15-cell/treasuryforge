# treasuryforge — Phase-3 Real-Implementation Playbook

**First live investment: ~200 MXN (~11 USD) · Solo individual in Mexico · Own funds · Non-institutional**

> Audience: you, the builder, about to risk your first ~200 pesos. This is the concrete, currently-real (2026) path from a simulation-only agent to one validated live trade — and an honest account of what it costs and where it can bite.
>
> Status of the underlying system: agent **proposes** intents → 8-rule hard **policy** engine disposes → wallet **executes** within enforced limits. Execution is an interface (`SimExecutor` today; `PaperExecutor`/live `BitsoExecutor` are the swap-in). 55 tests pass in simulation. Phase-3 makes the live executor real.

---

## 1. Executive summary

**Decision: proceed on Bitso. There is NO hard blocker** for a Mexico-based individual to make the first ~200 MXN trade. The path is open end-to-end: KYC via CURP/INE → free SPEI funding → trade-only, IP-allowlisted, no-withdrawal API key → `POST /api/v3/orders`. Nine of ten research agents and every adversarial verdict converge on Bitso as the right venue, and its API key model maps **1:1** onto the policy engine's blast-radius design with zero workarounds.

**The decisive findings:**

- **Bitso is the platform.** Mexico-domiciled, CNBV-supervised under the Ley Fintech (the MXN/SPEI rail runs through its CNBV-authorized IFPE subsidiary **NVIO Pagos México**), native free SPEI funding, CURP-based KYC, and — critically — granular API permissions that natively express *trade-only + no-withdrawal + IP-allowlist*.
- **The security stance is real and natively supported.** Five independent permission toggles + an IP allowlist of up to 5 addresses + up to 6 keys per account. A leaked trade-only key cannot exfiltrate funds.
- **Signing is stdlib-only.** Bitso uses plain HMAC-SHA256 (`hmac` + `hashlib` + `urllib`). No SDK, no `cryptography`, no JWT/Ed25519 (that constraint is exactly why Coinbase Advanced Trade is disqualified).
- **Live numbers verified today (2026-06-16, `GET /v3/available_books`):** every `*_mxn` book has `minimum_value = 10 MXN` (200 MXN clears it ~20×), and the **entry-tier flat_rate is maker 0.60% / taker 0.78%** — *not* the 0.15%/0.19% headline (that is the USD/crypto book) nor the 0.50%/0.65% stale doc sample.

**The honest truth about the money:** at 11 USD this is a **paid rehearsal of the live executor, not an investment**. Round-trip fee+spread drag is ~1.2% (maker) to ~1.56% (taker), and ~3–4% if you mistakenly hit the consumer "Quick Buy/Convert" spread path. **Expect to end slightly down on a flat market.** Success = a real order placed, filled, and reconciled inside policy limits — something simulation cannot validate.

**The soft/conditional blockers to clear (none stop the trade):**

| Item | Type | Mitigation |
|---|---|---|
| KYC must be completed first (CURP/INE + selfie) | Owner gate | Budget up to 24h; do not schedule trade #1 as time-critical |
| SPEI must come from a **same-name** MX CLABE | Owner gate | Bitso rejects third-party transfers |
| IP allowlist needs a **static egress IP** | Conditional | Run executor from the Netcup VPS (152.53.167.28), *not* the rotating residential MX IP |
| 2FA (authenticator app) required before any key | Pre-req | Enable TOTP, save the one-time restore code offline |
| Fee/spread drag at 11 USD | Economic | Treat as validation cost; feed real fee into the Phase-2 cost gate |
| Tax record-keeping from trade #1 | Obligation | Log per-fill ledger; the *buy* itself is non-taxable |

**One unverified-but-likely 2026 item to check live, not assume:** biometric CURP became the reinforced-identity standard for the MX financial sector in early/mid-2026 (press dates conflict; no primary source confirms it applies to ITFs/Bitso). If Bitso's live onboarding demands it and you lack it, obtain it at RENAPO first. **Low confidence — verify in the onboarding flow.**

---

## 2. Platform recommendation

### Primary: **Bitso** (personal / persona física account — NOT a business account)

**Evidence:**
- **Regulatory:** CNBV-supervised under the 2018 Ley Fintech. Precise framing (don't overstate): the **MXN/SPEI payment rail** is a CNBV-authorized IFPE held by subsidiary **NVIO Pagos México**; the **crypto-trading function itself** operates legal-but-unlicensed in the AML "actividad vulnerable" regime — the normal status for *all* MX exchanges, not a Bitso gap. Crypto balances are **not** IPAB/bank-insured. This does not block you; it means keep on-exchange balances tiny.
- **Funding:** Native MXN via SPEI, free, credits fast (Bitso documents "within 24h"; usually 1–2h). Requires only a CURP you already have.
- **Security fit (the clincher):** API keys expose five independent toggles — *Place orders / View balances / View account information / Perform security actions / Make withdrawals* — plus an IP allowlist (up to 5 IPs) and up to 6 keys. Trade-only + no-withdrawal + IP-pinned is a supported configuration, not a hack.
- **Stdlib fit:** HMAC-SHA256 signing, implementable with Python stdlib only.
- **Size fit (verified live today):** `minimum_value = 10 MXN`; 200 MXN clears it ~20×.

**Main tradeoff:** Bitso's MXN-book fees (0.60%/0.78%) are higher than its USD/stablecoin books (~0.30%/0.36%). For a *single first trade* you accept the MXN-book fee — routing MXN→USDT→asset pays the book fee **twice** and the stablecoin-book saving only amortizes across *many* trades. So: trade a **direct `*_mxn` book** for trade #1; consider USDT-routing only later as a steady-state lever. Secondary tradeoff: Bitso's uptime/never-hacked/zk-proof-of-reserves claims are largely self-reported — build defensively (§5).

### Runner-up: **Kraken** (documented fallback only)

Genuinely accessible to a Mexican individual in 2026: native MXN/SPEI funding since July 2025 (150 MXN min deposit, free, auto-converted to USD), trade-only/no-withdraw keys with IP restriction, HMAC signing (stdlib-compatible), and a defense-in-depth extra — withdrawals only to pre-whitelisted, 2FA-confirmed addresses, **plus a real server-side dead-man-switch** (`cancelAllOrdersAfter`) that Bitso lacks.

⚠️ **Unresolved contradiction to verify before ever using Kraken:** competitor (Bitso) sources claim Kraken charges "0.5% / 150 MXN minimum **withdrawal fee**" (would eat ~75% of a 200 MXN balance). Kraken's own page describes 150 MXN as a minimum **deposit** (free). A deposit minimum and a withdrawal fee are different things — **check Kraken's live withdrawal screen** before trusting either. Also: Kraken has **no spot sandbox** (only futures demo), so don't design a Kraken-spot-sandbox path.

**Explicitly de-prioritized:**
- **Binance (via the CNBV IFPE entity "Medá", ~Sep 2025):** real fallback, but auto-expires/deletes un-IP-whitelisted keys (a foot-gun for an unattended agent) and added a 2026-01-15 percent-encode-before-HMAC rule + recvWindow clock-skew enforcement — different signing, not a free swap.
- **Coinbase Advanced Trade: ruled OUT.** No native MXN/SPEI, and CDP keys require ECDSA/Ed25519 + JWT, which **Python stdlib cannot sign** — it breaks the stdlib-only constraint.

**Architectural directive:** keep the `Executor` interface exchange-agnostic (`SimExecutor → PaperExecutor → BitsoExecutor`) so Kraken/Binance can be added later without touching the policy engine.

---

## 3. OWNER CHECKLIST — zero to a validated trade-only key

Do these in order. Steps are owner-actions unless marked.

**A. Prep (before registering)**
1. Have ready: current (non-expired) **INE** front+back, a phone with working camera (liveness selfie), your **CURP** (check whether the biometric version is demanded live), and a **same-name** MX bank CLABE able to send SPEI.
2. Do **not** use a VPN during signup (raises Bitso's risk score → rejection).

**B. Register + KYC**
3. Create the account (email + phone) at bitso.com. Choose **personal / persona física** — never a business account.
4. Complete the verified tier: INE front+back + live selfie. **Type your full legal name EXACTLY as printed on the INE** (both apellidos + accents). Name/data mismatch against the CURP/RENAPO registry is the #1 documented first-attempt rejection. Photograph the INE flat, well-lit, all four corners in frame, no glare.
5. **[Gate]** Wait for "KYC fully approved" — budget up to 24h. SPEI funding *and* the 300 req/min API tier both require completed KYC.

**C. Lock down account security (before any key exists)**
6. Enable **2FA via an authenticator app (TOTP — Authy / Google Authenticator), NOT SMS.** SMS is a SIM-swap vector. 2FA is *mandatory before the API-key page will issue any credentials.*
7. Save the **one-time emergency restore code OFFLINE**, on a device separate from the trading PC. Seed the TOTP secret into a backup authenticator. (Losing both the 2FA device and the restore code forces slow, ticket-only recovery.)

**D. Fund**
8. In-app: **Wallet → MXN → Depositar**, get your dedicated CLABE, and send **one SPEI transfer of ~200 MXN from your own same-name bank account.** Third-party/family/different-name transfers are rejected/returned. Put **only** the bot's risk capital on-exchange. Treat the funded amount as the hard solvency ceiling.

**E. Create the TRADE-ONLY key**
9. **[Static IP first]** Decide where the executor runs. Pin its egress to the **Netcup VPS (152.53.167.28)**. Verify the actual egress IP from the executor host (`curl ifconfig.me`) — confirm it is the static one, not a tunnel/inbound IP — before adding it to the allowlist. (A dynamic residential IP will silently brick the key on every ISP rotation.)
10. Create **one** API key (of the 6 allowed) with **exactly these toggles:**

    | Permission | Setting |
    |---|---|
    | **Place orders** | ✅ ON |
    | **View balances** | ✅ ON |
    | View account information | ✅ ON (optional — for limits/reconciliation reads) |
    | **Perform security actions** | ❌ **OFF** (non-obvious trap: it can deactivate the account / block withdrawals) |
    | **Make withdrawals** | ❌ **OFF** (the hard wall — no exfiltration possible) |

11. Enable **"Restrict use of API addresses"** and add only the VPS static IP.
12. **Store the secret immediately — it is shown ONCE.** Put it in the OS keychain via `keyring` (Windows Credential Manager / DPAPI), behind a thin `SecretStore` wrapper. **Never** in `.env`, env vars, git, logs, the journal, or the HMAC audit log. Discard the decrypted value after building each signed request. Strengthen the Windows login password (DPAPI strength derives from it); consider BitLocker.
13. *(Optional)* Create a **second, read-only key** (View balances + View account info only) for an independent monitor/watchdog.

> ⚠️ **If you ever later enable withdrawals (you should not for the bot):** Bitso's per-asset withdrawal-address allowlist treats an **empty list as "any address allowed"** (default-*allow*, fail-open). Never leave it empty. For treasuryforge this is moot — the bot key has no withdrawal scope and the executor has zero withdrawal code path.

---

## 4. SAFE VALIDATION SEQUENCE — staged go/no-go ladder

Each rung is **gated in code** (e.g. stages `paper → prod-ro → prod-tiny → prod-live`), not by discipline. Refuse to advance until the prior rung is green. The first live run **STOPS after read-only**.

**Rung 0 — Sandbox / signer (capital-free).**
First validate the HMAC signer **offline against your own fixed test vector**, cross-checked with an `openssl` HMAC one-liner. ⚠️ **Bitso publishes NO numeric golden vector** — generate your own; do not "reproduce a documented example." Then *probe the sandbox live before trusting it* (`curl https://api-sandbox.bitso.com/api/v3/available_books`): the sandbox docs are stale (reference dead Ropsten testnet, conflicting hostnames, may be partner-gated and require emailing Developer Support to clear SMS). **If sandbox is dead, fall back to the in-repo `PaperExecutor` + a prod read-only key.** Do not block the project on the sandbox.

**Rung 1 — Public market data (no auth).** `GET /v3/available_books`, `/ticker`, `/order_book`. Validates HTTP client, JSON parsing, symbol mapping with zero key risk.

**Rung 2 — Authed read-only (zero spend).** With the trade-only key, sign `GET /api/v3/balance` and `GET /account_status`. A `200` + parseable JSON is the single best proof that signature + nonce + key + IP-allowlist all work. This is the canary; gate ALL order placement behind it passing this session.

**Rung 3 — Prove the key cannot withdraw (fail-closed).**
⚠️ **Corrected mechanism (the naive version is unsafe):** there is **no endpoint that returns a key's own permission scopes**, and firing a real withdrawal to "prove it fails" can *succeed* if the key were misconfigured with withdrawals + an empty (fail-open) address allowlist. Instead:
- (a) Rely on **scope-at-creation** (you never ticked "Make withdrawals") as the primary control; and
- (b) if you want a runtime negative-proof, sign a **deliberately un-executable** withdrawal (sub-minimum amount + empty/invalid destination) and assert it is rejected with auth error **`0202`** ("API key is not authorized to execute the requested method") — distinct from `0201` (bad signature) and from any `400` validation error. Treat any `2xx` or a `400`-validation result as **FAIL** and refuse to arm.

**Rung 4 — Read live constraints.** `GET /v3/available_books` → load `minimum_value`, `minimum_amount`, `tick_size` for the chosen book. `GET /api/v3/fees` → load the *actual* account taker/maker tier. **Never hardcode** the 10 MXN floor or the 0.78% fee.

**Rung 5 — One tiny test order.** Place ONE order at/near the **10 MXN floor** (e.g. 10–20 MXN) on a liquid MXN book, **gated behind the policy kill-switch + a temporarily-lowered per-tx cap**. ⚠️ **Kill-path test caveat:** a *market* buy fills instantly, so a follow-up `cancel_all` cancels nothing and proves nothing. To exercise cancellation, place a **resting limit order far from market** (won't fill) → confirm it's open → `DELETE /api/v3/orders/all` → confirm it's gone. *Then* do the tiny market/marketable-limit buy.

**Rung 6 — Reconcile (the real validation).** Confirm the fill via `GET /api/v3/user_trades` (authoritative, time-unbounded, keyed by `oid`) — **not** `GET /orders` alone, which drops completed orders after ~1h. **Measure realized effective cost** (fill price + reported fee vs public order-book mid) and reconcile against the assumed cost model. **If effective cost >> ~0.4%, you are on the spread path or a worse tier than assumed — STOP and switch routing before enabling the loop.**

**Rung 7 — The real ~195–200 MXN order**, single leg, one top-cap allowlisted asset (`btc_mxn` or `eth_mxn`), then HOLD. Only after a clean reconcile do you enable the autonomous loop.

---

## 5. CODEBASE work

### Build native, NOT CCXT
Bitso auth is plain HMAC-SHA256 — fully stdlib (`hmac` + `hashlib` + `urllib` + `json`). CCXT pulls in `requests` + `cryptography` + async deps + compiled wheels (a Windows build-tool risk) — a large, harder-to-audit blast radius for one signed POST per trade, contradicting the stdlib-only ethos. **Verdict: native `BitsoExecutor`.**

### Signing (verified)
```
signature = hex(HMAC-SHA256(secret, nonce + HTTP_method + request_path + json_body))
header:   Authorization: Bitso {key}:{nonce}:{signature}
```
- Sign the **exact byte string you send** — serialize the JSON body **once**; re-serializing after signing is the classic silent 401.
- `request_path` must include any query string.
- **Nonce:** Bitso deprecated Nonce v1 (Nov 2025). Use **Nonce v2** = 13-digit epoch-**milliseconds** + a 1–6 digit random salt (recommend 6). Mint as `max(now_ms_v2, last+1)` behind a process lock; **persist the last nonce in the crash-safe journal** so an NTP step-back or restart can't regress it. Serialize *all* signed calls through one monotonic nonce source; never share a key across concurrent processes.
- Add a **golden-vector unit test** (your own fixture vs `openssl`) before the first live call.

### Refactor the Executor: place ≠ fill (load-bearing)
The current `Executor` Protocol (`treasuryforge/executor.py:20-21`) is synchronous `execute(intent, tick, wallet) -> Fill`, which assumes an atomic fill. **Bitso's `POST /orders` returns ONLY `{success, payload:{oid}}` — no price, no fee.** Split into a two-phase contract:
- `place_order(intent) -> oid / origin_id`
- `reconcile(oid, origin_id) -> Fill` — poll `GET /user_trades` (NOT `GET /orders` alone), **VWAP-aggregate** multi-trade executions into one Fill, sum the fees. Add an explicit **`resting/unfilled`** outcome distinct from Fill so only real executions mutate the wallet. Keep `SimExecutor` conforming (its fill is synchronous but returns through `reconcile()`).
- Bitso has **no private user-data websocket** — own-order status is REST-poll only (~2–5s, capped).

### Extend the data model (current gaps, verified in `types.py`)
- **`Intent`** has only `symbol/side/base_amount/reason`. Add `order_type` (MARKET|LIMIT, **default MARKET** so the 55 tests + SimExecutor stay valid), `limit_price`, an optional `quote_amount` (maps to Bitso `minor` for a "spend exactly 200 MXN" buy — **market-only**; reject `quote_amount`+LIMIT). For maker-only, the executor must translate to Bitso's `time_in_force="postonly"` — there is **no raw `post_only` field** in the API.
- **`Fill`** hard-codes the fee as quote-denominated (`types.py:64-74`). ⚠️ **Bitso charges the BUY fee in the BASE asset received** (`fees_currency`). Generalize `Fill` to carry `fee_currency` and debit the correct leg, reading `fees_amount`/`fees_currency` from `user_trades`. *If unfixed, every live BUY reconciles as a mismatch and permanently false-trips the kill-switch.*

### Fix the fee model (load-bearing)
`SimExecutor` defaults `fee_rate=0.001` (0.10%) — ~7–8× below Bitso's real 0.78% MXN taker. Set `BitsoExecutor` and the **Phase-2 cost-aware Deflated-Sharpe / purged-CV gate** to the **live** rate from `GET /fees` (≥0.78% taker / 0.60% maker per side; ~1.56%/1.20% round-trip). A strategy that passes the gate at 0.1% can be net-negative at 0.78%.

### Policy engine additions
- **Min-notional FLOOR:** extend the existing per-tx notional cap to also reject any intent below the live `minimum_value` (and check `tick_size` price-alignment + base `minimum_amount`). Read live; never hardcode.
- **Liquid-pair allowlist (tighten existing rule-4):** restrict to liquid MXN majors (`btc_mxn`, `eth_mxn`, `usdt_mxn`) — a leaked trade-only key can still drain a balance via self-trade/pump-and-dump on an *illiquid* book (the real, documented residual risk; e.g. the 3Commas ~$22M 2022 leak). At 11 USD the attack is pointless, but it's the right guardrail as size grows.
- **Activate the inert staleness gate:** in live mode pass a **real `data_age_ns`** (from wall-clock/`time.monotonic_ns()` receipt time — **NOT** `MarketTick.ts`, which is an integer step counter) into `evaluate()`; set `max_staleness_ns ≈ 2–3× poll interval`. Today the gate never fires.
- **Bind tick-windows to 24h wall-clock** in live mode, or the "daily" caps (`window_steps`, `spend_window_steps`) stay meaningless.
- **Idempotency:** derive `origin_id` deterministically from the journaled decision id (≤40 chars, `[A-Za-z0-9_-]`), persist it **before** the POST. ⚠️ `origin_id` uniqueness is **active-orders-only** — after a fast fill it's reusable, so a timeout+retry can double-buy. The **journal**, not the exchange, is the at-most-once source of truth: gate retries on journal state; on any UNKNOWN, reconcile via `user_trades` **before** any re-POST; use a **fresh** `origin_id` per attempt to keep reconciliation unambiguous. Add a "retry-after-fill" test proving no second order.

### Defensive error handling (Bitso-specific)
Dispatch on HTTP status **then** `error.code`:
- Rate limit is **HTTP 420** (not 429), 60 rpm public / 300 rpm private (cancels exempt). A retry storm escalates a 1-min lockout to a **24h block** — never tight-retry; ≥60s exponential backoff + jitter; self-meter client-side well under 300 rpm (Bitso publishes no quota headers).
- `0202` = not authorized; `0213` = off-allowlist IP (give it a distinct "check IP allowlist" message, don't fold into a generic 401); `0379` insufficient funds (non-retryable); `0377/0378` = submitted-but-not-final (poll, never resubmit); `0201`/`0215` auth-fatal; `0206/0207` nonce.
- Treat 5xx/timeout as **INDETERMINATE** → resolve via `user_trades`/`origin_ids` lookup, never blind-retry. Fail-closed and loud on auth/permission/IP errors. Parse decimals as `Decimal`, never float; use **per-asset tolerances** in reconcile (BTC ≤ ~1 quantum, MXN ≤ 0.01) — do **not** reuse SimWallet's blanket `1e-9` clamp.

### Kill-switch / flatten
Wire `cancel_all()` = `DELETE /api/v3/orders/all` (cancellations are rate-limit-exempt — the panic channel always lands). Don't assume success from a `200`; re-query open orders (a *filled* order is silently absent from the cancelled array). Spot has no "close position" — flatten = enumerate non-MXN balances and market-sell each `*_mxn`, skipping sub-floor dust with an alert. Add a standalone **client-side watchdog** (separate read-only key) firing `cancel_all` on heartbeat loss — Bitso has **no server-side dead-man-switch**. At 11 USD with market-only orders nothing rests, so this is near-zero risk today but mandatory before any resting-limit strategy.

### PaperExecutor for parity
Same `BitsoExecutor` class, `base_url` as a single config constant — but the env switch must bind **`{base_url, api_key, api_secret}` as one atomic profile** (sandbox requires separate accounts AND separate credentials; "only the URL changes" is wrong and risks cross-wiring creds).

---

## 6. Costs at ~11 USD — is the trade even viable?

**Verified live (2026-06-16):**
| | Maker | Taker | Round-trip (taker) |
|---|---|---|---|
| Bitso `*_mxn` book | 0.60% | 0.78% | **~1.56%** (~3.1 MXN on 200 MXN) |
| Bitso USD/stablecoin book | 0.30% | 0.36% | ~0.72% |
| Consumer "Quick Buy/Convert" | — | hidden ~1.5–2% spread | **~3–4% (avoid)** |

- **Minimums:** `minimum_value = 10 MXN`; 200 MXN clears it ~20×. `minimum_amount` is tiny (`btc_mxn` 0.0000006 BTC). 200 MXN is round-trippable and won't get trapped as dust. **Do not assume `btc_mxn` is the only choice** — read live; pick the book where `max(minimum_amount × price, minimum_value) ≤ notional`.
- **Slippage:** non-issue at 11 USD — the order never walks the book. Live top-of-book spread on BTC/MXN is <0.02%. Cost ≈ fee + half-spread, NOT a depth-impact curve. Add a pre-trade spread guard (read public `order_book`, abort if estimated effective cost > ~1.5%).
- **Dust tail:** Bitso has **no public dust-convert sweep**. Enforce an executor invariant: never leave a residual whose post-trade MXN value < `minimum_value` (10 MXN). Single full-exit at 200 MXN avoids it; the agent must be structurally prevented from creating sub-floor residuals.

**Viability verdict:** the trade is **viable as a validation, not as a profit event.** The dominant cost is fees, not the fiat rail or minimums. A high-frequency mechanical strategy at this size is eaten alive by the ~1.2–1.6% round-trip hurdle. **Honest expected outcome: you end ~3–4 MXN down on a flat market — that is tuition for proving the live executor works.** The mechanical edge must clear this hurdle *in the backtest gate* before the autonomous loop is enabled. **Real risk of loss is 100% of the ~200 MXN** (price + fees + counterparty), but the *price-driven* total-loss tail is near-zero short-term for a top-cap asset (BTC ~52% annualized vol) — provided you stay on BTC/ETH, never a microcap.

---

## 7. Mexican tax & legal notes

> ⚠️ **CONFIRM WITH A PRIMARY SAT SOURCE OR A MEXICAN CONTADOR BEFORE RELYING ON ANY NUMBER OR SCALING.** Every tax figure below comes from **secondary sources (blogs/advisories), not primary SAT/LISR/DOF text.** This section is orientation, not advice. **None of it blocks the first trade.**

**What is reasonably settled (legal frame):**
- **Individual own-funds crypto trading is legal in Mexico.** No personal license, CNBV/Banxico/AMIB registration, or SAT anti-lavado (SPPLD) filing is required for a persona física trading her own funds. The restrictive rules bind banks, fintechs/ITFs, and providers — not the retail end-user.
- **Buying/holding is NOT a taxable event.** Only a **disposal** (`enajenación`: sell, **crypto-to-crypto swap**, crypto-to-stablecoin swap, or paying with crypto) triggers ISR. So **the first 200 MXN BUY is clean.**
- **CARF / automatic exchange-to-SAT reporting is arriving** (Mexico is in a later OECD wave — data collection ~2027, first exchange ~2028; some MX guides cite a 2026 RMF real-time-reporting rule that targets goods/services platforms, *not specifically crypto*). Bottom line: **assume your Bitso activity becomes visible to SAT** — "too small to be seen" is not a durable posture. Bitso does **not** withhold ISR; you self-report.

**What is genuinely uncertain (do NOT hard-code):**
- The **annual `enajenación de bienes` exemption** is cited variously as ~60,000 MXN or ~128,383 MXN (3× annual UMA) — and it is *legally unsettled* (PRODECON characterization) whether crypto even qualifies for the Art. 93 "bienes muebles" exemption at all. At 200 MXN any gain is de minimis and almost certainly below any threshold, but **do not encode an "exempt below X" rule.**
- ISR rate framing (progressive 1.92%–35%) and any "20% provisional withholding" claim are secondary/contested. The 20% figure likely belongs to the digital-platforms regime, not retail spot sales — **unconfirmed.**

**The real, immediate obligation (cheap, do it now):**
- **Record-keeping from trade #1.** CFF Art. 30 mandates ~5-year retention; missing records → SAT can default cost basis to **zero** and tax full proceeds. The **bright line to never cross:** never accept/pool/custody/trade **third-party funds**, and never offer paid signals/management-as-a-service — that triggers CNBV "Asesor en Inversiones" registration and/or the provider AML regime. Keep treasuryforge strictly single-user/own-funds (document this in a `SCOPE.md`).

**Codebase action:** extend the HMAC-audited journal into a per-fill, per-lot FIFO tax ledger (UTC timestamp, pair, side, qty, fill price, fee + `fee_currency`, **MXN value at fill**, exchange `oid`/`tid`), with CSV export. Store raw lot data so either FIFO/PEPS *or* costo-promedio (and the Art. 124 INPC inflation adjustment) can be computed later. Treat every swap as a disposal. Read `bitso.com/legal` to confirm the ToS stance on automated/bot trading before any *recurring* automation (not required for the one-off test).

---

## 8. Custody & API-key security stance

**Custody decision: keep the ~200 MXN in Bitso exchange custody. Do NOT self-custody.** Three independent reasons, all consensus:
1. **Economically self-defeating:** a hardware wallet (54–249 USD) is 5–22× the position; on-chain/withdrawal fees dwarf 11 USD.
2. **Structurally incompatible** with an autonomous API agent — cold storage needs a manual signed transfer per trade.
3. **It inverts the safety thesis:** a raw private key cannot be made "no-withdrawal" the way a scoped exchange key can — a leaked key = 100% instant loss with no permission gate.

The custody choice **licenses the security stance at zero functional cost:** because funds stay on-exchange, the bot key never needs withdrawal scope.

**The stance, and why:**
- **Trade-only, no-withdrawal:** `Place orders` + `View balances` ON; `Make withdrawals` **and** `Perform security actions` OFF. A leaked key can only churn trades inside the tiny balance — which the policy engine's rate-limit/cumulative-spend/notional/solvency rules further bound. It **cannot exfiltrate funds.** Make this a property of the **code**, too: the executor has **zero withdrawal code path** + a fail-closed startup self-check (Rung 3).
- **IP allowlist:** the outer wall. Pin to the static VPS IP. A leaked key is then also unusable off-host. *If* a static IP is genuinely unavailable, you may launch zero-IP (Bitso doesn't force it and — unlike Binance — doesn't auto-expire un-IP'd keys) and rely on no-withdrawal + the policy engine, but **document the weaker posture.**
- **Residual risk acknowledged:** counterparty (Bitso insolvency/freeze) is the remaining risk, financially negligible at 11 USD. No IPAB insurance; UIF can freeze accounts without a judicial order. Mitigate for free: fund from your own KYC-name-matched account, small explainable amounts, keep on-exchange balances tiny, never route third-party money.
- **Rare manual withdrawals** (if ever) go through the authenticated **web UI with 2FA + address allowlist** — never the bot key, never automated.

Secret storage: OS keychain (DPAPI) via `keyring`, never env/plaintext/logs (§3.12). DPAPI does not stop same-user malware — the no-withdrawal scope remains the real cap.

---

## 9. GO / NO-GO gate

**Every line must be GREEN before the 200 MXN is risked.**

**Owner / account**
- [ ] KYC fully approved (CURP/INE + selfie).
- [ ] Biometric-CURP requirement checked in *live* onboarding (obtained if demanded).
- [ ] 2FA = authenticator app (TOTP); emergency restore code saved offline on a separate device; TOTP seeded into a backup.
- [ ] ~200 MXN funded via SPEI from your **own same-name** CLABE; no other capital on-exchange.
- [ ] API key created: **Place orders + View balances ON; Make withdrawals + Perform security actions OFF.**
- [ ] IP allowlist enabled, set to the executor's **verified static egress IP** (`curl ifconfig.me` confirmed).
- [ ] Secret stored in keychain; **not** in git/env/logs/journal.

**Codebase**
- [ ] HMAC signer passes the golden-vector test; **Nonce v2** + journal-persisted monotonic nonce.
- [ ] Executor split into `place_order` + `reconcile` (poll `user_trades`, VWAP-aggregate, explicit unfilled outcome).
- [ ] `Fill` carries `fee_currency`; BUY fee debited from the **base** leg.
- [ ] Cost gate + executor fee set to **live `GET /fees`** (≥0.78% taker), not 0.1%.
- [ ] Min-notional FLOOR + `tick_size` check from live `available_books`; liquid-pair allowlist enforced.
- [ ] Staleness gate active (real wall-clock `data_age_ns`); tick-windows bound to 24h.
- [ ] Idempotency: fresh journaled `origin_id` per attempt; reconcile-before-retry 3-state machine; retry-after-fill test passes.
- [ ] `cancel_all()` wired; error taxonomy handles **HTTP 420** + backoff (no tight-retry).
- [ ] Per-asset `Decimal` reconcile tolerances (not the `1e-9` clamp).
- [ ] Tax/audit ledger emits a per-fill record (incl. MXN value at fill) from trade #1.

**Validation ladder (in order, each gated)**
- [ ] Rung 1 public data OK → Rung 2 signed `GET /balance` = 200 → Rung 3 withdrawal probe = `0202` (fail-closed) → Rung 4 live min/fee read → Rung 5 kill-path proven on a **resting limit** order → tiny order filled → Rung 6 **realized effective cost ≤ ~1.5%** (else STOP) → reconciled clean.

**Posture**
- [ ] You accept the ~200 MXN as fully at-risk burn-in capital with **no regulatory recourse** for self-inflicted bot losses, and the trade framed as **validation, not profit.**

**If any box is red → NO-GO.**

---

## 10. Open questions only the owner can answer

1. **Static IP:** will the executor run from the Netcup VPS (152.53.167.28) for a stable allowlisted egress, or do you accept the weaker zero-IP + no-withdrawal posture?
2. **Biometric CURP:** does Bitso's *live* onboarding demand it, and do you have it? (Verify at signup; obtain at RENAPO if needed.)
3. **Same-name CLABE:** do you have a Mexican bank account in your **exact legal name** able to send SPEI?
4. **Sandbox vs paper:** after live-probing `api-sandbox.bitso.com`, is it usable for an individual — or do you fall back to the in-repo `PaperExecutor` + prod read-only key?
5. **Contador:** will you get a one-time written opinion on ISR treatment / the exemption figure / whether bot frequency risks reclassification to *actividad empresarial* — **before** the strategy starts *selling*? (The first buy needs none.)
6. **ToS on bots:** are you comfortable proceeding on the one-off test before reading `bitso.com/legal` on automated trading? (Read it before *recurring* automation.)
7. **First asset:** `btc_mxn` or `eth_mxn` for trade #1? (Both top-cap, deepest books, lowest market-total-loss risk.)
8. **Loss tolerance confirmation:** are you explicitly OK ending the rehearsal ~3–4 MXN down, with the full ~200 MXN at risk and no recourse?

---

*Load-bearing live figures (`minimum_value = 10 MXN`; flat_rate maker 0.60% / taker 0.78% on btc_mxn/eth_mxn/usd_mxn) re-verified against `https://api.bitso.com/v3/available_books/` on 2026-06-16. Re-fetch at go-live — fees are 30-day-volume-tiered and minimums are per-book and can change. All tax/legal figures are secondary-sourced and must be confirmed with SAT or a contador before scaling.*