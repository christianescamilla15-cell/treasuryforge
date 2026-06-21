"""MR_SCALP_ZSCORE_V1 signal — indicators warm-up and the entry rules. Each entry
rule is exercised in isolation by injecting a crafted Indicators snapshot, so a
flipped comparison or threshold is caught."""

from __future__ import annotations

from dataclasses import replace

import pytest

from treasuryforge.signals.mr_scalp import Bar, Indicators, MrScalpParams, MrScalpSignal


def _ok_ind() -> Indicators:
    # a snapshot that passes EVERY entry rule
    return Indicators(close=100.0, ema=99.0, vwap=103.0, std=1.0, zscore=-3.0,
                      rsi=25.0, atr_fast=1.0, atr_slow=1.0, return_w=-0.005)


def test_all_rules_pass():
    s = MrScalpSignal(MrScalpParams())
    s._ind = _ok_ind()
    assert s.entry_ok(spread=0.0003)


def test_each_rule_blocks_entry():
    s = MrScalpSignal(MrScalpParams())
    base = _ok_ind()
    s._ind = replace(base, ema=101.0)          # close 100 < ema -> fading a downtrend
    assert not s.entry_ok(0.0003)
    s._ind = replace(base, zscore=-1.0)         # z > -2 -> not "low" enough
    assert not s.entry_ok(0.0003)
    s._ind = replace(base, rsi=45.0)            # rsi > 30 -> not oversold
    assert not s.entry_ok(0.0003)
    s._ind = base
    assert not s.entry_ok(spread=0.001)         # spread too wide
    s._ind = replace(base, return_w=-0.03)      # < -2% -> falling knife
    assert not s.entry_ok(0.0003)
    s._ind = replace(base, atr_fast=3.0, atr_slow=1.0)   # 3 > 2.5x1 -> crash/anomaly
    assert not s.entry_ok(0.0003)


def test_boundaries_are_inclusive_where_specified():
    s = MrScalpSignal(MrScalpParams())
    base = _ok_ind()
    s._ind = replace(base, zscore=-2.0)         # == z_enter -> still enters (<=)
    assert s.entry_ok(0.0003)
    s._ind = replace(base, rsi=30.0)            # == rsi_enter -> enters (<=)
    assert s.entry_ok(0.0003)
    s._ind = replace(base, atr_fast=2.5, atr_slow=1.0)   # == 2.5x -> enters (<=)
    assert s.entry_ok(0.0003)
    s._ind = base
    assert s.entry_ok(spread=0.0004)            # == max_spread_in -> enters (<=)
    assert not s.entry_ok(spread=0.00041)       # just over -> blocked


def test_not_ready_means_no_entry():
    s = MrScalpSignal(MrScalpParams())
    assert not s.ready and not s.entry_ok(0.0003)
    s.update(Bar(100, 100, 100, 100, 1.0, 0))   # one bar: still warming up
    assert not s.ready


def test_warms_up_and_ema_tracks_constant_price():
    p = MrScalpParams()
    s = MrScalpSignal(p)
    for i in range(p.atr_slow + p.window + 5):
        s.update(Bar(100, 100, 100, 100, 1.0, i))
    assert s.ready
    ind = s.ind
    assert ind.ema == pytest.approx(100.0) and ind.vwap == pytest.approx(100.0)   # constant price
    assert ind.zscore == 0.0 and ind.rsi == 100.0      # no variance, no losses
    assert not s.entry_ok(0.0003)                       # flat market -> close not > ema


def test_ema_recursion_on_a_step():
    s = MrScalpSignal(MrScalpParams(ema_period=4))      # alpha = 2/5 = 0.4
    s.update(Bar(10, 10, 10, 10, 1, 0))
    s.update(Bar(20, 20, 20, 20, 1, 1))
    assert s._ema == 0.4 * 20 + 0.6 * 10                # 14.0


# -- mutation-killing: exercise the FULL streaming computation -------------------
def _feed(s, rows):
    for i, (o, h, low, c, v) in enumerate(rows):
        s.update(Bar(o, h, low, c, v, i))


def _warm_params():
    return MrScalpParams(ema_period=4, window=3, rsi_period=2, atr_fast=2, atr_slow=3)


def test_streaming_return_w_exact():
    s = MrScalpSignal(_warm_params())
    _feed(s, [(10, 10, 10, 10, 1), (10, 11, 9, 11, 2), (11, 12, 10, 12, 1),
              (12, 13, 11, 13, 3), (13, 14, 12, 14, 2), (14, 15, 13, 15, 4)])
    ind = s.ind
    assert ind is not None and ind.close == 15.0
    assert ind.return_w == pytest.approx((15.0 - 12.0) / 12.0)   # closes deque [12,13,14,15]


def test_streaming_rsi_all_up_is_100_then_drops():
    s = MrScalpSignal(_warm_params())
    _feed(s, [(10, 10, 10, 10, 1), (11, 11, 11, 11, 1), (12, 12, 12, 12, 1),
              (13, 13, 13, 13, 1), (14, 14, 14, 14, 1), (15, 15, 15, 15, 1)])
    assert s.ind.rsi == 100.0                                    # only gains -> avg_loss 0
    s.update(Bar(14, 14, 14, 14, 1, 6))                          # a down move
    assert s.ind.rsi < 100.0                                     # avg_loss > 0 now


def test_streaming_vwap_volume_weighted():
    s = MrScalpSignal(_warm_params())
    _feed(s, [(10, 10, 10, 10, 1), (20, 20, 20, 20, 1), (20, 20, 20, 20, 1),
              (20, 20, 20, 20, 1), (10, 10, 10, 10, 100), (20, 20, 20, 20, 1)])
    assert s.ind.vwap < 15.0                                     # huge-volume 10-bar pulls vwap down


def test_streaming_zscore_negative_below_mean():
    s = MrScalpSignal(_warm_params())
    _feed(s, [(10, 10, 10, 10, 1), (10, 11, 9, 11, 1), (11, 12, 10, 12, 1),
              (12, 13, 11, 13, 1), (13, 14, 12, 13, 1), (9, 9, 9, 9, 1)])
    assert s.ind.zscore < 0.0                                    # last close well below recent vwap


def test_streaming_atr_reflects_true_range():
    s = MrScalpSignal(_warm_params())
    _feed(s, [(10, 10, 10, 10, 1), (10, 11, 9, 10, 1), (10, 11, 9, 10, 1),
              (10, 11, 9, 10, 1), (10, 11, 9, 10, 1), (10, 11, 9, 10, 1)])
    assert s.ind.atr_fast == pytest.approx(2.0) and s.ind.atr_slow == pytest.approx(2.0)  # range 11-9


def test_full_indicator_chain_exact_values():
    # Hand-computed over closes [10,11,10,12,11,13] with rsi_period=2 (Wilder), window=3.
    # This pins the ENTIRE Wilder warm-up + smoothing chain, the variance/std formula,
    # the volume-weighted vwap and the zscore divisor -- killing the arithmetic mutants
    # that a constant/monotonic series leaves equivalent.
    s = MrScalpSignal(_warm_params())                     # window=3, rsi_period=2, atr_fast=2, atr_slow=3
    _feed(s, [(10, 10, 10, 10, 1), (11, 11, 11, 11, 1), (10, 10, 10, 10, 1),
              (12, 12, 12, 12, 1), (11, 11, 11, 11, 1), (13, 13, 13, 13, 1)])
    i = s.ind
    assert i is not None and i.close == 13.0
    # RSI: warm-up avg_gain=avg_loss=0.5 at bar3, smoothing -> 1.3125 / 0.3125 = rs 4.2
    assert i.rsi == pytest.approx(100.0 - 100.0 / 5.2)    # 80.76923...
    # last window of closes is [12,11,13]: mean 12, var (0+1+1)/3 = 2/3 (strictly 0<var<1)
    assert i.std == pytest.approx((2.0 / 3.0) ** 0.5)     # kills (x+mean), *2, /window->*window, var>1
    assert 0.0 < i.std < 1.0
    assert i.vwap == pytest.approx(12.0)                  # h=l=c, equal volume -> simple mean of typicals
    assert i.zscore == pytest.approx((13.0 - 12.0) / (2.0 / 3.0) ** 0.5)   # (close-vwap)/std, > 0
    # tr last 3 = |12-10|,|11-12|,|13-11| = [2,1,2]; fast=last2 mean 1.5, slow=mean 5/3
    assert i.atr_fast == pytest.approx(1.5) and i.atr_slow == pytest.approx(5.0 / 3.0)


def test_param_defaults_are_pinned():
    # the spec's thresholds: a flipped/None default would silently change the signal
    p = MrScalpParams()
    assert (p.ema_period, p.window, p.rsi_period) == (200, 30, 14)
    assert (p.z_enter, p.rsi_enter) == (-2.0, 30.0)
    assert (p.max_spread_in, p.max_spread_out) == (0.0004, 0.0008)
    assert p.min_return_30m == -0.02
    assert (p.atr_fast, p.atr_slow, p.atr_ratio_max) == (5, 120, 2.5)
    assert (p.tp_net, p.sl) == (0.0025, -0.0018)
    assert (p.z_exit, p.max_hold_bars, p.margin) == (-0.5, 10, 0.0003)
    assert Bar(1, 2, 0, 1, 1).ts == 0                  # Bar ts default


def test_frozen_dataclasses():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        Bar(1, 1, 1, 1, 1).c = 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        MrScalpParams().z_enter = 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        _ok_ind().rsi = 50.0


def test_entry_strict_and_inclusive_boundaries():
    s = MrScalpSignal(MrScalpParams())
    base = _ok_ind()
    s._ind = replace(base, close=99.0, ema=99.0)          # close == ema -> NOT > -> blocked (strict)
    assert not s.entry_ok(0.0003)
    s._ind = replace(base, return_w=-0.02)                # == min_return_30m -> NOT > -> blocked
    assert not s.entry_ok(0.0003)
    s._ind = replace(base, atr_fast=3.0, atr_slow=2.0)    # 3 <= 2.5*2=5 enter (kills * -> /)
    assert s.entry_ok(0.0003)


def test_ready_guard_needs_more_than_window_closes():
    # exactly `window` closes + enough tr/rsi -> still NOT ready (kills <= -> <)
    s = MrScalpSignal(_warm_params())                     # window=3, atr_slow=3, rsi_period=2
    _feed(s, [(10, 11, 9, 10, 1), (11, 12, 10, 11, 1), (12, 13, 11, 12, 1)])
    assert not s.ready                                    # len(closes)==window=3 -> None
    s.update(Bar(13, 14, 12, 13, 1, 3))                  # 4th -> len 4 > window
    assert s.ready


def test_vwap_is_volume_weighted_exact():
    # distinct volumes in the last window -> kills tp*v -> tp/v
    s = MrScalpSignal(_warm_params())                     # window=3
    _feed(s, [(10, 10, 10, 10, 1), (10, 10, 10, 10, 1), (10, 10, 10, 10, 1),
              (20, 20, 20, 20, 1), (30, 30, 30, 30, 2), (40, 40, 40, 40, 3)])
    # last window tp_vol = [(20,1),(30,2),(40,3)] -> (20+60+120)/6 = 200/6
    assert s.ind.vwap == pytest.approx(200.0 / 6.0)
