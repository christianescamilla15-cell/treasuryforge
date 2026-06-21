"""Realistic fill engine — reverse-engineer the OBSERVABLE behavior of a matching
engine by walking REAL order-book depth.

We can't (and needn't) copy proprietary HFT/matching code. What matters is what
they produce: a market order eats the book level by level, so the price you get is
the volume-weighted average of the depth you consume — NOT the mid. This model
takes a real L2 book (captured keyless from Hyperliquid) and computes the true
VWAP fill, realized slippage, market impact, and whether the order only PARTIALLY
fills. That is the difference between a toy "fill at mid" backtest and one that
behaves like production.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    px: float
    sz: float


def parse_book(book: dict) -> tuple[list[Level], list[Level]]:
    """Accept Hyperliquid l2Book ({"levels": [[bids],[asks]]}) or a plain
    {"bids": [[px,sz],...], "asks": [...]} dict. Returns (bids, asks) sorted best-first."""
    if "levels" in book:
        raw_bids, raw_asks = book["levels"][0], book["levels"][1]
        bids = [Level(float(b["px"]), float(b["sz"])) for b in raw_bids]
        asks = [Level(float(a["px"]), float(a["sz"])) for a in raw_asks]
    else:
        bids = [Level(float(px), float(sz)) for px, sz in book.get("bids", [])]
        asks = [Level(float(px), float(sz)) for px, sz in book.get("asks", [])]
    bids.sort(key=lambda lvl: -lvl.px)        # best bid = highest
    asks.sort(key=lambda lvl: lvl.px)         # best ask = lowest
    return bids, asks


def walk_book(levels: list[Level], size: float) -> tuple[float, float]:
    """Consume `size` across price levels. Returns (vwap_price, filled_size).
    filled < size means the book wasn't deep enough (a partial fill)."""
    remaining, cost, filled = size, 0.0, 0.0
    for lvl in levels:
        take = min(remaining, lvl.sz)
        cost += take * lvl.px
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    vwap = cost / filled if filled > 0 else 0.0
    return vwap, filled


@dataclass(frozen=True)
class FillResult:
    vwap: float
    filled: float
    requested: float
    mid: float
    slippage: float          # fraction vs mid, always >= 0 (adverse)
    partial: bool


class MatchingFillModel:
    """Fills a market order against real book depth — the production-like behavior."""

    def fill(self, book: dict, side: str, size: float) -> FillResult:
        bids, asks = parse_book(book)
        if not bids or not asks:
            raise ValueError("order book has an empty side")
        mid = (bids[0].px + asks[0].px) / 2.0
        levels = asks if side == "buy" else bids
        vwap, filled = walk_book(levels, size)
        slip = (vwap - mid) / mid if side == "buy" else (mid - vwap) / mid
        return FillResult(vwap=vwap, filled=filled, requested=size, mid=mid,
                          slippage=max(slip, 0.0), partial=filled < size - 1e-12)
