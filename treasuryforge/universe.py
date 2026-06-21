"""Liquid-universe discovery (Roadmap B1) — find carry candidates across ALL perps.

Screening only 5 coins can miss a coin in a high-funding regime where the carry
actually clears the cost-gate. This pulls the WHOLE Hyperliquid perp universe from a
single metaAndAssetCtxs response, filters to liquid markets (a daily-volume floor, so
we don't "discover" an untradeable edge on an illiquid coin), and ranks by funding —
the carry candidates. The caller then deep-screens the top few (fetching spread/vol).

Pure and offline-testable: it parses the injected response, no network here. The
returned count IS the selection-bias n_trials the downstream DSR must use.
"""

from __future__ import annotations

from typing import Any


def liquid_candidates(meta_and_ctxs: Any, *, min_vol_usd: float = 5e6,
                      top: int = 15) -> list[dict]:
    """Parse metaAndAssetCtxs -> liquid coins ranked by funding (highest first).

    Each row: {coin, funding (per-hr), premium, vol_usd}. Only markets with daily
    notional volume >= min_vol_usd survive; the top `top` by funding are returned."""
    meta, ctxs = meta_and_ctxs[0], meta_and_ctxs[1]
    rows: list[dict] = []
    for a, c in zip(meta["universe"], ctxs):
        vol_usd = float(c.get("dayNtlVlm", 0.0))
        if vol_usd < min_vol_usd:
            continue
        mark, oracle = float(c.get("markPx", 0.0)), float(c.get("oraclePx", 0.0))
        premium = (mark - oracle) / oracle if oracle > 0 else 0.0
        rows.append({"coin": a["name"], "funding": float(c.get("funding", 0.0)),
                     "premium": premium, "vol_usd": vol_usd})
    rows.sort(key=lambda r: r["funding"], reverse=True)
    return rows[:top]
