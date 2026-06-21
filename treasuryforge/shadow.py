"""Shadow paper-book for the funding-carry strategy — collect a LIVE track record
with NO money, NO keys, NO venue.

The risk gates reject funding-carry on the BACKTEST (DSR 0.24, stressed ruin high).
Shadow trading is the honest next filter: run the same signal on real incoming
funding rates, simulate the delta-neutral position, and accrue hypothetical PnL —
so we learn whether the edge actually shows up live, without risking a peso. The
return series this produces feeds the same DSR / purged-CV / ruin gates and the
backtest-live gap detector. One of two honest outcomes: the edge survives live (and
can earn the first micro rung), or it doesn't (and we learned for free).

Per-interval return model (conservative — no funding on the open interval):
  FLAT  (out -> out):  0
  ENTER (out -> in ): -entry_cost
  HOLD  (in  -> in ): +funding_rate        (receive funding while delta-neutral)
  EXIT  (in  -> out): -exit_cost
Hypothetical equity compounds these. The book persists each observation to a
Journal and replays it on start, so it accumulates across restarts and days.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .journal import Journal
from .signals.funding import Action, FundingCarrySignal


@dataclass
class ShadowReport:
    n_intervals: int
    n_hold: int                 # intervals actually in-position accruing funding
    n_entries: int
    n_exits: int
    equity: float               # hypothetical, starts at 1.0
    realized_funding: float     # total funding received (gross)
    total_costs: float          # total entry+exit costs paid
    returns: list[float] = field(default_factory=list)

    @property
    def net_return(self) -> float:
        return self.equity - 1.0

    def render(self) -> str:
        return "\n".join([
            "=== funding-carry SHADOW (paper, no funds) ===",
            f"  intervals observed : {self.n_intervals}",
            f"  intervals in-position: {self.n_hold}",
            f"  entries / exits    : {self.n_entries} / {self.n_exits}",
            f"  realized funding   : {self.realized_funding:+.6f}",
            f"  costs paid         : {self.total_costs:.6f}",
            f"  net return         : {self.net_return:+.4%}  (equity {self.equity:.6f})",
        ])


@dataclass
class ShadowBook:
    signal: FundingCarrySignal
    journal: Journal | None = None
    equity: float = 1.0
    returns: list[float] = field(default_factory=list)
    realized_funding: float = 0.0
    total_costs: float = 0.0
    n_entries: int = 0
    n_exits: int = 0
    n_hold: int = 0

    def __post_init__(self) -> None:
        # replay by TRUSTING the stored action + return (the ledger is the source of
        # truth). Re-deciding would diverge once a cost-gate vetoes an entry; instead we
        # re-apply what actually happened and restore the signal's in-position state.
        if self.journal is not None:
            for ev in self.journal.read_ledger():
                if ev.get("kind") == "shadow":
                    action = str(ev["action"])
                    self._apply(action, float(ev["funding"]), float(ev["r"]), persist=False)
                    self.signal._in = action in (Action.ENTER.value, Action.HOLD.value)
                    self.signal._age = int(ev.get("age", 0))   # restore episode age (age-rule)

    def observe(self, funding_rate: float, *, ts: int, allow_entry: bool = True) -> Action:
        """Feed one live funding observation; returns the action taken this interval.
        allow_entry=False is the cost-gate: an ENTER the screener vetoes becomes FLAT
        (no position, no entry cost paid) — this is what stops fee-bleed churn."""
        action = self.signal.decide(funding_rate)
        if action is Action.ENTER and not allow_entry:
            self.signal._in = False              # undo decide()'s state change: stay flat
            action = Action.FLAT
        r = self._return_for(action, funding_rate)
        self._apply(action.value, funding_rate, r, persist=True, ts=ts)
        return action

    def report(self) -> ShadowReport:
        return ShadowReport(
            n_intervals=len(self.returns), n_hold=self.n_hold,
            n_entries=self.n_entries, n_exits=self.n_exits, equity=self.equity,
            realized_funding=self.realized_funding, total_costs=self.total_costs,
            returns=list(self.returns))

    # -- internals --------------------------------------------------------
    def _return_for(self, action: Action, funding_rate: float) -> float:
        if action is Action.ENTER:
            return -self.signal.p.entry_cost
        if action is Action.HOLD:
            return funding_rate
        if action is Action.EXIT:
            return -self.signal.p.exit_cost
        return 0.0                                  # FLAT

    def _apply(self, action: str, funding_rate: float, r: float,
               *, persist: bool, ts: int = 0) -> None:
        self.equity *= (1.0 + r)
        self.returns.append(r)
        if action == Action.ENTER.value:
            self.n_entries += 1
            self.total_costs += self.signal.p.entry_cost
        elif action == Action.HOLD.value:
            self.n_hold += 1
            self.realized_funding += funding_rate
        elif action == Action.EXIT.value:
            self.n_exits += 1
            self.total_costs += self.signal.p.exit_cost
        if persist and self.journal is not None:
            self.journal.append_event(
                {"kind": "shadow", "ts": ts, "action": action, "funding": funding_rate,
                 "r": r, "age": self.signal._age})
