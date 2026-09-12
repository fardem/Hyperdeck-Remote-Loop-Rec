#!/usr/bin/env bash
# HyperDeck Web Control - Start unter Linux / macOS
set -u
cd "$(dirname "$0")"

echo "============================================================"
echo "  HyperDeck Web Control wird gestartet"
echo "============================================================"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "[FEHLER] Python 3 wurde nicht gefunden."
  exit 1
fi

if [ ! -f ui/index.html ] || [ ! -f hyperdeck_backup.py ]; then
  echo "[FEHLER] Programmordner unvollstaendig (ui/ oder hyperdeck_backup.py fehlt)."
  exit 1
fi
echo "[1/3] Python gefunden: $("$PY" --version 2>&1)"
echo "[2/3] Abhaengigkeiten pruefen (flask, waitress) ..."
"$PY" -m pip install -r requirements.txt --disable-pip-version-check || \
  echo "[WARNUNG] Installation fehlgeschlagen - Start wird trotzdem versucht."

echo "[3/3] Dienst startet, der Browser oeffnet sich automatisch."
echo "      Beenden mit Strg + C."
echo
exec "$PY" hyperdeck_control.py "$@"
