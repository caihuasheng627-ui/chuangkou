@echo off
cd /d "%~dp0"
echo 创口温差初筛  http://127.0.0.1:8765
start "" http://127.0.0.1:8765
python -m app.server
pause
