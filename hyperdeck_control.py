#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HyperDeck Studio - Web Control
==============================
Fernsteuerung fuer Blackmagic HyperDeck ueber das Ethernet-Protokoll (Port 9993).

Funktionen
  * Loop-Record .... Hauptschalter fuer die gesamte Endlos-Automatik
      - Auto-Record .. startet die Aufnahme automatisch, wenn das Deck steht
      - Auto-Loop .... formatiert rechtzeitig die inaktive Karte
  * Timer-Aufnahme .. bis zu drei Zeitplaene (z. B. Mo-Fr 08:45-18:30).
    Der Rekorder startet und stoppt ohne Zutun zur eingestellten Uhrzeit.
  * Manueller STOP bleibt STOP. Er setzt eine Verriegelung, die Auto-Record
    blockiert, bis im Web-UI wieder RECORD (oder "Auto-Record freigeben")
    gedrueckt wird.
  * Alle wichtigen Parameter sind im Browser aenderbar und werden in
    hyperdeck_config.json gespeichert.

Architektur 
  * GENAU EIN Thread spricht mit dem Deck, ueber GENAU EINE dauerhafte
    TCP-Verbindung. Die Flask-Endpunkte reden nie selbst mit dem Deck,
    sie legen nur Auftraege in eine Queue -> das Web-UI kann nicht blockieren
    und zwei gleichzeitige Sockets koennen sich nicht mehr ins Gehege kommen.
  * Der Protokoll-Parser arbeitet zeilenbasiert nach Antwortcode statt mit
    time.sleep() und Textsuche. Asynchrone Meldungen (5xx) werden erkannt und
    uebersprungen, Mehrzeilenbloecke werden bis zur Leerzeile gelesen.
  * Jeder Fehler fuehrt zu sauberem Reconnect mit Backoff statt zum Stillstand.

Start (Windows: einfach start.bat doppelklicken):
    pip install flask
    python3 hyperdeck_control.py --ip 172.17.100.119 --web-port 5000

Der Browser wird beim Start automatisch geoeffnet (--no-browser schaltet das ab).
"""

import argparse
import copy
import datetime
import json
import logging
import os
import queue
import re
import select
import socket
import sys
import threading
import time
import traceback
import webbrowser

from flask import Flask, Response, jsonify, request, send_from_directory
from logging.handlers import RotatingFileHandler

try:
    import hyperdeck_backup
except ImportError:
    sys.exit("Die Datei hyperdeck_backup.py fehlt neben hyperdeck_control.py.\n"
             "Bitte den kompletten Programmordner kopieren, nicht nur einzelne Dateien.")

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

APP_VERSION = "3.2.0"       # wird in der Web-Oberflaeche und im Log angezeigt
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Ablage fuer Konfiguration und Logdatei. Ueber die Umgebungsvariable
# HYPERDECK_HOME laesst sich ein anderer Ordner waehlen - z. B. fuer eine
# zweite Instanz mit einem zweiten Deck oder fuer Tests.
DATA_DIR = os.environ.get("HYPERDECK_HOME") or APP_DIR
CONFIG_PATH = os.path.join(DATA_DIR, "hyperdeck_config.json")
LOG_PATH = os.path.join(DATA_DIR, "hyperdeck.log")
STARTED_AT = time.time()

TIMER_SLOTS = 3             # mehr als drei Zeitplaene sind nicht vorgesehen
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]   # Index = date.weekday()

# Vorgabe: Autorecord 1 laeuft werktags von 08:45 bis 18:30
DEFAULT_TIMERS = [
    {"enabled": True, "days": [0, 1, 2, 3, 4], "start": "08:45", "end": "18:30"},
    {"enabled": True, "days": [0, 1, 2, 3, 4], "start": "08:45", "end": "18:30"},
    {"enabled": True, "days": [5, 6], "start": "08:45", "end": "18:30"},
]

DEFAULT_SETTINGS = {
    "deck_ip": "172.17.100.119",
    "deck_port": 9993,
    "check_interval": 20,           # Sekunden zwischen zwei Deck-Abfragen
    "min_remaining_threshold": 5,   # ab dieser Restzeit (min) wird vorbereitet
    "inactive_min_free": 15,        # inaktive Karte formatieren, wenn weniger frei
    "loop_record": True,            # Hauptschalter der Endlos-Automatik
    "auto_record": True,
    "auto_loop": True,
    "sync_timecode": True,          # Timecode beim Start auf Uhrzeit setzen
    "format_filesystem": "exFAT",   # exFAT oder HFS+
    "format_name": "LoopDump",
    "timer_enabled": False,         # Zeitgesteuerte Aufnahme (Timer-Recording)
    "timer_count": 1,               # sichtbare/aktive Zeitplaene: 1 bis 3
    "timers": copy.deepcopy(DEFAULT_TIMERS),
    # Sicherung der Aufnahmen (FTP vom Deck -> Netzlaufwerk oder FTP-Server)
    "deck_ftp_port": 21,
    "deck_ftp_user": "",            # leer = anonym (Standard beim HyperDeck)
    "deck_ftp_pass": "",
    "backup_enabled": False,        # automatisch im Intervall spiegeln
    "backup_interval": 15,          # Minuten
    "backup_mode": "folder",        # "folder" (Ordner/Netzlaufwerk) oder "ftp"
    "backup_folder": "",            # z. B. Z:\\HyperDeck oder \\\\NAS\\Aufnahmen
    "backup_ftp_host": "",
    "backup_ftp_port": 21,
    "backup_ftp_user": "",
    "backup_ftp_pass": "",
    "backup_ftp_path": "/",
    "backup_source_path": "/",      # Startordner am Deck (normalerweise die Wurzel)
    "backup_block_format": True,    # Karte erst leeren, wenn ihre Clips gesichert sind
}

SECRET_KEYS = ("deck_ftp_pass", "backup_ftp_pass")
SETTING_CHOICES = {
    "format_filesystem": ("exFAT", "HFS+"),
    "backup_mode": ("folder", "ftp"),
}

SETTING_TYPES = {
    "deck_ip": str,
    "deck_port": int,
    "check_interval": int,
    "min_remaining_threshold": int,
    "inactive_min_free": int,
    "loop_record": bool,
    "auto_record": bool,
    "auto_loop": bool,
    "sync_timecode": bool,
    "format_filesystem": str,
    "format_name": str,
    "timer_enabled": bool,
    "timer_count": int,
    "timers": list,
    "deck_ftp_port": int,
    "deck_ftp_user": str,
    "deck_ftp_pass": str,
    "backup_enabled": bool,
    "backup_interval": int,
    "backup_mode": str,
    "backup_folder": str,
    "backup_ftp_host": str,
    "backup_ftp_port": int,
    "backup_ftp_user": str,
    "backup_ftp_pass": str,
    "backup_ftp_path": str,
    "backup_source_path": str,
    "backup_block_format": bool,
}

LIMITS = {
    "deck_port": (1, 65535),
    "check_interval": (1, 3600),
    "min_remaining_threshold": (1, 240),
    "inactive_min_free": (1, 2000),
    "timer_count": (1, TIMER_SLOTS),
    "deck_ftp_port": (1, 65535),
    "backup_interval": (1, 1440),
    "backup_ftp_port": (1, 65535),
}

# Asynchrone Meldungen des Decks (Protokoll: "5xx {Text}:"). Sie kommen
# unaufgefordert, sobald sie per "notify" abonniert sind.
ASYNC_CONNECTION = 500      # 500 connection info  (Begruessung)
ASYNC_SLOT = 502            # 502 slot info        (Karte gewechselt, Restzeit)
ASYNC_TRANSPORT = 508       # 508 transport info   (Aufnahme laeuft/steht)

FORMAT_COOLDOWN_S = 180     # Sperre pro Slot nach einer Formatierung
SLOT_POLL_MIN_S = 5         # Kartenstatus hoechstens so oft abfragen
AUTORECORD_RETRY_S = 10     # Mindestabstand zwischen zwei Auto-Record-Versuchen
TIMER_RETRY_S = 10          # Wiederholabstand, wenn ein Timer-Befehl nicht griff
TIMER_STOP_GRACE_S = 300    # so lange wird ein verpasster Timer-Stopp nachgeholt
BACKUP_CLEAN_MAX_AGE_S = 900  # so alt darf die letzte saubere Sicherung vor dem Leeren sein
LOG_MAX = 250

# Fehlercodes des HyperDeck-Protokolls, die haeufig vorkommen
ERROR_HINTS = {
    100: "Syntaxfehler",
    101: "Parameter nicht unterstuetzt",
    102: "Ungueltiger Wert",
    103: "Befehl nicht unterstuetzt",
    104: "Karte voll",
    105: "Keine Karte",
    106: "Kartenfehler",
    108: "Interner Fehler",
    109: "Wert ausserhalb des Bereichs",
    110: "Kein Eingangssignal",
    111: "Fernsteuerung deaktiviert - am Deck 'Remote' einschalten",
    120: "Verbindung abgewiesen",
    150: "Ungueltiger Zustand",
    160: "Ungueltiges Format",
    161: "Ungueltiges Token",
    162: "Formatierung nicht vorbereitet",
    163: "Parameter nicht unterstuetzt",
}

# --------------------------------------------------------------------------
# Zustand, Einstellungen, Log
# --------------------------------------------------------------------------

SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)   # eigene Kopie, nie die Vorgaben aendern
_settings_lock = threading.RLock()

STATE = {
    "connected": False,
    "connection_error": "",
    "device": "HyperDeck",
    "status": "offline",
    "timecode": "--:--:--:--",
    "active_slot": None,
    "slots": [
        {"id": 1, "status": "unknown", "remaining_min": 0, "volume": ""},
        {"id": 2, "status": "unknown", "remaining_min": 0, "volume": ""},
    ],
    "manual_stop": False,
    "busy": "",
    "seconds_until_check": 0,
    "last_poll": "",
    "last_format": {"1": "", "2": ""},
    "timer_active": None,       # Nummer (1..3) des laufenden Zeitfensters
    "timer_info": "Timer aus",  # Klartext fuer die Oberflaeche
    "notify": False,            # Deck meldet Aenderungen von selbst
}
_state_lock = threading.RLock()

_logs = []
_log_lock = threading.Lock()
_log_seq = [0]
_throttle = {}
_file_log = logging.getLogger("hyperdeck")
_file_log.propagate = False
_LOG_LEVELS = {"err": logging.ERROR, "warn": logging.WARNING}


def setup_file_log():
    """Rotierende Logdatei neben dem Skript (1 MB, drei Generationen), damit
    sich auch nach Tagen noch nachvollziehen laesst, was passiert ist."""
    try:
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1000000, backupCount=3,
                                      encoding="utf-8")
    except OSError as exc:
        log("Logdatei %s nicht schreibbar: %s" % (LOG_PATH, exc), "warn")
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                                           "%Y-%m-%d %H:%M:%S"))
    _file_log.addHandler(handler)
    _file_log.setLevel(logging.INFO)


def log(msg, level="info"):
    """Schreibt eine Zeile in Konsole, Web-Log und Logdatei. Jede Zeile hat
    eine ID, damit der Browser nur die neuen Zeilen nachladen muss."""
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    text = str(msg)
    with _log_lock:
        _log_seq[0] += 1
        _logs.append({"id": _log_seq[0], "time": stamp, "msg": text, "level": level})
        del _logs[:-LOG_MAX]
    if _file_log.handlers:
        _file_log.log(_LOG_LEVELS.get(level, logging.INFO), text)
    try:
        print("[%s] %s" % (stamp, text), flush=True)
    except UnicodeEncodeError:      # exotische Konsolen-Codepage
        print("[%s] %s" % (stamp, text.encode("ascii", "replace").decode("ascii")),
              flush=True)


def log_throttled(key, msg, level="info", period=120):
    """Verhindert, dass eine dauerhaft bestehende Stoerung das Log flutet."""
    now = time.monotonic()
    last = _throttle.get(key, 0.0)
    if now - last >= period:
        _throttle[key] = now
        log(msg, level)


def set_state(**kwargs):
    with _state_lock:
        STATE.update(kwargs)


def get_settings():
    with _settings_lock:
        snapshot = dict(SETTINGS)
    # Die Timer-Liste wird kopiert, damit kein Aufrufer die Originaldaten aendert.
    snapshot["timers"] = copy.deepcopy(snapshot["timers"])
    return snapshot


# ---- Timer-Hilfsfunktionen -----------------------------------------------

def _to_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes", "ja")
    return bool(value)


def parse_hhmm(value, fallback="00:00"):
    """Nimmt "8:45", "08:45" oder "08:45:00" und liefert immer "HH:MM"."""
    match = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})", str(value or ""))
    if match is None:
        return fallback
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return fallback
    return "%02d:%02d" % (hour, minute)


def hhmm_to_minutes(value):
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def normalize_days(raw, fallback):
    """Akzeptiert [0,1,2], "0,1,2" oder "Mo,Di" und liefert eine sortierte Liste."""
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    elif isinstance(raw, str):
        parts = [p for p in re.split(r"[,;\s]+", raw) if p]
    else:
        return list(fallback)
    days = []
    for part in parts:
        try:
            day = int(part)
        except (TypeError, ValueError):
            text = str(part).strip().lower()[:2]
            lookup = [w.lower() for w in WEEKDAYS]
            day = lookup.index(text) if text in lookup else -1
        if 0 <= day <= 6 and day not in days:
            days.append(day)
    return sorted(days)


def normalize_timers(raw):
    """Erzwingt immer genau TIMER_SLOTS vollstaendige, plausible Eintraege."""
    items = list(raw) if isinstance(raw, (list, tuple)) else []
    result = []
    for index in range(TIMER_SLOTS):
        base = DEFAULT_TIMERS[index]
        item = items[index] if index < len(items) and isinstance(items[index], dict) else {}
        result.append({
            "enabled": _to_bool(item.get("enabled", base["enabled"])),
            "days": normalize_days(item.get("days", base["days"]), base["days"]),
            "start": parse_hhmm(item.get("start", base["start"]), base["start"]),
            "end": parse_hhmm(item.get("end", base["end"]), base["end"]),
        })
    return result


def describe_days(days):
    if not days:
        return "kein Tag"
    if days == [0, 1, 2, 3, 4]:
        return "Mo-Fr"
    if days == [0, 1, 2, 3, 4, 5, 6]:
        return "taeglich"
    if days == [5, 6]:
        return "Sa+So"
    return "+".join(WEEKDAYS[d] for d in days)


def _coerce(key, value):
    kind = SETTING_TYPES[key]
    if kind is list:
        return normalize_timers(value)
    if kind is bool:
        return _to_bool(value)
    if kind is int:
        value = int(float(str(value).strip()))   # vertraegt auch "20" und "20.0"
        lo, hi = LIMITS.get(key, (None, None))
        if lo is not None:
            value = max(lo, min(hi, value))
        return value
    value = str(value).strip()
    choices = SETTING_CHOICES.get(key)
    if choices and value not in choices:
        raise ValueError("%s: %r nicht erlaubt" % (key, value))
    return value


def update_settings(new_values, persist=True):
    changed = {}
    with _settings_lock:
        for key, raw in new_values.items():
            if key not in DEFAULT_SETTINGS:
                continue
            try:
                value = _coerce(key, raw)
            except (TypeError, ValueError):
                continue
            if SETTINGS[key] != value:
                SETTINGS[key] = value
                changed[key] = value
        snapshot = dict(SETTINGS)
    if changed and persist:
        save_config(snapshot)
    return changed


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        update_settings(data, persist=False)
        log("Einstellungen aus %s geladen." % os.path.basename(CONFIG_PATH))
    except Exception as exc:
        log("Konfiguration nicht lesbar (%s) - Standardwerte aktiv." % exc, "warn")


def save_config(snapshot):
    """Erst in eine Temporaerdatei, dann umbenennen: ein Absturz oder
    Stromausfall mitten im Schreiben hinterlaesst keine kaputte Konfiguration."""
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, CONFIG_PATH)
    except Exception as exc:
        log("Einstellungen konnten nicht gespeichert werden: %s" % exc, "warn")


# --------------------------------------------------------------------------
# HyperDeck Ethernet-Protokoll
# --------------------------------------------------------------------------

class DeckError(Exception):
    pass


class DeckReply(object):
    __slots__ = ("code", "header", "data", "lines")

    def __init__(self, code, header, data, lines):
        self.code = code
        self.header = header
        self.data = data
        self.lines = lines

    @property
    def ok(self):
        return 200 <= self.code < 300

    def get(self, key, default=None):
        return self.data.get(key.lower(), default)

    def hint(self):
        text = ERROR_HINTS.get(self.code)
        return " (%s)" % text if text else ""

    def __str__(self):
        return "%d %s" % (self.code, self.header)


class HyperDeck(object):
    """Eine dauerhafte Verbindung. Wird ausschliesslich vom Worker benutzt."""

    def __init__(self):
        self.sock = None
        self.buffer = b""
        self.ip = None
        self.port = None
        self.on_async = None        # Rueckruf fuer unaufgeforderte 5xx-Meldungen

    @property
    def connected(self):
        return self.sock is not None

    def connect(self, ip, port, timeout=5.0):
        self.close()
        self.ip, self.port = ip, port
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.sock = sock
        self.buffer = b""
        # Begruessungsblock "500 connection info:" abholen
        return self._read_reply(timeout=timeout, allow_async=True)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.buffer = b""

    # ---- Lesen -----------------------------------------------------------

    def _read_line(self, deadline):
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeckError("Zeitueberschreitung beim Lesen der Antwort")
            self.sock.settimeout(min(0.5, remaining))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                raise DeckError("Socket-Fehler: %s" % exc)
            if not chunk:
                raise DeckError("Verbindung wurde vom Deck geschlossen")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("utf-8", "replace").rstrip("\r")

    def _read_reply(self, timeout=6.0, allow_async=False):
        deadline = time.monotonic() + timeout
        while True:
            line = self._read_line(deadline)
            if not line.strip():
                continue
            match = re.match(r"^(\d{3})\s*(.*)$", line.strip())
            if match is None:
                continue  # Streugut ignorieren
            code = int(match.group(1))
            header = match.group(2).rstrip(":").strip()
            data, lines = {}, []
            if line.rstrip().endswith(":"):
                while True:
                    item = self._read_line(deadline)
                    if not item.strip():
                        break
                    item = item.strip()
                    lines.append(item)
                    if ":" in item:
                        key, value = item.split(":", 1)
                        data[key.strip().lower()] = value.strip()
            if 500 <= code <= 599 and not allow_async:
                # Unaufgeforderte Meldung mitten in einer Antwort: verarbeiten
                # und weiterlesen, bis die eigentliche Antwort kommt.
                self._deliver_async(DeckReply(code, header, data, lines))
                continue
            return DeckReply(code, header, data, lines)

    def _deliver_async(self, reply):
        if self.on_async is None:
            return
        try:
            self.on_async(reply)
        except Exception as exc:                # darf nie den Leser sprengen
            log("Fehler beim Verarbeiten einer Deck-Meldung: %s" % exc, "warn")

    def pending(self, wait=0.0):
        """True, wenn eine vollstaendige Zeile bereitliegt. Blockiert hoechstens
        `wait` Sekunden und holt dabei neue Daten vom Socket."""
        if b"\n" in self.buffer:
            return True
        if self.sock is None:
            return False
        try:
            ready = select.select([self.sock], [], [], max(0.0, wait))[0]
        except (OSError, ValueError):
            return False
        if not ready:
            return False
        try:
            chunk = self.sock.recv(4096)
        except socket.timeout:
            return False
        except OSError as exc:
            raise DeckError("Socket-Fehler: %s" % exc)
        if not chunk:
            raise DeckError("Verbindung wurde vom Deck geschlossen")
        self.buffer += chunk
        return b"\n" in self.buffer

    def pump(self, wait=0.25):
        """Wartet auf unaufgeforderte Meldungen und verarbeitet sie. Ersetzt in
        der Worker-Schleife das blosse Schlafen: liegt nichts an, wird die Zeit
        abgewartet - kommt etwas, reagiert die Anzeige sofort."""
        deadline = time.monotonic() + wait
        seen = 0
        while self.sock is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and seen:
                break
            if not self.pending(max(0.0, remaining)):
                break
            reply = self._read_reply(timeout=5.0, allow_async=True)
            if 500 <= reply.code <= 599:
                self._deliver_async(reply)
            seen += 1
        return seen

    # ---- Schreiben -------------------------------------------------------

    def command(self, text, timeout=6.0):
        if self.sock is None:
            raise DeckError("Keine Verbindung zum Deck")
        try:
            self.sock.sendall((text + "\r\n").encode("utf-8"))
        except OSError as exc:
            raise DeckError("Senden fehlgeschlagen: %s" % exc)
        return self._read_reply(timeout=timeout)


deck = HyperDeck()
jobs = queue.Queue()
shutdown = threading.Event()
_format_cooldown = {1: 0.0, 2: 0.0}
_last_autorecord_error = {"text": ""}
_autorecord_next_try = [0.0]
_last_slot_poll = [0.0]
_async_seen = {"transport": False, "slot": False}
_last_automation = [0.0]
_format_name_supported = {"value": True}


# --------------------------------------------------------------------------
# Aktionen
# --------------------------------------------------------------------------

def is_recording(status):
    return str(status).lower().startswith("record")


def get_recording_state():
    with _state_lock:
        return is_recording(STATE["status"]), STATE["active_slot"]


# Die Sicherung laeuft in einem eigenen Thread ueber FTP (Port 21) und hat mit
# der Steuerverbindung (9993) nichts zu tun.
backup = hyperdeck_backup.Mirror(get_settings, log, get_recording_state)

_poll_pending = threading.Event()


def request_poll():
    """Loest eine sofortige Abfrage aus - aber nur eine, egal wie oft gedrueckt wird."""
    if not _poll_pending.is_set():
        _poll_pending.set()
        jobs.put({"action": "poll"})


def apply_timecode_preset():
    """Setzt den Startzeitcode auf die PC-Uhrzeit.

    Wichtig: Das Deck benutzt den Preset nur, wenn sein Timecode-Eingang auch
    auf "preset" steht (Protokoll: configuration: timecode input:
    {external/embedded/internal/preset/clip}). Ohne diesen Schritt bleibt die
    Vorgabe wirkungslos und die Aufnahme laeuft mit dem Timecode aus dem
    Videosignal weiter."""
    reply = deck.command("configuration: timecode input: preset")
    if not reply.ok:
        log("Deck nimmt 'timecode input: preset' nicht an (%s%s) - der Startzeitcode "
            "bleibt vermutlich wirkungslos." % (reply, reply.hint()), "warn")

    stamp = datetime.datetime.now().strftime("%H:%M:%S:00")
    reply = deck.command("configuration: timecode preset: %s" % stamp)
    if not reply.ok:
        log("Timecode-Vorgabe abgelehnt (%s%s) - TC-Sync wird abgeschaltet."
            % (reply, reply.hint()), "warn")
        update_settings({"sync_timecode": False})
        return False
    log("Startzeitcode auf %s gesetzt." % stamp)
    return True


def do_record(manual=False):
    cfg = get_settings()
    if cfg["sync_timecode"]:
        apply_timecode_preset()

    reply = deck.command("record", timeout=10.0)
    if reply.ok:
        set_state(manual_stop=False)
        _last_autorecord_error["text"] = ""
        log("Aufnahme gestartet (%s)." % ("manuell" if manual else "Auto-Record"), "ok")
        read_transport()
        return True

    text = "Aufnahme abgelehnt: %s%s" % (reply, reply.hint())
    if manual or _last_autorecord_error["text"] != text:
        _last_autorecord_error["text"] = text
        log(text, "err")
    return False


def do_stop(manual=False):
    reply = deck.command("stop", timeout=10.0)
    if manual:
        set_state(manual_stop=True)
        log("Aufnahme gestoppt. Auto-Record ist verriegelt, bis du sie wieder freigibst.",
            "warn")
    elif reply.ok:
        log("Aufnahme gestoppt.", "warn")
    if not reply.ok:
        log("Stopp-Befehl beantwortet mit %s%s" % (reply, reply.hint()), "err")
    read_transport()
    return reply.ok


def do_format(slot_id, manual=False):
    cfg = get_settings()
    with _state_lock:
        active = STATE["active_slot"]
        recording = is_recording(STATE["status"])

    if recording and active == slot_id:
        log("Slot %d wird gerade beschrieben - Formatierung abgebrochen." % slot_id, "err")
        return False

    info = deck.command("slot info: slot id: %d" % slot_id)
    if not info.ok or (info.get("status") or "").lower() != "mounted":
        log("Slot %d: keine eingebundene Karte - Formatierung uebersprungen." % slot_id, "warn")
        return False

    filesystem = cfg["format_filesystem"] or "exFAT"
    name = (cfg["format_name"] or "").strip()
    use_name = bool(name) and _format_name_supported["value"]
    attempts = []
    if use_name:
        attempts.append("format: slot id: %d prepare: %s name: %s" % (slot_id, filesystem, name))
    attempts.append("format: slot id: %d prepare: %s" % (slot_id, filesystem))

    set_state(busy="Formatiere Slot %d" % slot_id)
    try:
        prepared = None
        for index, command in enumerate(attempts):
            reply = deck.command(command, timeout=20.0)
            if reply.code == 216:
                prepared = reply
                break
            if index == 0 and use_name:
                _format_name_supported["value"] = False
                log("Dieses Deck nimmt keinen Datentraegernamen an (%s%s) - "
                    "formatiere ohne Namen." % (reply, reply.hint()), "warn")
            else:
                log("Deck lehnt Formatierung ab: %s%s" % (reply, reply.hint()), "warn")

        if prepared is None:
            log("Slot %d: kein Format-Token erhalten, Formatierung abgebrochen." % slot_id, "err")
            return False

        token = prepared.get("token")
        if not token and prepared.lines:
            token = prepared.lines[0].split(":")[-1].strip()
        if not token:
            log("Slot %d: Token fehlt in der Antwort des Decks." % slot_id, "err")
            return False

        confirm = deck.command("format: confirm: %s" % token, timeout=300.0)
        if confirm.ok:
            _format_cooldown[slot_id] = time.monotonic()
            with _state_lock:
                STATE["last_format"][str(slot_id)] = datetime.datetime.now().strftime("%H:%M:%S")
            log("Slot %d ist formatiert und aufnahmebereit (%s)." % (slot_id, filesystem), "ok")
            return True

        log("Formatierung Slot %d fehlgeschlagen: %s%s" % (slot_id, confirm, confirm.hint()), "err")
        return False
    finally:
        set_state(busy="")


# --------------------------------------------------------------------------
# Abfrage und Automatik
# --------------------------------------------------------------------------

def slot_from_data(slot_id, data, previous=None):
    """Baut den Slot-Zustand aus einer Antwort. Fehlende Felder behalten ihren
    alten Wert - asynchrone Meldungen enthalten nicht immer alles."""
    info = dict(previous or {"id": slot_id, "status": "unknown",
                             "remaining_min": 0, "volume": ""})
    info["id"] = slot_id
    if data.get("status"):
        info["status"] = data["status"].lower()
    if data.get("volume name") is not None:
        info["volume"] = data.get("volume name") or ""
    if data.get("recording time") is not None:
        try:
            info["remaining_min"] = int(float(data["recording time"])) // 60
        except (TypeError, ValueError):
            pass
    return info


def apply_slot(data):
    """Uebernimmt eine Slot-Meldung (abgefragt oder unaufgefordert)."""
    raw = (data.get("slot id") or "").strip()
    if not raw.isdigit():
        return None
    slot_id = int(raw)
    with _state_lock:
        slots = copy.deepcopy(STATE["slots"])
        previous = next((s for s in slots if s["id"] == slot_id), None)
        info = slot_from_data(slot_id, data, previous)
        slots = [s for s in slots if s["id"] != slot_id] + [info]
        STATE["slots"] = sorted(slots, key=lambda s: s["id"])
    return info


def apply_transport(data):
    """Uebernimmt eine Transport-Meldung (abgefragt oder unaufgefordert)."""
    status = (data.get("status") or "unbekannt").lower()
    timecode = data.get("timecode") or data.get("display timecode") or "--:--:--:--"
    raw_slot = (data.get("slot id") or "").strip()
    active = int(raw_slot) if raw_slot.isdigit() and raw_slot != "0" else None
    set_state(status=status, timecode=timecode, active_slot=active)
    return status, active


def handle_async(reply):
    """Wird vom Leser aufgerufen, wenn das Deck von sich aus etwas meldet.
    Hier wird nur der Zustand nachgezogen - die Automatik laeuft danach in der
    Worker-Schleife, damit sich kein Befehl in einen anderen verschachtelt."""
    if reply.code == ASYNC_TRANSPORT:
        status, _active = apply_transport(reply.data)
        _async_seen["transport"] = True
        log_throttled("async-transport-%s" % status,
                      "Deck meldet: %s" % status, period=5)
    elif reply.code == ASYNC_SLOT:
        info = apply_slot(reply.data)
        if info is not None:
            _async_seen["slot"] = True


def enable_notifications():
    """Abonniert die Meldungen des Decks. Klappt das nicht, wird weiter
    abgefragt - die Automatik funktioniert in beiden Faellen."""
    ok = True
    for what in ("transport", "slot"):
        reply = deck.command("notify: %s: true" % what)
        if not reply.ok:
            ok = False
            log("Deck nimmt 'notify: %s' nicht an (%s%s) - es wird weiter "
                "regelmaessig abgefragt." % (what, reply, reply.hint()), "warn")
    set_state(notify=ok)
    if ok:
        log("Das Deck meldet Aenderungen ab jetzt von selbst.", "ok")
    return ok


def read_slot(slot_id):
    reply = deck.command("slot info: slot id: %d" % slot_id)
    if not reply.ok:
        return {"id": slot_id, "status": "empty", "remaining_min": 0, "volume": ""}
    return apply_slot(dict(reply.data, **{"slot id": str(slot_id)})) or {
        "id": slot_id, "status": "empty", "remaining_min": 0, "volume": ""}


def read_transport():
    """Transportstatus abfragen und in den Zustand schreiben."""
    transport = deck.command("transport info", timeout=8.0)
    if not transport.ok:
        log_throttled("transport", "Deck antwortet auf 'transport info' mit %s%s"
                      % (transport, transport.hint()), "err")
        return None
    return apply_transport(transport.data)


def poll_deck():
    result = read_transport()
    if result is None:
        return
    status, active = result

    # Transportstatus und Timecode sind billig und duerfen im Sekundentakt
    # kommen. Die Kartenabfrage ist teurer und aendert sich ohnehin langsam.
    now = time.monotonic()
    if now - _last_slot_poll[0] >= SLOT_POLL_MIN_S:
        _last_slot_poll[0] = now
        read_slot(1)
        read_slot(2)
    set_state(last_poll=datetime.datetime.now().strftime("%H:%M:%S"))

    with _state_lock:
        slots = copy.deepcopy(STATE["slots"])
    run_automation(status, active, slots)


def automation_tick():
    """Automatik mit dem aktuellen Zustand laufen lassen - nach einer Meldung
    des Decks, ohne auf die naechste Abfrage zu warten."""
    with _state_lock:
        status = STATE["status"]
        active = STATE["active_slot"]
        slots = copy.deepcopy(STATE["slots"])
    run_automation(status, active, slots)


def run_automation(status, active, slots):
    cfg = get_settings()
    loop_on = cfg["loop_record"]
    with _state_lock:
        manual_stop = STATE["manual_stop"]

    if not is_recording(status):
        # Ist der Timer scharf, entscheidet allein der Zeitplan ueber Start und
        # Stopp - sonst wuerde Auto-Record den Timer-Stopp sofort ueberrennen.
        if cfg["timer_enabled"]:
            return
        if loop_on and cfg["auto_record"] and not manual_stop:
            # Bei kurzem Abfrageintervall sonst jede Sekunde ein Startversuch.
            now = time.monotonic()
            if now < _autorecord_next_try[0]:
                return
            _autorecord_next_try[0] = now + AUTORECORD_RETRY_S
            log("Deck steht (Status: %s) - starte Aufnahme neu." % status, "warn")
            do_record(manual=False)
        return

    if not loop_on or not cfg["auto_loop"] or active not in (1, 2):
        return

    other = 2 if active == 1 else 1
    by_id = {slot["id"]: slot for slot in slots}
    remaining_active = by_id[active]["remaining_min"]
    remaining_other = by_id[other]["remaining_min"]

    if remaining_active > cfg["min_remaining_threshold"]:
        return

    if by_id[other]["status"] != "mounted":
        log_throttled(
            "no-card-%d" % other,
            "Restzeit Slot %d nur noch %d min, aber Slot %d ist leer. Endlosaufnahme nicht moeglich."
            % (active, remaining_active, other),
            "err",
        )
        return

    if remaining_other >= cfg["inactive_min_free"]:
        return  # auf der anderen Karte ist genug Platz, Deck rollt selbst weiter

    if time.monotonic() - _format_cooldown[other] < FORMAT_COOLDOWN_S:
        return

    if cfg["backup_enabled"] and cfg["backup_block_format"]:
        if not backup.is_clean(BACKUP_CLEAN_MAX_AGE_S, slot_id=other):
            backup.request_run(scope=backup.slot_folder(other),
                               reason="vor dem Leeren von Slot %d" % other)
            log_throttled("backup-wait-%d" % other,
                          "Slot %d wird erst geleert, wenn seine Aufnahmen gesichert sind - "
                          "Sicherung wird angestossen." % other, "warn", period=60)
            return

    log("Restzeit Slot %d: %d min - bereite Slot %d vor." % (active, remaining_active, other),
        "warn")
    do_format(other)


# --------------------------------------------------------------------------
# Timer-Aufnahme (Zeitsteuerung)
# --------------------------------------------------------------------------

_timer_state = {
    "window": None,         # Kennung des laufenden Termins, z. B. "0@2026-09-07"
    "index": None,          # Index (0..2) des laufenden Zeitplans
    "next_try": 0.0,        # Monotonic-Zeit fuer den naechsten Versuch
    "stop_until": 0.0,      # bis dahin wird ein verpasster Stopp nachgeholt
    "next_desc": 0.0,       # Drosselung der Klartext-Berechnung
}


def active_timers(cfg):
    """Nur die Eintraege, die laut Anzahl sichtbar und eingeschaltet sind."""
    count = max(1, min(TIMER_SLOTS, int(cfg.get("timer_count", 1))))
    result = []
    for index, entry in enumerate(cfg["timers"][:count]):
        if not entry["enabled"] or not entry["days"]:
            continue
        start = hhmm_to_minutes(entry["start"])
        end = hhmm_to_minutes(entry["end"])
        if start == end:            # Fenster ohne Laenge -> unbrauchbar
            continue
        result.append((index, entry, start, end))
    return result


def find_active_timer(cfg, now):
    """Liefert (index, eintrag, kennung) des laufenden Fensters, sonst dreimal None.
    Fenster mit Ende <= Start laufen ueber Mitternacht. Die Kennung enthaelt das
    Startdatum des Termins - dadurch ist der Montag-Termin ein anderer als der
    Dienstag-Termin desselben Zeitplans."""
    minute_of_day = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7
    for index, entry, start, end in active_timers(cfg):
        if end > start:
            if today in entry["days"] and start <= minute_of_day < end:
                return index, entry, "%d@%s" % (index, now.date())
        else:
            if today in entry["days"] and minute_of_day >= start:
                return index, entry, "%d@%s" % (index, now.date())
            if yesterday in entry["days"] and minute_of_day < end:
                return index, entry, "%d@%s" % (
                    index, now.date() - datetime.timedelta(days=1))
    return None, None, None


def next_timer_start(cfg, now):
    """Naechster Aufnahmebeginn als (datetime, index) - oder (None, None)."""
    best, best_index = None, None
    for offset in range(0, 8):
        day = (now + datetime.timedelta(days=offset)).date()
        for index, entry, start, _end in active_timers(cfg):
            if day.weekday() not in entry["days"]:
                continue
            when = datetime.datetime.combine(
                day, datetime.time(start // 60, start % 60))
            if when > now and (best is None or when < best):
                best, best_index = when, index
    return best, best_index


def timer_info_text(cfg, now, index, entry):
    if not cfg["timer_enabled"]:
        return "Timer aus"
    if index is not None:
        return "Autorecord %d nimmt auf, Fenster bis %s Uhr" % (index + 1, entry["end"])
    when, next_index = next_timer_start(cfg, now)
    if when is None:
        return "Kein Zeitplan aktiv"
    day = "heute" if when.date() == now.date() else (
        "morgen" if (when.date() - now.date()).days == 1 else WEEKDAYS[when.weekday()])
    return "Nächster Start: Autorecord %d %s um %s Uhr" % (
        next_index + 1, day, when.strftime("%H:%M"))


def run_timer(now=None):
    """Wird vom Worker haeufig aufgerufen. Startet und stoppt die Aufnahme
    punktgenau, unabhaengig vom Abfrageintervall."""
    cfg = get_settings()
    now = now or datetime.datetime.now()
    monotonic = time.monotonic()

    if not cfg["timer_enabled"]:
        with _state_lock:
            stale = (STATE["timer_active"] is not None
                     or STATE["timer_info"] != "Timer aus")
        if stale or _timer_state["window"] is not None:
            _timer_state.update({"window": None, "index": None,
                                 "next_try": 0.0, "stop_until": 0.0})
            set_state(timer_active=None, timer_info="Timer aus")
        return

    index, entry, window = find_active_timer(cfg, now)

    # ---- Terminwechsel -----------------------------------------------
    if window != _timer_state["window"]:
        previous_index = _timer_state["index"]
        _timer_state["window"] = window
        _timer_state["index"] = index
        _timer_state["next_try"] = 0.0
        _timer_state["next_desc"] = 0.0        # Klartext sofort neu berechnen
        if index is None:
            # Fenster ist zu Ende: der Stopp wird notfalls mehrfach nachgeholt.
            _timer_state["stop_until"] = monotonic + TIMER_STOP_GRACE_S
            log("Autorecord %d: Aufnahmefenster beendet - Aufnahme wird gestoppt."
                % ((previous_index or 0) + 1), "warn")
        else:
            _timer_state["stop_until"] = 0.0
            set_state(manual_stop=False)   # neuer Termin hebt die Verriegelung auf
            log("Autorecord %d: Aufnahmefenster %s-%s (%s) beginnt - Aufnahme startet."
                % (index + 1, entry["start"], entry["end"], describe_days(entry["days"])),
                "ok")
        set_state(timer_active=(index + 1) if index is not None else None)

    # ---- Klartext fuer die Oberflaeche (gedrosselt, da 8-Tage-Suche) ---
    if monotonic >= _timer_state["next_desc"]:
        _timer_state["next_desc"] = monotonic + 5.0
        set_state(timer_info=timer_info_text(cfg, now, index, entry))

    with _state_lock:
        recording = is_recording(STATE["status"])
        manual_stop = STATE["manual_stop"]

    if monotonic < _timer_state["next_try"]:
        return

    if index is not None:
        # Innerhalb des Fensters: Aufnahme sicherstellen (auch nach Stromausfall
        # oder Verbindungsabbruch), aber einen manuellen Stopp respektieren.
        if recording or manual_stop:
            return
        _timer_state["next_try"] = monotonic + TIMER_RETRY_S
        do_record(manual=False)
        return

    # Ausserhalb aller Fenster wird nur ein frisch verpasster Stopp nachgeholt.
    # Eine spaetere Aufnahme von Hand bleibt unangetastet.
    if recording and monotonic < _timer_state["stop_until"]:
        _timer_state["next_try"] = monotonic + TIMER_RETRY_S
        do_stop(manual=False)
    elif not recording:
        _timer_state["stop_until"] = 0.0


# --------------------------------------------------------------------------
# Worker-Thread: einziger Besitzer der Deck-Verbindung
# --------------------------------------------------------------------------

def handle_job(job):
    action = job.get("action")
    if action == "record":
        # Ein bewusster Start hebt einen noch offenen Timer-Stopp auf.
        _timer_state["stop_until"] = 0.0
        _timer_state["next_try"] = 0.0
        do_record(manual=True)
    elif action == "stop":
        _timer_state["stop_until"] = 0.0
        _timer_state["next_try"] = time.monotonic() + TIMER_RETRY_S
        do_stop(manual=True)
    elif action == "format":
        try:
            slot_id = int(job.get("slot_id"))
        except (TypeError, ValueError):
            return
        if slot_id in (1, 2):
            do_format(slot_id, manual=True)
    elif action == "reconnect":
        log("Verbindung wird auf Wunsch neu aufgebaut.")
        deck.close()
        set_state(connected=False, status="offline")
    elif action == "poll":
        _poll_pending.clear()   # loest nur die sofortige Abfrage aus


def worker_loop():
    last_poll = -1e9
    backoff = 2.0
    log("Ueberwachung gestartet.")

    while not shutdown.is_set():
        cfg = get_settings()

        if not deck.connected:
            set_state(busy="Verbinde", status="offline")
            try:
                deck.on_async = handle_async
                banner = deck.connect(cfg["deck_ip"], cfg["deck_port"])
                model = (banner.get("model") if banner else None) or "HyperDeck"
                set_state(connected=True, connection_error="", busy="", device=model)
                log("Verbunden mit %s (%s:%d)." % (model, cfg["deck_ip"], cfg["deck_port"]), "ok")
                enable_notifications()
                last_poll = -1e9
                backoff = 2.0
            except Exception as exc:
                deck.close()
                set_state(connected=False, busy="", status="offline", notify=False,
                          connection_error=str(exc), seconds_until_check=0)
                log_throttled("connect", "Keine Verbindung zu %s:%d - %s"
                              % (cfg["deck_ip"], cfg["deck_port"], exc), "err", period=30)
                shutdown.wait(backoff)
                backoff = min(backoff * 1.5, 15.0)
                continue

        try:
            force_poll = False
            while deck.connected:
                try:
                    job = jobs.get_nowait()
                except queue.Empty:
                    break
                handle_job(job)
                force_poll = True

            now = time.monotonic()
            interval = cfg["check_interval"]
            if force_poll or now - last_poll >= interval:
                if deck.connected:
                    poll_deck()
                    last_poll = time.monotonic()

            # Der Timer wird oft geprueft (nicht nur beim Poll), damit er die
            # eingestellte Uhrzeit sekundengenau trifft.
            if deck.connected:
                run_timer()

            remaining = interval - (time.monotonic() - last_poll)
            set_state(seconds_until_check=max(0, int(round(remaining))))

            # Auf Meldungen des Decks warten statt bloss zu schlafen. Kommt
            # eine, greift die Automatik sofort - nicht erst beim naechsten Poll.
            if deck.connected:
                deck.pump(0.25)
                announced = _async_seen["transport"] or _async_seen["slot"]
                now = time.monotonic()
                # Zusaetzlich einmal pro Sekunde nachsehen: Wiederholsperren
                # (Auto-Record, Timer) duerfen einen Ausloeser nicht verschlucken.
                if announced or now - _last_automation[0] >= 1.0:
                    _async_seen["transport"] = _async_seen["slot"] = False
                    _last_automation[0] = now
                    automation_tick()

        except DeckError as exc:
            log("Verbindung gestoert: %s - baue neu auf." % exc, "warn")
            deck.close()
            set_state(connected=False, busy="", status="offline", notify=False,
                      connection_error=str(exc))
            shutdown.wait(1.0)
            continue
        except OSError as exc:
            log("Netzwerkfehler: %s - baue neu auf." % exc, "warn")
            deck.close()
            set_state(connected=False, busy="", status="offline", notify=False,
                      connection_error=str(exc))
            shutdown.wait(1.0)
            continue
        except Exception as exc:  # darf den Thread niemals beenden
            log("Unerwarteter Fehler im Worker: %s" % exc, "err")
            shutdown.wait(1.0)

        if not deck.connected:
            shutdown.wait(0.25)     # sonst hat pump() bereits gewartet


# --------------------------------------------------------------------------
# Weboberflaeche
# --------------------------------------------------------------------------



app = Flask(__name__)


@app.after_request
def no_cache(response):
    """Verhindert, dass der Browser eine alte Oberflaeche weiterbenutzt."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


UI_DIR = os.path.join(APP_DIR, "ui")
_page_cache = {"html": None}


def render_page():
    """Liest ui/index.html einmalig ein und setzt die Version ein."""
    if _page_cache["html"] is None:
        path = os.path.join(UI_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as fh:
            _page_cache["html"] = fh.read().replace("{{APP_VERSION}}", APP_VERSION)
    return _page_cache["html"]


def check_ui_files():
    """Bricht mit klarer Meldung ab, wenn der Ordner ui/ nicht mitkopiert wurde."""
    missing = [name for name in ("index.html", "style.css", "app.js")
               if not os.path.isfile(os.path.join(UI_DIR, name))]
    if missing:
        raise SystemExit(
            "Der Ordner 'ui' neben hyperdeck_control.py ist unvollstaendig (fehlt: %s).\n"
            "Bitte den kompletten Programmordner kopieren, nicht nur die .py-Datei."
            % ", ".join(missing))


@app.route("/")
def index():
    return Response(render_page(), mimetype="text/html")


@app.route("/ui/<path:filename>")
def ui_file(filename):
    return send_from_directory(UI_DIR, filename)


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/api/status")
def api_status():
    with _state_lock:
        snapshot = copy.deepcopy(STATE)
    payload = get_settings()
    payload.update(snapshot)

    # Log nur als Nachschub liefern: der Browser fragt im Sekundentakt und soll
    # nicht jedes Mal 250 Zeilen erneut uebertragen bekommen.
    with _log_lock:
        entries = list(_logs)
    newest = entries[-1]["id"] if entries else 0
    oldest = entries[0]["id"] if entries else 0
    reset = True
    since_raw = request.args.get("since")
    if since_raw is not None:
        try:
            since = int(since_raw)
        except (TypeError, ValueError):
            since = -1
        if oldest - 1 <= since <= newest:
            entries = [e for e in entries if e["id"] > since]
            reset = False

    payload["logs"] = entries
    payload["log_seq"] = newest
    payload["log_reset"] = reset
    payload["app_version"] = APP_VERSION
    payload["uptime_s"] = int(time.time() - STARTED_AT)
    payload["backup"] = backup.snapshot()
    for key in SECRET_KEYS:             # Passwoerter verlassen den Dienst nie
        payload[key + "_set"] = bool(payload.get(key))
        payload[key] = ""
    return jsonify(payload)


@app.route("/api/log.txt")
def api_logfile():
    """Die komplette Logdatei zum Nachlesen oder Weitergeben."""
    parts = []
    for name in (LOG_PATH + ".1", LOG_PATH):     # aeltere Generation zuerst
        if os.path.exists(name):
            with open(name, "r", encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read())
    return Response("".join(parts) or "Noch keine Logdatei vorhanden.\n",
                    mimetype="text/plain; charset=utf-8")


@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "resume_auto":
        set_state(manual_stop=False)
        log("Auto-Record wieder freigegeben.", "ok")
        request_poll()
        return jsonify(ok=True)

    if action == "poll":
        request_poll()
        return jsonify(ok=True)

    # ---- Sicherung: laeuft im eigenen Thread, braucht die Deck-Queue nicht
    if action == "backup":
        slot = data.get("slot_id")
        scope, reason = None, "manuell"
        if str(slot) in ("1", "2"):
            scope = backup.slot_folder(int(slot))
            reason = "Slot %s" % slot
            if scope is None:
                log("Slot %s: Ordner am Deck noch nicht bekannt - es wird alles gesichert."
                    % slot, "warn")
        started = backup.request_run(scope=scope, reason=reason)
        return jsonify(ok=started, error=None if started else "Sicherung läuft bereits")
    if action == "backup_test":
        started = backup.request_test()
        return jsonify(ok=started, error=None if started else "Sicherung läuft bereits")
    if action == "backup_cancel":
        backup.cancel()
        return jsonify(ok=True)

    if action not in ("record", "stop", "format", "reconnect"):
        return jsonify(ok=False, error="Unbekannter Befehl"), 400
    if jobs.qsize() > 50:
        return jsonify(ok=False, error="Zu viele Befehle in der Warteschlange"), 429

    jobs.put(data)
    return jsonify(ok=True)


def describe_change(key, value):
    """Kurztext fuers Log - die Timer-Liste wuerde sonst das Log zumuellen."""
    if key == "timers":
        parts = []
        for index, entry in enumerate(value):
            if entry["enabled"]:
                parts.append("%d: %s %s-%s" % (index + 1, describe_days(entry["days"]),
                                               entry["start"], entry["end"]))
        return "Zeitpläne [%s]" % ("; ".join(parts) if parts else "keiner aktiv")
    if key in SECRET_KEYS:
        return "%s=%s" % (key, "***" if value else "gelöscht")
    return "%s=%s" % (key, value)


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(silent=True) or {}
    # Passwortfelder: leer = unveraendert lassen, "-" = loeschen
    for key in SECRET_KEYS:
        if key in data:
            value = str(data[key])
            if value == "":
                del data[key]
            elif value == "-":
                data[key] = ""
    changed = update_settings(data)
    if changed:
        log("Einstellungen geändert: %s"
            % ", ".join(describe_change(k, v) for k, v in sorted(changed.items())))
        if "deck_ip" in changed or "deck_port" in changed:
            jobs.put({"action": "reconnect"})
        elif not all(k.startswith("backup_") or k.startswith("deck_ftp") for k in changed):
            request_poll()
    settings = get_settings()
    for key in SECRET_KEYS:
        settings[key] = ""
    return jsonify(ok=True, changed={k: ("***" if k in SECRET_KEYS else v)
                                      for k, v in changed.items()}, settings=settings)


# --------------------------------------------------------------------------
# Start
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HyperDeck Web Control")
    parser.add_argument("--ip", help="IP-Adresse des HyperDeck")
    parser.add_argument("--port", type=int, help="Protokoll-Port des HyperDeck (Standard 9993)")
    parser.add_argument("--interval", type=int, help="Abfrageintervall in Sekunden")
    parser.add_argument("--web-port", type=int, default=5000, help="Port der Weboberflaeche")
    parser.add_argument("--bind", default="0.0.0.0", help="Adresse, auf der der Webserver lauscht")
    parser.add_argument("--no-browser", action="store_true",
                        help="Browser beim Start nicht automatisch oeffnen")
    parser.add_argument("--version", action="version", version="HyperDeck Web Control " + APP_VERSION)
    args = parser.parse_args()

    check_ui_files()
    setup_file_log()
    load_config()
    log("HyperDeck Web Control %s gestartet." % APP_VERSION)
    overrides = {}
    if args.ip:
        overrides["deck_ip"] = args.ip
    if args.port:
        overrides["deck_port"] = args.port
    if args.interval:
        overrides["check_interval"] = args.interval
    if overrides:
        update_settings(overrides)

    worker = threading.Thread(target=worker_loop, name="hyperdeck-worker", daemon=True)
    worker.start()
    backup.start()

    cfg = get_settings()
    url = "http://localhost:%d" % args.web_port
    print("")
    print("=" * 62)
    print("  HYPERDECK WEB CONTROL  v%s" % APP_VERSION)
    print("  Deck:    %s:%d" % (cfg["deck_ip"], cfg["deck_port"]))
    print("  Browser: %s  (oder LAN-IP dieses Rechners)" % url)
    print("  Loop-Record: %s   Timer: %s" % (
        "ein" if cfg["loop_record"] else "aus",
        "ein" if cfg["timer_enabled"] else "aus"))
    for index, entry in enumerate(cfg["timers"][:cfg["timer_count"]]):
        print("    Autorecord %d: %s  %s-%s Uhr  [%s]" % (
            index + 1, describe_days(entry["days"]), entry["start"], entry["end"],
            "aktiv" if entry["enabled"] else "aus"))
    target = hyperdeck_backup.make_sink(cfg).describe() or "kein Ziel eingestellt"
    print("  Sicherung: %s -> %s" % (
        ("alle %d min" % cfg["backup_interval"]) if cfg["backup_enabled"] else "aus", target))
    print("  Logdatei:  %s" % LOG_PATH)
    print("=" * 62)
    print("  Dieses Fenster bitte offen lassen. Beenden mit Strg + C.")
    print("=" * 62)
    print("")

    if not args.no_browser:
        open_browser_later(url)

    try:
        serve_forever(args.bind, args.web_port)
    finally:
        shutdown.set()
        backup.stop()
        deck.close()


def serve_forever(host, port):
    """waitress ist ein richtiger Produktionsserver (mehrere Threads, kein
    Entwicklungs-Warnhinweis, keine Anfrageflut in der Konsole). Fehlt das
    Paket, laeuft der eingebaute Flask-Server als Ersatz."""
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        log("Paket 'waitress' fehlt - der Flask-Entwicklungsserver wird benutzt "
            "(pip install waitress).", "warn")
        try:
            app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)
        except OSError as exc:
            print("\nWebserver konnte Port %d nicht oeffnen: %s\n"
                  "Laeuft das Programm vielleicht schon? Sonst --web-port aendern." % (port, exc))
            raise
        return
    try:
        waitress_serve(app, host=host, port=port, threads=8,
                       ident="HyperDeck Web Control", _quiet=True)
    except OSError as exc:
        print("\nWebserver konnte Port %d nicht oeffnen: %s\n"
              "Laeuft das Programm vielleicht schon? Sonst --web-port aendern." % (port, exc))
        raise


def open_browser_later(url, delay=1.5):
    """Oeffnet die Oberflaeche, sobald der Webserver oben ist."""
    def worker():
        time.sleep(delay)
        try:
            webbrowser.open_new_tab(url)
            log("Browser wurde mit %s geoeffnet." % url)
        except Exception as exc:
            log("Browser konnte nicht geoeffnet werden (%s) - bitte %s manuell aufrufen."
                % (exc, url), "warn")
    threading.Thread(target=worker, name="browser-opener", daemon=True).start()


def pause_before_exit():
    """Haelt ein doppelt angeklicktes Konsolenfenster offen, damit die
    Fehlermeldung lesbar bleibt. start.bat setzt HYPERDECK_NO_PAUSE=1."""
    if os.environ.get("HYPERDECK_NO_PAUSE"):
        return
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return
        input("\nZum Schliessen dieses Fensters die Eingabetaste druecken ... ")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBeendet.")
    except Exception:
        traceback.print_exc()
        print("")
        print("!!! Der Dienst wurde wegen des oben genannten Fehlers beendet. !!!")
        pause_before_exit()
        sys.exit(1)
