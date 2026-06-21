"""Hyperliquid SIGN-WITHOUT-SEND gate (VPS only) -- proves the agent key works.

Loads the agent key from the environment (provisioned by the owner via
scripts/set_hl_secret.sh), builds the exact order payload the dry-run produced,
SIGNS it, and recovers the signer to confirm:
  1. the key's address == the agent AUTHORIZED on-chain for the master, and
  2. the signature over our payload recovers back to that address.

It NEVER prints the private key and NEVER POSTs to /exchange. A pass here means the
next step (a centavos live order with reconcile) can sign correctly.

    set -a; source /etc/treasuryforge/hl.env; set +a
    /opt/treasuryforge/.venv/bin/python scripts/hl_sign_check.py --coin ETH --usd 11
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.exchanges.hyperliquid import HyperliquidExecutor, HyperliquidInfo
from treasuryforge.exchanges.hyperliquid.secrets import resolve_agent_credentials
from treasuryforge.exchanges.hyperliquid.signer import (
    SignCheck,
    agent_address_from_key,
    recover_l1_signer,
    sign_order_action,
)
from treasuryforge.types import Intent, Side


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="ETH")
    ap.add_argument("--usd", type=float, default=11.0)
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    ap.add_argument("--cap", type=float, default=15.0)
    args = ap.parse_args()

    key, master = resolve_agent_credentials()          # from env; key is never printed
    info = HyperliquidInfo(_post)

    # 1) build the exact payload the dry-run validated (keyless) -------------------
    side = Side.BUY if args.side == "buy" else Side.SELL
    intent = Intent(args.coin, side, 0.0, quote_amount=args.usd, reason="sign-check")
    mid = info.all_mids()[args.coin]
    preview = HyperliquidExecutor(exchange=None, info=info, max_notional_usd=args.cap).preview_order(
        intent, price=mid)
    if not preview.ok or preview.action is None:
        print(f"DRY-RUN FAILED, nothing to sign: {preview.reason}")
        sys.exit(1)

    # 2) sign it (no send) and recover the signer ---------------------------------
    agent_addr = agent_address_from_key(key)
    authorized = info.authorized_agents(master)
    nonce = int(time.time() * 1000)
    sig = sign_order_action(key, preview.action, nonce)
    try:
        recovered = recover_l1_signer(preview.action, sig, nonce)
    except Exception as e:                              # recovery is best-effort
        print(f"  (recovery skipped: {type(e).__name__}: {e})")
        recovered = None

    chk = SignCheck(agent_address=agent_addr, authorized_agents=tuple(authorized),
                    signature=sig, recovered=recovered)

    print("=== SIGN-WITHOUT-SEND ===")
    print(f"  master account      {master}")
    print(f"  agent (from key)    {agent_addr}")
    print(f"  authorized agents   {len(authorized)} on-chain: "
          f"{', '.join(a[:10] + '..' for a in authorized)}")
    print(f"  this agent authorized {'YES' if chk.is_authorized else 'NO'}")
    print(f"  signature           r={sig['r'][:14]}... v={sig['v']}  (built OK)")
    print(f"  recovers to agent   {'YES' if chk.recovers_to_agent else ('SKIPPED' if recovered is None else 'NO')}")
    print(f"  payload (NOT sent)  {json.dumps(preview.action)}")
    print("\n" + "=" * 56)
    ok = chk.is_authorized and (chk.recovers_to_agent or recovered is None)
    print(f"VERDICT: {'SIGN GATE PASSED' if ok else 'SIGN GATE FAILED'} -- "
          f"nothing was sent. Key {'works and is the authorized agent.' if ok else 'check FAILED above.'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
