"""Hyperliquid keyless read layer (POST /info). No wallet, no signing, no funds.

Every method is a public /info query. `post` is injected (callable taking the
request body dict and returning parsed JSON) so the whole client is offline-
testable; the live `post` is a tiny urllib POST with a User-Agent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class HyperliquidInfo:
    def __init__(self, post: Callable[[dict], Any]) -> None:
        self._post = post

    # -- market metadata --------------------------------------------------
    def meta(self) -> dict:
        """Perp universe + asset metadata (names, size decimals, max leverage)."""
        return self._post({"type": "meta"})

    def asset_index(self, coin: str) -> int:
        names = [a["name"] for a in self.meta()["universe"]]
        return names.index(coin)

    def all_mids(self) -> dict[str, float]:
        """Mid price per coin."""
        return {k: float(v) for k, v in self._post({"type": "allMids"}).items()}

    def funding_and_marks(self) -> dict[str, dict]:
        """Current funding rate + mark/oracle price per coin (from metaAndAssetCtxs)."""
        meta, ctxs = self._post({"type": "metaAndAssetCtxs"})
        out = {}
        for a, c in zip(meta["universe"], ctxs):
            out[a["name"]] = {
                "funding": float(c.get("funding", 0.0)),
                "mark": float(c.get("markPx", 0.0)),
                "oracle": float(c.get("oraclePx", 0.0)),
                "open_interest": float(c.get("openInterest", 0.0)),
            }
        return out

    def l2_book(self, coin: str) -> dict:
        """Level-2 order book snapshot for a coin."""
        return self._post({"type": "l2Book", "coin": coin})

    # -- account state (keyless read of ANY address) ----------------------
    def user_state(self, address: str) -> dict:
        """Perp account state for an address: margin summary + open positions.
        Read-only and keyless — you can inspect any address."""
        return self._post({"type": "clearinghouseState", "user": address})

    def margin_summary(self, address: str) -> dict:
        st = self.user_state(address)
        ms = st.get("marginSummary", {})
        return {
            "account_value": float(ms.get("accountValue", 0.0)),
            "total_margin_used": float(ms.get("totalMarginUsed", 0.0)),
            "withdrawable": float(st.get("withdrawable", 0.0)),
        }

    def open_positions(self, address: str) -> list[dict]:
        out = []
        for p in self.user_state(address).get("assetPositions", []):
            pos = p.get("position", {})
            out.append({
                "coin": pos.get("coin"),
                "size": float(pos.get("szi", 0.0)),
                "entry_px": float(pos.get("entryPx") or 0.0),
                "unrealized_pnl": float(pos.get("unrealizedPnl", 0.0)),
            })
        return out

    def spot_balance(self, address: str, coin: str = "USDC") -> float:
        """Total balance of a spot token (default USDC)."""
        st = self._post({"type": "spotClearinghouseState", "user": address})
        for b in st.get("balances", []):
            if b.get("coin") == coin:
                return float(b.get("total", 0.0))
        return 0.0

    def authorized_agents(self, address: str) -> list[str]:
        """ALL agent wallet addresses currently authorized for this account, from
        `extraAgents`. This is the FULL list — webData2.agentAddress returns only the
        frontend's own session agent and misses user-created API wallets, so the
        sign-check must use this. Expiry (validUntil) is enforced by HL at order time."""
        ea = self._post({"type": "extraAgents", "user": address})
        return [a["address"] for a in ea] if isinstance(ea, list) else []

    def user_fills(self, address: str) -> list[dict]:
        """Recent fills for an account (keyless). Each has coin/px/sz/side/fee/oid/cloid."""
        res = self._post({"type": "userFills", "user": address})
        return res if isinstance(res, list) else []

    def fills_for_cloid(self, address: str, cloid: str) -> list[dict]:
        """The fills belonging to ONE client order id — the reconcile key. Matching by
        cloid (not oid) is what makes retries at-most-once: a re-post reuses the cloid,
        so a fill that already happened is found here instead of duplicated."""
        c = cloid.lower()
        return [f for f in self.user_fills(address) if str(f.get("cloid", "")).lower() == c]

    def available_collateral(self, address: str) -> float:
        """Tradable USD collateral. With a UNIFIED account the perp ledger reads
        $0 while the USDC sits on the spot side, yet that USDC backs perp trades —
        so the real collateral is the perp account value PLUS the spot USDC. On a
        classic (non-unified) account the spot USDC is 0 and this equals the perp
        account value, so the same call is correct in both regimes."""
        return self.margin_summary(address)["account_value"] + self.spot_balance(address, "USDC")
