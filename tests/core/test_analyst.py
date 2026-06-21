"""Unit tests for the analyst observability module."""

from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

from treasuryforge.analyst import generate_digest, render_digest_to_string
from treasuryforge.journal import Journal


@pytest.fixture
def temp_env():
    d = tempfile.mkdtemp()

    # 1. Create a dummy relay file
    relay_dir = os.path.join(d, "relay")
    os.makedirs(relay_dir, exist_ok=True)
    relay_path = os.path.join(relay_dir, "funding.json")
    with open(relay_path, "w", encoding="utf-8") as f:
        json.dump({"ts": 100000, "venues": {"BIN": {"BTC": 0.05}}}, f)

    # 2. Create orchestrator staging ledger
    orch_dir = os.path.join(d, "orchestrator")
    Journal(orch_dir).append_event({
        "kind": "stage",
        "ts": 100100,
        "strategy": "funding:BTC",
        "tier": 0.01,
        "dsr": 0.65,
        "status": "PENDING_OK"
    })

    # 3. Create dummy shadow strategy ledger
    # Passes DSR and APR gates, should check committee
    shadow_btc_dir = os.path.join(d, "shadow_btc")
    j1 = Journal(shadow_btc_dir)
    # 35 trades over 15 days, steady gains to clear gate and committee
    ts_start = 100000
    for i in range(35):
        # alternating small returns to ensure it passes recent mean + consistency checks
        r = 0.003 if i % 2 == 0 else 0.001
        j1.append_event({
            "kind": "shadow",
            "ts": ts_start + i * 40000,  # total time > 14 days (14*86400 = 1209600s)
            "r": r
        })

    # 4. Create another shadow strategy that fails the gate (too few trades)
    shadow_eth_dir = os.path.join(d, "shadow_eth")
    j2 = Journal(shadow_eth_dir)
    j2.append_event({
        "kind": "shadow",
        "ts": ts_start,
        "r": 0.05
    })

    yield d, relay_path

    shutil.rmtree(d)


def test_analyst_observability_digest(temp_env):
    state_dir, relay_path = temp_env

    # Generate digest at simulated time 100200
    # Relay age should be 100200 - 100000 = 200s (fresh)
    digest = generate_digest(
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200
    )

    assert digest["ts"] == 100200
    assert digest["relay_age_seconds"] == 200
    assert digest["relay_fresh"] is True
    assert len(digest["staged_pending"]) == 1
    assert digest["staged_pending"][0]["strategy"] == "funding:BTC"

    # Verify loaded strategies
    strats = {s["strategy"]: s for s in digest["strategies"]}
    assert len(strats) == 2
    assert "funding:BTC" in strats
    assert "funding:ETH" in strats

    # funding:BTC should clear the gate
    btc = strats["funding:BTC"]
    assert btc["trades_count"] == 35
    assert btc["gate_passed"] is True
    assert btc["status"] in ("DEPLOY", "HOLD")  # depending on whether MC ruin vetoes it (steady with MC)

    # funding:ETH should fail the gate
    eth = strats["funding:ETH"]
    assert eth["trades_count"] == 1
    assert eth["gate_passed"] is False
    assert eth["status"] == "HOLD"
    assert "Failed gate" in eth["reasons"][0]

    # Verify rendering works without throwing errors
    report = render_digest_to_string(digest)
    assert "TREASURYFORGE ANALYST DIGEST" in report
    assert "Relay Egress Status: FRESH" in report
    assert "funding:BTC" in report
    assert "funding:ETH" in report
