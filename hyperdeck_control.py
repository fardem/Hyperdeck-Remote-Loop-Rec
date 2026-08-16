#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HyperDeck Studio - Web Control
==============================
Fernsteuerung fuer Blackmagic HyperDeck ueber das Ethernet-Protokoll (Port 9993).

Funktionen
  * Auto-Record .... startet die Aufnahme automatisch, wenn das Deck steht
  * Auto-Loop ...... formatiert rechtzeitig die inaktive Karte -> Endlosaufnahme
  * Manueller STOP bleibt STOP. Er setzt eine Verriegelung, die Auto-Record
    blockiert, bis im Web-UI wieder RECORD (oder "Auto-Record freigeben")
    gedrueckt wird.
  * Alle wichtigen Parameter sind im Browser aenderbar und werden in
    hyperdeck_config.json gespeichert.

Architektur (das war die Ursache der Haenger im alten Script)
  * GENAU EIN Thread spricht mit dem Deck, ueber GENAU EINE dauerhafte
    TCP-Verbindung. Die Flask-Endpunkte reden nie selbst mit dem Deck,
    sie legen nur Auftraege in eine Queue -> das Web-UI kann nicht blockieren
    und zwei gleichzeitige Sockets koennen sich nicht mehr ins Gehege kommen.
  * Der Protokoll-Parser arbeitet zeilenbasiert nach Antwortcode statt mit
    time.sleep() und Textsuche. Asynchrone Meldungen (5xx) werden erkannt und
    uebersprungen, Mehrzeilenbloecke werden bis zur Leerzeile gelesen.
  * Jeder Fehler fuehrt zu sauberem Reconnect mit Backoff statt zum Stillstand.

Start:
    pip install flask
    python3 hyperdeck_control.py --ip 172.17.100.119 --web-port 5000
"""

import argparse
import copy
import datetime
import json
import os
import queue
import re
import socket
import threading
import time

from flask import Flask, Response, jsonify, request

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "hyperdeck_config.json")

DEFAULT_SETTINGS = {
    "deck_ip": "172.17.100.119",
    "deck_port": 9993,
    "check_interval": 20,           # Sekunden zwischen zwei Deck-Abfragen
    "min_remaining_threshold": 5,   # ab dieser Restzeit (min) wird vorbereitet
    "inactive_min_free": 15,        # inaktive Karte formatieren, wenn weniger frei
    "auto_record": True,
    "auto_loop": True,
    "sync_timecode": True,          # Timecode beim Start auf Uhrzeit setzen
    "format_filesystem": "exFAT",   # exFAT oder HFS+
    "format_name": "LoopDump",
}

SETTING_TYPES = {
    "deck_ip": str,
    "deck_port": int,
    "check_interval": int,
    "min_remaining_threshold": int,
    "inactive_min_free": int,
    "auto_record": bool,
    "auto_loop": bool,
    "sync_timecode": bool,
    "format_filesystem": str,
    "format_name": str,
}

LIMITS = {
    "deck_port": (1, 65535),
    "check_interval": (5, 3600),
    "min_remaining_threshold": (1, 240),
    "inactive_min_free": (1, 2000),
}

UI_VERSION = "2.1"          # muss mit UI_VERSION im HTML uebereinstimmen
FORMAT_COOLDOWN_S = 180     # Sperre pro Slot nach einer Formatierung
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

SETTINGS = dict(DEFAULT_SETTINGS)
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
}
_state_lock = threading.RLock()

_logs = []
_log_lock = threading.Lock()
_throttle = {}


def log(msg, level="info"):
    entry = {
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "msg": str(msg),
        "level": level,
    }
    print("[%s] %s" % (entry["time"], entry["msg"]), flush=True)
    with _log_lock:
        _logs.append(entry)
        del _logs[:-LOG_MAX]


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
        return dict(SETTINGS)


def _coerce(key, value):
    kind = SETTING_TYPES[key]
    if kind is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes", "ja")
        return bool(value)
    if kind is int:
        value = int(value)
        lo, hi = LIMITS.get(key, (None, None))
        if lo is not None:
            value = max(lo, min(hi, value))
        return value
    return str(value).strip()


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
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, ensure_ascii=False)
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
                continue  # asynchrone Statusmeldung, nicht unsere Antwort
            return DeckReply(code, header, data, lines)

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
_format_name_supported = {"value": True}


# --------------------------------------------------------------------------
# Aktionen
# --------------------------------------------------------------------------

def is_recording(status):
    return str(status).lower().startswith("record")


def do_record(manual=False):
    cfg = get_settings()
    if cfg["sync_timecode"]:
        stamp = datetime.datetime.now().strftime("%H:%M:%S:00")
        reply = deck.command("configuration: timecode preset: %s" % stamp)
        if not reply.ok:
            log("Timecode-Vorgabe abgelehnt (%s%s) - TC-Sync wird abgeschaltet."
                % (reply, reply.hint()), "warn")
            update_settings({"sync_timecode": False})

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

def read_slot(slot_id):
    reply = deck.command("slot info: slot id: %d" % slot_id)
    if not reply.ok:
        return {"id": slot_id, "status": "empty", "remaining_min": 0, "volume": ""}
    try:
        seconds = int(float(reply.get("recording time") or 0))
    except (TypeError, ValueError):
        seconds = 0
    return {
        "id": slot_id,
        "status": (reply.get("status") or "unknown").lower(),
        "remaining_min": seconds // 60,
        "volume": reply.get("volume name") or "",
    }


def read_transport():
    """Transportstatus lesen und sofort in den Zustand schreiben."""
    transport = deck.command("transport info", timeout=8.0)
    if not transport.ok:
        log_throttled("transport", "Deck antwortet auf 'transport info' mit %s%s"
                      % (transport, transport.hint()), "err")
        return None

    status = (transport.get("status") or "unbekannt").lower()
    timecode = transport.get("timecode") or transport.get("display timecode") or "--:--:--:--"
    raw_slot = (transport.get("slot id") or "").strip()
    active = int(raw_slot) if raw_slot.isdigit() and raw_slot != "0" else None
    set_state(status=status, timecode=timecode, active_slot=active)
    return status, active


def poll_deck():
    result = read_transport()
    if result is None:
        return
    status, active = result

    slots = [read_slot(1), read_slot(2)]
    set_state(slots=slots, last_poll=datetime.datetime.now().strftime("%H:%M:%S"))

    run_automation(status, active, slots)


def run_automation(status, active, slots):
    cfg = get_settings()
    with _state_lock:
        manual_stop = STATE["manual_stop"]

    if not is_recording(status):
        if cfg["auto_record"] and not manual_stop:
            log("Deck steht (Status: %s) - starte Aufnahme neu." % status, "warn")
            do_record(manual=False)
        return

    if not cfg["auto_loop"] or active not in (1, 2):
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

    log("Restzeit Slot %d: %d min - bereite Slot %d vor." % (active, remaining_active, other),
        "warn")
    do_format(other)


# --------------------------------------------------------------------------
# Worker-Thread: einziger Besitzer der Deck-Verbindung
# --------------------------------------------------------------------------

def handle_job(job):
    action = job.get("action")
    if action == "record":
        do_record(manual=True)
    elif action == "stop":
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
    # "poll" braucht nichts zu tun, es loest nur eine sofortige Abfrage aus


def worker_loop():
    last_poll = -1e9
    backoff = 2.0
    log("Ueberwachung gestartet.")

    while not shutdown.is_set():
        cfg = get_settings()

        if not deck.connected:
            set_state(busy="Verbinde", status="offline")
            try:
                banner = deck.connect(cfg["deck_ip"], cfg["deck_port"])
                model = (banner.get("model") if banner else None) or "HyperDeck"
                set_state(connected=True, connection_error="", busy="", device=model)
                log("Verbunden mit %s (%s:%d)." % (model, cfg["deck_ip"], cfg["deck_port"]), "ok")
                last_poll = -1e9
                backoff = 2.0
            except Exception as exc:
                deck.close()
                set_state(connected=False, busy="", status="offline",
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
            interval = get_settings()["check_interval"]
            if force_poll or now - last_poll >= interval:
                if deck.connected:
                    poll_deck()
                    last_poll = time.monotonic()

            remaining = interval - (time.monotonic() - last_poll)
            set_state(seconds_until_check=max(0, int(round(remaining))))

        except DeckError as exc:
            log("Verbindung gestoert: %s - baue neu auf." % exc, "warn")
            deck.close()
            set_state(connected=False, busy="", status="offline", connection_error=str(exc))
            shutdown.wait(1.0)
            continue
        except OSError as exc:
            log("Netzwerkfehler: %s - baue neu auf." % exc, "warn")
            deck.close()
            set_state(connected=False, busy="", status="offline", connection_error=str(exc))
            shutdown.wait(1.0)
            continue
        except Exception as exc:  # darf den Thread niemals beenden
            log("Unerwarteter Fehler im Worker: %s" % exc, "err")
            shutdown.wait(1.0)

        shutdown.wait(0.25)


# --------------------------------------------------------------------------
# Weboberflaeche
# --------------------------------------------------------------------------

HTML_PAGE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>HyperDeck Control</title>
<style>
:root{
  --bg:#08090c;
  --panel:#111319;
  --panel-hi:#161922;
  --line:#22262f;
  --line-soft:#1a1d25;
  --txt:#e7eaf0;
  --dim:#8a92a2;
  --dim2:#5c6472;
  --rec:#ff3b30;
  --ok:#35d07f;
  --warn:#ffb020;
  --acc:#5b8cff;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Roboto Mono",monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{
  background:var(--bg);
  color:var(--txt);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,sans-serif;
  font-size:15px;line-height:1.45;
  padding:16px;display:flex;justify-content:center;
}
.wrap{width:100%;max-width:920px;display:flex;flex-direction:column;gap:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim2);
  font-weight:600;margin-bottom:10px}

/* Kopfzeile */
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.top h1{font-size:16px;font-weight:650;letter-spacing:-.01em}
.host{font-family:var(--mono);font-size:12px;color:var(--dim2)}
.link{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--dim2);flex:none}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px rgba(53,208,127,.15)}
.dot.off{background:var(--rec);box-shadow:0 0 0 3px rgba(255,59,48,.15)}

/* Tally + Timecode */
.stage{display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:center}
@media(max-width:560px){.stage{grid-template-columns:1fr;gap:12px}}
.tally{
  border:1px solid var(--line);border-radius:12px;padding:14px 16px;min-width:132px;
  background:var(--panel-hi);text-align:center
}
.tally.live{border-color:rgba(255,59,48,.55);background:rgba(255,59,48,.10)}
.tally .word{font-size:19px;font-weight:700;letter-spacing:.12em}
.tally.live .word{color:var(--rec)}
.tally .sub{font-size:11px;color:var(--dim2);letter-spacing:.08em;text-transform:uppercase;margin-top:2px}
.tally.live .word::before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%;
  background:var(--rec);margin-right:9px;vertical-align:middle;animation:blink 1.4s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.tc{font-family:var(--mono);font-size:clamp(34px,9vw,54px);font-weight:600;letter-spacing:.02em;
  font-variant-numeric:tabular-nums;line-height:1}
.tc-label{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim2);margin-top:6px}

/* Hinweisleisten */
.notice{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
  border-radius:12px;padding:12px 16px;font-size:14px}
.notice.lock{background:rgba(255,176,32,.10);border:1px solid rgba(255,176,32,.4);color:#ffd98a}
.notice.busy{background:rgba(91,140,255,.10);border:1px solid rgba(91,140,255,.4);color:#bcd0ff}
.notice.err{background:rgba(255,59,48,.10);border:1px solid rgba(255,59,48,.4);color:#ffb3ae}

/* Karten-Slots */
.slots{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:560px){.slots{grid-template-columns:1fr}}
.slot{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.slot.active{border-color:rgba(53,208,127,.5)}
.slot.low{border-color:rgba(255,176,32,.55)}
.slot-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.slot-name{font-size:14px;font-weight:650}
.tag{font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;
  padding:3px 8px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
.tag.rec{color:var(--ok);border-color:rgba(53,208,127,.5)}
.mins{font-family:var(--mono);font-size:32px;font-weight:600;font-variant-numeric:tabular-nums;
  margin:10px 0 2px}
.mins small{font-family:inherit;font-size:12px;font-weight:400;color:var(--dim2);margin-left:6px;
  letter-spacing:.06em}
.bar{height:5px;border-radius:3px;background:var(--line-soft);overflow:hidden;margin:10px 0 10px}
.bar span{display:block;height:100%;background:var(--acc);transition:width .4s ease}
.bar span.low{background:var(--warn)}
.meta{font-size:12px;color:var(--dim2);display:flex;justify-content:space-between;gap:8px}

/* Bedienung */
.buttons{display:flex;gap:10px;flex-wrap:wrap}
button{font:inherit;font-weight:650;color:var(--txt);background:var(--panel-hi);
  border:1px solid var(--line);border-radius:10px;padding:11px 18px;cursor:pointer;
  transition:filter .15s,transform .06s}
button:hover{filter:brightness(1.25)}
button:active{transform:translateY(1px)}
button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
button:disabled{opacity:.45;cursor:not-allowed}
.b-rec{background:var(--rec);border-color:var(--rec);color:#fff}
.b-warn{background:rgba(255,176,32,.14);border-color:rgba(255,176,32,.45);color:#ffd98a}
.b-ghost{background:transparent}
.b-sm{padding:7px 12px;font-size:13px;font-weight:600}

/* Schalter */
.switches{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin-top:14px}
.sw{display:flex;align-items:center;justify-content:space-between;gap:12px;
  background:var(--panel-hi);border:1px solid var(--line);border-radius:10px;padding:11px 14px}
.sw .t{font-size:13.5px;font-weight:600}
.sw .d{font-size:11.5px;color:var(--dim2);margin-top:1px}
.track{position:relative;width:42px;height:24px;border-radius:999px;background:#2a2f3a;flex:none;
  cursor:pointer;transition:background .18s}
.track::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;
  background:#fff;transition:transform .18s}
.track.on{background:var(--ok)}
.track.on::after{transform:translateX(18px)}
input[type=checkbox]{position:absolute;opacity:0;width:0;height:0}
input[type=checkbox]:focus-visible + .track{outline:2px solid var(--acc);outline-offset:2px}

/* Einstellungen */
.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.field{display:flex;flex-direction:column;gap:6px}
.field label{font-size:12px;color:var(--dim)}
.field input,.field select{background:#0c0e13;border:1px solid var(--line);color:var(--txt);
  border-radius:9px;padding:10px 12px;font:inherit;font-family:var(--mono);font-size:14px}
.field input:focus,.field select:focus{outline:none;border-color:var(--acc)}
.hint{font-size:12px;color:var(--dim2);margin-top:12px}
.row{display:flex;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap}

/* Countdown */
.poll{display:flex;align-items:center;gap:12px;margin-top:14px;font-size:12.5px;color:var(--dim)}
.poll .track2{flex:1;height:4px;border-radius:2px;background:var(--line-soft);overflow:hidden;min-width:80px}
.poll .track2 span{display:block;height:100%;background:var(--dim2);transition:width .9s linear}

/* Log */
.log{background:#0a0c10;border:1px solid var(--line-soft);border-radius:10px;padding:10px 12px;
  height:190px;overflow-y:auto;font-family:var(--mono);font-size:12.5px;line-height:1.6}
.log div{white-space:pre-wrap;word-break:break-word}
.log .t{color:var(--dim2)}
.log .info{color:#c3cad6}
.log .ok{color:var(--ok)}
.log .warn{color:var(--warn)}
.log .err{color:#ff7b73}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<div class="wrap">

  <div class="panel">
    <div class="top">
      <div>
        <h1 id="device">HyperDeck Control</h1>
        <div class="host" id="host">--</div>
      </div>
      <div class="link"><span class="dot" id="dot"></span><span id="linkTxt">Verbinde …</span></div>
    </div>

    <div class="stage" style="margin-top:18px">
      <div class="tally" id="tally">
        <div class="word" id="tallyWord">--</div>
        <div class="sub" id="tallySub">Status</div>
      </div>
      <div>
        <div class="tc" id="tc">--:--:--:--</div>
        <div class="tc-label" id="tcLabel">Timecode</div>
      </div>
    </div>

    <div class="poll">
      <span>Nächste Abfrage in <b id="cd" style="color:var(--txt);font-family:var(--mono)">--</b> s</span>
      <div class="track2"><span id="cdBar" style="width:100%"></span></div>
      <span id="lastPoll"></span>
    </div>
  </div>

  <div id="noticeStale" class="notice err" hidden>
    <span>Der Browser zeigt eine veraltete Oberfläche. Lade die Seite mit Strg+Shift+R neu.</span>
    <button class="b-sm" onclick="location.reload(true)">Neu laden</button>
  </div>
  <div id="noticeLock" class="notice lock" hidden>
    <span>Manuell gestoppt. Auto-Record bleibt aus, bis du ihn freigibst.</span>
    <button class="b-warn b-sm" onclick="send('resume_auto')">Auto-Record freigeben</button>
  </div>
  <div id="noticeBusy" class="notice busy" hidden><span id="busyTxt"></span></div>
  <div id="noticeErr" class="notice err" hidden><span id="errTxt"></span></div>

  <div class="slots" id="slots"></div>

  <div class="panel">
    <div class="eyebrow">Bedienung</div>
    <div class="buttons">
      <button class="b-rec" onclick="send('record')">Aufnahme starten</button>
      <button onclick="send('stop')">Aufnahme stoppen</button>
      <button class="b-ghost" onclick="send('poll')">Jetzt abfragen</button>
      <button class="b-ghost" onclick="send('reconnect')">Neu verbinden</button>
    </div>

    <div class="switches">
      <label class="sw">
        <div><div class="t">Auto-Record</div><div class="d">Startet die Aufnahme neu, wenn das Deck steht</div></div>
        <input type="checkbox" id="sw_auto_record" onchange="setFlag('auto_record',this.checked)">
        <span class="track" id="tr_auto_record"></span>
      </label>
      <label class="sw">
        <div><div class="t">Auto-Loop</div><div class="d">Formatiert die inaktive Karte rechtzeitig</div></div>
        <input type="checkbox" id="sw_auto_loop" onchange="setFlag('auto_loop',this.checked)">
        <span class="track" id="tr_auto_loop"></span>
      </label>
      <label class="sw">
        <div><div class="t">Timecode auf Uhrzeit</div><div class="d">Setzt den Startzeitcode auf die Systemzeit</div></div>
        <input type="checkbox" id="sw_sync_timecode" onchange="setFlag('sync_timecode',this.checked)">
        <span class="track" id="tr_sync_timecode"></span>
      </label>
    </div>
  </div>

  <div class="panel">
    <div class="eyebrow">Einstellungen</div>
    <div class="fields">
      <div class="field">
        <label for="f_deck_ip">Deck-IP</label>
        <input id="f_deck_ip" data-key="deck_ip" type="text" inputmode="decimal">
      </div>
      <div class="field">
        <label for="f_deck_port">Deck-Port</label>
        <input id="f_deck_port" data-key="deck_port" type="number" min="1" max="65535">
      </div>
      <div class="field">
        <label for="f_check_interval">Abfrage alle … Sekunden</label>
        <input id="f_check_interval" data-key="check_interval" type="number" min="5" max="3600">
      </div>
      <div class="field">
        <label for="f_min_remaining_threshold">Vorbereiten ab … Minuten Rest</label>
        <input id="f_min_remaining_threshold" data-key="min_remaining_threshold" type="number" min="1" max="240">
      </div>
      <div class="field">
        <label for="f_inactive_min_free">Karte leeren unter … Minuten frei</label>
        <input id="f_inactive_min_free" data-key="inactive_min_free" type="number" min="1" max="2000">
      </div>
      <div class="field">
        <label for="f_format_filesystem">Dateisystem</label>
        <select id="f_format_filesystem" data-key="format_filesystem">
          <option value="exFAT">exFAT</option>
          <option value="HFS+">HFS+</option>
        </select>
      </div>
      <div class="field">
        <label for="f_format_name">Datenträgername</label>
        <input id="f_format_name" data-key="format_name" type="text">
      </div>
    </div>
    <div class="row">
      <button onclick="saveSettings()">Einstellungen speichern</button>
      <span class="hint" id="saveHint">Werden in hyperdeck_config.json gesichert.</span>
    </div>
  </div>

  <div class="panel">
    <div class="eyebrow">Ereignisse</div>
    <div class="log" id="log"></div>
    <div class="hint" id="foot">Oberfläche 2.1</div>
  </div>

</div>

<script>
var UI_VERSION = '2.1';
var $ = function(id){ return document.getElementById(id); };
var dirty = {};
var lastLogLen = -1;
var lastInterval = 60;

// Countdown laeuft lokal weiter, damit er auch zwischen zwei Serverantworten tickt
var cdValue = null;
var cdStamp = 0;
var busyNow = '';

function num(v){
  var n = Number(v);
  return (v === null || v === '' || typeof v === 'undefined' || !isFinite(n)) ? null : n;
}

function esc(s){
  return String(s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}

async function api(path, body){
  var opt = {};
  if (body){
    opt = { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) };
  }
  var res = await fetch(path, opt);
  return res.json();
}

async function send(action, extra){
  var payload = { action: action };
  if (extra){ for (var k in extra){ payload[k] = extra[k]; } }
  await api('/api/command', payload);
  refresh();
}

async function setFlag(key, value){
  var body = {};
  body[key] = value;
  await api('/api/settings', body);
  refresh();
}

async function formatSlot(id){
  if (!confirm('Slot ' + id + ' wirklich formatieren? Alle Aufnahmen auf dieser Karte gehen verloren.')) return;
  await send('format', { slot_id: id });
}

async function saveSettings(){
  var body = {};
  var nodes = document.querySelectorAll('[data-key]');
  for (var i = 0; i < nodes.length; i++){
    var el = nodes[i];
    body[el.dataset.key] = el.value;
  }
  var res = await api('/api/settings', body);
  dirty = {};
  var n = Object.keys(res.changed || {}).length;
  $('saveHint').textContent = n ? ('Gespeichert: ' + Object.keys(res.changed).join(', ')) : 'Keine Änderung.';
  setTimeout(function(){ $('saveHint').textContent = 'Werden in hyperdeck_config.json gesichert.'; }, 4000);
  refresh();
}

document.addEventListener('input', function(e){
  if (e.target && e.target.dataset && e.target.dataset.key){ dirty[e.target.dataset.key] = true; }
});
document.addEventListener('change', function(e){
  if (e.target && e.target.dataset && e.target.dataset.key){ dirty[e.target.dataset.key] = true; }
});

function fillField(id, key, value){
  var el = $(id);
  if (!el || dirty[key] || document.activeElement === el) return;
  if (el.value !== String(value)) el.value = value;
}

function setSwitch(key, on){
  var box = $('sw_' + key), track = $('tr_' + key);
  if (!box) return;
  box.checked = !!on;
  track.className = on ? 'track on' : 'track';
}

function renderSlots(d){
  if (!d.slots || !d.slots.length){
    $('slots').innerHTML = '<div class="panel">Keine Slot-Daten vom Deck.</div>';
    return;
  }
  var scale = 60;
  for (var i = 0; i < d.slots.length; i++){ scale = Math.max(scale, num(d.slots[i].remaining_min) || 0); }
  var threshold = num(d.min_remaining_threshold) || 0;
  var html = '';
  for (var j = 0; j < d.slots.length; j++){
    var s = d.slots[j];
    var mins = num(s.remaining_min);
    var isActive = d.active_slot === s.id;
    var rec = isActive && String(d.status).indexOf('record') === 0;
    var low = rec && mins !== null && mins <= threshold;
    var pct = Math.max(2, Math.min(100, Math.round((mins || 0) / scale * 100)));
    var mounted = s.status === 'mounted' && mins !== null;
    var lf = (d.last_format || {})[String(s.id)];
    var stamp = lf ? 'zuletzt geleert ' + esc(lf) : '';
    html += '<div class="slot' + (isActive ? ' active' : '') + (low ? ' low' : '') + '">' +
      '<div class="slot-head"><div class="slot-name">Slot ' + s.id +
        (s.volume ? ' · <span style="color:var(--dim2);font-weight:400">' + esc(s.volume) + '</span>' : '') +
      '</div>' +
      (isActive ? '<span class="tag' + (rec ? ' rec' : '') + '">' + (rec ? 'nimmt auf' : 'aktiv') + '</span>' : '') +
      '</div>' +
      '<div class="mins">' + (mounted ? mins : '—') + '<small>Minuten frei</small></div>' +
      '<div class="bar"><span class="' + (low ? 'low' : '') + '" style="width:' + (mounted ? pct : 0) + '%"></span></div>' +
      '<div class="meta"><span>' + esc(s.status || 'unbekannt') + '</span><span>' + stamp + '</span></div>' +
      '<div style="margin-top:12px"><button class="b-sm b-ghost" ' + (mounted ? '' : 'disabled ') +
        'onclick="formatSlot(' + s.id + ')">Karte leeren</button></div>' +
      '</div>';
  }
  $('slots').innerHTML = html;
}

function renderLog(logs){
  if (logs.length === lastLogLen) return;
  lastLogLen = logs.length;
  var box = $('log');
  var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  var html = '';
  for (var i = 0; i < logs.length; i++){
    html += '<div><span class="t">' + esc(logs[i].time) + '</span> <span class="' +
      esc(logs[i].level) + '">' + esc(logs[i].msg) + '</span></div>';
  }
  box.innerHTML = html;
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function localCountdown(){
  if (cdValue === null) return null;
  return Math.max(0, cdValue - (Date.now() - cdStamp) / 1000);
}

function paintCountdown(){
  var v = localCountdown();
  if (busyNow){
    $('cd').textContent = '…';
    $('cdBar').style.width = '100%';
    return;
  }
  $('cd').textContent = (v === null) ? '--' : Math.ceil(v);
  $('cdBar').style.width = (v === null ? 0 : Math.max(0, Math.min(100, v / lastInterval * 100))) + '%';
}

async function refresh(){
  var d;
  try {
    d = await api('/api/status');
  } catch (e){
    $('dot').className = 'dot off';
    $('linkTxt').textContent = 'Webserver nicht erreichbar';
    return;
  }

  $('device').textContent = d.device || 'HyperDeck Control';
  $('host').textContent = d.deck_ip + ':' + d.deck_port;
  $('dot').className = 'dot ' + (d.connected ? 'on' : 'off');
  $('linkTxt').textContent = d.connected ? 'verbunden' : 'keine Verbindung';

  var recording = String(d.status).indexOf('record') === 0;
  $('tally').className = recording ? 'tally live' : 'tally';
  $('tallyWord').textContent = recording ? 'REC' : String(d.status || '--').toUpperCase();
  $('tallySub').textContent = recording ? 'Aufnahme läuft' : 'Transportstatus';
  $('tc').textContent = d.timecode;
  $('tcLabel').textContent = d.active_slot ? ('Timecode · Slot ' + d.active_slot) : 'Timecode';

  lastInterval = num(d.check_interval) || 60;
  var server = num(d.seconds_until_check);
  if (!d.connected || server === null){
    cdValue = null;
  } else if (cdValue === null || Math.abs(server - localCountdown()) > 1.5){
    cdValue = server; cdStamp = Date.now();     // neu synchronisieren
  }
  busyNow = d.busy || '';
  paintCountdown();
  $('lastPoll').textContent = d.last_poll ? ('zuletzt ' + d.last_poll) : '';

  var stale = d.ui_version && d.ui_version !== UI_VERSION;
  $('noticeStale').hidden = !stale;
  $('foot').textContent = 'Oberfläche ' + UI_VERSION + ' · Dienst ' + (d.ui_version || '?');

  $('noticeLock').hidden = !d.manual_stop;
  $('noticeBusy').hidden = !d.busy;
  $('busyTxt').textContent = d.busy ? (d.busy + ' … das kann eine Weile dauern.') : '';
  var showErr = !d.connected && d.connection_error;
  $('noticeErr').hidden = !showErr;
  if (showErr) $('errTxt').textContent = 'Deck nicht erreichbar: ' + d.connection_error;

  renderSlots(d);

  setSwitch('auto_record', d.auto_record);
  setSwitch('auto_loop', d.auto_loop);
  setSwitch('sync_timecode', d.sync_timecode);

  fillField('f_deck_ip', 'deck_ip', d.deck_ip);
  fillField('f_deck_port', 'deck_port', d.deck_port);
  fillField('f_check_interval', 'check_interval', d.check_interval);
  fillField('f_min_remaining_threshold', 'min_remaining_threshold', d.min_remaining_threshold);
  fillField('f_inactive_min_free', 'inactive_min_free', d.inactive_min_free);
  fillField('f_format_filesystem', 'format_filesystem', d.format_filesystem);
  fillField('f_format_name', 'format_name', d.format_name);

  renderLog(d.logs || []);
}

setInterval(function(){ if (!document.hidden) refresh(); }, 1000);
setInterval(function(){ if (!document.hidden) paintCountdown(); }, 250);
refresh();
</script>
</body>
</html>
"""


app = Flask(__name__)


@app.after_request
def no_cache(response):
    """Verhindert, dass der Browser eine alte Oberflaeche weiterbenutzt."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/api/status")
def api_status():
    with _state_lock:
        snapshot = copy.deepcopy(STATE)
    with _log_lock:
        logs = list(_logs)
    payload = dict(get_settings())
    payload.update(snapshot)
    payload["logs"] = logs
    payload["ui_version"] = UI_VERSION
    return jsonify(payload)


@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "resume_auto":
        set_state(manual_stop=False)
        log("Auto-Record wieder freigegeben.", "ok")
        jobs.put({"action": "poll"})
        return jsonify(ok=True)

    if action not in ("record", "stop", "poll", "format", "reconnect"):
        return jsonify(ok=False, error="Unbekannter Befehl"), 400

    jobs.put(data)
    return jsonify(ok=True)


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(silent=True) or {}
    changed = update_settings(data)
    if changed:
        log("Einstellungen geändert: %s"
            % ", ".join("%s=%s" % (k, v) for k, v in sorted(changed.items())))
        if "deck_ip" in changed or "deck_port" in changed:
            jobs.put({"action": "reconnect"})
        else:
            jobs.put({"action": "poll"})
    return jsonify(ok=True, changed=changed, settings=get_settings())


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
    args = parser.parse_args()

    load_config()
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

    cfg = get_settings()
    print("")
    print("=" * 58)
    print("  HYPERDECK WEB CONTROL")
    print("  Deck:    %s:%d" % (cfg["deck_ip"], cfg["deck_port"]))
    print("  Browser: http://localhost:%d  (oder LAN-IP dieses Rechners)" % args.web_port)
    print("=" * 58)
    print("")

    try:
        app.run(host=args.bind, port=args.web_port, threaded=True,
                debug=False, use_reloader=False)
    finally:
        shutdown.set()
        deck.close()


if __name__ == "__main__":
    main()
