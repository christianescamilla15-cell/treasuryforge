"""Property-based / stateful fuzzing of the policy engine.

Operationalizes 'validate before funds': instead of a handful of hand-written
cases, Hypothesis drives the real intent -> evaluate -> execute -> register_fill
loop over thousands of arbitrary histories and asserts the safety invariants hold
on EVERY allowed verdict. Any counterexample is auto-shrunk to a minimal repro.

The invariants are derived from first principles (what the gate PROMISES), not by
copying policy.py — so a bug in the engine cannot hide behind a matching bug here.
"""

from __future__ import annotations

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from treasuryforge import PolicyConfig, PolicyEngine, SimExecutor, SimWallet
from treasuryforge.types import Intent, MarketTick, Side

FEE = 0.001
CAP = 500.0
WINDOW = 10
SPEND_BUDGET = 1000.0


class PolicyMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = PolicyConfig(
            allowed_symbols=frozenset({"TOKEN"}),
            max_notional_per_tx=CAP,
            max_tx_per_window=5,
            window_steps=WINDOW,
            max_drawdown_pct=0.20,
            fee_rate=FEE,
            max_notional_per_window=SPEND_BUDGET,
        )
        self.engine = PolicyEngine(self.cfg)
        self.wallet = SimWallet(quote=10_000.0)
        self.executor = SimExecutor(fee_rate=FEE, slippage_bps=0.0)
        self.ts = 0
        self.ever_tripped = False

    @rule(
        amount=st.floats(min_value=0.01, max_value=30.0),
        price=st.floats(min_value=10.0, max_value=300.0),
        side=st.sampled_from([Side.BUY, Side.SELL]),
    )
    def step(self, amount: float, price: float, side: Side) -> None:
        self.ts += 1
        tick = MarketTick("TOKEN", price, self.ts)
        intent = Intent("TOKEN", side, amount)
        notional = amount * price

        verdict = self.engine.evaluate(intent, tick, self.wallet)

        if verdict.allowed:
            # PROMISE 1: never allow past the per-tx notional cap
            assert notional <= CAP + 1e-9
            # PROMISE 2: never allow while tripped
            assert not self.engine.tripped
            # PROMISE 3: an allowed trade is affordable / coverable
            if side is Side.BUY:
                assert notional * (1 + FEE) <= self.wallet.quote + 1e-6
            else:
                assert amount <= self.wallet.base_balance("TOKEN") + 1e-9
            # advance state exactly as the runner would
            self.executor.execute(intent, tick, self.wallet)
            self.engine.register_fill(self.ts, notional)

        if self.engine.tripped:
            self.ever_tripped = True

    @invariant()
    def breaker_is_latched(self) -> None:
        # PROMISE 4: a tripped breaker never un-trips within a run
        if self.ever_tripped:
            assert self.engine.tripped

    @invariant()
    def balances_never_negative(self) -> None:
        # PROMISE 5: the wallet can never be driven negative
        assert self.wallet.quote >= -1e-9
        assert all(v >= -1e-9 for v in self.wallet.positions.values())


TestPolicyMachine = PolicyMachine.TestCase
TestPolicyMachine.settings = settings(max_examples=200, stateful_step_count=40, deadline=None)
