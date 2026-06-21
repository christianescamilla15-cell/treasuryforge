"""Bitso adapter — all offline (injected transport, no network, no keys, no funds)."""

from __future__ import annotations

import json

import pytest

from treasuryforge import Intent, OrderType, Side
from treasuryforge.exchanges.bitso import (
    BitsoError,
    BitsoExecutor,
    BitsoSigner,
    NonceV2,
    OrderHandle,
    Unfilled,
)
from treasuryforge.exchanges.bitso.errors import FATAL_AUTH, NON_RETRYABLE, RETRYABLE_BACKOFF

# -- signer: golden vector (cross-checked vs openssl AND python at build time) --
GOLDEN_SIG = "acbad404127ea91fd5a6632a82bbb81f424d76eb5ac862b04934e586b0062162"
GOLDEN_BODY = '{"book":"btc_mxn","side":"buy","type":"market","major":"0.0001"}'


def test_signer_matches_golden_vector():
    nonce = NonceV2(now_ms=lambda: 1_700_000_000_000, salt=lambda: 0)
    signer = BitsoSigner("testkey", "testsecret0123456789", nonce)
    header, used = signer.auth_header("POST", "/api/v3/orders", GOLDEN_BODY)
    assert used == 1_700_000_000_000_000_000
    assert header == f"Bitso testkey:{used}:{GOLDEN_SIG}"


def test_static_signature_helper_matches_golden():
    sig = BitsoSigner.signature(b"testsecret0123456789", 1_700_000_000_000_000_000,
                                "POST", "/api/v3/orders", GOLDEN_BODY)
    assert sig == GOLDEN_SIG


def test_nonce_is_monotonic_even_on_clock_regress():
    # last is already ahead of the candidate (simulating an NTP step-back / restart)
    n = NonceV2(now_ms=lambda: 1000, salt=lambda: 5, last=2_000_000_000)
    a = n.next()
    b = n.next()
    assert a == 2_000_000_001 and b == 2_000_000_002


# -- executor: injectable fake transport -------------------------------------
class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, body, headers):
        self.calls.append((method, path, body, headers))
        return self.responses.pop(0)


def _exec(responses):
    nonce = NonceV2(now_ms=lambda: 1, salt=lambda: 0)
    signer = BitsoSigner("k", "s", nonce)
    ft = FakeTransport(responses)
    return BitsoExecutor(signer, ft, book_map={"BTC": "btc_mxn"}), ft


def test_place_order_maps_market_buy_and_signs():
    ex, ft = _exec([(200, {"success": True, "payload": {"oid": "abc123"}})])
    h = ex.place_order(Intent("BTC", Side.BUY, 0.0001), "ord-1")
    assert h.oid == "abc123" and h.book == "btc_mxn" and h.side is Side.BUY

    method, path, body, headers = ft.calls[0]
    assert method == "POST" and path == "/api/v3/orders/"
    p = json.loads(body)
    assert p == {"book": "btc_mxn", "side": "buy", "type": "market",
                 "major": "0.0001", "origin_id": "ord-1"}
    assert headers["Authorization"].startswith("Bitso k:")


def test_quote_amount_maps_to_minor_buy_only():
    ex, ft = _exec([(200, {"success": True, "payload": {"oid": "x"}})])
    ex.place_order(Intent("BTC", Side.BUY, 0.0, quote_amount=200.0), "o")
    p = json.loads(ft.calls[0][2])
    assert p["minor"] == "200.0" and "major" not in p

    ex2, _ = _exec([])
    with pytest.raises(ValueError):       # spend-exactly on a SELL is rejected
        ex2.place_order(Intent("BTC", Side.SELL, 0.0, quote_amount=200.0), "o")


def test_limit_requires_price():
    ex, _ = _exec([])
    with pytest.raises(ValueError):
        ex.place_order(Intent("BTC", Side.SELL, 0.001, order_type=OrderType.LIMIT), "o")


def test_place_order_raises_classified_auth_error():
    ex, _ = _exec([(401, {"success": False, "error": {"code": "0202", "message": "nope"}})])
    with pytest.raises(BitsoError) as e:
        ex.place_order(Intent("BTC", Side.BUY, 0.0001), "o")
    assert e.value.category == FATAL_AUTH and e.value.code == "0202"


def test_reconcile_vwaps_partial_fills_and_fee_in_base_for_buy():
    trades = [
        {"major": "0.0006", "price": "1000000", "fees_amount": "0.0000006", "tid": 10},
        {"major": "0.0004", "price": "1010000", "fees_amount": "0.0000004", "tid": 11},
    ]
    ex, _ = _exec([(200, {"success": True, "payload": trades})])
    fill = ex.reconcile(OrderHandle("o", "abc", "btc_mxn", Side.BUY), "BTC")
    assert not isinstance(fill, Unfilled)
    assert fill.base_amount == pytest.approx(0.001)
    assert fill.price == pytest.approx((600 + 404) / 0.001)          # VWAP
    assert fill.fee == pytest.approx(0.000001)
    assert fill.fee_currency == "base"                              # Bitso BUY fee in base
    assert fill.ts == 11


def test_reconcile_returns_unfilled_when_no_trades_yet():
    ex, _ = _exec([(200, {"success": True, "payload": []})])
    r = ex.reconcile(OrderHandle("o", "abc", "btc_mxn", Side.BUY), "BTC")
    assert isinstance(r, Unfilled)


# -- error taxonomy ----------------------------------------------------------
def test_rate_limit_is_420_not_429():
    from treasuryforge.exchanges.bitso.errors import classify
    assert classify(420) == RETRYABLE_BACKOFF
    assert classify(429) == NON_RETRYABLE          # 429 is NOT how Bitso signals rate limit


def test_5xx_is_indeterminate_not_retryable():
    from treasuryforge.exchanges.bitso.errors import INDETERMINATE, classify
    assert classify(503) == INDETERMINATE
    assert classify(0) == INDETERMINATE            # timeout
