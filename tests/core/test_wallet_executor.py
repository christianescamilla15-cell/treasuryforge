"""Wallet + executor: value is never created out of thin air."""

from __future__ import annotations

import pytest

from treasuryforge import Intent, MarketTick, Side, SimExecutor, SimWallet
from treasuryforge.wallet import InsufficientFunds


def test_buy_moves_quote_to_base():
    w = SimWallet(quote=10_000.0)
    ex = SimExecutor(fee_rate=0.001, slippage_bps=0.0)
    fill = ex.execute(Intent("TOKEN", Side.BUY, 2.0), MarketTick("TOKEN", 100.0, 0), w)
    # spent 2*100 + 0.001*200 = 200.2
    assert w.quote == pytest.approx(10_000.0 - 200.2)
    assert w.base_balance("TOKEN") == pytest.approx(2.0)
    assert fill.fee == pytest.approx(0.2)


def test_slippage_is_adverse():
    ex = SimExecutor(fee_rate=0.0, slippage_bps=10.0)  # 0.10%
    buy = ex.execute(Intent("TOKEN", Side.BUY, 1.0), MarketTick("TOKEN", 100.0, 0),
                     SimWallet(10_000))
    sell = ex.execute(Intent("TOKEN", Side.SELL, 1.0), MarketTick("TOKEN", 100.0, 0),
                      SimWallet(0, {"TOKEN": 1.0}))
    assert buy.price > 100.0      # buy fills higher
    assert sell.price < 100.0     # sell fills lower


def test_round_trip_only_loses_fees_and_slippage():
    """Buy then sell at the same mid price: you can only end with LESS quote."""
    w = SimWallet(quote=10_000.0)
    ex = SimExecutor(fee_rate=0.001, slippage_bps=5.0)
    px = MarketTick("TOKEN", 100.0, 0)
    ex.execute(Intent("TOKEN", Side.BUY, 1.0), px, w)
    ex.execute(Intent("TOKEN", Side.SELL, 1.0), px, w)
    assert w.base_balance("TOKEN") == pytest.approx(0.0)
    assert w.quote < 10_000.0                      # never more than we started
    assert w.quote > 9_900.0                       # but only frictional loss


def test_wallet_refuses_to_go_negative():
    w = SimWallet(quote=50.0)
    ex = SimExecutor(fee_rate=0.0, slippage_bps=0.0)
    with pytest.raises(InsufficientFunds):
        ex.execute(Intent("TOKEN", Side.BUY, 10.0), MarketTick("TOKEN", 100.0, 0), w)


def test_equity_is_quote_plus_marked_positions():
    w = SimWallet(quote=1_000.0, positions={"TOKEN": 3.0})
    assert w.equity({"TOKEN": 50.0}) == pytest.approx(1_150.0)
