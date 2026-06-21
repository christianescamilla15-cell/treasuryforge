"""Mark an ignition as a PICK -- Christian's discretionary call, BEFORE the outcome is known.

Tags the most recent OPEN ignition for a coin as picked. Honest only if run while the
ignition is still open (pre-resolution); marking after the fact would be hindsight, which
the resolver/scorer treat as invalid by design (a pick event after 'resolved' still folds,
so DO NOT mark resolved ones -- the tool warns you).

    python scripts/mark_pick.py DEGEN
    python scripts/mark_pick.py --list          # show currently-open ignitions to pick from
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

from ignition_detector import _state

from treasuryforge.journal import Journal


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("coin", nargs="?", default="", help="coin to pick (e.g. DEGEN)")
    ap.add_argument("--list", action="store_true", help="list open ignitions")
    args = ap.parse_args()
    journal = Journal("state/ignitions")
    st = _state(journal)

    if args.list or not args.coin:
        opens = [(i, r) for i, r in st.items() if r["status"] == "open"]
        opens.sort(key=lambda x: x[1]["ts"], reverse=True)
        print(f"open ignitions ({len(opens)}):", flush=True)
        for i, r in opens[:40]:
            mark = " [PICKED]" if r["picked"] else ""
            age_h = (int(time.time()) - r["ts"]) / 3600
            print(f"  {r['coin']:12} +{r['signal_ret']:.0%}  {age_h:4.0f}h ago{mark}  ({i})",
                  flush=True)
        return

    coin = args.coin.upper()

    def _match(r):
        return r["coin"] == coin or r["coin"].split("-")[0] == coin

    cands = [(i, r) for i, r in st.items() if _match(r) and r["status"] == "open"]
    if not cands:
        resolved = [i for i, r in st.items() if _match(r) and r["status"] == "resolved"]
        if resolved:
            print(f"! {coin} has only RESOLVED ignitions -- too late to pick (would be hindsight)",
                  file=sys.stderr)
        else:
            print(f"! no open ignition for {coin}", file=sys.stderr)
        sys.exit(1)
    cands.sort(key=lambda x: x[1]["ts"], reverse=True)
    _id = cands[0][0]
    if cands[0][1]["picked"]:
        print(f"{coin} ({_id}) already picked.")
        return
    journal.append_event({"kind": "pick", "id": _id, "ts": int(time.time())})
    print(f"PICKED {coin}  ({_id}) -- entry {cands[0][1]['entry']:.6g}, "
          f"signal +{cands[0][1]['signal_ret']:.0%}", flush=True)


if __name__ == "__main__":
    main()
