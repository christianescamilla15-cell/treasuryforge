"""Execution layer — the swap point.

`Executor` is the interface the rest of the system talks to. Today the only
implementation is `SimExecutor`, which fills against the simulated market with a
fee and adverse slippage. Tomorrow you add `PaperExecutor` (Kraken paper mode)
or `OnchainExecutor` (Coinbase AgentKit + an MPC/agentic wallet on a testnet)
implementing the same `execute(...)` signature — and nothing else changes.

An executor only ever receives intents the policy engine already approved.
"""

from __future__ import annotations

from typing import Protocol

from .types import Fill, Intent, MarketTick, Side
from .wallet import SimWallet


class Executor(Protocol):
    def execute(self, intent: Intent, tick: MarketTick, wallet: SimWallet) -> Fill: ...


class SimExecutor:
    def __init__(self, fee_rate: float = 0.001, slippage_bps: float = 5.0) -> None:
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps          # 1 bps = 0.01%

    def execute(self, intent: Intent, tick: MarketTick, wallet: SimWallet) -> Fill:
        slip = self.slippage_bps / 10_000.0
        # Slippage is always adverse: you buy a bit higher, sell a bit lower.
        if intent.side is Side.BUY:
            fill_price = tick.price * (1.0 + slip)
        else:
            fill_price = tick.price * (1.0 - slip)

        gross = intent.base_amount * fill_price
        fee = gross * self.fee_rate

        fill = Fill(
            symbol=intent.symbol,
            side=intent.side,
            base_amount=intent.base_amount,
            price=round(fill_price, 6),
            fee=round(fee, 6),
            ts=tick.ts,
        )
        wallet.apply_fill(fill)
        return fill
