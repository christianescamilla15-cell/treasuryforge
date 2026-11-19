"""Rules that existed only as prose until now (docs/reglas.md maps every rule to its tests).

1. The 8 policy rules are evaluated IN ORDER and the first violated rule names the denial.
   Peeling one violation at a time proves the order end to end (a reordering mutant fails).
2. A denied intent never consumes the rate limit (the spend-budget twin already exists).
3. Invalid transitions of the order state machine: terminal states never move again.
4. Invalid transitions of the stage ladder: no skipped rungs, only KILL reaches DEAD,
   DEAD is absorbing — checked exhaustively over every stage x every outcome profile.
"""

from __future__ import annotations

import dataclasses

import pytest

from treasuryforge import Intent, MarketTick, Side, SimWallet
from treasuryforge.exchanges.bitso.errors import NON_RETRYABLE, BitsoError
from treasuryforge.journal import Journal
from treasuryforge.orders import IdempotentOrderManager, OrderState
from treasuryforge.policy import PolicyConfig, PolicyEngine
from treasuryforge.risk import LivePerformance, Stage, evaluate_stage
from treasuryforge.risk.stages import STAGE_CAPITAL

# --------------------------------------------------------------------------- 1. order


@dataclasses.dataclass
class Scenario:
    """Every flag True = that rule is violated. Each one is independent of the others."""

    kill: bool = True
    tripped: bool = True
    stale: bool = True
    foreign_symbol: bool = True
    over_cap: bool = True
    rate_full: bool = True
    spend_full: bool = True
    broke: bool = True

    def run(self) -> str:
        cfg = PolicyConfig(
            allowed_symbols=frozenset({"TOKEN"}), max_notional_per_tx=500.0,
            max_tx_per_window=1, window_steps=10, max_drawdown_pct=0.20,
            kill_switch=self.kill, max_notional_per_window=1000.0, max_staleness_ns=10,
        )
        eng = PolicyEngine(cfg)
        eng.restore({
            "starting_equity": 100.0,                      # floor 80; equity stays >= 100
            "tripped": self.tripped,
            "recent_ts": [0] if self.rate_full else [],
            "spend": [[0, 900.0]] if self.spend_full else [],
        })
        notional = 600.0 if self.over_cap else 200.0
        intent = Intent("SCAM" if self.foreign_symbol else "TOKEN", Side.BUY, notional / 100.0)
        wallet = SimWallet(quote=100.0 if self.broke else 10_000.0)
        verdict = eng.evaluate(intent, MarketTick(intent.symbol, 100.0, 1), wallet,
                               data_age_ns=100 if self.stale else 1)
        return verdict.reason


EXPECTED_ORDER = [
    ("kill", "DENY:kill_switch"),
    ("tripped", "DENY:circuit_breaker"),
    ("stale", "DENY:stale_data"),
    ("foreign_symbol", "DENY:symbol"),
    ("over_cap", "DENY:notional"),
    ("rate_full", "DENY:rate_limit"),
    ("spend_full", "DENY:spend_budget"),
    ("broke", "DENY:insufficient_quote"),
]


def test_the_8_rules_fire_in_their_documented_order():
    s = Scenario()
    for flag, prefix in EXPECTED_ORDER:
        reason = s.run()
        assert reason.startswith(prefix), f"with {flag} still violated expected {prefix}, got {reason}"
        setattr(s, flag, False)                              # fix this one; the next rule must surface
    assert s.run() == "ALLOW"


@pytest.mark.parametrize(("flag", "prefix"), EXPECTED_ORDER)
def test_each_rule_alone_denies_with_its_own_name(flag, prefix):
    s = Scenario(**{f.name: False for f in dataclasses.fields(Scenario)})
    setattr(s, flag, True)
    assert s.run().startswith(prefix)


# --------------------------------------------------------------------------- 2. no debit on deny


def test_denied_intents_never_consume_the_rate_limit():
    cfg = PolicyConfig(allowed_symbols=frozenset({"TOKEN"}), max_notional_per_tx=500.0,
                       max_tx_per_window=1, window_steps=10, max_drawdown_pct=0.20)
    eng = PolicyEngine(cfg)
    w = SimWallet(quote=10_000.0)
    for ts in range(5):                                      # five denials inside the window
        assert not eng.evaluate(Intent("SCAM", Side.BUY, 1.0), MarketTick("SCAM", 100.0, ts), w).allowed
    assert eng.evaluate(Intent("TOKEN", Side.BUY, 1.0), MarketTick("TOKEN", 100.0, 5), w).allowed


# --------------------------------------------------------------------------- 3. order machine


class _Exec:
    """Executor that must never be called: any call is an invalid transition."""

    def place_order(self, intent, origin_id):                # pragma: no cover - must not run
        raise AssertionError(f"terminal order {origin_id} was re-posted")

    def reconcile(self, handle, symbol):                     # pragma: no cover - must not run
        raise AssertionError(f"terminal order {handle.origin_id} was reconciled")


class _RejectOnce:
    def __init__(self):
        self.place_calls = 0

    def place_order(self, intent, origin_id):
        self.place_calls += 1
        raise BitsoError(NON_RETRYABLE, "0379", "insufficient funds", 400)

    def reconcile(self, handle, symbol):                     # pragma: no cover - must not run
        raise AssertionError("a REJECTED order never landed; there is nothing to reconcile")


def test_rejected_is_terminal_across_resubmit_and_restart(tmp_path):
    ex = _RejectOnce()
    m = IdempotentOrderManager(ex, Journal(str(tmp_path / "orders")))
    assert m.submit(Intent("BTC", Side.BUY, 0.001), "o1", "BTC").state is OrderState.REJECTED
    # REJECTED -> anything is invalid: neither a resubmit nor a restart may move it
    assert m.submit(Intent("BTC", Side.BUY, 0.001), "o1", "BTC").state is OrderState.REJECTED
    m2 = IdempotentOrderManager(_Exec(), Journal(str(tmp_path / "orders")))
    assert m2.recover() == []
    assert m2._orders["o1"].state is OrderState.REJECTED
    assert ex.place_calls == 1


# --------------------------------------------------------------------------- 4. stage ladder

_BASE = dict(edge_retention=0.80, slippage_ratio=1.2, live_dd=0.10, expected_dd_p75=0.15,
             expected_dd_p90=0.20, stress_dd_p95=0.30, sample_size=50, min_sample=30)
PROFILES = {
    "promote": {},
    "hold": {"edge_retention": 0.60},
    "demote": {"slippage_ratio": 2.5},
    "kill": {"execution_failure": True},
    "kill_and_demote": {"edge_retention": 0.20, "slippage_ratio": 3.0},
}


@pytest.mark.parametrize("profile", sorted(PROFILES))
@pytest.mark.parametrize("stage", list(Stage))
def test_stage_ladder_never_makes_an_invalid_transition(stage, profile):
    d = evaluate_stage(stage, LivePerformance(**{**_BASE, **PROFILES[profile]}))
    assert d.from_stage is stage
    if stage is Stage.DEAD:                                  # DEAD is absorbing
        assert (d.to_stage, d.action) == (Stage.DEAD, "DEAD")
    elif d.action == "KILL":                                 # only KILL reaches DEAD, from any rung
        assert d.to_stage is Stage.DEAD
    else:                                                    # otherwise one rung at most, never DEAD
        assert d.to_stage is not Stage.DEAD
        assert abs(int(d.to_stage) - int(stage)) <= 1
        assert {"PROMOTE": 1, "DEMOTE": -1, "HOLD": 0}[d.action] == int(d.to_stage) - int(stage) \
            or (d.action == "DEMOTE" and stage is Stage.PAPER_LIVE and d.to_stage is Stage.PAPER_LIVE)
    assert d.capital_fraction == STAGE_CAPITAL[d.to_stage]   # capital always follows the rung
