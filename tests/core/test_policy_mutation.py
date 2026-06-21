"""Boundary + exactness tests for the policy engine — pin the EXACT rule edges and
verdict messages so mutations to comparisons, epsilons, fee arithmetic and reason
strings are caught (mutation-testing hardening of the money-governing engine)."""

from __future__ import annotations

from treasuryforge import Intent, MarketTick, Side, SimWallet
from treasuryforge.policy import PolicyConfig, PolicyEngine


def cfg(**over):
    base = dict(allowed_symbols=frozenset({"TOKEN"}), max_notional_per_tx=500.0,
                max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.20, fee_rate=0.0)
    base.update(over)
    return PolicyConfig(**base)


def tick(price=100.0, ts=0):
    return MarketTick("TOKEN", price, ts)


def buy(amount):
    return Intent("TOKEN", Side.BUY, amount)


# -- exact verdict messages (kills the XX-wrapped string mutants) -------------
def test_allow_reason_is_exactly_ALLOW():
    v = PolicyEngine(cfg()).evaluate(buy(1.0), tick(), SimWallet(10_000))
    assert v.allowed and v.reason == "ALLOW"


def test_every_denial_reason_starts_with_DENY_and_names_the_rule():
    cases = [
        (cfg(kill_switch=True), buy(1.0), SimWallet(10_000), tick(), "DENY:kill_switch"),
        (cfg(), Intent("SCAM", Side.BUY, 1.0), SimWallet(10_000), tick(), "DENY:symbol"),
        (cfg(max_notional_per_tx=50.0), buy(1.0), SimWallet(10_000), tick(100.0), "DENY:notional"),
        (cfg(min_notional_per_tx=10.0), buy(0.05), SimWallet(10_000), tick(100.0), "DENY:min_notional"),
        (cfg(), buy(1.0), SimWallet(50.0), tick(100.0), "DENY:insufficient_quote"),
        (cfg(), Intent("TOKEN", Side.SELL, 5.0), SimWallet(10_000), tick(), "DENY:insufficient_base"),
    ]
    for c, intent, wallet, tk, prefix in cases:
        v = PolicyEngine(c).evaluate(intent, tk, wallet)
        assert not v.allowed and v.reason.startswith(prefix), v.reason


def test_rate_limit_and_spend_and_stale_messages():
    eng = PolicyEngine(cfg(max_tx_per_window=1, window_steps=10))
    w = SimWallet(10_000)
    eng.evaluate(buy(1.0), tick(ts=0), w); eng.register_fill(0, 100.0)
    assert eng.evaluate(buy(1.0), tick(ts=1), w).reason.startswith("DENY:rate_limit")

    eng2 = PolicyEngine(cfg(max_notional_per_window=100.0))
    w2 = SimWallet(10_000)
    eng2.evaluate(buy(1.0), tick(ts=0), w2); eng2.register_fill(0, 100.0)
    assert eng2.evaluate(buy(1.0), tick(ts=1), w2).reason.startswith("DENY:spend_budget")

    eng3 = PolicyEngine(cfg(max_staleness_ns=1000))
    assert eng3.evaluate(buy(1.0), tick(), SimWallet(10_000), data_age_ns=5000).reason \
        .startswith("DENY:stale_data")


# -- exact boundaries (kills the >/>= and epsilon mutants) --------------------
def test_notional_exactly_at_cap_is_allowed():
    # 5 * 100 = 500 == cap -> allowed (rule is strict >)
    assert PolicyEngine(cfg(max_notional_per_tx=500.0)).evaluate(
        buy(5.0), tick(100.0), SimWallet(10_000)).allowed


def test_min_notional_exactly_at_floor_is_allowed():
    # 0.1 * 100 = 10 == floor -> allowed (rule denies strictly below)
    assert PolicyEngine(cfg(min_notional_per_tx=10.0)).evaluate(
        buy(0.1), tick(100.0), SimWallet(10_000)).allowed


def test_breaker_at_exactly_the_floor_does_not_trip():
    eng = PolicyEngine(cfg(max_drawdown_pct=0.20))
    w = SimWallet(quote=0.0, positions={"TOKEN": 100.0})
    eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(100.0, 0), w)   # anchor equity=10_000
    # price 80 -> equity 8_000 == floor (10_000*0.8); strict < => NOT tripped
    v = eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(80.0, 1), w)
    assert v.allowed and not eng.tripped


def test_solvency_buy_cost_includes_fee_multiplicatively():
    # fee makes the cost HIGHER: 500 notional at 10% fee = 550 > 500 quote -> denied.
    # (a '/' mutation would compute 454 and wrongly allow it.)
    eng = PolicyEngine(cfg(fee_rate=0.10))
    v = eng.evaluate(buy(5.0), tick(100.0), SimWallet(500.0))          # notional 500
    assert not v.allowed and v.reason.startswith("DENY:insufficient_quote")
    # exactly affordable at zero fee
    assert PolicyEngine(cfg(fee_rate=0.0)).evaluate(
        buy(5.0), tick(100.0), SimWallet(500.0)).allowed


def test_solvency_sell_exactly_at_holdings_is_allowed():
    assert PolicyEngine(cfg()).evaluate(
        Intent("TOKEN", Side.SELL, 5.0), tick(), SimWallet(0.0, {"TOKEN": 5.0})).allowed


def test_staleness_exactly_at_budget_is_allowed():
    assert PolicyEngine(cfg(max_staleness_ns=1000)).evaluate(
        buy(1.0), tick(), SimWallet(10_000), data_age_ns=1000).allowed


# -- snapshot/restore exactness ----------------------------------------------
def test_snapshot_has_expected_keys_and_restore_defaults_to_not_tripped():
    eng = PolicyEngine(cfg())
    eng.evaluate(buy(1.0), tick(), SimWallet(10_000))
    snap = eng.snapshot()
    assert set(snap) == {"starting_equity", "tripped", "recent_ts", "spend"}
    fresh = PolicyEngine(cfg())
    fresh.restore({})                      # empty state -> tripped defaults to False
    assert fresh.tripped is False


def test_restore_preserves_recent_ts_key():
    eng = PolicyEngine(cfg())
    eng.evaluate(buy(1.0), tick(ts=0), SimWallet(10_000))
    eng.register_fill(3, 100.0)
    revived = PolicyEngine(cfg())
    revived.restore(eng.snapshot())
    # the spend/rate windows carried over (wrong snapshot key would lose them)
    assert list(revived._recent_ts) == [3]


def test_restore_repopulates_the_spend_window():
    eng = PolicyEngine(cfg(max_notional_per_window=100.0))
    eng.evaluate(buy(1.0), tick(100.0, 0), SimWallet(10_000)); eng.register_fill(0, 100.0)
    revived = PolicyEngine(cfg(max_notional_per_window=100.0))
    revived.restore(eng.snapshot())            # wrong 'spend' key or =None would lose this
    assert sum(n for _, n in revived._spend) == 100.0
    # the restored spend actually enforces the budget on the next evaluate
    v = revived.evaluate(buy(1.0), tick(100.0, 1), SimWallet(10_000))
    assert not v.allowed and v.reason.startswith("DENY:spend_budget")


# -- defaults exercised via OMITTED args (kills default-value mutants) --------
def test_default_fee_rate_is_zero_so_cost_equals_notional():
    # config WITHOUT fee_rate -> default 0.0 -> a buy of exactly the quote is affordable
    # (default 1.0 would double the cost and deny; default None would TypeError).
    c = PolicyConfig(allowed_symbols=frozenset({"TOKEN"}), max_notional_per_tx=10_000.0,
                     max_tx_per_window=100, window_steps=10, max_drawdown_pct=0.20)
    assert PolicyEngine(c).evaluate(buy(5.0), tick(100.0), SimWallet(500.0)).allowed


def test_fresh_engine_tripped_is_the_bool_false():
    # _tripped default must be False (the property is read directly), not None
    assert PolicyEngine(cfg()).tripped is False


def test_register_fill_defaults_to_zero_notional():
    eng = PolicyEngine(cfg())
    eng.register_fill(7)                        # notional omitted -> 0.0, not 1.0
    assert eng.snapshot()["spend"] == [[7, 0.0]]


# -- exact reason content (kills message string/arithmetic mutants) -----------
def test_circuit_breaker_reason_is_well_formed():
    eng = PolicyEngine(cfg(max_drawdown_pct=0.10))
    w = SimWallet(quote=0.0, positions={"TOKEN": 100.0})
    eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(100.0, 0), w)      # anchor 10_000
    v = eng.evaluate(Intent("TOKEN", Side.SELL, 1.0), tick(50.0, 1), w)   # equity 5_000 < 9_000
    assert not v.allowed and v.reason.startswith("DENY:circuit_breaker") and v.reason.endswith("00")


def test_spend_budget_reason_reports_summed_value_and_window():
    eng = PolicyEngine(cfg(max_notional_per_window=100.0))
    w = SimWallet(10_000)
    eng.evaluate(buy(1.0), tick(100.0, 0), w); eng.register_fill(0, 100.0)
    v = eng.evaluate(buy(1.0), tick(100.0, 1), w)   # spent 100 + 100 = 200
    assert "200.00" in v.reason                     # 'spent - notional' mutant -> 0.00
    assert v.reason.endswith("/10 steps")           # 'XX...stepsXX' mutant -> fails


# -- prune cutoff exactness (kills <=/break mutants) --------------------------
def test_prune_evicts_a_fill_exactly_at_the_window_cutoff():
    # ts == cutoff must be pruned (<=); a '<' mutant keeps it and blocks the trade.
    eng = PolicyEngine(cfg(max_tx_per_window=1, window_steps=10))
    eng.evaluate(buy(1.0), tick(100.0, 0), SimWallet(10_000)); eng.register_fill(0, 100.0)
    # at ts=10 the cutoff is 10-10=0; the ts=0 fill sits exactly on it -> evicted
    assert eng.evaluate(buy(1.0), tick(100.0, 10), SimWallet(10_000)).allowed


def test_prune_breaks_at_first_in_window_fill():
    # the loop must BREAK (not continue) on an in-window fill; a 'continue' mutant
    # spins forever -> returning at all proves the break fired.
    eng = PolicyEngine(cfg(max_tx_per_window=5, window_steps=10))
    w = SimWallet(10_000)
    eng.evaluate(buy(1.0), tick(100.0, 5), w); eng.register_fill(5, 100.0)
    assert eng.evaluate(buy(1.0), tick(100.0, 8), w).allowed   # cutoff -2; ts=5 -> else/break


# -- min-notional epsilon guard is exact (kills 1e-9/2e-9 boundary mutants) ---
def test_min_notional_epsilon_boundary_is_exact():
    floor = 10.0
    # notional == floor-1e-9: strict '<' allows it (a '<=' mutant would deny)
    assert PolicyEngine(cfg(min_notional_per_tx=floor)).evaluate(
        buy(floor - 1e-9), tick(1.0), SimWallet(10_000)).allowed
    # notional == floor-1.5e-9: inside the 1e-9 guard -> denied (a 2e-9 mutant would allow)
    assert not PolicyEngine(cfg(min_notional_per_tx=floor)).evaluate(
        buy(floor - 1.5e-9), tick(1.0), SimWallet(10_000)).allowed


def test_solvency_quote_epsilon_boundary_is_exact():
    # cost == quote+1e-9: strict '>' allows (a '>=' mutant denies); price 1 so cost==base
    eng = PolicyEngine(cfg(max_notional_per_tx=10_000.0, fee_rate=0.0))
    assert eng.evaluate(buy(500.0 + 1e-9), tick(1.0), SimWallet(500.0)).allowed
    # cost == quote+1.5e-9: past the guard -> denied (a 2e-9 mutant would allow)
    assert not eng.evaluate(buy(500.0 + 1.5e-9), tick(1.0), SimWallet(500.0)).allowed


def test_solvency_base_epsilon_boundary_is_exact():
    eng = PolicyEngine(cfg())
    sell = lambda amt: Intent("TOKEN", Side.SELL, amt)
    # base == held+1e-9: strict '>' allows (a '>=' mutant denies)
    assert eng.evaluate(sell(5.0 + 1e-9), tick(1.0), SimWallet(0.0, {"TOKEN": 5.0})).allowed
    # base == held+1.5e-9: past the guard -> denied (a 2e-9 mutant would allow)
    assert not eng.evaluate(sell(5.0 + 1.5e-9), tick(1.0), SimWallet(0.0, {"TOKEN": 5.0})).allowed


def test_spend_budget_epsilon_boundary_is_exact():
    # spent+notional == budget+1e-9 exactly (single prior fill == budget, tiny add),
    # so the strict '>' allows it; a '>=' mutant denies. price 1 => notional == base.
    def eng():
        e = PolicyEngine(cfg(max_notional_per_tx=10_000.0, max_notional_per_window=100.0))
        e.evaluate(buy(1.0), tick(1.0, 0), SimWallet(10_000)); e.register_fill(0, 100.0)
        return e
    assert eng().evaluate(buy(1e-9), tick(1.0, 1), SimWallet(10_000)).allowed
    # spent+notional == budget+1.5e-9: past the guard -> denied (a 2e-9 mutant allows)
    assert not eng().evaluate(buy(1.5e-9), tick(1.0, 1), SimWallet(10_000)).allowed
