"""Capital protocol hardening (Christian's cold verdict): maturity-tiered position caps,
the hard-number promotion gate, and the time-boxed loss breakers."""

from __future__ import annotations

import pytest

from treasuryforge.carry_portfolio_allocator import Candidate, allocate
from treasuryforge.loss_limits import DEFAULT as LIM
from treasuryforge.loss_limits import BreakerInput, LossLimits, check_breakers
from treasuryforge.maturity import can_advance, cap_for, next_tier, tier
from treasuryforge.promotion_gate import (
    PromotionCriteria,
    StrategyStats,
    evaluate_promotion,
)


# -- maturity tiers -------------------------------------------------------------
def test_tier_caps_ramp():
    assert cap_for("micro") == 0.02 and cap_for("small") == 0.05
    assert cap_for("normal") == 0.12 and cap_for("exceptional") == 0.20
    assert cap_for("mature") == 0.25
    assert next_tier("micro").name == "small"
    assert next_tier("mature") is None
    with pytest.raises(ValueError, match="unknown tier"):
        tier("huge")


def test_advance_needs_time_AND_volume():
    assert not can_advance("micro", days_live=20, events=10)    # events short of small's 30
    assert not can_advance("micro", days_live=5, events=50)     # days short of small's 14
    assert can_advance("micro", days_live=20, events=40)        # both met
    assert not can_advance("mature", days_live=9999, events=9999)  # top tier never advances


def test_allocator_honors_per_candidate_tier_cap():
    # a micro strategy (2% cap) and a mature one (25%), equal score
    cands = [Candidate("young", "A", 1.0, max_position=cap_for("micro")),
             Candidate("old", "B", 1.0, max_position=cap_for("mature"))]
    allocs = {a.name: a.weight for a in allocate(cands)}
    assert allocs["young"] == pytest.approx(0.02)              # capped at its micro tier
    assert allocs["old"] > allocs["young"]                     # mature can take more
    assert allocs["old"] == pytest.approx(0.25)               # but still under the global cap


def test_allocator_default_cap_unchanged_when_no_tier():
    cands = [Candidate("a", "X", 1.0), Candidate("b", "X", 1.0)]   # no max_position
    allocs = {a.name: a.weight for a in allocate(cands)}
    assert all(w <= 0.25 + 1e-9 for w in allocs.values())         # global 25% still applies


# -- promotion gate -------------------------------------------------------------
def _good() -> StrategyStats:
    return StrategyStats(dsr=0.72, net_apr=0.10, n_events=50, n_days=21, duty_cycle=0.5,
                         realized_slippage=0.0008, modeled_slippage=0.0008,
                         live_pnl=0.05, shadow_pnl=0.05, shadow_pnl_std=0.01)


def test_promotion_passes_only_when_all_gates_pass():
    d = evaluate_promotion(_good())
    assert d.promoted and d.failures == ()


def test_each_gate_can_veto():
    import dataclasses as dc
    base = _good()
    for field, bad, name in [("dsr", 0.40, "dsr"), ("net_apr", 0.0, "net_apr"),
                             ("n_events", 10, "events"), ("n_days", 3.0, "days"),
                             ("realized_slippage", 0.01, "slippage")]:
        d = evaluate_promotion(dc.replace(base, **{field: bad}))
        assert not d.promoted and name in d.failures


def test_live_worse_than_shadow_vetoes():
    base = _good()
    import dataclasses as dc
    # live far below shadow (more than 2 sigma) -> fail
    bad = dc.replace(base, live_pnl=0.05 - 3 * 0.01)
    d = evaluate_promotion(bad)
    assert "live_vs_shadow" in d.failures
    ok = dc.replace(base, live_pnl=0.05 - 1 * 0.01)               # within 2 sigma -> pass
    assert "live_vs_shadow" not in evaluate_promotion(ok).failures


def test_duty_cycle_gate_for_spread_strategies():
    crit = PromotionCriteria(min_duty_cycle=0.30)
    import dataclasses as dc
    assert evaluate_promotion(_good(), crit).checks                # has the check
    low = dc.replace(_good(), duty_cycle=0.10)
    assert "duty_cycle" in evaluate_promotion(low, crit).failures


# -- loss breakers --------------------------------------------------------------
def test_breakers_clear_when_healthy():
    s = check_breakers(BreakerInput(pnl_1d=0.01, pnl_7d=0.02, pnl_30d=0.04,
                                    days_since_kill=float("inf"), op_errors=0, live_gap=0.05))
    assert not s.halted and "CLEAR" in s.render()


def test_each_breaker_trips():
    base = dict(pnl_1d=0.0, pnl_7d=0.0, pnl_30d=0.0, days_since_kill=float("inf"),
                op_errors=0, live_gap=0.0)
    cases = [("pnl_1d", -0.03, "daily"), ("pnl_7d", -0.06, "weekly"),
             ("pnl_30d", -0.11, "monthly"), ("days_since_kill", 2.0, "cooldown"),
             ("op_errors", 3, "op errors"), ("live_gap", 0.40, "live-gap")]
    for field, val, frag in cases:
        s = check_breakers(BreakerInput(**{**base, field: val}))
        assert s.halted and any(frag in r for r in s.reasons), f"{field} should trip {frag}"


def test_breaker_boundaries_inclusive():
    # exactly at the daily limit -> halts (<=)
    s = check_breakers(BreakerInput(-LIM.max_daily_loss, 0.0, 0.0, float("inf"), 0, 0.0))
    assert s.halted
    # just inside -> clear
    s2 = check_breakers(BreakerInput(-LIM.max_daily_loss + 1e-6, 0.0, 0.0, float("inf"), 0, 0.0))
    assert not s2.halted


def test_custom_limits_and_frozen():
    import dataclasses
    lim = LossLimits(max_daily_loss=0.01)
    assert check_breakers(BreakerInput(-0.015, 0, 0, float("inf"), 0, 0), lim).halted
    with pytest.raises(dataclasses.FrozenInstanceError):
        LIM.max_daily_loss = 0.5


# -- mutation-killers: defaults, frozen, exact render, boundary inclusivity ------
def test_tier_fields_pinned():
    assert (tier("micro").min_days_live, tier("micro").min_events) == (0.0, 0)
    assert (tier("small").min_days_live, tier("small").min_events) == (14.0, 30)
    assert (tier("normal").min_days_live, tier("normal").min_events) == (60.0, 100)
    assert (tier("exceptional").min_days_live, tier("exceptional").min_events) == (120.0, 200)
    assert (tier("mature").min_days_live, tier("mature").min_events) == (240.0, 400)


def test_advance_boundary_inclusive():
    assert can_advance("micro", 14.0, 30)              # exactly small's gates -> advances (>=)
    assert not can_advance("micro", 13.99, 30)         # day just under
    assert not can_advance("micro", 14.0, 29)          # event just under


def test_tier_frozen():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        tier("micro").max_position = 0.5


def test_criteria_defaults_pinned():
    c = PromotionCriteria()
    assert (c.min_dsr, c.min_net_apr) == (0.60, 0.05)
    assert (c.min_events, c.min_days) == (30, 14.0)
    assert c.min_duty_cycle == 0.0
    assert (c.max_slippage_ratio, c.max_live_shadow_dev) == (1.5, 2.0)


def test_promotion_boundaries_inclusive():
    import dataclasses as dc
    base = _good()
    assert evaluate_promotion(dc.replace(base, dsr=0.60)).promoted               # == min_dsr
    assert evaluate_promotion(dc.replace(base, net_apr=0.05)).promoted           # == min_net_apr
    assert evaluate_promotion(dc.replace(base, n_events=30, n_days=14.0)).promoted
    assert "slippage" not in evaluate_promotion(
        dc.replace(base, realized_slippage=0.0008 * 1.5, modeled_slippage=0.0008)).failures
    assert evaluate_promotion(                                                    # live exactly at floor
        dc.replace(base, live_pnl=0.05 - 2 * 0.01, shadow_pnl=0.05, shadow_pnl_std=0.01)).promoted


def test_promotion_render_and_frozen():
    import dataclasses
    d = evaluate_promotion(_good())
    assert d.render().startswith("=== promotion gate: PROMOTE ===")
    bad = evaluate_promotion(dataclasses.replace(_good(), dsr=0.0))
    txt = bad.render()
    assert "HOLD (1 gate(s) failing)" in txt
    assert "[FAIL] dsr" in txt and "[PASS] net_apr" in txt
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.checks = ()


def test_empty_decision_not_promoted():
    from treasuryforge.promotion_gate import PromotionDecision
    assert not PromotionDecision(checks=()).promoted    # bool(checks) guard


def test_promotion_dataclasses_frozen():
    import dataclasses

    from treasuryforge.promotion_gate import GateCheck
    with pytest.raises(dataclasses.FrozenInstanceError):
        PromotionCriteria().min_dsr = 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        _good().dsr = 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        GateCheck("x", True, "d").passed = False


def test_loss_limits_defaults_pinned():
    lim = LossLimits()
    assert (lim.max_daily_loss, lim.max_weekly_loss, lim.max_monthly_loss) == (0.02, 0.05, 0.10)
    assert lim.kill_cooldown_days == 7.0
    assert lim.max_op_errors == 3 and lim.max_live_gap == 0.30


def test_loss_boundaries_inclusive_all():
    inf = float("inf")
    assert check_breakers(BreakerInput(-0.02, 0, 0, inf, 0, 0.0)).halted     # daily == (<=)
    assert check_breakers(BreakerInput(0, -0.05, 0, inf, 0, 0.0)).halted     # weekly ==
    assert check_breakers(BreakerInput(0, 0, -0.10, inf, 0, 0.0)).halted     # monthly ==
    assert not check_breakers(BreakerInput(0, 0, 0, 7.0, 0, 0.0)).halted     # cooldown == -> ok (< strict)
    assert check_breakers(BreakerInput(0, 0, 0, 6.99, 0, 0.0)).halted
    assert check_breakers(BreakerInput(0, 0, 0, inf, 3, 0.0)).halted         # op_errors == (>=)
    assert not check_breakers(BreakerInput(0, 0, 0, inf, 2, 0.0)).halted
    assert not check_breakers(BreakerInput(0, 0, 0, inf, 0, 0.30)).halted    # live_gap == -> ok (> strict)
    assert check_breakers(BreakerInput(0, 0, 0, inf, 0, 0.31)).halted


def test_breaker_render_and_frozen():
    import dataclasses

    from treasuryforge.loss_limits import BreakerState
    assert BreakerState(reasons=()).render() == "breakers: CLEAR (trading allowed)"
    s = check_breakers(BreakerInput(-0.05, 0, 0, float("inf"), 0, 0.0))
    assert s.render().startswith("breakers: HALTED -> ")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.reasons = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        BreakerInput(0, 0, 0, float("inf"), 0, 0.0).pnl_1d = 1.0     # BreakerInput frozen


def test_breaker_exact_reason_strings():
    # exact render kills the XX-wrapped reason strings + the "; " separator
    assert check_breakers(BreakerInput(-0.05, 0, 0, float("inf"), 0, 0.0)).render() == \
        "breakers: HALTED -> daily loss -5.0% <= -2%"
    assert check_breakers(BreakerInput(0, -0.06, -0.11, float("inf"), 0, 0.0)).render() == \
        "breakers: HALTED -> weekly loss -6.0% <= -5%; monthly loss -11.0% <= -10%"
    assert check_breakers(BreakerInput(0, 0, 0, 3.0, 5, 0.5)).render() == \
        "breakers: HALTED -> kill cooldown 3.0d < 7d; op errors 5 >= 3; live-gap 50% > 30%"


def test_promotion_render_details_exact():
    import dataclasses
    d = evaluate_promotion(_good())
    details = {c.name: c.detail for c in d.checks}
    assert details["dsr"] == "0.72 >= 0.60"
    assert details["net_apr"] == "+10.0% >= +5.0%"
    assert details["events"] == "50 >= 30"
    assert details["days"] == "21 >= 14"
    assert details["duty_cycle"] == "50% >= 0%"
    assert details["slippage"] == "0.0008 <= 0.0012 (modeled x1.5)"
    assert details["live_vs_shadow"] == "live +0.0500 >= shadow_floor +0.0300"
    # exact render lines kill the check-line / join / head wraps
    lines = d.render().split("\n")
    assert lines[1] == f"  [PASS] {'dsr':18} 0.72 >= 0.60"
    bad = evaluate_promotion(dataclasses.replace(_good(), dsr=0.0))
    assert bad.render().split("\n")[0] == "=== promotion gate: HOLD (1 gate(s) failing) ==="


def test_promotion_duty_cycle_boundary_inclusive():
    import dataclasses
    crit = PromotionCriteria(min_duty_cycle=0.5)
    ok = evaluate_promotion(dataclasses.replace(_good(), duty_cycle=0.5), crit)
    assert "duty_cycle" not in ok.failures                  # 0.5 >= 0.5 (kills >= -> >)
