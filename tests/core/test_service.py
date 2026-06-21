"""Service runner — the fail-closed outer process. Proves the lifecycle is safe:
a bad preflight never trades (SAFE_HALTED), in-flight orders are reconciled before
the loop, a tripped dead-man's switch exits cleanly, and ANY exception fires the
fail-safe (cancel + kill) on the way down."""

from __future__ import annotations

from treasuryforge.exchanges.bitso.executor import OrderHandle, Unfilled
from treasuryforge.journal import Journal
from treasuryforge.live import LiveSupervisor, StepKind
from treasuryforge.orders import IdempotentOrderManager, OrderRecord, OrderState
from treasuryforge.policy import PolicyConfig, PolicyEngine
from treasuryforge.preflight import PreflightInputs
from treasuryforge.service import Service, ServiceExit
from treasuryforge.staleness import NS_PER_S, StalenessGate
from treasuryforge.types import Fill, Intent, MarketTick, Side
from treasuryforge.wallet import SimWallet
from treasuryforge.watchdog import DeadMansSwitch

W = 1_700_000_000 * NS_PER_S
M = 50_000 * NS_PER_S


class FakeAgent:
    def __init__(self, intent):
        self.intent = intent

    def decide(self, tick, wallet):
        return self.intent


class FakeExec:
    def __init__(self, land=True):
        self.land = land

    def place_order(self, intent, origin_id):
        return OrderHandle(origin_id=origin_id, oid=f"oid-{origin_id}", book="btc_mxn", side=intent.side)

    def reconcile(self, handle, symbol):
        if self.land:
            return Fill(symbol=symbol, side=handle.side, base_amount=0.001, price=1e6,
                        fee=0.0, ts=1, fee_currency="base")
        return Unfilled(handle, "no fills yet")


def _cfg():
    return PolicyConfig(allowed_symbols=frozenset({"BTC"}), max_notional_per_tx=1e9,
                        max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.5,
                        max_notional_per_window=1e12, max_staleness_ns=10 * NS_PER_S)


def _make(tmp_path, *, intent=None, land=True, timeout=30.0):
    orders = IdempotentOrderManager(FakeExec(land=land), Journal(str(tmp_path / "orders")))
    sup = LiveSupervisor(
        policy=PolicyEngine(_cfg()), agent=FakeAgent(intent), orders=orders,
        watchdog=DeadMansSwitch(str(tmp_path / "hb.json"), timeout_s=timeout),
        staleness=StalenessGate(max_data_age_ns=5 * NS_PER_S),
        wall_ns=lambda: W, mono_ns=lambda: M)
    calls = []
    return Service(sup, on_halt=calls.append), sup, calls


def _inputs(tmp_path, **over):
    base = dict(mode="live", config=_cfg(), journal_dir=str(tmp_path / "j"),
                has_credentials=True, now_wall=1_700_000_000.0, exchange_reachable=True,
                data_age_s=1.0, clock_skew_s=0.3)
    base.update(over)
    return PreflightInputs(**base)


def _tick():
    return MarketTick("BTC", 1_000_000.0, ts=1)


def _feed(n, wallet, data_wall=W):
    for _ in range(n):
        yield (_tick(), data_wall, wallet)


def test_safe_halted_on_bad_preflight_never_trades(tmp_path):
    svc, _, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001))
    code = svc.run(_inputs(tmp_path, has_credentials=False), _feed(3, SimWallet(10_000)))
    assert code is ServiceExit.SAFE_HALTED
    assert svc.steps == []                              # the loop never ran
    assert len(calls) == 1 and "SAFE_HALTED" in calls[0]


def test_clean_run_returns_ok_and_trades(tmp_path):
    svc, _, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001))
    code = svc.run(_inputs(tmp_path), _feed(1, SimWallet(10_000)))
    assert code is ServiceExit.OK
    assert svc.steps[0].kind is StepKind.FILLED and calls == []


def test_recovers_inflight_order_before_the_loop(tmp_path):
    svc, sup, _ = _make(tmp_path, intent=None, land=True)
    # an order was in flight when the previous process died; it has since filled
    sup.orders._orders["o1"] = OrderRecord("o1", OrderState.SUBMITTED, symbol="BTC", oid="oid-o1")
    svc.run(_inputs(tmp_path), _feed(0, SimWallet(10_000)))   # empty feed: only start + recover
    assert sup.orders._orders["o1"].state is OrderState.FILLED


def test_dead_man_switch_exits_clean(tmp_path):
    svc, sup, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001), timeout=10.0)
    sup.watchdog.beat(now=100.0)
    sup.watchdog.supervise(now=200.0, on_trip=lambda r: None)    # pre-trip
    code = svc.run(_inputs(tmp_path), _feed(1, SimWallet(10_000)))
    assert code is ServiceExit.DEAD_MAN and "dead-man" in calls[-1]


def test_stale_data_is_not_fatal(tmp_path):
    svc, _, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001))
    code = svc.run(_inputs(tmp_path), _feed(2, SimWallet(10_000), data_wall=W - 60 * NS_PER_S))
    assert code is ServiceExit.OK                        # not a crash; just no trades
    assert all(s.kind is StepKind.HALTED_STALE for s in svc.steps) and calls == []


def test_fails_closed_on_unexpected_exception(tmp_path):
    svc, _, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001))

    def boom(wallet):
        yield (_tick(), W, wallet)
        raise RuntimeError("feed exploded")

    code = svc.run(_inputs(tmp_path), boom(SimWallet(10_000)))
    assert code is ServiceExit.ERROR
    assert len(calls) == 1 and "unexpected error" in calls[0] and "feed exploded" in calls[0]


# -- mutation hardening: exact exit codes + fail-safe messages ---------------
def test_exit_codes_are_exact():
    assert (int(ServiceExit.OK), int(ServiceExit.SAFE_HALTED),
            int(ServiceExit.DEAD_MAN), int(ServiceExit.ERROR)) == (0, 10, 20, 30)


def test_safe_halted_message_lists_failed_checks_exactly(tmp_path):
    from treasuryforge.preflight import run_preflight
    svc, _, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001))
    inp = _inputs(tmp_path, has_credentials=False, config=None)   # several failures
    svc.run(inp, _feed(0, SimWallet(10_000)))
    expected = "preflight SAFE_HALTED: " + ",".join(c.name for c in run_preflight(inp).failures())
    assert calls[0] == expected                      # exact prefix + comma-joined names


def test_dead_man_halt_message_exact(tmp_path):
    svc, sup, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001), timeout=10.0)
    sup.watchdog.beat(now=100.0)
    sup.watchdog.supervise(now=200.0, on_trip=lambda r: None)
    svc.run(_inputs(tmp_path), _feed(1, SimWallet(10_000)))
    assert calls[-1] == "dead-man's switch tripped"


def test_error_halt_message_prefix_and_repr(tmp_path):
    svc, _, calls = _make(tmp_path, intent=Intent("BTC", Side.BUY, 0.001))

    def boom(wallet):
        yield (_tick(), W, wallet)
        raise RuntimeError("kaboom")

    svc.run(_inputs(tmp_path), boom(SimWallet(10_000)))
    assert calls[0].startswith("unexpected error: ") and "kaboom" in calls[0]
