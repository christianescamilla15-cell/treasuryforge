"""Fully autonomous scalp trader -- runs the momentum-ignition signal live, gates on the
proven DSR, and (when ARMED) executes real micro orders ITSELF through the rail. No human
in the loop: the deployed service DECIDES and EXECUTES; every order is disposed by THREE
guards before it reaches the rail -- the deployment gate (is this edge deploy-worthy?), the
unanimous 6-consultant committee, AND the policy engine's 8 hard rules (kill-switch,
circuit-breaker, allowlist, per-tx notional cap, rate-limit, spend-budget, solvency). The
brain proposes; the policy disposes; only then does the wallet execute. Default is PAPER
(--arm off); with --arm it trades real money the moment a coin clears ALL three.

Two honest constraints of the system itself (not a nanny -- mechanics):
  1. The deployment gate still governs WHAT deploys (DSR>=0.60 over >=30 trades / >=14d).
     Arming trusts the gate as the sole guard; it does NOT deploy anything unproven.
  2. HL min order is $10 and the micro tier is 1% of collateral -> real auto-deploy needs
     collateral >= ~$1000 (1% = $10). At ~$20 a $10 order would be >10% of the account, so
     the engine REFUSES to fire and stays paper, logging why. The autonomy is armed; the
     bankroll is then the only thing gating a live trade.

    python scripts/run_autonomous.py --top 15 --interval 60           # paper
    set -a; source /etc/treasuryforge/hl.env; set +a
    python scripts/run_autonomous.py --top 15 --interval 60 --arm      # autonomous LIVE
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.deployment_gate import DeploymentGate
from treasuryforge.journal import Journal
from treasuryforge.policy import PolicyConfig, PolicyEngine
from treasuryforge.scalp_shadow import ScalpBook
from treasuryforge.types import Intent, MarketTick, Side
from treasuryforge.wallet import SimWallet

_GATE = DeploymentGate()
_HL_MIN = 10.0               # HL minimum order notional (USD)


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def _liquid(top: int, min_vol: float) -> list[str]:
    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    pool = sorted(((float(c.get("dayNtlVlm", 0) or 0), a["name"])
                   for a, c in zip(meta["universe"], ctxs)), reverse=True)
    return [n for v, n in pool if v >= min_vol][:top]


def _last_closed_1m(coin: str, now_ms: int):
    cs = _post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m",
               "startTime": now_ms - 4 * 60_000, "endTime": now_ms}})
    closed = [k for k in cs if int(k["T"]) <= now_ms]
    if not closed:
        return None
    k = closed[-1]
    return int(k["t"]), float(k["h"]), float(k["l"]), float(k["c"])


def _scalp_returns(journal: Journal) -> list[float]:
    return [float(e["r"]) for e in journal.read_ledger() if e.get("kind") == "scalp"]


def _interval_sharpe(rs: list[float]) -> float | None:
    """Per-interval (non-annualized) Sharpe = mean/std, same convention as the DSR's _moments.
    None when undefined (too few trades or zero variance)."""
    n = len(rs)
    if n < 2:
        return None
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / n
    return mean / math.sqrt(var) if var > 0 else None


def _trial_sharpes(journals: dict[str, Journal]) -> list[float]:
    """The per-coin Sharpe of EVERY coin in the scan -- the multiple-testing burden the DSR
    must deflate by. A wider universe raises the bar instead of lowering it."""
    return [s for j in journals.values() if (s := _interval_sharpe(_scalp_returns(j))) is not None]


def _gate_open(journal: Journal, trial_sharpes: list[float] | None = None) -> bool:
    evs = [e for e in journal.read_ledger() if e.get("kind") == "scalp"]
    rs = [float(e["r"]) for e in evs]
    ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]

    # 1. Base deployment gate, DSR deflated by the whole scanned universe (multiple testing)
    verdict = _GATE.evaluate(rs, ts, trial_sharpes=trial_sharpes)
    if not verdict.deploy:
        return False

    # 2. Committee verification (unanimous 6-consultant check)
    from treasuryforge.consultants import Committee
    comm_verdict = Committee().review(rs, ts)
    if not comm_verdict.approved:
        print(f"Committee vetoed: {comm_verdict.render()}", flush=True)
        return False

    return True


def _build_policy(info, master: str, coins: list[str], args) -> tuple[PolicyEngine, Journal]:
    """Construct the live policy engine (8 hard rules) and restore its latched state.

    Caps are anchored to the STARTING collateral so the agent can never widen its own limits;
    the breaker + rate/spend windows are persisted to a journal so a restart cannot silently
    un-trip the breaker or reset the windows (crash-safe latched state)."""
    col0 = info.available_collateral(master)
    cfg = PolicyConfig(
        allowed_symbols=frozenset(coins),
        max_notional_per_tx=args.max_notional_pct * col0,
        max_tx_per_window=args.max_tx,
        window_steps=args.policy_window,
        max_drawdown_pct=args.max_dd,
        min_notional_per_tx=_HL_MIN,
        max_notional_per_window=args.max_spend_pct * col0,
        spend_window_steps=args.policy_window,
        fee_rate=0.001,
    )
    policy = PolicyEngine(cfg)
    pj = Journal("state/policy_live")
    snaps = [e for e in pj.read_ledger() if e.get("kind") == "policy_state"]
    if snaps:
        policy.restore(snaps[-1]["state"])
    print(f"POLICY armed: per-tx cap ${cfg.max_notional_per_tx:.2f} "
          f"({args.max_notional_pct:.0%} of ${col0:.2f}), breaker {args.max_dd:.0%} DD, "
          f"{args.max_tx} tx / {args.policy_window}s, min ${_HL_MIN:.0f}.", flush=True)
    return policy, pj


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-vol", type=float, default=5_000_000)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--state-prefix", default="state/scalp")
    ap.add_argument("--arm", action="store_true", help="execute REAL orders on gated signals")
    ap.add_argument("--tier", type=float, default=0.01, help="capital allocation fraction (e.g., 0.01 for 1%)")
    # --- policy engine (8 hard rules) knobs, as fractions of starting collateral ---
    ap.add_argument("--max-notional-pct", type=float, default=0.20,
                    help="per-tx notional cap as fraction of starting collateral (policy rule 5)")
    ap.add_argument("--max-spend-pct", type=float, default=0.50,
                    help="cumulative spend budget per window, fraction of starting collateral (rule 7)")
    ap.add_argument("--max-dd", type=float, default=0.10,
                    help="circuit-breaker: trip if equity falls this fraction (rule 2)")
    ap.add_argument("--max-tx", type=int, default=5, help="rate limit: max trades per window (rule 6)")
    ap.add_argument("--policy-window", type=int, default=3600,
                    help="rate-limit + spend-budget rolling window, in seconds")
    args = ap.parse_args()

    coins = _liquid(args.top, args.min_vol)

    live = None
    if args.arm:
        from treasuryforge.exchanges.hyperliquid import HyperliquidInfo
        from treasuryforge.exchanges.hyperliquid.live_executor import HlTwoPhaseExecutor
        from treasuryforge.exchanges.hyperliquid.secrets import resolve_agent_credentials
        from treasuryforge.orders import IdempotentOrderManager
        key, master = resolve_agent_credentials()

        def _exchange():
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            return Exchange(Account.from_key(key), constants.MAINNET_API_URL, account_address=master)

        info_client = HyperliquidInfo(_post)
        policy, pjournal = _build_policy(info_client, master, coins, args)
        live = {"info": info_client, "master": master, "exchange": _exchange,
                "two_phase": HlTwoPhaseExecutor, "mgr": IdempotentOrderManager,
                "policy": policy, "policy_journal": pjournal}

    books = {c: ScalpBook() for c in coins}
    journals = {c: Journal(f"{args.state_prefix}_{c.lower()}") for c in coins}
    last_bar: dict[str, int] = {}
    trade_eq = {c: 1.0 for c in coins}
    mode = "ARMED-LIVE" if args.arm else "PAPER"
    print(f"AUTONOMOUS scalp {mode}: {len(coins)} coins, gate=DSR>=0.60. "
          f"Live execution only when a coin's gate clears AND tier ({args.tier:.2%}) allocation >= ${_HL_MIN:.0f}.", flush=True)

    while True:
        now_ms = int(time.time() * 1000)
        # multiple-testing burden across the WHOLE scanned universe, recomputed each cycle so
        # the DSR a survivor must clear scales with how many coins we are looking at.
        trial_sharpes = _trial_sharpes(journals)
        for coin in coins:
            try:
                bar = _last_closed_1m(coin, now_ms)
                if bar is None or bar[0] == last_bar.get(coin):
                    continue
                t, high, low, close = bar
                last_bar[coin] = t
                action, r = books[coin].observe(high, low, close)
                trade_eq[coin] *= (1.0 + r)
                if action.startswith("EXIT"):
                    journals[coin].append_event({"kind": "scalp", "ts": int(t / 1000),
                                                 "r": trade_eq[coin] - 1.0, "exit": action})
                    trade_eq[coin] = 1.0
                # --- autonomous LIVE execution (armed + gated + bankroll OK) ---
                if live and action in ("ENTER", "EXIT_STOP", "EXIT_TRAIL", "EXIT_TIME"):
                    _maybe_execute(live, coin, action, journals[coin], args.tier, close, trial_sharpes)
            except Exception as e:
                print(f"({coin} error: {str(e)[:60]})", flush=True)
        time.sleep(args.interval)


_GATE_ALERTED: set[str] = set()    # coins already announced as gate-open (dedupe the push)


def _notify(text: str) -> None:
    """Best-effort immediate Telegram push for live events. NEVER raises -- a notify failure
    must never touch trading. No-ops cleanly when the Telegram env isn't set (paper)."""
    try:
        from scripts.telegram_report import send
        send(text)
    except Exception:
        pass


def _maybe_execute(live: dict, coin: str, action: str, journal: Journal, tier: float,
                   price: float = 0.0, trial_sharpes: list[float] | None = None) -> None:
    """Real micro order ONLY if the coin's gate is open, the tier clears the HL minimum, AND
    the policy engine's 8 hard rules approve the ENTER. Otherwise log why and stay flat -- the
    engine never forces an oversized trade. Closes (risk-reducing) are NOT policy-gated: a
    blocked exit would strand a live position, which is more dangerous than letting it close.
    Every gate-cross and every live order/denial fires an IMMEDIATE Telegram alert."""
    if not _gate_open(journal, trial_sharpes):
        return
    if coin not in _GATE_ALERTED:                         # first time this coin clears the gate
        _GATE_ALERTED.add(coin)
        _notify(f"GATE OPEN: {coin} cruzo DSR>=0.60 + comite. Evaluando orden...")
    collateral = live["info"].available_collateral(live["master"])
    notional = tier * collateral
    if action == "ENTER":
        if notional < _HL_MIN:
            msg = (f"{coin} GATE OPEN pero tier ${notional:.2f} < ${_HL_MIN:.0f} min "
                   f"-> NO opera (necesita ~${_HL_MIN / tier:.0f} colateral). Sigue en papel.")
            print(f">> {msg}", flush=True)
            _notify(msg)
            return
        intent = Intent(coin, Side.BUY, 0.0, quote_amount=notional, reason="autonomous scalp")
        # --- POLICY DISPOSES: the 8 hard rules gate every new-risk order ---
        policy = live.get("policy")
        if policy is not None:
            tick = MarketTick(coin, price, int(time.time()))
            wallet = SimWallet(quote=collateral)          # equity == collateral (perps PnL is in it)
            verdict = policy.evaluate(intent, tick, wallet)
            if not verdict.allowed:
                print(f">> {coin} {verdict.reason} -> NOT trading (policy dispose).", flush=True)
                _notify(f"{coin} gate OK pero POLICY bloqueo: {verdict.reason}")
                return
        ex = live["two_phase"](live["exchange"](), live["info"], live["master"], max_notional_usd=notional * 1.2)
        out = live["mgr"](ex, Journal("state/hl_live")).submit(
            intent, f"auto:{coin}:{int(time.time())}", coin)
        print(f">> LIVE ENTER {coin} ${notional:.2f}: {out.state.value} {out.reason}", flush=True)
        _notify(f"LIVE ENTER {coin} ${notional:.2f}: {out.state.value} {out.reason}")
        if policy is not None and out.state.value in ("FILLED", "OPEN"):  # count only orders that hit the book
            policy.register_fill(int(time.time()), notional)
            live["policy_journal"].append_event(
                {"kind": "policy_state", "ts": int(time.time()), "state": policy.snapshot()})
    else:  # close any open position
        pos = next((p for p in live["info"].open_positions(live["master"])
                    if p["coin"] == coin and abs(p["size"]) > 0), None)
        if pos:
            side = Side.SELL if pos["size"] > 0 else Side.BUY
            ex = live["two_phase"](live["exchange"](), live["info"], live["master"],
                                   max_notional_usd=1e9, reduce_only=True)
            out = live["mgr"](ex, Journal("state/hl_live")).submit(
                Intent(coin, side, abs(pos["size"]), reason="autonomous close"),
                f"auto:close:{coin}:{int(time.time())}", coin)
            print(f">> LIVE CLOSE {coin}: {out.state.value} {out.reason}", flush=True)
            _notify(f"LIVE CLOSE {coin}: {out.state.value} {out.reason}")


if __name__ == "__main__":
    main()
