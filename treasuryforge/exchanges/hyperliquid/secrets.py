"""Resolve the Hyperliquid AGENT credentials — env first (VPS), keychain second.

The bot signs with an AGENT (API) wallet that can TRADE but NOT withdraw — the
on-chain equivalent of the Bitso trade-only key. It is identified by:
  HL_AGENT_KEY        the agent wallet's private key (0x + 64 hex) — SECRET
  HL_ACCOUNT_ADDRESS  your MAIN account address the agent acts for (0x...) — public

Like the Bitso secret, the agent key never passes through the chat: you provision
it on the VPS yourself (scripts/set_hl_secret.sh) and the code reads it from the
environment. A leaked agent key can place trades inside your caps but CANNOT
withdraw your funds.
"""

from __future__ import annotations

import os

_ENV_KEY = "HL_AGENT_KEY"
_ENV_ADDR = "HL_ACCOUNT_ADDRESS"


def resolve_agent_credentials() -> tuple[str, str]:
    key = os.environ.get(_ENV_KEY)
    addr = os.environ.get(_ENV_ADDR)
    if key and addr:
        return key, addr
    raise RuntimeError(
        "No Hyperliquid agent credentials. Set HL_AGENT_KEY + HL_ACCOUNT_ADDRESS "
        "(VPS, via scripts/set_hl_secret.sh) — the agent key is trade-only/no-withdraw."
    )
