"""Autonomous broker report -- the capital-allocation brain's current decisions across every
shadow (funding-carry, basis, cross-venue, scalp). Loads each strategy's live paper returns,
runs the deployment gate, and prints DEPLOY / HOLD per strategy plus the portfolio summary.
A DEPLOY decision STAGES a real micro order (it never auto-POSTs -- the rail still needs your
explicit per-trade OK, and the auto-mode classifier enforces that).

    python scripts/run_broker.py

Run it any time, or on a timer. With no proven edge every line reads HOLD and $0 is at risk
-- that is the broker doing its job, not idling.
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, ".")

from treasuryforge.broker import PORTFOLIO_CAP, decide
from treasuryforge.journal import Journal

# (state prefix, ledger 'kind', label) for every shadow the broker allocates over
_SOURCES = [("state/shadow", "shadow", "funding"), ("state/basis", "basis", "basis"),
            ("state/cross", "shadow", "cross"), ("state/scalp", "scalp", "scalp")]


def _load() -> dict[str, tuple[list[float], list[int]]]:
    recs: dict[str, tuple[list[float], list[int]]] = {}
    for prefix, kind, label in _SOURCES:
        for d in sorted(glob.glob(f"{prefix}_*")):
            if not os.path.isdir(d):
                continue
            evs = [e for e in Journal(d).read_ledger() if e.get("kind") == kind]
            if not evs:
                continue
            coin = os.path.basename(d).split("_")[-1].upper()
            rs = [float(e["r"]) for e in evs]
            ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]
            recs[f"{label}:{coin}"] = (rs, ts)
    return recs


def main() -> None:
    recs = _load()
    rep = decide(recs)
    print("=== AUTONOMOUS BROKER -- capital allocation decisions ===")
    print(f"  strategies tracked: {len(recs)}   portfolio cap: {PORTFOLIO_CAP:.0%} of bankroll")
    print(f"  {'strategy':18}{'n':>5}{'days':>6}{'DSR':>7}{'APR':>9}  decision")
    for d in rep.decisions[:25]:
        v = d.verdict
        tag = f"DEPLOY @{d.tier_fraction:.0%}" if d.action == "DEPLOY" else "hold"
        print(f"  {d.strategy:18}{v.n:>5}{v.days:>6.1f}{v.dsr:>7.3f}{v.apr:>+9.1%}  {tag}")
    if len(rep.decisions) > 25:
        print(f"  ... and {len(rep.decisions) - 25} more (all hold)")
    print(f"\n  DEPLOYED: {rep.n_deployed} strategies, {rep.total_deployed:.0%} of bankroll at risk")
    if rep.any_live:
        print("  >> STAGING real micro orders for the DEPLOY lines -- confirm each to POST "
              "(rail needs your explicit OK).")
    else:
        print("  >> $0 at risk: no strategy has cleared the gate. The broker waits -- it cannot "
              "manufacture an edge, and won't gamble one.")


if __name__ == "__main__":
    main()
