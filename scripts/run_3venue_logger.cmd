@echo off
REM treasuryforge 3-venue spread logger -- runs on Christian's PC (residential IP reaches
REM Binance fapi where the VPS gets 451). Plain .cmd: not subject to PowerShell policy.
cd /d "C:\Users\DANNY\Desktop\treasuryforge"
".venv\Scripts\python.exe" scripts\log_cross_spread_3venue.py --coins XRP,ZEC --push-to root@152.53.167.28 >> "state\3venue_task.log" 2>&1
