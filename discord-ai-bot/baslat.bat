@echo off

cd /d "%~dp0"

python -m pip install -r requirements.txt -q

python token_kontrol.py

if errorlevel 1 pause & exit /b 1

python bot.py

pause
