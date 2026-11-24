"""Dead-man's switch — client-side liveness guard.

Time is injected (no real clock) so expiry is deterministic. The fail-safe is a
spy that records (and can be made to fail) so we can prove the trip fires exactly
once, survives a crash mid-trip, and is fail-closed.
"""

from __future__ import annotations

import pytest

from treasuryforge.watchdog import DeadMansSwitch, Heartbeat


def _dms(tmp_path, timeout=10.0):
    return DeadMansSwitch(str(tmp_path / "hb" / "heartbeat.json"), timeout_s=timeout)


def test_requires_positive_timeout(tmp_path):
    with pytest.raises(ValueError):
        DeadMansSwitch(str(tmp_path / "h.json"), timeout_s=0)


def test_fresh_beat_is_not_expired(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    assert not d.is_expired(now=105.0)        # within timeout
    assert d.is_expired(now=111.0)            # 11s > 10s


def test_no_heartbeat_is_not_expired(tmp_path):
    # nothing started yet -> nothing to guard
    assert not _dms(tmp_path).is_expired(now=10_000.0)


def test_beat_increments_seq_and_persists(tmp_path):
    d = _dms(tmp_path)
    d.beat(now=1.0)
    d.beat(now=2.0)
    hb = d.read()
    assert hb.seq == 2 and hb.ts == 2.0 and hb.tripped is False


def test_supervise_does_not_trip_when_healthy(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    calls = []
    assert d.supervise(now=105.0, on_trip=calls.append) is False
    assert calls == []


def test_supervise_trips_once_when_expired(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    calls = []
    assert d.supervise(now=120.0, on_trip=calls.append) is True     # 20s > 10s -> trip
    assert len(calls) == 1 and "no heartbeat" in calls[0]
    assert d.tripped
    # a second supervise must NOT fire again (latched)
    assert d.supervise(now=130.0, on_trip=calls.append) is False
    assert len(calls) == 1


def test_crash_recovery_trips_on_stale_heartbeat(tmp_path):
    # bot beat then died while orders were live; a fresh supervisor reads the stale
    # heartbeat and must trip immediately
    _dms(tmp_path, timeout=10).beat(now=100.0)
    fresh = _dms(tmp_path, timeout=10)         # separate supervisor instance / process
    calls = []
    assert fresh.supervise(now=200.0, on_trip=calls.append) is True
    assert len(calls) == 1


def test_beat_is_refused_after_trip(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    d.supervise(now=120.0, on_trip=lambda r: None)
    with pytest.raises(RuntimeError, match="tripped"):
        d.beat(now=121.0)                       # fail-closed: cannot silently un-trip


def test_crash_mid_trip_refires(tmp_path):
    # if the fail-safe itself crashes, the trip must NOT be persisted, so the next
    # supervise re-fires it (the order cancel never silently gets skipped)
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)

    def flaky_on_trip(reason):
        flaky_on_trip.n += 1
        if flaky_on_trip.n == 1:
            raise RuntimeError("cancel_all failed")
    flaky_on_trip.n = 0

    with pytest.raises(RuntimeError, match="cancel_all failed"):
        d.supervise(now=120.0, on_trip=flaky_on_trip)
    assert not d.tripped                         # trip NOT latched (fail-safe didn't complete)
    assert d.supervise(now=130.0, on_trip=flaky_on_trip) is True   # re-fires, now succeeds
    assert d.tripped and flaky_on_trip.n == 2


def test_reset_clears_the_latch(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    d.supervise(now=120.0, on_trip=lambda r: None)
    assert d.tripped
    d.reset(now=200.0)                           # deliberate manual recovery
    assert not d.tripped
    d.beat(now=201.0)                            # beating works again
    assert not d.is_expired(now=205.0)


def test_heartbeat_dataclass_roundtrips(tmp_path):
    d = _dms(tmp_path)
    d.beat(now=5.0)
    hb = d.read()
    assert isinstance(hb, Heartbeat) and hb.ts == 5.0


# ============================================================================
# mutation hardening: boundaries, exact messages, dirname fallback, seq math
# ============================================================================
def test_timeout_of_one_is_valid(tmp_path):
    d = DeadMansSwitch(str(tmp_path / "h.json"), timeout_s=1)   # 1 > 0 -> allowed
    d.beat(now=100.0)
    assert not d.is_expired(now=100.5) and d.is_expired(now=101.5)


def test_timeout_error_message_is_exact(tmp_path):
    with pytest.raises(ValueError, match=r"^timeout_s must be positive$"):
        DeadMansSwitch(str(tmp_path / "h.json"), timeout_s=-1)


def test_expiry_boundary_is_strict(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    assert not d.is_expired(now=110.0)         # exactly at the timeout -> NOT expired (>)


def test_supervise_does_not_trip_exactly_at_timeout(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    assert d.supervise(now=110.0, on_trip=lambda r: None) is False   # age == timeout -> no trip


def test_trip_reason_reports_exact_age(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    calls = []
    d.supervise(now=120.0, on_trip=calls.append)
    assert calls == ["no heartbeat for 20.0s (> 10.0s timeout)"]     # age = now - ts (not +)


def test_trip_refused_message_starts_with_the_phrase(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    d.supervise(now=120.0, on_trip=lambda r: None)
    with pytest.raises(RuntimeError, match=r"^dead-man's switch is tripped"):
        d.beat(now=121.0)


def test_bare_filename_path_uses_cwd(tmp_path, monkeypatch):
    # a path with no directory component must fall back to "." (cwd), not "" or None
    monkeypatch.chdir(tmp_path)
    d = DeadMansSwitch("heartbeat.json", timeout_s=10)
    d.beat(now=100.0)
    assert d.read().ts == 100.0


def test_reset_seq_increments_from_previous(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    d.beat(now=101.0)                          # seq 2
    d.supervise(now=200.0, on_trip=lambda r: None)
    hb = d.reset(now=300.0)
    assert hb.seq == 3                          # prev.seq(2) + 1


def test_reset_on_fresh_switch_starts_seq_at_one(tmp_path):
    hb = _dms(tmp_path, timeout=10).reset(now=5.0)   # no prior heartbeat
    assert hb.seq == 1


def test_heartbeat_default_reason_is_empty(tmp_path):
    d = _dms(tmp_path)
    d.beat(now=1.0)
    assert d.read().reason == ""


# -- mutation hardening (mutmut 3): what the trip and the reset PERSIST, and how -------
def test_trip_persists_the_last_beat_time_and_the_reason(tmp_path):
    # the latched heartbeat keeps WHEN the bot was last alive and WHY it was tripped:
    # that is what beat() reports when it refuses and what an operator reads
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    calls = []
    d.supervise(now=120.0, on_trip=calls.append)
    hb = d.read()
    assert hb.tripped is True and hb.ts == 100.0
    assert hb.reason == calls[0] == "no heartbeat for 20.0s (> 10.0s timeout)"


def test_reset_persists_the_recovery_time_and_an_open_latch(tmp_path):
    d = _dms(tmp_path, timeout=10)
    d.beat(now=100.0)
    d.supervise(now=120.0, on_trip=lambda r: None)
    hb = d.reset(now=200.0)
    assert hb.ts == 200.0 and hb.tripped is False
    assert d.read() == hb


def test_heartbeat_is_written_through_a_tmp_file_in_the_same_directory(tmp_path, monkeypatch):
    # os.replace is only atomic within one filesystem: the temp file must live next to
    # the heartbeat (not in the system temp dir or the cwd) and be recognizable as .tmp
    import os

    replaced = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    d = _dms(tmp_path)
    d.beat(now=1.0)
    (src, dst), = replaced
    assert dst == d.path
    assert os.path.dirname(src) == os.path.dirname(d.path)
    assert src.endswith(".tmp")


def test_failed_write_leaves_no_tmp_file_and_keeps_the_error(tmp_path, monkeypatch):
    import os

    def boom(src, dst):
        raise OSError("disk full")

    d = _dms(tmp_path)
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        d.beat(now=1.0)
    assert os.listdir(os.path.dirname(d.path)) == []      # the temp file was cleaned up
    assert d.read() is None                                # and nothing was half-written


def test_bare_filename_creates_no_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    DeadMansSwitch("heartbeat.json", timeout_s=10)
    assert list(tmp_path.iterdir()) == []                  # cwd is reused, nothing created
