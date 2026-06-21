"""Guarded SCALP execution on Hyperliquid (VPS only) -- the active trader's trigger.

Wraps the PROVEN execution rail (preflight -> preview -> idempotent submit + reconcile)
with the guardrails a leveraged scalp needs: a hard LEVERAGE CAP, the per-tx policy caps,
an explicit max-loss readout, and an automatic reduce-only STOP placed right after the
entry fills. You call the trade; the cockpit sizes it, refuses an insane leverage, and
bounds the damage. Nothing moves without --send (and your explicit OK per real-money POST).

    set -a; source /etc/treasuryforge/hl.env; set +a
    # preview a long: $45 notional on the ~$20 collateral (~2.3x), 0.5% stop
    python scripts/hl_scalp.py --coin ETH --dir long --usd 45 --stop 0.5
    # actually fire it (entry + stop):
    python scripts/hl_scalp.py --coin ETH --dir long --usd 45 --stop 0.5 --send
    # flatten now:
    python scripts/hl_scalp.py --coin ETH --close --send
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

MAX_LEV_HARD = 5.0          # the ruin math: estimation error * leverage = ruin; never above this


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


def _place_stop(exchange, coin: str, entry_is_buy: bool, size: float, stop_px: float) -> dict:
    """Reduce-only STOP-MARKET on the opposite side -- bounds the loss if price runs against
    you. Verified on the FIRST real fire (confirm it appears in the HL UI), per the rail's
    'first real order is the test' discipline."""
    order_type = {"trigger": {"isMarket": True, "triggerPx": stop_px, "tpsl": "sl"}}
    return exchange.order(coin, not entry_is_buy, size, stop_px, order_type, reduce_only=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="ETH")
    ap.add_argument("--dir", default="long", choices=["long", "short"])
    ap.add_argument("--usd", type=float, help="position NOTIONAL in USD (>= $10 HL min)")
    ap.add_argument("--stop", type=float, default=0.5, help="stop-loss distance, percent")
    ap.add_argument("--max-lev", type=float, default=3.0, help="leverage cap (hard ceiling 5x)")
    ap.add_argument("--cap", type=float, default=60.0, help="max notional per tx (policy)")
    ap.add_argument("--close", action="store_true", help="flatten the open position (reduce-only)")
    ap.add_argument("--send", action="store_true", help="ACTUALLY place (else dry-run)")
    args = ap.parse_args()

    key, master = resolve_agent_credentials()
    info = HyperliquidInfo(_post)
    collateral = info.available_collateral(master)
    mid = info.all_mids()[args.coin]
    print(f"master {master}  collateral ${collateral:.2f}  {args.coin} mid ${mid:.4g}")

    # --- CLOSE path (reuse the proven reduce-only flatten) -----------------------
    if args.close:
        pos = next((p for p in info.open_positions(master)
                    if p["coin"] == args.coin and abs(p["size"]) > 0), None)
        if pos is None:
            print(f"no open {args.coin} position.")
            return
        side = Side.SELL if pos["size"] > 0 else Side.BUY
        intent = Intent(args.coin, side, abs(pos["size"]), reason="scalp close")
        if not args.send:
            print(f"DRY-RUN: would flatten {pos['size']} {args.coin} ({side.value} reduce-only).")
            return
        ex = HlTwoPhaseExecutor(_build_exchange(key, master), info, master,
                                max_notional_usd=args.cap, reduce_only=True)
        out = IdempotentOrderManager(ex, Journal("state/hl_live")).submit(
            intent, f"scalp:close:{args.coin}:{int(time.time())}", args.coin)
        print(f"  CLOSE state={out.state.value} filled={out.is_filled} {out.reason}")
        return

    # --- OPEN path: leverage guardrail + sizing + stop ---------------------------
    if not args.usd:
        print("need --usd (position notional).")
        sys.exit(1)
    lev = args.usd / collateral if collateral > 0 else float("inf")
    cap = min(args.max_lev, MAX_LEV_HARD)
    is_buy = args.dir == "long"
    stop_px = mid * (1 - args.stop / 100) if is_buy else mid * (1 + args.stop / 100)
    max_loss = args.usd * args.stop / 100
    print(f"\n=== SCALP {args.dir.upper()} {args.coin} ===")
    print(f"  notional ${args.usd:.2f}  effective leverage {lev:.2f}x (cap {cap:.1f}x)")
    print(f"  stop {args.stop:.2f}% -> trigger ${stop_px:.4g}   MAX LOSS ~${max_loss:.2f}")
    if lev > cap + 1e-9:
        print(f"\nREFUSED: {lev:.2f}x > {cap:.1f}x leverage cap. Lower --usd or raise --max-lev "
              f"(hard ceiling {MAX_LEV_HARD:.0f}x).")
        sys.exit(1)

    server_ms = int(info.user_state(master).get("time", 0))
    skew_s = abs(time.time() - server_ms / 1000.0) if server_ms else None
    cfg = PolicyConfig(allowed_symbols=frozenset({args.coin}), max_notional_per_tx=args.cap,
                       max_tx_per_window=10, window_steps=3600, max_drawdown_pct=0.20,
                       min_notional_per_tx=10.0, max_notional_per_window=args.cap)
    report = run_preflight(PreflightInputs(
        mode="live", config=cfg, journal_dir="state/hl_live", has_credentials=True,
        now_wall=time.time(), exchange_reachable=collateral >= 0, data_age_s=0.5,
        clock_skew_s=skew_s, max_clock_skew_s=5.0))
    if not report.ready:
        print("\n" + report.render() + "\nSAFE_HALTED -- refusing.")
        sys.exit(1)

    side = Side.BUY if is_buy else Side.SELL
    intent = Intent(args.coin, side, 0.0, quote_amount=args.usd, reason=f"scalp {args.dir}")
    preview = HyperliquidExecutor(exchange=None, info=info, max_notional_usd=args.cap).preview_order(
        intent, price=mid)
    print("\n=== ENTRY PREVIEW ===\n" + preview.render())
    if not preview.ok:
        sys.exit(1)

    if not args.send:
        print("\nLIVE DRY-RUN: preflight + leverage cap + preview passed. Nothing sent. "
              "Add --send to fire entry + stop.")
        return

    ex = HlTwoPhaseExecutor(_build_exchange(key, master), info, master, max_notional_usd=args.cap)
    mgr = IdempotentOrderManager(ex, Journal("state/hl_live"))
    origin = f"scalp:open:{args.coin}:{int(time.time())}"
    print(f"\n=== SENDING ENTRY (origin={origin}) ===")
    out = mgr.submit(intent, origin, args.coin)
    print(f"  state={out.state.value} filled={out.is_filled} {out.reason}")
    if out.fill:
        f = out.fill
        print(f"  FILL: {f.base_amount} {args.coin} @ ${f.price:.4g} fee ${f.fee:.4f}")
        try:
            res = _place_stop(_build_exchange(key, master), args.coin, is_buy, f.base_amount, stop_px)
            print(f"  STOP placed @ ${stop_px:.4g} (reduce-only): {json.dumps(res)[:120]}")
        except Exception as e:  # a failed stop must be loud -- you're now unprotected
            print(f"  !! STOP FAILED: {str(e)[:80]} -- SET A STOP MANUALLY IN THE UI NOW")
    print("\nPositions:", info.open_positions(master) or "none")


if __name__ == "__main__":
    main()
