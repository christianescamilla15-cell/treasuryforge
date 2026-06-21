#!/usr/bin/env bash
# Run ON the VPS (Debian 13) after copying the treasuryforge folder there.
# Creates an isolated venv, installs deps, and runs the PAPER ladder as a smoke
# test (zero risk). It does NOT touch real funds.
set -euo pipefail

cd "$(dirname "$0")/.."
echo ">> treasuryforge VPS setup in $(pwd)"

python3 -m venv .venv
./.venv/bin/python -m pip install -q --upgrade pip
./.venv/bin/python -m pip install -q -r requirements-dev.txt -r requirements-live.txt

echo ">> running the test suite"
./.venv/bin/python -m pytest -q

echo ">> paper validation ladder (emulator, no funds)"
./.venv/bin/python scripts/validate_live.py --mode paper --arm

echo ">> confirming this host's egress IP (must match the Bitso API key allowlist)"
curl -s ifconfig.me || true
echo

cat <<'NOTE'

>> NEXT (manual, by you):
   1. Put the trade-only key in /etc/treasuryforge/bitso.env (chmod 600), from
      deploy/bitso.env.example. Do NOT paste it anywhere else.
   2. Confirm the egress IP printed above == the IP you allowlisted on the key.
   3. Live READ-ONLY validation (safe, no orders):
        set -a; source /etc/treasuryforge/bitso.env; set +a
        ./.venv/bin/python scripts/validate_live.py --mode live
   4. Only if rungs 1-4 are all green, the tiny ~20 MXN order (rungs 5-6):
        ./.venv/bin/python scripts/validate_live.py --mode live --arm --max-mxn 20
NOTE
