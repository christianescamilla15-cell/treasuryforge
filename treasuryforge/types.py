"""Core value objects shared across the system.

Everything is a frozen dataclass: intents and fills are immutable records, which
makes the ledger auditable and the whole run reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(frozen=True)
class MarketTick:
    """A single observation of the market at a discrete time step."""

    symbol: str
    price: float          # quote per 1 unit of base (e.g. USDC per TOKEN)
    ts: int               # integer time step (deterministic, no wall-clock)


@dataclass(frozen=True)
class Intent:
    """What the agent WANTS to do. It is only a proposal — never an action.

    The agent emits intents; nothing moves until the policy engine approves and
    the executor fills. base_amount is the quantity of the risky asset.
    """

    symbol: str
    side: Side
    base_amount: float    # quantity of base asset to buy/sell
    reason: str = ""      # agent's rationale, kept for the audit ledger
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None      # required for LIMIT orders
    quote_amount: float | None = None     # "spend exactly N quote" (MARKET BUY only)

    def notional(self, price: float) -> float:
        """Quote value of the intent at the given price (always positive)."""
        if self.quote_amount is not None:
            return abs(self.quote_amount)
        return abs(self.base_amount) * price


@dataclass(frozen=True)
class Verdict:
    """The policy engine's ruling on an intent."""

    allowed: bool
    reason: str           # human-readable: why allowed, or why denied


@dataclass(frozen=True)
class Fill:
    """A completed execution. The only thing allowed to mutate the wallet.

    `fee_currency` matters on real venues: Bitso charges a BUY fee in the BASE
    asset received (not in quote). Defaulting to "quote" preserves the simulator's
    original semantics exactly; the live executor sets "base" for buys so the fee
    is debited from the correct leg — otherwise every live BUY reconciles as a
    mismatch and permanently false-trips the kill-switch.
    """

    symbol: str
    side: Side
    base_amount: float    # base actually transacted (positive)
    price: float          # effective fill price after slippage
    fee: float            # fee paid (>= 0), denominated in fee_currency
    ts: int
    fee_currency: str = "quote"           # "quote" or "base"

    @property
    def quote_delta(self) -> float:
        """Signed change to the quote balance caused by this fill.

        BUY  -> negative (we spend quote, plus the fee if it is charged in quote).
        SELL -> positive (we receive quote, minus the fee if charged in quote).
        """
        gross = self.base_amount * self.price
        quote_fee = self.fee if self.fee_currency == "quote" else 0.0
        if self.side is Side.BUY:
            return -(gross + quote_fee)
        return gross - quote_fee

    @property
    def base_delta(self) -> float:
        """Signed change to the base balance caused by this fill.

        A BUY fee charged in base reduces the base actually received.
        """
        base_fee = self.fee if self.fee_currency == "base" else 0.0
        if self.side is Side.BUY:
            return self.base_amount - base_fee
        return -self.base_amount
