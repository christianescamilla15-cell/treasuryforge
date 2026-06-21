#!/usr/bin/env bash
# Run this YOURSELF in your OWN ssh session on the VPS.
# Provisions the Hyperliquid AGENT (API) wallet credentials. The agent private key
# is read hidden (read -s): never echoed, never in shell history, written 0600.
# It never reaches Claude / this chat. The agent key is trade-only/no-withdraw.
set -euo pipefail
mkdir -p /etc/treasuryforge
umask 077
read -rp  "HL_ACCOUNT_ADDRESS (your main 0x... address, public): " ADDR
read -rsp "HL_AGENT_KEY (agent wallet private key 0x...64hex, hidden): " KEY
echo
echo "captured: address len=${#ADDR}, key len=${#KEY} (expect ~42 and ~66)"
read -rp "write the file? [y/N] " OK
if [ "$OK" != "y" ] && [ "$OK" != "Y" ]; then echo "aborted"; exit 1; fi
printf 'HL_ACCOUNT_ADDRESS=%s\nHL_AGENT_KEY=%s\n' "$ADDR" "$KEY" > /etc/treasuryforge/hyperliquid.env
chmod 600 /etc/treasuryforge/hyperliquid.env
unset KEY ADDR
echo "Wrote /etc/treasuryforge/hyperliquid.env (0600). Done."
