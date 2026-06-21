"""Liquid-universe discovery (B1): the daily-volume floor and the funding ranking."""

from __future__ import annotations

import pytest

from treasuryforge.universe import liquid_candidates


def _resp():
    meta = {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "ILLIQ"}, {"name": "HOT"}]}
    ctxs = [
        {"funding": "0.00001", "markPx": "65000", "oraclePx": "65000", "dayNtlVlm": "5e8"},
        {"funding": "0.000005", "markPx": "1800", "oraclePx": "1799", "dayNtlVlm": "2e8"},
        {"funding": "0.0009", "markPx": "1", "oraclePx": "1", "dayNtlVlm": "1000"},      # illiquid
        {"funding": "0.00012", "markPx": "10", "oraclePx": "9.99", "dayNtlVlm": "2e7"},  # hot funding
    ]
    return [meta, ctxs]


def test_filters_illiquid_and_ranks_by_funding():
    rows = liquid_candidates(_resp(), min_vol_usd=5e6)
    coins = [r["coin"] for r in rows]
    assert "ILLIQ" not in coins                      # filtered out despite huge funding
    assert coins == ["HOT", "BTC", "ETH"]            # ranked by funding desc


def test_premium_computed_and_top_limit():
    rows = liquid_candidates(_resp(), min_vol_usd=5e6, top=2)
    assert len(rows) == 2 and rows[0]["coin"] == "HOT"
    assert rows[0]["premium"] == pytest.approx((10 - 9.99) / 9.99)


def test_volume_floor_can_empty_the_set():
    assert liquid_candidates(_resp(), min_vol_usd=1e12) == []


def test_volume_floor_inclusive_at_boundary():
    r = liquid_candidates([{"universe": [{"name": "A"}]},
                           [{"funding": "0.0", "markPx": "1", "oraclePx": "1", "dayNtlVlm": "5000000"}]],
                          min_vol_usd=5e6)
    assert [x["coin"] for x in r] == ["A"]                # 5e6 not < 5e6 -> kept


def test_premium_oracle_zero_guard():
    r = liquid_candidates([{"universe": [{"name": "A"}]},
                           [{"funding": "0.001", "markPx": "10", "oraclePx": "0", "dayNtlVlm": "1e7"}]],
                          min_vol_usd=5e6)
    assert r[0]["premium"] == 0.0


def test_default_min_vol_top_and_sort():
    univ = [{"name": f"C{i}"} for i in range(20)]
    ctx = [{"funding": str(i), "markPx": "1", "oraclePx": "1", "dayNtlVlm": "1e7"} for i in range(20)]
    r = liquid_candidates([{"universe": univ}, ctx])      # defaults min_vol 5e6, top 15
    assert len(r) == 15 and r[0]["coin"] == "C19" and r[0]["funding"] == 19.0


def test_default_min_vol_is_5e6_keeps_a_5e6_coin():
    # a 5e6-vol coin must survive the DEFAULT floor (kills the 5e6 -> 1e7 default mutation)
    r = liquid_candidates([{"universe": [{"name": "A"}]},
                           [{"funding": "0", "markPx": "1", "oraclePx": "1", "dayNtlVlm": "5000000"}]])
    assert [x["coin"] for x in r] == ["A"]


def test_missing_mark_defaults_to_zero():
    # oracle present, markPx MISSING -> mark defaults 0 -> premium = (0-100)/100 = -1
    r = liquid_candidates([{"universe": [{"name": "A"}]},
                           [{"funding": "0", "oraclePx": "100", "dayNtlVlm": "1e7"}]], min_vol_usd=5e6)
    assert r[0]["premium"] == pytest.approx(-1.0)


def test_oracle_guard_is_strict_gt_zero_not_one():
    # oracle = 0.5 (>0 but not >1) -> premium MUST compute (kills `oracle > 0` -> `oracle > 1`)
    r = liquid_candidates([{"universe": [{"name": "A"}]},
                           [{"funding": "0", "markPx": "1.0", "oraclePx": "0.5", "dayNtlVlm": "1e7"}]],
                          min_vol_usd=5e6)
    assert r[0]["premium"] == pytest.approx(1.0)
