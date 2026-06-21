"""Tamper-evident audit log — HMAC-SHA256 hash chain over every decision.

Each record seals (prev_hash + canonical-JSON entry) with an HMAC keyed by a
secret the agent process should not be able to overwrite. Any after-the-fact
edit, reorder, insert or delete breaks the chain and `verify_chain` returns
False. Pure stdlib (hashlib + hmac + json).

Honest scope: this proves TAMPER-EVIDENCE, not non-repudiation — the same key
both signs and verifies. Store the key and the log outside the agent's writable
path to make tampering actually hard. (We deliberately drop the SEC 15c3-5 /
Reg-AT framing from the raw research: that rule was withdrawn / does not apply.)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

GENESIS = "0" * 64


def _canonical(entry: dict) -> str:
    return json.dumps(entry, separators=(",", ":"), sort_keys=True)


class AuditLog:
    def __init__(self, path: str, key: bytes, prev_hash: str = GENESIS) -> None:
        self.path = path
        self._key = key
        self.prev = prev_hash

    def record(self, entry: dict) -> str:
        payload = _canonical(entry)
        mac = hmac.new(self._key, (self.prev + payload).encode("utf-8"),
                       hashlib.sha256).hexdigest()
        line = json.dumps({"prev": self.prev, "entry": entry, "hmac": mac},
                          separators=(",", ":"), sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.prev = mac
        return mac


def verify_chain(path: str, key: bytes, genesis: str = GENESIS) -> bool:
    """True iff the on-disk chain is intact and every HMAC checks out."""
    prev = genesis
    if not os.path.exists(path):
        return True
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("prev") != prev:
                return False
            mac = hmac.new(key, (prev + _canonical(rec["entry"])).encode("utf-8"),
                           hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, rec.get("hmac", "")):
                return False
            prev = mac
    return True
