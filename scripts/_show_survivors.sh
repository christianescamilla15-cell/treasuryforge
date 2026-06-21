#!/usr/bin/env bash
# Dump diffs of all surviving mutants for a source file. Debug helper for the loop.
#   docker run --rm -v "$PWD:/app" -w /app treasuryforge:ci bash scripts/_show_survivors.sh treasuryforge/policy.py "TESTS..."
set -uo pipefail
SRC="$1"; shift
TESTS="$*"
rm -rf .mutmut-cache
mutmut run --paths-to-mutate "$SRC" --runner "python -m pytest -xq $TESTS" >/dev/null 2>&1
for id in $(mutmut result-ids survived 2>/dev/null | tr '\r ' '\n\n'); do
  echo "===== mutant $id ====="
  mutmut show "$id" 2>/dev/null | tr '\r' '\n'
done
