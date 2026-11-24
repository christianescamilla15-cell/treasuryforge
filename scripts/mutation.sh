#!/usr/bin/env bash
# Per-component mutation testing with a kill-score gate (default 85%).
# Linux/Docker only (mutmut forks). Each component is mutated against ITS
# OWN test suite — the component-organized layout is what makes this meaningful.
#   docker run --rm treasuryforge:ci bash scripts/mutation.sh
#   bash scripts/mutation.sh --shard 2/6     # CI: the 2nd of 6 round-robin slices
#   bash scripts/mutation.sh metrics drift   # only those components
#   bash scripts/mutation.sh --survivors policy   # + the diff of every mutant that was not killed
#
# mutmut 3 takes no paths on the command line: it reads [tool.mutmut] from pyproject.toml
# and writes the mutated tree to ./mutants. So each component runs on a THROW-AWAY COPY
# (package + tests + pyproject) with its own [tool.mutmut] appended: the working tree is
# never mutated and one component's results can never leak into the next one.
set -uo pipefail
THRESHOLD=${MUTATION_THRESHOLD:-85}
PY=${PY:-python}                 # set PY=/opt/treasuryforge/.venv/bin/python on the VPS
ROOT=$(cd "$(dirname "$0")/.." && pwd)

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

# mutate <src> <tests...>: prints "killed not_killed mutants score" (score -1 = did not run).
# Score = mutmut 3's own formula, (killed + timeout) / (total - skipped): a mutant that
# survived, had no covering test or ended "suspicious" counts AGAINST the component.
mutate() {
  local src="$1"; shift
  local work line
  work=$(mktemp -d)
  cp -r "$ROOT/treasuryforge" "$ROOT/tests" "$ROOT/pyproject.toml" "$work/"
  find "$work" -name __pycache__ -prune -exec rm -rf {} +
  {
    echo
    echo '[tool.mutmut]'
    echo 'source_paths = ["treasuryforge"]'
    echo "only_mutate = [\"$src\"]"
    printf 'pytest_add_cli_args_test_selection = [%s]\n' "$(printf '"%s", ' "$@" | sed 's/, $//')"
  } >> "$work/pyproject.toml"
  if (cd "$work" && "$PY" -m mutmut run > mutmut.log 2>&1 && "$PY" -m mutmut export-cicd-stats > /dev/null 2>&1); then
    line=$("$PY" - "$work/mutants/mutmut-cicd-stats.json" <<'PYEOF'
import json, sys
s = json.load(open(sys.argv[1]))
detected = s["killed"] + s["timeout"]
tested = s["total"] - s["skipped"]
print(detected, tested - detected, tested, 100 * detected // tested if tested else -1)
PYEOF
)
  else
    line="0 0 0 -1"
    echo "  mutmut failed on $src; last lines of its log:" >&2
    tr '\r' '\n' < "$work/mutmut.log" | grep -av '^\s*$' | tail -15 | sed 's/^/    /' >&2
  fi
  if [ "$SURVIVORS" -eq 1 ]; then
    (cd "$work" && for m in $("$PY" -m mutmut results 2>/dev/null | cut -d: -f1); do
       "$PY" -m mutmut show "$m" 2>/dev/null; echo; done) >&2
  fi
  rm -rf "$work"
  echo "$line"
}

# --shard K/N runs every N-th component starting at the K-th (round-robin, so a component
# added to the list is ALWAYS in some shard). Other positional args restrict the run to
# those component names (e.g. `... metrics drift`).
SHARD_K=0; SHARD_N=1; SURVIVORS=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --shard) SHARD_K=${2%%/*}; SHARD_N=${2##*/}; shift 2 ;;
    --survivors) SURVIVORS=1; shift ;;
    *) break ;;
  esac
done
WANT=" $* "
# not `mutmut --version`: mutmut 3 guesses the source dir even for that and crashes outside the repo dir
"$PY" -c 'import importlib.metadata as m; print("mutmut", m.version("mutmut"))'
printf '%-16s %7s %10s %8s %7s\n' COMPONENT KILLED NOT-KILLED MUTANTS SCORE
fail=0; measured=0; idx=0
for entry in "${COMPONENTS[@]}"; do
  idx=$((idx + 1))
  [ "$SHARD_N" -gt 1 ] && [ $(( (idx - 1) % SHARD_N + 1 )) -ne "$SHARD_K" ] && continue
  IFS='|' read -r name src tests <<< "$entry"
  name=$(echo "$name" | xargs); src=$(echo "$src" | xargs); tests=$(echo "$tests" | xargs)
  [ "$#" -gt 0 ] && [[ "$WANT" != *" $name "* ]] && continue
  # shellcheck disable=SC2086  # the test list is word-split on purpose
  read -r killed notkilled total score <<< "$(mutate "$src" $tests)"
  measured=$((measured + 1))
  if [ "$score" -lt 0 ]; then
    # 0 mutants means mutmut did not run (e.g. its baseline test run failed): a gate that
    # measured nothing must not pass.
    printf '%-16s %7s %10s %8s %7s\n' "$name" "-" "-" "-" "NO-RUN"
    fail=1
    continue
  fi
  printf '%-16s %7s %10s %8s %6s%%\n' "$name" "$killed" "$notkilled" "$total" "$score"
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
