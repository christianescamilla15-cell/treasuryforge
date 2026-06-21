"""Mutation-hardening for the strategy graveyard: strict revival-condition
boundaries, exact unmet messages, the empty-fingerprint guard, and field
round-trip through the append-only JSONL store."""

from __future__ import annotations

from treasuryforge.risk import GraveyardEntry, StrategyGraveyard


def _entry(sid="S1", fp="fp1", revival=None):
    return GraveyardEntry(
        strategy_id=sid, hypothesis="h", market="m", date="2026-06-17",
        metrics={"dsr": 0.4}, verdict="REJECT: X", failure_mode="f",
        revival_condition=revival if revival is not None else {"dsr": [">", 0.60]},
        fingerprint=fp)


def test_revival_gt_boundary_is_strict(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(revival={"dsr": [">", 0.60]}))
    ok, unmet = g.check_revival("S1", {"dsr": 0.60})        # == threshold -> still unmet
    assert not ok and unmet == ["dsr=0.6 not > 0.6"]
    ok2, unmet2 = g.check_revival("S1", {"dsr": 0.61})
    assert ok2 and unmet2 == []


def test_revival_lt_boundary_is_strict(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(revival={"ruin": ["<", 0.05]}))
    ok, unmet = g.check_revival("S1", {"ruin": 0.05})        # == threshold -> still unmet
    assert not ok and unmet == ["ruin=0.05 not < 0.05"]
    ok2, _ = g.check_revival("S1", {"ruin": 0.04})
    assert ok2


def test_revival_missing_metric_message(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(revival={"dsr": [">", 0.6]}))
    ok, unmet = g.check_revival("S1", {})
    assert not ok and unmet == ["dsr: not measured"]


def test_unknown_strategy_message(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    ok, unmet = g.check_revival("NOPE", {"x": 1})
    assert not ok and unmet == ["no buried strategy 'NOPE'"]


def test_revival_all_conditions_met(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(revival={"dsr": [">", 0.6], "ruin": ["<", 0.05]}))
    ok, unmet = g.check_revival("S1", {"dsr": 0.7, "ruin": 0.01})
    assert ok and unmet == []


def test_empty_fingerprint_does_not_match(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(fp=""))
    assert g.find_by_fingerprint("") is None                # the `e.fingerprint and ...` guard


def test_fingerprint_match_and_miss(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(sid="A", fp="abc"))
    hit = g.find_by_fingerprint("abc")
    assert hit is not None and hit.strategy_id == "A"
    assert g.find_by_fingerprint("zzz") is None


def test_all_empty_when_no_file(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "none.jsonl"))
    assert g.all() == []


def test_bury_appends_in_order_and_roundtrips_fields(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(sid="A"))
    g.bury(_entry(sid="B"))
    rows = g.all()
    assert [r.strategy_id for r in rows] == ["A", "B"]
    assert rows[0].revival_condition == {"dsr": [">", 0.60]}
    assert rows[0].metrics == {"dsr": 0.4}
