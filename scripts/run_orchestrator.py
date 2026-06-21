"""Real-time autonomous ORCHESTRATOR -- the live brain over the broker. It re-evaluates the
deployment gate across every shadow continuously (not hourly), and the moment a strategy
CROSSES the gate it (a) fires a real-time alert and (b) STAGES the deployment as PENDING.
The actual fund move is a one-tap human confirm -- the auto-mode classifier hard-blocks
autonomous real-money POSTs, so the orchestrator decides + stages in real time but never
moves money on its own. It also flags strategies APPROACHING the gate so there is warning,
and heartbeats so silence is never mistaken for death.

    python scripts/run_orchestrator.py --interval 60

Role split (Christian's model): the broker DETECTS + alerts; the orchestrator DECIDES
advancement + (on your OK) moves the funds.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, ".")

from treasuryforge.broker import decide
from treasuryforge.journal import Journal

_SOURCES = [("state/shadow", "shadow", "funding"), ("state/basis", "basis", "basis"),
            ("state/cross", "shadow", "cross"), ("state/scalp", "scalp", "scalp")]
_APPROACH_DSR = 0.40            # warn when a strategy gets within reach of the 0.60 gate


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
            recs[f"{label}:{coin}"] = ([float(e["r"]) for e in evs],
                                       [int(e.get("ts", 0)) for e in evs if e.get("ts")])
    return recs


def _status(decision) -> str:
    if decision.action == "DEPLOY":
        return "DEPLOY"
    return "APPROACH" if decision.verdict.dsr >= _APPROACH_DSR else "HOLD"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    prev: dict[str, str] = {}
    stage = Journal("state/orchestrator")
    last_hb = 0.0
    print(f"ORCHESTRATOR armed: real-time gate watch over all shadows, every {args.interval}s",
          flush=True)

    while True:
        try:
            rep = decide(_load())
            now = time.time()
            for d in rep.decisions:
                st = _status(d)
                if st != prev.get(d.strategy):
                    if st == "DEPLOY":
                        print(f">> DEPLOY {d.strategy} @{d.tier_fraction:.0%}  "
                              f"DSR {d.verdict.dsr:.3f} APR {d.verdict.apr:+.0%} -- "
                              f"PENDING your OK to move funds", flush=True)
                        stage.append_event({"kind": "stage", "ts": int(now), "strategy": d.strategy,
                                            "tier": d.tier_fraction, "dsr": d.verdict.dsr,
                                            "status": "PENDING_OK"})
                    elif st == "APPROACH":
                        print(f">> APPROACH {d.strategy}: DSR {d.verdict.dsr:.3f} (need 0.60), "
                              f"{d.verdict.n} trades / {d.verdict.days:.0f}d", flush=True)
                    prev[d.strategy] = st
            if now - last_hb > 1800:                          # 30-min liveness + progress
                best = rep.decisions[0] if rep.decisions else None
                tag = f"best {best.strategy} DSR {best.verdict.dsr:.3f}" if best else "no data"
                print(f"(heartbeat: {len(rep.decisions)} strategies, {tag}, "
                      f"{rep.n_deployed} deployed)", flush=True)
                last_hb = now
        except Exception as e:
            print(f"(orchestrator error: {str(e)[:70]})", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
