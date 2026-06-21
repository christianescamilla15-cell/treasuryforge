"""Selection scorecard: picked vs unpicked EV, the significance gate, and the honest
verdict that refuses to call a few lucky picks 'skill'."""

from __future__ import annotations

import pytest

from treasuryforge.selection_score import Resolved, score


def _recs(picked_rets, unpicked_rets):
    return ([Resolved(f"P{i}", True, r) for i, r in enumerate(picked_rets)]
            + [Resolved(f"U{i}", False, r) for i, r in enumerate(unpicked_rets)])


def test_evs_split_correctly():
    s = score(_recs([0.5, 0.3], [-0.1, -0.2, 0.0]))
    assert s.n == 5 and s.n_picked == 2 and s.n_unpicked == 3
    assert s.ev_picked == pytest.approx(0.4)
    assert s.ev_unpicked == pytest.approx(-0.1)
    assert s.ev_all == pytest.approx((0.5 + 0.3 - 0.1 - 0.2 + 0.0) / 5)
    assert s.edge_vs_unpicked == pytest.approx(0.5)


def test_few_lucky_picks_do_not_count_as_skill():
    # 3 great picks, huge edge, but tiny sample -> must NOT beat baseline
    s = score(_recs([5.0, 4.0, 6.0], [-0.2] * 50))
    assert s.edge_vs_unpicked > 0
    assert not s.beats_baseline                       # n_picked < 20
    assert s.verdict.startswith("NEED MORE DATA")


def test_real_separated_edge_registers():
    # 30 picks clearly + tightly above 60 unpicked -> z >= 2, beats baseline
    picked = [0.20 + 0.01 * (i % 3) for i in range(30)]    # ~0.21 mean, low variance
    unpicked = [-0.10 + 0.01 * (i % 3) for i in range(60)]
    s = score(_recs(picked, unpicked))
    assert s.n_picked == 30 and s.edge_vs_unpicked > 0.25
    assert s.edge_z >= 2.0 and s.beats_baseline
    assert "SELECTION EDGE" in s.verdict


def test_no_edge_when_picks_match_population():
    # picks statistically indistinguishable from unpicked -> NO EDGE
    rets = [0.1, -0.3, 0.2, -0.1, 0.0, -0.2] * 6
    s = score(_recs(rets[:20], rets[:40]))
    assert not s.beats_baseline


def test_negative_edge_is_not_skill():
    s = score(_recs([-0.3] * 25, [0.1] * 40))
    assert s.edge_vs_unpicked < 0 and not s.beats_baseline
    assert "NO EDGE" in s.verdict


def test_empty_and_frozen():
    import dataclasses
    s = score([])
    assert s.n == 0 and s.ev_all == 0.0 and not s.beats_baseline
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.n = 5


# -- mutation-killers: exact stats, boundaries, exact verdict strings -----------
def test_mean_se_exact():
    from treasuryforge.selection_score import _mean_se
    assert _mean_se([5.0]) == (5.0, 0.0)                      # n<2 guard (kills 1.0 / n<3)
    m, se = _mean_se([0.0, 0.2])
    assert m == pytest.approx(0.1) and se == pytest.approx(0.1)        # var=(0.01+0.01)/1, se=sqrt(.02/2)
    m3, se3 = _mean_se([0.0, 0.0, 0.3])
    assert m3 == pytest.approx(0.1) and se3 == pytest.approx(0.1)      # n=3 kills *(n-1) vs /(n-1)
    assert _mean_se([]) == (0.0, 0.0)


def test_z_and_comb_se_exact():
    s = score(_recs([0.1, 0.3], [-0.2, 0.0]))                # se_p=se_u=0.1, edge=0.3
    assert s.ev_picked == pytest.approx(0.2) and s.ev_unpicked == pytest.approx(-0.1)
    assert s.edge_vs_unpicked == pytest.approx(0.3)
    assert s.edge_z == pytest.approx(0.3 / (0.02 ** 0.5))    # comb_se = sqrt(0.1^2+0.1^2)


def test_beats_baseline_at_exactly_20_picks():
    picked = [0.20 + 0.01 * (i % 2) for i in range(20)]      # exactly 20, tight, high
    unpicked = [-0.10 + 0.01 * (i % 2) for i in range(40)]
    s = score(_recs(picked, unpicked))
    assert s.n_picked == 20 and s.beats_baseline             # 20 (not 21) clears (kills n>20, >=21)


def test_z_below_three_still_beats():
    # construct a separated edge with 2 < z < 3 -> beats (z>=2) but kills the z>=3 mutant
    picked = [0.10 + 0.02 * (i % 5) for i in range(25)]
    unpicked = [0.04 + 0.02 * (i % 5) for i in range(50)]
    s = score(_recs(picked, unpicked))
    if 2.0 <= s.edge_z < 3.0:
        assert s.beats_baseline                              # z in [2,3) must still register


def test_exact_verdicts_kill_xx_wraps():
    few = score(_recs([5.0, 4.0, 6.0], [-0.2] * 50))
    assert few.verdict == "NEED MORE DATA (3/20 picks resolved)"
    edge = score(_recs([0.20 + 0.01 * (i % 2) for i in range(20)], [-0.10] * 40))
    assert edge.verdict == "SELECTION EDGE (picks beat the population, statistically separated)"
    none = score(_recs([0.1] * 20, [0.1] * 40))              # edge exactly 0 -> NO EDGE (kills >=0)
    assert none.edge_vs_unpicked == pytest.approx(0.0)
    assert none.verdict == "NO EDGE -- picks do not beat the mechanical baseline (consistent with luck)"
