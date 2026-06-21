"""Hyperliquid LIVE order (Phase 3, VPS only) -- the first real POST, at-most-once.

Drives ONE centavos order through the IdempotentOrderManager: live preflight ->
dry-run preview -> (with --send) sign + POST with a deterministic cloid -> reconcile
the fill by cloid. Idempotent: re-running with the same --origin reconciles instead
of duplicating.

SAFETY: without --send it is a LIVE DRY-RUN -- it builds the signing Exchange, runs
preflight, and previews the exact order, but POSTs NOTHING. --send is the only thing
that moves money, and even then only within the $cap.

    set -a; source /etc/treasuryforge/hl.env; set +a
    # validate everything, send nothing:
    /opt/treasuryforge/.venv/bin/python scripts/hl_live_order.py --usd 11 --cap 15
    # actually place it:
    /opt/treasuryforge/.venv/bin/python scripts/hl_live_order.py --usd 11 --cap 15 --send
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.exchanges.hyperliquid import HyperliquidExecutor, HyperliquidInfo
from treasuryforge.exchanges.hyperliquid.live_executor import HlTwoPhaseExecutor
from treasuryforge.exchanges.hyperliquid.secrets import resolve_agent_credentials
from treasuryforge.journal import Journal
from treasuryforge.orders import IdempotentOrderManager
from treasuryforge.policy import PolicyConfig
from treasuryforge.preflight import PreflightInputs, run_preflight
from treasuryforge.types import Intent, Side


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _build_exchange(key: str, master: str):
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    return Exchange(Account.from_key(key), constants.MAINNET_API_URL, account_address=master)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="ETH")
    ap.add_argument("--usd", type=float, default=11.0)
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    ap.add_argument("--cap", type=float, default=15.0)
    ap.add_argument("--origin", default=None, help="logical order id (stable across retries)")
    ap.add_argument("--close", action="store_true", help="close the open position (reduce-only)")
    ap.add_argument("--send", action="store_true", help="ACTUALLY place the order (else dry-run)")
    args = ap.parse_args()

    key, master = resolve_agent_credentials()
    info = HyperliquidInfo(_post)
    collateral = info.available_collateral(master)
    mid = info.all_mids()[args.coin]
    print(f"master {master}  collateral ${collateral:.2f}  {args.coin} mid ${mid:.2f}")

    # 1) live preflight (fail-closed) ---------------------------------------------
    server_ms = int(info.user_state(master).get("time", 0))
    skew_s = abs(time.time() - server_ms / 1000.0) if server_ms else None
    cfg = PolicyConfig(allowed_symbols=frozenset({args.coin}), max_notional_per_tx=args.cap,
                       max_tx_per_window=3, window_steps=3600, max_drawdown_pct=0.20,
                       min_notional_per_tx=10.0, max_notional_per_window=args.cap)
    report = run_preflight(PreflightInputs(
        mode="live", config=cfg, journal_dir="state/hl_live", has_credentials=True,
        now_wall=time.time(), exchange_reachable=collateral >= 0, data_age_s=0.5,
        clock_skew_s=skew_s, max_clock_skew_s=5.0))
    print("\n=== PREFLIGHT (live) ===")
    print(report.render())
    if not report.ready:
        print("\nSAFE_HALTED -- refusing to trade.")
        sys.exit(1)

    # 2) build the intent — a reduce-only CLOSE (exact position size) or an OPEN ----
    reduce_only = args.close
    if args.close:
        pos = next((p for p in info.open_positions(master)
                    if p["coin"] == args.coin and abs(p["size"]) > 0), None)
        if pos is None:
            print(f"\nno open {args.coin} position to close.")
            return
        close_side = Side.SELL if pos["size"] > 0 else Side.BUY
        intent = Intent(args.coin, close_side, abs(pos["size"]), reason="close position")
        print(f"\nCLOSING {pos['size']} {args.coin} -> {close_side.value} "
              f"{abs(pos['size'])} (reduce-only)")
    else:
        side = Side.BUY if args.side == "buy" else Side.SELL
        intent = Intent(args.coin, side, 0.0, quote_amount=args.usd, reason="phase3 rail test")
    preview = HyperliquidExecutor(exchange=None, info=info, max_notional_usd=args.cap).preview_order(
        intent, price=mid, reduce_only=reduce_only)
    print("\n=== ORDER PREVIEW ===")
    print(preview.render())
    if not preview.ok:
        sys.exit(1)

    if not args.send:
        print("\nLIVE DRY-RUN: exchange built, preflight passed, order previewed. "
              "Nothing sent. Re-run with --send to place it.")
        _build_exchange(key, master)   # prove the signing Exchange constructs
        print("signing Exchange constructed OK (agent key valid).")
        return

    # 3) SEND -- idempotent submit + reconcile ------------------------------------
    kind = "close" if args.close else "open"
    origin = args.origin or f"phase3:{kind}:{args.coin}:{int(time.time())}"
    ex = HlTwoPhaseExecutor(_build_exchange(key, master), info, master,
                            max_notional_usd=args.cap, reduce_only=reduce_only)
    mgr = IdempotentOrderManager(ex, Journal("state/hl_live"))
    print(f"\n=== SENDING (origin={origin}) ===")
    outcome = mgr.submit(intent, origin, args.coin)
    print(f"  state={outcome.state.value}  filled={outcome.is_filled}  reason={outcome.reason}")
    if outcome.fill:
        f = outcome.fill
        print(f"  FILL: {f.base_amount} {args.coin} @ ${f.price:.2f}  fee ${f.fee:.4f}")
    print("\nPositions now:", info.open_positions(master) or "none")


if __name__ == "__main__":
    main()
