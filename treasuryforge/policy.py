"""Policy engine — the 'guardrail'. This is the most important module.

The agent (the brain / LLM) can hallucinate, be prompt-injected via market data,
or simply be wrong. The policy engine is the layer of HARD, non-negotiable rules
that sits between a proposed intent and any execution. It does not trust the
agent. In the real system these same rules are enforced by the wallet's session
caps / smart-contract policy — here we enforce them in code so we can validate
the logic with zero risk.

Rules enforced, in order:
  1. kill switch          — global stop, denies everything.
  2. circuit breaker      — if equity drops past max_drawdown, trip and stay tripped.
  3. staleness gate       — deny if the market data is older than the budget
                            (fail-closed; inert in the deterministic sim).
  4. symbol allowlist     — only approved assets.
  5. per-tx notional cap  — no single trade larger than max_notional_per_tx.
  6. rate limit           — at most max_tx_per_window trades per rolling window.
  7. spend budget         — at most max_notional_per_window of value per window
                            (closes the drip-drain gap a count-only limit leaves).
  8. solvency             — never propose what the wallet cannot afford.

Phase-2 hardening: PolicyConfig is frozen (the agent cannot mutate its own
limits); latched state (breaker, windows) is snapshot/restore-able so a crash
cannot silently un-trip the breaker (see journal.py).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .types import Intent, MarketTick, Side, Verdict
from .wallet import SimWallet


@dataclass(frozen=True)
class PolicyConfig:
    allowed_symbols: frozenset[str]
    max_notional_per_tx: float          # quote value cap on a single trade
    max_tx_per_window: int              # rate limit: trade COUNT per window
    window_steps: int                   # rolling window length (in ticks)
    max_drawdown_pct: float             # e.g. 0.10 -> trip if equity falls 10%
    fee_rate: float = 0.0               # used for the solvency check buffer
    kill_switch: bool = False
    min_notional_per_tx: float | None = None   # exchange minimum_value floor (live)
    # cumulative spend budget (value, not count). None disables the rule.
    max_notional_per_window: float | None = None
    spend_window_steps: int | None = None   # defaults to window_steps if None
    # staleness budget in nanoseconds. None (or no data_age supplied) = inert.
    max_staleness_ns: int | None = None

    @property
    def _spend_window(self) -> int:
        return self.spend_window_steps if self.spend_window_steps is not None else self.window_steps


@dataclass
class PolicyEngine:
    config: PolicyConfig
    _starting_equity: float | None = None
    _tripped: bool = False
    _recent_ts: deque[int] = field(default_factory=deque)
    _spend: deque[tuple[int, float]] = field(default_factory=deque)

    @property
    def tripped(self) -> bool:
        return self._tripped

    def evaluate(  # noqa: C901 - one flat, auditable sequence of 8 guard rules; splitting hurts review
        self,
        intent: Intent,
        tick: MarketTick,
        wallet: SimWallet,
        data_age_ns: int | None = None,
    ) -> Verdict:
        cfg = self.config
        prices = {tick.symbol: tick.price}

        if self._starting_equity is None:
            self._starting_equity = wallet.equity(prices)

        # 1. kill switch ----------------------------------------------------
        if cfg.kill_switch:
            return Verdict(False, "DENY:kill_switch active")

        # 2. circuit breaker ------------------------------------------------
        equity = wallet.equity(prices)
        floor = self._starting_equity * (1.0 - cfg.max_drawdown_pct)
        if self._tripped or equity < floor:
            self._tripped = True
            return Verdict(
                False,
                f"DENY:circuit_breaker equity={equity:.2f} < floor={floor:.2f}",
            )

        # 3. staleness gate (fail-closed; inert unless BOTH the budget and a
        #    real data age are supplied — the deterministic sim supplies neither)
        if cfg.max_staleness_ns is not None and data_age_ns is not None:
            if data_age_ns > cfg.max_staleness_ns:
                return Verdict(
                    False,
                    f"DENY:stale_data age={data_age_ns}ns > {cfg.max_staleness_ns}ns",
                )

        # 4. symbol allowlist ----------------------------------------------
        if intent.symbol not in cfg.allowed_symbols:
            return Verdict(False, f"DENY:symbol '{intent.symbol}' not in allowlist")

        # 5. per-tx notional cap (and exchange min-notional floor) ---------
        notional = intent.notional(tick.price)
        if notional > cfg.max_notional_per_tx:
            return Verdict(
                False,
                f"DENY:notional {notional:.2f} > cap {cfg.max_notional_per_tx:.2f}",
            )
        if cfg.min_notional_per_tx is not None and notional < cfg.min_notional_per_tx - 1e-9:
            return Verdict(
                False,
                f"DENY:min_notional {notional:.2f} < floor {cfg.min_notional_per_tx:.2f}",
            )

        # 6. rate limit (trade count) --------------------------------------
        self._prune(self._recent_ts, tick.ts, cfg.window_steps)
        if len(self._recent_ts) >= cfg.max_tx_per_window:
            return Verdict(
                False,
                f"DENY:rate_limit {cfg.max_tx_per_window}/{cfg.window_steps} steps",
            )

        # 7. spend budget (cumulative value) -------------------------------
        if cfg.max_notional_per_window is not None:
            self._prune(self._spend, tick.ts, cfg._spend_window)
            spent = sum(n for _, n in self._spend)
            if spent + notional > cfg.max_notional_per_window + 1e-9:
                return Verdict(
                    False,
                    f"DENY:spend_budget {spent + notional:.2f} > "
                    f"{cfg.max_notional_per_window:.2f}/{cfg._spend_window} steps",
                )

        # 8. solvency -------------------------------------------------------
        if intent.side is Side.BUY:
            cost = notional * (1.0 + cfg.fee_rate)
            if cost > wallet.quote + 1e-9:
                return Verdict(
                    False, f"DENY:insufficient_quote need={cost:.2f} have={wallet.quote:.2f}"
                )
        else:  # SELL
            held = wallet.base_balance(intent.symbol)
            if intent.base_amount > held + 1e-9:
                return Verdict(
                    False, f"DENY:insufficient_base need={intent.base_amount:.6f} have={held:.6f}"
                )

        return Verdict(True, "ALLOW")

    def register_fill(self, ts: int, notional: float = 0.0) -> None:
        """Record an EXECUTED trade so the rate limiter and spend budget count it.

        Debited on fills only (never at evaluate-time) so denied/aborted intents
        never consume budget.
        """
        self._recent_ts.append(ts)
        self._spend.append((ts, notional))

    # -- crash-safe latched state -----------------------------------------
    def snapshot(self) -> dict:
        """Serializable latched state — persist this so a restart cannot reset
        the breaker or re-anchor the drawdown floor to a post-loss equity."""
        return {
            "starting_equity": self._starting_equity,
            "tripped": self._tripped,
            "recent_ts": list(self._recent_ts),
            "spend": [[ts, n] for ts, n in self._spend],
        }

    def restore(self, state: dict) -> None:
        self._starting_equity = state.get("starting_equity")
        self._tripped = bool(state.get("tripped", False))
        self._recent_ts = deque(int(t) for t in state.get("recent_ts", []))
        self._spend = deque((int(ts), float(n)) for ts, n in state.get("spend", []))

    @staticmethod
    def _prune(dq: deque, now_ts: int, window: int) -> None:
        cutoff = now_ts - window
        while dq:
            ts = dq[0][0] if isinstance(dq[0], tuple) else dq[0]
            if ts <= cutoff:
                dq.popleft()
            else:
                break
