"""Unit tests for the arm preflight checks."""

from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

from scripts import preflight_arm
from treasuryforge.journal import Journal

# The eth/SDK deps are quarantined on the VPS (see treasuryforge/exchanges/hyperliquid/signer.py),
# so the suite must not import eth_account. Golden value, derived ONCE with eth-account 0.13:
#   Account.from_key("0x" + "a" * 64).address
# It keeps the real EIP-55 mixed casing that HL's lowercase list must still match.
_KEY = "0x" + "a" * 64
_ADDRESS = "0x8fd379246834eac74B8419FfdA202CF8051F7A03"


def _derive(agent_key: str) -> str:
    assert agent_key == _KEY, "only the pinned test key has a golden address"
    return _ADDRESS


def check_all(**kw):
    kw.setdefault("derive_address", _derive)
    return preflight_arm.check_all(**kw)



class MockInfo:
    def __init__(self, authorized_list: list[str], collateral: float) -> None:
        self.authorized_list = authorized_list
        self._collateral = collateral

    def authorized_agents(self, master: str) -> list[str]:
        return self.authorized_list

    def available_collateral(self, master: str) -> float:
        return self._collateral


@pytest.fixture
def arm_env():
    d = tempfile.mkdtemp()
    relay_path = os.path.join(d, "relay.json")

    # default fresh relay
    with open(relay_path, "w", encoding="utf-8") as f:
        json.dump({"ts": 100000}, f)

    # default clear policy
    policy_dir = os.path.join(d, "policy")
    Journal(policy_dir).checkpoint({"_tripped": False})

    yield d, relay_path

    shutil.rmtree(d)


def test_arm_preflight_success(arm_env):
    state_dir, relay_path = arm_env

    agent_key = _KEY
    agent_address = _derive(agent_key)
    master = "0x" + "b" * 40

    mock_info = MockInfo(authorized_list=[agent_address], collateral=1200.0)

    # Run check_all at ts 100200 (age = 200s, fresh)
    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master
    )
    assert ok is True


def test_arm_preflight_auth_is_case_insensitive(arm_env):
    # HL returns agent addresses LOWERCASE; Account.from_key returns EIP-55 checksum.
    # A valid authorization must still match despite the case difference (the bug we hit live).
    state_dir, relay_path = arm_env
    agent_key = _KEY
    agent_address = _derive(agent_key)          # checksum casing
    master = "0x" + "b" * 40
    mock_info = MockInfo(authorized_list=[agent_address.lower()], collateral=1200.0)

    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master,
    )
    assert ok is True


def test_arm_preflight_unauthorized_agent(arm_env):
    state_dir, relay_path = arm_env

    agent_key = _KEY
    master = "0x" + "b" * 40

    # empty authorized list
    mock_info = MockInfo(authorized_list=[], collateral=1200.0)

    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master
    )
    assert ok is False


def test_arm_preflight_low_collateral(arm_env):
    state_dir, relay_path = arm_env

    agent_key = _KEY
    agent_address = _derive(agent_key)
    master = "0x" + "b" * 40

    # collateral $500 -> 1% is $5 < $10 minimum
    mock_info = MockInfo(authorized_list=[agent_address], collateral=500.0)

    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master
    )
    assert ok is False


def test_arm_preflight_stale_relay(arm_env):
    state_dir, relay_path = arm_env

    agent_key = _KEY
    agent_address = _derive(agent_key)
    master = "0x" + "b" * 40

    mock_info = MockInfo(authorized_list=[agent_address], collateral=1200.0)

    # Run check_all at ts 102000 (age = 2000s > 900s, stale)
    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=102000,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master
    )
    assert ok is False


def test_arm_preflight_tripped_breaker(arm_env):
    state_dir, relay_path = arm_env

    agent_key = _KEY
    agent_address = _derive(agent_key)
    master = "0x" + "b" * 40

    mock_info = MockInfo(authorized_list=[agent_address], collateral=1200.0)

    # Trip the circuit breaker in policy state
    policy_dir = os.path.join(state_dir, "policy")
    Journal(policy_dir).checkpoint({"_tripped": True})

    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master
    )
    assert ok is False


def test_arm_preflight_low_collateral_with_custom_tier(arm_env):
    state_dir, relay_path = arm_env

    agent_key = _KEY
    agent_address = _derive(agent_key)
    master = "0x" + "b" * 40

    # collateral $500 -> 1% is $5 < $10 minimum (fails by default)
    # but if we use tier = 0.05, 5% is $25 >= $10 minimum (should pass!)
    mock_info = MockInfo(authorized_list=[agent_address], collateral=500.0)

    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=mock_info,
        mock_agent_key=agent_key,
        mock_master=master,
        tier=0.05
    )
    assert ok is True



def test_arm_preflight_fails_closed_without_signing_deps(arm_env):
    # Off the VPS the quarantined eth deps are absent: the signer raises RuntimeError with the
    # install hint. The preflight must report NOT safe to arm, never crash or pass.
    state_dir, relay_path = arm_env

    def _missing(_key: str) -> str:
        raise RuntimeError("eth_account is required to sign (VPS only)")

    ok = check_all(
        mode="paper",
        state_dir=state_dir,
        relay_path=relay_path,
        now=100200,
        mock_info=MockInfo(authorized_list=[_ADDRESS], collateral=1200.0),
        mock_agent_key=_KEY,
        mock_master="0x" + "b" * 40,
        derive_address=_missing,
    )
    assert ok is False
