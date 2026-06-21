"""Local demo: run the agent end-to-end with zero risk and print the audit ledger.

    python run_demo.py            # normal market
    python run_demo.py --crash    # scripted crash -> watch the circuit breaker trip
"""

from __future__ import annotations

import argparse

from treasuryforge import (
    MarketSimulator,
    MeanReversionAgent,
    PolicyConfig,
    PolicyEngine,
    Runner,
    SimExecutor,
    SimWallet,
)


def build(crash: bool) -> Runner:
    symbol = "TOKEN"
    if crash:
        # Hold the asset, then price collapses -> equity falls past the drawdown
        # floor -> circuit breaker trips and halts all trading.
        prices = [100.0] * 20 + [100.0 * (0.97 ** i) for i in range(1, 60)]
        market = MarketSimulator(symbol=symbol, prices=prices)
        wallet = SimWallet(quote=0.0, positions={symbol: 100.0})
    else:
        market = MarketSimulator(symbol=symbol, start_price=100.0, seed=7,
                                 volatility=0.02)
        wallet = SimWallet(quote=10_000.0)

    fee_rate = 0.001
    policy = PolicyEngine(PolicyConfig(
        allowed_symbols=frozenset({symbol}),
        max_notional_per_tx=500.0,     # no single trade worth more than 500 quote
        max_tx_per_window=3,           # at most 3 trades ...
        window_steps=10,               # ... every 10 ticks
        max_drawdown_pct=0.15,         # trip if equity drops 15%
        fee_rate=fee_rate,
    ))

    return Runner(
        market=market,
        agent=MeanReversionAgent(symbol=symbol, window=20, threshold=0.02, trade_base=2.0),
        policy=policy,
        executor=SimExecutor(fee_rate=fee_rate, slippage_bps=5.0),
        wallet=wallet,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crash", action="store_true", help="scripted crash scenario")
    ap.add_argument("--steps", type=int, default=80)
    ap.add_argument("--ledger", action="store_true", help="print every step")
    args = ap.parse_args()

    runner = build(args.crash)
    report = runner.run(args.steps)

    if args.ledger:
        for e in report.ledger:
            print(f"t={e.ts:>3} px={e.price:>9.2f} eq={e.equity:>10.2f}  "
                  f"{e.kind:<6} {e.detail}")
        print()
    print(report.summary())


if __name__ == "__main__":
    main()
