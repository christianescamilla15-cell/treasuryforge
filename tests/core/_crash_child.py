"""Child process for the crash-safety test: trips the breaker (which the runner
checkpoints durably), then hard-kills itself with os._exit so NO clean shutdown,
atexit, or finalizer runs. If the breaker survives this, durability is real."""

import os
import sys

from treasuryforge import (
    Journal,
    MarketSimulator,
    MeanReversionAgent,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
)


def main() -> None:
    d = sys.argv[1]
    sym = "TOKEN"
    prices = [100.0] * 20 + [100.0 * (0.97 ** i) for i in range(1, 40)]
    policy = PolicyEngine(PolicyConfig(
        allowed_symbols=frozenset({sym}), max_notional_per_tx=500.0,
        max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.15, fee_rate=0.001))
    runner = Runner(
        market=MarketSimulator(symbol=sym, prices=prices),
        agent=MeanReversionAgent(symbol=sym, window=20, threshold=0.02, trade_base=1.0),
        policy=policy, executor=SimExecutor(),
        wallet=SimWallet(quote=0.0, positions={sym: 100.0}),
        journal=Journal(d),
    )
    runner.run(60)            # breaker trips and is checkpointed mid-run
    os._exit(1)               # hard crash — bypass all clean-shutdown paths


if __name__ == "__main__":
    main()
