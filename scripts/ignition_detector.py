"""Live ignition detector + outcome resolver -- the honest forward ledger for the
selection-skill test. Logs EVERY ignition (full universe, no survivorship), lets Christian
mark picks BEFORE outcomes are known (scripts/mark_pick.py), and resolves every ignition by
the SAME mechanical exit so picked and unpicked are judged identically.

Append-only event ledger (state/ignitions/ledger.jsonl), replayed to reconstruct state:
  {"kind":"ignition","id","ts","coin","entry","signal_ret"}   detection
  {"kind":"pick","id","ts"}                                    user marked a pick
  {"kind":"resolved","id","ts","realized_return"}             outcome booked

    python scripts/ignition_detector.py --loop 900        # poll every 15 min (forward run)
    python scripts/ignition_detector.py                   # one detect+resolve pass
Read-only research, no keys, no orders.
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

from _coinbase import path_since, recent_1h, usd_products

from treasuryforge.journal import Journal
from treasuryforge.signals.momentum import MomentumParams, simulate_exit

MAJORS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "BCH", "USDT",
          "USDC", "DAI", "EUR", "GBP", "DOT", "MATIC", "UNI", "ATOM", "ETC", "XLM"}


def _state(journal: Journal) -> dict[str, dict]:
    """Replay the ledger into {id: record}."""
    st: dict[str, dict] = {}
    for ev in journal.read_ledger():
        k, _id = ev.get("kind"), ev.get("id")
        if k == "ignition":
            st[_id] = {"coin": ev["coin"], "ts": ev["ts"], "entry": ev["entry"],
                       "signal_ret": ev["signal_ret"], "picked": False, "status": "open",
                       "realized": None}
        elif k == "pick" and _id in st:
            st[_id]["picked"] = True
        elif k == "resolved" and _id in st:
            st[_id]["status"] = "resolved"
            st[_id]["realized"] = ev["realized_return"]
    return st


def detect(journal: Journal, st: dict, coins: list[str], p: MomentumParams,
           cooldown_h: int) -> int:
    now = int(time.time())
    open_or_recent = {r["coin"]: r["ts"] for r in st.values()
                      if r["status"] == "open" or now - r["ts"] < cooldown_h * 3600}
    found = 0
    for coin in coins:
        if coin in open_or_recent:
            continue
        bars = recent_1h(coin, 4)
        if len(bars) < 3:
            continue
        last = bars[-2][3] / bars[-3][3] - 1.0 if bars[-3][3] > 0 else 0.0   # last completed 1h
        if last >= p.enter_1m:
            _id = f"{coin}-{now}"
            journal.append_event({"kind": "ignition", "id": _id, "ts": now, "coin": coin,
                                  "entry": bars[-2][3], "signal_ret": last})
            st[_id] = {"coin": coin, "ts": now, "entry": bars[-2][3], "signal_ret": last,
                       "picked": False, "status": "open", "realized": None}
            found += 1
            print(f"  IGNITION {coin:12} +{last:.1%} @ {bars[-2][3]:.6g}  (id {_id})", flush=True)
    return found


def resolve(journal: Journal, st: dict, p: MomentumParams, resolve_h: int) -> int:
    now = int(time.time())
    done = 0
    for _id, r in list(st.items()):
        if r["status"] != "open" or now - r["ts"] < resolve_h * 3600:
            continue
        path = path_since(r["coin"], r["ts"])
        if len(path) < 2:
            continue
        highs = [b[1] for b in path]
        lows = [b[2] for b in path]
        closes = [b[3] for b in path]
        _, gross = simulate_exit(r["entry"], highs, lows, closes, p)
        realized = gross - p.cost
        journal.append_event({"kind": "resolved", "id": _id, "ts": now,
                              "realized_return": realized})
        r["status"] = "resolved"
        r["realized"] = realized
        done += 1
        tag = "PICKED" if r["picked"] else "      "
        print(f"  RESOLVED {r['coin']:12} {tag} -> {realized:+.1%}  (id {_id})", flush=True)
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enter", type=float, default=0.15)
    ap.add_argument("--trail", type=float, default=0.40)
    ap.add_argument("--stop", type=float, default=0.30)
    ap.add_argument("--cost", type=float, default=0.005)
    ap.add_argument("--resolve-hours", type=int, default=168, help="hold window before booking")
    ap.add_argument("--cooldown-hours", type=int, default=168, help="no re-flag same coin within")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--loop", type=int, default=0, help="seconds between passes (0 = one pass)")
    args = ap.parse_args()
    p = MomentumParams(enter_1m=args.enter, trail_frac=args.trail, stop_frac=args.stop,
                       max_hold=args.resolve_hours, cost=args.cost)
    journal = Journal("state/ignitions")
    coins = [c for c in usd_products() if c.split("-")[0] not in MAJORS][: args.limit]
    print(f"detector: {len(coins)} non-major Coinbase USD coins, enter +{args.enter:.0%}/1h, "
          f"resolve after {args.resolve_hours}h\n", flush=True)
    while True:
        st = _state(journal)
        opens = sum(1 for r in st.values() if r["status"] == "open")
        f = detect(journal, st, coins, p, args.cooldown_hours)
        d = resolve(journal, st, p, args.resolve_hours)
        print(f"[{time.strftime('%m-%d %H:%M')}] +{f} ignitions, {d} resolved, "
              f"{opens + f - d} open", flush=True)
        if args.loop <= 0:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
