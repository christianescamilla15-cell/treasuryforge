"""Cross-venue carry economics (Roadmap v2 P1) — the QUEEN metric.

The fatal error is "spread 30% APR -> I earn 30%". No. A delta-neutral cross-venue
position needs collateral on BOTH venues (~2x capital), pays fees/slippage on 4 legs,
an ongoing hedge-rebalance cost, a one-time transfer, a liquidation buffer, and an
orphan-leg risk premium (the two exchanges are NOT atomic). So the honest return is
the net funding amortised over the hold, divided by the TOTAL locked capital — and
then scaled by the opportunity duty cycle (how much of the time the spread is even on).

    net_apr_on_total_capital = (spread - amortised_trade_cost - hedge - orphan_premium)
                               / (2/leverage * (1 + liq_buffer))

That ~30% gross can become single-digit on capital. This module makes that explicit so
no one deploys on a gross number. Pure, stdlib, offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

HOURS_PER_YEAR = 24 * 365


@dataclass(frozen=True)
class CrossVenueParams:
    fee_per_leg: float = 0.00045        # taker fee each leg (cross-venue: no held-spot overlay)
    slippage_per_leg: float = 0.0002
    legs: int = 4                       # two perps, open + close
    hedge_rebalance_apr: float = 0.01   # ongoing cost of keeping the pair delta-neutral
    transfer_friction: float = 0.0010   # one-time, moving capital in/out across venues
    orphan_leg_premium_apr: float = 0.02  # risk premium for non-atomic two-exchange execution
    leverage: float = 2.0               # margin leverage per venue
    liq_buffer_frac: float = 0.5        # extra margin held to survive price gaps
    # --- frictions Christian enumerated (the "cold verdict" cost stack) ---------
    # Drags on the funding actually CAPTURED (notional level):
    funding_settlement_drag_apr: float = 0.005   # HL pays hourly, OKX every 8h -> timing slip
    downtime_haircut_apr: float = 0.005          # relay/system down -> missed/late funding
    # Drags on the TOTAL LOCKED CAPITAL (capital level, not notional):
    opportunity_cost_apr: float = 0.04           # risk-free yield (T-bills) foregone on locked capital
    exchange_risk_apr: float = 0.01              # tail premium: venue freeze/insolvency on locked funds
    transfer_delay_days: float = 1.0             # capital in transit -> opportunity cost during the move


DEFAULT = CrossVenueParams()


@dataclass(frozen=True)
class CrossVenueEconomics:
    gross_spread_apr: float
    amortised_trade_cost_apr: float     # round-trip + transfer, spread over the hold
    notional_drag_apr: float            # hedge + orphan + settlement + downtime (notional level)
    capital_drag_apr: float             # (opportunity + exchange-risk) x locked_ratio (capital level)
    net_funding_apr_on_notional: float  # what the NOTIONAL earns net (still not the answer)
    total_locked_ratio: float           # total capital / notional (>= 1; ~1.5 typical)
    net_apr_on_total_capital: float     # THE queen metric
    breakeven_hold_hours: float

    def effective_apr(self, duty_cycle: float) -> float:
        """Net APR on capital scaled by the share of time the spread is actually on."""
        return self.net_apr_on_total_capital * duty_cycle

    @property
    def is_deployable(self) -> bool:
        return self.net_apr_on_total_capital > 0.0


def _amortised(hold_hours: float, params: CrossVenueParams) -> tuple[float, float]:
    """(one_time_cost, amortised_apr). one_time includes the opportunity cost of capital
    sitting in transit between venues (transfer_delay_days at the risk-free rate)."""
    round_trip = params.legs * (params.fee_per_leg + params.slippage_per_leg)
    transit_opp = params.transfer_delay_days / 365.0 * params.opportunity_cost_apr
    one_time = round_trip + params.transfer_friction + transit_opp
    hold_years = hold_hours / HOURS_PER_YEAR
    amortised = one_time / hold_years if hold_years > 0 else float("inf")
    return one_time, amortised


def _notional_drag(params: CrossVenueParams) -> float:
    return (params.hedge_rebalance_apr + params.orphan_leg_premium_apr
            + params.funding_settlement_drag_apr + params.downtime_haircut_apr)


def _locked_ratio(params: CrossVenueParams) -> float:
    # collateral on BOTH venues: 2 x (notional / leverage), plus a liquidation buffer
    return 2.0 / params.leverage * (1.0 + params.liq_buffer_frac)


def _capital_drag(params: CrossVenueParams) -> float:
    # risk-free foregone + venue tail risk, charged on the WHOLE locked capital
    return (params.opportunity_cost_apr + params.exchange_risk_apr) * _locked_ratio(params)


def breakeven_spread_apr(hold_hours: float, params: CrossVenueParams = DEFAULT) -> float:
    """The gross spread APR at which the QUEEN metric (net APR on total locked capital)
    is exactly zero. Solving net_on_capital = 0 for spread gives:
        spread = amortised + notional_drag + capital_drag * locked_ratio
    This is the HONEST floor a spread must clear to net anything -- materially higher than
    the old fees-only floor, because capital sits idle (opportunity cost) and at risk."""
    _, amortised = _amortised(hold_hours, params)
    return amortised + _notional_drag(params) + _capital_drag(params) * _locked_ratio(params)


def cross_venue_economics(spread_apr: float, *, hold_hours: float,
                          params: CrossVenueParams = DEFAULT) -> CrossVenueEconomics:
    one_time, amortised = _amortised(hold_hours, params)
    notional_drag = _notional_drag(params)
    net_funding = spread_apr - amortised - notional_drag
    total_locked_ratio = _locked_ratio(params)
    capital_drag = _capital_drag(params)
    # funding earned per unit of capital, MINUS the per-capital frictions (opportunity, tail)
    net_on_capital = net_funding / total_locked_ratio - capital_drag
    breakeven_hold_hours = (one_time / (spread_apr / HOURS_PER_YEAR)
                            if spread_apr > 0 else float("inf"))
    return CrossVenueEconomics(
        gross_spread_apr=spread_apr, amortised_trade_cost_apr=amortised,
        notional_drag_apr=notional_drag, capital_drag_apr=capital_drag,
        net_funding_apr_on_notional=net_funding, total_locked_ratio=total_locked_ratio,
        net_apr_on_total_capital=net_on_capital, breakeven_hold_hours=breakeven_hold_hours)
