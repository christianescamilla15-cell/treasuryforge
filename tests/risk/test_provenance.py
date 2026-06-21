"""Reproducibility pack — deterministic content hashes + provenance metadata."""

from __future__ import annotations

from treasuryforge.risk import canonical_hash, make_provenance

DATA = [0.001, -0.002, 0.003]
CONFIG = {"entry_z": 2.0, "exit_z": 0.5, "fee": 0.0005}
STRAT = {"name": "pairs", "x": "AVAX", "y": "LTC", "beta": 1.23}


def _pack(timestamp="2026-06-17T00:00:00Z", **over):
    kw = dict(data=DATA, config=CONFIG, strategy=STRAT, report="VERDICT: REJECT")
    kw.update(over)
    return make_provenance(timestamp=timestamp, **kw)


def test_canonical_hash_is_deterministic_and_order_independent():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert canonical_hash([1, 2]) != canonical_hash([2, 1])


def test_same_inputs_reproduce():
    a, b = _pack(), _pack()
    assert a.content_fingerprint() == b.content_fingerprint()
    assert a.reproduces(b)
    assert a.pack_id == b.pack_id            # same timestamp too -> identical id


def test_changed_data_breaks_fingerprint():
    base = _pack()
    changed = _pack(data=[0.001, -0.002, 0.004])   # one number differs
    assert not base.reproduces(changed)
    assert base.data_hash != changed.data_hash


def test_changed_config_breaks_fingerprint():
    base = _pack()
    changed = _pack(config={**CONFIG, "exit_z": 0.6})
    assert base.config_hash != changed.config_hash
    assert not base.reproduces(changed)


def test_timestamp_changes_pack_id_but_not_content_fingerprint():
    a = _pack(timestamp="2026-06-17T00:00:00Z")
    b = _pack(timestamp="2026-06-18T00:00:00Z")
    assert a.pack_id != b.pack_id                 # pack id includes the timestamp
    assert a.content_fingerprint() == b.content_fingerprint()   # but the inputs match


def test_pack_records_environment_and_render():
    p = _pack()
    assert "python" in p.environment
    out = p.render()
    assert "REPRODUCIBILITY PACK" in out and "pack id" in out
