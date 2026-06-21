"""The deployment gate can only WITHHOLD capital — never spend it. These tests prove
it stays HOLD on every unproven track record and only releases the micro tier when DSR,
net APR, intervals AND days all clear, sizing the freshly-promoted edge down to tier."""

from __future__ import annotations

from treasuryforge.backtest.metrics import deflated_sharpe_ratio
from treasuryforge.deployment_gate import DeploymentGate, GatedStrategy
from treasuryforge.risk.stages import STAGE_CAPITAL, Stage
from treasuryforge.types import Intent, MarketTick, Side
from treasuryforge.wallet import SimWallet

# A strong, low-variance, positive series spanning ~20 days -> clears every gate.
_STRONG = [0.003, 0.001] * 25                       # n=50, mean 0.002, sr 2.0
_SPAN_20D = [i * (20 * 86400 // 49) for i in range(50)]   # max-min ~= 20 days


def test_strong_record_captures_a_passing_dsr() -> None:
    # ground truth: the realistic strong series really does clear the 0.60 DSR bar
    assert deflated_sharpe_ratio(_STRONG, n_trials=1) >= 0.60


def test_default_gate_deploys_on_strong_record_at_micro_tier() -> None:
    v = DeploymentGate().evaluate(_STRONG, _SPAN_20D)
    assert v.deploy is True
    assert v.tier_fraction == STAGE_CAPITAL[Stage.MICRO_CAPITAL] == 0.01
    assert v.n == 50 and v.days >= 14.0


def test_trial_sharpes_deflates_dsr_and_blocks_a_wide_scan() -> None:
    # _STRONG clears the gate as a single trial. Evaluated as ONE of 50 candidates, the
    # multiple-testing deflation raises the benchmark so the SAME record no longer deploys --
    # a wider universe cannot manufacture a false edge.
    trial_sharpes = [-2.0 + 4.0 * i / 49 for i in range(50)]   # 50 spread per-coin Sharpes
    single = DeploymentGate().evaluate(_STRONG, _SPAN_20D)
    wide = DeploymentGate().evaluate(_STRONG, _SPAN_20D, trial_sharpes=trial_sharpes)
    assert single.deploy is True
    assert wide.dsr < single.dsr             # deflation lowered the survival probability
    assert wide.deploy is False              # and pushed it below the 0.60 bar


def test_blocks_on_too_few_intervals() -> None:
    v = DeploymentGate().evaluate([0.002] * 10, list(range(0, 10 * 86400, 86400)))
    assert v.deploy is False
    assert "insufficient" in v.reason and v.tier_fraction == 0.0


def test_blocks_on_all_zero_returns() -> None:
    v = DeploymentGate().evaluate([0.0] * 50, _SPAN_20D)
    assert v.deploy is False and "insufficient" in v.reason


def test_dsr_gate_isolated() -> None:
    # an impossible DSR bar fails ONLY on DSR even though APR + sample pass
    v = DeploymentGate(min_dsr=1.01).evaluate(_STRONG, _SPAN_20D)
    assert v.deploy is False and "DSR" in v.reason and "APR" not in v.reason


def test_apr_gate_isolated() -> None:
    # a 10000% APR bar fails ONLY on APR even though DSR + sample pass
    v = DeploymentGate(min_net_apr=100.0).evaluate(_STRONG, _SPAN_20D)
    assert v.deploy is False and "APR" in v.reason and "DSR" not in v.reason


def test_days_gate_isolated() -> None:
    # 50 strong intervals but compressed into 2 days -> fails ONLY on days
    span_2d = [i * (2 * 86400 // 49) for i in range(50)]
    v = DeploymentGate().evaluate(_STRONG, span_2d)
    assert v.deploy is False and "d <" in v.reason


class _FakeSignal:
    """Records whether it was consulted, so we can prove the gate short-circuits."""

    def __init__(self, intent: Intent | None) -> None:
        self.intent = intent
        self.calls = 0

    def decide(self, tick: MarketTick, wallet: SimWallet) -> Intent | None:
        self.calls += 1
        return self.intent


def _tick() -> MarketTick:
    return MarketTick("BTC", 1_000_000.0, ts=1)


def test_gated_strategy_stays_hold_and_never_consults_signal_when_blocked() -> None:
    sig = _FakeSignal(Intent("BTC", Side.BUY, 0.001))
    gs = GatedStrategy(sig, track_record=lambda: ([0.0] * 50, _SPAN_20D))
    assert gs.decide(_tick(), SimWallet(10_000)) is None
    assert sig.calls == 0                              # gated BEFORE the signal runs
    assert gs.last_verdict is not None and gs.last_verdict.deploy is False


def test_gated_strategy_releases_signal_capped_to_tier_when_cleared() -> None:
    sig = _FakeSignal(Intent("BTC", Side.BUY, 0.001))      # wants 0.001 BTC
    gs = GatedStrategy(sig, track_record=lambda: (_STRONG, _SPAN_20D))
    out = gs.decide(_tick(), SimWallet(10_000))
    assert out is not None and sig.calls == 1
    # tier budget = 1% * 10_000 = 100 quote -> 100 / 1_000_000 = 0.0001 BTC max
    assert out.base_amount == 0.0001
    assert "tier-capped" in out.reason


def test_tier_cap_passes_small_intent_through_unchanged() -> None:
    sig = _FakeSignal(Intent("BTC", Side.BUY, 0.00005))    # already under the 0.0001 cap
    gs = GatedStrategy(sig, track_record=lambda: (_STRONG, _SPAN_20D))
    out = gs.decide(_tick(), SimWallet(10_000))
    assert out is not None and out.base_amount == 0.00005 and "tier-capped" not in out.reason


def test_tier_cap_applies_to_quote_amount_orders() -> None:
    sig = _FakeSignal(Intent("BTC", Side.BUY, 0.0, quote_amount=500.0))  # wants 500 quote
    gs = GatedStrategy(sig, track_record=lambda: (_STRONG, _SPAN_20D))
    out = gs.decide(_tick(), SimWallet(10_000))
    assert out is not None and out.quote_amount == 100.0   # capped to the 1% tier budget
