"""Hyperliquid L1 wire format — size/price rounding and the order ACTION payload.

This mirrors the official SDK's rules so a dry-run preview is byte-faithful to what
would actually be signed and POSTed to /exchange:

  * size  -> rounded to the coin's szDecimals (from /info `meta`).
  * price -> 5 significant figures, then clamped to (MAX_DECIMALS - szDecimals)
             decimals; integers are always allowed. MAX_DECIMALS = 6 (perp), 8 (spot).
  * numbers go on the wire as normalized decimal strings (no sci-notation, no
    trailing zeros) — the SDK's float_to_wire, reproduced here with `decimal`.

Pure, deterministic, KEY-FREE: no signing and no network live in this module, so
the whole order-construction path is unit-testable without a wallet or funds.
"""

from __future__ import annotations

from decimal import Decimal

PERP_MAX_DECIMALS = 6
SPOT_MAX_DECIMALS = 8
_TIFS = ("Alo", "Ioc", "Gtc")


def float_to_wire(x: float) -> str:
    """SDK-faithful: round to 8dp, reject lossy rounding, emit a normalized string."""
    rounded = f"{x:.8f}"
    if abs(float(rounded) - x) >= 1e-12:
        raise ValueError(f"{x} cannot be represented on the wire without loss")
    return f"{Decimal(rounded).normalize():f}"


def round_size(sz: float, sz_decimals: int) -> float:
    return round(float(sz), sz_decimals)


def round_price(px: float, sz_decimals: int, *, is_perp: bool = True) -> float:
    px = float(px)
    if px <= 0:
        raise ValueError("price must be positive")
    max_dec = (PERP_MAX_DECIMALS if is_perp else SPOT_MAX_DECIMALS) - sz_decimals
    # 5 significant figures, then clamp to the allowed decimal places (SDK rule).
    return round(float(f"{px:.5g}"), max_dec)


def build_order_action(asset_index: int, is_buy: bool, price: float, size: float,
                       sz_decimals: int, *, tif: str = "Ioc",
                       reduce_only: bool = False, is_perp: bool = True) -> dict:
    """The exact L1 `order` action dict that gets signed + POSTed. No key, no network."""
    if tif not in _TIFS:
        raise ValueError(f"tif must be one of {_TIFS}, got {tif!r}")
    px = round_price(price, sz_decimals, is_perp=is_perp)
    sz = round_size(size, sz_decimals)
    if sz <= 0:
        raise ValueError(f"size {size} rounds to zero at szDecimals={sz_decimals}")
    return {
        "type": "order",
        "orders": [{
            "a": int(asset_index),
            "b": bool(is_buy),
            "p": float_to_wire(px),
            "s": float_to_wire(sz),
            "r": bool(reduce_only),
            "t": {"limit": {"tif": tif}},
        }],
        "grouping": "na",
    }
