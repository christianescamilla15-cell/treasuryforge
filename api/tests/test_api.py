"""Contract tests for the demo API (api/main.py) — the backend the Vercel demo calls.

They pin what the browser demo relies on: every endpoint answers, the verdicts come
from the REAL PolicyEngine (same DENY:<rule> prefixes), the crash scenario trips the
breaker, and the HMAC audit chain verifies. Run by the CI job «api»:

    pip install -r api/requirements-dev.txt && pytest api/tests -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_root_lists_the_endpoints(client):
    body = client.get("/").json()
    assert body["status"] == "live"
    assert "GET  /api/health" in body["endpoints"]


def test_health_is_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_stats_lists_the_8_rules_in_order(client):
    rules = client.get("/api/stats").json()["rules"]
    assert [r["n"] for r in rules] == list(range(1, 9))
    assert rules[0]["id"] == "kill_switch" and rules[-1]["id"] == "solvency"


def test_evaluate_allows_a_normal_trade(client):
    r = client.post("/api/policy/evaluate",
                    json={"symbol": "TOKEN", "side": "BUY", "notional": 200.0, "price": 100.0})
    assert r.status_code == 200
    v = r.json()["verdict"]
    assert v == {"allowed": True, "reason": "ALLOW", "rule": None}


@pytest.mark.parametrize(("payload", "rule"), [
    ({"symbol": "TOKEN", "side": "BUY", "notional": 200.0, "price": 100.0,
      "config": {"kill_switch": True}}, "kill_switch"),
    ({"symbol": "SCAM", "side": "BUY", "notional": 200.0, "price": 100.0}, "symbol"),
    ({"symbol": "TOKEN", "side": "BUY", "notional": 900.0, "price": 100.0}, "notional"),
    ({"symbol": "TOKEN", "side": "SELL", "notional": 200.0, "price": 100.0}, "insufficient_base"),
])
def test_evaluate_denials_name_the_rule(client, payload, rule):
    v = client.post("/api/policy/evaluate", json=payload).json()["verdict"]
    assert v["allowed"] is False and v["rule"] == rule and v["reason"].startswith(f"DENY:{rule}")


def test_evaluate_rejects_invalid_input(client):
    # notional must be > 0 (pydantic) -> 422, never reaches the engine
    r = client.post("/api/policy/evaluate",
                    json={"symbol": "TOKEN", "side": "BUY", "notional": 0, "price": 100.0})
    assert r.status_code == 422


def test_evaluate_rejects_a_malformed_config(client):
    r = client.post("/api/policy/evaluate",
                    json={"symbol": "TOKEN", "side": "BUY", "notional": 1.0, "price": 1.0,
                          "config": {"max_tx_per_window": "many"}})
    assert r.status_code == 400 and "invalid config" in r.json()["detail"]


def test_backtest_crash_trips_the_breaker_and_the_audit_chain_verifies(client):
    body = client.post("/api/backtest/run", json={"scenario": "crash", "ticks": 80}).json()
    assert body["breaker"]["tripped"] is True
    assert body["denials_by_rule"].get("DENY:circuit_breaker", 0) > 0   # keys keep the DENY: prefix
    assert body["audit"]["integrity_verified"] is True


def test_backtest_rejects_out_of_range_ticks(client):
    assert client.post("/api/backtest/run", json={"ticks": 5}).status_code == 422


def test_audit_sample_is_a_verified_chain_and_clamps_n(client):
    body = client.get("/api/audit/sample", params={"n": 500}).json()
    assert body["chain_integrity_verified"] is True
    assert len(body["entries"]) == 20                    # n is clamped to [1, 20]
