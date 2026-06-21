"""The staged go/no-go validation ladder (PHASE3_IMPLEMENTATION.md §4).

Each rung is gated: order-placing rungs (5, 6) run ONLY when arm=True. Read-only
rungs (1-4) are always safe. The same code runs in `paper` mode (MockBitsoAPI,
zero risk) and `live` mode (real transport, real key, from the VPS).

run_ladder returns a list of RungResult so it is unit-testable and the CLI just
prints it. A single FAIL halts the ladder — you never advance on a red rung.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...types import Intent, OrderType, Side
from .client import BitsoClient
from .errors import BitsoError
from .executor import BitsoExecutor, Unfilled

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


@dataclass
class RungResult:
    name: str
    status: str
    detail: str
    data: dict = field(default_factory=dict)


def _mxn_available(balance_payload: dict) -> float | None:
    for b in balance_payload.get("payload", {}).get("balances", []):
        if b.get("currency") == "mxn":
            return float(b.get("available", 0.0))
    return None


def run_ladder(  # noqa: C901 - sequential safety ladder; each rung is a named gate, kept linear on purpose
    client: BitsoClient,
    executor: BitsoExecutor,
    *,
    symbol: str = "BTC",
    book: str = "btc_mxn",
    arm: bool = False,
    max_mxn: float = 20.0,
    origin_prefix: str = "tf-val",
) -> list[RungResult]:
    out: list[RungResult] = []

    def add(r: RungResult) -> bool:
        out.append(r)
        return r.status != FAIL

    # Rung 1 — public market constraints --------------------------------
    status, payload = client.available_books()
    books = {b["book"]: b for b in payload.get("payload", [])} if payload.get("success") else {}
    if status == 200 and book in books:
        bk = books[book]
        add(RungResult("1-available_books", PASS,
                       f"{book} min_value={bk.get('minimum_value')} min_amount={bk.get('minimum_amount')}",
                       {"book": bk}))
    else:
        return [RungResult("1-available_books", FAIL, f"status={status}, {book} not found")]

    # Rung 2 — signed read (auth canary) --------------------------------
    status, payload = client.balance()
    if status == 200 and payload.get("success"):
        mxn = _mxn_available(payload)
        if not add(RungResult("2-balance", PASS, f"auth OK; mxn available={mxn}", {"mxn": mxn})):
            return out
    else:
        out.append(RungResult("2-balance", FAIL, f"signed read failed: status={status} {payload}"))
        return out

    # Rung 3 — prove the key CANNOT withdraw (fail-closed) ---------------
    # The probe sends a deliberately invalid withdrawal. Reaching param
    # VALIDATION (a 400) means the request passed the authorization gate -> the
    # key HAS withdraw scope -> FAIL. Only a 0202 (auth-blocked before business
    # logic) proves it cannot withdraw. A 404 means the probe path is wrong
    # (inconclusive); a sig/IP error means we couldn't authenticate at all.
    status, payload = client.probe_withdrawal()
    code = payload.get("error", {}).get("code", "")
    AUTH_FAILED = {"0201", "0206", "0207", "0213", "0215"}
    if payload.get("success") or status in (200, 201):
        out.append(RungResult("3-no_withdraw", FAIL,
                              "DANGER: withdrawal ACCEPTED — key has withdraw scope. ABORT."))
        return out
    if code == "0202":
        add(RungResult("3-no_withdraw", PASS, "withdrawal rejected with 0202 (not authorized)"))
    elif status == 404:
        add(RungResult("3-no_withdraw", WARN,
                       "probe path 404 (inconclusive) — rely on scope-at-creation"))
    elif code in AUTH_FAILED:
        add(RungResult("3-no_withdraw", WARN,
                       f"could not authenticate the probe (code={code}); rerun after fixing auth"))
    else:
        out.append(RungResult("3-no_withdraw", FAIL,
                              f"DANGER: probe reached business logic (status={status} code={code}) "
                              "— key likely HAS withdraw scope. ABORT."))
        return out

    # Rung 4 — live fee tier --------------------------------------------
    status, payload = client.fees()
    taker = None
    if status == 200 and payload.get("success"):
        for f in payload.get("payload", {}).get("fees", []):
            if f.get("book") == book:
                taker = float(f.get("taker_fee_decimal"))
        add(RungResult("4-fees", PASS, f"{book} taker={taker}", {"taker": taker}))
    else:
        add(RungResult("4-fees", WARN, f"could not read fees: status={status}"))

    if not arm:
        out.append(RungResult("5-kill_path", SKIP, "not armed (read-only run)"))
        out.append(RungResult("6-tiny_order", SKIP, "not armed (read-only run)"))
        return out

    try:
        # Rung 5 — kill-path on a RESTING limit order (proves cancel works) --
        bk = books[book]
        rest_price = max(float(bk.get("minimum_price", "1") or "1"), 1.0)
        rest_amount = max(float(bk.get("minimum_amount", "0.0001")), max_mxn / rest_price)
        limit_intent = Intent(symbol, Side.BUY, rest_amount, order_type=OrderType.LIMIT,
                              limit_price=rest_price, reason="kill-path resting order")
        handle = executor.place_order(limit_intent, f"{origin_prefix}-rest")
        _, oo = client.open_orders(book)
        is_open = any(o.get("oid") == handle.oid for o in oo.get("payload", []))
        client.cancel_all()
        _, oo2 = client.open_orders(book)
        still_open = any(o.get("oid") == handle.oid for o in oo2.get("payload", []))
        if is_open and not still_open:
            add(RungResult("5-kill_path", PASS, "resting order opened then cancel_all cleared it"))
        else:
            out.append(RungResult("5-kill_path", FAIL,
                                  f"kill-path broken: opened={is_open} still_open={still_open}"))
            return out

        # Rung 6 — one tiny market buy, then reconcile (the real validation) -
        buy = Intent(symbol, Side.BUY, 0.0, order_type=OrderType.MARKET,
                     quote_amount=min(max_mxn, 20.0), reason="tiny validation buy")
        handle = executor.place_order(buy, f"{origin_prefix}-buy")
        fill = executor.reconcile(handle, symbol)
    except BitsoError as e:
        out.append(RungResult("5/6-order", FAIL, f"order rung failed: {e}"))
        return out

    if isinstance(fill, Unfilled):
        out.append(RungResult("6-tiny_order", FAIL, f"order did not fill: {fill.reason}"))
        return out
    notional = fill.base_amount * fill.price
    fee_quote = fill.fee * fill.price if fill.fee_currency == "base" else fill.fee
    eff_cost = fee_quote / notional if notional else 1.0
    status_6 = PASS if eff_cost <= 0.015 else FAIL
    add(RungResult("6-tiny_order", status_6,
                   f"filled {fill.base_amount} {symbol} @ {fill.price}; "
                   f"effective cost {eff_cost:.4%} (gate <=1.50%)",
                   {"fill_base": fill.base_amount, "price": fill.price,
                    "fee": fill.fee, "fee_currency": fill.fee_currency, "eff_cost": eff_cost}))
    return out
