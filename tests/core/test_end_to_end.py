"""End-to-end gates: deterministic, conservative, and guardrails actually bite."""

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


def make_runner(prices=None, seed=7, wallet=None, **policy_over):
    symbol = "TOKEN"
    market = (
        MarketSimulator(symbol=symbol, prices=prices)
        if prices is not None
        else MarketSimulator(symbol=symbol, start_price=100.0, seed=seed, volatility=0.02)
    )
    pcfg = dict(
        allowed_symbols=frozenset({symbol}),
        max_notional_per_tx=500.0,
        max_tx_per_window=3,
        window_steps=10,
        max_drawdown_pct=0.15,
        fee_rate=0.001,
    )
    pcfg.update(policy_over)
    return Runner(
        market=market,
        agent=MeanReversionAgent(symbol=symbol, window=20, threshold=0.02, trade_base=2.0),
        policy=PolicyEngine(PolicyConfig(**pcfg)),
        executor=SimExecutor(fee_rate=0.001, slippage_bps=5.0),
        wallet=wallet if wallet is not None else SimWallet(quote=10_000.0),
    )


def test_run_is_deterministic():
    """Same seed -> identical fills and identical final equity (bit-exact gate)."""
    r1 = make_runner(seed=7).run(120)
    r2 = make_runner(seed=7).run(120)
    assert r1.final_equity == r2.final_equity
    assert [f.price for f in r1.fills] == [f.price for f in r2.fills]
    assert [f.side for f in r1.fills] == [f.side for f in r2.fills]


def test_no_value_created_conservation():
    """Final equity must equal initial equity minus exactly the fees + slippage
    paid, marked at the realized prices. We verify it via the wallet identity:
    sum of every fill's quote_delta + base marked-to-market == equity change."""
    runner = make_runner(seed=11)
    start = SimWallet(quote=10_000.0).equity({"TOKEN": 100.0})
    report = runner.run(150)

    quote_from_fills = sum(f.quote_delta for f in report.fills)
    base_held = sum(f.base_delta for f in report.fills)
    last_price = report.ledger[-1].price
    reconstructed = 10_000.0 + quote_from_fills + base_held * last_price

    assert report.final_equity == pytest.approx(reconstructed, abs=1e-6)
    # fees are strictly non-negative -> the system can only bleed, never mint
    assert all(f.fee >= 0 for f in report.fills)
    assert report.initial_equity == pytest.approx(start)


def test_balances_never_go_negative_over_a_full_run():
    runner = make_runner(seed=3)
    report = runner.run(200)
    assert runner.wallet.quote >= 0.0
    assert all(v >= 0.0 for v in runner.wallet.positions.values())
    _ = report


def test_tiny_caps_produce_denials():
    """If the policy is strict, the agent's oversized intents get blocked."""
    runner = make_runner(seed=7, max_notional_per_tx=50.0)  # trade_base 2 @ ~100 = 200 > 50
    report = runner.run(120)
    assert sum(report.denials.values()) > 0
    assert any(k.startswith("DENY:notional") for k in report.denials)


def test_crash_trips_breaker_and_halts_trading():
    # Wallet is HOLDING the asset (equity 10_000 at px 100) when price collapses,
    # so the drawdown actually hits equity and the breaker must fire.
    prices = [100.0] * 20 + [100.0 * (0.97 ** i) for i in range(1, 60)]
    held = SimWallet(quote=0.0, positions={"TOKEN": 100.0})
    runner = make_runner(prices=prices, wallet=held, max_drawdown_pct=0.15)
    report = runner.run(80)
    assert report.breaker_tripped
    # once tripped, no fills happen after the trip point
    trip_ts = next(e.ts for e in report.ledger if "circuit_breaker" in e.detail)
    assert all(f.ts <= trip_ts for f in report.fills)


def test_no_signal_no_trades_means_flat_equity():
    """A market that never deviates enough -> agent holds -> equity unchanged."""
    flat = [100.0] * 60
    runner = make_runner(prices=flat)
    report = runner.run(60)
    assert len(report.fills) == 0
    assert report.final_equity == pytest.approx(report.initial_equity)
