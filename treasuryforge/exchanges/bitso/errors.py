"""Bitso error taxonomy — dispatch on HTTP status THEN error.code.

The dangerous defaults (from the Phase-3 research):
  * Rate limit is HTTP 420 (NOT 429). A tight retry storm escalates a 1-minute
    lockout into a 24-hour block — so 420 is non-retryable here; back off >= 60s.
  * 5xx / timeout is INDETERMINATE, never blind-retry: the order may have landed.
    Resolve via a user_trades / origin_ids lookup before any re-POST.
  * Auth / permission / IP-allowlist errors are fail-closed and loud.
"""

from __future__ import annotations

from dataclasses import dataclass

# action categories the caller must branch on
RETRYABLE_BACKOFF = "retry_backoff"     # transient, safe to retry after a long backoff
INDETERMINATE = "indeterminate"         # unknown outcome -> reconcile before any retry
FATAL_AUTH = "fatal_auth"               # key/signature/permission/IP -> stop, alert
NON_RETRYABLE = "non_retryable"         # deterministic rejection (e.g. insufficient funds)
SUBMITTED = "submitted"                 # accepted but not final -> poll, never resubmit
OK = "ok"

# code -> (category, human message)
_CODES: dict[str, tuple[str, str]] = {
    "0201": (FATAL_AUTH, "invalid signature"),
    "0202": (FATAL_AUTH, "API key not authorized for this method (check key scope)"),
    "0206": (INDETERMINATE, "nonce issue"),
    "0207": (INDETERMINATE, "nonce issue"),
    "0213": (FATAL_AUTH, "request IP not in the API key allowlist (check IP allowlist)"),
    "0215": (FATAL_AUTH, "authentication failed"),
    "0377": (SUBMITTED, "order submitted, not yet final — poll, do not resubmit"),
    "0378": (SUBMITTED, "order submitted, not yet final — poll, do not resubmit"),
    "0379": (NON_RETRYABLE, "insufficient funds"),
}


@dataclass(frozen=True)
class BitsoError(Exception):
    category: str
    code: str
    message: str
    http_status: int

    def __str__(self) -> str:
        return f"[{self.http_status}/{self.code}] {self.category}: {self.message}"


def classify(http_status: int, code: str | None = None, message: str = "") -> str:
    """Return the action category for a response."""
    if http_status == 420:
        return RETRYABLE_BACKOFF          # rate limited — long backoff ONLY, never tight-retry
    if http_status >= 500 or http_status == 0:
        return INDETERMINATE              # server error / timeout: outcome unknown
    if code and code in _CODES:
        return _CODES[code][0]
    if http_status in (200, 201):
        return OK
    if http_status in (401, 403):
        return FATAL_AUTH
    return NON_RETRYABLE                   # 4xx validation etc.
