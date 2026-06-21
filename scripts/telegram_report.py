"""Telegram status push -- the system reports to YOU; you never run a command to check it.

Reads the durable ledgers (read-only, places no orders) and pushes ONE concise digest to
Telegram: armed coins, the coin CLOSEST to the deployment gate (deflated DSR), whether
anything deployed, relay freshness, and how many real orders have fired. Run on a systemd
timer so it arrives on its own.

    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python scripts/telegram_report.py

Token + chat id come from the env (put them in /etc/treasuryforge/telegram.env, NEVER in the
repo). Stdlib only.
"""

from __future__ import annotations

import glob
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

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


def _scalp_board(state_dir: str = "state") -> list[tuple[float, str, int, float, bool]]:
    """Per-coin (deflated DSR, coin, trades, days, deploy), best first -- the deflated DSR is
    the bar the live loop actually applies (discounted for the whole scanned universe)."""
    gate = DeploymentGate()
    recs: dict[str, tuple[list[float], list[int]]] = {}
    for d in sorted(glob.glob(os.path.join(state_dir, "scalp_*"))):
        if not os.path.isdir(d):
            continue
        evs = [e for e in Journal(d).read_ledger() if e.get("kind") == "scalp"]
        rs = [float(e["r"]) for e in evs]
        ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]
        if rs:
            recs[os.path.basename(d).replace("scalp_", "").upper()] = (rs, ts)
    trials = [s for rs, _ in recs.values() if (s := _interval_sharpe(rs)) is not None]
    rows = [(gate.evaluate(rs, ts, trial_sharpes=trials).dsr, coin, len(rs),
             gate.evaluate(rs, ts).days, gate.evaluate(rs, ts, trial_sharpes=trials).deploy)
            for coin, (rs, ts) in recs.items()]
    rows.sort(reverse=True)
    return rows


def build_digest(state_dir: str = "state") -> str:
    rows = _scalp_board(state_dir)
    lines = ["TreasuryForge"]
    if not rows:
        lines.append("scalp: sin track record todavia")
    else:
        deployed = [r for r in rows if r[4]]
        best = rows[0]
        lines.append(f"coins: {len(rows)} | desplegadas: {len(deployed)}")
        lines.append(f"mas cerca: {best[1]}  DSR {best[0]:.3f}  ({best[2]} trades / {best[3]:.1f}d)")
        lines.append("gate: DSR>=0.60 + >=30 trades + >=14d")
        if not deployed:
            lines.append("-> nada cruza el gate: HOLD, $0 en riesgo")

    relay = os.path.join(state_dir, "relay", "funding.json")
    if os.path.exists(relay):
        age = int(time.time() - os.path.getmtime(relay))
        lines.append(f"relay: {age}s ({'OK' if age <= 900 else 'VIEJO'})")

    live_dir = os.path.join(state_dir, "hl_live")
    n_orders = len(Journal(live_dir).read_ledger()) if os.path.isdir(live_dir) else 0
    lines.append(f"ordenes reales: {n_orders}")
    return "\n".join(lines)


def send(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        print("FAIL: set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID", flush=True)
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return bool(json.loads(r.read().decode()).get("ok", False))


def main() -> None:
    ok = send(build_digest())
    print("sent" if ok else "send failed", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
