"""Backtest delta-neutral funding-carry on REAL Hyperliquid history, through the
overfitting gate (Deflated Sharpe + purged-CV). Keyless, no funds.

    python scripts/backtest_funding.py --days 180 --coins BTC,ETH,SOL --fee 0.0005

Honest scope: models funding accrued minus entry/exit costs on a delta-neutral
book. It does NOT model basis risk, perp liquidation on a price gap, or funding
settlement edge cases — so a passing DSR is NECESSARY, not sufficient.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest import backtest_funding_carry
from treasuryforge.backtest.cv import purged_kfold
from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.signals.funding import FundingCarryParams

HOURS_PER_YEAR = 24 * 365


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_funding(coin: str, days: int) -> list[float]:
    now = int(time.time() * 1000)
    start = now - days * 24 * 3600 * 1000
    rates: list[float] = []
    seen = set()
    while start < now:
        rows = _post({"type": "fundingHistory", "coin": coin, "startTime": start})
        if not rows:
            break
        new = [r for r in rows if r["time"] not in seen]
        if not new:
            break
        for r in new:
            seen.add(r["time"])
            rates.append(float(r["fundingRate"]))
        start = new[-1]["time"] + 1
        time.sleep(0.15)
    return rates


def grid_search(rates: list[float], fee: float):
    enters = [1e-6, 5e-6, 1e-5, 2e-5, 5e-5]
    # absolute exit thresholds, incl. NEGATIVE = hold through small dips (carry,
    # not churn). Only bail when funding turns meaningfully negative.
    exits = [-5e-5, -2e-5, -1e-5, 0.0, 1e-6]
    trials = []
    for er in enters:
        for ex in exits:
            if ex > er:
                continue
            p = FundingCarryParams(enter_rate=er, exit_rate=ex, fee_per_leg=fee)
            res = backtest_funding_carry(rates, p)
            # rank by total return, not Sharpe, so a do-nothing config can't "win"
            # on a 0/0 Sharpe; we report Sharpe/DSR separately for the winner.
            trials.append((res.total_return, p, res))
    n_trials = len(trials)
    best = max(trials, key=lambda t: t[0])
    trial_sharpes = [sharpe_ratio(t[2].returns) for t in trials]   # per-obs, for DSR
    return best, n_trials, trial_sharpes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--coins", default="BTC,ETH,SOL")
    ap.add_argument("--fee", type=float, default=0.0005, help="taker fee per leg")
    args = ap.parse_args()

    for coin in args.coins.split(","):
        rates = fetch_funding(coin.strip(), args.days)
        if len(rates) < 200:
            print(f"\n{coin}: only {len(rates)} rows, skipping")
            continue
        (_tr, p, res), n_trials, trial_sharpes = grid_search(rates, args.fee)
        sr = sharpe_ratio(res.returns, HOURS_PER_YEAR)
        ann_ret = res.total_return * (HOURS_PER_YEAR / len(rates))
        dsr = deflated_sharpe_ratio(res.returns, trial_sharpes=trial_sharpes)
        pct_in = res.intervals_in_position / len(rates)

        # purged-CV: is the best config consistent across time, not one lucky window?
        fold_sr = []
        for _train, test in purged_kfold(len(rates), k=5, embargo=24):
            seg = [rates[i] for i in test]
            fr = backtest_funding_carry(seg, p)
            fold_sr.append(round(sharpe_ratio(fr.returns, HOURS_PER_YEAR), 2))

        print(f"\n=== {coin}  ({len(rates)} hourly funding obs, ~{len(rates)/24:.0f} days) ===")
        print(f"best params: enter={p.enter_rate:.1e}/hr exit={p.exit_rate:.1e}/hr "
              f"fee={p.fee_per_leg:.2%}/leg roundtrip={p.round_trip_cost:.3%}")
        print(f"trades: {res.n_trades}   time in position: {pct_in:.0%}")
        print(f"total return (net): {res.total_return:+.2%}   annualized: {ann_ret:+.1%}")
        print(f"max drawdown: {res.max_drawdown():.2%}")
        print(f"Sharpe (annualized): {sr:.2f}")
        print(f"Deflated Sharpe Ratio (n_trials={n_trials}): {dsr:.3f}  "
              f"{'PASS (>0.95)' if dsr > 0.95 else 'FAIL (<=0.95)'}")
        print(f"purged-CV per-fold Sharpe: {fold_sr}  (want all clearly >0, consistent)")

    print("\nNOTE: this models funding minus fees only. It omits basis risk, perp"
          " liquidation, and settlement edge cases — a passing DSR is necessary,"
          " NOT sufficient. Real risk-adjusted return is LOWER than shown.")


if __name__ == "__main__":
    main()
