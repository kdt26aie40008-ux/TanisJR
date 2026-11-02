@echo off
rem Double-click launcher (kept ASCII-only so cmd.exe parses it under any code page)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
pause
