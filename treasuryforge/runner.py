"""Runner — orchestrates the 24/7 loop (here: N discrete steps).

For each tick:  agent.decide -> policy.evaluate -> (if allowed) executor.execute.
Every decision and ruling is appended to an auditable ledger, so we can verify
the system "makes correct operations" by reading exactly what happened and why.

This is the loop you would later wrap in a service (nssm / VPS) for real 24/7
operation — but only after the local validation gates are green.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent import Strategy
from .audit import AuditLog
from .executor import Executor
from .journal import Journal
from .market import MarketSimulator
from .policy import PolicyEngine
from .types import Fill, Intent, MarketTick, Verdict
from .wallet import InsufficientFunds, SimWallet


@dataclass
class LedgerEvent:
    ts: int
    price: float
    kind: str                 # "FILL", "DENIED", or "HOLD"
    detail: str
    equity: float


@dataclass
class RunReport:
    initial_equity: float
    final_equity: float
    fills: list[Fill] = field(default_factory=list)
    ledger: list[LedgerEvent] = field(default_factory=list)
    denials: dict[str, int] = field(default_factory=dict)
    breaker_tripped: bool = False

    @property
    def pnl(self) -> float:
        return self.final_equity - self.initial_equity

    @property
    def pnl_pct(self) -> float:
        return self.pnl / self.initial_equity if self.initial_equity else 0.0

    def summary(self) -> str:
        lines = [
            "=== treasuryforge run report ===",
            f"steps          : {len(self.ledger)}",
            f"fills executed : {len(self.fills)}",
            f"denied intents : {sum(self.denials.values())}",
            f"initial equity : {self.initial_equity:,.2f}",
            f"final equity   : {self.final_equity:,.2f}",
            f"pnl            : {self.pnl:+,.2f} ({self.pnl_pct:+.2%})",
            f"breaker tripped: {self.breaker_tripped}",
        ]
        if self.denials:
            lines.append("denials by reason:")
            for reason, n in sorted(self.denials.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {n:>4}x  {reason}")
        return "\n".join(lines)


@dataclass
class Runner:
    market: MarketSimulator
    agent: Strategy
    policy: PolicyEngine
    executor: Executor
    wallet: SimWallet
    journal: Journal | None = None          # durable crash-safe state (optional)
    audit: AuditLog | None = None           # tamper-evident decision log (optional)
    execution_delay: int = 1                # fill at t+execution_delay (1 = next tick).
    #   Point-in-time discipline: the agent decides on tick t but the order fills
    #   at the NEXT tick's price, so it can never trade on the bar it is still
    #   forming (kills the #1 backtest bug: signal-on-close / fill-on-same-close).

    def _state(self, ts: int) -> dict:
        return {"last_ts": ts, "policy": self.policy.snapshot(), "wallet": self.wallet.snapshot()}

    def run(self, steps: int) -> RunReport:
        report = RunReport(initial_equity=0.0, final_equity=0.0)
        first = True
        pending: tuple[Intent, int] | None = None     # (approved intent, decided_ts)

        for tick in self.market.ticks(steps):
            prices = {tick.symbol: tick.price}
            if first:
                report.initial_equity = self.wallet.equity(prices)
                first = False

            # settle a previously-approved intent at THIS tick's price
            if pending is not None:
                self._settle(report, pending[0], tick)
                pending = None

            intent = self.agent.decide(tick, self.wallet)
            if intent is None:
                self._log(report, tick.ts, tick.price, "HOLD", "no signal")
                continue

            verdict: Verdict = self.policy.evaluate(intent, tick, self.wallet)
            if self.audit is not None:
                self.audit.record({
                    "ts": tick.ts, "price": tick.price,
                    "intent": {"symbol": intent.symbol, "side": intent.side.value,
                               "base_amount": intent.base_amount},
                    "allowed": verdict.allowed, "reason": verdict.reason,
                })
            if not verdict.allowed:
                self._tally_denial(report, verdict.reason)
                self._log(report, tick.ts, tick.price, "DENIED",
                          f"{intent.side.value} {intent.base_amount} :: {verdict.reason}")
                # a freshly latched breaker is money-relevant — persist it now
                if self.journal is not None and self.policy.tripped:
                    self.journal.checkpoint(self._state(tick.ts))
                continue

            if self.execution_delay <= 0:
                self._settle(report, intent, tick)       # same-tick fill (opt-out)
            else:
                pending = (intent, tick.ts)              # fill on the next tick

        report.final_equity = self.wallet.equity(self._last_prices)
        report.breaker_tripped = self.policy.tripped
        return report

    def _settle(self, report: RunReport, intent: Intent, tick: MarketTick) -> None:
        try:
            fill = self.executor.execute(intent, tick, self.wallet)
        except InsufficientFunds:
            # price moved between decision and fill — abort, never overdraw
            self._tally_denial(report, "DENY:fill_aborted price_moved")
            self._log(report, tick.ts, tick.price, "DENIED",
                      f"{intent.side.value} {intent.base_amount} :: fill_aborted (price moved)")
            return
        self.policy.register_fill(tick.ts, fill.base_amount * fill.price)
        report.fills.append(fill)
        self._log(report, tick.ts, tick.price, "FILL",
                  f"{fill.side.value} {fill.base_amount} @ {fill.price} "
                  f"fee={fill.fee} :: {intent.reason}")
        if self.journal is not None:
            self.journal.append_event({
                "ts": fill.ts, "side": fill.side.value, "base": fill.base_amount,
                "price": fill.price, "fee": fill.fee,
            })
            self.journal.checkpoint(self._state(fill.ts))

    # -- helpers -----------------------------------------------------------
    _last_prices: dict[str, float] = field(default_factory=dict)

    def _log(self, report: RunReport, ts: int, price: float, kind: str, detail: str) -> None:
        self._last_prices = {self.market.symbol: price}
        report.ledger.append(
            LedgerEvent(ts, price, kind, detail, self.wallet.equity(self._last_prices))
        )

    @staticmethod
    def _tally_denial(report: RunReport, reason: str) -> None:
        # collapse to the rule name (text before the first space) for the histogram
        key = reason.split(" ", 1)[0]
        report.denials[key] = report.denials.get(key, 0) + 1
