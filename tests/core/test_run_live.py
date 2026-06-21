"""Systemd entrypoint shim — mode/venue parsing and the fail-closed exit codes.
Until a venue feed/executor is wired, launching must refuse to operate (SAFE_HALTED),
never silently fake-trade."""

from __future__ import annotations

from treasuryforge.run_live import main, parse_mode, venue_wired
from treasuryforge.service import ServiceExit


def test_parse_mode_accepts_only_paper_or_live():
    assert parse_mode({"TF_MODE": "paper"}) == "paper"
    assert parse_mode({"TF_MODE": "live"}) == "live"
    assert parse_mode({"TF_MODE": "x"}) is None
    assert parse_mode({}) is None


def test_venue_wired():
    assert venue_wired({"TF_VENUE": "bitso"})
    assert venue_wired({"TF_VENUE": "hyperliquid"})
    assert not venue_wired({"TF_VENUE": "nope"})
    assert not venue_wired({})


def test_service_exit_codes_are_stable():
    assert (int(ServiceExit.OK), int(ServiceExit.SAFE_HALTED),
            int(ServiceExit.DEAD_MAN), int(ServiceExit.ERROR)) == (0, 10, 20, 30)


def test_main_safe_halts_without_explicit_mode():
    assert main({}) == int(ServiceExit.SAFE_HALTED)
    assert main({"TF_MODE": "bad"}) == int(ServiceExit.SAFE_HALTED)


def test_main_safe_halts_without_a_venue():
    assert main({"TF_MODE": "live"}) == int(ServiceExit.SAFE_HALTED)
    assert main({"TF_MODE": "paper"}) == int(ServiceExit.SAFE_HALTED)


def test_main_safe_halts_when_venue_unimplemented():
    # venue set but feed/executor not built yet -> still fail-closed, not a crash
    assert main({"TF_MODE": "live", "TF_VENUE": "hyperliquid"}) == int(ServiceExit.SAFE_HALTED)


# -- mutation hardening: stderr messages per branch + os.environ default -----
def test_bad_mode_message(capsys):
    main({"TF_MODE": "nope"})
    err = capsys.readouterr().err
    assert err.startswith("run_live:") and "TF_MODE must be" in err


def test_no_venue_message(capsys):
    main({"TF_MODE": "live"})
    err = capsys.readouterr().err
    assert err.startswith("run_live:") and "no venue wired" in err


def test_unimplemented_venue_message_names_the_venue(capsys):
    main({"TF_MODE": "live", "TF_VENUE": "hyperliquid"})
    err = capsys.readouterr().err
    assert err.startswith("run_live:") and "not yet implemented" in err and "hyperliquid" in err


def test_main_with_no_arg_reads_os_environ(monkeypatch):
    monkeypatch.delenv("TF_MODE", raising=False)
    monkeypatch.delenv("TF_VENUE", raising=False)
    assert main() == int(ServiceExit.SAFE_HALTED)        # reads os.environ when env is None
