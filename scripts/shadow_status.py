"""Aggregate every shadow track record (funding-carry + basis, all coins) into one
status board. Reads the durable ledgers directly -- the recorded per-interval return
`r` IS the source of truth, so this is exact and parameter-free.

    python scripts/shadow_status.py

Run this any time to see the progress: per coin/strategy the intervals observed, days
live, % in-position, realized funding/convergence, net return, and (once >= 30
intervals) the live Sharpe and Deflated Sharpe converging toward the >= 0.60 gate.
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, ".")

from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.cross_venue_economics import breakeven_spread_apr
from treasuryforge.deployment_gate import DeploymentGate
from treasuryforge.journal import Journal
from treasuryforge.opportunity_duty_cycle import opportunity_duty_cycle
from treasuryforge.pnl_decomposition import decompose

HOURS_PER_YEAR = 24 * 365
# 1-year hold gives the MOST GENEROUS (lowest) breakeven floor (amortised one-time cost
# ~0). If the spread isn't above even this floor often, the edge is dead regardless of how
# long you could hold -- so it's the right necessary-condition floor for the duty cycle.
STEADY_HOLD_HOURS = 24 * 365


def _summary(directory: str, kind: str) -> dict | None:
    evs = [e for e in Journal(directory).read_ledger() if e.get("kind") == kind]
    if not evs:
        return None
    rs = [float(e["r"]) for e in evs]
    bd = decompose(evs)                              # A1: where the PnL actually comes from
    eq = 1.0
    for r in rs:
        eq *= (1.0 + r)
    ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]
    days = (max(ts) - min(ts)) / 86400.0 if len(ts) >= 2 else 0.0
    out = {"coin": os.path.basename(directory).split("_")[-1].upper(),
           "n": len(rs), "held": bd.n_hold, "days": days, "net": eq - 1.0,
           "funding": bd.funding, "convergence": bd.convergence, "fees": bd.costs,
           "cost_to_gross": bd.cost_to_gross, "sharpe": None, "dsr": None}
    if len(rs) >= 30 and any(r != 0 for r in rs):
        out["sharpe"] = sharpe_ratio(rs, periods_per_year=HOURS_PER_YEAR)
        out["dsr"] = deflated_sharpe_ratio(rs, n_trials=1)
    return out


def _board(title: str, prefix: str, kind: str, *, show_conv: bool = False) -> None:
    rows = sorted((s for d in glob.glob(f"{prefix}_*") if os.path.isdir(d)
                   and (s := _summary(d, kind))), key=lambda r: r["net"], reverse=True)
    print(f"\n=== {title} ===")
    if not rows:
        print("  (no track record yet)")
        return
    extra = f"{'conv':>9}" if show_conv else ""
    print(f"  {'coin':5}{'obs':>6}{'held':>6}{'days':>6}{'funding':>10}{extra}"
          f"{'fees':>9}{'net':>9}{'cost/grs':>9}{'Sharpe':>8}{'DSR':>7}")
    for r in rows:
        conv = f"{r['convergence']:>+9.5f}" if show_conv else ""
        sr = f"{r['sharpe']:>8.2f}" if r["sharpe"] is not None else f"{'--':>8}"
        dsr = f"{r['dsr']:>7.3f}" if r["dsr"] is not None else f"{'--':>7}"
        c2g = r["cost_to_gross"]
        c2g_s = f"{'inf':>9}" if c2g == float("inf") else f"{c2g:>8.0%} "
        print(f"  {r['coin']:5}{r['n']:>6}{r['held']:>6}{r['days']:>6.1f}"
              f"{r['funding']:>+10.5f}{conv}{r['fees']:>+9.5f}{r['net']:>+9.4%}{c2g_s}{sr}{dsr}")


def _spread_aprs(directory: str) -> list[float]:
    """The WIDEST-reachable spread-APR series logged to state/multivenue_<coin> across all
    reachable venues (HL/OKX/Gate/Bitget/MEXC/HTX + Binance/Bybit via the relay). Reachable
    by construction -- a venue absent this tick is dropped, so the duty cycle cannot be
    inflated by a pair you cannot actually price (e.g. a stale-relay Binance)."""
    return [float(e["widest_apr"]) for e in Journal(directory).read_ledger()
            if e.get("kind") == "multivenue"]


def _duty_board(prefix: str = "state/multivenue") -> None:
    """The QUEEN question: what fraction of the time is the WIDEST cross-venue spread above
    the honest break-even floor? With more venues the widest pair is both wider AND on more
    of the time. A 50% peak for 4h/month is a mirage; the duty cycle + the longest unbroken
    on-streak (how long you'd actually hold) tell the real story."""
    floor = breakeven_spread_apr(STEADY_HOLD_HOURS)
    print(f"\n=== MULTI-VENUE DUTY CYCLE (8 venues + relay, floor {floor:.1%} APR @ "
          f"{STEADY_HOLD_HOURS // 24}d-hold steady) ===")
    dirs = sorted(d for d in glob.glob(f"{prefix}_*") if os.path.isdir(d))
    rows = [(os.path.basename(d).split("_")[-1].upper(), _spread_aprs(d)) for d in dirs]
    rows = [(c, a) for c, a in rows if a]
    if not rows:
        print("  (no spread log yet)")
        return
    print(f"  {'coin':5}{'obs':>6}{'duty':>7}{'on':>11}{'mean-on':>10}{'max-streak':>12}")
    for coin, aprs in rows:
        dc = opportunity_duty_cycle(aprs, breakeven_apr=floor)
        print(f"  {coin:5}{dc.n:>6}{dc.fraction:>7.0%}{f'{dc.n_on}/{dc.n}':>11}"
              f"{dc.mean_spread_when_on:>+10.1%}{dc.max_consecutive_on:>12}")
    print("  duty = share of intervals above the floor; max-streak = longest unbroken hold.")
    print("  Low duty or short streaks behind a high peak = snapshot mirage, NOT a live edge.")


def _scalp_board(prefix: str = "state/scalp") -> None:
    """The autonomous scalp shadow + the DEPLOYMENT GATE verdict per coin. Each row is a
    coin's completed paper trades; the gate auto-promotes to real micro capital only when
    DSR >= 0.60 AND APR >= 5% over >= 30 trades / >= 14 days. Until every verdict reads
    'no', not one cent of real capital moves -- the autonomy earns the money, never skips it."""
    gate = DeploymentGate()
    dirs = sorted(d for d in glob.glob(f"{prefix}_*") if os.path.isdir(d))
    print("\n=== SCALP SHADOW + DEPLOYMENT GATE (momentum-ignition, paper) ===")
    rows = []
    for d in dirs:
        evs = [e for e in Journal(d).read_ledger() if e.get("kind") == "scalp"]
        if not evs:
            continue
        rs = [float(e["r"]) for e in evs]
        ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]
        rows.append((os.path.basename(d).split("_")[-1].upper(), gate.evaluate(rs, ts)))
    if not rows:
        print("  (no completed paper trades yet -- accumulating; nothing deployable)")
        return
    print(f"  {'coin':6}{'trades':>7}{'days':>6}{'DSR':>7}{'APR':>9}  deploy?")
    for coin, v in sorted(rows, key=lambda x: -x[1].dsr):
        print(f"  {coin:6}{v.n:>7}{v.days:>6.1f}{v.dsr:>7.3f}{v.apr:>+9.1%}  "
              f"{'DEPLOY @1%' if v.deploy else 'no'}")
    print("  real capital deploys ONLY on a green verdict (DSR>=0.60 & APR>=5%, n>=30, >=14d).")


def main() -> None:
    print("SHADOW STATUS BOARD (paper, no funds) -- net is hypothetical, gate = DSR >= 0.60")
    _board("FUNDING-CARRY", "state/shadow", "shadow")
    _board("SPOT-vs-PERP BASIS", "state/basis", "basis", show_conv=True)
    _board("CROSS-VENUE (HL-OKX spread carry)", "state/cross", "shadow")
    _duty_board()
    _scalp_board()
    print("\nNote: DSR '--' = needs >= 30 intervals. A real edge drives DSR toward 0.60+ as"
          " intervals accrue; a mirage stays low or wobbles. Let it run days/weeks.")


if __name__ == "__main__":
    main()
