"""MR_SCALP_ZSCORE_V1 — short-term mean-reversion candidate signal.

Christian's spec, encoded as a mechanical, testable, killable rule (no "AI guesses a
dip"). The signal computes the indicators and the ENTRY condition; the backtest owns
the position, the honest maker-fill model and the costs. Pure stdlib.

ENTRY LONG (all must hold):
  price > EMA_200 · zscore_30m <= -2.0 · RSI_14 <= 30 · spread <= 0.04%
  · return_30m > -2.0% · ATR_fast <= 2.5 * ATR_slow
EXIT (any): TP_net >= +0.25% · SL <= -0.18% · zscore_30m >= -0.5 · hold >= 10 bars
  · spread > 0.08% · policy kill   (the exit is mechanical, never "wait and see")
COST GATE: a trade is only valid if expected gross edge > fees + spread + slippage + margin.

Honest caveat (and the research's verdict): retail short-horizon mean-reversion is
real GROSS but ~0 NET after spread/fees, the dip-vs-falling-knife split is the
unsolved part, and the 97%-of-retail-day-traders-lose base rate is the prior. This
exists to be MEASURED net-of-cost and almost certainly REJECTED by the gates — which
is the point.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    o: float
    h: float
    l: float
    c: float
    v: float
    ts: int = 0


@dataclass(frozen=True)
class MrScalpParams:
    ema_period: int = 200
    window: int = 30            # VWAP / zscore / return lookback (bars)
    rsi_period: int = 14
    z_enter: float = -2.0
    rsi_enter: float = 30.0
    max_spread_in: float = 0.0004      # 0.04%
    max_spread_out: float = 0.0008     # 0.08%
    min_return_30m: float = -0.02      # -2.0%
    atr_fast: int = 5
    atr_slow: int = 120
    atr_ratio_max: float = 2.5
    tp_net: float = 0.0025             # +0.25% net target
    sl: float = -0.0018                # -0.18% stop
    z_exit: float = -0.5
    max_hold_bars: int = 10
    margin: float = 0.0003             # 0.03% required edge buffer over costs


@dataclass(frozen=True)
class Indicators:
    close: float
    ema: float
    vwap: float
    std: float
    zscore: float
    rsi: float
    atr_fast: float
    atr_slow: float
    return_w: float


class MrScalpSignal:
    """Streaming indicators + the entry test. Feed 1m bars via update()."""

    def __init__(self, params: MrScalpParams) -> None:
        self.p = params
        self._ema: float | None = None
        self._a = 2.0 / (params.ema_period + 1)
        self._closes: deque[float] = deque(maxlen=params.window + 1)
        self._tp_vol: deque[tuple[float, float]] = deque(maxlen=params.window)   # (typical, vol)
        self._tr: deque[float] = deque(maxlen=params.atr_slow)
        self._prev_close: float | None = None
        # Wilder RSI state
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._rsi_n = 0
        self._ind: Indicators | None = None

    @property
    def ready(self) -> bool:
        return self._ind is not None

    @property
    def ind(self) -> Indicators | None:
        return self._ind

    def update(self, bar: Bar) -> None:
        p = self.p
        # EMA
        self._ema = bar.c if self._ema is None else (self._a * bar.c + (1 - self._a) * self._ema)
        # RSI (Wilder)
        if self._prev_close is not None:
            ch = bar.c - self._prev_close
            gain, loss = max(ch, 0.0), max(-ch, 0.0)
            if self._rsi_n < p.rsi_period:
                self._avg_gain += gain
                self._avg_loss += loss
                self._rsi_n += 1
                if self._rsi_n == p.rsi_period:
                    self._avg_gain /= p.rsi_period
                    self._avg_loss /= p.rsi_period
            else:
                self._avg_gain = (self._avg_gain * (p.rsi_period - 1) + gain) / p.rsi_period
                self._avg_loss = (self._avg_loss * (p.rsi_period - 1) + loss) / p.rsi_period
        # True range
        tr = bar.h - bar.l if self._prev_close is None else max(
            bar.h - bar.l, abs(bar.h - self._prev_close), abs(bar.l - self._prev_close))
        self._tr.append(tr)
        # rolling windows
        self._closes.append(bar.c)
        self._tp_vol.append(((bar.h + bar.l + bar.c) / 3.0, bar.v))
        self._prev_close = bar.c
        self._ind = self._compute(bar.c)

    def _compute(self, close: float) -> Indicators | None:
        p = self.p
        if (len(self._closes) <= p.window or len(self._tr) < p.atr_slow
                or self._rsi_n < p.rsi_period or self._ema is None):
            return None
        win = list(self._closes)[-p.window:]
        mean = sum(win) / p.window
        var = sum((x - mean) ** 2 for x in win) / p.window
        std = math.sqrt(var) if var > 0 else 0.0
        num = sum(tp * v for tp, v in self._tp_vol)
        den = sum(v for _, v in self._tp_vol)
        vwap = num / den if den > 0 else mean
        z = (close - vwap) / std if std > 0 else 0.0
        rs = self._avg_gain / self._avg_loss if self._avg_loss > 0 else math.inf
        rsi = 100.0 - 100.0 / (1.0 + rs)
        trs = list(self._tr)
        atr_fast = sum(trs[-p.atr_fast:]) / p.atr_fast
        atr_slow = sum(trs[-p.atr_slow:]) / p.atr_slow
        close_w_ago = self._closes[0]
        ret_w = (close - close_w_ago) / close_w_ago if close_w_ago > 0 else 0.0
        return Indicators(close, self._ema, vwap, std, z, rsi, atr_fast, atr_slow, ret_w)

    def entry_ok(self, spread: float) -> bool:
        """All entry rules. `spread` is the current fractional bid-ask spread."""
        i = self._ind
        if i is None:
            return False
        return (
            i.close > i.ema                              # 1. not fading a downtrend
            and i.zscore <= self.p.z_enter               # 2. "is low"
            and i.rsi <= self.p.rsi_enter                # 3. oversold confirmation
            and spread <= self.p.max_spread_in           # 4. spread won't eat the trade
            and i.return_w > self.p.min_return_30m       # 5. not a falling knife
            and i.atr_fast <= self.p.atr_ratio_max * i.atr_slow   # 6. no crash/anomaly
        )
