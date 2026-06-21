"""Strategy graveyard — buried rejections + revival conditions."""

from __future__ import annotations

from treasuryforge.risk import GraveyardEntry, StrategyGraveyard


def _entry(sid="PAIRS_AVAX_LTC", fp="fp123"):
    return GraveyardEntry(
        strategy_id=sid,
        hypothesis="AVAX and LTC spread mean-reverts",
        market="hyperliquid 1h",
        date="2026-06-17",
        metrics={"dsr": 0.441, "stress_ruin": 0.854, "expected_dd": 0.40},
        verdict="REJECT: EDGE_IS_NOT_RELIABLE",
        failure_mode="DSR<0.60, purged-CV unstable, stress ruin 85%",
        revival_condition={"dsr": [">", 0.60], "stress_ruin": ["<", 0.05],
                           "expected_dd": ["<", 0.20]},
        fingerprint=fp,
    )


def test_bury_and_read_back(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "graveyard.jsonl"))
    g.bury(_entry())
    g.bury(_entry(sid="TSMOM_BTC", fp="fp999"))
    rows = g.all()
    assert len(rows) == 2
    assert rows[0].strategy_id == "PAIRS_AVAX_LTC"
    assert rows[0].revival_condition["dsr"] == [">", 0.60]


def test_catches_disguised_corpse_by_fingerprint(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry(fp="abc"))
    # a "new" strategy that hashes the same as a buried one
    hit = g.find_by_fingerprint("abc")
    assert hit is not None and hit.strategy_id == "PAIRS_AVAX_LTC"
    assert g.find_by_fingerprint("different") is None


def test_revival_blocked_until_all_conditions_met(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry())
    # still bad: dsr improved but stress ruin still high
    ok, unmet = g.check_revival("PAIRS_AVAX_LTC",
                                {"dsr": 0.65, "stress_ruin": 0.40, "expected_dd": 0.18})
    assert not ok
    assert any("stress_ruin" in u for u in unmet)


def test_revival_allowed_when_conditions_met(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    g.bury(_entry())
    ok, unmet = g.check_revival("PAIRS_AVAX_LTC",
                                {"dsr": 0.72, "stress_ruin": 0.03, "expected_dd": 0.15})
    assert ok and unmet == []


def test_revival_unknown_strategy(tmp_path):
    g = StrategyGraveyard(str(tmp_path / "g.jsonl"))
    ok, unmet = g.check_revival("NOPE", {})
    assert not ok and "no buried strategy" in unmet[0]
