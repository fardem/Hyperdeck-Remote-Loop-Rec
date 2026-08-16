@echo off
title HyperDeck Web Control
echo ======================================================
echo   HyperDeck Web Control wird gestartet...
echo ======================================================

pip install -r requirements.txt >nul 2>&1
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:5000"
python hyperdeck_control.py
pause
