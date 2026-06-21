#!/usr/bin/env bash
# Run a single-component mutation pass on an INTERNAL COPY of the repo, so the
# mounted source tree (mount it :ro) is never mutated and the host stays unblocked.
#   docker run --rm -v "$PWD:/app:ro" treasuryforge:ci bash /app/scripts/_mut_copy.sh <src> "<tests>"
set -uo pipefail
SRC="$1"; shift
TESTS="$*"
cp -a /app /work
cd /work
rm -rf .mutmut-cache
mutmut run --paths-to-mutate "$SRC" --runner "python -m pytest -xq $TESTS" 2>&1 \
  | tr '\r' '\n' | grep -E '🎉|🙁' | tail -1
# also dump surviving mutant ids+diffs for iteration
echo "---SURVIVORS---"
for id in $(mutmut result-ids survived 2>/dev/null | tr '\r ' '\n\n'); do
  echo "== $id =="
  mutmut show "$id" 2>/dev/null | tr '\r' '\n' | grep -E '^[+-]' | grep -vE '^[+-]{3}'
done
