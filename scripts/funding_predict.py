"""Funding-continuation predictor evaluation (C2) — does it beat the base rate OOS?

Pulls real funding history per coin, splits each series by TIME (train = earlier,
test = strictly later, an embargo against leakage), extracts high-funding episodes in
each window, and tests the two simple selectors against the honest bar -- beating the
out-of-sample fresh-entry reach rate:

  * age rule: enter only after an episode has already survived N hours (survival momentum)
  * coin selection: trade only the coins whose train-period persistence is high

    python scripts/funding_predict.py --coins HYPE,ZEC,UNI,ENA,NEAR,ASTER,BTC,ETH,SOL --days 45
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.funding_persistence import funding_persistence
from treasuryforge.funding_predictor import (
    conditional_reach,
    evaluate_age_rule,
    evaluate_coin_selection,
)
from treasuryforge.signals.funding import HyperliquidFundingFeed


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literal
        return json.loads(r.read().decode())


def _durations(hist, enter, exit_, be):
    return funding_persistence(hist, enter_rate=enter, exit_rate=exit_,
                               breakeven_intervals=be).durations


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="HYPE,ZEC,UNI,ENA,NEAR,ASTER,BTC,ETH,SOL")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--enter", type=float, default=0.00001)
    ap.add_argument("--exit", type=float, default=0.0000001)   # hold while positive
    ap.add_argument("--breakeven", type=int, default=40)
    ap.add_argument("--max-age", type=int, default=24)
    ap.add_argument("--split", type=float, default=0.7)
    args = ap.parse_args()

    feed = HyperliquidFundingFeed(_hl_post)
    start_ms = int((time.time() - args.days * 86400) * 1000)
    be = args.breakeven

    pooled_train: list[int] = []
    pooled_test: list[int] = []
    pc_train: dict[str, float] = {}
    pc_test: dict[str, float] = {}
    pc_reach: dict[str, tuple[int, int]] = {}
    for coin in (c.strip() for c in args.coins.split(",")):
        hist = feed.funding_history(coin, start_ms)
        if len(hist) < 50:
            continue
        cut = int(len(hist) * args.split)
        tr = _durations(hist[:cut], args.enter, args.exit, be)
        te = _durations(hist[cut:], args.enter, args.exit, be)
        pooled_train += tr
        pooled_test += te
        if tr and te:
            pc_train[coin] = conditional_reach(tr, 0, be)
            pc_test[coin] = conditional_reach(te, 0, be)
            pc_reach[coin] = (sum(1 for d in te if d >= be), len(te))

    print(f"FUNDING PREDICTOR (C2) -- {args.days}d, break-even {be}h, train/test {args.split:.0%}/"
          f"{1 - args.split:.0%}, pooled episodes {len(pooled_train)}/{len(pooled_test)}\n")

    age = evaluate_age_rule(pooled_train, pooled_test, breakeven=be, max_age=args.max_age)
    print("1) SURVIVAL-MOMENTUM (enter after age N):")
    print(f"   train base {age.base_rate:.0%} -> best age {age.best_age}h (train {age.train_rate:.0%})")
    print(f"   OOS: fresh {age.test_base_rate:.0%}  vs  age-{age.best_age}h "
          f"{age.test_rate_at_best_age:.0%}  (n={age.n_test_at_risk})  "
          f"-> {'BEATS baseline' if age.beats_baseline else 'does NOT beat'}")

    print("\n2) COIN-SELECTION (trade only persistent coins):")
    sel = evaluate_coin_selection(pc_train, pc_test, pc_reach)
    print(f"   train->test rate correlation {sel.correlation:+.2f}")
    print(f"   selected (top half by train): {sel.selected}")
    print(f"   OOS: selected {sel.selected_test_rate:.0%}  vs  rest {sel.rest_test_rate:.0%}  "
          f"-> {'BEATS baseline' if sel.beats_baseline else 'does NOT beat'}")

    print("\nVERDICT:", "a selector beats the base rate OOS -- worth pursuing"
          if (age.beats_baseline or sel.beats_baseline)
          else "NEITHER simple selector beats the base rate OOS -- discard, no complex model")


if __name__ == "__main__":
    main()
