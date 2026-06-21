"""Run the Bitso validation ladder.

    # exhaustive local run — zero risk, full ladder against the emulator:
    python scripts/validate_live.py --mode paper --arm

    # live read-only (rungs 1-4), FROM THE VPS only (IP-allowlisted key):
    python scripts/validate_live.py --mode live

    # live, place ONE tiny ~20 MXN order (rungs 5-6) — only after read-only is green:
    python scripts/validate_live.py --mode live --arm --max-mxn 20

`paper` uses the in-process MockBitsoAPI (no network, no funds). `live` reads the
key from the environment (VPS) or the OS keychain (Windows) and hits api.bitso.com.
Read-only by default; order rungs require --arm.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

sys.path.insert(0, ".")

from treasuryforge.exchanges.bitso.client import BitsoClient
from treasuryforge.exchanges.bitso.executor import BitsoExecutor
from treasuryforge.exchanges.bitso.mock import MockBitsoAPI
from treasuryforge.exchanges.bitso.signer import BitsoSigner, NonceV2
from treasuryforge.exchanges.bitso.transport import make_http_transport
from treasuryforge.exchanges.bitso.validation import FAIL, run_ladder


def _real_nonce() -> NonceV2:
    return NonceV2(now_ms=lambda: int(time.time() * 1000),
                   salt=lambda: random.randint(0, 999_999))


def build(mode: str, symbol: str, book: str):
    book_map = {symbol: book}
    if mode == "paper":
        api = MockBitsoAPI()
        signer = BitsoSigner("paper-key", "paper-secret", _real_nonce())
        transport = api
    else:
        from treasuryforge.exchanges.bitso.secrets import resolve_credentials
        api_key, api_secret = resolve_credentials()
        signer = BitsoSigner(api_key, api_secret, _real_nonce())
        transport = make_http_transport()
    client = BitsoClient(signer, transport)
    executor = BitsoExecutor(signer, transport, book_map=book_map)
    return client, executor


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["paper", "live"], default="paper")
    ap.add_argument("--arm", action="store_true", help="enable order-placing rungs 5-6")
    ap.add_argument("--max-mxn", type=float, default=20.0)
    ap.add_argument("--symbol", default="BTC")
    ap.add_argument("--book", default="btc_mxn")
    args = ap.parse_args()

    if args.mode == "live" and args.arm:
        print("LIVE + ARMED: this will place a real order with real money.")
        print(f"Asset={args.book}  max spend={args.max_mxn} MXN.\n")

    client, executor = build(args.mode, args.symbol, args.book)
    results = run_ladder(client, executor, symbol=args.symbol, book=args.book,
                         arm=args.arm, max_mxn=args.max_mxn)

    print(f"=== Bitso validation ladder ({args.mode}, armed={args.arm}) ===")
    worst_ok = True
    for r in results:
        print(f"[{r.status:^4}] {r.name:<18} {r.detail}")
        if r.status == FAIL:
            worst_ok = False
    print("\nRESULT:", "ALL GREEN — proceed to the next gate" if worst_ok
          else "HALTED on a FAIL — do NOT advance")
    sys.exit(0 if worst_ok else 1)


if __name__ == "__main__":
    main()
