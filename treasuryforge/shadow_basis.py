"""Shadow paper-book for the spot-vs-perp BASIS carry — live track record, NO money.

Mirrors the funding-carry ShadowBook but on the basis signal, and crucially models
the EXTRA return stream the funding model ignores: premium convergence.

Per-interval return model (conservative):
  FLAT  (out -> out):  0
  ENTER (out -> in ): -entry_cost            (and anchor prev_premium = premium)
  HOLD  (in  -> in ): +funding + (prev_premium - premium)   funding + convergence gain
  EXIT  (in  -> out): -exit_cost
A shrinking premium is a GAIN for long-spot/short-perp, so (prev - curr) is the
mark-to-market of the convergence each interval. Persists every observation to a
Journal (funding AND premium) and replays it on start, accumulating across days.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .journal import Journal
from .signals.basis import BasisSignal
from .signals.funding import Action


@dataclass
class BasisReport:
    n_intervals: int
    n_hold: int
    n_entries: int
    n_exits: int
    equity: float
    realized_funding: float
    realized_convergence: float
    total_costs: float
    returns: list[float] = field(default_factory=list)

    @property
    def net_return(self) -> float:
        return self.equity - 1.0

    def render(self) -> str:
        return "\n".join([
            "=== spot-vs-perp BASIS SHADOW (paper, no funds) ===",
            f"  intervals observed : {self.n_intervals}",
            f"  intervals in-position: {self.n_hold}",
            f"  entries / exits    : {self.n_entries} / {self.n_exits}",
            f"  realized funding   : {self.realized_funding:+.6f}",
            f"  realized convergence: {self.realized_convergence:+.6f}",
            f"  costs paid         : {self.total_costs:.6f}",
            f"  net return         : {self.net_return:+.4%}  (equity {self.equity:.6f})",
        ])


@dataclass
class BasisBook:
    signal: BasisSignal
    journal: Journal | None = None
    equity: float = 1.0
    returns: list[float] = field(default_factory=list)
    realized_funding: float = 0.0
    realized_convergence: float = 0.0
    total_costs: float = 0.0
    n_entries: int = 0
    n_exits: int = 0
    n_hold: int = 0
    _prev_premium: float = 0.0

    def __post_init__(self) -> None:
        # replay TRUSTING the stored action + return (consistent with a cost-gate that
        # may veto entries); reconstruct counters and the in-position / premium state.
        if self.journal is not None:
            for ev in self.journal.read_ledger():
                if ev.get("kind") == "basis":
                    self._apply_stored(str(ev["action"]), float(ev["funding"]),
                                       float(ev["premium"]), float(ev["r"]))

    def observe(self, funding_rate: float, premium: float, *, ts: int,
                allow_entry: bool = True) -> Action:
        """Feed one live (funding, premium) observation. allow_entry=False is the
        cost-gate: an ENTER the screener vetoes becomes FLAT (no entry cost)."""
        action = self.signal.decide(premium)
        if action is Action.ENTER and not allow_entry:
            self.signal._in = False
            action = Action.FLAT
        convergence = 0.0
        if action is Action.ENTER:
            r = -self.signal.p.entry_cost
            self._prev_premium = premium
        elif action is Action.HOLD:
            convergence = self._prev_premium - premium
            r = funding_rate + convergence
            self._prev_premium = premium
        elif action is Action.EXIT:
            r = -self.signal.p.exit_cost
        else:
            r = 0.0
        self._record(action.value, funding_rate, convergence, r)
        if self.journal is not None:
            self.journal.append_event({"kind": "basis", "ts": ts, "action": action.value,
                                       "funding": funding_rate, "premium": premium, "r": r})
        return action

    def report(self) -> BasisReport:
        return BasisReport(
            n_intervals=len(self.returns), n_hold=self.n_hold, n_entries=self.n_entries,
            n_exits=self.n_exits, equity=self.equity, realized_funding=self.realized_funding,
            realized_convergence=self.realized_convergence, total_costs=self.total_costs,
            returns=list(self.returns))

    # -- internals --------------------------------------------------------
    def _record(self, action: str, funding_rate: float, convergence: float, r: float) -> None:
        """Update counters + equity from a (live-computed or stored) return."""
        if action == Action.ENTER.value:
            self.n_entries += 1
            self.total_costs += self.signal.p.entry_cost
        elif action == Action.HOLD.value:
            self.n_hold += 1
            self.realized_funding += funding_rate
            self.realized_convergence += convergence
        elif action == Action.EXIT.value:
            self.n_exits += 1
            self.total_costs += self.signal.p.exit_cost
        self.equity *= (1.0 + r)
        self.returns.append(r)

    def _apply_stored(self, action: str, funding_rate: float, premium: float, r: float) -> None:
        convergence = (r - funding_rate) if action == Action.HOLD.value else 0.0
        self._record(action, funding_rate, convergence, r)
        self.signal._in = action in (Action.ENTER.value, Action.HOLD.value)
        if self.signal._in:
            self._prev_premium = premium
