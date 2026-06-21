"""Falsify MR_SCALP_ZSCORE_V1 on real Hyperliquid 1m data, net of cost.

Built to KILL it cleanly: sweeps 3 cost regimes (optimistic/base/stressed), runs the
honest maker-fill backtest, and judges the BASE regime through the same gates that
rejected funding-carry and pairs (DSR / purged-CV / stressed ruin), printing the
RAW / COSTS / EXECUTION / VALIDATION / VERDICT report.

    python scripts/backtest_mr_scalp.py --coin ETH --days 14
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest import purged_kfold
from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.backtest.mr_scalp_backtest import CostModel, backtest_mr_scalp
from treasuryforge.risk.ruin import monte_carlo_ruin
from treasuryforge.signals.mr_scalp import Bar, MrScalpParams

REGIMES = {
    "optimistic": CostModel(maker_fee=0.00010, taker_fee=0.00030, spread=0.00010, slippage=0.00005),
    "base":       CostModel(maker_fee=0.00015, taker_fee=0.00045, spread=0.00030, slippage=0.00020),
    "stressed":   CostModel(maker_fee=0.00040, taker_fee=0.00080, spread=0.00060, slippage=0.00040),
}


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
        return json.loads(r.read().decode())


def fetch_1m(coin: str, days: int, now_ms: int) -> list[Bar]:
    start = now_ms - days * 24 * 60 * 60 * 1000
    bars: list[Bar] = []
    cur = start
    while cur < now_ms:
        rows = _post({"type": "candleSnapshot",
                      "req": {"coin": coin, "interval": "1m", "startTime": cur, "endTime": now_ms}})
        if not rows:
            break
        for r in rows:
            bars.append(Bar(float(r["o"]), float(r["h"]), float(r["l"]),
                            float(r["c"]), float(r["v"]), int(r["t"])))
        nxt = int(rows[-1]["t"]) + 60_000
        if nxt <= cur:
            break
        cur = nxt
        if len(rows) < 5000:
            break
    # de-dup by timestamp (pagination overlap)
    seen, out = set(), []
    for b in bars:
        if b.ts not in seen:
            seen.add(b.ts)
            out.append(b)
    return out


def _fold_sharpes(rets: list[float]) -> list[float]:
    if len(rets) < 10:                      # too few trades to cross-validate meaningfully
        return []
    out = []
    for _train, test in purged_kfold(len(rets), k=5, embargo=2):
        seg = [rets[i] for i in test]
        out.append(sharpe_ratio(seg) if len(seg) >= 2 else 0.0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="ETH")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    now_ms = int(time.time() * 1000)
    bars = fetch_1m(args.coin, args.days, now_ms)
    print(f"fetched {len(bars)} 1m bars of {args.coin} (~{len(bars)/1440:.1f} days)\n")
    params = MrScalpParams()

    results = {name: backtest_mr_scalp(bars, params, cm) for name, cm in REGIMES.items()}

    print("=== COST REGIME SWEEP (net return / trades / win%) ===")
    for name, r in results.items():
        print(f"  {name:11s} net={r.net_return:+.3%}  trades={len(r.trades):4d}  "
              f"win={r.win_rate:.0%}  edge/cost={r.edge_cost_ratio:.2f}")
    print()

    base = results["base"]
    rets = base.returns
    if len(rets) < 2:
        print("STRATEGY: MR_SCALP_ZSCORE_V1\n  too few trades to judge — "
              f"({len(rets)} in base regime). VERDICT: REJECT: COSTS_EAT_EDGE (gate starved it)")
        return

    tpy = max(base.trades_per_day * 365.0, 1.0)
    sr_net = sharpe_ratio(rets, periods_per_year=int(tpy))
    sr_gross = sharpe_ratio([t.gross for t in base.trades], periods_per_year=int(tpy))
    dsr = deflated_sharpe_ratio(rets, n_trials=1)        # a-priori spec -> benefit of the doubt
    folds = _fold_sharpes(rets)
    worst = min(folds) if folds else None
    worst_str = f"{worst:.2f}" if worst is not None else f"n/a (only {len(rets)} trades, <10)"
    stressed = monte_carlo_ruin(rets, leverage=1.0, adverse_shift=abs(base.avg_net) * 0.5,
                                tail_shock_prob=0.02, tail_shock_mult=4.0, paths=2000, seed=7)

    # ---- verdict ----
    if base.avg_net <= 0 or base.edge_cost_ratio < 2.0:
        verdict = "REJECT: COSTS_EAT_EDGE"
    elif len(rets) < 10 or base.trades_per_day < 0.5:
        verdict = "REJECT: INSUFFICIENT_FREQUENCY (can't earn statistical confidence)"
    elif dsr < 0.60 or (worst is not None and worst < -1.0) or stressed.p_ruin > 0.10:
        verdict = "REJECT: EDGE_IS_NOT_RELIABLE"
    elif base.filled_losers / max(len(base.trades), 1) > 0.6 and base.missed_rebound_rate > 0.4:
        verdict = "REJECT: ADVERSE_SELECTION"
    else:
        verdict = "CONTINUE_SHADOW"

    print(f"""STRATEGY: MR_SCALP_ZSCORE_V1   (base regime, {args.coin}, {len(bars)/1440:.1f}d)

RAW
  gross Sharpe (ann): {sr_gross:.2f}
  net Sharpe (ann)  : {sr_net:.2f}
  avg trade gross   : {base.avg_gross:+.4%}
  avg trade net     : {base.avg_net:+.4%}
  win rate          : {base.win_rate:.0%}
  trades/day        : {base.trades_per_day:.2f}
  avg hold (bars)   : {base.avg_hold:.1f}

COSTS
  cost/trade        : {base.cost_per_trade:.4%}
  gross-edge/cost   : {base.edge_cost_ratio:.2f}   (need > 2)

EXECUTION (adverse selection)
  maker fill rate   : {base.maker_fill_rate:.0%}   (filled {base.n_filled}/{base.n_placed})
  missed rebound rate: {base.missed_rebound_rate:.0%}   (missed winners {base.missed_winners}/{base.n_missed})
  post-fill drift   : {base.post_fill_drift:+.4%}   (negative = adverse)
  filled losers     : {base.filled_losers}/{len(base.trades)}

VALIDATION
  DSR (n_trials=1)  : {dsr:.3f}   (gate >= 0.60)
  purged-CV worst   : {worst_str}
  stressed ruin     : {stressed.p_ruin:.1%}
  expected maxDD    : {stressed.expected_max_drawdown:.1%}

VERDICT
  {verdict}""")


if __name__ == "__main__":
    main()
