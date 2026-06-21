"""Move your Bitso API credentials into the OS keychain — run it YOURSELF.

The secret is typed into a hidden prompt (getpass): it is never echoed to the
screen, never written to a file, never logged, and never leaves your machine.
After it round-trips through the keychain, DELETE the downloaded credentials
file from your Downloads folder.

    cd Desktop/treasuryforge
    .venv\\Scripts\\python.exe scripts\\import_bitso_key.py
"""

from __future__ import annotations

import getpass
import sys

# allow running from the project root without installing the package
sys.path.insert(0, ".")

from treasuryforge.exchanges.bitso.secrets import SecretStore


def main() -> None:
    print("Importing Bitso credentials into the OS keychain (Windows Credential Manager).")
    print("Nothing is written to disk or shown on screen. Ctrl+C to abort.\n")

    api_key = input("API key (the public part, ok to show): ").strip()
    api_secret = getpass.getpass("API secret (hidden — paste and press Enter): ").strip()

    if not api_key or not api_secret:
        raise SystemExit("Both the key and the secret are required.")

    store = SecretStore()
    store.set_credentials(api_key, api_secret)

    # verify the round-trip WITHOUT ever printing the secret
    ok = store.api_key() == api_key and store.api_secret() == api_secret
    # scrub the local copies
    api_secret = "x" * len(api_secret)
    del api_secret

    if ok:
        print("\nOK: stored and verified in the OS keychain (service 'treasuryforge-bitso').")
        print("NEXT: delete the credentials file from Downloads and empty the Recycle Bin.")
    else:
        print("\nERROR: keychain round-trip failed — nothing trustworthy stored.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
