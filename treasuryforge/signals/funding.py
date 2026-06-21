"""Funding-rate carry — a real, mechanical, delta-neutral edge.

The trade: hold +1 spot and -1 perpetual (size-matched) so price PnL cancels
(delta-neutral). On a perp, every funding interval longs pay shorts when the
funding rate is positive. Being SHORT the perp, you RECEIVE funding_rate * notional
each interval. The position's return is the accumulated funding minus the cost of
opening and closing both legs. We only harvest POSITIVE funding (shorting the perp
+ long spot needs no borrow); negative-funding harvest needs a spot short and is
out of scope for v1.

This module is the DECISION layer (perceive + compute probability). It never
executes; it emits ENTER/HOLD/EXIT/FLAT that the policy engine still has to clear.

Honest caveat from the research: funding carry is real but THIN and not risk-free
— funding can flip, the perp leg can be liquidated on a price gap, and the
headline APRs are volatile. Every parameter must be backtested net-of-cost through
the Deflated-Sharpe / purged-CV gate before it governs real funds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Action(str, Enum):
    ENTER = "ENTER"     # open the delta-neutral position this interval
    HOLD = "HOLD"       # stay in, accrue funding
    EXIT = "EXIT"       # close the position this interval
    FLAT = "FLAT"       # stay out


def annualize(rate_per_interval: float, intervals_per_year: int) -> float:
    """Simple (non-compounded) annualization of a per-interval funding rate."""
    return rate_per_interval * intervals_per_year


@dataclass(frozen=True)
class FundingCarryParams:
    enter_rate: float          # ENTER when funding_rate >= this (per interval)
    exit_rate: float           # EXIT when funding_rate < this (per interval)
    fee_per_leg: float         # taker fee fraction per leg
    legs_round_trip: int = 4   # open spot+perp, close spot+perp = 4 legs

    def __post_init__(self) -> None:
        if self.exit_rate > self.enter_rate:
            raise ValueError("exit_rate must be <= enter_rate (hysteresis)")

    @property
    def round_trip_cost(self) -> float:
        return self.legs_round_trip * self.fee_per_leg

    @property
    def entry_cost(self) -> float:
        return (self.legs_round_trip / 2) * self.fee_per_leg   # open 2 legs

    @property
    def exit_cost(self) -> float:
        return (self.legs_round_trip / 2) * self.fee_per_leg   # close 2 legs

    def breakeven_intervals(self) -> float:
        """How many intervals of `enter_rate` funding it takes to cover the
        full round-trip cost. A carry that never holds this long loses money."""
        if self.enter_rate <= 0:
            return float("inf")
        return self.round_trip_cost / self.enter_rate


class FundingCarrySignal:
    """Stateful enter/exit with hysteresis (enter high, exit low) plus the C2 age-rule.

    min_age delays entry until the high-funding EPISODE has already survived that many
    intervals — the survival-momentum selector the economic backtest found turns a
    fee-bleeding fresh-entry carry (-185bps OOS) into break-even (+4bps). min_age=0
    reduces to plain hysteresis (enter the moment funding crosses). _age is the episode
    age (intervals since funding crossed enter, while it stays >= exit)."""

    def __init__(self, params: FundingCarryParams, min_age: int = 0) -> None:
        self.p = params
        self.min_age = min_age
        self._in = False
        self._age = 0

    @property
    def in_position(self) -> bool:
        return self._in

    def _advance_age(self, funding_rate: float) -> None:
        if self._age == 0:
            if funding_rate >= self.p.enter_rate:
                self._age = 1                     # episode starts
        elif funding_rate < self.p.exit_rate:
            self._age = 0                         # episode ended
        else:
            self._age += 1                        # episode continues

    def decide(self, funding_rate: float) -> Action:
        self._advance_age(funding_rate)
        if self._in:
            if self._age == 0:                    # episode ended -> close
                self._in = False
                return Action.EXIT
            return Action.HOLD
        if self._age >= max(self.min_age, 1):     # episode survived the age gate -> enter
            self._in = True
            return Action.ENTER
        return Action.FLAT

    def expected_net_carry(self, funding_rate: float, holding_intervals: int) -> float:
        """Expected net return of entering now and holding `holding_intervals`,
        accruing `funding_rate` each interval, minus the full round-trip cost.
        This is the 'compute probability' number: > 0 means the carry is worth it."""
        return funding_rate * holding_intervals - self.p.round_trip_cost


class HyperliquidFundingFeed:
    """Keyless funding-rate feed (Hyperliquid `/info`). `post` is injected so the
    feed is fully offline-testable; the live `post` is a tiny urllib POST. No key,
    no auth, no funds — Hyperliquid's /info is genuinely public."""

    def __init__(self, post: Callable[[dict], Any]) -> None:
        self._post = post

    def current_funding(self, coin: str = "BTC") -> float:
        """Latest funding rate (per interval, e.g. hourly on Hyperliquid)."""
        data = self._post({"type": "metaAndAssetCtxs"})
        meta, ctxs = data[0], data[1]
        names = [a["name"] for a in meta["universe"]]
        idx = names.index(coin)
        return float(ctxs[idx]["funding"])

    def funding_history(self, coin: str = "BTC", start_ms: int = 0) -> list[float]:
        rows = self._post({"type": "fundingHistory", "coin": coin, "startTime": start_ms})
        return [float(r["fundingRate"]) for r in rows]

    def current_basis(self, coin: str = "BTC") -> tuple[float, float]:
        """(funding_per_interval, premium) in ONE call, where premium = (mark-oracle)/
        oracle. Drives the basis shadow: funding for the carry, premium for the entry."""
        data = self._post({"type": "metaAndAssetCtxs"})
        meta, ctxs = data[0], data[1]
        idx = [a["name"] for a in meta["universe"]].index(coin)
        c = ctxs[idx]
        mark, oracle = float(c.get("markPx", 0.0)), float(c.get("oraclePx", 0.0))
        premium = (mark - oracle) / oracle if oracle > 0 else 0.0
        return float(c["funding"]), premium
