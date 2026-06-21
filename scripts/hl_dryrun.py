"""Hyperliquid execution DRY-RUN gate -- the first gate before any real order.

Keyless and side-effect-free: it pulls live /info, runs the fail-closed preflight
(paper mode), builds the EXACT L1 order payload that would be signed + POSTed, and
validates it against the venue $10 floor and your safety cap. It signs NOTHING and
sends NOTHING -- signing needs the agent key, which lives only on the VPS (Phase 2).

    python scripts/hl_dryrun.py --coin ETH --usd 11 --side buy --cap 15

Run this from the PC to prove the construction path end-to-end with zero risk.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.exchanges.hyperliquid import HyperliquidExecutor, HyperliquidInfo
from treasuryforge.policy import PolicyConfig
from treasuryforge.preflight import PreflightInputs, run_preflight
from treasuryforge.types import Intent, Side

MASTER = "0xbe79f330a1575f341D2c1a66Fd3909761111e431"   # info/queries + holds the funds


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="ETH")
    ap.add_argument("--usd", type=float, default=11.0, help="notional in USDC (>= $10 floor)")
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    ap.add_argument("--cap", type=float, default=15.0, help="your per-tx safety cap (USD)")
    ap.add_argument("--master", default=MASTER)
    args = ap.parse_args()

    info = HyperliquidInfo(_post)

    print("=== ACCOUNT STATE (keyless read of the master address) ===")
    ms = info.margin_summary(args.master)
    spot_usdc = info.spot_balance(args.master, "USDC")
    collateral = info.available_collateral(args.master)
    print(f"  {args.master}")
    print(f"  perp account_value ${ms['account_value']:.2f}  +  spot USDC ${spot_usdc:.2f}"
          f"  =  UNIFIED collateral ${collateral:.2f}")
    positions = info.open_positions(args.master)
    print(f"  open positions: {positions if positions else 'none'}")

    mid = info.all_mids()[args.coin]
    fm = info.funding_and_marks().get(args.coin, {})
    print(f"\n  {args.coin} mid ${mid:.4f}  funding/hr {fm.get('funding', 0.0):+.6%}"
          f"  ({fm.get('funding', 0.0) * 24 * 365:+.2%} APR)")

    # 1) fail-closed preflight (paper mode -- this is a dry-run, no live gates) -----
    cfg = PolicyConfig(allowed_symbols=frozenset({args.coin}), max_notional_per_tx=args.cap,
                       max_tx_per_window=3, window_steps=3600, max_drawdown_pct=0.20,
                       min_notional_per_tx=10.0)
    report = run_preflight(PreflightInputs(
        mode="paper", config=cfg, journal_dir="state/hl_dryrun",
        has_credentials=False, now_wall=time.time(), data_age_s=0.5))
    print("\n=== PREFLIGHT (paper) ===")
    print(report.render())

    # 2) the dry-run order gate -- builds the exact payload, signs/sends nothing -----
    side = Side.BUY if args.side == "buy" else Side.SELL
    intent = Intent(args.coin, side, 0.0, quote_amount=args.usd, reason="dry-run rail test")
    ex = HyperliquidExecutor(exchange=None, info=info, max_notional_usd=args.cap)
    preview = ex.preview_order(intent, price=mid)

    print("\n=== DRY-RUN ORDER GATE ===")
    print(preview.render())
    if preview.action is not None:
        print("\n  EXACT L1 PAYLOAD that would be signed (agent key, VPS) + POSTed to /exchange:")
        print("  " + json.dumps(preview.action))

    print("\n" + "=" * 64)
    ready = report.ready and preview.ok
    print(f"VERDICT: {'GATE PASSED' if ready else 'GATE FAILED'} -- nothing was signed, "
          f"nothing was sent.")
    print("Next (VPS only): sign-WITHOUT-send check using HL_AGENT_KEY, then a"
          " centavos live order with reconcile. The agent key never touches this PC"
          " or the chat.")


if __name__ == "__main__":
    main()
