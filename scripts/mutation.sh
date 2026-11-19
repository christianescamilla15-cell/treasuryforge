#!/usr/bin/env bash
# Per-component mutation testing with a kill-score gate (default 85%).
# Linux/Docker only (mutmut needs Linux). Each component is mutated against ITS
# OWN test suite — the component-organized layout is what makes this meaningful.
#   docker run --rm treasuryforge:ci bash scripts/mutation.sh
#   bash scripts/mutation.sh --shard 2/6     # CI: the 2nd of 6 round-robin slices
#   bash scripts/mutation.sh metrics drift   # only those components
set -uo pipefail
THRESHOLD=${MUTATION_THRESHOLD:-85}
PY=${PY:-python}                 # set PY=/opt/treasuryforge/.venv/bin/python on the VPS

# "name | source file | its test path(s)"
COMPONENTS=(
  "sizing    | treasuryforge/sizing.py            | tests/backtest/test_sizing_backtest.py"
  "metrics   | treasuryforge/backtest/metrics.py  | tests/backtest/test_metrics_mutation.py"
  "stages    | treasuryforge/risk/stages.py       | tests/risk/test_stages.py tests/risk/test_stages_mutation.py"
  "drift     | treasuryforge/risk/drift.py        | tests/risk/test_drift.py tests/risk/test_drift_mutation.py"
  "graveyard | treasuryforge/risk/graveyard.py    | tests/risk/test_graveyard.py tests/risk/test_graveyard_mutation.py"
  "live_gap  | treasuryforge/risk/live_gap.py     | tests/risk/test_live_gap.py tests/risk/test_live_gap_mutation.py"
  "policy    | treasuryforge/policy.py            | tests/core/test_policy.py tests/core/test_policy_phase2.py tests/core/test_policy_stateful.py tests/core/test_policy_mutation.py"
  "ruin      | treasuryforge/risk/ruin.py         | tests/risk/test_risk_of_ruin.py tests/risk/test_ruin_mutation.py"
  "orders    | treasuryforge/orders.py            | tests/core/test_orders_idempotency.py"
  "watchdog  | treasuryforge/watchdog.py          | tests/core/test_watchdog.py"
  "preflight | treasuryforge/preflight.py          | tests/core/test_preflight.py"
  "staleness | treasuryforge/staleness.py          | tests/core/test_staleness.py"
  "live      | treasuryforge/live.py              | tests/core/test_live.py"
  "service   | treasuryforge/service.py           | tests/core/test_service.py"
  "run_live  | treasuryforge/run_live.py          | tests/core/test_run_live.py"
  "shadow    | treasuryforge/shadow.py            | tests/core/test_shadow.py"
  "shadow_basis | treasuryforge/shadow_basis.py   | tests/core/test_shadow_basis.py"
  "pnl_decomp | treasuryforge/pnl_decomposition.py | tests/core/test_pnl_decomposition.py"
  "fill_model | treasuryforge/fill_model.py       | tests/core/test_fill_model.py"
  "carry_screener | treasuryforge/carry_screener.py | tests/core/test_carry_screener.py"
  "universe  | treasuryforge/universe.py          | tests/core/test_universe.py"
  "funding_persist | treasuryforge/funding_persistence.py | tests/core/test_funding_persistence.py"
  "funding_predict | treasuryforge/funding_predictor.py   | tests/core/test_funding_predictor.py"
  "carry_backtest | treasuryforge/carry_backtest.py | tests/core/test_carry_backtest.py"
  "cross_venue | treasuryforge/cross_venue.py      | tests/core/test_cross_venue.py"
  "regime    | treasuryforge/signals/regime.py    | tests/signals/test_regime.py"
  "basis     | treasuryforge/signals/basis.py     | tests/signals/test_basis.py"
  "mr_scalp  | treasuryforge/signals/mr_scalp.py  | tests/signals/test_mr_scalp.py"
  "cross_venue_econ | treasuryforge/cross_venue_economics.py | tests/core/test_cross_venue_economics.py"
  "duty_cycle | treasuryforge/opportunity_duty_cycle.py | tests/core/test_opportunity_duty_cycle.py"
  "economic_gate | treasuryforge/economic_gate.py | tests/core/test_economic_gate.py"
  "cross_legger | treasuryforge/cross_venue_legger.py | tests/core/test_cross_venue_legger.py"
  "allocator | treasuryforge/carry_portfolio_allocator.py | tests/core/test_carry_portfolio_allocator.py"
  "venue_spread | treasuryforge/venue_spread.py | tests/core/test_venue_spread.py"
  "maturity  | treasuryforge/maturity.py        | tests/core/test_capital_protocol.py"
  "promotion | treasuryforge/promotion_gate.py  | tests/core/test_capital_protocol.py"
  "loss_limits | treasuryforge/loss_limits.py   | tests/core/test_capital_protocol.py"
  "selection | treasuryforge/selection_score.py | tests/core/test_selection_score.py"
  "momentum  | treasuryforge/signals/momentum.py | tests/core/test_momentum_backtest.py"
  "momentum_bt | treasuryforge/momentum_backtest.py | tests/core/test_momentum_backtest.py"
  "tsmom     | treasuryforge/signals/tsmom.py   | tests/core/test_tsmom_backtest.py"
  "tsmom_bt  | treasuryforge/tsmom_backtest.py  | tests/core/test_tsmom_backtest.py"
)

# --shard K/N runs every N-th component starting at the K-th (round-robin, so a component
# added to the list is ALWAYS in some shard). Other positional args restrict the run to
# those component names (e.g. `... metrics drift`).
SHARD_K=0; SHARD_N=1
if [ "${1:-}" = "--shard" ]; then
  SHARD_K=${2%%/*}; SHARD_N=${2##*/}; shift 2
fi
WANT=" $* "
printf '%-11s %7s %9s %7s\n' COMPONENT KILLED SURVIVED SCORE
fail=0; measured=0; idx=0
for entry in "${COMPONENTS[@]}"; do
  idx=$((idx + 1))
  [ "$SHARD_N" -gt 1 ] && [ $(( (idx - 1) % SHARD_N + 1 )) -ne "$SHARD_K" ] && continue
  IFS='|' read -r name src tests <<< "$entry"
  name=$(echo "$name" | xargs); src=$(echo "$src" | xargs); tests=$(echo "$tests" | xargs)
  [ "$#" -gt 0 ] && [[ "$WANT" != *" $name "* ]] && continue
  rm -rf .mutmut-cache
  # locale-robust parse: the final progress line is "N/M K t s S k" (killed=3rd, survived=6th int)
  nums=$("$PY" -m mutmut run --paths-to-mutate "$src" --runner "$PY -m pytest -xq $tests" 2>&1 \
         | tr '\r' '\n' | grep -aE '[0-9]+/[0-9]+ ' | tail -1 | grep -oE '[0-9]+' | tr '\n' ' ')
  killed=$(echo "$nums" | awk '{print $3}'); killed=${killed:-0}
  surv=$(echo "$nums"   | awk '{print $6}'); surv=${surv:-0}
  total=$((killed + surv))
  measured=$((measured + 1))
  if [ "$total" -eq 0 ]; then
    # 0 mutants means mutmut did not run (e.g. its baseline test run failed): a gate that
    # measured nothing must not pass.
    printf '%-11s %7s %9s %7s\n' "$name" "-" "-" "NO-RUN"
    fail=1
    continue
  fi
  score=$((100 * killed / total))
  printf '%-11s %7s %9s %6s%%\n' "$name" "$killed" "$surv" "$score"
  [ "$score" -lt "$THRESHOLD" ] && fail=1
done

if [ "$measured" -eq 0 ]; then
  echo "MUTATION GATE FAILED: no component selected (shard ${SHARD_K}/${SHARD_N}, filter:${WANT})"
  exit 1
fi

echo "-----------------------------------------------"
if [ "$fail" -eq 0 ]; then
  echo "MUTATION GATE PASSED (every component >= ${THRESHOLD}%)"
else
  echo "MUTATION GATE FAILED (a component < ${THRESHOLD}%) — strengthen its tests"
  exit 1
fi
