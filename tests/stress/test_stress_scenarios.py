"""Stress validation — drive the WHOLE stack through synthetic crashes, storms and
fat-tail jumps (fidelity level 2) and assert the safety invariants HOLD no matter
how violent the market gets. This is the 'does it survive prod-like chaos' test.
"""

from __future__ import annotations

from treasuryforge import (
    MeanReversionAgent,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
)
from treasuryforge.marketlab import Regime, SyntheticMarket

SYM = "TOKEN"

CRASH_HEAVY = [
    Regime("calm", 0.0, 0.01, 0.85),
    Regime("storm", 0.0, 0.035, 0.85),
    Regime("crash", -0.008, 0.06, 0.82),    # realistic-severe crashes (-20% to -60%)
]


def _run(seed: int, *, position_heavy: bool, drawdown=0.15, jump_prob=0.03):
    wallet = (SimWallet(quote=0.0, positions={SYM: 100.0})
              if position_heavy else SimWallet(quote=10_000.0))
    runner = Runner(
        market=SyntheticMarket(symbol=SYM, start_price=100.0, seed=seed,
                               jump_prob=jump_prob, regimes=list(CRASH_HEAVY)),
        agent=MeanReversionAgent(symbol=SYM, window=20, threshold=0.02, trade_base=2.0),
        policy=PolicyEngine(PolicyConfig(
            allowed_symbols=frozenset({SYM}), max_notional_per_tx=500.0,
            max_tx_per_window=5, window_steps=10, max_drawdown_pct=drawdown, fee_rate=0.001)),
        executor=SimExecutor(fee_rate=0.001, slippage_bps=5.0),
        wallet=wallet,
    )
    return runner, runner.run(400)


def test_balances_never_negative_under_stress():
    # across many violent paths, the wallet must never be driven negative
    for seed in range(40):
        runner, _ = _run(seed, position_heavy=False)
        assert runner.wallet.quote >= -1e-9
        assert all(v >= -1e-9 for v in runner.wallet.positions.values())


def test_money_is_conserved_through_jumps_and_crashes():
    # even with gaps/jumps, equity reconstructs exactly from the fills (no value minted)
    for seed in range(20):
        _, report = _run(seed, position_heavy=False)
        base = sum(f.base_delta for f in report.fills)
        quote = 10_000.0 + sum(f.quote_delta for f in report.fills)
        assert report.final_equity == __import__("pytest").approx(
            quote + base * report.ledger[-1].price)


def test_breaker_trips_when_holding_through_crashes():
    # holding the asset while the market crashes -> the drawdown breaker MUST fire
    trips = sum(1 for s in range(50) if _run(s, position_heavy=True)[1].breaker_tripped)
    assert trips >= 25                  # the protection engages on most violent paths


def test_no_spurious_trips_in_a_calm_market():
    calm = [Regime("calm", 0.0, 0.003, 0.99)]
    runner = Runner(
        market=SyntheticMarket(symbol=SYM, seed=1, jump_prob=0.0, regimes=calm),
        agent=MeanReversionAgent(symbol=SYM, window=20, threshold=0.02, trade_base=1.0),
        policy=PolicyEngine(PolicyConfig(frozenset({SYM}), 500.0, 5, 10, 0.30, fee_rate=0.001)),
        executor=SimExecutor(), wallet=SimWallet(quote=10_000.0))
    report = runner.run(400)
    assert not report.breaker_tripped   # a calm market must NOT false-trip the breaker
