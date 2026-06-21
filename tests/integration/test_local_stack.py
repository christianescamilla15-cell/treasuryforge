"""LOCAL STACK — the whole system end-to-end against the local emulators.

This is our "LocalStack": MockBitsoAPI (the full Bitso HTTP contract), the
MeanReversion agent loop, and the risk-governance pipeline all run with NO
network, NO funds, in milliseconds — a fraction of the time a real-venue run
takes. One place that proves every layer wires together.
"""

from __future__ import annotations

import pytest

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


def test_layer1_agent_loop_against_market_simulator():
    """MarketSimulator -> Agent -> 8-rule Policy -> SimExecutor -> Wallet."""
    sym = "TOKEN"
    runner = Runner(
        market=MarketSimulator(symbol=sym, start_price=100.0, seed=7, volatility=0.02),
        agent=MeanReversionAgent(symbol=sym, window=20, threshold=0.02, trade_base=2.0),
        policy=PolicyEngine(PolicyConfig(
            allowed_symbols=frozenset({sym}), max_notional_per_tx=500.0,
            max_tx_per_window=3, window_steps=10, max_drawdown_pct=0.15, fee_rate=0.001)),
        executor=SimExecutor(fee_rate=0.001, slippage_bps=5.0),
        wallet=SimWallet(quote=10_000.0),
    )
    report = runner.run(150)
    assert len(report.ledger) == 150
    assert report.final_equity > 0
    # money conservation: equity reconstructs exactly from the fills
    base = sum(f.base_delta for f in report.fills)
    quote = 10_000.0 + sum(f.quote_delta for f in report.fills)
    assert report.final_equity == pytest.approx(quote + base * report.ledger[-1].price)


def test_layer2_full_bitso_http_contract_against_emulator():
    """books -> signed balance -> no-withdraw proof -> kill-path -> tiny order -> reconcile,
    all against the in-process Bitso emulator (zero network)."""
    api = MockBitsoAPI()
    signer = BitsoSigner("k", "s", NonceV2(now_ms=lambda: 1, salt=lambda: 0))
    client = BitsoClient(signer, api)
    ex = BitsoExecutor(signer, api, book_map={"BTC": "btc_mxn"})
    results = run_ladder(client, ex, symbol="BTC", book="btc_mxn", arm=True, max_mxn=20.0)
    assert all(r.status != FAIL for r in results)
    fill = next(r for r in results if r.name == "6-tiny_order")
    assert fill.data["fee_currency"] == "base"      # the real Bitso BUY-fee quirk


def test_layer3_risk_governance_pipeline():
    """measure -> validate(DSR) -> size -> survive -> named verdict, on synthetic returns."""
    returns = [0.0006 + (0.004 if i % 2 else -0.004) for i in range(300)]
    report = assess_and_report("synthetic", returns, dsr=0.43, dsr_min=0.60, paths=1500)
    assert report.verdict == "REJECT: EDGE_IS_NOT_RELIABLE"   # low DSR -> not deployable


def test_local_stack_is_fast():
    """The whole point: the emulated stack runs in well under a second."""
    import time
    t0 = time.perf_counter()
    api = MockBitsoAPI()
    signer = BitsoSigner("k", "s", NonceV2(now_ms=lambda: 1, salt=lambda: 0))
    run_ladder(BitsoClient(signer, api), BitsoExecutor(signer, api, book_map={"BTC": "btc_mxn"}),
               symbol="BTC", book="btc_mxn", arm=True, max_mxn=20.0)
    assert (time.perf_counter() - t0) < 1.0
