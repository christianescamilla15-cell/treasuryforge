"""Autonomous capital-allocation broker -- the decision brain over every shadow track
record. It reads each strategy's live PAPER returns, runs the deployment gate, and emits an
allocation DECISION per strategy: HOLD (keep proving in shadow, $0 at risk), or DEPLOY (the
edge cleared the gate -> real micro capital, capped to the portfolio ceiling). It DECIDES
autonomously, but it cannot manufacture an edge -- so when none clears the gate every
decision is HOLD and $0 is deployed. That is the broker working correctly, not idle.

Portfolio rule: total deployed capital is capped (default 25% of bankroll = the top stage
tier), and when several strategies clear at once, each still enters at the micro tier. Pure
stdlib + the deployment gate -> offline- and mutation-testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .consultants import Committee
from .deployment_gate import DeploymentGate, GateVerdict

PORTFOLIO_CAP = 0.25            # never deploy more than this fraction of the bankroll in total


@dataclass(frozen=True)
class BrokerDecision:
    strategy: str
    action: str                # "DEPLOY" | "HOLD"
    tier_fraction: float        # share of bankroll allocated (0.0 if HOLD or capped out)
    verdict: GateVerdict
    reason: str


@dataclass(frozen=True)
class BrokerReport:
    decisions: tuple[BrokerDecision, ...]
    total_deployed: float       # sum of allocated fractions (<= PORTFOLIO_CAP)
    n_deployed: int

    @property
    def any_live(self) -> bool:
        return self.n_deployed > 0


def decide(track_records: dict[str, tuple[Sequence[float], Sequence[int]]], *,
           gate: DeploymentGate | None = None, committee: Committee | None = None,
           portfolio_cap: float = PORTFOLIO_CAP) -> BrokerReport:
    """One allocation decision per strategy track record, highest-DSR first. A strategy
    DEPLOYS only if it clears the gate AND the consultant committee is unanimous; deployable
    strategies then fill the portfolio up to the cap (micro tier each); the rest HOLD."""
    gate = gate or DeploymentGate()
    committee = committee or Committee()
    graded = sorted(((s, rs, ts, gate.evaluate(rs, ts)) for s, (rs, ts) in track_records.items()),
                    key=lambda x: -x[3].dsr)
    decisions: list[BrokerDecision] = []
    deployed = 0.0
    for strat, rs, ts, v in graded:
        panel = committee.review(rs, ts) if v.deploy else None
        if v.deploy and panel is not None and not panel.approved:
            decisions.append(BrokerDecision(strat, "HOLD", 0.0, v,
                                            f"gate ok but committee vetoed: {panel.render()}"))
        elif v.deploy and deployed + v.tier_fraction <= portfolio_cap + 1e-9:
            decisions.append(BrokerDecision(strat, "DEPLOY", v.tier_fraction, v,
                                            f"cleared gate + committee ({v.reason})"))
            deployed += v.tier_fraction
        elif v.deploy:
            decisions.append(BrokerDecision(strat, "HOLD", 0.0, v,
                                            f"gate+committee ok but portfolio cap {portfolio_cap:.0%} full"))
        else:
            decisions.append(BrokerDecision(strat, "HOLD", 0.0, v, v.reason))
    n = sum(1 for d in decisions if d.action == "DEPLOY")
    return BrokerReport(tuple(decisions), deployed, n)
