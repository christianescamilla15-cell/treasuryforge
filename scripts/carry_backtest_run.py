"""Carry selector economic backtest (C2 follow-up) — does the selector NET more, OOS?

Splits each coin's funding history by time, picks the selected coins on TRAIN (top half
by break-even reach rate), then books the carry economics on TEST for four variants:
fresh-all, age-gated-all, coin-selected, and age+coin. Reports net PnL, win rate, avg
hold, per-position Sharpe and Deflated Sharpe (n_trials reflects the selectors searched).

    python scripts/carry_backtest_run.py --coins HYPE,ZEC,UNI,ENA,NEAR,ASTER,BTC,ETH,SOL,AVAX,ARB,SUI,XRP,WLD --min-age 24
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.carry_backtest import backtest_carry
from treasuryforge.funding_persistence import funding_persistence
from treasuryforge.signals.funding import HyperliquidFundingFeed


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literal
        return json.loads(r.read().decode())


def _reach_rate(hist, enter, exit_, be):
    durs = funding_persistence(hist, enter_rate=enter, exit_rate=exit_, breakeven_intervals=be).durations
    return (sum(1 for d in durs if d >= be) / len(durs)) if durs else 0.0


def _variant(test_hist_by_coin, coins, enter, exit_, rt, min_age, n_trials):
    rets: list[float] = []
    net = funding = cost = 0.0
    holds: list[int] = []
    for coin in coins:
        r = backtest_carry(test_hist_by_coin[coin], enter=enter, exit_=exit_,
                           round_trip=rt, min_age=min_age)
        rets += r.returns
        holds += r.holds
        net += r.net
        funding += r.total_funding
        cost += r.total_cost
    n = len(rets)
    wr = sum(1 for x in rets if x > 0) / n if n else 0.0
    sr = sharpe_ratio(rets) if n >= 2 else 0.0
    dsr = deflated_sharpe_ratio(rets, n_trials=n_trials) if n >= 2 else 0.0
    avg_hold = sum(holds) / len(holds) if holds else 0.0
    return {"n": n, "net_bps": net * 1e4, "win": wr, "hold": avg_hold, "sharpe": sr, "dsr": dsr}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="HYPE,ZEC,UNI,ENA,NEAR,ASTER,BTC,ETH,SOL,AVAX,ARB,SUI,XRP,WLD")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--enter", type=float, default=0.00001)
    ap.add_argument("--exit", type=float, default=0.0000001)   # hold while positive
    ap.add_argument("--round-trip", type=float, default=0.0005)  # 2-leg overlay ~5bps
    ap.add_argument("--breakeven", type=int, default=40)
    ap.add_argument("--min-age", type=int, default=24)
    ap.add_argument("--split", type=float, default=0.7)
    ap.add_argument("--n-trials", type=int, default=24, help="selectors searched (DSR deflation)")
    args = ap.parse_args()

    feed = HyperliquidFundingFeed(_hl_post)
    start_ms = int((time.time() - args.days * 86400) * 1000)
    test_by_coin: dict[str, list[float]] = {}
    train_reach: dict[str, float] = {}
    for coin in (c.strip() for c in args.coins.split(",")):
        hist = feed.funding_history(coin, start_ms)
        if len(hist) < 50:
            continue
        cut = int(len(hist) * args.split)
        train_reach[coin] = _reach_rate(hist[:cut], args.enter, args.exit, args.breakeven)
        test_by_coin[coin] = hist[cut:]
    coins = list(test_by_coin)
    ranked = sorted(coins, key=lambda c: train_reach[c], reverse=True)
    selected = ranked[: max(1, len(ranked) // 2)]

    print(f"CARRY SELECTOR BACKTEST -- {args.days}d, OOS test, round-trip {args.round_trip*1e4:.1f}bps, "
          f"min-age {args.min_age}h\nselected coins (top half by TRAIN persistence): {selected}\n")
    rt, en, ex = args.round_trip, args.enter, args.exit
    variants = {
        "fresh  (all coins)": (coins, 0),
        "age    (all coins)": (coins, args.min_age),
        "coin   (selected) ": (selected, 0),
        "age+coin (selected)": (selected, args.min_age),
    }
    print(f"  {'variant':22}{'n':>4}{'net(bps)':>10}{'win':>6}{'hold':>7}{'Sharpe':>8}{'DSR':>7}")
    for label, (cs, ma) in variants.items():
        v = _variant(test_by_coin, cs, en, ex, rt, ma, args.n_trials)
        print(f"  {label:22}{v['n']:>4}{v['net_bps']:>+10.1f}{v['win']:>6.0%}{v['hold']:>6.0f}h"
              f"{v['sharpe']:>8.2f}{v['dsr']:>7.2f}")
    print("\n(net in bps, OOS. The selector EARNS its keep only if age/coin nets MORE than"
          " fresh-all AND positive. DSR deflates for the selectors searched.)")


if __name__ == "__main__":
    main()
