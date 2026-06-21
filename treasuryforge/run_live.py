"""Systemd entrypoint — the fail-closed launcher.

`python -m treasuryforge.run_live` is what the systemd unit runs. It assembles the
Service from environment config and maps the ServiceExit to a process exit code so
the unit's restart policy can react (SAFE_HALTED / DEAD_MAN never restart-loop;
ERROR restarts safely because startup re-runs preflight and reconciles in-flight
orders).

The live MARKET FEED + EXECUTOR are the one venue-specific piece: they are plugged
in here once a venue is chosen and funded (the agent/API wallet for Hyperliquid, or
the trade-only key for Bitso). Until a venue is wired, the launcher refuses to
operate and returns SAFE_HALTED — which is the correct fail-closed default, not a
bug: a process with no venue must not pretend it can trade.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from .service import ServiceExit

_VENUES = ("bitso", "hyperliquid")


def parse_mode(env: Mapping[str, str]) -> str | None:
    """Return the explicit run mode, or None if it is not exactly paper/live."""
    mode = env.get("TF_MODE")
    return mode if mode in ("paper", "live") else None


def venue_wired(env: Mapping[str, str]) -> bool:
    """Whether a live market feed + executor are configured for this run."""
    return env.get("TF_VENUE", "") in _VENUES


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    mode = parse_mode(env)
    if mode is None:
        sys.stderr.write("run_live: TF_MODE must be 'paper' or 'live' -> SAFE_HALTED\n")
        return int(ServiceExit.SAFE_HALTED)
    if not venue_wired(env):
        # no live feed/executor plugged in yet -> fail closed, never fake-trade
        sys.stderr.write("run_live: no venue wired (set TF_VENUE once funded) -> SAFE_HALTED\n")
        return int(ServiceExit.SAFE_HALTED)

    # --- venue wiring goes here (once a venue is chosen and funded) -----------
    # build_feed/build_executor -> IdempotentOrderManager -> LiveSupervisor ->
    # Service(supervisor, on_halt=cancel_all_and_kill).run(preflight_inputs, feed)
    # then: return int(exit_code)
    sys.stderr.write(f"run_live: venue '{env.get('TF_VENUE')}' not yet implemented -> SAFE_HALTED\n")
    return int(ServiceExit.SAFE_HALTED)


if __name__ == "__main__":  # pragma: no mutate (entrypoint guard; main() is tested directly)
    sys.exit(main())
