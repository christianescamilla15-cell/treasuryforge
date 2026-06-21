"""Scalp track-record status board -- which coin is CLOSEST to the deployment gate.

Reads the durable scalp ledgers (state/scalp_*) directly; the recorded per-trade return `r`
IS the source of truth, so this is exact and parameter-free. Read-only: places no orders.

    PYTHONPATH=/opt/treasuryforge python scripts/scalp_status.py

For each coin it shows trades, days live, net return, the per-coin DSR (single-trial view of
how strong it looks), and the DEFLATED DSR -- the actual bar the live armed loop applies,
which discounts every coin scanned for multiple testing. The gate needs DSR>=0.60 AND
>=30 trades AND >=14 days; the deflated column is what really decides.
"""

from __future__ import annotations

import glob
import math
import os
import sys

sys.path.insert(0, ".")

from treasuryforge.deployment_gate import DeploymentGate
from treasuryforge.journal import Journal


def _interval_sharpe(rs: list[float]) -> float | None:
    n = len(rs)
    if n < 2:
        return None
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / n
    return mean / math.sqrt(var) if var > 0 else None


def main() -> None:
    gate = DeploymentGate()
    records = {}
    for d in sorted(glob.glob("state/scalp_*")):
        if not os.path.isdir(d):
            continue
        evs = [e for e in Journal(d).read_ledger() if e.get("kind") == "scalp"]
        rs = [float(e["r"]) for e in evs]
        ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]
        if rs:
            records[os.path.basename(d).replace("scalp_", "").upper()] = (rs, ts)

    if not records:
        print("No scalp track records yet (state/scalp_* empty).")
        return

    # the live multiple-testing burden = the Sharpe of every coin currently tracked
    trial_sharpes = [s for rs, _ in records.values() if (s := _interval_sharpe(rs)) is not None]

    rows = []
    for coin, (rs, ts) in records.items():
        raw = gate.evaluate(rs, ts)                                   # single-trial view
        deflated = gate.evaluate(rs, ts, trial_sharpes=trial_sharpes)  # what the loop applies
        net = 1.0
        for r in rs:
            net *= (1.0 + r)
        rows.append((deflated.dsr, raw.dsr, coin, len(rs), raw.days, net - 1.0, deflated.deploy))

    rows.sort(reverse=True)
    print(f"{'coin':<8}{'DSR(defl)':>10}{'DSR(raw)':>10}{'trades':>8}{'days':>7}{'net':>9}  deploy?")
    for dsr_d, dsr_r, coin, n, days, net, dep in rows:
        print(f"{coin:<8}{dsr_d:>10.3f}{dsr_r:>10.3f}{n:>8}{days:>7.1f}{net:>+8.1%}  {dep}")

    best = rows[0]
    print(f"\nClosest: {best[2]} -- deflated DSR {best[0]:.3f} (raw {best[1]:.3f}), "
          f"{best[3]} trades / {best[4]:.1f}d.")
    print(f"Gate needs: DSR>=0.60 AND >=30 trades AND >=14 days. Coins tracked: {len(records)}.")


if __name__ == "__main__":
    main()
