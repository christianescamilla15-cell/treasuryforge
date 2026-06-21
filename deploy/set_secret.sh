#!/usr/bin/env bash
# Run this YOURSELF in your OWN ssh session on the VPS.
# The secret is read hidden (read -s): never echoed, never in shell history,
# written to a 0600 file. It never reaches Claude / this chat.
#
# It prints the CAPTURED LENGTHS (not the values) so you can immediately catch a
# paste that dropped characters (the classic cause of a 0215 auth error).
set -euo pipefail
mkdir -p /etc/treasuryforge
umask 077
read -rp  "BITSO_API_KEY (public part, ok to show): " K
read -rsp "BITSO_API_SECRET (hidden, paste + Enter): " S
echo
echo "captured: key=${#K} chars, secret=${#S} chars"
echo "  -> if these do not match what Bitso shows (e.g. key=10, secret=32),"
echo "     the paste dropped characters. Press Ctrl+C and run again."
read -rp "Looks right? write the file? [y/N] " OK
if [ "$OK" != "y" ] && [ "$OK" != "Y" ]; then
  echo "Aborted, nothing written."
  exit 1
fi
printf 'BITSO_API_KEY=%s\nBITSO_API_SECRET=%s\n' "$K" "$S" > /etc/treasuryforge/bitso.env
chmod 600 /etc/treasuryforge/bitso.env
unset K S
echo "Wrote /etc/treasuryforge/bitso.env (0600). Done. You can close this session."
