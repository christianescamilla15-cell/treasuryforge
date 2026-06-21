"""Sign-without-send VERDICT logic (SignCheck). The actual eth/SDK signing is VPS-
only (deps quarantined) and validated by running scripts/hl_sign_check.py there;
here we pin the pass/fail rules that decide whether a signature is trustworthy."""

from __future__ import annotations

from treasuryforge.exchanges.hyperliquid.signer import SignCheck

_SIG = {"r": "0x1", "s": "0x2", "v": 27}


def _chk(agent, authorized, recovered):
    return SignCheck(agent_address=agent, authorized_agents=tuple(authorized),
                     signature=_SIG, recovered=recovered)


def test_ok_when_in_authorized_list_and_recovers_case_insensitive():
    c = _chk("0xAbC123", ["0xother", "0xabc123"], "0xABC123")   # membership, case-insensitive
    assert c.is_authorized and c.recovers_to_agent and c.ok


def test_not_authorized_when_agent_not_in_list():
    c = _chk("0xaaa", ["0xbbb", "0xccc"], "0xaaa")
    assert not c.is_authorized and not c.ok


def test_not_ok_when_signature_recovers_to_wrong_address():
    c = _chk("0xaaa", ["0xaaa"], "0xbbb")
    assert c.is_authorized and not c.recovers_to_agent and not c.ok


def test_fails_when_no_agents_authorized_on_chain():
    c = _chk("0xaaa", [], "0xaaa")
    assert not c.is_authorized and not c.ok


def test_recovery_skipped_is_not_counted_as_recovered():
    c = _chk("0xaaa", ["0xaaa"], None)
    assert c.is_authorized and not c.recovers_to_agent
