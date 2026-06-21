"""Reproducibility pack — the historical truth of every decision.

Before adding more intelligence, lock down traceability: every verdict must be
answerable with "which EXACT data, config, strategy, code and environment produced
this?". Each report gets content hashes (deterministic — same inputs, same hash)
plus the git commit, timestamp and environment (metadata). A single `pack_id`
fingerprints the whole decision.

The CONTENT hashes (data/config/strategy/report) are deterministic, so two runs on
identical inputs are provably reproducible even though their timestamps differ.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field


def canonical_hash(obj: object) -> str:
    """SHA-256 of a canonical JSON serialization (order-independent, stable)."""
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_commit(cwd: str | None = None) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "no-git"


def _environment() -> dict:
    env = {"python": sys.version.split()[0]}
    try:
        import treasuryforge
        env["treasuryforge"] = getattr(treasuryforge, "__version__", "0.1.0")
    except Exception:
        pass
    return env


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ReproducibilityPack:
    data_hash: str
    config_hash: str
    strategy_hash: str
    report_hash: str
    git_commit: str
    timestamp: str
    environment: dict = field(default_factory=dict)
    pack_id: str = ""

    def content_fingerprint(self) -> str:
        """Deterministic id of the INPUTS+OUTPUT only (no timestamp/commit) — two
        runs on the same data/config/strategy share this even across machines."""
        return text_hash("|".join([self.data_hash, self.config_hash,
                                   self.strategy_hash, self.report_hash]))

    def reproduces(self, other: ReproducibilityPack) -> bool:
        return self.content_fingerprint() == other.content_fingerprint()

    def render(self) -> str:
        e = " ".join(f"{k}={v}" for k, v in self.environment.items())
        return "\n".join([
            "REPRODUCIBILITY PACK",
            f"  pack id:      {self.pack_id[:16]}",
            f"  data:         {self.data_hash[:16]}",
            f"  config:       {self.config_hash[:16]}",
            f"  strategy:     {self.strategy_hash[:16]}",
            f"  report:       {self.report_hash[:16]}",
            f"  git commit:   {self.git_commit[:12]}",
            f"  timestamp:    {self.timestamp}",
            f"  environment:  {e}"])


def make_provenance(*, data: object, config: object, strategy: object, report: object,
                    timestamp: str | None = None, git_cwd: str | None = None) -> ReproducibilityPack:
    dh = canonical_hash(data)
    ch = canonical_hash(config)
    sh = canonical_hash(strategy)
    rh = text_hash(report) if isinstance(report, str) else canonical_hash(report)
    gc = _git_commit(git_cwd)
    ts = timestamp or _now_iso()
    env = _environment()
    pack_id = text_hash("|".join([dh, ch, sh, rh, gc, ts]))
    return ReproducibilityPack(dh, ch, sh, rh, gc, ts, env, pack_id)
