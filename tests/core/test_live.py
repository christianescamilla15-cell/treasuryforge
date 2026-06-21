"""Live supervisor — the execution-safety layer wired into one guarded step.

Proves the orchestration: startup refuses on a bad preflight; a step halts (and
places NOTHING) on stale data or a tripped dead-man's switch; an approved intent
is routed through the idempotent manager; every step beats the watchdog; and the
supervisor fires the fail-safe when the loop stops beating. All clocks/feeds/exec
are injected — no network, keys, or wall-clock.
"""

from __future__ import annotations

import dataclasses

import pytest

from treasuryforge.exchanges.bitso.executor import OrderHandle, Unfilled
from treasuryforge.journal import Journal
from treasuryforge.live import LiveSupervisor, StepKind, StepResult
from treasuryforge.orders import IdempotentOrderManager
from treasuryforge.policy import PolicyConfig, PolicyEngine
from treasuryforge.preflight import PreflightInputs
from treasuryforge.staleness import NS_PER_S, StalenessGate
from treasuryforge.types import Fill, Intent, MarketTick, Side
from treasuryforge.wallet import SimWallet
from treasuryforge.watchdog import DeadMansSwitch

W = 1_700_000_000 * NS_PER_S       # a sane wall-clock base (ns)
M = 50_000 * NS_PER_S


class FakeAgent:
    def __init__(self, intent):
        self.intent = intent

    def decide(self, tick, wallet):
        return self.intent


class FakeExec:
    def __init__(self, land=True):
        self.land = land
        self.placed = []

    def place_order(self, intent, origin_id):
        self.placed.append(origin_id)
        return OrderHandle(origin_id=origin_id, oid=f"oid-{origin_id}", book="btc_mxn", side=intent.side)

    def reconcile(self, handle, symbol):
        if self.land:
            return Fill(symbol=symbol, side=handle.side, base_amount=0.001, price=1e6,
                        fee=0.0, ts=1, fee_currency="base")
        return Unfilled(handle, "no fills yet")


def _cfg(**over):
    base = dict(allowed_symbols=frozenset({"BTC"}), max_notional_per_tx=1e9,
                max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.5,
                max_notional_per_window=1e12, max_staleness_ns=10 * NS_PER_S)
    base.update(over)
    return PolicyConfig(**base)


def _sup(tmp_path, *, intent=None, land=True, wall=W, mono=M, timeout=30.0, max_age=5 * NS_PER_S):
    ex = FakeExec(land=land)
    sup = LiveSupervisor(
        policy=PolicyEngine(_cfg()),
        agent=FakeAgent(intent),
        orders=IdempotentOrderManager(ex, Journal(str(tmp_path / "orders"))),
        watchdog=DeadMansSwitch(str(tmp_path / "hb.json"), timeout_s=timeout),
        staleness=StalenessGate(max_data_age_ns=max_age),
        wall_ns=lambda: wall,
        mono_ns=lambda: mono,
    )
    return sup, ex


def _tick():
    return MarketTick("BTC", 1_000_000.0, ts=1)


def _buy():
    return Intent("BTC", Side.BUY, 0.001)


# -- startup -----------------------------------------------------------------
def _inputs(tmp_path, **over):
    base = dict(mode="live", config=_cfg(), journal_dir=str(tmp_path / "j"),
                has_credentials=True, now_wall=1_700_000_000.0, exchange_reachable=True,
                data_age_s=1.0, clock_skew_s=0.3)
    base.update(over)
    return PreflightInputs(**base)


def test_start_refuses_on_bad_preflight(tmp_path):
    sup, _ = _sup(tmp_path)
    assert not sup.start(_inputs(tmp_path, has_credentials=False)).ready


def test_start_ready_on_healthy_preflight(tmp_path):
    sup, _ = _sup(tmp_path)
    assert sup.start(_inputs(tmp_path)).ready


# -- the guarded step --------------------------------------------------------
def test_stale_data_halts_and_places_nothing(tmp_path):
    sup, ex = _sup(tmp_path, intent=_buy(), max_age=5 * NS_PER_S)
    sup.observe_data(W - 60 * NS_PER_S)            # data is 60s old, budget 5s
    r = sup.step(_tick(), SimWallet(10_000))
    assert r.kind is StepKind.HALTED_STALE and not r.traded
    assert ex.placed == []                          # nothing routed to the exchange


def test_no_data_observed_halts(tmp_path):
    sup, ex = _sup(tmp_path, intent=_buy())
    r = sup.step(_tick(), SimWallet(10_000))        # never observed data
    assert r.kind is StepKind.HALTED_STALE and ex.placed == []


def test_fresh_allowed_intent_routes_through_idempotent_submit(tmp_path):
    sup, ex = _sup(tmp_path, intent=_buy(), land=True)
    sup.observe_data(W)
    r = sup.step(_tick(), SimWallet(10_000))
    assert r.kind is StepKind.FILLED and r.traded
    assert ex.placed == ["live:BTC:1"]              # deterministic origin_id


def test_resting_order_reports_open(tmp_path):
    sup, _ = _sup(tmp_path, intent=_buy(), land=False)    # accepted, no fill yet
    sup.observe_data(W)
    r = sup.step(_tick(), SimWallet(10_000))
    assert r.kind is StepKind.OPEN


def test_hold_when_agent_has_no_signal(tmp_path):
    sup, ex = _sup(tmp_path, intent=None)
    sup.observe_data(W)
    r = sup.step(_tick(), SimWallet(10_000))
    assert r.kind is StepKind.HOLD and ex.placed == []


def test_policy_denial_blocks_order(tmp_path):
    sup, ex = _sup(tmp_path, intent=Intent("SCAM", Side.BUY, 0.001))   # not in allowlist
    sup.observe_data(W)
    r = sup.step(_tick(), SimWallet(10_000))
    assert r.kind is StepKind.DENIED and "allowlist" in r.reason and ex.placed == []


def test_step_beats_the_watchdog(tmp_path):
    sup, _ = _sup(tmp_path, intent=None)
    sup.observe_data(W)
    sup.step(_tick(), SimWallet(10_000))
    assert sup.watchdog.read().ts == W / NS_PER_S   # liveness recorded


def test_tripped_dead_man_switch_halts_step(tmp_path):
    sup, ex = _sup(tmp_path, intent=_buy(), timeout=10.0)
    sup.watchdog.beat(now=100.0)
    sup.watchdog.supervise(now=200.0, on_trip=lambda r: None)   # trip it
    sup.observe_data(W)
    r = sup.step(_tick(), SimWallet(10_000))
    assert r.kind is StepKind.HALTED_DEAD and ex.placed == []


# -- dead-man's switch -------------------------------------------------------
def test_supervise_fires_failsafe_when_loop_stops_beating(tmp_path):
    sup, _ = _sup(tmp_path, intent=None, timeout=10.0)
    sup.observe_data(W)
    sup.step(_tick(), SimWallet(10_000))            # beats at W/1e9 = 1.7e9 s
    calls = []
    fired = sup.supervise(now_wall_s=W / NS_PER_S + 20.0, on_trip=calls.append)   # 20s later
    assert fired and len(calls) == 1


# -- mutation hardening: exact StepKind values, reasons, frozen result --------
def test_step_kind_values_are_exact():
    assert [k.value for k in StepKind] == [
        "HALTED_DEAD", "HALTED_STALE", "HOLD", "DENIED", "SUBMITTED", "FILLED", "OPEN", "REJECTED"]


def test_step_result_frozen_and_outcome_defaults_none():
    r = StepResult(StepKind.HOLD, "x")
    assert r.outcome is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.kind = StepKind.FILLED


def test_traded_flag_per_kind():
    traded = {StepKind.SUBMITTED, StepKind.FILLED, StepKind.OPEN}
    for k in StepKind:
        assert StepResult(k, "x").traded == (k in traded)


def test_dead_man_reason_exact(tmp_path):
    sup, _ = _sup(tmp_path, intent=_buy(), timeout=10.0)
    sup.watchdog.beat(now=100.0)
    sup.watchdog.supervise(now=200.0, on_trip=lambda r: None)
    sup.observe_data(W)
    assert sup.step(_tick(), SimWallet(10_000)).reason == "dead-man's switch tripped"


def test_hold_reason_exact(tmp_path):
    sup, _ = _sup(tmp_path, intent=None)
    sup.observe_data(W)
    assert sup.step(_tick(), SimWallet(10_000)).reason == "no signal"
