"""FIFO Tax Ledger for CFF Art. 30 Compliance.

Tracks buys and matching sells to compute cost basis, proceeds, fees, and realized gains/losses
for tax reporting purposes. Keeps a persistent state to survive restarts crash-safely.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass


@dataclass
class BuyLot:
    coin: str
    qty: float
    price: float
    ts: int
    fee: float
    fill_id: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BuyLot:
        return cls(
            coin=str(d["coin"]),
            qty=float(d["qty"]),
            price=float(d["price"]),
            ts=int(d["ts"]),
            fee=float(d["fee"]),
            fill_id=str(d["fill_id"]),
        )


@dataclass
class MatchedTrade:
    coin: str
    qty: float
    buy_ts: int
    sell_ts: int
    buy_price: float
    sell_price: float
    buy_fee: float
    sell_fee: float
    buy_id: str
    sell_id: str
    realized_pnl: float  # (sell_price - buy_price) * qty - buy_fee - sell_fee

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> MatchedTrade:
        return cls(
            coin=str(d["coin"]),
            qty=float(d["qty"]),
            buy_ts=int(d["buy_ts"]),
            sell_ts=int(d["sell_ts"]),
            buy_price=float(d["buy_price"]),
            sell_price=float(d["sell_price"]),
            buy_fee=float(d["buy_fee"]),
            sell_fee=float(d["sell_fee"]),
            buy_id=str(d["buy_id"]),
            sell_id=str(d["sell_id"]),
            realized_pnl=float(d["realized_pnl"]),
        )


class FifoTaxLedger:
    """FIFO tax ledger tracking cost-basis, sales proceeds and realized PnL."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.active_lots: list[BuyLot] = []
        self.matched_trades: list[MatchedTrade] = []
        self.load()

    def add_fill(self, fill_id: str, ts: int, coin: str, side: str, qty: float,
                 price: float, fee: float) -> list[MatchedTrade]:
        """Add a fill (BUY or SELL). On SELL, run FIFO matching and return the MatchedTrade entries."""
        side = side.upper()
        if qty <= 0:
            raise ValueError(f"Quantity must be positive, got {qty}")
        if price <= 0:
            raise ValueError(f"Price must be positive, got {price}")
        if fee < 0:
            raise ValueError(f"Fee cannot be negative, got {fee}")

        coin = coin.upper()

        if side == "BUY":
            lot = BuyLot(coin=coin, qty=qty, price=price, ts=ts, fee=fee, fill_id=fill_id)
            self.active_lots.append(lot)
            self.save()
            return []

        elif side == "SELL":
            matches = self._match_sell(fill_id, ts, coin, qty, price, fee)
            self.matched_trades.extend(matches)
            self.save()
            return matches

        else:
            raise ValueError(f"Unknown side: {side}")

    def _match_sell(self, sell_id: str, sell_ts: int, coin: str, sell_qty: float,
                    sell_price: float, sell_fee: float) -> list[MatchedTrade]:
        """Internal helper to match a sell against active buy lots using FIFO."""
        coin_lots = [lot for lot in self.active_lots if lot.coin == coin]
        available_qty = sum(lot.qty for lot in coin_lots)
        if available_qty < sell_qty:
            raise ValueError(
                f"Insufficient inventory for {coin}. Need {sell_qty}, only have {available_qty} available."
            )

        matches: list[MatchedTrade] = []
        remaining_sell = sell_qty

        # Process active lots in FIFO order
        new_active_lots: list[BuyLot] = []
        for lot in self.active_lots:
            if lot.coin != coin or remaining_sell <= 0:
                new_active_lots.append(lot)
                continue

            match_qty = min(remaining_sell, lot.qty)

            # Proportional fees
            prop_buy_fee = lot.fee * (match_qty / lot.qty) if lot.qty > 0 else 0.0
            prop_sell_fee = sell_fee * (match_qty / sell_qty) if sell_qty > 0 else 0.0

            # Realized PnL: proceeds - cost basis - fees
            proceeds = match_qty * sell_price
            cost_basis = match_qty * lot.price
            realized_pnl = proceeds - cost_basis - prop_buy_fee - prop_sell_fee

            match_entry = MatchedTrade(
                coin=coin,
                qty=match_qty,
                buy_ts=lot.ts,
                sell_ts=sell_ts,
                buy_price=lot.price,
                sell_price=sell_price,
                buy_fee=prop_buy_fee,
                sell_fee=prop_sell_fee,
                buy_id=lot.fill_id,
                sell_id=sell_id,
                realized_pnl=realized_pnl
            )
            matches.append(match_entry)

            # Adjust lot quantities
            remaining_sell -= match_qty
            lot.qty -= match_qty
            lot.fee -= prop_buy_fee  # reduce remaining fee proportionally

            if lot.qty > 1e-10:  # float precision tolerance
                new_active_lots.append(lot)

        self.active_lots = new_active_lots
        return matches

    def get_inventory(self, coin: str) -> list[BuyLot]:
        """Get list of active buy lots for a coin."""
        return [lot for lot in self.active_lots if lot.coin == coin.upper()]

    def get_unrealized_cost_basis(self, coin: str) -> float:
        """Sum of cost basis (qty * price) for remaining unsold lots of a coin."""
        return sum(lot.qty * lot.price for lot in self.get_inventory(coin))

    def save(self) -> None:
        """Atomic state save (tempfile + replace) to ensure crash safety."""
        dir_name = os.path.dirname(self.path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        state = {
            "active_lots": [lot.to_dict() for lot in self.active_lots],
            "matched_trades": [trade.to_dict() for trade in self.matched_trades],
        }

        fd, tmp = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, sort_keys=True, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def load(self) -> None:
        """Load state from file if it exists."""
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                state = json.load(f)
            self.active_lots = [BuyLot.from_dict(d) for d in state.get("active_lots", [])]
            self.matched_trades = [MatchedTrade.from_dict(d) for d in state.get("matched_trades", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            # If the file is corrupt or invalid, we reset to empty state (crash-only tolerance)
            self.active_lots = []
            self.matched_trades = []

    def generate_compliance_report(self) -> str:
        """Generates a Markdown compliance report suitable for CFF Art. 30 audit trails."""
        lines = [
            "# CFF Art. 30 FIFO Tax Ledger Report",
            "",
            "## Matched Transactions (Realized Gain/Loss)",
            "",
            "| Coin | Qty | Buy Date (TS) | Sell Date (TS) | Buy Price | Sell Price | Buy Fee | Sell Fee | Realized PnL | Buy ID | Sell ID |",  # noqa: E501
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]

        total_pnl = 0.0
        for t in self.matched_trades:
            lines.append(
                f"| {t.coin} | {t.qty:.6f} | {t.buy_ts} | {t.sell_ts} | {t.buy_price:.4f} | {t.sell_price:.4f} | {t.buy_fee:.4f} | {t.sell_fee:.4f} | {t.realized_pnl:+.4f} | {t.buy_id} | {t.sell_id} |"  # noqa: E501
            )
            total_pnl += t.realized_pnl

        lines.extend([
            "",
            f"**Total Realized PnL:** {total_pnl:+.4f}",
            "",
            "## Unsold Inventory (Unrealized Cost Basis)",
            "",
            "| Coin | Qty | Buy Date (TS) | Cost Price | Remaining Buy Fee | Buy ID |",
            "|---|---|---|---|---|---|",
        ])

        for lot in self.active_lots:
            lines.append(
                f"| {lot.coin} | {lot.qty:.6f} | {lot.ts} | {lot.price:.4f} | {lot.fee:.4f} | {lot.fill_id} |"
            )

        return "\n".join(lines)
