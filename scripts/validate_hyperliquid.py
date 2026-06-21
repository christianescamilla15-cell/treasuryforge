"""Hyperliquid live validation ladder. Read-only by default; one tiny ~$12 order
(the venue minimum is $10) behind --arm. Runs with the AGENT (no-withdraw) key.

    # read-only (account + funding), safe:
    python scripts/validate_hyperliquid.py
    # one tiny ~12 USD short + immediate flatten (rungs 4-5):
    python scripts/validate_hyperliquid.py --arm --usd 12 --coin ETH
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.exchanges.hyperliquid import (
    MIN_NOTIONAL_USD,
    HyperliquidExecutor,
    HyperliquidInfo,
)
from treasuryforge.types import Intent, Side


def _post(body):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="store_true")
    ap.add_argument("--usd", type=float, default=12.0)
    ap.add_argument("--coin", default="ETH")
    args = ap.parse_args()

    info = HyperliquidInfo(_post)

    # Rung 1 — keyless market read
    fm = info.funding_and_marks()
    mark = fm[args.coin]["mark"]
    print(f"[PASS] 1-market      {args.coin} mark=${mark}  funding={fm[args.coin]['funding']:+.6%}/hr")

    # Rung 2 — account state (needs the agent address)
    from treasuryforge.exchanges.hyperliquid.secrets import resolve_agent_credentials
    agent_key, account_address = resolve_agent_credentials()
    ms = info.margin_summary(account_address)
    print(f"[PASS] 2-account     value=${ms['account_value']:.2f}  "
          f"withdrawable=${ms['withdrawable']:.2f}")
    if ms["account_value"] < args.usd:
        print(f"[STOP] account value ${ms['account_value']:.2f} < test size ${args.usd} — fund more")
        return

    if not args.arm:
        print("[SKIP] 3-order      (read-only; pass --arm for the tiny live order)")
        return

    # Rung 3 — build the signing Exchange from the AGENT key (never printed)
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    wallet = Account.from_key(agent_key)
    ex = Exchange(wallet, base_url="https://api.hyperliquid.xyz", account_address=account_address)
    execu = HyperliquidExecutor(ex, info, max_notional_usd=args.usd + 1.0)

    # Rung 4 — one tiny SHORT (the carry short leg), gated to ~$12
    sz = round(args.usd / mark, 4)
    print(f"[..]   4-order      placing SHORT {sz} {args.coin} (~${sz*mark:.2f}); min=${MIN_NOTIONAL_USD:.0f}")
    res = execu.place_order(Intent(args.coin, Side.SELL, sz), price=mark)
    print(f"       -> ok={res.ok} filled={res.filled_size} @ ${res.avg_price}")

    # Rung 5 — flatten immediately (close the test position)
    print("[..]   5-flatten    market_close")
    close = ex.market_close(args.coin)
    print(f"       -> {close.get('status') if isinstance(close, dict) else close}")
    print("\nDONE. Check the position is flat in app.hyperliquid.xyz.")


if __name__ == "__main__":
    main()
