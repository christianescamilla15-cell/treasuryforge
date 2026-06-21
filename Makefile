.PHONY: install lint type security test cov mutation scan ci-strict ci sonar docker-validate clean

install:
	python -m pip install -r requirements-dev.txt -r requirements-live.txt
	python -m pip install -e .

lint:
	ruff check treasuryforge tests scripts

type:
	mypy

security:
	bandit -r treasuryforge -q -ll
	pip-audit -r requirements-live.txt -r requirements-dev.txt --progress-spinner off

test:
	pytest -q

cov:
	pytest --cov=treasuryforge --cov-report=xml --cov-report=term-missing -q

# mutation testing (the "Stryker" of Python): proves the tests actually catch
# bugs. Per-component kill-score gate (>=85%). Linux/Docker only.
mutation:
	bash scripts/mutation.sh

# local-stack sandbox: full system end-to-end against the emulators, in ms
sandbox:
	pytest tests/integration -q
	python scripts/sandbox.py

# build the local market 'BD' from REAL Hyperliquid data (candles/funding/L2 depth)
marketdb:
	python scripts/build_market_db.py --coins BTC,ETH,SOL --days 120

# stress campaign: drive the full stack through synthetic crash/storm paths
stress:
	pytest tests/stress -q
	python scripts/stress.py --paths 300

# the 5 scan processes as one strict gate with a PASS/FAIL summary
scan:
	bash scripts/scan.sh

# the 5 scans + the mutation kill-score gate (the full strict pipeline)
ci-strict:
	bash scripts/scan.sh mutation

# the full local gate (what CI and Docker run)
ci: lint type security cov
	@echo "==> CI GREEN"

# bring up SonarQube and scan (needs docker + sonar-scanner on PATH)
sonar:
	docker compose up -d sonarqube
	@echo "SonarQube starting at http://localhost:9000 (admin/admin). Then: sonar-scanner"

docker-validate:
	docker build -t treasuryforge:ci .
	docker run --rm treasuryforge:ci

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml .coverage
