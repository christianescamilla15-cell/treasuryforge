"""PnL decomposition (Roadmap A1) — where does the shadow's return ACTUALLY come from?

A net number hides everything. A strategy can show a positive net that is really just
a few lucky funding ticks masking a steady fee bleed, or a "basis" edge that is all
fee and no convergence. This splits a shadow ledger's return into its honest sources
and reconciles them EXACTLY to the additive total (sum of per-interval returns):

    net = funding + convergence + entry_fees + exit_fees + slippage + hedge_drift

funding/convergence are the GROSS edge; the rest are costs (<= 0). `cost_to_gross` is
the A2 kill metric: if costs eat more than ~25-35% of the gross edge, the signal dies.
slippage/hedge_drift are 0 under the current conservative model — they have explicit
slots so a more realistic fill/hedge model (A2) populates them without changing callers.

Works on any shadow ledger event (kind 'shadow' = funding-carry, 'basis' = basis): each
carries action + r, and HOLD events carry funding (and, for basis, r = funding + conv).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PnlBreakdown:
    funding: float          # funding received while in-position (gross)
    convergence: float      # premium convergence captured (basis only; 0 for funding-carry)
    entry_fees: float       # <= 0
    exit_fees: float        # <= 0
    slippage: float         # <= 0 (0 until the A2 fill model populates it)
    hedge_drift: float      # delta-neutral hedge imperfection (0 until modeled)
    n_intervals: int
    n_hold: int

    @property
    def gross(self) -> float:
        return self.funding + self.convergence

    @property
    def costs(self) -> float:
        return self.entry_fees + self.exit_fees + self.slippage + self.hedge_drift

    @property
    def net(self) -> float:
        return self.gross + self.costs

    @property
    def cost_to_gross(self) -> float:
        """|costs| / gross. The A2 gate kills a signal when this exceeds ~0.25-0.35."""
        return abs(self.costs) / self.gross if self.gross > 1e-12 else float("inf")

    def render(self) -> str:
        return "\n".join([
            f"  funding     {self.funding:+.6f}",
            f"  convergence {self.convergence:+.6f}",
            f"  entry fees  {self.entry_fees:+.6f}",
            f"  exit fees   {self.exit_fees:+.6f}",
            f"  slippage    {self.slippage:+.6f}",
            f"  hedge drift {self.hedge_drift:+.6f}",
            f"  --> gross {self.gross:+.6f}  costs {self.costs:+.6f}  "
            f"NET {self.net:+.6f}  cost/gross {self.cost_to_gross:.1%}",
        ])


def decompose(events: Iterable[dict]) -> PnlBreakdown:
    funding = convergence = entry_fees = exit_fees = 0.0
    n = n_hold = 0
    for e in events:
        if e.get("kind") not in ("shadow", "basis"):
            continue
        n += 1
        action = e.get("action")
        r = float(e.get("r", 0.0))
        if action == "ENTER":
            entry_fees += r                 # r = -entry_cost
        elif action == "EXIT":
            exit_fees += r                  # r = -exit_cost
        elif action == "HOLD":
            n_hold += 1
            f = float(e.get("funding", 0.0))
            funding += f
            convergence += r - f            # basis: r = funding + conv; funding-carry: conv = 0
        # FLAT: r == 0, contributes nothing
    return PnlBreakdown(funding=funding, convergence=convergence, entry_fees=entry_fees,
                        exit_fees=exit_fees, slippage=0.0, hedge_drift=0.0,
                        n_intervals=n, n_hold=n_hold)
