#!/usr/bin/env bash
# The 5 scan processes as one strict gate, each reported PASS/FAIL with a final
# summary table (non-zero exit if any fail). Pass `mutation` to also run the
# per-component mutation kill-score gate as a 6th process (slow; Linux/Docker).
#
#   bash scripts/scan.sh              # the 5 static scans
#   bash scripts/scan.sh mutation     # + mutmut kill-score gate (>=85%/component)
set -uo pipefail

NAMES=()
RESULTS=()
run() {
  local name="$1"; shift
  echo ""
  echo "===================================================================="
  echo "==> $name"
  echo "===================================================================="
  if "$@"; then NAMES+=("$name"); RESULTS+=("PASS"); else NAMES+=("$name"); RESULTS+=("FAIL"); fi
}

run "1. ruff       (lint + complexity)" ruff check treasuryforge tests scripts
run "2. mypy       (static types)"      mypy
run "3. bandit     (security SAST)"     bandit -r treasuryforge -q -ll
run "4. pip-audit  (dependency CVEs)"   pip-audit -r requirements-live.txt -r requirements-dev.txt --progress-spinner off
run "5. pytest-cov (tests + cov>=90%)"  pytest --cov=treasuryforge --cov-report=term-missing -q

if [ "${1:-}" = "mutation" ]; then
  run "6. mutmut     (mutation>=85%)"   bash scripts/mutation.sh
fi

echo ""
echo "===================== SCAN SUMMARY ====================="
fail=0
for i in "${!NAMES[@]}"; do
  printf '  %-34s %s\n' "${NAMES[$i]}" "${RESULTS[$i]}"
  [ "${RESULTS[$i]}" = "FAIL" ] && fail=1
done
echo "========================================================"
if [ "$fail" -eq 0 ]; then
  echo ">> ALL SCANS GREEN"
else
  echo ">> SCAN FAILED — see the failing process above"
  exit 1
fi
