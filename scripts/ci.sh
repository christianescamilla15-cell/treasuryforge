#!/usr/bin/env bash
# Full local quality gate — the same checks CI and Docker run. Fails on any red.
set -euo pipefail

echo "==> ruff (lint + import hygiene)"
ruff check treasuryforge tests scripts

echo "==> mypy (static types)"
mypy

echo "==> bandit (security static analysis)"
bandit -r treasuryforge -q -ll

echo "==> pip-audit (our declared dependencies, not the base image's pip)"
pip-audit -r requirements-live.txt -r requirements-dev.txt --progress-spinner off

echo "==> pytest + coverage"
pytest --cov=treasuryforge --cov-report=xml --cov-report=term -q

echo "==> ALL GREEN"
