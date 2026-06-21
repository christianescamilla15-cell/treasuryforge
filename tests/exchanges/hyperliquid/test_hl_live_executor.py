"""Hyperliquid two-phase executor: cloid idempotency, error categorisation, fill
aggregation, and the at-most-once guarantee through the real IdempotentOrderManager.
Offline: fake SDK exchange + fake info, no key, no funds, no network."""

from __future__ import annotations

import pytest

from treasuryforge import Intent, Side
from treasuryforge.exchanges.bitso.errors import (
    FATAL_AUTH,
    INDETERMINATE,
    NON_RETRYABLE,
    BitsoError,
)
from treasuryforge.exchanges.bitso.executor import Unfilled
from treasuryforge.exchanges.hyperliquid.live_executor import HlTwoPhaseExecutor, origin_to_cloid
from treasuryforge.journal import Journal
from treasuryforge.orders import IdempotentOrderManager, OrderState
from treasuryforge.types import Fill

MASTER = "0xMASTER"


class FakeInfo:
    def __init__(self):
        self.fills: dict[str, list[dict]] = {}     # cloid -> fills (shared with the exchange)

    def all_mids(self):
        return {"ETH": 1800.0, "BTC": 65000.0}

    def meta(self):
        return {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]}

    def fills_for_cloid(self, address, cloid):
        return self.fills.get(cloid.lower(), [])


class FakeExchange:
    """Records orders; on a 'fill' outcome it lands a fill the FakeInfo will reconcile."""

    def __init__(self, info, outcome="fill", raise_exc=None, error_msg="Insufficient margin"):
        self.info, self.outcome, self.raise_exc = info, outcome, raise_exc
        self.error_msg = error_msg
        self.calls = []

    def order(self, coin, is_buy, sz, px, order_type, reduce_only=False, cloid=None):
        self.calls.append({"coin": coin, "is_buy": is_buy, "sz": sz,
                           "reduce_only": reduce_only, "cloid": cloid})
        if self.raise_exc:
            raise self.raise_exc
        if self.outcome == "error":
            return {"response": {"data": {"statuses": [{"error": self.error_msg}]}}}
        if self.outcome == "rest":
            return {"response": {"data": {"statuses": [{"resting": {"oid": 777}}]}}}
        # 'fill': land a fill under the cloid so reconcile finds it
        self.info.fills[str(cloid).lower()] = [
            {"coin": coin, "px": "1801.0", "sz": str(sz), "side": "B" if is_buy else "A",
             "fee": "0.01", "time": 123, "oid": 555, "cloid": str(cloid)}]
        return {"response": {"data": {"statuses": [{"filled": {"totalSz": str(sz), "avgPx": "1801.0", "oid": 555}}]}}}


def _exec(info, outcome="fill", raise_exc=None, cap=15.0):
    ex = FakeExchange(info, outcome=outcome, raise_exc=raise_exc)
    # cloid_factory=str bypasses the SDK Cloid wrapping (validated on the VPS)
    return HlTwoPhaseExecutor(ex, info, MASTER, max_notional_usd=cap, cloid_factory=str), ex


def _intent(usd=11.0, side=Side.BUY):
    return Intent("ETH", side, 0.0, quote_amount=usd)


def test_cloid_is_deterministic_and_well_formed():
    a, b = origin_to_cloid("carry:ETH:1"), origin_to_cloid("carry:ETH:1")
    assert a == b and a.startswith("0x") and len(a) == 34      # 0x + 32 hex (128-bit)
    assert origin_to_cloid("carry:ETH:2") != a


def test_place_guard_failure_is_non_retryable():
    info = FakeInfo()
    ex, _ = _exec(info, cap=5.0)                                # cap below $10 floor
    with pytest.raises(BitsoError) as e:
        ex.place_order(_intent(20.0), "o1")
    assert e.value.category == NON_RETRYABLE


def test_place_network_exception_is_indeterminate():
    info = FakeInfo()
    ex, _ = _exec(info, raise_exc=TimeoutError("read timed out"))
    with pytest.raises(BitsoError) as e:
        ex.place_order(_intent(), "o1")
    assert e.value.category == INDETERMINATE                    # outcome unknown -> reconcile


def test_place_venue_error_is_classified():
    info = FakeInfo()
    ex, _ = _exec(info, outcome="error")
    with pytest.raises(BitsoError) as e:
        ex.place_order(_intent(), "o1")
    assert e.value.category == NON_RETRYABLE                    # insufficient margin = deterministic


def test_unregistered_agent_error_is_fatal_auth():
    info = FakeInfo()
    ex = HlTwoPhaseExecutor(FakeExchange(info, outcome="error", error_msg="Agent not registered"),
                            info, MASTER, max_notional_usd=15.0, cloid_factory=str)
    with pytest.raises(BitsoError) as e:
        ex.place_order(_intent(), "o1")
    assert e.value.category == FATAL_AUTH                       # bad/unauthorized agent -> stop, alert


def test_place_fill_returns_handle_with_oid():
    info = FakeInfo()
    ex, _ = _exec(info, outcome="fill")
    h = ex.place_order(_intent(), "o1")
    assert h.origin_id == "o1" and h.oid == "555" and h.book == "ETH"


def test_size_sent_is_hl_rounded_not_raw():
    # regression: the SDK rejects too-many-decimal sizes; we must send the szDecimals-
    # rounded value (ETH szDec=4). 11/1800 = 0.0061111.. -> must be sent as 0.0061.
    info = FakeInfo()
    ex, fake = _exec(info, outcome="fill")
    ex.place_order(_intent(11.0), "o1")
    assert fake.calls[0]["sz"] == pytest.approx(0.0061)         # rounded, not 0.0061111


def test_reconcile_no_fills_is_unfilled():
    info = FakeInfo()
    ex, _ = _exec(info)
    from treasuryforge.exchanges.bitso.executor import OrderHandle
    res = ex.reconcile(OrderHandle("nope", None, "ETH", Side.BUY), "ETH")
    assert isinstance(res, Unfilled)


def test_reconcile_aggregates_partial_fills():
    info = FakeInfo()
    ex, _ = _exec(info)
    cloid = origin_to_cloid("o9")
    info.fills[cloid.lower()] = [
        {"px": "1800", "sz": "0.003", "fee": "0.01", "time": 100, "cloid": cloid},
        {"px": "1820", "sz": "0.002", "fee": "0.02", "time": 200, "cloid": cloid}]
    from treasuryforge.exchanges.bitso.executor import OrderHandle
    fill = ex.reconcile(OrderHandle("o9", "1", "ETH", Side.BUY), "ETH")
    assert isinstance(fill, Fill)
    assert fill.base_amount == pytest.approx(0.005)
    assert fill.price == pytest.approx((1800 * 0.003 + 1820 * 0.002) / 0.005)   # size-weighted
    assert fill.fee == pytest.approx(0.03) and fill.ts == 200


def test_close_is_reduce_only_and_skips_floor():
    # a reduce-only close of a sub-$10 position must be allowed AND flagged reduce_only
    info = FakeInfo()
    fake = FakeExchange(info, outcome="fill")
    ex = HlTwoPhaseExecutor(fake, info, MASTER, max_notional_usd=15.0,
                            cloid_factory=str, reduce_only=True)
    ex.place_order(Intent("ETH", Side.SELL, 0.003), "close-1")   # 0.003*1800=$5.4 < $10 floor
    assert fake.calls[0]["reduce_only"] is True and fake.calls[0]["is_buy"] is False


def test_at_most_once_through_the_manager(tmp_path):
    info = FakeInfo()
    ex, fake = _exec(info, outcome="fill")
    mgr = IdempotentOrderManager(ex, Journal(str(tmp_path)))
    out1 = mgr.submit(_intent(), "carry:ETH:1", "ETH")
    out2 = mgr.submit(_intent(), "carry:ETH:1", "ETH")          # same origin_id -> must NOT re-place
    assert out1.is_filled and out2.is_filled
    assert out2.state is OrderState.FILLED
    assert len(fake.calls) == 1                                 # the order was sent exactly once
