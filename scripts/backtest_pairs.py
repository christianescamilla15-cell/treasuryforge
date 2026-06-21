"""Scan a basket of coins for cointegrated pairs on REAL Hyperliquid price data,
then backtest the cointegrated ones through the gate. Keyless, no funds.

    python scripts/backtest_pairs.py --interval 1h --days 120 --fee 0.0005

This is where you SEE the research live: most pairs do NOT cointegrate, and the
ones that do give a MODEST (often cost-killed) edge — not the 1.5-3.0 Sharpe
marketed. Honest scope: a passing in-sample cointegration + backtest is necessary,
NOT sufficient — the relationship can break out-of-sample (purged-CV exposes it).
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest import backtest_pairs
from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.signals.cointegration import engle_granger

INTERVAL_HOURS = {"1h": 1, "4h": 4, "1d": 24}


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def fetch_closes(coin: str, interval: str, days: int) -> dict[int, float]:
    now = int(time.time() * 1000)
    start = now - days * 24 * 3600 * 1000
    out: dict[int, float] = {}
    cur = start
    while cur < now:
        candles = _post({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval, "startTime": cur, "endTime": now}})
        if not candles:
            break
        new = [c for c in candles if c["t"] not in out]
        if not new:
            break
        for c in new:
            out[c["t"]] = float(c["c"])
        cur = new[-1]["t"] + 1
        time.sleep(0.12)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1h", choices=list(INTERVAL_HOURS))
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--coins", default="BTC,ETH,SOL,AVAX,ARB,OP,LINK,LTC,DOGE,BNB")
    ap.add_argument("--stop-z", type=float, default=4.0)
    ap.add_argument("--regime-window", type=int, default=240)
    ap.add_argument("--max-half-life", type=float, default=240.0)
    args = ap.parse_args()
    ppy = int(24 * 365 / INTERVAL_HOURS[args.interval])

    coins = [c.strip() for c in args.coins.split(",")]
    series = {}
    for c in coins:
        s = fetch_closes(c, args.interval, args.days)
        if len(s) > 100:
            series[c] = s
    common = sorted(set.intersection(*[set(s) for s in series.values()]))
    print(f"{len(series)} coins, {len(common)} aligned {args.interval} bars "
          f"(~{len(common)*INTERVAL_HOURS[args.interval]/24:.0f} days)\n")
    aligned = {c: [series[c][t] for t in common] for c in series}

    pairs = list(itertools.combinations(sorted(aligned), 2))
    results = []
    for x, y in pairs:
        r = engle_granger(aligned[x], aligned[y])
        if r.cointegrated and r.half_life != float("inf"):
            common_kw = dict(alpha=r.alpha, beta=r.beta, window=60, entry_z=2.0,
                             exit_z=0.5, fee_per_leg=args.fee)
            bt = backtest_pairs(aligned[x], aligned[y], **common_kw)
            btg = backtest_pairs(aligned[x], aligned[y], stop_z=args.stop_z,
                                 regime_gate=True, regime_window=args.regime_window,
                                 max_half_life=args.max_half_life, **common_kw)
            results.append((x, y, r, bt, btg))

    print(f"pairs tested: {len(pairs)}   cointegrated (5%): {len(results)}")
    # selection bias = the dispersion of per-obs Sharpes across the pairs we ranked
    trial_sharpes = [sharpe_ratio(t[3].returns) for t in results]
    results.sort(key=lambda t: t[4].sharpe(ppy), reverse=True)   # rank by the GATED Sharpe

    print(f"\n{'':24}|{'  UNGATED (naive band)':^22}|{'  GATED (regime+stop-z)':^26}")
    print(f"{'pair':14}{'half-life':>10}|{'trades':>7}{'net':>8}{'Shrp':>7}|"
          f"{'trades':>7}{'gated':>7}{'net':>8}{'Shrp':>7}{'DSR':>6}")
    for x, y, r, bt, btg in results[:12]:
        dsr = deflated_sharpe_ratio(btg.returns, trial_sharpes=trial_sharpes)
        hl = f"{r.half_life:.0f}h" if r.half_life < 1e4 else "inf"
        print(f"{x+'/'+y:14}{hl:>10}|{bt.n_trades:>7}{bt.total_return:>+8.1%}"
              f"{bt.sharpe(ppy):>7.2f}|{btg.n_trades:>7}{btg.n_gated:>7}"
              f"{btg.total_return:>+8.1%}{btg.sharpe(ppy):>7.2f}{dsr:>6.2f}")

    # Honest aggregate: did gating help, on the pairs that survived cointegration?
    if results:
        d_sharpe = [t[4].sharpe(ppy) - t[3].sharpe(ppy) for t in results]
        improved = sum(1 for d in d_sharpe if d > 0)
        print(f"\nGATING EFFECT across {len(results)} cointegrated pairs: "
              f"Sharpe improved on {improved}/{len(results)}, "
              f"mean dSharpe {sum(d_sharpe)/len(d_sharpe):+.2f}, "
              f"trades {sum(t[3].n_trades for t in results)} -> {sum(t[4].n_trades for t in results)}.")
    print("\nNOTE: in-sample cointegration mining over many pairs OVERFITS. The gate"
          " can only REMOVE trades (it never invents edge) -- its job is to skip the"
          " regimes where the spread has stopped reverting. If dSharpe is ~0 or"
          " negative, the gate isn't helping HERE and we say so; net-of-cost at this"
          " frequency the underlying edge is often thin or gone (research: dies daily).")


if __name__ == "__main__":
    main()
