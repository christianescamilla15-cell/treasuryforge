"""Hyperliquid adapter (perp DEX on its own L1).

Phase-4 execution venue for the strategies that need a SHORT leg (funding-carry,
pairs) — Bitso is spot-only. Hyperliquid has no API keys / KYC: your wallet IS
your identity (EIP-712 / phantom-agent signing). The READ surface (/info) is fully
keyless and is what this module covers first; ORDER execution needs a real
eth-signing dependency + a funded wallet (decisions surfaced to the owner, not
auto-committed).

Security note: order placement should use an AGENT (API) wallet that can trade but
NOT withdraw — the on-chain equivalent of the Bitso trade-only/no-withdraw key,
preserving the blast-radius principle.
"""

from .executor import MIN_NOTIONAL_USD, DryRunPreview, HLOrderResult, HyperliquidExecutor
from .info import HyperliquidInfo
from .wire import build_order_action, round_price, round_size

__all__ = ["MIN_NOTIONAL_USD", "DryRunPreview", "HLOrderResult", "HyperliquidExecutor",
           "HyperliquidInfo", "build_order_action", "round_price", "round_size"]
