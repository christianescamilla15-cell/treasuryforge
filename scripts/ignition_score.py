"""The selection scorecard -- do Christian's picks beat the mechanical baseline?

Replays the ignition ledger, scores resolved ignitions (picked vs the whole population),
and prints the honest verdict. Until ~20 picks resolve it says NEED MORE DATA -- a few
lucky picks must never read as skill.

    python scripts/ignition_score.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ignition_detector import _state

from treasuryforge.journal import Journal
from treasuryforge.selection_score import Resolved, score


def main() -> None:
    st = _state(Journal("state/ignitions"))
    resolved = [Resolved(r["coin"], r["picked"], r["realized"])
                for r in st.values() if r["status"] == "resolved" and r["realized"] is not None]
    opens = sum(1 for r in st.values() if r["status"] == "open")
    picks_open = sum(1 for r in st.values() if r["status"] == "open" and r["picked"])
    s = score(resolved)

    print("=== IGNITION SELECTION SCORECARD ===\n", flush=True)
    print(f"resolved: {s.n}   (open: {opens}, of which picked: {picks_open})", flush=True)
    print(f"picks resolved: {s.n_picked}   unpicked resolved: {s.n_unpicked}\n", flush=True)
    print(f"EV all ignitions  (the mechanical baseline): {s.ev_all:+.2%}", flush=True)
    print(f"EV YOUR picks                              : {s.ev_picked:+.2%}", flush=True)
    print(f"EV unpicked                                : {s.ev_unpicked:+.2%}", flush=True)
    print(f"\nedge (picks - unpicked): {s.edge_vs_unpicked:+.2%}   z = {s.edge_z:.2f}", flush=True)
    print(f"\nVERDICT: {s.verdict}", flush=True)
    if s.n_picked < 20:
        print("  (keep marking picks; the scorecard needs a real sample before it can speak)",
              flush=True)


if __name__ == "__main__":
    main()
