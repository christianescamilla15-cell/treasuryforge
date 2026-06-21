"""Market lab: SQLite store, synthetic regimes, and realistic depth-walking fills."""

from __future__ import annotations

import pytest

from treasuryforge.marketlab import (
    MarketStore,
    MatchingFillModel,
    SyntheticMarket,
    parse_book,
    walk_book,
)


# -- store (the BD) ----------------------------------------------------------
def _candles(n, start_t=0):
    return [{"t": start_t + i, "o": 100, "h": 101, "l": 99, "c": 100 + i, "v": 5} for i in range(n)]


def test_store_upsert_and_query_roundtrip():
    s = MarketStore(":memory:")
    s.upsert_candles("BTC", "1h", _candles(5))
    assert s.closes("BTC", "1h") == [100, 101, 102, 103, 104]


def test_store_upsert_is_idempotent():
    s = MarketStore(":memory:")
    s.upsert_candles("BTC", "1h", _candles(5))
    s.upsert_candles("BTC", "1h", _candles(5))          # same keys -> replace, not dup
    assert len(s.closes("BTC", "1h")) == 5


def test_store_sync_with_injected_transport():
    s = MarketStore(":memory:")
    # fake Hyperliquid: first call returns 3 candles, then nothing (stop)
    calls = [_candles(3, start_t=10**12)]

    def fake_post(body):
        return calls.pop(0) if calls else []

    n = s.sync_candles("ETH", "1h", days=1, post=fake_post)
    assert n == 3 and len(s.closes("ETH", "1h")) == 3


def test_store_funding_and_summary():
    s = MarketStore(":memory:")
    s.upsert_funding("BTC", [(1, 0.0001), (2, -0.0002)])
    assert s.funding_rates("BTC") == [pytest.approx(0.0001), pytest.approx(-0.0002)]
    assert s.summary()["funding"]["BTC"] == 2


def test_store_orderbook_snapshot():
    s = MarketStore(":memory:")
    book = {"levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "2"}]]}
    assert s.snapshot_orderbook("BTC", ts=1, book=book) == 2


# -- synthetic market (realistic volatility) ---------------------------------
def test_synthetic_is_deterministic():
    a = [t.price for t in SyntheticMarket(seed=1).ticks(300)]
    b = [t.price for t in SyntheticMarket(seed=1).ticks(300)]
    assert a == b


def test_synthetic_prices_stay_positive():
    assert all(t.price > 0 for t in SyntheticMarket(seed=2).ticks(2000))


def test_synthetic_has_more_vol_than_a_calm_walk():
    # the regime+jump market should be materially more volatile than a tiny-vol walk
    rough = SyntheticMarket(seed=3).realized_vol(2000)
    assert rough > 0.005


def test_synthetic_drives_the_runner():
    from treasuryforge import (
        MeanReversionAgent,
        PolicyConfig,
        PolicyEngine,
        Runner,
        SimExecutor,
        SimWallet,
    )
    sym = "TOKEN"
    runner = Runner(
        market=SyntheticMarket(symbol=sym, seed=7),
        agent=MeanReversionAgent(symbol=sym, window=20, threshold=0.02, trade_base=1.0),
        policy=PolicyEngine(PolicyConfig(frozenset({sym}), 500.0, 5, 10, 0.15, fee_rate=0.001)),
        executor=SimExecutor(),
        wallet=SimWallet(quote=10_000.0),
    )
    report = runner.run(300)
    assert len(report.ledger) == 300         # full crash/vol path drove the stack


# -- realistic fills (walking real depth) ------------------------------------
def test_walk_book_full_and_partial():
    from treasuryforge.marketlab import Level
    book = [Level(100, 1.0), Level(101, 1.0), Level(102, 5.0)]
    vwap, filled = walk_book(book, 1.5)              # eats level1 + half of level2
    assert filled == pytest.approx(1.5)
    assert vwap == pytest.approx((1 * 100 + 0.5 * 101) / 1.5)
    _, partial = walk_book(book, 100.0)              # not enough depth
    assert partial < 100.0


def test_matching_fill_buy_slips_above_mid():
    book = {"bids": [[99, 5]], "asks": [[100, 1], [102, 5]]}
    r = MatchingFillModel().fill(book, "buy", 3.0)   # eats 1@100 + 2@102
    assert r.mid == pytest.approx(99.5)
    assert r.vwap == pytest.approx((100 + 2 * 102) / 3)
    assert r.slippage > 0 and not r.partial


def test_matching_fill_partial_when_book_too_thin():
    book = {"bids": [[99, 1]], "asks": [[100, 0.5]]}
    r = MatchingFillModel().fill(book, "buy", 2.0)
    assert r.partial and r.filled == pytest.approx(0.5)


def test_parse_hyperliquid_l2_format():
    hl = {"levels": [[{"px": "99", "sz": "2"}], [{"px": "100", "sz": "3"}]], "coin": "BTC"}
    bids, asks = parse_book(hl)
    assert bids[0].px == 99 and asks[0].px == 100


def test_matching_fill_empty_side_raises():
    with pytest.raises(ValueError):
        MatchingFillModel().fill({"bids": [], "asks": [[100, 1]]}, "buy", 1.0)
