"""Idempotent order manager — at-most-once + reconcile-before-retry.

Each test drives the manager through a dangerous real-world sequence (timeout that
secretly landed, crash mid-flight, blind retry) and asserts the invariant: a
logical order produces AT MOST ONE fill, retries reuse the same origin_id, and a
restart reconciles in-flight orders before doing anything new.
"""

from __future__ import annotations

from treasuryforge.exchanges.bitso.errors import (
    FATAL_AUTH,
    INDETERMINATE,
    NON_RETRYABLE,
    BitsoError,
)
from treasuryforge.exchanges.bitso.executor import OrderHandle, Unfilled
from treasuryforge.journal import Journal
from treasuryforge.orders import (
    IdempotentOrderManager,
    OrderRecord,
    OrderState,
    Outcome,
    make_origin_id,
)
from treasuryforge.types import Fill, Intent, Side


def _fill(origin_id: str) -> Fill:
    return Fill(symbol="BTC", side=Side.BUY, base_amount=0.001, price=1_000_000.0,
                fee=0.000001, ts=int(origin_id[-1]) if origin_id[-1].isdigit() else 1,
                fee_currency="base")


class FakeExec:
    """Scriptable two-phase executor. `place_script` is a queue of behaviors:
    "ok" (returns oid), "submitted" (accepted, oid=None), or a BitsoError to raise.
    An origin_id present in `landed` reconciles to a Fill; otherwise Unfilled.
    `land_on_ok=True` makes a successful place ALSO mark the order as landed."""

    def __init__(self, place_script, landed=None, land_on_ok=True):
        self.place_script = list(place_script)
        self.landed = set(landed or ())
        self.land_on_ok = land_on_ok
        self.place_calls: list[str] = []
        self.reconcile_calls: list[str] = []
        self.reconcile_symbols: list[str] = []

    def place_order(self, intent: Intent, origin_id: str) -> OrderHandle:
        self.place_calls.append(origin_id)
        b = self.place_script.pop(0) if self.place_script else "ok"
        if isinstance(b, BitsoError):
            raise b
        oid = f"oid-{origin_id}" if b == "ok" else None
        if self.land_on_ok and b == "ok":
            self.landed.add(origin_id)
        return OrderHandle(origin_id=origin_id, oid=oid, book="btc_mxn", side=intent.side)

    def reconcile(self, handle: OrderHandle, symbol: str):
        self.reconcile_calls.append(handle.origin_id)
        self.reconcile_symbols.append(symbol)
        if handle.origin_id in self.landed:
            return _fill(handle.origin_id)
        return Unfilled(handle, "no fills yet")


def _intent():
    return Intent("BTC", Side.BUY, 0.001)


def _mgr(tmp_path, ex, sub="orders"):
    return IdempotentOrderManager(ex, Journal(str(tmp_path / sub)))


# -- happy path + idempotent replay -----------------------------------------
def test_happy_path_places_once_and_fills(tmp_path):
    ex = FakeExec(["ok"])
    out = _mgr(tmp_path, ex).submit(_intent(), "o1", "BTC")
    assert out.is_filled and out.fill.base_amount == 0.001
    assert ex.place_calls == ["o1"]


def test_resubmit_replays_fill_without_a_second_place(tmp_path):
    ex = FakeExec(["ok"])
    m = _mgr(tmp_path, ex)
    first = m.submit(_intent(), "o1", "BTC")
    second = m.submit(_intent(), "o1", "BTC")          # same origin_id again
    assert first.is_filled and second.is_filled
    assert second.fill.side is Side.BUY                # enum survives replay
    assert ex.place_calls == ["o1"]                    # NOT placed twice


# -- the timeout-but-landed trap (no duplicate) -----------------------------
def test_indeterminate_then_reconcile_finds_the_fill(tmp_path):
    # place times out (INDETERMINATE) but the order DID land + fill on the exchange
    err = BitsoError(INDETERMINATE, "", "timeout", 0)
    ex = FakeExec([err], landed={"o1"})                # already landed despite the timeout
    out = _mgr(tmp_path, ex).submit(_intent(), "o1", "BTC")
    assert out.is_filled
    assert ex.place_calls == ["o1"]                    # exactly one POST, no duplicate
    assert ex.reconcile_calls == ["o1"]                # reconciled before any retry


# -- timeout-not-landed: safe retry reuses the SAME origin_id ----------------
def test_indeterminate_not_landed_retries_same_origin_id(tmp_path):
    err = BitsoError(INDETERMINATE, "", "timeout", 0)
    ex = FakeExec([err, "ok"])                         # 1st times out (not landed), 2nd lands+fills
    out = _mgr(tmp_path, ex).submit(_intent(), "o1", "BTC")
    assert out.is_filled
    assert ex.place_calls == ["o1", "o1"]              # retried with the SAME id, never a new one


# -- deterministic rejection is terminal ------------------------------------
def test_non_retryable_is_rejected_and_not_retried(tmp_path):
    err = BitsoError(NON_RETRYABLE, "0379", "insufficient funds", 400)
    ex = FakeExec([err])
    m = _mgr(tmp_path, ex)
    out = m.submit(_intent(), "o1", "BTC")
    assert out.state is OrderState.REJECTED and not out.is_filled
    again = m.submit(_intent(), "o1", "BTC")           # resubmit must NOT re-POST
    assert again.state is OrderState.REJECTED
    assert ex.place_calls == ["o1"]


def test_fatal_auth_is_rejected(tmp_path):
    err = BitsoError(FATAL_AUTH, "0213", "IP not allowlisted", 403)
    out = _mgr(tmp_path, FakeExec([err])).submit(_intent(), "o1", "BTC")
    assert out.state is OrderState.REJECTED


# -- resting order is left OPEN, never re-posted ----------------------------
def test_submitted_but_unfilled_is_open_and_not_reposted(tmp_path):
    ex = FakeExec(["ok"], land_on_ok=False)            # accepted w/ oid, but no fill yet
    m = _mgr(tmp_path, ex)
    out = m.submit(_intent(), "o1", "BTC")
    assert out.state is OrderState.OPEN
    again = m.submit(_intent(), "o1", "BTC")           # has an oid -> live -> must NOT re-POST
    assert again.state is OrderState.OPEN
    assert ex.place_calls == ["o1"]


# -- crash recovery: in-flight order is reconciled before new action --------
def test_recover_reconciles_inflight_order_after_restart(tmp_path):
    # manager #1 submits, order accepted (oid=None, submitted-not-final), no fill yet
    ex1 = FakeExec(["submitted"], land_on_ok=False)
    m1 = _mgr(tmp_path, ex1)
    out1 = m1.submit(_intent(), "o1", "BTC")
    assert out1.state is OrderState.OPEN

    # ... process crashes; meanwhile the order fills on the exchange ...
    ex2 = FakeExec([], landed={"o1"})
    m2 = _mgr(tmp_path, ex2)                            # rebuilt from the SAME journal dir
    assert m2._orders["o1"].state is OrderState.OPEN    # state recovered from disk
    recovered = m2.recover()
    assert len(recovered) == 1 and recovered[0].is_filled
    assert ex2.place_calls == []                        # recovery NEVER places a new order


def test_recover_skips_terminal_orders(tmp_path):
    ex1 = FakeExec(["ok"])
    m1 = _mgr(tmp_path, ex1)
    m1.submit(_intent(), "o1", "BTC")                  # FILLED (terminal)
    m2 = _mgr(tmp_path, FakeExec([]))
    assert m2.recover() == []                           # nothing in-flight to reconcile


# -- the origin_id helper ----------------------------------------------------
def test_make_origin_id_is_deterministic():
    a = make_origin_id("funding_carry", 42, "ETH")
    b = make_origin_id("funding_carry", 42, "ETH")
    assert a == b == "funding_carry:ETH:42"
    assert make_origin_id("funding_carry", 43, "ETH") != a


# ============================================================================
# mutation hardening: persistence, exact state values, defaults, boundaries
# ============================================================================
def test_order_state_values_are_exact():
    assert [s.value for s in OrderState] == [
        "placing", "submitted", "unknown", "open", "filled", "rejected"]


def test_order_record_defaults_and_roundtrip():
    rec = OrderRecord(origin_id="x", state=OrderState.PLACING)
    assert (rec.symbol, rec.book, rec.side) == ("", "", "buy")
    assert rec.oid is None and rec.attempts == 0 and rec.reason == "" and rec.fill is None
    d = rec.to_dict()
    assert d["state"] == "placing"                       # enum serialized to its value
    assert OrderRecord.from_dict(d) == rec               # exact round-trip


def test_order_record_handle_maps_side():
    assert OrderRecord("x", OrderState.OPEN, side="buy").handle().side is Side.BUY
    assert OrderRecord("x", OrderState.OPEN, side="sell").handle().side is Side.SELL


def test_outcome_terminal_and_filled_flags():
    assert Outcome("x", OrderState.FILLED).is_terminal and Outcome("x", OrderState.FILLED).is_filled
    assert Outcome("x", OrderState.REJECTED).is_terminal
    assert not Outcome("x", OrderState.OPEN).is_terminal
    assert not Outcome("x", OrderState.OPEN).is_filled


def test_journal_records_each_transition_with_kind_and_event(tmp_path):
    ex = FakeExec(["ok"])
    m = _mgr(tmp_path, ex)
    m.submit(_intent(), "o1", "BTC")
    events = m.journal.read_ledger()
    assert [e["event"] for e in events] == ["placing", "submitted", "filled"]
    assert all(e["kind"] == "order" for e in events)
    assert all(e["origin_id"] == "o1" for e in events)   # rec fields are unpacked in (** not *)


def test_submitted_record_captures_oid_book_and_side(tmp_path):
    ex = FakeExec(["ok"], land_on_ok=False)
    m = _mgr(tmp_path, ex)
    m.submit(Intent("BTC", Side.SELL, 0.001), "o1", "BTC")
    rec = m._orders["o1"]
    assert rec.oid == "oid-o1" and rec.book == "btc_mxn" and rec.side == "sell"
    assert rec.state is OrderState.OPEN and rec.reason == "resting"


def test_filled_record_has_empty_reason(tmp_path):
    m = _mgr(tmp_path, FakeExec(["ok"]))
    m.submit(_intent(), "o1", "BTC")
    assert m._orders["o1"].reason == ""


def test_attempts_counts_and_max_attempts_default_is_three(tmp_path):
    err = BitsoError(INDETERMINATE, "", "timeout", 0)
    ex = FakeExec([err, err, err, err, err])             # never lands -> exhausts retries
    out = _mgr(tmp_path, ex).submit(_intent(), "o1", "BTC")
    assert ex.place_calls == ["o1", "o1", "o1"]          # exactly max_attempts=3, same id
    assert out.state is OrderState.UNKNOWN


def test_rejected_outcome_has_no_fill(tmp_path):
    err = BitsoError(NON_RETRYABLE, "0379", "insufficient funds", 400)
    out = _mgr(tmp_path, FakeExec([err])).submit(_intent(), "o1", "BTC")
    assert out.fill is None


def test_recover_passes_symbol_from_record_or_map(tmp_path):
    # record has no symbol; symbol_of supplies it -> reconcile must see "BTC"
    ex1 = FakeExec(["submitted"], land_on_ok=False)
    m1 = _mgr(tmp_path, ex1)
    rec = OrderRecord("o1", OrderState.UNKNOWN, symbol="")   # in-flight, unknown, no symbol
    m1._orders["o1"] = rec
    ex2 = FakeExec([], landed={"o1"})
    m2 = IdempotentOrderManager(ex2, m1.journal)
    m2._orders = {"o1": rec}
    m2.recover(symbol_of={"o1": "BTC"})
    assert ex2.reconcile_symbols == ["BTC"]


def test_recover_marks_resting_order_open_only_when_it_has_an_oid(tmp_path):
    ex = FakeExec([])                                    # nothing lands
    m = _mgr(tmp_path, ex)
    m._orders = {
        "withoid": OrderRecord("withoid", OrderState.SUBMITTED, symbol="BTC", oid="oid-x"),
        "noid": OrderRecord("noid", OrderState.UNKNOWN, symbol="BTC", oid=None),
    }
    m.recover()
    assert m._orders["withoid"].state is OrderState.OPEN          # oid + no fill -> resting
    assert m._orders["withoid"].reason == "resting (recovered)"
    assert m._orders["noid"].state is OrderState.UNKNOWN          # no oid -> NOT marked open


def test_recover_processes_nonterminal_after_a_terminal(tmp_path):
    # a terminal order encountered first must be SKIPPED (continue), not stop the loop
    ex = FakeExec([], landed={"live"})
    m = _mgr(tmp_path, ex)
    m._orders = {
        "dead": OrderRecord("dead", OrderState.FILLED, symbol="BTC"),
        "live": OrderRecord("live", OrderState.SUBMITTED, symbol="BTC", oid="oid-l"),
    }
    m.recover()
    assert m._orders["live"].state is OrderState.FILLED          # processed despite earlier terminal
