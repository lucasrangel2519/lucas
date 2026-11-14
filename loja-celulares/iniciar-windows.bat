@echo off
cd /d "%~dp0"
start "" http://localhost:8080
where py >nul 2>nul && (py servidor.py %*) || (python servidor.py %*)
pause
