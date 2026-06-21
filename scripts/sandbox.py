"""Local-stack sandbox — run the WHOLE system against the emulators, one command.

    python scripts/sandbox.py

Our "LocalStack": exercise the agent loop, the full Bitso HTTP contract, and the
risk-governance pipeline against in-process emulators — no network, no funds, in
milliseconds. The thorough integration assertions live in
tests/integration/test_local_stack.py (run via `make sandbox`); this is the demo.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from treasuryforge import (
    MarketSimulator,
    MeanReversionAgent,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
)
from treasuryforge.exchanges.bitso import BitsoClient, BitsoExecutor, BitsoSigner, NonceV2
from treasuryforge.exchanges.bitso.mock import MockBitsoAPI
from treasuryforge.exchanges.bitso.validation import FAIL, run_ladder
from treasuryforge.risk import assess_and_report


def main() -> None:
    t0 = time.perf_counter()
    print("=== LOCAL STACK (emulators, no network, no funds) ===\n")

    sym = "TOKEN"
    runner = Runner(
        market=MarketSimulator(symbol=sym, start_price=100.0, seed=7, volatility=0.02),
        agent=MeanReversionAgent(symbol=sym, window=20, threshold=0.02, trade_base=2.0),
        policy=PolicyEngine(PolicyConfig(frozenset({sym}), 500.0, 3, 10, 0.15, fee_rate=0.001)),
        executor=SimExecutor(fee_rate=0.001, slippage_bps=5.0),
        wallet=SimWallet(quote=10_000.0),
    )
    rep = runner.run(150)
    print(f"[1] agent loop      {len(rep.fills)} fills, equity {rep.final_equity:,.2f}, "
          f"breaker={rep.breaker_tripped}")

    api = MockBitsoAPI()
    signer = BitsoSigner("k", "s", NonceV2(now_ms=lambda: 1, salt=lambda: 0))
    ladder = run_ladder(BitsoClient(signer, api),
                        BitsoExecutor(signer, api, book_map={"BTC": "btc_mxn"}),
                        symbol="BTC", book="btc_mxn", arm=True, max_mxn=20.0)
    ok = all(r.status != FAIL for r in ladder)
    print(f"[2] Bitso emulator  ladder {'ALL GREEN' if ok else 'FAILED'} "
          f"({len(ladder)} rungs, full HTTP contract)")

    returns = [0.0006 + (0.004 if i % 2 else -0.004) for i in range(300)]
    report = assess_and_report("synthetic", returns, dsr=0.43, dsr_min=0.60, paths=1500)
    print(f"[3] risk pipeline   verdict: {report.verdict}")

    dt = (time.perf_counter() - t0) * 1000
    print(f"\n>> LOCAL STACK OK in {dt:.0f} ms (a real-venue run is minutes-to-hours)")


if __name__ == "__main__":
    main()
