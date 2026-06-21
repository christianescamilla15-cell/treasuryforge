#!/usr/bin/env bash
# Dump surviving mutant diffs for one or more (src, tests) pairs, on an internal
# copy (mount :ro). Args: src1 tests1 src2 tests2 ...
#   docker run --rm -v "$PWD:/app:ro" treasuryforge:ci bash /app/scripts/_dump.sh <src1> "<tests1>" ...
set -uo pipefail
cp -a /app /work
cd /work
while [ "$#" -ge 2 ]; do
  src="$1"; tests="$2"; shift 2
  echo "##### $src #####"
  rm -rf .mutmut-cache
  mutmut run --paths-to-mutate "$src" --runner "python -m pytest -xq $tests" >/dev/null 2>&1
  for id in $(mutmut result-ids survived 2>/dev/null | tr '\r ' '\n\n'); do
    echo "== $id =="
    mutmut show "$id" 2>/dev/null | tr '\r' '\n' | grep -E '^[+-]' | grep -vE '^[+-]{3}'
  done
done
