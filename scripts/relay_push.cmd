@echo off
REM treasuryforge funding relay -- fetch Binance/Bybit on this (region-permissive) host and
REM push the snapshot to the VPS. Scheduled every 5 min by Windows Task Scheduler.
REM Path-independent: %~dp0 is the scripts\ dir, .. is the repo root.
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\relay_funding_pc.py --coins XRP,ZEC | ssh -o BatchMode=yes -o ConnectTimeout=20 root@152.53.167.28 "cat > /opt/treasuryforge/state/relay/funding.json"
