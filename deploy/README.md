# Deploying treasuryforge to the VPS (Netcup 152.53.167.28)

The Bitso API key is IP-allowlisted to the VPS, so **all live API calls must run
from the VPS**, not your PC. This is the staged plan to get there safely.

## Why the VPS
- Static egress IP for the key's IP allowlist (your residential MX IP drifts).
- The 24/7 agent will live here anyway.

## 1. Copy the code (from your PC)

From the project folder, with `scp` (Git Bash) — exclude the local venv:

```bash
tar --exclude=.venv --exclude=.pytest_cache --exclude='*.pyc' -czf /tmp/tf.tgz -C "$(pwd)/.." treasuryforge
scp /tmp/tf.tgz root@152.53.167.28:/opt/
ssh root@152.53.167.28 'cd /opt && tar xzf tf.tgz && rm tf.tgz'
```
(Replace `root` with your actual VPS user.)

## 2. Set up on the VPS

```bash
ssh root@152.53.167.28
cd /opt/treasuryforge
bash deploy/setup_on_vps.sh
```
This builds the venv, runs the test suite, runs the **paper** ladder (no funds),
and prints the VPS egress IP. Confirm that IP matches the one you allowlisted on
the Bitso key.

## 3. Provision the secret (on the VPS, never in the repo)

```bash
mkdir -p /etc/treasuryforge
cp deploy/bitso.env.example /etc/treasuryforge/bitso.env
chmod 600 /etc/treasuryforge/bitso.env
nano /etc/treasuryforge/bitso.env   # paste the trade-only key + secret
```

## 4. Live validation ladder (gated)

```bash
set -a; source /etc/treasuryforge/bitso.env; set +a

# READ-ONLY first (rungs 1-4: books, signed balance, no-withdraw proof, fees):
./.venv/bin/python scripts/validate_live.py --mode live

# ONLY if all green -> the tiny ~20 MXN order (rungs 5-6):
./.venv/bin/python scripts/validate_live.py --mode live --arm --max-mxn 20
```

Rung 3 proves the key cannot withdraw (expects Bitso code `0202`). If it reports
the key can withdraw, the ladder ABORTS — fix the key scope before anything else.

## 5. The 24/7 fail-closed service (systemd)

The execution-safety layer is built and mutation-tested: idempotent orders
(at-most-once + reconcile-before-retry), a client-side dead-man's switch, a
fail-closed startup preflight, and a runtime staleness/clock-sanity gate, all wired
by `LiveSupervisor` and run by the fail-closed `Service` (`python -m
treasuryforge.run_live`).

```bash
# user + state dir (least privilege)
useradd -r -s /usr/sbin/nologin treasuryforge || true
mkdir -p /opt/treasuryforge/state && chown -R treasuryforge:treasuryforge /opt/treasuryforge/state

# config + secrets (root-owned, 0600)
cp deploy/bitso.env.example /etc/treasuryforge/treasuryforge.env
printf 'TF_MODE=paper\n' >> /etc/treasuryforge/treasuryforge.env   # paper until a venue is funded
chmod 600 /etc/treasuryforge/treasuryforge.env

# install + start
cp deploy/treasuryforge.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now treasuryforge
systemctl status treasuryforge
journalctl -u treasuryforge -f
```

**Fail-closed by design** — the unit's restart policy keys off the launcher's exit
code (`treasuryforge.service.ServiceExit`):

| exit | meaning | restart? |
|------|---------|----------|
| 10 `SAFE_HALTED` | a preflight precondition failed | **no** — a human fixes the env |
| 20 `DEAD_MAN` | the dead-man's switch fired | **no** — a human inspects |
| 30 `ERROR` | unexpected fault | **yes** — startup re-runs preflight + reconciles in-flight orders first |

Until a venue feed/executor is wired (`TF_VENUE=bitso|hyperliquid`, set once the
trade-only key / agent wallet is funded), `run_live` returns `SAFE_HALTED` on
purpose: a process with no venue must not pretend it can trade.

## 6. The funding-carry shadow (paper, NO funds — start this now)

This collects a LIVE track record for the funding-carry edge with **no money, no
keys, no venue** (Hyperliquid's `/info` is public). Run it on the VPS so the hourly
sampling is gap-free; it can start immediately, independent of any deposit.

```bash
mkdir -p /opt/treasuryforge/state && chown -R treasuryforge:treasuryforge /opt/treasuryforge/state
cp deploy/treasuryforge-shadow.service deploy/treasuryforge-shadow.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now treasuryforge-shadow.timer   # fires hourly

# watch it
systemctl list-timers treasuryforge-shadow.timer
journalctl -u treasuryforge-shadow -f                # see each hourly observation + the report
./.venv/bin/python scripts/run_shadow.py --coin ETH --state-dir state/shadow_eth   # run once by hand
```

Each run appends one funding observation to `state/shadow_eth` (persisted, survives
reboots). Once ≥30 intervals accrue it prints the **live Sharpe + Deflated Sharpe**;
watch over days/weeks whether the DSR converges toward the ≥0.60 gate (a real edge)
or stays below (noise). Either outcome is learned for free.
