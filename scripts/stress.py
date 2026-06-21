"""Pre-prod stress campaign — drive the full stack through N synthetic crash/storm
paths (fidelity level 2) and report how it behaves under prod-like chaos.

    python scripts/stress.py --paths 300
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from treasuryforge import (
    MeanReversionAgent,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
)
from treasuryforge.marketlab import Regime, SyntheticMarket

SYM = "TOKEN"
CRASH_HEAVY = [
    Regime("calm", 0.0, 0.01, 0.85),
    Regime("storm", 0.0, 0.035, 0.85),
    Regime("crash", -0.008, 0.06, 0.82),
]


def run_one(seed: int):
    runner = Runner(
        market=SyntheticMarket(symbol=SYM, start_price=100.0, seed=seed,
                               jump_prob=0.03, regimes=list(CRASH_HEAVY)),
        agent=MeanReversionAgent(symbol=SYM, window=20, threshold=0.02, trade_base=2.0),
        policy=PolicyEngine(PolicyConfig(frozenset({SYM}), 500.0, 5, 10, 0.15, fee_rate=0.001)),
        executor=SimExecutor(fee_rate=0.001, slippage_bps=5.0),
        wallet=SimWallet(quote=0.0, positions={SYM: 100.0}),    # holding through the storm
    )
    report = runner.run(400)
    eq = [e.equity for e in report.ledger]
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak > 0 else 0.0)
    neg = runner.wallet.quote < -1e-9 or any(v < -1e-9 for v in runner.wallet.positions.values())
    return report.breaker_tripped, mdd, neg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=300)
    args = ap.parse_args()

    trips = negatives = 0
    dds = []
    for seed in range(args.paths):
        tripped, mdd, neg = run_one(seed)
        trips += tripped
        negatives += neg
        dds.append(mdd)
    dds.sort()
    n = len(dds)

    print(f"=== STRESS CAMPAIGN: {n} synthetic crash/storm paths (400 steps each) ===\n")
    print(f"  drawdown circuit-breaker tripped:  {trips}/{n} ({trips/n:.0%}) of violent paths")
    print(f"  negative-balance invariant broken: {negatives}/{n}  (must be 0)")
    print(f"  max-drawdown   median: {dds[n//2]:.1%}   p95: {dds[int(n*0.95)]:.1%}   worst: {dds[-1]:.1%}")
    print()
    ok = negatives == 0
    print(">> STRESS PASS — no invariant broken under chaos" if ok
          else ">> STRESS FAIL — an invariant broke")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
