@echo off
REM treasuryforge persistent forward-research loops -- launched hidden at logon by a VBS in
REM the Startup folder. BOTH are read-only measurement: no keys, no orders, no capital.
REM   1) 3-venue funding-spread logger (HL+OKX+Binance), 5-min, mirrors to the VPS.
REM   2) Coinbase ignition detector (+15%/1h), 15-min, the selection-skill forward ledger.
REM State is written to each loop's journal (state\spread3_*, state\ignitions); the
REM scorecard/score scripts read those. Plain .cmd: not subject to PowerShell policy.
cd /d "C:\Users\DANNY\Desktop\treasuryforge"
start "tf-3venue" /b ".venv\Scripts\python.exe" scripts\log_cross_spread_3venue.py --coins XRP,ZEC --push-to root@152.53.167.28 --loop 300
start "tf-ignition" /b ".venv\Scripts\python.exe" scripts\ignition_detector.py --loop 900 --enter 0.15 --limit 400 --resolve-hours 168
