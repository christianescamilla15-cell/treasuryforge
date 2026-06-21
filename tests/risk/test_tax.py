"""Unit tests for the FIFO tax ledger."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from treasuryforge.risk.tax import FifoTaxLedger


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def test_fifo_tax_ledger_basic_buy_and_sell(temp_dir):
    path = os.path.join(temp_dir, "tax.json")
    ledger = FifoTaxLedger(path)

    # 1. Add BUY fill
    ledger.add_fill(
        fill_id="buy1",
        ts=1000,
        coin="BTC",
        side="BUY",
        qty=2.0,
        price=50000.0,
        fee=100.0
    )

    assert len(ledger.active_lots) == 1
    assert ledger.active_lots[0].coin == "BTC"
    assert ledger.active_lots[0].qty == 2.0
    assert ledger.active_lots[0].price == 50000.0
    assert ledger.get_unrealized_cost_basis("BTC") == 100000.0

    # 2. Add SELL fill that matches exactly
    matches = ledger.add_fill(
        fill_id="sell1",
        ts=2000,
        coin="BTC",
        side="SELL",
        qty=2.0,
        price=60000.0,
        fee=120.0
    )

    assert len(ledger.active_lots) == 0
    assert len(ledger.matched_trades) == 1
    assert len(matches) == 1

    match = matches[0]
    assert match.coin == "BTC"
    assert match.qty == 2.0
    assert match.buy_price == 50000.0
    assert match.sell_price == 60000.0
    assert match.buy_fee == 100.0
    assert match.sell_fee == 120.0
    # PnL = (60k0 - 50k) * 2 - 100 - 120 = 20000 - 220 = 19780
    assert match.realized_pnl == 19780.0
    assert ledger.get_unrealized_cost_basis("BTC") == 0.0


def test_fifo_tax_ledger_fifo_queuing(temp_dir):
    path = os.path.join(temp_dir, "tax.json")
    ledger = FifoTaxLedger(path)

    # Buy 1: 5 BTC @ $40k
    ledger.add_fill("buy1", 1000, "BTC", "BUY", 5.0, 40000.0, 100.0)
    # Buy 2: 3 BTC @ $45k
    ledger.add_fill("buy2", 1100, "BTC", "BUY", 3.0, 45000.0, 60.0)

    # Sell: 6 BTC @ $50k, fee $120
    # Consumes Buy 1 (5.0 BTC) and 1.0 BTC of Buy 2.
    matches = ledger.add_fill("sell1", 1200, "BTC", "SELL", 6.0, 50000.0, 120.0)

    assert len(matches) == 2

    # First match (Buy 1 consumed fully)
    m1 = matches[0]
    assert m1.buy_id == "buy1"
    assert m1.qty == 5.0
    assert m1.buy_price == 40000.0
    assert m1.buy_fee == 100.0
    assert m1.sell_fee == 120.0 * (5.0 / 6.0)  # $100.0
    # PnL = (50k - 40k) * 5 - 100 - 100 = 49800.0
    assert m1.realized_pnl == 49800.0

    # Second match (Buy 2 consumed partially: 1.0 out of 3.0 BTC)
    m2 = matches[1]
    assert m2.buy_id == "buy2"
    assert m2.qty == 1.0
    assert m2.buy_price == 45000.0
    assert m2.buy_fee == pytest.approx(60.0 * (1.0 / 3.0))  # $20.0
    assert m2.sell_fee == pytest.approx(120.0 * (1.0 / 6.0))  # $20.0
    # PnL = (50k - 45k) * 1 - 20 - 20 = 4960.0
    assert m2.realized_pnl == pytest.approx(4960.0)

    # Inventory left
    inv = ledger.get_inventory("BTC")
    assert len(inv) == 1
    assert inv[0].fill_id == "buy2"
    assert inv[0].qty == 2.0
    assert inv[0].fee == pytest.approx(40.0)
    assert ledger.get_unrealized_cost_basis("BTC") == 90000.0


def test_fifo_tax_ledger_insufficient_inventory(temp_dir):
    path = os.path.join(temp_dir, "tax.json")
    ledger = FifoTaxLedger(path)

    ledger.add_fill("buy1", 1000, "BTC", "BUY", 1.0, 40000.0, 10.0)

    with pytest.raises(ValueError, match="Insufficient inventory"):
        ledger.add_fill("sell1", 1200, "BTC", "SELL", 1.5, 45000.0, 10.0)


def test_fifo_tax_ledger_persistence(temp_dir):
    path = os.path.join(temp_dir, "tax.json")
    ledger = FifoTaxLedger(path)

    ledger.add_fill("buy1", 1000, "BTC", "BUY", 1.0, 40000.0, 10.0)

    # Reload from disk
    ledger2 = FifoTaxLedger(path)
    assert len(ledger2.active_lots) == 1
    assert ledger2.active_lots[0].fill_id == "buy1"
    assert ledger2.active_lots[0].qty == 1.0

    # Sell on ledger2
    ledger2.add_fill("sell1", 1100, "BTC", "SELL", 1.0, 45000.0, 10.0)
    assert len(ledger2.active_lots) == 0

    # Reload on ledger3
    ledger3 = FifoTaxLedger(path)
    assert len(ledger3.active_lots) == 0
    assert len(ledger3.matched_trades) == 1
    assert ledger3.matched_trades[0].sell_id == "sell1"


def test_fifo_tax_ledger_compliance_report(temp_dir):
    path = os.path.join(temp_dir, "tax.json")
    ledger = FifoTaxLedger(path)

    ledger.add_fill("buy1", 1000, "BTC", "BUY", 1.0, 40000.0, 10.0)
    ledger.add_fill("sell1", 1100, "BTC", "SELL", 1.0, 45000.0, 10.0)
    ledger.add_fill("buy2", 1200, "ETH", "BUY", 2.0, 2000.0, 5.0)

    report = ledger.generate_compliance_report()
    assert "CFF Art. 30 FIFO Tax Ledger Report" in report
    assert "BTC" in report
    assert "ETH" in report
    assert "buy1" in report
    assert "sell1" in report
    assert "+4980.0000" in report
