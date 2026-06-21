"""TreasuryForge HTTP API — thin FastAPI wrapper over the REAL Python engine.

Exposes the actual treasuryforge package (PolicyEngine, Runner, MeanReversionAgent,
SimExecutor, SimWallet, MarketSimulator, AuditLog) over HTTP. The browser demo at
treasuryforge.vercel.app calls these endpoints — no JS port, no fake data.

Same 8 rules, same crash-safe state, same HMAC audit chain — all enforced by
production code in treasuryforge/policy.py, runner.py, audit.py.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Project root is one level up from api/ — required for `from treasuryforge import …`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from treasuryforge import (  # noqa: E402
    AuditLog,
    MarketSimulator,
    MeanReversionAgent,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
    verify_chain,
)
from treasuryforge.types import Intent, MarketTick, Side  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="TreasuryForge API",
    description="HTTP wrapper over the real Python policy engine. Backs treasuryforge.vercel.app demo.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://treasuryforge.vercel.app",
        "https://ch65-portfolio.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _count_tests() -> dict:
    test_files = list((_REPO_ROOT / "tests").rglob("test_*.py"))
    total_funcs = 0
    for f in test_files:
        try:
            total_funcs += f.read_text(encoding="utf-8", errors="ignore").count("def test_")
        except Exception:
            continue
    return {"files": len(test_files), "functions": total_funcs}


def _count_loc(folder: str) -> int:
    total = 0
    p = _REPO_ROOT / folder
    if not p.exists():
        return 0
    for f in p.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        try:
            total += sum(1 for _ in f.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            pass
    return total


_STATS = {
    "tests": _count_tests(),
    "modules": len([p for p in (_REPO_ROOT / "treasuryforge").glob("*.py") if "__pycache__" not in str(p)]),
    "loc": {
        "production": _count_loc("treasuryforge"),
        "tests": _count_loc("tests"),
    },
    "rules": [
        {"n": 1, "id": "kill_switch", "purpose": "global stop — denies everything"},
        {"n": 2, "id": "circuit_breaker", "purpose": "trip on max_drawdown_pct, stay tripped"},
        {"n": 3, "id": "staleness_gate", "purpose": "deny if context older than budget"},
        {"n": 4, "id": "symbol_allowlist", "purpose": "only approved symbols"},
        {"n": 5, "id": "per_tx_notional_cap", "purpose": "no single trade above cap"},
        {"n": 6, "id": "rate_limit", "purpose": "max trades per rolling window"},
        {"n": 7, "id": "spend_budget", "purpose": "max notional value per window"},
        {"n": 8, "id": "solvency", "purpose": "never approve what wallet cannot afford"},
    ],
    "stack": ["Python 3.11+", "Hypothesis (fuzzing)", "stdlib-only HMAC-SHA256"],
    "source": "https://github.com/christianescamilla15-cell/treasuryforge",
    "policy_module": "treasuryforge/policy.py",
    "audit_module": "treasuryforge/audit.py",
    "runner_module": "treasuryforge/runner.py",
}


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "TreasuryForge API",
        "status": "live",
        "docs": "/docs",
        "endpoints": [
            "GET  /api/health",
            "GET  /api/stats",
            "POST /api/policy/evaluate",
            "POST /api/backtest/run",
            "GET  /api/audit/sample",
        ],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/stats")
def stats():
    """Real stats counted at module import — no hardcoded numbers."""
    return _STATS


# ── Policy evaluate ───────────────────────────────────────────────────
class EvaluateRequest(BaseModel):
    symbol: str = Field(..., examples=["TOKEN"])
    side: str = Field(..., examples=["BUY", "SELL"])
    notional: float = Field(..., gt=0, examples=[200.0])
    price: float = Field(..., gt=0, examples=[100.0])
    config: dict | None = Field(default=None)


@app.post("/api/policy/evaluate")
def policy_evaluate(req: EvaluateRequest):
    """Evaluate a SINGLE intent using the REAL PolicyEngine.

    Builds Intent + MarketTick + SimWallet and runs treasuryforge.PolicyEngine.evaluate().
    Returns the actual Verdict — same code path as the production engine.
    """
    o = req.config or {}
    try:
        cfg = PolicyConfig(
            allowed_symbols=frozenset(o.get("allowed_symbols", ["TOKEN", "BTC", "ETH"])),
            max_notional_per_tx=float(o.get("max_notional_per_tx", 500.0)),
            max_tx_per_window=int(o.get("max_tx_per_window", 3)),
            window_steps=int(o.get("window_steps", 10)),
            max_drawdown_pct=float(o.get("max_drawdown_pct", 0.15)),
            fee_rate=float(o.get("fee_rate", 0.001)),
            kill_switch=bool(o.get("kill_switch", False)),
            max_notional_per_window=o.get("max_notional_per_window"),
        )
    except Exception as e:
        raise HTTPException(400, f"invalid config: {e}")

    engine = PolicyEngine(config=cfg)
    side = Side.BUY if req.side.upper() == "BUY" else Side.SELL
    base_amount = req.notional / req.price
    intent = Intent(symbol=req.symbol, side=side, base_amount=base_amount)
    tick = MarketTick(symbol=req.symbol, price=req.price, ts=0)
    wallet = SimWallet(quote=float(o.get("starting_quote", 10_000.0)))

    verdict = engine.evaluate(intent, tick, wallet)
    rule = None
    if not verdict.allowed and ":" in verdict.reason:
        # format: DENY:<rule> <detail>
        rule = verdict.reason.split(":", 1)[1].split(" ", 1)[0]

    return {
        "verdict": {
            "allowed": verdict.allowed,
            "reason": verdict.reason,
            "rule": rule,
        },
        "intent": {
            "symbol": intent.symbol,
            "side": intent.side.value,
            "base_amount": intent.base_amount,
            "notional": intent.notional(tick.price),
        },
        "policy_module": "treasuryforge.policy.PolicyEngine",
        "real_code": True,
    }


# ── Backtest ──────────────────────────────────────────────────────────
class BacktestRequest(BaseModel):
    scenario: str = Field(default="normal", examples=["normal", "crash"])
    ticks: int = Field(default=60, ge=10, le=300)


@app.post("/api/backtest/run")
def backtest_run(req: BacktestRequest):
    """Run a REAL backtest using treasuryforge.Runner over `ticks` time steps.

    Builds market + agent + policy + executor + wallet from the real classes
    (same as run_demo.py) and returns aggregated stats from the actual run.
    """
    symbol = "TOKEN"
    crash = req.scenario == "crash"
    if crash:
        # Hold the asset, then a scripted -3%/tick collapse → breaker trips.
        prices = [100.0] * 20 + [100.0 * (0.97 ** i) for i in range(1, req.ticks - 20 + 1)]
        market = MarketSimulator(symbol=symbol, prices=prices)
        wallet = SimWallet(quote=0.0, positions={symbol: 100.0})
    else:
        market = MarketSimulator(symbol=symbol, start_price=100.0, seed=7, volatility=0.02)
        wallet = SimWallet(quote=10_000.0)

    fee_rate = 0.001
    policy = PolicyEngine(PolicyConfig(
        allowed_symbols=frozenset({symbol}),
        max_notional_per_tx=500.0,
        max_tx_per_window=3,
        window_steps=10,
        max_drawdown_pct=0.15,
        fee_rate=fee_rate,
    ))

    # Real HMAC audit chain to a tempfile
    audit_path = tempfile.NamedTemporaryFile(prefix="tf_audit_", suffix=".jsonl", delete=False).name
    audit = AuditLog(path=audit_path, key=b"demo-api-key-not-for-prod")

    runner = Runner(
        market=market,
        agent=MeanReversionAgent(symbol=symbol, window=20, threshold=0.02, trade_base=2.0),
        policy=policy,
        executor=SimExecutor(fee_rate=fee_rate, slippage_bps=5.0),
        wallet=wallet,
        audit=audit,
    )

    started = datetime.now(timezone.utc)
    report = runner.run(steps=req.ticks)
    finished = datetime.now(timezone.utc)

    # Read back the audit log to count entries + verify
    audit_entries: list[dict] = []
    try:
        with open(audit_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    audit_entries.append(json.loads(line))
    except Exception:
        pass
    chain_ok = verify_chain(audit_path, key=b"demo-api-key-not-for-prod")
    try:
        os.unlink(audit_path)
    except Exception:
        pass

    return {
        "scenario": req.scenario,
        "duration_ms": int((finished - started).total_seconds() * 1000),
        "ticks_requested": req.ticks,
        "fills_executed": len(report.fills),
        "ledger_events": len(report.ledger),
        "denials_by_rule": dict(report.denials),
        "denials_total": sum(report.denials.values()),
        "wallet": {
            "initial_equity": round(report.initial_equity, 4),
            "final_equity": round(report.final_equity, 4),
            "pnl": round(report.pnl, 4),
            "pnl_pct": round(report.pnl_pct * 100, 4),
        },
        "breaker": {
            "tripped": report.breaker_tripped,
        },
        "audit": {
            "entries": len(audit_entries),
            "integrity_verified": chain_ok,
            "first_sample": audit_entries[0] if audit_entries else None,
            "last_sample": audit_entries[-1] if audit_entries else None,
        },
        "real_code": True,
        "source": "https://github.com/christianescamilla15-cell/treasuryforge/blob/main/run_demo.py",
    }


# ── Audit sample (HMAC chain demo) ────────────────────────────────────
@app.get("/api/audit/sample")
def audit_sample(n: int = 5):
    """Return N entries from a freshly-generated REAL HMAC audit chain.

    Builds an AuditLog in a temp file, records N entries, reads them back,
    runs verify_chain() (the actual production function) and returns everything.
    """
    n = max(1, min(n, 20))
    path = tempfile.NamedTemporaryFile(prefix="tf_audit_demo_", suffix=".jsonl", delete=False).name
    audit = AuditLog(path=path, key=b"demo-api-key-not-for-prod")
    for i in range(n):
        audit.record({
            "ts": i,
            "intent": {"symbol": "TOKEN", "side": "BUY", "base_amount": 1.0 + i * 0.5},
            "allowed": (i % 3) != 0,
            "reason": "ALLOW" if (i % 3) else "DENY:rate_limit demo",
        })

    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    chain_ok = verify_chain(path, key=b"demo-api-key-not-for-prod")
    try:
        os.unlink(path)
    except Exception:
        pass

    return {
        "entries": entries,
        "chain_integrity_verified": chain_ok,
        "algorithm": "HMAC-SHA256 over canonical JSON",
        "module": "treasuryforge.audit",
        "real_code": True,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
