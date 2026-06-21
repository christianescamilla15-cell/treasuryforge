# treasuryforge — Production-Maturity Roadmap

The quant CORE is closed: `strategy → backtest → validation (DSR/purged-CV) →
sizing (DSR·fractional-Kelly) → risk-of-ruin → decision report`. What turns it
into an *institutional* system is the production / falsification / governance
layer below. Designed by Christian; built incrementally.

| # | Layer | Purpose | Status |
|---|-------|---------|--------|
| 1 | **Paper-live + Backtest-Live gap** | catch a strong backtest that dies in the air (latency, real fills, slippage, vanished edge) | ✅ `risk/live_gap.py` |
| 2 | Backtest-to-live degradation score | `E_live / E_backtest` < 0.5 → REJECT: EDGE_DECAYED | ✅ (in #1) |
| 3 | **Kill-switch by statistical drift** | Page-Hinkley on live expectancy (decrease) + slippage (increase) + hard DD band → KILL: EDGE_DRIFT_DETECTED / EXECUTION_DEGRADED / DD_EXCEEDS_STRESS_BAND. Kill, don't wait. | ✅ `risk/drift.py` |
| 4 | Portfolio-level risk | joint risk across strategies: `f ∝ Σ⁻¹μ` with hard caps; gates for CORRELATION_CLUSTER, PORTFOLIO_DD, SAME_REGIME_EXPOSURE | ⬜ |
| 5 | Capacity / market impact | `E(size) = E₀ − a·sizeᵝ`; max tradable size before the edge collapses; recommended live size | ⬜ |
| 6 | Execution-quality report | realized vs modeled slippage, maker fill rate, cancel rate, post-fill drift, adverse selection, latency → EXECUTION_EDGE_LEAK | 🟡 partial (in #1) |
| 7 | **Strategy graveyard** | append-only archive of every rejection (hypothesis, metrics, failure mode, REVIVAL CONDITION, fingerprint) — blocks reviving a corpse until conditions are met; catches disguised re-attempts | ✅ `risk/graveyard.py` |
| 8 | **Reproducibility pack** | deterministic `data/config/strategy/report` hashes + `git_commit / timestamp / environment` + a reproducible content fingerprint on every verdict | ✅ `risk/provenance.py` |
| 9 | **Capital-allocation ladder** | Stage 0 paper → 1% → 3% → 8% → cap; PROMOTE/HOLD/DEMOTE/KILL on live edge-retention / slippage / DD / kill-switch | ✅ `risk/stages.py` |

## The verdict vocabulary (the engine speaks in these)

Decision report: `NO_EDGE · EDGE_IS_NOT_RELIABLE · PATH_TOO_DANGEROUS · DEPLOY_SMALL`
Live gap: `INSUFFICIENT_LIVE_DATA · NO_BACKTEST_EDGE · EDGE_DECAYED · BACKTEST_LIVE_GAP · EXECUTION_EDGE_LEAK · APPROVE_STAGE_1`

## Cold conclusion

> The quant framework decides if the game is winnable, if the capital grows, and
> if you survive the path. The production layer decides whether the real market
> still allows it, whether execution leaks the edge, whether the portfolio can
> collapse together, and whether a dead strategy stays dead. You built the judge;
> these are the cameras on execution so the bot cannot lie to you live.

## Manual Arming Procedure for Live Trading

To transition the autonomous scalp trader from paper mode to real-money execution on the VPS:

1. **Verify Prerequisites**:
   - Run the preflight script to ensure all API, auth, collateral, and relay conditions pass. If operating with a small collateral balance (e.g., ~$20 USDC), provide the appropriate `--tier` (e.g., `0.55`) so that the micro-tier sizing check calculates correctly against the $10 minimum:
     ```bash
     /opt/treasuryforge/.venv/bin/python scripts/preflight_arm.py --mode live --tier 0.55
     ```
   - If using the default 1% micro-tier, ensure the collateral in the Hyperliquid master account is >= $1000.

2. **Configure the systemd service file**:
   - Open `/etc/systemd/system/treasuryforge-scalp.service` (or edit the template in `deploy/` and copy it over).
   - Ensure the `EnvironmentFile` is loaded:
     ```ini
     EnvironmentFile=/etc/treasuryforge/hl.env
     ```
   - Ensure the `ExecStart` line specifies both `--arm` and the correct `--tier` parameter matching your collateral constraints (e.g., `--tier 0.55` for smaller collateral):
     ```ini
     ExecStart=/opt/treasuryforge/.venv/bin/python scripts/run_autonomous.py --top 15 --interval 60 --arm --tier 0.55
     ```

3. **Reload and Restart**:
   ```bash
   systemctl daemon-reload
   systemctl restart treasuryforge-scalp
   systemctl status treasuryforge-scalp
   ```

