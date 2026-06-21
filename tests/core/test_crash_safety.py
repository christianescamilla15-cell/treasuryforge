"""Crash-only journal + tamper-evident audit log."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from treasuryforge import (
    AuditLog,
    Intent,
    Journal,
    MarketTick,
    PolicyConfig,
    PolicyEngine,
    Side,
    SimWallet,
    verify_chain,
)

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(os.path.dirname(HERE))


def _policy():
    return PolicyEngine(PolicyConfig(
        allowed_symbols=frozenset({"TOKEN"}), max_notional_per_tx=500.0,
        max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.15, fee_rate=0.001))


# -- journal -----------------------------------------------------------------
def test_breaker_survives_a_hard_process_crash(tmp_path):
    """The bug Phase-2 found: a restart silently un-trips a latched breaker.
    Run a child that trips the breaker then os._exit(1) with no clean shutdown;
    a fresh engine restored from the journal must STILL be tripped."""
    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.run([sys.executable, os.path.join(HERE, "_crash_child.py"), str(tmp_path)],
                          cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 1, proc.stderr      # confirms the hard-exit path ran

    journal = Journal(str(tmp_path))
    state = journal.load_state()
    assert state is not None and state["policy"]["tripped"] is True

    revived = _policy()
    revived.restore(state["policy"])
    assert revived.tripped
    w = SimWallet.from_snapshot(state["wallet"])
    v = revived.evaluate(Intent("TOKEN", Side.SELL, 1.0),
                         MarketTick("TOKEN", 200.0, 999), w)   # even if price recovered
    assert not v.allowed and "circuit_breaker" in v.reason


def test_checkpoint_is_atomic_valid_json(tmp_path):
    j = Journal(str(tmp_path))
    for i in range(50):
        j.checkpoint({"policy": {"tripped": i % 2 == 0}, "wallet": {"quote": float(i)}})
    # the file must always be a single complete, parseable checkpoint
    with open(j.state_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["wallet"]["quote"] == 49.0


def test_ledger_tolerates_a_torn_final_line(tmp_path):
    j = Journal(str(tmp_path))
    j.append_event({"ts": 0, "side": "BUY"})
    j.append_event({"ts": 1, "side": "SELL"})
    # simulate a crash mid-write: append a partial, unterminated JSON fragment
    with open(j.ledger_path, "a", encoding="utf-8") as f:
        f.write('{"ts": 2, "side": "BU')
    events = j.read_ledger()
    assert len(events) == 2 and events[-1]["ts"] == 1     # torn line dropped, rest intact


# -- audit log ---------------------------------------------------------------
def test_audit_chain_verifies_when_intact(tmp_path):
    key = b"test-secret-key"
    log = AuditLog(str(tmp_path / "audit.jsonl"), key)
    for i in range(10):
        log.record({"ts": i, "allowed": i % 3 != 0})
    assert verify_chain(str(tmp_path / "audit.jsonl"), key) is True


def test_audit_chain_detects_tampering(tmp_path):
    key = b"test-secret-key"
    path = str(tmp_path / "audit.jsonl")
    log = AuditLog(path, key)
    for i in range(5):
        log.record({"ts": i, "allowed": True})

    lines = open(path, encoding="utf-8").read().splitlines()
    rec = json.loads(lines[2])
    rec["entry"]["allowed"] = False            # forge a past decision
    lines[2] = json.dumps(rec, separators=(",", ":"), sort_keys=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    assert verify_chain(path, key) is False


def test_audit_chain_detects_deletion(tmp_path):
    key = b"k"
    path = str(tmp_path / "audit.jsonl")
    log = AuditLog(path, key)
    for i in range(5):
        log.record({"ts": i})
    lines = open(path, encoding="utf-8").read().splitlines()
    del lines[2]                                # drop a record
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    assert verify_chain(path, key) is False
