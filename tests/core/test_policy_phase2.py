"""Phase-2 additions to the policy engine: spend budget, staleness, frozen config,
and snapshot/restore of latched state."""

from __future__ import annotations

import dataclasses

import pytest

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
        max_tx_per_window=100,           # high so it doesn't mask other rules
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


# -- frozen config -----------------------------------------------------------
def test_config_is_immutable():
    c = cfg()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.max_notional_per_tx = 1e9          # the agent must not rewrite its limits


# -- spend budget ------------------------------------------------------------
def test_spend_budget_blocks_drip_drain():
    # count limit is huge; only the VALUE budget should bite
    eng = PolicyEngine(cfg(max_notional_per_window=250.0, spend_window_steps=10))
    w = SimWallet(10_000)
    # two 100-notional buys = 200, still under 250
    for ts in (0, 1):
        assert eng.evaluate(buy(1.0), tick(ts=ts), w).allowed
        eng.register_fill(ts, 100.0)
    # third would push cumulative to 300 > 250 -> blocked despite count budget free
    v = eng.evaluate(buy(1.0), tick(ts=2), w)
    assert not v.allowed and "spend_budget" in v.reason


def test_spend_budget_recovers_after_window():
    eng = PolicyEngine(cfg(max_notional_per_window=100.0, spend_window_steps=5))
    w = SimWallet(10_000)
    assert eng.evaluate(buy(1.0), tick(ts=0), w).allowed
    eng.register_fill(0, 100.0)
    assert not eng.evaluate(buy(1.0), tick(ts=1), w).allowed     # budget spent
    # ts=6 is outside the 5-step spend window from ts=0
    assert eng.evaluate(buy(1.0), tick(ts=6), w).allowed


def test_spend_budget_only_debits_on_fills_not_denials():
    eng = PolicyEngine(cfg(max_notional_per_window=100.0))
    w = SimWallet(10_000)
    # evaluate many times WITHOUT registering fills -> budget never consumed
    for ts in range(5):
        assert eng.evaluate(buy(1.0), tick(ts=ts), w).allowed


# -- min-notional floor (exchange minimum_value) -----------------------------
def test_min_notional_floor_rejects_dust():
    eng = PolicyEngine(cfg(min_notional_per_tx=10.0))
    # 0.05 * 100 = 5.0, below the 10.0 exchange floor
    v = eng.evaluate(buy(0.05), tick(price=100.0), SimWallet(10_000))
    assert not v.allowed and "min_notional" in v.reason


def test_min_notional_floor_allows_at_or_above():
    eng = PolicyEngine(cfg(min_notional_per_tx=10.0))
    assert eng.evaluate(buy(0.1), tick(price=100.0), SimWallet(10_000)).allowed   # exactly 10
    assert eng.evaluate(buy(1.0), tick(price=100.0), SimWallet(10_000)).allowed


# -- staleness gate ----------------------------------------------------------
def test_staleness_inert_without_age_or_budget():
    # budget set but no data_age supplied (the sim case) -> rule is inert
    eng = PolicyEngine(cfg(max_staleness_ns=1_000))
    assert eng.evaluate(buy(1.0), tick(), SimWallet(10_000)).allowed
    # age supplied but no budget -> inert
    eng2 = PolicyEngine(cfg())
    assert eng2.evaluate(buy(1.0), tick(), SimWallet(10_000), data_age_ns=10**12).allowed


def test_staleness_denies_old_data():
    eng = PolicyEngine(cfg(max_staleness_ns=1_000_000))   # 1ms budget
    v = eng.evaluate(buy(1.0), tick(), SimWallet(10_000), data_age_ns=5_000_000)
    assert not v.allowed and "stale_data" in v.reason


def test_staleness_allows_fresh_data():
    eng = PolicyEngine(cfg(max_staleness_ns=1_000_000))
    assert eng.evaluate(buy(1.0), tick(), SimWallet(10_000), data_age_ns=500_000).allowed


# -- snapshot / restore (the crash-safety primitive) -------------------------
def test_snapshot_restore_preserves_tripped_breaker():
    eng = PolicyEngine(cfg(max_drawdown_pct=0.10))
    w = SimWallet(quote=0.0, positions={"TOKEN": 100.0})
    eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=100.0, ts=0), w)  # anchor at 10_000
    eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=80.0, ts=1), w)   # trips
    assert eng.tripped

    snap = eng.snapshot()
    revived = PolicyEngine(cfg(max_drawdown_pct=0.10))
    revived.restore(snap)
    # a restart must NOT un-trip the breaker, even if price recovered
    assert revived.tripped
    v = revived.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=150.0, ts=2), w)
    assert not v.allowed and "circuit_breaker" in v.reason


def test_snapshot_restore_preserves_drawdown_anchor():
    eng = PolicyEngine(cfg(max_drawdown_pct=0.20))
    w = SimWallet(quote=0.0, positions={"TOKEN": 100.0})
    eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=100.0, ts=0), w)  # anchor 10_000
    snap = eng.snapshot()
    assert snap["starting_equity"] == pytest.approx(10_000.0)
    revived = PolicyEngine(cfg(max_drawdown_pct=0.20))
    revived.restore(snap)
    # floor must still be anchored to the ORIGINAL 10_000 (8_000), not re-anchored
    v = revived.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(price=79.0, ts=1), w)
    assert not v.allowed and "circuit_breaker" in v.reason
