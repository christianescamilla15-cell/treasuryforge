"""Basis shadow book: the two-stream return (funding + premium convergence) and
durable replay across restarts."""

from __future__ import annotations

import pytest

from treasuryforge.journal import Journal
from treasuryforge.shadow_basis import BasisBook
from treasuryforge.signals.basis import BasisParams, BasisSignal


def _book(journal=None):
    p = BasisParams(enter_premium=0.0010, exit_premium=0.0002, fee_per_leg=0.0003)
    return BasisBook(BasisSignal(p), journal=journal)


def test_cost_gate_vetoes_basis_entry():
    b = _book()
    a = b.observe(0.00001, 0.0012, ts=1, allow_entry=False)   # contango but gate vetoes
    assert a.value == "FLAT" and b.n_entries == 0
    assert b.returns[-1] == 0.0 and not b.signal.in_position


def test_enter_costs_and_anchors_premium():
    b = _book()
    b.observe(funding_rate=0.00001, premium=0.0012, ts=1)     # ENTER
    assert b.n_entries == 1
    assert b.returns[-1] == pytest.approx(-2 * 0.0003)        # entry_cost
    assert b._prev_premium == pytest.approx(0.0012)


def test_hold_captures_funding_plus_convergence():
    b = _book()
    b.observe(0.00001, 0.0012, ts=1)                          # ENTER (anchor 0.0012)
    b.observe(0.00002, 0.0007, ts=2)                          # HOLD: premium 0.0012 -> 0.0007
    assert b.n_hold == 1
    convergence = 0.0012 - 0.0007                             # = 0.0005 gain
    assert b.returns[-1] == pytest.approx(0.00002 + convergence)
    assert b.realized_funding == pytest.approx(0.00002)
    assert b.realized_convergence == pytest.approx(convergence)


def test_exit_then_flat():
    b = _book()
    b.observe(0.00001, 0.0012, ts=1)                          # ENTER
    b.observe(0.00001, 0.0001, ts=2)                          # EXIT (premium <= exit)
    assert b.n_exits == 1 and b.returns[-1] == pytest.approx(-2 * 0.0003)
    b.observe(0.00001, 0.0001, ts=3)                          # FLAT
    assert b.returns[-1] == 0.0


def test_replay_reconstructs_equity(tmp_path):
    j = Journal(str(tmp_path))
    live = _book(journal=j)
    for ts, (f, prem) in enumerate([(0.00001, 0.0012), (0.00002, 0.0007),
                                    (0.00001, 0.0004), (0.00001, 0.0001)], start=1):
        live.observe(f, prem, ts=ts)
    replayed = _book(journal=Journal(str(tmp_path)))          # rebuild from the ledger
    assert replayed.equity == pytest.approx(live.equity)
    assert replayed.n_hold == live.n_hold and replayed.n_exits == live.n_exits
    assert replayed.realized_convergence == pytest.approx(live.realized_convergence)


# -- mutation-killing: report, compounding, exact counters ---------------------
def test_report_properties_and_render():
    b = _book()
    b.observe(0.00001, 0.0012, ts=1)                          # ENTER
    b.observe(0.00002, 0.0007, ts=2)                          # HOLD
    rep = b.report()
    assert rep.net_return == pytest.approx(b.equity - 1.0)    # equity - 1
    assert (rep.n_entries, rep.n_hold, rep.n_exits, rep.n_intervals) == (1, 1, 0, 2)
    text = rep.render()
    assert "BASIS SHADOW" in text and "convergence" in text and "net return" in text


def test_equity_compounds_multiplicatively():
    b = _book()
    b.observe(0.00001, 0.0012, ts=1)                          # ENTER r=-entry_cost
    e_after_enter = b.equity
    assert e_after_enter == pytest.approx(1.0 * (1.0 + (-2 * 0.0003)))
    b.observe(0.00002, 0.0007, ts=2)                          # HOLD r=funding+conv
    r2 = 0.00002 + (0.0012 - 0.0007)
    assert b.equity == pytest.approx(e_after_enter * (1.0 + r2))


def test_realized_funding_only_counts_holds():
    b = _book()
    b.observe(0.00001, 0.0012, ts=1)                          # ENTER -> no funding counted
    assert b.realized_funding == 0.0
    b.observe(0.00009, 0.0007, ts=2)                          # HOLD
    assert b.realized_funding == pytest.approx(0.00009)


def test_book_defaults_and_default_journal():
    b = _book()                                               # journal=None default
    assert b.returns == [] and b.total_costs == 0.0
    assert b.observe(0.0001, 0.0001, ts=1).value == "FLAT"    # no journal -> no crash (kills None->"")


def test_report_render_lines_exact():
    from treasuryforge.shadow_basis import BasisReport
    rep = BasisReport(n_intervals=3, n_hold=2, n_entries=1, n_exits=0, equity=1.001,
                      realized_funding=0.00005, realized_convergence=0.0001, total_costs=0.0006)
    assert rep.returns == []                                  # BasisReport.returns default factory
    lines = rep.render().split("\n")                          # exact lines kill the XX-wrap mutations
    assert lines[0] == "=== spot-vs-perp BASIS SHADOW (paper, no funds) ==="
    assert lines[1] == "  intervals observed : 3"
    assert lines[2] == "  intervals in-position: 2"
    assert lines[3] == "  entries / exits    : 1 / 0"
    assert lines[4] == "  realized funding   : +0.000050"
    assert lines[5] == "  realized convergence: +0.000100"
    assert lines[6] == "  costs paid         : 0.000600"
    assert lines[7] == "  net return         : +0.1000%  (equity 1.001000)"


def test_event_has_ts_key():
    j = Journal(str(__import__("tempfile").mkdtemp()))
    b = BasisBook(BasisSignal(BasisParams(enter_premium=0.001, exit_premium=0.0002, fee_per_leg=0.0003)),
                  journal=j)
    b.observe(0.00001, 0.0012, ts=77)
    ev = next(e for e in j.read_ledger() if e.get("kind") == "basis")
    assert ev["ts"] == 77                                     # the "ts" key (kills "XXtsXX")


def test_counters_accumulate_across_two_cycles():
    b = _book()
    b.observe(0.00001, 0.0012, ts=1)                          # ENTER
    b.observe(0.00002, 0.0009, ts=2)                          # HOLD
    b.observe(0.00003, 0.0008, ts=3)                          # HOLD
    b.observe(0.00001, 0.0001, ts=4)                          # EXIT
    b.observe(0.00001, 0.0012, ts=5)                          # ENTER again
    assert b.n_entries == 2 and b.n_hold == 2 and b.n_exits == 1     # += not = (would be 1)
    assert b.realized_funding == pytest.approx(0.00002 + 0.00003)    # sum of the two holds
    # convergence accumulates too: (0.0012-0.0009) + (0.0009-0.0008) (kills += -> =)
    assert b.realized_convergence == pytest.approx(0.0003 + 0.0001)
    assert b.total_costs == pytest.approx(2 * 0.0006 + 0.0006)       # 2 entries + 1 exit cost
