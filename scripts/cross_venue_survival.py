"""Cross-venue spread SURVIVAL model (Roadmap v2 P2/P3) -- reuse the validated machinery.

The veredicto asked for a simple, auditable, hard-to-overfit persistence model (hazard /
survival, NO deep learning). We already have exactly that: funding_persistence (episode
durations under hysteresis) + funding_predictor.conditional_reach (P[survives age+horizon |
survived to age]) -- the same OOS-validated tooling that worked for single-venue. This
applies it to the cross-venue SPREAD series (HL vs OKX), so the entry gate becomes:
"enter only after the spread has been ON long enough that its survival probability is high".

    python scripts/cross_venue_survival.py --coin XRP --horizon 6
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue_economics import HOURS_PER_YEAR, breakeven_spread_apr
from treasuryforge.funding_persistence import funding_persistence
from treasuryforge.funding_predictor import survival_curve


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "tf/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="XRP")
    ap.add_argument("--hold", type=int, default=336)
    ap.add_argument("--horizon", type=int, default=6, help="survival horizon in 8h windows")
    ap.add_argument("--max-age", type=int, default=12)
    args = ap.parse_args()
    be = breakeven_spread_apr(args.hold)

    hl_rows = _post("https://api.hyperliquid.xyz/info",
                    {"type": "fundingHistory", "coin": args.coin, "startTime": 0})
    hl = sorted((int(r["time"]), float(r["fundingRate"]) * HOURS_PER_YEAR) for r in hl_rows)
    okx = sorted((int(r["fundingTime"]), float(r["fundingRate"]) * 3 * 365) for r in
                 _get(f"https://www.okx.com/api/v5/public/funding-rate-history?instId={args.coin}-USDT-SWAP&limit=100")["data"])
    spreads = [abs(min(hl, key=lambda x: abs(x[0] - t))[1] - okx_apr) for t, okx_apr in okx] if hl else []

    # episodes = runs of spread above break-even; survival = P(lasts horizon more | survived to age)
    stats = funding_persistence(spreads, enter_rate=be, exit_rate=be * 0.8, breakeven_intervals=args.horizon)
    curve = survival_curve(stats.durations, breakeven=args.horizon, max_age=args.max_age)

    print(f"CROSS-VENUE SPREAD SURVIVAL -- {args.coin}, break-even {be:.1%} APR, horizon {args.horizon}x8h\n")
    print(f"  episodes: {stats.n_episodes}  median {stats.median_duration:.0f}x8h  "
          f"reach-horizon base {stats.pct_reach_breakeven:.0%}")
    print(f"  {'age (x8h)':>10}{'P(survive +horizon | survived to age)':>40}")
    for age, p in curve:
        bar = "#" * int(p * 30)
        print(f"  {age:>10}{p:>10.0%}  {bar}")
    print("\n(rising P with age = survival MOMENTUM: enter only after the spread has proven N windows."
          " This is the entry gate's persistence term -- same OOS-validated hazard tooling as single-venue.)")


if __name__ == "__main__":
    main()
