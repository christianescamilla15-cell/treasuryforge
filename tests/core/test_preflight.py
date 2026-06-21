"""Startup preflight — fail-closed. A healthy environment is READY; breaking ANY
single precondition must drop the startup state to SAFE_HALTED with that check
named in the failures. The bot never operates on a partial environment."""

from __future__ import annotations

import dataclasses

import pytest

from treasuryforge.policy import PolicyConfig
from treasuryforge.preflight import (
    Check,
    PreflightInputs,
    PreflightReport,
    StartupState,
    run_preflight,
)


def _cfg(**over) -> PolicyConfig:
    base = dict(allowed_symbols=frozenset({"BTC"}), max_notional_per_tx=500.0,
                max_tx_per_window=5, window_steps=10, max_drawdown_pct=0.2,
                max_notional_per_window=1000.0, max_staleness_ns=10**9)
    base.update(over)
    return PolicyConfig(**base)


def _inputs(tmp_path, **over) -> PreflightInputs:
    base = dict(mode="live", config=_cfg(), journal_dir=str(tmp_path / "j"),
                has_credentials=True, now_wall=1_700_000_000.0, exchange_reachable=True,
                data_age_s=1.0, max_data_age_s=5.0, clock_skew_s=0.3, max_clock_skew_s=2.0)
    base.update(over)
    return PreflightInputs(**base)


def _failed(r):
    return {c.name for c in r.failures()}


def test_all_preconditions_pass_is_ready(tmp_path):
    r = run_preflight(_inputs(tmp_path))
    assert r.ready and r.state is StartupState.READY and r.failures() == []


def test_paper_mode_skips_live_only_gates(tmp_path):
    # paper: exchange/clock-skew not enforced, spend cap not required
    r = run_preflight(_inputs(tmp_path, mode="paper", exchange_reachable=False,
                              clock_skew_s=None, config=_cfg(max_notional_per_window=None)))
    assert r.ready


def test_implicit_mode_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, mode=None))
    assert not r.ready and "mode_explicit" in _failed(r)


def test_missing_config_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, config=None))
    assert r.state is StartupState.SAFE_HALTED and "config_loaded" in _failed(r)


def test_no_journal_dir_halts(tmp_path):
    assert "journal_writable" in _failed(run_preflight(_inputs(tmp_path, journal_dir=None)))


def test_unwritable_journal_halts(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")                       # a file cannot be a directory parent
    r = run_preflight(_inputs(tmp_path, journal_dir=str(f / "sub")))
    assert not r.ready and "journal_writable" in _failed(r)


def test_missing_credentials_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, has_credentials=False))
    assert not r.ready and "credentials_present" in _failed(r)


def test_empty_allowlist_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, config=_cfg(allowed_symbols=frozenset())))
    assert not r.ready and "allowlist_active" in _failed(r)


def test_zero_caps_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, config=_cfg(max_notional_per_tx=0.0)))
    assert not r.ready and "caps_loaded" in _failed(r)


def test_live_requires_spend_cap(tmp_path):
    r = run_preflight(_inputs(tmp_path, config=_cfg(max_notional_per_window=None)))
    assert not r.ready and "caps_loaded" in _failed(r)


def test_kill_switch_latched_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, config=_cfg(kill_switch=True)))
    assert not r.ready and "kill_switch_clear" in _failed(r)


def test_insane_clock_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, now_wall=123.0))     # 1970-ish: clock not set
    assert not r.ready and "clock_sane" in _failed(r)


def test_stale_data_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, data_age_s=60.0))    # 60s > 5s budget
    assert not r.ready and "data_feed_fresh" in _failed(r)


def test_missing_data_age_halts(tmp_path):
    r = run_preflight(_inputs(tmp_path, data_age_s=None))
    assert not r.ready and "data_feed_fresh" in _failed(r)


def test_clock_skew_halts_live(tmp_path):
    r = run_preflight(_inputs(tmp_path, clock_skew_s=10.0))  # > 2s budget
    assert not r.ready and "clock_skew_bounded" in _failed(r)


def test_unreachable_exchange_halts_live(tmp_path):
    r = run_preflight(_inputs(tmp_path, exchange_reachable=False))
    assert not r.ready and "exchange_reachable" in _failed(r)


def test_render_shows_state_and_failures(tmp_path):
    out = run_preflight(_inputs(tmp_path, has_credentials=False)).render()
    assert "SAFE_HALTED" in out and "credentials_present" in out and "refusing to operate" in out


# ============================================================================
# mutation hardening: exact checks/details, render, defaults, boundaries
# ============================================================================
def test_startup_state_values_exact():
    assert StartupState.READY.value == "READY"
    assert StartupState.SAFE_HALTED.value == "SAFE_HALTED"


def test_check_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Check("x", True, "d").ok = False


def test_preflight_inputs_defaults():
    inp = PreflightInputs(mode="paper", config=None, journal_dir=None,
                          has_credentials=False, now_wall=1.0)
    assert inp.exchange_reachable is True
    assert inp.data_age_s is None and inp.clock_skew_s is None
    assert inp.max_data_age_s == 5.0 and inp.max_clock_skew_s == 2.0
    assert inp.min_sane_epoch == 1_600_000_000.0


def test_report_checks_default_is_empty():
    assert PreflightReport(StartupState.READY).checks == []


def test_all_checks_are_exact_when_healthy(tmp_path):
    jd = str(tmp_path / "j")
    r = run_preflight(_inputs(tmp_path, journal_dir=jd))
    assert r.state is StartupState.READY
    assert [(c.name, c.ok, c.detail) for c in r.checks] == [
        ("mode_explicit", True, "mode='live' (must be 'paper' or 'live')"),
        ("config_loaded", True, "PolicyConfig present"),
        ("journal_writable", True, f"writable: {jd}"),
        ("credentials_present", True, "wallet/key resolvable"),
        ("allowlist_active", True, "1 symbol(s) allowed"),
        ("caps_loaded", True, "per-tx cap=500.0, spend cap=1000.0"),
        ("kill_switch_clear", True, "clear"),
        ("clock_sane", True, "wall=1700000000"),
        ("data_feed_fresh", True, "age=1.0s vs budget 5.0s"),
        ("clock_skew_bounded", True, "skew=0.3s vs budget 2.0s"),
        ("exchange_reachable", True, "reachable"),
    ]


def test_render_exact_when_halted():
    rep = PreflightReport(StartupState.SAFE_HALTED, [Check("a", True, "d1"), Check("b", False, "d2")])
    assert rep.render() == ("STARTUP: SAFE_HALTED\n"
                            "  [PASS] a: d1\n"
                            "  [FAIL] b: d2\n"
                            "  -> refusing to operate (1 precondition(s) failed)")


def test_render_ready_has_no_refusing_line():
    rep = PreflightReport(StartupState.READY, [Check("a", True, "d1")])
    assert rep.render() == "STARTUP: READY\n  [PASS] a: d1"


def test_journal_no_dir_message(tmp_path):
    r = run_preflight(_inputs(tmp_path, journal_dir=None))
    jc = next(c for c in r.checks if c.name == "journal_writable")
    assert not jc.ok and jc.detail == "no journal directory configured"


def test_journal_existing_dir_still_passes(tmp_path):
    jd = tmp_path / "j"
    jd.mkdir()                                       # pre-existing dir; exist_ok=True must allow it
    assert run_preflight(_inputs(tmp_path, journal_dir=str(jd))).ready


def test_clock_sane_boundary_inclusive(tmp_path):
    r = run_preflight(_inputs(tmp_path, now_wall=1_600_000_000.0))   # == min_sane_epoch
    assert "clock_sane" not in _failed(r)


def test_data_fresh_boundary_inclusive(tmp_path):
    r = run_preflight(_inputs(tmp_path, data_age_s=5.0))             # age == budget
    assert "data_feed_fresh" not in _failed(r)


def test_clock_skew_boundary_inclusive(tmp_path):
    r = run_preflight(_inputs(tmp_path, clock_skew_s=2.0))           # skew == budget
    assert "clock_skew_bounded" not in _failed(r)


def test_caps_positive_not_above_one(tmp_path):
    r = run_preflight(_inputs(tmp_path, config=_cfg(max_notional_per_tx=0.5)))
    assert "caps_loaded" not in _failed(r)                          # cap>0 (not cap>1)


def test_config_none_paper_fails_caps_but_passes_killswitch(tmp_path):
    r = run_preflight(_inputs(tmp_path, mode="paper", config=None, clock_skew_s=None))
    assert "caps_loaded" in _failed(r)               # default cap 0.0 -> fails
    assert "kill_switch_clear" not in _failed(r)     # default kill_switch False -> passes
