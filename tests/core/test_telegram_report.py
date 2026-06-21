"""Unit tests for the read-only Telegram status report."""

from __future__ import annotations

import tempfile

from scripts.telegram_report import _interval_sharpe, build_digest, send


def test_interval_sharpe_degenerate():
    assert _interval_sharpe([]) is None
    assert _interval_sharpe([0.01]) is None
    assert _interval_sharpe([0.002, 0.002]) is None          # zero variance
    s = _interval_sharpe([0.003, 0.001])
    assert s is not None and abs(s - 2.0) < 1e-9


def test_digest_handles_empty_state():
    with tempfile.TemporaryDirectory() as d:
        out = build_digest(state_dir=d)
        assert "TreasuryForge" in out and "sin track record" in out


def test_send_without_credentials_fails_safely(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert send("hi") is False                                 # no network attempted
