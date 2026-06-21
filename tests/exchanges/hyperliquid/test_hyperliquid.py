"""Hyperliquid keyless read layer — offline, injected post."""

from __future__ import annotations

import pytest

from treasuryforge.exchanges.hyperliquid import HyperliquidInfo


def test_funding_and_marks_parses():
    fake = lambda body: [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
        [{"funding": "0.0000125", "markPx": "100000", "oraclePx": "100010", "openInterest": "5"},
         {"funding": "0.0000300", "markPx": "3500", "oraclePx": "3499", "openInterest": "50"}],
    ]
    info = HyperliquidInfo(fake)
    fm = info.funding_and_marks()
    assert fm["BTC"]["funding"] == pytest.approx(0.0000125)
    assert fm["ETH"]["mark"] == pytest.approx(3500.0)


def test_all_mids_parses():
    info = HyperliquidInfo(lambda b: {"BTC": "100000.0", "ETH": "3500.5"})
    mids = info.all_mids()
    assert mids["BTC"] == pytest.approx(100000.0) and mids["ETH"] == pytest.approx(3500.5)


def test_margin_summary_and_positions():
    state = {
        "marginSummary": {"accountValue": "150.5", "totalMarginUsed": "20.0"},
        "withdrawable": "130.5",
        "assetPositions": [
            {"position": {"coin": "ETH", "szi": "-0.05", "entryPx": "3500",
                          "unrealizedPnl": "1.2"}},
        ],
    }
    info = HyperliquidInfo(lambda b: state)
    ms = info.margin_summary("0xabc")
    assert ms["account_value"] == pytest.approx(150.5)
    assert ms["withdrawable"] == pytest.approx(130.5)
    pos = info.open_positions("0xabc")
    assert pos[0]["coin"] == "ETH" and pos[0]["size"] == pytest.approx(-0.05)


def test_asset_index():
    info = HyperliquidInfo(lambda b: {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]})
    assert info.asset_index("SOL") == 2


def _unified_post(body):
    # a UNIFIED account: perp ledger reads $0, the USDC lives on the spot side
    if body["type"] == "clearinghouseState":
        return {"marginSummary": {"accountValue": "0.0", "totalMarginUsed": "0.0"},
                "withdrawable": "0.0", "assetPositions": []}
    if body["type"] == "spotClearinghouseState":
        return {"balances": [{"coin": "USDC", "total": "19.85", "hold": "0.0"},
                             {"coin": "USDE", "total": "0.0"}]}
    raise AssertionError(f"unexpected query {body['type']}")


def test_spot_balance_reads_usdc():
    info = HyperliquidInfo(_unified_post)
    assert info.spot_balance("0xabc", "USDC") == pytest.approx(19.85)
    assert info.spot_balance("0xabc", "USDE") == pytest.approx(0.0)
    assert info.spot_balance("0xabc", "DOGE") == pytest.approx(0.0)   # absent -> 0


def test_available_collateral_sums_perp_and_spot_for_unified():
    # the whole point: perp $0 + spot USDC $19.85 = $19.85 tradable, NOT $0
    info = HyperliquidInfo(_unified_post)
    assert info.available_collateral("0xabc") == pytest.approx(19.85)


def test_available_collateral_classic_account_is_perp_value():
    # classic account: funds in perp, spot empty -> same call still correct
    def classic(body):
        if body["type"] == "clearinghouseState":
            return {"marginSummary": {"accountValue": "150.5", "totalMarginUsed": "0"},
                    "withdrawable": "150.5", "assetPositions": []}
        return {"balances": []}
    info = HyperliquidInfo(classic)
    assert info.available_collateral("0xabc") == pytest.approx(150.5)


def test_authorized_agents_lists_all_from_extra_agents():
    ea = [{"name": "wall", "address": "0x6f63ac", "validUntil": 1},
          {"name": "test 2", "address": "0x42917a", "validUntil": 2}]
    info = HyperliquidInfo(lambda b: ea if b["type"] == "extraAgents" else {})
    addrs = info.authorized_agents("0xabc")
    assert addrs == ["0x6f63ac", "0x42917a"]      # the FULL list, not just one


def test_authorized_agents_empty_when_none():
    assert HyperliquidInfo(lambda b: []).authorized_agents("0xabc") == []
    assert HyperliquidInfo(lambda b: None).authorized_agents("0xabc") == []
