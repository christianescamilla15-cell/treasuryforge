"""Startup preflight — fail-closed. The bot does NOT get to operate on a best
effort. Before any order flow, every precondition must hold; if a single one
fails the startup state is SAFE_HALTED and the process refuses to trade.

Preconditions (the operator's checklist, in code):
  1.  mode is explicit            paper | live (never an implicit default)
  2.  config loaded               a PolicyConfig is present
  3.  journal writable            durable state has somewhere to go
  4.  credentials present         the wallet/key is resolvable (the secret itself
                                  is NEVER passed here — only "is it present")
  5.  allowlist active            at least one approved symbol
  6.  caps loaded                 per-tx notional cap > 0 (and spend cap if live)
  7.  kill-switch clear           config kill-switch not latched on
  8.  clock sane                  wall-clock is a real, post-2020 time
  9.  clock skew bounded          |local - exchange| within budget (live only)
  10. data feed fresh             latest market data age within budget
  11. exchange reachable          a cheap reachability probe passed (live only)

Network/clock facts are passed in as PROBE RESULTS (the caller runs the probes),
so this module stays pure and fully unit-testable; the checks themselves are real.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class StartupState(str, Enum):
    READY = "READY"
    SAFE_HALTED = "SAFE_HALTED"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class PreflightInputs:
    mode: str | None                       # "paper" | "live"
    config: object | None                  # PolicyConfig (duck-typed below)
    journal_dir: str | None
    has_credentials: bool
    now_wall: float                        # time.time() at startup
    exchange_reachable: bool = True        # probe result (only enforced when live)
    data_age_s: float | None = None        # age of the freshest market data
    max_data_age_s: float = 5.0
    clock_skew_s: float | None = None      # |local - exchange_time| (probe result)
    max_clock_skew_s: float = 2.0
    min_sane_epoch: float = 1_600_000_000.0   # ~2020-09-13; reject an unset/insane clock


@dataclass
class PreflightReport:
    state: StartupState
    checks: list[Check] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.state is StartupState.READY

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def render(self) -> str:
        lines = [f"STARTUP: {self.state.value}"]
        for c in self.checks:
            lines.append(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
        if not self.ready:
            lines.append(f"  -> refusing to operate ({len(self.failures())} precondition(s) failed)")
        return "\n".join(lines)


def _journal_writable(path: str | None) -> Check:
    if not path:
        return Check("journal_writable", False, "no journal directory configured")
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".preflight")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return Check("journal_writable", True, f"writable: {path}")
    except OSError as e:
        return Check("journal_writable", False, f"not writable: {e}")


def run_preflight(inp: PreflightInputs) -> PreflightReport:
    live = inp.mode == "live"
    cfg = inp.config
    checks: list[Check] = []

    checks.append(Check("mode_explicit", inp.mode in ("paper", "live"),
                        f"mode={inp.mode!r} (must be 'paper' or 'live')"))
    checks.append(Check("config_loaded", cfg is not None, "PolicyConfig present" if cfg else "no config"))
    checks.append(_journal_writable(inp.journal_dir))
    checks.append(Check("credentials_present", inp.has_credentials,
                        "wallet/key resolvable" if inp.has_credentials else "no credentials"))

    # config-derived gates (only meaningful once a config is loaded)
    allowed: frozenset[str] = getattr(cfg, "allowed_symbols", frozenset()) or frozenset()
    checks.append(Check("allowlist_active", len(allowed) > 0, f"{len(allowed)} symbol(s) allowed"))
    cap = float(getattr(cfg, "max_notional_per_tx", 0.0) or 0.0)
    spend_cap = getattr(cfg, "max_notional_per_window", None)
    caps_ok = cap > 0 and (not live or spend_cap is not None)
    checks.append(Check("caps_loaded", caps_ok,
                        f"per-tx cap={cap}, spend cap={spend_cap}"))
    ks = bool(getattr(cfg, "kill_switch", False))
    checks.append(Check("kill_switch_clear", not ks, "latched ON" if ks else "clear"))

    # clock / data freshness
    checks.append(Check("clock_sane", inp.now_wall >= inp.min_sane_epoch,
                        f"wall={inp.now_wall:.0f}"))
    fresh = inp.data_age_s is not None and inp.data_age_s <= inp.max_data_age_s
    checks.append(Check("data_feed_fresh", fresh,
                        f"age={inp.data_age_s}s vs budget {inp.max_data_age_s}s"))

    # live-only external gates
    if live:
        skew_ok = inp.clock_skew_s is not None and abs(inp.clock_skew_s) <= inp.max_clock_skew_s
        checks.append(Check("clock_skew_bounded", skew_ok,
                            f"skew={inp.clock_skew_s}s vs budget {inp.max_clock_skew_s}s"))
        checks.append(Check("exchange_reachable", inp.exchange_reachable,
                            "reachable" if inp.exchange_reachable else "unreachable"))

    state = StartupState.READY if all(c.ok for c in checks) else StartupState.SAFE_HALTED
    return PreflightReport(state, checks)
