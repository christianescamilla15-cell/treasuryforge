"""Point-in-time / fill-at-t+1: the agent cannot trade on the bar it just saw."""

from __future__ import annotations

import pytest

from treasuryforge import (
    MarketSimulator,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
)
from treasuryforge.types import Intent, MarketTick, Side


class BuyOnceAt:
    """A deliberate look-ahead 'cheater': it buys at a tick whose price it can
    see. Under correct point-in-time execution it must fill at the NEXT price,
    never the price it observed."""

    def __init__(self, at_ts: int):
        self.at_ts = at_ts

    def decide(self, tick: MarketTick, wallet: SimWallet):
        if tick.ts == self.at_ts and wallet.base_balance("TOKEN") == 0:
            return Intent("TOKEN", Side.BUY, 1.0)
        return None


def _runner(execution_delay: int):
    sym = "TOKEN"
    prices = [100.0, 100.0, 200.0, 200.0, 200.0]      # jump right after the signal bar
    return Runner(
        market=MarketSimulator(symbol=sym, prices=prices),
        agent=BuyOnceAt(at_ts=1),
        policy=PolicyEngine(PolicyConfig(
            allowed_symbols=frozenset({sym}), max_notional_per_tx=1e9,
            max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.99)),
        executor=SimExecutor(fee_rate=0.0, slippage_bps=0.0),
        wallet=SimWallet(quote=10_000.0),
        execution_delay=execution_delay,
    )


def test_t_plus_1_fills_at_next_price_not_signal_price():
    report = _runner(execution_delay=1).run(5)
    assert len(report.fills) == 1
    # decided at ts=1 (price 100) but filled at ts=2 (price 200) — no same-bar trade
    assert report.fills[0].price == pytest.approx(200.0)
    assert report.fills[0].ts == 2


def test_opt_out_delay_zero_fills_at_signal_price():
    report = _runner(execution_delay=0).run(5)
    assert len(report.fills) == 1
    assert report.fills[0].price == pytest.approx(100.0)     # same-bar (the bug, opt-in only)
    assert report.fills[0].ts == 1


def test_default_runner_uses_t_plus_1():
    # the safe default must be delay >= 1
    r = Runner(market=MarketSimulator(prices=[1.0]), agent=BuyOnceAt(0),
               policy=PolicyEngine(PolicyConfig(frozenset({"TOKEN"}), 1e9, 100, 10, 0.99)),
               executor=SimExecutor(), wallet=SimWallet(10_000))
    assert r.execution_delay >= 1
