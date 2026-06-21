"""treasuryforge — local-first sandbox for an autonomous treasury agent.

Validates the architecture (agent proposes -> policy disposes -> wallet executes
within hard limits) with ZERO keys, ZERO funds and ZERO network calls. The
execution layer is an interface, so the simulator can later be swapped for a
paper/testnet backend without touching the agent or the policy engine.
"""

from .agent import MeanReversionAgent, Strategy
from .audit import AuditLog, verify_chain
from .executor import SimExecutor
from .journal import Journal
from .market import MarketSimulator
from .policy import PolicyConfig, PolicyEngine
from .runner import Runner, RunReport
from .types import Fill, Intent, MarketTick, OrderType, Side, Verdict
from .wallet import SimWallet

__all__ = [
    "AuditLog",
    "Fill",
    "Intent",
    "Journal",
    "MarketSimulator",
    "MarketTick",
    "MeanReversionAgent",
    "OrderType",
    "PolicyConfig",
    "PolicyEngine",
    "RunReport",
    "Runner",
    "Side",
    "SimExecutor",
    "SimWallet",
    "Strategy",
    "Verdict",
    "verify_chain",
]
