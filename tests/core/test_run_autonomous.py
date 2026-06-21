"""Unit tests for scripts/run_autonomous.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.run_autonomous import _gate_open, _interval_sharpe, _maybe_execute, _trial_sharpes
from treasuryforge.journal import Journal
from treasuryforge.policy import PolicyConfig, PolicyEngine


def test_interval_sharpe_handles_degenerate_inputs():
    assert _interval_sharpe([]) is None                 # too few
    assert _interval_sharpe([0.01]) is None             # n < 2
    assert _interval_sharpe([0.005, 0.005]) is None     # zero variance
    s = _interval_sharpe([0.003, 0.001])                # mean 0.002, std 0.001 -> 2.0
    assert s is not None and abs(s - 2.0) < 1e-9


def test_trial_sharpes_aggregates_only_computable_coins():
    j_good = MagicMock(spec=Journal)
    j_good.read_ledger.return_value = [{"kind": "scalp", "r": 0.003}, {"kind": "scalp", "r": 0.001}]
    j_flat = MagicMock(spec=Journal)
    j_flat.read_ledger.return_value = [{"kind": "scalp", "r": 0.002}, {"kind": "scalp", "r": 0.002}]
    j_empty = MagicMock(spec=Journal)
    j_empty.read_ledger.return_value = []
    out = _trial_sharpes({"A": j_good, "B": j_flat, "C": j_empty})
    assert out == [2.0]                                 # only the coin with non-zero variance


def _policy(max_notional: float) -> PolicyEngine:
    return PolicyEngine(PolicyConfig(
        allowed_symbols=frozenset({"BTC"}),
        max_notional_per_tx=max_notional,
        max_tx_per_window=5,
        window_steps=3600,
        max_drawdown_pct=0.10,
        min_notional_per_tx=10.0,
        max_notional_per_window=100.0,
        spend_window_steps=3600,
        fee_rate=0.001,
    ))


def test_gate_open_requires_both_gate_and_committee_approval():
    journal = MagicMock(spec=Journal)
    journal.read_ledger.return_value = [
        {"kind": "scalp", "ts": 1000, "r": 0.01},
        {"kind": "scalp", "ts": 2000, "r": -0.005},
    ]

    with patch("scripts.run_autonomous._GATE") as mock_gate, \
         patch("treasuryforge.consultants.Committee") as mock_committee_cls:

        mock_gate_evaluate_res = MagicMock()
        mock_gate.evaluate.return_value = mock_gate_evaluate_res

        mock_committee = MagicMock()
        mock_committee_cls.return_value = mock_committee
        mock_comm_verdict = MagicMock()
        mock_committee.review.return_value = mock_comm_verdict

        # Case 1: Standard gate says False -> _gate_open returns False immediately
        mock_gate_evaluate_res.deploy = False
        assert _gate_open(journal) is False
        mock_committee.review.assert_not_called()

        # Case 2: Standard gate says True, Committee says False -> _gate_open returns False
        mock_gate_evaluate_res.deploy = True
        mock_comm_verdict.approved = False
        mock_comm_verdict.render.return_value = "VETO:regime"
        assert _gate_open(journal) is False
        mock_committee.review.assert_called_once()

        # Case 3: Both standard gate and Committee approve -> _gate_open returns True
        mock_comm_verdict.approved = True
        mock_committee.review.reset_mock()
        assert _gate_open(journal) is True
        mock_committee.review.assert_called_once()


def test_maybe_execute_calculates_notional_from_tier_and_collateral():
    live = {
        "info": MagicMock(),
        "master": "0xmaster",
        "exchange": MagicMock(),
        "two_phase": MagicMock(),
        "mgr": MagicMock()
    }
    # Mock collateral to $20 USDC
    live["info"].available_collateral.return_value = 20.0
    journal = MagicMock(spec=Journal)

    with patch("scripts.run_autonomous._gate_open", return_value=True):
        # Case A: tier = 0.01 (1%), notional = $0.20 < $10.0 -> Sigue en papel
        with patch("builtins.print") as mock_print:
            _maybe_execute(live, "USDC", "ENTER", journal, tier=0.01)
            live["two_phase"].assert_not_called()
            printed_msgs = "".join(call[0][0] for call in mock_print.call_args_list)
            assert "Sigue en papel" in printed_msgs

        # Case B: tier = 0.55 (55%), notional = $11.0 >= $10.0 -> Live trade executed
        live["two_phase"].reset_mock()
        mock_mgr_instance = MagicMock()
        live["mgr"].return_value = mock_mgr_instance

        _maybe_execute(live, "USDC", "ENTER", journal, tier=0.55)

        # Verify the available_collateral call
        live["info"].available_collateral.assert_called_with("0xmaster")
        # Verify two_phase initialization with correct max_notional_usd (1.2 * 11.0 = 13.2)
        live["two_phase"].assert_called_once_with(
            live["exchange"](), live["info"], "0xmaster", max_notional_usd=13.2
        )
        # Verify submission
        mock_mgr_instance.submit.assert_called_once()


def test_maybe_execute_policy_denies_oversized_enter():
    # tier 0.55 of $20 = $11 notional, but the per-tx cap is $4 -> policy DENIES, no order.
    live = {"info": MagicMock(), "master": "0xm", "exchange": MagicMock(),
            "two_phase": MagicMock(), "mgr": MagicMock(),
            "policy": _policy(max_notional=4.0), "policy_journal": MagicMock(spec=Journal)}
    live["info"].available_collateral.return_value = 20.0
    journal = MagicMock(spec=Journal)

    with patch("scripts.run_autonomous._gate_open", return_value=True), \
         patch("builtins.print") as mock_print:
        _maybe_execute(live, "BTC", "ENTER", journal, tier=0.55, price=100.0)
        live["two_phase"].assert_not_called()                 # blocked before the rail
        printed = "".join(c[0][0] for c in mock_print.call_args_list)
        assert "policy dispose" in printed and "DENY:notional" in printed


def test_maybe_execute_policy_allows_and_registers_fill():
    # tier 0.55 of $20 = $11 notional, within the $15 cap -> ALLOW, submit, and record the fill.
    policy = _policy(max_notional=15.0)
    live = {"info": MagicMock(), "master": "0xm", "exchange": MagicMock(),
            "two_phase": MagicMock(), "mgr": MagicMock(),
            "policy": policy, "policy_journal": MagicMock(spec=Journal)}
    live["info"].available_collateral.return_value = 20.0
    out = MagicMock()
    out.state.value = "FILLED"
    out.reason = "ok"
    mgr_instance = MagicMock()
    mgr_instance.submit.return_value = out
    live["mgr"].return_value = mgr_instance
    journal = MagicMock(spec=Journal)

    with patch("scripts.run_autonomous._gate_open", return_value=True):
        _maybe_execute(live, "BTC", "ENTER", journal, tier=0.55, price=100.0)
        mgr_instance.submit.assert_called_once()
        assert len(policy._recent_ts) == 1                    # register_fill counted it
        live["policy_journal"].append_event.assert_called_once()  # latched state persisted


def test_maybe_execute_alerts_on_gate_cross_once():
    import scripts.run_autonomous as ra
    ra._GATE_ALERTED.clear()
    live = {"info": MagicMock(), "master": "0xm", "exchange": MagicMock(),
            "two_phase": MagicMock(), "mgr": MagicMock(),
            "policy": _policy(max_notional=4.0), "policy_journal": MagicMock(spec=Journal)}
    live["info"].available_collateral.return_value = 20.0   # tier 0.55 -> $11 > $4 cap -> policy denies
    journal = MagicMock(spec=Journal)

    with patch("scripts.run_autonomous._gate_open", return_value=True), \
         patch("scripts.run_autonomous._notify") as mock_notify:
        _maybe_execute(live, "BTC", "ENTER", journal, tier=0.55, price=100.0)
        assert any("GATE OPEN" in c.args[0] for c in mock_notify.call_args_list)
        mock_notify.reset_mock()
        _maybe_execute(live, "BTC", "ENTER", journal, tier=0.55, price=100.0)   # same coin again
        assert not any("GATE OPEN" in c.args[0] for c in mock_notify.call_args_list)  # deduped


def test_notify_swallows_send_errors(monkeypatch):
    import scripts.run_autonomous as ra
    import scripts.telegram_report as tr

    def boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(tr, "send", boom)
    ra._notify("x")                                          # must NOT raise -- trading is sacred
