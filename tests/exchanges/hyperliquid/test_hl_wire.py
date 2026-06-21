"""Hyperliquid L1 wire format — SDK-faithful size/price rounding + action payload.
A wrong format here = a rejected or mis-sized live order, so the rules are pinned."""

from __future__ import annotations

import pytest

from treasuryforge.exchanges.hyperliquid.wire import (
    build_order_action,
    float_to_wire,
    round_price,
    round_size,
)


def test_float_to_wire_normalizes_and_strips():
    assert float_to_wire(3570.0) == "3570"        # integer -> no decimals
    assert float_to_wire(3570.50) == "3570.5"     # trailing zero stripped
    assert float_to_wire(0.001) == "0.001"        # no float-repr garbage (decimal)


def test_float_to_wire_rejects_lossy():
    with pytest.raises(ValueError):
        float_to_wire(0.123456789)                # needs >8dp -> not representable


def test_round_size_to_sz_decimals():
    assert round_size(0.123456, 4) == 0.1235
    assert round_size(0.00012, 3) == 0.0          # rounds away below the size grid


def test_round_price_5_sigfigs_then_decimals():
    assert round_price(3570.123, 4) == 3570.1     # ETH-like: szDec 4 -> max 2 dp, 5 sig figs
    assert round_price(1234.567, 4) == 1234.6
    assert round_price(65432.1, 5) == 65432.0     # BTC-like: szDec 5 -> max 1 dp


def test_round_price_rejects_nonpositive():
    with pytest.raises(ValueError):
        round_price(0.0, 4)


def test_build_order_action_exact_structure():
    a = build_order_action(1, True, 3570.5, 0.0031, 4, tif="Ioc")
    assert a["type"] == "order" and a["grouping"] == "na"
    o = a["orders"][0]
    assert o["a"] == 1 and o["b"] is True and o["r"] is False
    assert o["t"] == {"limit": {"tif": "Ioc"}}
    assert o["p"] == "3570.5" and o["s"] == "0.0031"


def test_build_order_action_reduce_only_and_sell():
    o = build_order_action(0, False, 65000.0, 0.001, 5, tif="Gtc", reduce_only=True)["orders"][0]
    assert o["b"] is False and o["r"] is True and o["t"]["limit"]["tif"] == "Gtc"


def test_build_rejects_bad_tif():
    with pytest.raises(ValueError):
        build_order_action(0, True, 100.0, 1.0, 2, tif="XXX")


def test_build_rejects_size_that_rounds_to_zero():
    with pytest.raises(ValueError):
        build_order_action(0, True, 100.0, 0.0001, 2)     # 0.0001 -> 0.0 at 2 dp
