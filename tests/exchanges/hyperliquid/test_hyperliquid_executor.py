"""Hyperliquid executor — offline, fake SDK exchange. No wallet, no funds."""

from __future__ import annotations

import pytest

from treasuryforge import Intent, OrderType, Side
from treasuryforge.exchanges.hyperliquid import HyperliquidExecutor


class FakeExchange:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "status": "ok",
            "response": {"type": "order", "data": {"statuses": [
                {"filled": {"totalSz": "0.001", "avgPx": "65000", "oid": 999}}]}},
        }

    def market_open(self, coin, is_buy, sz, px, slippage, *a, **k):
        self.calls.append(("market_open", coin, is_buy, sz))
        return self.response

    def order(self, coin, is_buy, sz, limit_px, order_type, *a, **k):
        self.calls.append(("order", coin, is_buy, sz, limit_px))
        return self.response


class FakeInfo:
    def all_mids(self):
        return {"BTC": 65000.0, "ETH": 3500.0}


def _ex(max_notional_usd=None, response=None):
    return HyperliquidExecutor(FakeExchange(response), FakeInfo(), max_notional_usd=max_notional_usd)


# -- the 20-MXN vs $10-minimum conflict (the whole point of the guard) -------
def test_order_below_10usd_minimum_is_refused():
    ex = _ex()
    # 0.0001 BTC * 65000 = $6.50, below the $10 Hyperliquid minimum
    intent = Intent("BTC", Side.BUY, 0.0001)
    with pytest.raises(ValueError, match="minimum"):
        ex.place_order(intent, price=65000.0)


def test_cap_below_venue_minimum_is_flagged():
    # a ~20-MXN (~$1.10) cap can NEVER satisfy the $10 floor -> loud error
    ex = _ex(max_notional_usd=1.10)
    intent = Intent("BTC", Side.BUY, 0.0002)         # $13, above min but above cap too
    with pytest.raises(ValueError):
        ex.place_order(intent, price=65000.0)


# -- valid orders ------------------------------------------------------------
def test_valid_market_buy_fills():
    ex = _ex(max_notional_usd=50.0)
    intent = Intent("BTC", Side.BUY, 0.0002)          # $13, ok
    res = ex.place_order(intent, price=65000.0)
    assert res.ok and res.filled_size == pytest.approx(0.001) and res.avg_price == pytest.approx(65000)


def test_short_leg_sets_is_buy_false():
    fake = FakeExchange()
    ex = HyperliquidExecutor(fake, FakeInfo(), max_notional_usd=50.0)
    # the SHORT perp leg of a funding carry
    ex.place_order(Intent("ETH", Side.SELL, 0.01), price=3500.0)
    assert fake.calls[0][0] == "market_open" and fake.calls[0][2] is False


def test_cap_exceeded_refused():
    ex = _ex(max_notional_usd=15.0)
    intent = Intent("BTC", Side.BUY, 0.001)           # $65, over the $15 cap
    with pytest.raises(ValueError, match="cap"):
        ex.place_order(intent, price=65000.0)


def test_quote_amount_converts_to_size():
    fake = FakeExchange()
    ex = HyperliquidExecutor(fake, FakeInfo(), max_notional_usd=50.0)
    ex.place_order(Intent("BTC", Side.BUY, 0.0, quote_amount=13.0), price=65000.0)
    # sz = 13 / 65000
    assert fake.calls[0][3] == pytest.approx(13.0 / 65000.0)


def test_limit_order_routes_to_order():
    fake = FakeExchange()
    ex = HyperliquidExecutor(fake, FakeInfo(), max_notional_usd=50.0)
    ex.place_order(Intent("BTC", Side.SELL, 0.0002, order_type=OrderType.LIMIT, limit_price=66000.0))
    assert fake.calls[0][0] == "order" and fake.calls[0][4] == 66000.0


def test_parse_handles_error_response():
    ex = _ex(max_notional_usd=50.0, response={"status": "err", "response": "insufficient margin"})
    res = ex.place_order(Intent("BTC", Side.BUY, 0.0002), price=65000.0)
    assert not res.ok
