"""Arm preflight check (go/no-go) — verify Hyperliquid and relay conditions before arming.

Runs checks:
  1. API Up
  2. Agent Key Authorized
  3. Available Collateral
  4. Relay Freshness
  5. Kill-Switch/Breaker Tripped Check
  6. Micro Tier Sizing Check (1% >= $10)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

from eth_account import Account

from treasuryforge.exchanges.hyperliquid.info import HyperliquidInfo
from treasuryforge.exchanges.hyperliquid.secrets import resolve_agent_credentials
from treasuryforge.journal import Journal
from treasuryforge.relay_feed import load_snapshot


def _post(body: dict) -> dict:
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _check_api(mode: str) -> bool:
    print("[..] Checking Hyperliquid API reachability...", end="", flush=True)
    if mode == "paper":
        print(" [PASS] (mocked)")
        return True
    try:
        _post({"type": "meta"})
        print(" [PASS] Responsive")
        return True
    except Exception as e:
        print(f" [FAIL] API unreachable: {e}")
        return False


def _check_auth(api_up: bool, info: HyperliquidInfo | None, agent_key: str, master: str) -> bool:
    if not (api_up and info and master):
        print(" [FAIL] Agent auth check skipped (API down or credentials missing)")
        return False
    print("[..] Checking Agent Key authorization...", end="", flush=True)
    try:
        agent_address = Account.from_key(agent_key).address
        agents = info.authorized_agents(master)
        # EVM addresses are case-insensitive; HL returns lowercase, Account.from_key returns
        # EIP-55 checksum. Compare case-folded or a valid auth reads as a false [FAIL].
        if agent_address.lower() in {a.lower() for a in agents}:
            print(f" [PASS] Agent {agent_address} authorized for master {master}")
            return True
        print(f" [FAIL] Agent {agent_address} NOT authorized for master {master} on-chain!")
        return False
    except Exception as e:
        print(f" [FAIL] Auth check failed: {e}")
        return False


def _check_collateral(api_up: bool, info: HyperliquidInfo | None, master: str) -> float:
    if not (api_up and info and master):
        print(" [FAIL] Collateral check skipped")
        return 0.0
    print("[..] Fetching account collateral...", end="", flush=True)
    try:
        collateral = info.available_collateral(master)
        print(f" [PASS] Available collateral: ${collateral:.2f}")
        return collateral
    except Exception as e:
        print(f" [FAIL] Failed to fetch collateral: {e}")
        return 0.0


def _check_relay(relay_path: str, now: int) -> bool:
    print("[..] Checking local relay freshness...", end="", flush=True)
    snap = load_snapshot(relay_path)
    relay_ts = snap.get("ts", 0)
    if relay_ts > 0:
        age = now - relay_ts
        if age <= 900:
            print(f" [PASS] Relay is fresh (age: {age}s)")
            return True
        print(f" [FAIL] Relay is stale (age: {age}s, max allowed: 900s)")
        return False
    print(" [FAIL] Relay file missing or corrupt")
    return False


def _check_latch(state_dir: str) -> bool:
    print("[..] Checking Policy Engine latch state...", end="", flush=True)
    policy_dir = os.path.join(state_dir, "policy")
    policy_state = Journal(policy_dir).load_state()
    if policy_state and policy_state.get("_tripped", False):
        print(" [FAIL] Policy Engine circuit breaker is TRIPPED!")
        return False
    print(" [PASS] Latch is clear")
    return True


def _check_micro(collateral: float, tier: float = 0.01) -> bool:
    if collateral > 0:
        print("[..] Verifying micro-tier sizing bounds...", end="", flush=True)
        micro_tier = tier * collateral
        if micro_tier >= 10.0:
            print(f" [PASS] Micro tier size ${micro_tier:.2f} >= $10.00 minimum")
            return True
        print(f" [FAIL] Micro tier size ${micro_tier:.2f} < $10.00 minimum! (Requires >= ${10.0 / tier:.2f} collateral)")
        return False
    print(" [FAIL] Micro-tier check skipped due to zero/missing collateral")
    return False


def check_all(
    mode: str = "live",
    state_dir: str = "state",
    relay_path: str = "state/relay/funding.json",
    now: int | None = None,
    mock_info: HyperliquidInfo | None = None,
    mock_agent_key: str | None = None,
    mock_master: str | None = None,
    tier: float = 0.01
) -> bool:
    if now is None:
        now = int(time.time())

    print(f"=== ARM PREFLIGHT CHECK ({mode.upper()}) ===", flush=True)

    api_up = _check_api(mode)

    # Initialize info client
    if mode == "paper":
        info = mock_info
        agent_key = mock_agent_key or "0x" + "a" * 64
        master = mock_master or "0x" + "b" * 40
    else:
        info = HyperliquidInfo(_post)
        try:
            agent_key, master = resolve_agent_credentials()
        except Exception as e:
            print(f" [FAIL] Credentials missing: {e}")
            return False

    auth_ok = _check_auth(api_up, info, agent_key, master)
    collateral = _check_collateral(api_up, info, master)
    relay_ok = _check_relay(relay_path, now)
    latch_ok = _check_latch(state_dir)
    micro_ok = _check_micro(collateral, tier)

    all_ok = api_up and auth_ok and (collateral > 0) and relay_ok and latch_ok and micro_ok

    print("==========================================", flush=True)
    if all_ok:
        print("PREFLIGHT SUCCESS: System is safe to arm.", flush=True)
        return True
    else:
        print("PREFLIGHT FAILED: DO NOT ARM THE PROCESS.", flush=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["live", "paper"], default="live")
    ap.add_argument("--state-dir", default="state")
    ap.add_argument("--relay-path", default="state/relay/funding.json")
    ap.add_argument("--tier", type=float, default=0.01, help="capital allocation fraction (e.g., 0.01 for 1%)")
    args = ap.parse_args()

    ok = check_all(mode=args.mode, state_dir=args.state_dir, relay_path=args.relay_path, tier=args.tier)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
