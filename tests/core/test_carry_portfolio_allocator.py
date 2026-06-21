"""Carry portfolio allocator (v2 P10): per-position / per-cluster / total caps, and the
'correlated bets share one budget' rule."""

from __future__ import annotations

import pytest

from treasuryforge.carry_portfolio_allocator import (
    Allocation,
    AllocatorCaps,
    Candidate,
    allocate,
)


def test_proportional_to_score_when_uncapped():
    cs = [Candidate("A", "clA", 0.10), Candidate("B", "clB", 0.30)]
    caps = AllocatorCaps(max_per_position=1.0, max_per_cluster=1.0, max_total=1.0)
    a = {x.name: x.weight for x in allocate(cs, caps)}
    assert a["B"] == pytest.approx(0.75) and a["A"] == pytest.approx(0.25)   # 0.3 vs 0.1


def test_per_position_cap_binds():
    cs = [Candidate("A", "clA", 0.9), Candidate("B", "clB", 0.1)]
    a = {x.name: x.weight for x in allocate(cs, AllocatorCaps(max_per_position=0.25))}
    assert a["A"] == pytest.approx(0.25)                 # capped despite the huge score


def test_correlated_cluster_shares_one_budget():
    # three spreads all in the SAME cluster (e.g. HL outlier) -> capped as ONE bet
    cs = [Candidate("X", "HL_outlier", 0.2), Candidate("Y", "HL_outlier", 0.2),
          Candidate("Z", "HL_outlier", 0.2)]
    allocs = allocate(cs, AllocatorCaps(max_per_position=0.25, max_per_cluster=0.40))
    cluster_total = sum(x.weight for x in allocs)
    assert cluster_total == pytest.approx(0.40)          # the whole cluster <= 40%, not 75%


def test_total_cap_binds_across_clusters():
    cs = [Candidate("A", "c1", 0.3), Candidate("B", "c2", 0.3), Candidate("C", "c3", 0.3)]
    allocs = allocate(cs, AllocatorCaps(max_per_position=0.5, max_per_cluster=0.5, max_total=0.6))
    assert sum(x.weight for x in allocs) == pytest.approx(0.6)


def test_negative_scores_are_dropped():
    cs = [Candidate("A", "c1", 0.2), Candidate("B", "c2", -0.1)]
    names = {x.name for x in allocate(cs)}
    assert names == {"A"}


def test_marginal_risk_contribution_is_the_weight():
    a = Allocation("A", "c1", 0.18)
    assert a.marginal_risk_contribution == 0.18


def test_empty_when_nothing_positive():
    assert allocate([Candidate("A", "c1", -1.0)]) == []


# -- mutation-killers: defaults, frozen, score>0, exact cluster scaling ----------
def test_caps_defaults_and_frozen():
    import dataclasses
    c = AllocatorCaps()
    assert (c.max_per_position, c.max_per_cluster, c.max_total) == (0.25, 0.40, 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.max_total = 5.0


def test_candidate_and_allocation_frozen():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        Candidate("a", "X", 1.0).score = 2.0
    a = allocate([Candidate("a", "X", 1.0)])[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.weight = 0.5


def test_zero_score_excluded():
    allocs = allocate([Candidate("a", "X", 1.0), Candidate("z", "X", 0.0)])
    assert {a.name for a in allocs} == {"a"}             # score > 0 strict (kills >=)


def test_cluster_cap_scales_members_together():
    cands = [Candidate("a", "CL", 1.0), Candidate("b", "CL", 1.0)]   # same cluster
    allocs = {a.name: a.weight for a in allocate(cands)}
    # step1 each min(0.25, 0.5)=0.25; cluster sum 0.5 > 0.40 -> scale 0.8 -> 0.20 each
    assert allocs["a"] == pytest.approx(0.20) and allocs["b"] == pytest.approx(0.20)
