"""The committee is a perspective-diverse panel: a strategy is deploy-worthy only when it
survives EVERY lens. Each consultant vetoes a distinct failure mode the project actually hit."""

from __future__ import annotations

from treasuryforge.consultants import (
    Committee,
    _concentration,
    _consistency,
    _drawdown,
    _edge,
    _regime,
    _ruin,
)

_STRONG = [0.003, 0.001] * 25                              # steady, both halves +, no outlier
_TS = list(range(50))


def test_strong_record_passes_every_consultant() -> None:
    v = Committee().review(_STRONG, _TS)
    assert v.approved and not v.vetoes


def test_concentration_vetoes_one_outlier_edge() -> None:
    returns = [0.001] * 40 + [0.5]                         # the ORDI shape: one trade is everything
    assert _concentration(returns, _TS).approve is False
    assert not Committee().review(returns, _TS).approved


def test_consistency_vetoes_a_reversing_record() -> None:
    returns = [0.01] * 20 + [-0.01] * 20                   # great first half, negative second
    assert _consistency(returns, _TS).approve is False
    assert not Committee().review(returns, _TS).approved


def test_drawdown_vetoes_a_deep_trough() -> None:
    returns = [0.01] * 10 + [-0.30]                        # ~30% drop > 25% limit
    assert _drawdown(returns, _TS).approve is False


def test_edge_vetoes_a_zero_mean_record() -> None:
    returns = [0.001, -0.001] * 25                         # ~no edge -> low DSR
    assert _edge(returns, _TS).approve is False


def test_ruin_vetoes_a_volatile_blow_up_prone_record() -> None:
    # big swings -> block bootstrap breaches the 20% drawdown band on most paths
    returns = [0.25, -0.20] * 25
    assert _ruin(returns, _TS).approve is False
    assert not Committee().review(returns, _TS).approved


def test_ruin_passes_a_steady_record() -> None:
    assert _ruin(_STRONG, _TS).approve is True


def test_regime_vetoes_a_late_decaying_edge() -> None:
    # works early then the regime turns -> recent window no longer pays
    returns = [0.02] * 25 + [-0.01] * 25
    assert _regime(returns, _TS).approve is False


def test_regime_passes_a_still_paying_edge() -> None:
    assert _regime(_STRONG, _TS).approve is True


def test_regime_handles_a_short_record() -> None:
    assert _regime([0.01, 0.01], [0, 1]).approve is True


def test_any_single_veto_blocks_the_committee() -> None:
    # passes edge/concentration/drawdown but reverses -> the lone consistency veto must block
    returns = [0.02] * 25 + [-0.005] * 25
    v = Committee().review(returns, _TS)
    assert not v.approved and any(vote.consultant == "consistency" for vote in v.vetoes)


def test_regime_vetoes_mean_reverting_equity_curve() -> None:
    # Passes recent mean check (last 13 returns have positive mean)
    # but the equity curve is flat/mean-reverting (VR < 0.9)
    # and has no net growth (final equity < 1.0, so is_steady = False)
    returns = [-0.1] + [0.012, -0.01] * 20
    ts = list(range(len(returns)))
    vote = _regime(returns, ts)
    assert vote.approve is False
    assert "VR(k=8)" in vote.reason

