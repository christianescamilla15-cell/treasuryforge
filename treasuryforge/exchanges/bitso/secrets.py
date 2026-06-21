"""Secret storage for live API credentials — OS keychain, never plaintext.

Uses the `keyring` library: Windows Credential Manager (DPAPI) on Windows,
Keychain on macOS, SecretService on Linux. The API secret is NEVER written to
the repo, a `.env`, env vars, logs, the journal, or the audit log — it lives only
in the OS keychain and is read into memory only to build a signed request.

`keyring` is a deliberate, scoped dependency used ONLY on the live/credential
path (`requirements-live.txt`). The simulation core stays stdlib-only.

DPAPI does not stop same-user malware on an unattended host — the real cap on a
leaked key remains the trade-only / no-withdrawal scope set at key creation.
"""

from __future__ import annotations

import os

SERVICE = "treasuryforge-bitso"
_KEY = "api_key"
_SECRET = "api_secret"
_ENV_KEY = "BITSO_API_KEY"
_ENV_SECRET = "BITSO_API_SECRET"


def resolve_credentials() -> tuple[str, str]:
    """Get (api_key, api_secret) from the environment first, then the keychain.

    On the headless VPS, the secret is injected via the environment by systemd
    (from a 0600 EnvironmentFile, never the repo). On the Windows dev box it
    lives in the OS keychain. Raises if neither is configured.
    """
    env_key, env_secret = os.environ.get(_ENV_KEY), os.environ.get(_ENV_SECRET)
    if env_key and env_secret:
        return env_key, env_secret
    store = SecretStore()
    key, secret = store.api_key(), store.api_secret()
    if key and secret:
        return key, secret
    raise RuntimeError(
        "No Bitso credentials found. Set BITSO_API_KEY/BITSO_API_SECRET (VPS) "
        "or run scripts/import_bitso_key.py to store them in the keychain (Windows)."
    )


class SecretStore:
    def __init__(self, service: str = SERVICE) -> None:
        try:
            import keyring
        except ImportError as e:  # pragma: no cover - environment guard
            raise RuntimeError(
                "keyring is not installed. Install the live deps: "
                "pip install -r requirements-live.txt"
            ) from e
        self._kr = keyring
        self._service = service

    def set_credentials(self, api_key: str, api_secret: str) -> None:
        self._kr.set_password(self._service, _KEY, api_key)
        self._kr.set_password(self._service, _SECRET, api_secret)

    def api_key(self) -> str | None:
        return self._kr.get_password(self._service, _KEY)

    def api_secret(self) -> str | None:
        return self._kr.get_password(self._service, _SECRET)

    def is_configured(self) -> bool:
        return bool(self.api_key() and self.api_secret())

    def clear(self) -> None:
        for k in (_KEY, _SECRET):
            try:
                self._kr.delete_password(self._service, k)
            except Exception:
                pass
