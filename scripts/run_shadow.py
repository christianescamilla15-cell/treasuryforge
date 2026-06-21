"""Live shadow runner for funding-carry across MANY coins — track record, NO funds.

One invocation = one funding observation PER COIN, each persisted to its own journal
(state/shadow_<coin>) so they accumulate independently. Drive it hourly (systemd) to
match Hyperliquid's funding interval. /info is keyless: no key, no wallet, no money.

    python scripts/run_shadow.py --coins BTC,ETH,SOL,AVAX,ARB

Running several coins in parallel multiplies the evidence-per-hour: it tells us
whether the funding edge is coin-specific or robust, far faster than one coin alone.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.carry_screener import ScreenParams, screen_coin
from treasuryforge.journal import Journal
from treasuryforge.shadow import ShadowBook
from treasuryforge.signals.funding import (
    FundingCarryParams,
    FundingCarrySignal,
    HyperliquidFundingFeed,
    annualize,
)

HOURS_PER_YEAR = 24 * 365


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literal
        return json.loads(r.read().decode())


def _spread(coin: str) -> float:
    levels = _hl_post({"type": "l2Book", "coin": coin}).get("levels", [[], []])
    if not levels[0] or not levels[1]:
        return 0.001
    bid, ask = float(levels[0][0]["px"]), float(levels[1][0]["px"])
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid if mid > 0 else 0.001


def _hourly_vol(coin: str) -> float:
    import math
    now = int(time.time() * 1000)
    candles = _hl_post({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "1h", "startTime": now - 48 * 3600 * 1000, "endTime": now}})
    closes = [float(c["c"]) for c in candles][-25:]
    if len(closes) < 3:
        return 0.001
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    mean = sum(rets) / len(rets)
    return (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="ETH", help="comma-separated, e.g. BTC,ETH,SOL")
    ap.add_argument("--state-prefix", default="state/shadow")
    ap.add_argument("--enter-rate", type=float, default=0.00001)   # per-hour funding to ENTER
    ap.add_argument("--exit-rate", type=float, default=0.000003)   # per-hour funding to EXIT
    ap.add_argument("--fee-per-leg", type=float, default=0.0003)
    ap.add_argument("--legs", type=int, default=2, help="2 = perp overlay on held spot; 4 = fresh")
    ap.add_argument("--gate-hold", type=int, default=40, help="hold (h) the cost-gate assumes")
    ap.add_argument("--min-age", type=int, default=24, help="C2 age-rule: enter after N h of episode")
    args = ap.parse_args()

    params = FundingCarryParams(enter_rate=args.enter_rate, exit_rate=args.exit_rate,
                                fee_per_leg=args.fee_per_leg)
    screen = ScreenParams(hold_hours=args.gate_hold, legs=args.legs)
    feed = HyperliquidFundingFeed(_hl_post)
    ts = int(time.time())

    for coin in (c.strip() for c in args.coins.split(",")):
        book = ShadowBook(FundingCarrySignal(params, min_age=args.min_age),
                          journal=Journal(f"{args.state_prefix}_{coin.lower()}"))
        funding = feed.current_funding(coin)
        # COST-GATE: only consult the screener when an entry is actually on the table;
        # veto it if the net carry over the hold can't beat the round-trip (anti-churn).
        gate = ""
        allow_entry = True
        if not book.signal.in_position and funding >= args.enter_rate:
            opp = screen_coin(coin, funding=funding, premium=0.0,
                              spread=_spread(coin), vol=_hourly_vol(coin), params=screen)
            allow_entry = opp.net_edge > 0
            gate = f"  [gate {opp.verdict.value} net {opp.net_edge_bps:+.1f}bps]"
        action = book.observe(funding, ts=ts, allow_entry=allow_entry)
        rep = book.report()
        line = (f"[{coin:5}] funding={funding:+.8f}/hr "
                f"({annualize(funding, HOURS_PER_YEAR):+.2%} APR) -> {action.value:5}{gate}  "
                f"net {rep.net_return:+.4%}  ({rep.n_intervals} obs, {rep.n_hold} held)")
        if len(rep.returns) >= 30:
            dsr = deflated_sharpe_ratio(rep.returns, n_trials=1)
            sr = sharpe_ratio(rep.returns, periods_per_year=HOURS_PER_YEAR)
            line += f"  Sharpe {sr:.2f}  DSR {dsr:.3f}"
        print(line)


if __name__ == "__main__":
    main()
