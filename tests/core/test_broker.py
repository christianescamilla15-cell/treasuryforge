"""The autonomous broker must DEPLOY only what clears the gate, HOLD everything else, and
never allocate past the portfolio cap -- so with no proven edge it sits at $0, correctly."""

from __future__ import annotations

from treasuryforge.broker import decide
from treasuryforge.deployment_gate import DeploymentGate

_STRONG = [0.003, 0.001] * 25                              # n=50, clears DSR + APR
_SPAN_20D = [i * (20 * 86400 // 49) for i in range(50)]
_WEAK = [0.0001, -0.0001] * 25                             # ~zero mean, fails the gate


def test_holds_everything_when_no_edge() -> None:
    rep = decide({"funding:ETH": (_WEAK, _SPAN_20D), "scalp:SOL": (_WEAK, _SPAN_20D)})
    assert not rep.any_live and rep.total_deployed == 0.0
    assert all(d.action == "HOLD" for d in rep.decisions)


def test_deploys_a_strategy_that_clears_the_gate() -> None:
    rep = decide({"cross:ZEC": (_STRONG, _SPAN_20D), "scalp:SOL": (_WEAK, _SPAN_20D)})
    assert rep.n_deployed == 1 and rep.total_deployed == 0.01
    top = rep.decisions[0]
    assert top.strategy == "cross:ZEC" and top.action == "DEPLOY" and top.tier_fraction == 0.01


def test_portfolio_cap_blocks_excess_deploys() -> None:
    # cap so tight only one micro (1%) deploy fits; the second clears but is held back
    rep = decide({"a": (_STRONG, _SPAN_20D), "b": (_STRONG, _SPAN_20D)},
                 portfolio_cap=0.015)
    assert rep.n_deployed == 1 and rep.total_deployed == 0.01
    held = [d for d in rep.decisions if d.action == "HOLD"]
    assert len(held) == 1 and "cap" in held[0].reason


def test_ranks_by_dsr_highest_first() -> None:
    rep = decide({"weak": (_WEAK, _SPAN_20D), "strong": (_STRONG, _SPAN_20D)})
    assert rep.decisions[0].strategy == "strong"      # highest DSR first


def test_empty_input_is_flat() -> None:
    rep = decide({}, gate=DeploymentGate())
    assert rep.decisions == () and rep.total_deployed == 0.0 and not rep.any_live
