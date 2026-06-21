"""Honest backtest for MR_SCALP_ZSCORE_V1 — built to KILL it cleanly, net of cost.

Christian's five mandatory punishments are all modeled head-on:

  1. Conservative maker fill — a limit buy at best_bid fills ONLY if the next bar's
     low <= bid; a maker take-profit fills ONLY if a later high >= target. No magic.
  2. No same-candle fantasy — the signal is computed on the CLOSED bar t; the order
     can only fill on bar t+1; a freshly-filled position is not exit-checked on its
     fill bar; and if stop and target are both touched in one bar, the STOP is
     assumed first (worst case).
  3. (Cost regimes — optimistic/base/stressed — are swept by the runner.)
  4. Adverse selection, explicit — post-fill drift, missed-rebound rate, and the
     filled-losers vs missed-winners pattern (the market-maker's curse).
  5. Frequency / edge accounting — trades/day, gross vs net edge per trade,
     cost/trade, and the gross-edge/cost ratio (must exceed 2 to be worth anything).

Cost gate: enter only when the expected snap-back to VWAP exceeds round-trip cost +
margin, so a high-cost venue never trades and a cheap one gets to prove or disprove.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..signals.mr_scalp import Bar, MrScalpParams, MrScalpSignal

BARS_PER_DAY = 1440      # 1-minute bars


@dataclass(frozen=True)
class CostModel:
    maker_fee: float = 0.00015
    taker_fee: float = 0.00045
    spread: float = 0.0003
    slippage: float = 0.0002

    @property
    def round_trip_estimate(self) -> float:
        return 2 * self.taker_fee + self.spread + 2 * self.slippage


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    bars_held: int
    reason: str
    ret: float           # net fractional return
    gross: float         # gross fractional return (no fees/slippage)


@dataclass
class MrScalpResult:
    trades: list[Trade] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)       # net per-trade
    n_bars: int = 0
    n_signaled: int = 0          # entry conditions met
    n_cost_skipped: int = 0      # killed by the cost gate
    n_placed: int = 0            # maker orders rested
    n_filled: int = 0            # maker orders that filled (adverse selection)
    n_missed: int = 0            # rested but never filled (price bounced)
    missed_winners: int = 0      # missed orders that WOULD have hit TP within hold
    post_fill_drift: float = 0.0 # avg signed drift after fill (negative = adverse)

    @property
    def net_return(self) -> float:
        eq = 1.0
        for r in self.returns:
            eq *= (1.0 + r)
        return eq - 1.0

    @property
    def win_rate(self) -> float:
        return sum(1 for r in self.returns if r > 0) / len(self.returns) if self.returns else 0.0

    @property
    def filled_losers(self) -> int:
        return sum(1 for t in self.trades if t.ret <= 0)

    @property
    def missed_rebound_rate(self) -> float:
        return self.missed_winners / self.n_missed if self.n_missed else 0.0

    @property
    def avg_gross(self) -> float:
        return sum(t.gross for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def avg_net(self) -> float:
        return sum(self.returns) / len(self.returns) if self.returns else 0.0

    @property
    def cost_per_trade(self) -> float:
        return self.avg_gross - self.avg_net

    @property
    def edge_cost_ratio(self) -> float:
        return abs(self.avg_gross) / self.cost_per_trade if self.cost_per_trade > 0 else 0.0

    @property
    def trades_per_day(self) -> float:
        return len(self.trades) * BARS_PER_DAY / self.n_bars if self.n_bars else 0.0

    @property
    def avg_hold(self) -> float:
        return sum(t.bars_held for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def maker_fill_rate(self) -> float:
        return self.n_filled / self.n_placed if self.n_placed else 0.0


def backtest_mr_scalp(bars: list[Bar], params: MrScalpParams, cost: CostModel) -> MrScalpResult:
    sig = MrScalpSignal(params)
    res = MrScalpResult()
    pending_bid: float | None = None     # maker buy resting for THIS bar (placed on the prev)
    pos: dict | None = None
    drifts: list[float] = []
    n = len(bars)

    for i, bar in enumerate(bars):
        res.n_bars += 1

        # 1. EXITS first — only for a position opened on a PREVIOUS bar (no same-candle)
        if pos is not None:
            pos["bars"] += 1
            entry = pos["entry"]
            tp = entry * (1.0 + params.tp_net + 2 * cost.maker_fee)
            sl = entry * (1.0 + params.sl)
            px: float | None = None
            reason = ""
            ef = cost.taker_fee
            cur = sig.ind                                    # indicators as of the prior close
            if bar.l <= sl:                                  # STOP assumed first (worst case)
                px, reason = sl * (1 - cost.slippage), "SL"
            elif bar.h >= tp:                                # maker take-profit
                px, reason, ef = tp, "TP", cost.maker_fee
            elif cur is not None and cur.zscore >= params.z_exit:
                px, reason = bar.c * (1 - cost.slippage), "ZEXIT"
            elif pos["bars"] >= params.max_hold_bars:
                px, reason = bar.c * (1 - cost.slippage), "TIME"
            if px is not None:
                gross = (px - entry) / entry
                net = (px * (1 - ef)) / (entry * (1 + cost.maker_fee)) - 1.0
                res.trades.append(Trade(pos["ts"], bar.ts, entry, px, pos["bars"], reason, net, gross))
                res.returns.append(net)
                pos = None

        # 2. resolve a resting maker buy against THIS bar (adverse selection)
        if pos is None and pending_bid is not None:
            if bar.l <= pending_bid:                         # filled: price traded down to us
                pos = {"ts": bar.ts, "entry": pending_bid, "bars": 0}
                res.n_filled += 1
                k = min(i + params.max_hold_bars, n - 1)     # post-fill drift over the hold window
                drifts.append((bars[k].c - pending_bid) / pending_bid)
            else:                                            # missed: price bounced past our bid
                res.n_missed += 1
                hi = max((bars[j].h for j in range(i, min(i + params.max_hold_bars, n))),
                         default=pending_bid)
                if hi >= pending_bid * (1.0 + params.tp_net):   # would have hit TP -> a missed winner
                    res.missed_winners += 1
            pending_bid = None                               # 15s timeout -> cancel if unfilled

        # 3. indicators update with the now-closed bar
        sig.update(bar)

        # 4. flat + signal -> rest a maker buy for the NEXT bar (cost-gated)
        ind = sig.ind
        if pos is None and pending_bid is None and ind is not None and sig.entry_ok(cost.spread):
            res.n_signaled += 1
            expected_snapback = (ind.vwap - ind.close) / ind.close
            if expected_snapback > cost.round_trip_estimate + params.margin:
                pending_bid = bar.c * (1.0 - cost.spread / 2.0)
                res.n_placed += 1
            else:
                res.n_cost_skipped += 1

    res.post_fill_drift = sum(drifts) / len(drifts) if drifts else 0.0
    return res
