"""Bitso adapter: stdlib-only HMAC-SHA256 signing + a two-phase executor.

Chosen in Phase-3 (see PHASE3_IMPLEMENTATION.md): Mexico-domiciled, CNBV-supervised,
native free SPEI, CURP KYC, and API-key permissions that natively express
trade-only + no-withdrawal + IP-allowlist. Signing is plain HMAC-SHA256 — no SDK,
no `cryptography`, no JWT — so the whole adapter stays inside the stdlib-only ethos.
"""

from .client import BitsoClient
from .errors import BitsoError, classify
from .executor import BitsoExecutor, OrderHandle, Unfilled
from .signer import BitsoSigner, NonceV2

__all__ = [
    "BitsoClient",
    "BitsoError",
    "BitsoExecutor",
    "BitsoSigner",
    "NonceV2",
    "OrderHandle",
    "Unfilled",
    "classify",
]
