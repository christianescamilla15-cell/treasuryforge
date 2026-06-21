"""Close the loop with REAL data: MEASURE -> VALIDATE(DSR) -> SIZE(f=DSR*Kelly/2)
-> SURVIVE(risk-of-ruin gate). Funding-carry on real Hyperliquid data, no funds.

    python scripts/assess_strategy.py --coin ETH --days 180

Teaching point: the funding-only return series UNDERSTATES the real risk (it omits
basis/liquidation tails). So we assess twice — naive, and STRESSED (adverse-regime
shift + fat-tail shocks). The module is only as honest as the distribution you feed it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest import backtest_funding_carry
from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.risk import StrategyRiskPolicy, kelly_leverage, monte_carlo_ruin
from treasuryforge.signals.funding import FundingCarryParams

HPY = 24 * 365


def _post(b):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(b).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_funding(coin, days):
    now = int(time.time() * 1000); start = now - days * 24 * 3600 * 1000
    out, seen = [], set()
    while start < now:
        rows = _post({"type": "fundingHistory", "coin": coin, "startTime": start})
        new = [r for r in rows if r["time"] not in seen]
        if not new:
            break
        for r in new:
            seen.add(r["time"]); out.append(float(r["fundingRate"]))
        start = new[-1]["time"] + 1; time.sleep(0.12)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="ETH")
    ap.add_argument("--days", type=int, default=180)
    args = ap.parse_args()

    rates = fetch_funding(args.coin, args.days)
    print(f"=== {args.coin} funding, {len(rates)} hourly obs (~{len(rates)/24:.0f} days) ===\n")

    # ---- 1. MEASURE (grid -> best by return, collect per-obs trial Sharpes) ----
    fee = 0.0003
    trials = []
    for er in (1e-6, 5e-6, 1e-5, 2e-5):
        for ex in (-5e-5, -1e-5, 0.0):
            if ex > er:
                continue
            p = FundingCarryParams(enter_rate=er, exit_rate=ex, fee_per_leg=fee)
            res = backtest_funding_carry(rates, p)
            trials.append((res.total_return, p, res, sharpe_ratio(res.returns)))
    best = max(trials, key=lambda t: t[0])
    R = best[2].returns
    trial_sharpes = [t[3] for t in trials]
    E = sum(R) / len(R); sd = (sum((x - E) ** 2 for x in R) / len(R)) ** 0.5

    # ---- 2. VALIDATE ----
    sr = sharpe_ratio(R, HPY)
    dsr = deflated_sharpe_ratio(R, trial_sharpes=trial_sharpes)
    print(f"1) MEASURE   E[r]={E:.2e}/hr  sigma={sd:.2e}  Sharpe(ann)={sr:.1f}")
    print(f"2) VALIDATE  DSR={dsr:.3f}  (prob. the edge is real after deflating {len(trials)} configs)"
          )

    # ---- 3. SIZE: f = DSR * (1/2) * Kelly, capped to a sane account leverage ----
    Lk = kelly_leverage(R)
    HARD_CAP = 5.0
    f = min(dsr * 0.5 * Lk, HARD_CAP)
    print(f"3) SIZE      full-Kelly L*={Lk:.0f}x  ->  f = DSR*0.5*Kelly = {dsr * 0.5 * Lk:.1f}x "
          f"(capped at {HARD_CAP:.0f}x) -> use {f:.2f}x")

    # ---- 4. SURVIVE: risk-of-ruin gate, naive vs stressed ----
    pol = StrategyRiskPolicy(kelly_fraction=0.5, max_leverage=HARD_CAP, min_dsr=0.6,
                             max_p_ruin=0.05, ruin_drawdown=0.30, max_expected_drawdown=0.20)
    print(f"\n4) SURVIVE   risk-of-ruin gate at f={f:.2f}x (ruin = -30% drawdown):")
    naive = monte_carlo_ruin(R, leverage=f, ruin_drawdown=0.30, paths=4000, seed=1)
    # stress models the basis/liquidation tails the funding-only series OMITS
    stressed = monte_carlo_ruin(R, leverage=f, ruin_drawdown=0.30, paths=4000, seed=1,
                                adverse_shift=2 * E, tail_shock_prob=0.002, tail_shock_mult=8.0)
    print(f"   naive     P(ruin)={naive.p_ruin:.2%}  E[maxDD]={naive.expected_max_drawdown:.2%}  cap_median={naive.median_final_multiple:.2f}x"
          )
    print(f"   STRESSED  P(ruin)={stressed.p_ruin:.2%}  E[maxDD]={stressed.expected_max_drawdown:.2%}  cap_median={stressed.median_final_multiple:.2f}x  (adverse regime + liq tails)"
          )

    res = pol.assess(R, leverage=f, dsr=dsr, adverse_shift=2 * E, tail_shock_prob=0.002,
                     tail_shock_mult=8.0, paths=4000, seed=1)
    print("\nVERDICT (stressed): {}".format(res["verdict"].upper()))
    for name, ok, detail in res["gates"]:
        print(f"   [{'OK ' if ok else 'XX '}] {name}: {detail}")
    print("\nLESSON: the funding-only series looks safe (naive); the honest answer needs"
          " the basis/liquidation tails. The module is only as truthful as its input"
          " distribution — feed it stress, not just the happy path.")


if __name__ == "__main__":
    main()
