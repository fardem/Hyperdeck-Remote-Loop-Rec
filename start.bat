@echo off
rem ===========================================================
rem  HyperDeck Web Control - Startdatei fuer Windows
rem  Doppelklick genuegt. Das Fenster bleibt in JEDEM Fall offen,
rem  damit man sieht, was passiert (auch bei Fehlern).
rem ===========================================================
setlocal
chcp 65001 >nul 2>&1
title HyperDeck Web Control
cd /d "%~dp0"

rem Umlaute sauber ausgeben, Ausgabe nicht puffern, Python-Pause unterdruecken
rem (dieses Skript pausiert am Ende selbst).
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "HYPERDECK_NO_PAUSE=1"

rem Port der Weboberflaeche - hier bei Bedarf aendern
set "WEBPORT=5000"

echo ============================================================
echo   HyperDeck Web Control wird gestartet
echo ============================================================
echo.

rem ---------- 1. Python suchen -------------------------------------------
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [FEHLER] Es wurde kein Python 3 gefunden.
  echo.
  echo   1. Python 3 installieren:  https://www.python.org/downloads/
  echo   2. Bei der Installation "Add python.exe to PATH" ankreuzen.
  echo   3. Danach diese Datei erneut starten.
  goto :ende
)

echo [1/3] Python gefunden:
%PY% --version
echo.

rem ---------- 2. Abhaengigkeiten ------------------------------------------
echo [2/3] Abhaengigkeiten pruefen (flask) ...
%PY% -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [WARNUNG] Die Installation der Abhaengigkeiten hat nicht funktioniert.
  echo           Der Start wird trotzdem versucht - eventuell ist flask
  echo           bereits vorhanden.
)
echo.

rem ---------- 3. Start ----------------------------------------------------
echo [3/3] Dienst startet. Der Browser oeffnet sich automatisch.
echo       Adresse: http://localhost:%WEBPORT%
echo.
echo ------------------------------------------------------------
echo   Dieses Fenster bitte OFFEN LASSEN - hier laeuft der Dienst.
echo   Beenden mit Strg + C oder durch Schliessen des Fensters.
echo ------------------------------------------------------------
echo.

%PY% hyperdeck_control.py --web-port %WEBPORT% %*
set "RC=%ERRORLEVEL%"

echo.
echo ------------------------------------------------------------
echo   Der Dienst wurde beendet (Rueckgabewert %RC%).
echo ------------------------------------------------------------

:ende
echo.
pause
endlocal
