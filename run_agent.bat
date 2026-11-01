@echo off
cd /d %~dp0
if not exist tmp mkdir tmp
set TMP=%~dp0tmp
set TEMP=%~dp0tmp
set PYTHONIOENCODING=utf-8
echo 启动影之刃零 AI 代理（F12 随时急停）...
.venv\Scripts\python.exe -m agent.main config.yaml
pause
