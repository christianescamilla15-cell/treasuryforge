"""The DRY-RUN gate (preview_order): builds + validates the exact payload, and is
PROVEN never to touch the SDK exchange (constructed with exchange=None so any use
would crash). No key, no funds, no network."""

from __future__ import annotations

import pytest

from treasuryforge import Intent, Side
from treasuryforge.exchanges.hyperliquid import HyperliquidExecutor


class FakeInfo:
    def all_mids(self):
        return {"ETH": 3500.0, "BTC": 65000.0}

    def meta(self):
        return {"universe": [{"name": "BTC", "szDecimals": 5},
                             {"name": "ETH", "szDecimals": 4}]}


def _ex(cap=15.0):
    # exchange=None: the dry-run path must NEVER touch the SDK
    return HyperliquidExecutor(exchange=None, info=FakeInfo(), max_notional_usd=cap)


def test_preview_builds_payload_without_sending():
    p = _ex(15.0).preview_order(Intent("ETH", Side.BUY, 0.0, quote_amount=11.0), price=3500.0)
    assert p.ok and p.action is not None
    o = p.action["orders"][0]
    assert o["a"] == 1 and o["b"] is True                  # ETH index 1, buy
    assert o["t"] == {"limit": {"tif": "Ioc"}}             # market-like -> crossing IOC
    assert float(o["p"]) == pytest.approx(3570.0, abs=1.0)  # mid * (1 + 0.02)


def test_preview_short_leg_crosses_down():
    p = _ex(50.0).preview_order(Intent("ETH", Side.SELL, 0.0, quote_amount=11.0), price=3500.0)
    assert p.ok and p.action["orders"][0]["b"] is False
    assert float(p.action["orders"][0]["p"]) == pytest.approx(3430.0, abs=1.0)  # mid * (1 - 0.02)


def test_preview_below_venue_floor_denied_no_action():
    p = _ex(15.0).preview_order(Intent("ETH", Side.BUY, 0.0, quote_amount=6.0), price=3500.0)
    assert not p.ok and p.action is None and "minimum" in p.reason


def test_preview_over_safety_cap_denied():
    p = _ex(15.0).preview_order(Intent("ETH", Side.BUY, 0.0, quote_amount=20.0), price=3500.0)
    assert not p.ok and p.action is None and "cap" in p.reason


def test_preview_unknown_coin_denied():
    p = _ex(50.0).preview_order(Intent("DOGE", Side.BUY, 0.0, quote_amount=11.0), price=0.2)
    assert not p.ok and "universe" in p.reason


def test_reduce_only_close_skips_min_floor():
    # a $5.40 close is below the $10 OPEN floor but allowed as reduce-only
    p = _ex(15.0).preview_order(Intent("ETH", Side.SELL, 0.003), price=1800.0, reduce_only=True)
    assert p.ok and p.action["orders"][0]["r"] is True


def test_reduce_only_still_enforces_cap():
    p = _ex(15.0).preview_order(Intent("ETH", Side.SELL, 0.02), price=1800.0, reduce_only=True)
    assert not p.ok and "cap" in p.reason          # $36 close still exceeds the $15 cap


def test_preview_render_is_readable():
    p = _ex(15.0).preview_order(Intent("ETH", Side.BUY, 0.0, quote_amount=11.0), price=3500.0)
    text = p.render()
    assert "BUY (long) ETH" in text and "NOT signed, NOT sent" in text
