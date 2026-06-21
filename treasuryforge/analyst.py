"""Analyst module — read-only observabilidad of shadows, orchestrator state, and relay freshness."""

from __future__ import annotations

import glob
import os
import time

from .backtest.metrics import deflated_sharpe_ratio
from .consultants import Committee
from .deployment_gate import DeploymentGate
from .journal import Journal
from .relay_feed import load_snapshot
from .risk.report import assess_and_report


def load_strategy_track_records(state_dir: str = "state") -> dict[str, tuple[list[float], list[int]]]:
    """Load track records for all active strategies from the journal directories."""
    sources = [
        (os.path.join(state_dir, "shadow"), "shadow", "funding"),
        (os.path.join(state_dir, "basis"), "basis", "basis"),
        (os.path.join(state_dir, "cross"), "shadow", "cross"),
        (os.path.join(state_dir, "scalp"), "scalp", "scalp")
    ]
    recs: dict[str, tuple[list[float], list[int]]] = {}
    for prefix_pat, kind, label in sources:
        for d in sorted(glob.glob(f"{prefix_pat}_*")):
            if not os.path.isdir(d):
                continue
            evs = [e for e in Journal(d).read_ledger() if e.get("kind") == kind]
            if not evs:
                continue
            coin = os.path.basename(d).split("_")[-1].upper()
            recs[f"{label}:{coin}"] = (
                [float(e["r"]) for e in evs],
                [int(e.get("ts", 0)) for e in evs if e.get("ts")]
            )
    return recs


def generate_digest(
    state_dir: str = "state",
    relay_path: str = "state/relay/funding.json",
    now: int | None = None
) -> dict:
    """Generate a read-only observability digest of the orchestrator state, strategy track records,
    gate verdicts, committee votes, and relay status.
    """
    if now is None:
        now = int(time.time())

    # 1. Relay freshness
    relay_snap = load_snapshot(relay_path)
    relay_ts = relay_snap.get("ts", 0)
    relay_age = now - relay_ts if relay_ts > 0 else float("inf")

    # 2. Orchestrator staged actions
    orchestrator_ledger_path = os.path.join(state_dir, "orchestrator")
    staged_events = []
    if os.path.isdir(orchestrator_ledger_path):
        staged_events = Journal(orchestrator_ledger_path).read_ledger()

    # 3. Strategy evaluation
    recs = load_strategy_track_records(state_dir)
    gate = DeploymentGate()
    committee = Committee()

    strategies_summary = []
    for strat, (rs, ts) in recs.items():
        gate_verdict = gate.evaluate(rs, ts)
        dsr = deflated_sharpe_ratio(rs, n_trials=1)

        # Run detailed risk report if we have at least 2 returns
        risk_report = None
        if len(rs) >= 2:
            try:
                risk_report = assess_and_report(strat, rs, dsr=dsr)
            except Exception:
                pass

        # Committee vote
        panel = committee.review(rs, ts)

        # Decide status
        status = "HOLD"
        reasons = []

        if gate_verdict.deploy:
            if panel.approved:
                status = "DEPLOY"
                reasons.append("Passed gate and committee")
            else:
                status = "HOLD"
                reasons.append(f"Committee vetoed: {panel.render()}")
        else:
            reasons.append(f"Failed gate: {gate_verdict.reason}")
            # Check if approaching
            if gate_verdict.dsr >= 0.40:
                status = "APPROACHING"

        strategies_summary.append({
            "strategy": strat,
            "status": status,
            "trades_count": len(rs),
            "dsr": dsr,
            "apr": gate_verdict.apr,
            "gate_passed": gate_verdict.deploy,
            "gate_reason": gate_verdict.reason,
            "committee_approved": panel.approved,
            "vetoes": [v.reason for v in panel.vetoes],
            "vetoed_by": [v.consultant for v in panel.vetoes],
            "risk_verdict": risk_report.verdict if risk_report else "INSUFFICIENT_DATA",
            "reasons": reasons
        })

    # Sort strategies: DEPLOY first, then APPROACHING, then HOLD (highest DSR first within each group)
    status_order = {"DEPLOY": 0, "APPROACHING": 1, "HOLD": 2}
    strategies_summary.sort(key=lambda x: (status_order.get(str(x["status"]), 2), -float(str(x["dsr"]))))

    return {
        "ts": now,
        "relay_age_seconds": relay_age,
        "relay_fresh": relay_age <= 900,  # 15 minutes freshness threshold
        "staged_pending": [e for e in staged_events if e.get("status") == "PENDING_OK"],
        "strategies": strategies_summary
    }


def render_digest_to_string(digest: dict) -> str:
    """Helper to render the analyst digest as a user-friendly readable report."""
    lines = []
    lines.append("================================================================================")
    lines.append("                         TREASURYFORGE ANALYST DIGEST                           ")
    lines.append("================================================================================")

    # Relay status
    age = digest["relay_age_seconds"]
    age_str = f"{age}s" if age != float("inf") else "NEVER"
    status_str = "FRESH" if digest["relay_fresh"] else "STALE"
    lines.append(f"Relay Egress Status: {status_str} (Age: {age_str})")

    # Staged actions
    pending = digest["staged_pending"]
    lines.append(f"Pending Staged Advancements: {len(pending)}")
    for p in pending:
        lines.append(f"  - {p.get('strategy')} @ {p.get('tier', 0.0):.0%} (DSR: {p.get('dsr', 0.0):.3f})")

    lines.append("")
    lines.append("STRATEGIES SUMMARY:")
    lines.append("--------------------------------------------------------------------------------")
    lines.append(f"{'STRATEGY':<20} | {'STATUS':<12} | {'TRADES':<6} | {'DSR':<6} | {'RISK VERDICT':<25}")
    lines.append("--------------------------------------------------------------------------------")

    for s in digest["strategies"]:
        lines.append(
            f"{s['strategy']:<20} | {s['status']:<12} | {s['trades_count']:<6} | {s['dsr']:.3f} | {s['risk_verdict']:<25}"  # noqa: E501
        )
        for r in s["reasons"]:
            lines.append(f"  -> {r}")
        if s["vetoes"]:
            lines.append(f"  -> Vetoes: {', '.join(s['vetoes'])}")

    lines.append("================================================================================")
    return "\n".join(lines)
