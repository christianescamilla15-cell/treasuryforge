"""Shadow paper-book for funding-carry. Deterministic: a funding sequence drives
ENTER/HOLD/EXIT, the conservative per-interval return model is exact, and the
journal persists + replays the run (so a restart resumes the same track record and
in-position state). No money, no keys."""

from __future__ import annotations

import pytest

from treasuryforge.journal import Journal
from treasuryforge.shadow import ShadowBook, ShadowReport
from treasuryforge.signals.funding import Action, FundingCarryParams, FundingCarrySignal


def _sig():
    return FundingCarrySignal(FundingCarryParams(
        enter_rate=0.0001, exit_rate=0.00005, fee_per_leg=0.0005, legs_round_trip=4))


def _book(tmp_path, journal=True, sub="shadow"):
    j = Journal(str(tmp_path / sub)) if journal else None
    return ShadowBook(_sig(), journal=j)


def test_enter_hold_exit_sequence_and_report(tmp_path):
    b = _book(tmp_path)
    actions = [b.observe(f, ts=i) for i, f in enumerate([0.0002, 0.0002, 0.00003, 0.00003])]
    assert actions == [Action.ENTER, Action.HOLD, Action.EXIT, Action.FLAT]
    assert b.returns == [pytest.approx(-0.001), pytest.approx(0.0002), pytest.approx(-0.001), 0.0]
    r = b.report()
    assert (r.n_intervals, r.n_entries, r.n_hold, r.n_exits) == (4, 1, 1, 1)
    assert r.realized_funding == pytest.approx(0.0002)
    assert r.total_costs == pytest.approx(0.002)
    assert r.equity == pytest.approx(0.999 * 1.0002 * 0.999)
    assert r.net_return == pytest.approx(r.equity - 1.0)


def test_age_rule_survives_restart(tmp_path):
    # the hourly shadow is oneshot, so EVERY run replays: the episode age must persist or
    # the age-rule never accumulates. min_age=3: 2 high intervals (FLAT), restart, then the
    # 3rd high interval must ENTER (age restored to 2, not reset to 0).
    p = FundingCarryParams(enter_rate=0.0001, exit_rate=0.00005, fee_per_leg=0.0005, legs_round_trip=4)
    b1 = ShadowBook(FundingCarrySignal(p, min_age=3), journal=Journal(str(tmp_path)))
    assert b1.observe(0.0002, ts=0) is Action.FLAT      # age 1
    assert b1.observe(0.0002, ts=1) is Action.FLAT      # age 2
    assert b1.n_entries == 0
    b2 = ShadowBook(FundingCarrySignal(p, min_age=3), journal=Journal(str(tmp_path)))
    assert b2.signal._age == 2                           # age restored across the restart
    assert b2.observe(0.0002, ts=2) is Action.ENTER      # age 3 -> enter, not restarted


def test_cost_gate_vetoes_entry_and_persists_flat(tmp_path):
    b = _book(tmp_path)
    a = b.observe(0.0002, ts=0, allow_entry=False)      # funding > enter_rate but gate says NO
    assert a is Action.FLAT and b.n_entries == 0
    assert b.returns[-1] == 0.0 and not b.signal.in_position   # no entry, no cost paid
    # gate consistent across restart: replay must NOT resurrect the vetoed entry
    b2 = _book(tmp_path)
    assert b2.n_entries == 0 and not b2.signal.in_position
    assert b2.observe(0.0002, ts=1, allow_entry=True) is Action.ENTER   # now it enters


def test_stays_flat_below_enter_rate(tmp_path):
    b = _book(tmp_path)
    assert b.observe(0.00001, ts=0) is Action.FLAT
    assert b.observe(0.00002, ts=1) is Action.FLAT
    assert b.report().equity == 1.0 and b.report().returns == [0.0, 0.0]


def test_hold_accrues_funding(tmp_path):
    b = _book(tmp_path)
    b.observe(0.0002, ts=0)                 # ENTER
    b.observe(0.0003, ts=1)                 # HOLD
    b.observe(0.0004, ts=2)                 # HOLD
    assert b.report().realized_funding == pytest.approx(0.0007) and b.report().n_hold == 2


def test_return_model_per_action(tmp_path):
    b = _book(tmp_path, journal=False)
    assert b._return_for(Action.ENTER, 0.0002) == pytest.approx(-0.001)
    assert b._return_for(Action.HOLD, 0.0002) == pytest.approx(0.0002)
    assert b._return_for(Action.EXIT, 0.0002) == pytest.approx(-0.001)
    assert b._return_for(Action.FLAT, 0.0002) == 0.0


def test_journal_persists_and_replays(tmp_path):
    b1 = ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))
    for i, f in enumerate([0.0002, 0.0003, 0.00003]):
        b1.observe(f, ts=i)                 # ENTER, HOLD, EXIT
    b2 = ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))   # restart from same journal
    r1, r2 = b1.report(), b2.report()
    assert (r2.equity, r2.returns, r2.n_entries, r2.n_hold, r2.n_exits) == \
           (r1.equity, r1.returns, r1.n_entries, r1.n_hold, r1.n_exits)
    assert b2.signal.in_position is False               # after EXIT -> out, restored
    assert b2.observe(0.0002, ts=3) is Action.ENTER     # continues correctly


def test_replay_restores_in_position(tmp_path):
    b1 = ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))
    b1.observe(0.0002, ts=0)                # ENTER -> in position
    b2 = ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))
    assert b2.signal.in_position is True                # restored as in-position
    assert b2.observe(0.0002, ts=1) is Action.HOLD      # resumes as HOLD, not a new ENTER


def test_render_has_key_lines(tmp_path):
    b = _book(tmp_path)
    b.observe(0.0002, ts=0)
    out = b.report().render()
    assert "funding-carry SHADOW" in out and "net return" in out and "in-position" in out


# -- mutation hardening: exact render, defaults, counters, journal keys -------
def test_report_returns_default_is_a_list():
    assert ShadowReport(0, 0, 0, 0, 1.0, 0.0, 0.0).returns == []


def test_book_defaults():
    b = ShadowBook(_sig())
    assert b.journal is None and b.equity == 1.0 and b.returns == []


def test_render_is_exact():
    r = ShadowReport(n_intervals=4, n_hold=1, n_entries=1, n_exits=1, equity=0.998,
                     realized_funding=0.0002, total_costs=0.002)
    assert r.render() == "\n".join([
        "=== funding-carry SHADOW (paper, no funds) ===",
        "  intervals observed : 4",
        "  intervals in-position: 1",
        "  entries / exits    : 1 / 1",
        "  realized funding   : +0.000200",
        "  costs paid         : 0.002000",
        "  net return         : -0.2000%  (equity 0.998000)",
    ])


def test_flat_counts_no_exits_or_costs(tmp_path):
    b = _book(tmp_path)
    b.observe(0.00001, ts=0)
    b.observe(0.00002, ts=1)                     # both FLAT (below enter)
    r = b.report()
    assert (r.n_entries, r.n_hold, r.n_exits, r.total_costs) == (0, 0, 0, 0.0)


def test_two_entries_accumulate_count_and_cost(tmp_path):
    b = _book(tmp_path)
    for f in [0.0002, 0.00001, 0.0002]:          # ENTER, EXIT, ENTER
        b.observe(f, ts=0)
    r = b.report()
    assert r.n_entries == 2
    assert r.total_costs == pytest.approx(2 * b.signal.p.entry_cost + b.signal.p.exit_cost)


def test_two_exits_accumulate_count(tmp_path):
    b = _book(tmp_path)
    for f in [0.0002, 0.00001, 0.0002, 0.00001]:  # ENTER, EXIT, ENTER, EXIT
        b.observe(f, ts=0)
    assert b.report().n_exits == 2


def test_journal_event_has_exact_keys(tmp_path):
    b = ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))
    b.observe(0.0002, ts=42)                      # ENTER
    ev = next(e for e in b.journal.read_ledger() if e.get("kind") == "shadow")
    assert set(ev) == {"kind", "ts", "action", "funding", "r", "age"}
    assert ev["ts"] == 42 and ev["action"] == "ENTER"


def test_replay_does_not_repersist(tmp_path):
    b1 = ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))
    b1.observe(0.0002, ts=0)
    b1.observe(0.0003, ts=1)
    n_before = len([e for e in Journal(str(tmp_path / "s")).read_ledger() if e.get("kind") == "shadow"])
    ShadowBook(_sig(), journal=Journal(str(tmp_path / "s")))   # replay only
    n_after = len([e for e in Journal(str(tmp_path / "s")).read_ledger() if e.get("kind") == "shadow"])
    assert n_after == n_before == 2               # replay must NOT append back
