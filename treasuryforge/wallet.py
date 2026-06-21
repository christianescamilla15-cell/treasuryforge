"""Simulated wallet — the 'vault'.

It holds a quote balance (e.g. USDC) and base positions. The ONLY way to change
balances is to apply a Fill. apply_fill is defensive: it refuses to ever go
negative, even if some upstream check failed. In the real system this role is
played by an MPC / smart-account wallet that enforces the same invariant on-chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import Fill


class InsufficientFunds(Exception):
    """Raised when a fill would drive a balance negative."""


@dataclass
class SimWallet:
    quote: float                                   # spendable quote currency
    positions: dict[str, float] = field(default_factory=dict)

    def base_balance(self, symbol: str) -> float:
        return self.positions.get(symbol, 0.0)

    def equity(self, prices: dict[str, float]) -> float:
        """Total value = quote + mark-to-market of every position."""
        total = self.quote
        for symbol, amount in self.positions.items():
            total += amount * prices.get(symbol, 0.0)
        return total

    def apply_fill(self, fill: Fill) -> None:
        """Mutate balances by a fill. Never creates value, never goes negative."""
        new_quote = self.quote + fill.quote_delta
        new_base = self.base_balance(fill.symbol) + fill.base_delta

        # Tiny negative epsilons from float math are clamped; real overdrafts raise.
        if new_quote < -1e-9:
            raise InsufficientFunds(
                f"quote would go negative: {new_quote:.6f} (have {self.quote:.6f})"
            )
        if new_base < -1e-9:
            raise InsufficientFunds(
                f"{fill.symbol} would go negative: {new_base:.6f}"
            )

        self.quote = max(new_quote, 0.0)
        self.positions[fill.symbol] = max(new_base, 0.0)

    def snapshot(self) -> dict[str, float]:
        return {"quote": self.quote, **dict(self.positions)}

    @classmethod
    def from_snapshot(cls, snap: dict[str, float]) -> SimWallet:
        positions = {k: float(v) for k, v in snap.items() if k != "quote"}
        return cls(quote=float(snap["quote"]), positions=positions)
