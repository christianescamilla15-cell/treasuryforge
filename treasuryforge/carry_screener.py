"""Carry opportunity screener (Roadmap A3) — rank by NET edge, gate on cost.

The churn the PnL decomposition exposed (fees 10-64x the funding collected) happens
because the shadow enters whenever funding crosses a threshold, ignoring whether the
funding it can collect over the hold actually beats the round-trip cost. This screener
is that missing cost-gate:

    score = expected_funding_over_N_hours        (carry you can collect)
          + expected_premium_convergence         (basis leg; only when contango)
          - round_trip_cost   (REALISTIC, from the A2 maker-first fill model)
          - liquidation_buffer

Only a POSITIVE net edge is worth entering. Verdicts escalate only as more evidence
arrives: NO_TRADE (cost-gate fails) -> WATCH (thin / cost-heavy) -> PAPER (net edge
survives costs) -> MICRO_ELIGIBLE / LIVE_ELIGIBLE (also pass the risk gates: DSR>=0.60
and enough shadow days). The screener NEVER grants MICRO/LIVE on net edge alone.

Selection-bias honesty: screening N coins for the best is the trap the DSR exists to
catch, so the result carries `n_candidates` — downstream validation must set the DSR's
n_trials to it, or the "best" coin is just the luckiest of N.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from .fill_model import FillModelParams, round_trip_cost

HOURS_PER_YEAR = 24 * 365


class Verdict(str, Enum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    PAPER = "PAPER"
    MICRO_ELIGIBLE = "MICRO_ELIGIBLE"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"


@dataclass(frozen=True)
class ScreenParams:
    hold_hours: int = 8                  # horizon over which we expect to collect funding
    margin_bps: float = 0.0001           # required net-edge buffer (1 bp)
    liq_buffer: float = 0.00005          # liquidation-buffer cost (fractional)
    max_cost_ratio: float = 0.35         # kill if costs eat > this share of gross
    legs: int = 4
    fill: FillModelParams = field(default_factory=FillModelParams)


@dataclass(frozen=True)
class CarryOpportunity:
    coin: str
    funding_apr: float
    expected_funding: float              # over hold_hours (fractional)
    expected_convergence: float
    round_trip_cost: float
    net_edge: float                      # fractional, over the hold
    verdict: Verdict

    @property
    def gross(self) -> float:
        return self.expected_funding + self.expected_convergence

    @property
    def net_edge_bps(self) -> float:
        return self.net_edge * 1e4

    @property
    def cost_ratio(self) -> float:
        return (self.gross - self.net_edge) / self.gross if self.gross > 1e-12 else float("inf")


DEFAULT_SCREEN = ScreenParams()


def _classify(net: float, gross: float, p: ScreenParams,
              dsr: float | None, shadow_days: float | None) -> Verdict:
    if net <= 0.0:
        return Verdict.NO_TRADE                       # cost-gate: carry doesn't beat the round-trip
    cost_ratio = (gross - net) / gross if gross > 1e-12 else float("inf")
    if net < p.margin_bps or cost_ratio > p.max_cost_ratio:
        return Verdict.WATCH                          # edge too thin / costs eat too much
    if dsr is None or shadow_days is None:
        return Verdict.PAPER                          # worth shadowing; risk gates not yet evaluated
    if dsr >= 0.60 and shadow_days >= 30:
        return Verdict.LIVE_ELIGIBLE
    if dsr >= 0.60 and shadow_days >= 7:
        return Verdict.MICRO_ELIGIBLE
    return Verdict.PAPER


def screen_coin(coin: str, *, funding: float, premium: float, spread: float, vol: float,
                params: ScreenParams = DEFAULT_SCREEN, funding_pred: float | None = None,
                dsr: float | None = None, shadow_days: float | None = None) -> CarryOpportunity:
    """Score ONE coin. funding_pred defaults to funding (naive persistence) until the
    Track-C predictor exists. A short-perp carry captures premium convergence only in
    contango (premium > 0); backwardation is the long-perp side, out of scope here."""
    fpred = funding if funding_pred is None else funding_pred
    expected_funding = fpred * params.hold_hours
    expected_conv = max(premium, 0.0)
    gross = expected_funding + expected_conv
    rtc = round_trip_cost(params.fill, spread=spread, vol=vol, legs=params.legs)
    net = gross - rtc - params.liq_buffer
    verdict = _classify(net, gross, params, dsr, shadow_days)
    return CarryOpportunity(coin=coin, funding_apr=funding * HOURS_PER_YEAR,
                            expected_funding=expected_funding, expected_convergence=expected_conv,
                            round_trip_cost=rtc, net_edge=net, verdict=verdict)


def screen(candidates: Sequence[dict], params: ScreenParams = DEFAULT_SCREEN) -> list[CarryOpportunity]:
    """Screen a universe (list of dicts with coin/funding/premium/spread/vol[/dsr/shadow_days]),
    ranked by net edge. The returned list length IS the n_trials downstream DSR must use."""
    out = [screen_coin(c["coin"], funding=c["funding"], premium=c.get("premium", 0.0),
                        spread=c["spread"], vol=c["vol"], params=params,
                        funding_pred=c.get("funding_pred"), dsr=c.get("dsr"),
                        shadow_days=c.get("shadow_days"))
           for c in candidates]
    return sorted(out, key=lambda o: o.net_edge, reverse=True)
