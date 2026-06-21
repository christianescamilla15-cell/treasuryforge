"""Exhaustive LOCAL validation of the live path — against the high-fidelity
MockBitsoAPI emulator. Zero network, zero keys, zero funds. This is the gate that
must be green before a single peso is risked.
"""

from __future__ import annotations

import pytest

from treasuryforge import Intent, Side
from treasuryforge.exchanges.bitso.client import BitsoClient
from treasuryforge.exchanges.bitso.executor import BitsoExecutor
from treasuryforge.exchanges.bitso.mock import MockBitsoAPI
from treasuryforge.exchanges.bitso.signer import BitsoSigner, NonceV2
from treasuryforge.exchanges.bitso.validation import FAIL, PASS, SKIP, run_ladder


def _wire(api: MockBitsoAPI):
    signer = BitsoSigner("k", "s", NonceV2(now_ms=lambda: 1, salt=lambda: 0))
    client = BitsoClient(signer, api)
    executor = BitsoExecutor(signer, api, book_map={"BTC": "btc_mxn"})
    return client, executor


def _by_name(results):
    return {r.name: r for r in results}


# -- the full ladder ---------------------------------------------------------
def test_full_ladder_all_green_on_emulator():
    client, ex = _wire(MockBitsoAPI())
    results = run_ladder(client, ex, arm=True, max_mxn=20.0)
    assert all(r.status != FAIL for r in results)
    names = _by_name(results)
    assert names["1-available_books"].status == PASS
    assert names["2-balance"].status == PASS
    assert names["3-no_withdraw"].status == PASS
    assert names["5-kill_path"].status == PASS
    assert names["6-tiny_order"].status == PASS
    assert names["6-tiny_order"].data["fee_currency"] == "base"      # Bitso BUY fee in base
    assert names["6-tiny_order"].data["eff_cost"] == pytest.approx(0.0078, abs=1e-4)


def test_readonly_run_skips_order_rungs():
    client, ex = _wire(MockBitsoAPI())
    names = _by_name(run_ladder(client, ex, arm=False))
    assert names["5-kill_path"].status == SKIP
    assert names["6-tiny_order"].status == SKIP


# -- the SAFETY detections (the whole point) ---------------------------------
def test_ladder_HALTS_if_key_can_withdraw():
    # a misconfigured key that CAN withdraw must be caught at rung 3 and abort
    client, ex = _wire(MockBitsoAPI(withdrawals_allowed=True))
    results = run_ladder(client, ex, arm=True)
    names = _by_name(results)
    assert names["3-no_withdraw"].status == FAIL
    assert "4-fees" not in names                          # halted, never advanced


def test_ladder_fails_clean_on_insufficient_funds():
    # only 5 MXN but the tiny order wants 20 -> 0379, must surface as a clean FAIL
    client, ex = _wire(MockBitsoAPI(balances={"mxn": 5.0, "btc": 0.0}))
    results = run_ladder(client, ex, arm=True, max_mxn=20.0)
    assert any(r.status == FAIL for r in results)
    assert all("Traceback" not in r.detail for r in results)


def test_unsigned_private_call_is_rejected():
    api = MockBitsoAPI()
    status, payload = api("GET", "/api/v3/balance/", "", {})      # no Authorization
    assert status == 401 and payload["error"]["code"] == "0201"


# -- emulator fidelity -------------------------------------------------------
def test_market_buy_debits_quote_credits_base_minus_fee():
    api = MockBitsoAPI(balances={"mxn": 200.0, "btc": 0.0}, prices={"btc_mxn": 1_000_000.0})
    _client, ex = _wire(api)
    h = ex.place_order(Intent("BTC", Side.BUY, 0.0, quote_amount=20.0), "o1")
    fill = ex.reconcile(h, "BTC")
    gross = 20.0 / 1_000_000.0
    assert api.balances["mxn"] == pytest.approx(180.0)            # spent exactly 20
    assert api.balances["btc"] == pytest.approx(gross * (1 - 0.0078))
    assert fill.fee_currency == "base"


def test_rate_limit_surfaces_as_420():
    api = MockBitsoAPI()
    api.inject_rate_limit(1)
    status, _ = api("GET", "/api/v3/balance/", "", {"Authorization": "Bitso x"})
    assert status == 420                                          # NOT 429


def test_resting_limit_then_cancel_all_clears_it():
    api = MockBitsoAPI()
    client, ex = _wire(api)
    from treasuryforge.types import OrderType
    h = ex.place_order(Intent("BTC", Side.BUY, 0.001, order_type=OrderType.LIMIT,
                              limit_price=1.0), "rest1")
    _, oo = client.open_orders("btc_mxn")
    assert any(o["oid"] == h.oid for o in oo["payload"])
    client.cancel_all()
    _, oo2 = client.open_orders("btc_mxn")
    assert not any(o["oid"] == h.oid for o in oo2["payload"])


# -- idempotency hazard: the exchange does NOT dedupe ------------------------
def test_duplicate_origin_id_creates_two_orders_proving_journal_is_required():
    api = MockBitsoAPI()
    _, ex = _wire(api)
    intent = Intent("BTC", Side.BUY, 0.0, quote_amount=20.0)
    ex.place_order(intent, "same-id")
    ex.place_order(intent, "same-id")                            # retry with same origin_id
    completed = [o for o in api.orders.values() if o["status"] == "completed"]
    assert len(completed) == 2     # exchange double-bought -> the JOURNAL must prevent this
