#!/usr/bin/env bash
# Provision the Hyperliquid AGENT credentials on the VPS -- run as root, by the OWNER.
#
# The agent private key is read from a HIDDEN prompt (read -s): it never appears in
# the chat, in your shell history, or on screen. It is written to a root/service-only
# env file (mode 600) that the live service loads via EnvironmentFile. The agent key
# is trade-only / no-withdraw, so even a leak cannot move funds out.
#
#   sudo bash scripts/set_hl_secret.sh
set -euo pipefail

DEST=/etc/treasuryforge/hl.env
SVC_USER=treasuryforge

read -rsp "Paste HL_AGENT_KEY (agent private key, hidden): " KEY; echo
if [[ ! "$KEY" =~ ^0x[0-9a-fA-F]{64}$ ]]; then
  echo "ERROR: key must be 0x followed by 64 hex chars." >&2; exit 1
fi
read -rp  "HL_ACCOUNT_ADDRESS (your MASTER address, public 0x...): " ADDR
if [[ ! "$ADDR" =~ ^0x[0-9a-fA-F]{40}$ ]]; then
  echo "ERROR: address must be 0x followed by 40 hex chars." >&2; exit 1
fi

install -d -m 750 -o "$SVC_USER" -g "$SVC_USER" /etc/treasuryforge
umask 077
printf 'HL_AGENT_KEY=%s\nHL_ACCOUNT_ADDRESS=%s\n' "$KEY" "$ADDR" > "$DEST"
chown "$SVC_USER:$SVC_USER" "$DEST"
chmod 600 "$DEST"
unset KEY

echo "wrote $DEST (600, $SVC_USER). The key was NOT echoed. Never commit this file."
echo "Sign-check:  set -a; source $DEST; set +a; \\"
echo "             /opt/treasuryforge/.venv/bin/python scripts/hl_sign_check.py"
