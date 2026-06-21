"""Funding persistence (Track C baseline): episode detection under hysteresis,
duration stats, break-even share, and right-censoring of an open final episode."""

from __future__ import annotations

import pytest

from treasuryforge.funding_persistence import funding_persistence


def _p(hist, enter=0.00001, exit_=0.000003, be=3):
    return funding_persistence(hist, enter_rate=enter, exit_rate=exit_, breakeven_intervals=be)


def test_single_episode_duration():
    # rises above enter, holds 4 intervals above exit, then drops below exit
    hist = [0.0, 0.00002, 0.00002, 0.00001, 0.000005, 0.0000001, 0.0]
    s = _p(hist)
    assert s.n_episodes == 1 and s.durations == [4] and not s.last_censored


def test_two_episodes_and_breakeven_share():
    hist = [0.00002, 0.0, 0.00002, 0.00002, 0.00002, 0.0]   # ep1 len1, ep2 len3
    s = _p(hist, be=3)
    assert s.durations == [1, 3]
    assert s.pct_reach_breakeven == pytest.approx(0.5)      # only the len-3 episode reaches be=3
    assert s.median_duration == pytest.approx(2.0)


def test_open_final_episode_is_censored():
    hist = [0.0, 0.00002, 0.00002, 0.00002]                 # still high at the end
    s = _p(hist)
    assert s.last_censored and s.durations == [3]


def test_never_enters():
    s = _p([0.0, 0.000001, 0.0000005])
    assert s.n_episodes == 0 and s.pct_reach_breakeven == 0.0 and s.median_duration == 0.0


def test_rejects_inverted_band():
    with pytest.raises(ValueError):
        funding_persistence([0.0], enter_rate=0.0, exit_rate=0.001, breakeven_intervals=1)


# -- mutation-killing: pin the stats arithmetic --------------------------------
def test_median_odd_and_even():
    from treasuryforge.funding_persistence import PersistenceStats
    assert PersistenceStats(3, [2, 4, 6], 5).median_duration == 4.0          # odd -> middle
    assert PersistenceStats(4, [2, 4, 6, 8], 5).median_duration == pytest.approx(5.0)  # (4+6)/2


def test_mean_and_pct_reach_inclusive():
    from treasuryforge.funding_persistence import PersistenceStats
    s = PersistenceStats(2, [5, 4], breakeven_intervals=5)
    assert s.mean_duration == pytest.approx(4.5)
    assert s.pct_reach_breakeven == pytest.approx(0.5)         # d>=5 inclusive: only the 5


def test_empty_stats_are_zero():
    from treasuryforge.funding_persistence import PersistenceStats
    s = PersistenceStats(0, [], 5)
    assert s.median_duration == 0.0 and s.mean_duration == 0.0 and s.pct_reach_breakeven == 0.0


def test_stats_defaults_and_frozen():
    import dataclasses

    from treasuryforge.funding_persistence import PersistenceStats
    s = PersistenceStats(0)                          # all the rest default
    assert s.durations == [] and s.breakeven_intervals == 0 and s.last_censored is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.n_episodes = 5


def test_median_odd_uses_middle_index():
    from treasuryforge.funding_persistence import PersistenceStats
    # 5 elements -> median is s[2]=3 (kills s[n//2] -> s[n//3] which would give s[1]=2)
    assert PersistenceStats(5, [1, 2, 3, 4, 5], 0).median_duration == 3.0


def test_render_is_exact_string():
    from treasuryforge.funding_persistence import PersistenceStats
    # exact match kills the 'XX...XX' string-wrap mutations (substring checks miss them)
    closed = PersistenceStats(2, [3, 5], breakeven_intervals=4, last_censored=False).render()
    assert closed == "episodes=2  median=4h  mean=4h  reach_breakeven(4h)=50%"
    opened = PersistenceStats(2, [3, 5], breakeven_intervals=4, last_censored=True).render()
    assert opened == "episodes=2  median=4h  mean=4h  reach_breakeven(4h)=50%  [last open]"


def test_equal_band_is_allowed():
    # exit == enter must NOT raise (kills `>` -> `>=` in the validation)
    funding_persistence([0.0], enter_rate=0.001, exit_rate=0.001, breakeven_intervals=1)


def test_inverted_band_message_exact():
    with pytest.raises(ValueError, match=r"^exit_rate must be <= enter_rate$"):
        funding_persistence([0.0], enter_rate=0.0, exit_rate=0.001, breakeven_intervals=1)


def test_enter_boundary_inclusive():
    # f EXACTLY == enter_rate starts an episode (kills `f >= enter` -> `f > enter`)
    s = funding_persistence([0.001, 0.001, 0.0], enter_rate=0.001, exit_rate=0.0005, breakeven_intervals=1)
    assert s.n_episodes == 1 and s.durations == [2]


def test_exit_boundary_keeps_episode_open():
    # f EXACTLY == exit_rate CONTINUES the episode (kills `f < exit` -> `f <= exit`)
    s = funding_persistence([0.002, 0.0005, 0.002, 0.0], enter_rate=0.001, exit_rate=0.0005,
                            breakeven_intervals=1)
    assert s.n_episodes == 1 and s.durations == [3]   # 0.0005 not < 0.0005 -> stays in
