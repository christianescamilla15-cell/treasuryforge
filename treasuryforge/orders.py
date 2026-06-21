"""Idempotent order manager — at-most-once submission with reconcile-before-retry.

The single most dangerous failure in live trading is not a bad strategy; it is
DUPLICATING an order because a place request timed out, the process crashed, or a
retry fired before we knew the first attempt's outcome. The rule is absolute:

    never send a second order for the same logical intent without first finding
    out what happened to the first one.

Two cooperating mechanisms enforce it:

  1. a STABLE origin_id per logical intent, persisted in the Journal, so every
     retry and every restart reuses the SAME id;
  2. RECONCILE-BEFORE-RETRY: on any uncertain outcome (timeout / 5xx / rate-limit)
     or on recovery after a crash, query the exchange by origin_id BEFORE acting.
     A confirmed fill is recorded once; only a confirmed no-fill is retried, and
     the retry reuses the same origin_id (which the exchange dedups among ACTIVE
     orders).

Why that is exactly-once: a landed-and-filled order is found by user_trades and
recorded (so we never re-post it); a landed-but-resting order is dedup'd by the
exchange on origin_id (so a re-post cannot duplicate it); a never-landed order is
safe to re-post. The journal guarantees we always reuse the id across the gap.

State machine per origin_id:
  PLACING -> SUBMITTED -> FILLED            happy path
  PLACING -> REJECTED                       deterministic rejection (never landed)
  PLACING -> UNKNOWN  -> FILLED | OPEN      timeout/5xx -> resolved by reconcile
  SUBMITTED | OPEN | UNKNOWN -> FILLED|OPEN  polled by reconcile
FILLED and REJECTED are terminal; submit() on a terminal id replays the result.

The manager is two-phase-executor shaped (Bitso today): the injected executor must
expose place_order(intent, origin_id) -> handle(.oid/.book/.side) and
reconcile(handle, symbol) -> Fill | <unfilled>, and raise BitsoError on failure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Protocol

from .exchanges.bitso.errors import (
    FATAL_AUTH,
    NON_RETRYABLE,
    BitsoError,
)
from .exchanges.bitso.executor import OrderHandle, Unfilled
from .journal import Journal
from .types import Fill, Intent, Side


class TwoPhaseExecutor(Protocol):
    """The execution surface the manager drives. BitsoExecutor satisfies it; an HL
    adapter can too. place_order raises BitsoError on failure."""

    def place_order(self, intent: Intent, origin_id: str) -> OrderHandle: ...
    def reconcile(self, handle: OrderHandle, symbol: str) -> Fill | Unfilled: ...


class OrderState(str, Enum):
    PLACING = "placing"        # journaled, POST in flight
    SUBMITTED = "submitted"    # exchange accepted (have oid or origin-only)
    UNKNOWN = "unknown"        # POST outcome unknown (timeout/5xx) -> must reconcile
    OPEN = "open"              # confirmed landed, no fill yet (resting / pending)
    FILLED = "filled"          # reconciled to a Fill (terminal)
    REJECTED = "rejected"      # deterministic pre-execution rejection (terminal)


_TERMINAL = {OrderState.FILLED, OrderState.REJECTED}
# categories that mean "the order definitely did NOT land" (safe, no reconcile)
_DEFINITELY_NOT_LANDED = {FATAL_AUTH, NON_RETRYABLE}


@dataclass
class OrderRecord:
    origin_id: str
    state: OrderState
    symbol: str = ""
    book: str = ""
    side: str = "buy"          # "buy" | "sell"
    oid: str | None = None
    attempts: int = 0
    reason: str = ""
    fill: dict | None = None   # asdict(Fill) once FILLED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> OrderRecord:
        d = dict(d)
        d["state"] = OrderState(d["state"])
        return cls(**d)

    def handle(self) -> OrderHandle:
        return OrderHandle(origin_id=self.origin_id, oid=self.oid, book=self.book,
                           side=Side.BUY if self.side == "buy" else Side.SELL)


@dataclass
class Outcome:
    """What submit()/recover() resolved an order to, for the caller to act on."""
    origin_id: str
    state: OrderState
    fill: Fill | None = None
    reason: str = ""

    @property
    def is_filled(self) -> bool:
        return self.state is OrderState.FILLED

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL


@dataclass
class IdempotentOrderManager:
    executor: TwoPhaseExecutor     # two-phase: place_order + reconcile
    journal: Journal               # DEDICATED journal dir (do not share with policy state)
    _orders: dict[str, OrderRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        state = self.journal.load_state()
        if state and "orders" in state:
            self._orders = {oid: OrderRecord.from_dict(r) for oid, r in state["orders"].items()}

    # -- persistence ------------------------------------------------------
    def _persist(self, rec: OrderRecord, event: str) -> None:
        self._orders[rec.origin_id] = rec
        # append-only audit first (durable WAL), then the fast-recovery checkpoint
        self.journal.append_event({"kind": "order", "event": event, **rec.to_dict()})
        self.journal.checkpoint({"orders": {o: r.to_dict() for o, r in self._orders.items()}})

    # -- public API -------------------------------------------------------
    def submit(self, intent: Intent, origin_id: str, symbol: str, *, max_attempts: int = 3) -> Outcome:
        """Idempotently drive one logical order toward a terminal/open state. Safe to
        call repeatedly with the same origin_id: a settled order replays its result;
        an in-flight one is reconciled FIRST; only a genuinely-uncertain (timed-out)
        attempt with no confirmed submission is retried, reusing the same origin_id."""
        rec = self._orders.get(origin_id)
        if rec is None:
            side = "buy" if intent.side is Side.BUY else "sell"
            rec = OrderRecord(origin_id=origin_id, state=OrderState.PLACING, symbol=symbol, side=side)
            self._persist(rec, "placing")
        return self._resolve(rec, intent, symbol, max_attempts)

    def recover(self, symbol_of: dict[str, str] | None = None) -> list[Outcome]:
        """After a restart, RECONCILE every non-terminal order before any new action.
        Recovery never places an order — it only learns the fate of in-flight ones."""
        out = []
        for origin_id, rec in list(self._orders.items()):
            if rec.state in _TERMINAL:
                continue
            symbol = rec.symbol or (symbol_of or {}).get(origin_id, "")
            if not self._try_fill(rec, symbol) and rec.oid is not None:
                self._set(rec, OrderState.OPEN, "resting (recovered)")
            out.append(self._outcome(rec))
        return out

    # -- internals --------------------------------------------------------
    def _resolve(self, rec: OrderRecord, intent: Intent, symbol: str, max_attempts: int) -> Outcome:
        if rec.state in _TERMINAL:
            return self._outcome(rec)

        # reconcile-before-(re)act for an order already in flight (or recovered)
        if rec.state in (OrderState.SUBMITTED, OrderState.OPEN, OrderState.UNKNOWN):
            if self._try_fill(rec, symbol):
                return self._outcome(rec)
            if rec.state is not OrderState.UNKNOWN:        # landed + resting -> never re-post
                self._set(rec, OrderState.OPEN, "resting")
                return self._outcome(rec)
            # UNKNOWN with no confirmed submission -> safe to (re)place below

        # (re)place, bounded, ALWAYS reusing the same origin_id
        while rec.attempts < max_attempts:
            self._place_once(rec, intent)
            if rec.state is OrderState.REJECTED:
                return self._outcome(rec)
            if self._try_fill(rec, symbol):
                return self._outcome(rec)
            if rec.state is not OrderState.UNKNOWN:        # SUBMITTED but unfilled -> resting
                self._set(rec, OrderState.OPEN, "resting")
                return self._outcome(rec)
            # UNKNOWN (timed out, no confirmation) -> retry with the same origin_id
        return self._outcome(rec)                          # attempts exhausted, still uncertain

    def _place_once(self, rec: OrderRecord, intent: Intent) -> None:
        rec.attempts += 1
        try:
            handle = self.executor.place_order(intent, rec.origin_id)
        except BitsoError as e:
            if e.category in _DEFINITELY_NOT_LANDED:
                self._set(rec, OrderState.REJECTED, str(e))
            else:                                          # INDETERMINATE / RETRYABLE_BACKOFF
                self._set(rec, OrderState.UNKNOWN, str(e))
            return
        rec.oid = getattr(handle, "oid", None)
        rec.book = getattr(handle, "book", rec.book)
        self._set(rec, OrderState.SUBMITTED, "")

    def _try_fill(self, rec: OrderRecord, symbol: str) -> bool:
        """Reconcile by oid/origin_id; promote to FILLED on a real fill. Returns
        whether it filled. Leaves the state unchanged on no-fill (the caller decides)."""
        result = self.executor.reconcile(rec.handle(), symbol or rec.symbol)
        if isinstance(result, Fill):
            rec.fill = asdict(result)
            self._set(rec, OrderState.FILLED, "")
            return True
        return False

    def _set(self, rec: OrderRecord, state: OrderState, reason: str) -> None:
        rec.state, rec.reason = state, reason
        self._persist(rec, state.value)

    def _outcome(self, rec: OrderRecord) -> Outcome:
        fill = None
        if rec.fill:
            d = dict(rec.fill)
            d["side"] = Side(d["side"])        # JSON round-trips the enum to its str value
            fill = Fill(**d)
        return Outcome(rec.origin_id, rec.state, fill=fill, reason=rec.reason)


def make_origin_id(strategy: str, step: int, symbol: str) -> str:
    """Deterministic, collision-resistant id for one logical decision. The SAME
    (strategy, step, symbol) always yields the same id, so a retry reuses it."""
    return f"{strategy}:{symbol}:{step}"
