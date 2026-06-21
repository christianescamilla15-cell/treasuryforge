"""The policy engine is the safety boundary: every hard rule must provably fire."""

from __future__ import annotations

from treasuryforge import (
    Intent,
    MarketTick,
    PolicyConfig,
    PolicyEngine,
    Side,
    SimWallet,
)


def cfg(**over) -> PolicyConfig:
    base = dict(
        allowed_symbols=frozenset({"TOKEN"}),
        max_notional_per_tx=500.0,
        max_tx_per_window=3,
        window_steps=10,
        max_drawdown_pct=0.15,
        fee_rate=0.001,
    )
    base.update(over)
    return PolicyConfig(**base)


def tick(price=100.0, ts=0):
    return MarketTick("TOKEN", price, ts)


def buy(amount=1.0):
    return Intent("TOKEN", Side.BUY, amount)


def test_allows_a_normal_trade():
    eng = PolicyEngine(cfg())
    assert eng.evaluate(buy(1.0), tick(), SimWallet(10_000)).allowed


def test_kill_switch_denies_everything():
    eng = PolicyEngine(cfg(kill_switch=True))
    v = eng.evaluate(buy(1.0), tick(), SimWallet(10_000))
    assert not v.allowed and "kill_switch" in v.reason


def test_symbol_allowlist():
    eng = PolicyEngine(cfg())
    v = eng.evaluate(Intent("SCAM", Side.BUY, 1.0), tick(), SimWallet(10_000))
    assert not v.allowed and "allowlist" in v.reason


def test_per_tx_notional_cap():
    eng = PolicyEngine(cfg(max_notional_per_tx=500.0))
    # 6 units * 100 = 600 > 500 cap
    v = eng.evaluate(buy(6.0), tick(price=100.0), SimWallet(10_000))
    assert not v.allowed and "notional" in v.reason


def test_rate_limit_blocks_after_n_in_window():
    eng = PolicyEngine(cfg(max_tx_per_window=3, window_steps=10))
    w = SimWallet(10_000)
    for ts in range(3):
        assert eng.evaluate(buy(1.0), tick(ts=ts), w).allowed
        eng.register_fill(ts)
    v = eng.evaluate(buy(1.0), tick(ts=3), w)
    assert not v.allowed and "rate_limit" in v.reason


def test_rate_limit_recovers_after_window_passes():
    eng = PolicyEngine(cfg(max_tx_per_window=1, window_steps=5))
    w = SimWallet(10_000)
    assert eng.evaluate(buy(1.0), tick(ts=0), w).allowed
    eng.register_fill(0)
    assert not eng.evaluate(buy(1.0), tick(ts=1), w).allowed
    # ts=6 is outside the 5-step window from ts=0
    assert eng.evaluate(buy(1.0), tick(ts=6), w).allowed


def test_circuit_breaker_trips_and_stays_tripped():
    eng = PolicyEngine(cfg(max_drawdown_pct=0.10))
    w = SimWallet(quote=0.0, positions={"TOKEN": 100.0})
    # starting equity recorded at price 100 -> 10_000
    assert eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=100.0, ts=0), w).allowed
    # price collapses to 80 -> equity 8_000, below the 9_000 floor
    v = eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=80.0, ts=1), w)
    assert not v.allowed and "circuit_breaker" in v.reason
    assert eng.tripped
    # stays tripped even if price recovers
    v2 = eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=120.0, ts=2), w)
    assert not v2.allowed and eng.tripped


def test_solvency_buy_needs_quote():
    eng = PolicyEngine(cfg())
    v = eng.evaluate(buy(1.0), tick(price=100.0), SimWallet(quote=50.0))
    assert not v.allowed and "insufficient_quote" in v.reason


def test_solvency_sell_needs_base():
    eng = PolicyEngine(cfg())
    v = eng.evaluate(Intent("TOKEN", Side.SELL, 5.0), tick(), SimWallet(quote=10_000))
    assert not v.allowed and "insufficient_base" in v.reason
