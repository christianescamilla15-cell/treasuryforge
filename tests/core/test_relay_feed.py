"""The relay feed must FAIL CLOSED: a stale or missing snapshot yields None venues, never
a phantom spread. Only a fresh snapshot releases the relayed (Binance/Bybit) funding."""

from __future__ import annotations

from treasuryforge.relay_feed import load_snapshot, relay_funding

_SNAP = {"ts": 1000, "venues": {"BIN": {"XRP": -0.05, "ZEC": -0.38}, "BYB": {"XRP": -0.04}}}


def test_fresh_snapshot_releases_funding() -> None:
    out = relay_funding(_SNAP, "XRP", now=1100, max_age_s=900)
    assert out == {"BIN": -0.05, "BYB": -0.04}


def test_stale_snapshot_drops_every_venue_to_none() -> None:
    out = relay_funding(_SNAP, "XRP", now=9999, max_age_s=900)   # 8999s old > 900s budget
    assert out == {"BIN": None, "BYB": None}


def test_coin_absent_from_a_venue_is_none() -> None:
    out = relay_funding(_SNAP, "ZEC", now=1100, max_age_s=900)
    assert out == {"BIN": -0.38, "BYB": None}                     # BYB has no ZEC


def test_boundary_exactly_at_budget_is_still_fresh() -> None:
    out = relay_funding(_SNAP, "XRP", now=1900, max_age_s=900)    # exactly 900s old
    assert out["BIN"] == -0.05


def test_missing_or_corrupt_file_loads_empty_not_crash(tmp_path) -> None:
    assert load_snapshot(str(tmp_path / "nope.json")) == {"ts": 0, "venues": {}}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_snapshot(str(bad)) == {"ts": 0, "venues": {}}


def test_empty_snapshot_yields_no_venues() -> None:
    assert relay_funding({"ts": 0, "venues": {}}, "XRP", now=100, max_age_s=900) == {}
