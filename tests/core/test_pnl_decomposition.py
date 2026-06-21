"""PnL decomposition (A1): the split must reconcile EXACTLY to the additive total,
separate gross (funding+convergence) from costs, and expose cost/gross for the gate."""

from __future__ import annotations

import pytest

from treasuryforge.pnl_decomposition import decompose


def _funding_ledger():
    # ENTER -> 3x HOLD (funding) -> EXIT, fee 0.0006 per side
    return [
        {"kind": "shadow", "action": "ENTER", "funding": 0.00001, "r": -0.0006},
        {"kind": "shadow", "action": "HOLD", "funding": 0.00001, "r": 0.00001},
        {"kind": "shadow", "action": "HOLD", "funding": 0.00002, "r": 0.00002},
        {"kind": "shadow", "action": "HOLD", "funding": 0.00001, "r": 0.00001},
        {"kind": "shadow", "action": "EXIT", "funding": 0.0, "r": -0.0006},
    ]


def test_funding_decomposition_and_exact_reconciliation():
    b = decompose(_funding_ledger())
    assert b.funding == pytest.approx(0.00004)        # 1+2+1 e-5
    assert b.convergence == pytest.approx(0.0)        # funding-carry has no convergence
    assert b.entry_fees == pytest.approx(-0.0006) and b.exit_fees == pytest.approx(-0.0006)
    assert b.n_hold == 3
    total_r = sum(e["r"] for e in _funding_ledger())
    assert b.net == pytest.approx(total_r)            # reconciles EXACTLY


def test_basis_separates_funding_from_convergence():
    # HOLD r = funding + convergence; here convergence = r - funding
    evs = [
        {"kind": "basis", "action": "ENTER", "funding": 0.00001, "premium": 0.0012, "r": -0.0006},
        {"kind": "basis", "action": "HOLD", "funding": 0.00002, "premium": 0.0007, "r": 0.00052},
        {"kind": "basis", "action": "EXIT", "funding": 0.0, "premium": 0.0001, "r": -0.0006},
    ]
    b = decompose(evs)
    assert b.funding == pytest.approx(0.00002)
    assert b.convergence == pytest.approx(0.00052 - 0.00002)   # 0.0005 captured
    assert b.net == pytest.approx(sum(e["r"] for e in evs))


def test_cost_to_gross_metric():
    b = decompose(_funding_ledger())            # gross 0.00004, costs -0.0012
    assert b.cost_to_gross == pytest.approx(0.0012 / 0.00004)   # costs dwarf the edge -> KILL
    assert b.cost_to_gross > 0.35


def test_ignores_unrelated_events_and_flat():
    evs = [
        {"kind": "order", "action": "filled", "r": 99.0},   # not a shadow event
        {"kind": "shadow", "action": "FLAT", "funding": 0.0, "r": 0.0},
        {"kind": "shadow", "action": "HOLD", "funding": 0.00003, "r": 0.00003},
    ]
    b = decompose(evs)
    assert b.funding == pytest.approx(0.00003) and b.net == pytest.approx(0.00003)
    assert b.n_intervals == 2                   # FLAT + HOLD counted, the 'order' ignored


def test_empty_is_safe():
    b = decompose([])
    assert b.net == 0.0 and b.cost_to_gross == float("inf")


# -- mutation-killing: pin the property arithmetic ------------------------------
def test_breakdown_property_arithmetic():
    from treasuryforge.pnl_decomposition import PnlBreakdown
    b = PnlBreakdown(funding=0.003, convergence=0.001, entry_fees=-0.0006, exit_fees=-0.0004,
                     slippage=-0.0001, hedge_drift=-0.0002, n_intervals=5, n_hold=3)
    assert b.gross == pytest.approx(0.004)               # funding + convergence
    assert b.costs == pytest.approx(-0.0013)             # entry+exit+slippage+drift
    assert b.net == pytest.approx(0.004 - 0.0013)        # gross + costs (not minus)
    assert b.cost_to_gross == pytest.approx(0.0013 / 0.004)   # |costs| / gross


def test_cost_to_gross_infinite_without_gross():
    from treasuryforge.pnl_decomposition import PnlBreakdown
    assert PnlBreakdown(0.0, 0.0, -0.001, 0.0, 0.0, 0.0, 1, 0).cost_to_gross == float("inf")


def test_exit_bucket_is_separate_from_entry():
    b = decompose([{"kind": "shadow", "action": "EXIT", "funding": 0.0, "r": -0.0007}])
    assert b.exit_fees == pytest.approx(-0.0007) and b.entry_fees == 0.0


def test_breakdown_is_frozen():
    import dataclasses

    from treasuryforge.pnl_decomposition import PnlBreakdown
    b = PnlBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.funding = 1.0


def test_cost_to_gross_epsilon_boundary():
    from treasuryforge.pnl_decomposition import PnlBreakdown
    # gross exactly 1e-12 -> NOT > 1e-12 -> inf (kills `>` -> `>=`)
    assert PnlBreakdown(1e-12, 0.0, -0.001, 0.0, 0.0, 0.0, 1, 0).cost_to_gross == float("inf")
    # gross 1.5e-12 -> > 1e-12 -> finite (kills `>1e-12` -> `>2e-12`)
    assert PnlBreakdown(1.5e-12, 0.0, -0.001, 0.0, 0.0, 0.0, 1, 0).cost_to_gross != float("inf")


def test_render_has_all_labels_and_values():
    from treasuryforge.pnl_decomposition import PnlBreakdown
    text = PnlBreakdown(0.003, 0.001, -0.0006, -0.0004, -0.0001, -0.0002, 5, 3).render()
    for label in ("funding", "convergence", "entry fees", "exit fees", "slippage",
                  "hedge drift", "gross", "costs", "NET", "cost/gross"):
        assert label in text
    assert "+0.003000" in text and "+0.001000" in text          # actual values rendered


def test_accumulates_across_repeated_actions():
    evs = [{"kind": "shadow", "action": "ENTER", "funding": 0.0, "r": -0.0006},
           {"kind": "shadow", "action": "ENTER", "funding": 0.0, "r": -0.0006},
           {"kind": "basis", "action": "HOLD", "funding": 0.00001, "r": 0.00051},
           {"kind": "basis", "action": "HOLD", "funding": 0.00002, "r": 0.00052},
           {"kind": "shadow", "action": "EXIT", "funding": 0.0, "r": -0.0004},
           {"kind": "shadow", "action": "EXIT", "funding": 0.0, "r": -0.0004}]
    b = decompose(evs)
    assert b.entry_fees == pytest.approx(-0.0012)               # += accumulates, not = (last)
    assert b.exit_fees == pytest.approx(-0.0008)
    assert b.convergence == pytest.approx((0.00051 - 0.00001) + (0.00052 - 0.00002))  # both HOLDs


def test_missing_r_and_funding_default_to_zero():
    # HOLD with funding present but r MISSING -> r=0 -> convergence = 0 - funding
    b = decompose([{"kind": "shadow", "action": "HOLD", "funding": 0.00003}])
    assert b.funding == pytest.approx(0.00003) and b.convergence == pytest.approx(-0.00003)
    # HOLD with r present but funding MISSING -> f=0
    b2 = decompose([{"kind": "basis", "action": "HOLD", "r": 0.0005}])
    assert b2.funding == 0.0 and b2.convergence == pytest.approx(0.0005)
