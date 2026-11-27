@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo 创口温差初筛  http://127.0.0.1:8765
start "" http://127.0.0.1:8765
python -m app.server
pause
