#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HyperDeck Studio - Sicherung der Aufnahmen per FTP
==================================================
Der HyperDeck stellt seine Karten ueber einen eingebauten FTP-Server bereit
(anonym, Port 21, Uebertragung auch waehrend der Aufnahme erlaubt - das Deck
drosselt selbst). Dieses Modul spiegelt die fertigen Clips in ein Ziel:

  * einen lokalen Ordner oder ein Netzlaufwerk  (Z:\\Aufnahmen, \\\\NAS\\Freigabe)
  * oder einen FTP-Server                        (NAS mit FTP-Dienst)

Grundsaetze
  * Eigener Thread, eigene Verbindung. Die Steuerverbindung (Port 9993) wird
    nie beruehrt, die Weboberflaeche blockiert nie.
  * Nur der kleinste FTP-Befehlssatz: CWD, NLST, SIZE, MDTM, RETR - mehr
    beherrscht der Server im HyperDeck nicht zuverlaessig (siehe unten).
  * Nur "fertige" Dateien: eine Datei wird erst kopiert, wenn ihre Groesse
    ueber einen Zeitraum unveraendert bleibt (laufende Aufnahmen wachsen).
  * Nie loeschen. Am Deck wird nichts entfernt; das Leeren der Karten bleibt
    Sache der Loop-Automatik.
  * Eindeutige Zieldateinamen: der HyperDeck zaehlt nach jedem Formatieren
    wieder bei 0001 - deshalb bekommt jede Datei den Aufnahmezeitpunkt vorne
    dran (2026-09-12_09-00-13_HyperDeck_0001.mov). Gleicher Name bei anderer
    Groesse -> Groesse wird angehaengt. Nichts wird ueberschrieben.
  * Kopiert wird in eine .part-Datei, erst danach wird umbenannt. Ein
    Abbruch hinterlaesst keine halb fertigen Clips unter echtem Namen.
"""

import collections
import datetime
import ftplib
import io
import os
import re
import socket
import threading
import time

CHUNK = 256 * 1024          # Blockgroesse beim Kopieren
STABLE_S = 20               # so lange muss eine Datei unveraendert bleiben
FTP_TIMEOUT = 30            # Sekunden fuer Verbindungsaufbau und Befehle
TRACE_MAX = 80              # so viele Zeilen FTP-Dialog werden mitgeschnitten
LOG_PROGRESS_S = 30         # Abstand der Tacho-Zeilen im Log
SPEED_SMOOTH = 0.25         # Glaettung der Geschwindigkeit (0 = traege, 1 = zappelig)
PROBE_NAME = "_hyperdeck_schreibtest.tmp"

# Verwaltungskram der Dateisysteme - gehoert nicht in die Sicherung.
# Windows legt auf jeder Karte "System Volume Information" an, macOS ".Trashes".
SKIP_FOLDERS = ("system volume information", "$recycle.bin", "recycler",
                "lost+found", "found.000", ".trashes", ".spotlight-v100",
                ".fseventsd", ".temporaryitems", ".documentrevisions-v100")
SKIP_FILES = ("desktop.ini", "thumbs.db", "autorun.inf", ".ds_store",
              "wpsettings.dat", "indexervolumeguid")


def is_system_entry(name):
    """True fuer Ordner und Dateien, die das Betriebssystem angelegt hat."""
    plain = str(name).strip().lower()
    return (plain.startswith(".") or plain in SKIP_FOLDERS or plain in SKIP_FILES
            or plain.endswith(".tmp"))
PART_SUFFIX = ".part"
SLOT_FOLDER_RE = re.compile(r"(\d)$")


class BackupError(Exception):
    pass


class BackupCancelled(BackupError):
    pass


class FileInfo(object):
    __slots__ = ("path", "size", "mtime")

    def __init__(self, path, size, mtime=None):
        self.path = path        # relativer Pfad unter dem Quellordner, "/"-getrennt
        self.size = int(size)
        self.mtime = mtime      # datetime oder None

    @property
    def name(self):
        return self.path.rsplit("/", 1)[-1]

    @property
    def folder(self):
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""

    @property
    def top(self):
        return self.path.split("/", 1)[0] if "/" in self.path else ""


def human_size(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return ("%d %s" % (num, unit)) if unit == "B" else ("%.1f %s" % (num, unit)).replace(".", ",")
        num /= 1024.0


def n_files(count):
    return "1 Datei" if count == 1 else "%d Dateien" % count


def duration_text(seconds):
    if seconds < 1:
        return "unter 1 s"
    seconds = int(seconds)
    if seconds < 60:
        return "%d s" % seconds
    if seconds < 3600:
        return "%d:%02d min" % (seconds // 60, seconds % 60)
    return "%d:%02d h" % (seconds // 3600, (seconds % 3600) // 60)


def eta_text(done, total, speed):
    """"noch etwa 3:09 min" - oder leer, wenn sich nichts schaetzen laesst."""
    if not (speed > 0) or not total or total <= done:
        return ""
    seconds = (total - done) / speed
    return "gleich fertig" if seconds < 1 else "noch etwa %s" % duration_text(seconds)


def progress_text(done, total, speed):
    """Tachozeile: 42 % (128,0 MB von 305,0 MB) - 24,6 MB/s - noch etwa 7 s"""
    parts = []
    if total:
        parts.append("%d %% (%s von %s)" % (done * 100 // total, human_size(done), human_size(total)))
    else:
        parts.append(human_size(done))
    if speed > 0:
        parts.append("%s/s" % human_size(speed))
    rest = eta_text(done, total, speed)
    if rest:
        parts.append(rest)
    return " - ".join(parts)


def join_ftp(*parts):
    """Setzt FTP-Pfade mit "/" zusammen und vermeidet doppelte Schraegstriche."""
    out = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return "/" + out if (parts and str(parts[0]).startswith("/")) else out


def target_name(info):
    """Zieldateiname mit Zeitstempel: eindeutig ueber Formatierungen hinweg."""
    if info.mtime is not None:
        return "%s_%s" % (info.mtime.strftime("%Y-%m-%d_%H-%M-%S"), info.name)
    return info.name


def sized_name(name, size):
    stem, ext = os.path.splitext(name)
    return "%s_%d%s" % (stem, size, ext)


# --------------------------------------------------------------------------
# FTP-Zugriff auf das Deck
# --------------------------------------------------------------------------
#
# Der FTP-Server im HyperDeck ist bewusst winzig. Er kennt weder MLSD noch
# zuverlaessig LIST, und er mag keine absoluten Pfade als Befehlsargument.
# Scheitert ein Datenbefehl, bleibt bei ihm ausserdem eine unbeantwortete
# "226 Closing data connection" im Steuerkanal liegen - der naechste Befehl
# liest sie als seine eigene Antwort, ab da ist der Dialog um eine Zeile
# verschoben und irgendwann meldet ftplib genau diese 226 als Fehler.
#
# Deshalb hier nur der kleinste gemeinsame Nenner, so wie ihn auch einfache
# FTP-Programme benutzen:
#     CWD <ordner>  ->  NLST  ->  SIZE <name>  ->  MDTM <name>  ->  RETR <name>
# Immer erst in den Ordner wechseln, danach nur noch blanke Dateinamen.
# Und bei jedem Verdacht auf einen verschobenen Dialog: Verbindung wegwerfen
# und neu aufbauen. Das kostet Millisekunden und rettet den Lauf.


class NotADirectory(BackupError):
    """Der Name ist kein Ordner (CWD abgelehnt)."""


def parse_mdtm(value):
    """"20260912090013" -> datetime. Die Uhrzeit kommt vom Deck."""
    try:
        return datetime.datetime.strptime(str(value).strip()[:14], "%Y%m%d%H%M%S")
    except (TypeError, ValueError):
        return None


class _TracingFTP(ftplib.FTP):
    """ftplib mit Mitschnitt: der letzte Dialog steht bei einem Fehler im Log
    und macht aus 'irgendwas mit FTP' eine konkrete Diagnose."""

    trace = None

    def putline(self, line):
        self._note(">", line)
        return ftplib.FTP.putline(self, line)

    def getline(self):
        line = ftplib.FTP.getline(self)
        self._note("<", line)
        return line

    def _note(self, arrow, line):
        if self.trace is None:
            return
        text = str(line).rstrip("\r\n")
        if text.upper().startswith("PASS"):
            text = "PASS ***"
        self.trace.append("%s %s" % (arrow, text))


class FtpClient(object):
    """Eine FTP-Verbindung mit gemerktem Arbeitsordner und Selbstheilung."""

    def __init__(self, host, port=21, user="", password="", timeout=FTP_TIMEOUT):
        self.host, self.port = host, int(port or 21)
        self.user, self.password = user or "", password or ""
        self.timeout = timeout
        self.ftp = None
        self.cwd_path = None
        self.trace = collections.deque(maxlen=TRACE_MAX)

    # ---- Verbindung -------------------------------------------------------

    def connect(self):
        self.close()
        ftp = _TracingFTP()
        ftp.trace = self.trace
        ftp.encoding = "utf-8"
        self.trace.append("--- verbinde mit %s:%d ---" % (self.host, self.port))
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(self.user or "anonymous", self.password or "anonymous@")
        ftp.set_pasv(True)
        self.ftp = ftp
        self.cwd_path = None
        try:
            ftp.voidcmd("TYPE I")
        except ftplib.all_errors:
            pass
        return ftp

    def ensure(self):
        """Liefert eine benutzbare Verbindung und stellt den Ordner wieder her."""
        if self.ftp is not None:
            return self.ftp
        wanted = self.cwd_path
        self.connect()
        if wanted and wanted != "/":
            try:
                self.ftp.cwd(wanted)
                self.cwd_path = wanted
            except ftplib.all_errors:
                self.cwd_path = None
        return self.ftp

    def close(self):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
        self.ftp = None
        self.cwd_path = None

    def drop(self, reason=""):
        """Verbindung wegwerfen, weil der Dialog nicht mehr stimmt."""
        if reason:
            self.trace.append("--- Verbindung verworfen: %s ---" % reason)
        self.close()

    def dialog(self):
        return list(self.trace)

    def binary(self):
        """NLST laeuft ueber TYPE A - vor SIZE und RETR zurueck auf binaer."""
        ftp = self.ensure()
        try:
            ftp.voidcmd("TYPE I")
        except (ftplib.error_reply, ftplib.error_proto) as exc:
            self.drop("TYPE I: %s" % exc)
            ftp = self.ensure()
            ftp.voidcmd("TYPE I")
        return ftp

    # ---- Grundbefehle -----------------------------------------------------

    def chdir(self, path):
        """Wechselt in den Ordner. Alles danach benutzt blanke Dateinamen."""
        path = path or "/"
        ftp = self.ensure()
        if self.cwd_path == path:
            return ftp
        try:
            ftp.cwd(path)
        except ftplib.error_perm as exc:
            raise NotADirectory("%s (%s)" % (path, exc))
        except (ftplib.error_reply, ftplib.error_proto, EOFError, OSError) as exc:
            self.drop("CWD %s: %s" % (path, exc))
            ftp = self.ensure()
            try:
                ftp.cwd(path)
            except ftplib.error_perm as exc2:
                raise NotADirectory("%s (%s)" % (path, exc2))
        self.cwd_path = path
        return ftp

    def list_names(self, path):
        """Dateinamen im Ordner - nur NLST, das kann jeder FTP-Server."""
        self.chdir(path)
        try:
            raw_names = self.ensure().nlst()
        except ftplib.error_perm as exc:
            if str(exc)[:3] in ("450", "550"):
                return []                       # leerer Ordner
            raise
        except (ftplib.error_reply, ftplib.error_proto, EOFError, OSError) as exc:
            self.drop("NLST %s: %s" % (path, exc))
            self.chdir(path)
            raw_names = self.ensure().nlst()
        names = []
        for raw in raw_names:
            name = str(raw).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip()
            if name and name not in (".", "..") and name not in names:
                names.append(name)
        return sorted(names)

    def size(self, name):
        """Groesse einer Datei im aktuellen Ordner - None, wenn es keine ist."""
        ftp = self.binary()
        try:
            value = ftp.size(name)
        except ftplib.error_perm:
            return None                         # meist ein Ordner
        except (ftplib.error_reply, ftplib.error_proto, EOFError, OSError) as exc:
            self.drop("SIZE %s: %s" % (name, exc))
            return None
        return None if value is None else int(value)

    def mdtm(self, name):
        """Aufnahmezeitpunkt laut Deck - None, wenn das Deck MDTM nicht kann."""
        try:
            resp = self.ensure().sendcmd("MDTM " + name)
        except ftplib.error_perm:
            return None
        except (ftplib.error_reply, ftplib.error_proto, EOFError, OSError) as exc:
            self.drop("MDTM %s: %s" % (name, exc))
            return None
        return parse_mdtm(resp[3:]) if resp[:3] == "213" else None

    def retrieve(self, folder, name, callback, blocksize=CHUNK):
        """Laedt eine Datei blockweise. retrbinary setzt TYPE I selbst und
        liest die Abschlussantwort sauber weg - genau das, was fehlte."""
        self.chdir(folder or "/")
        self.ensure().retrbinary("RETR " + name, callback, blocksize)

    # ---- fuer FTP-Ziele ---------------------------------------------------

    def size_of_path(self, path):
        """Groesse ueber einen vollen Pfad (nur fuer Ziel-Server benutzt)."""
        folder, _, name = str(path).rpartition("/")
        try:
            self.chdir(folder or "/")
        except NotADirectory:
            return None
        return self.size(name)

    def makedirs(self, path):
        ftp = self.ensure()
        current = "/" if str(path).startswith("/") else ""
        for part in [p for p in str(path).split("/") if p]:
            current = join_ftp(current, part) if current else part
            try:
                ftp.mkd(current)
            except ftplib.error_perm:
                pass                            # existiert bereits (550)
        self.cwd_path = None

    def delete(self, path):
        try:
            self.ensure().delete(path)
        except ftplib.all_errors:
            pass

    # ---- Durchlauf --------------------------------------------------------

    def walk(self, root, max_depth=3):
        """Alle Dateien unter root als FileInfo mit relativem Pfad."""
        files = []
        self._walk(root or "/", "", 0, max_depth, files)
        files.sort(key=lambda f: f.path)
        return files

    def _walk(self, abs_dir, rel, depth, max_depth, files):
        names = self.list_names(abs_dir)
        folders = []
        for name in names:
            if is_system_entry(name):
                continue
            child = "%s/%s" % (rel, name) if rel else name
            size = self.size(name)
            if size:                            # > 0 -> eindeutig eine Datei
                files.append(FileInfo(child, size, self.mdtm(name)))
            else:
                folders.append((name, child))
        for name, child in folders:
            if depth >= max_depth:
                continue
            try:
                self._walk(join_ftp(abs_dir, name), child, depth + 1, max_depth, files)
            except NotADirectory:
                continue                        # doch eine Datei (0 Bytes)


# --------------------------------------------------------------------------
# Ziele
# --------------------------------------------------------------------------

class LocalSink(object):
    """Lokaler Ordner oder Netzlaufwerk (UNC-Pfad)."""

    kind = "Ordner"

    def __init__(self, root):
        self.root = root

    def describe(self):
        return self.root

    def prepare(self):
        if not self.root:
            raise BackupError("Kein Zielordner eingestellt")
        os.makedirs(self.root, exist_ok=True)
        probe = os.path.join(self.root, PROBE_NAME)
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)

    def size_of(self, rel):
        path = os.path.join(self.root, *rel.split("/"))
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def begin_write(self, rel):
        final = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(final), exist_ok=True)
        part = final + PART_SUFFIX
        fh = open(part, "wb")

        class Writer(object):
            def write(self_inner, chunk):
                fh.write(chunk)

            def commit(self_inner):
                fh.flush()
                os.fsync(fh.fileno())
                fh.close()
                os.replace(part, final)

            def abort(self_inner):
                try:
                    fh.close()
                finally:
                    try:
                        os.remove(part)
                    except OSError:
                        pass
        return Writer()

    def dialog(self):
        return []

    def close(self):
        pass


class FtpSink(object):
    """FTP-Server als Ziel (z. B. NAS)."""

    kind = "FTP"

    def __init__(self, host, port, user, password, root):
        self.client = FtpClient(host, port, user, password)
        self.root = root or "/"

    def describe(self):
        return "ftp://%s:%d%s" % (self.client.host, self.client.port, self.root)

    def prepare(self):
        if not self.client.host:
            raise BackupError("Kein FTP-Server als Ziel eingestellt")
        self.client.connect()
        self.client.makedirs(self.root)
        self.client.chdir(self.root)
        self.client.binary().storbinary("STOR " + PROBE_NAME, io.BytesIO(b"ok"))
        self.client.delete(PROBE_NAME)

    def size_of(self, rel):
        return self.client.size_of_path(join_ftp(self.root, rel))

    def dialog(self):
        return self.client.dialog()

    def begin_write(self, rel):
        client = self.client
        final = join_ftp(self.root, rel)
        folder, _, name = final.rpartition("/")
        if folder:
            client.makedirs(folder)
        client.chdir(folder or "/")
        part = name + PART_SUFFIX
        ftp = client.binary()
        conn = ftp.transfercmd("STOR " + part)

        class Writer(object):
            def write(self_inner, chunk):
                conn.sendall(chunk)

            def commit(self_inner):
                conn.close()
                ftp.voidresp()
                try:
                    ftp.delete(name)       # falls ein Rest mit gleichem Namen liegt
                except ftplib.all_errors:
                    pass
                ftp.rename(part, name)

            def abort(self_inner):
                try:
                    conn.close()
                except Exception:
                    pass
                try:
                    ftp.voidresp()
                except Exception:
                    pass
                client.delete(part)
                client.drop("STOR abgebrochen")   # Steuerkanal koennte verwirrt sein
        return Writer()

    def close(self):
        self.client.close()


def make_sink(cfg):
    if (cfg.get("backup_mode") or "folder") == "ftp":
        return FtpSink(cfg.get("backup_ftp_host", ""), cfg.get("backup_ftp_port", 21),
                       cfg.get("backup_ftp_user", ""), cfg.get("backup_ftp_pass", ""),
                       cfg.get("backup_ftp_path", "/") or "/")
    return LocalSink((cfg.get("backup_folder") or "").strip())


# --------------------------------------------------------------------------
# Der Spiegel-Thread
# --------------------------------------------------------------------------

class Mirror(object):
    """Kopiert fertige Clips vom Deck ins Ziel. Ein Thread, keine Ueberraschungen."""

    def __init__(self, get_settings, log, get_recording_state=None):
        self.get_settings = get_settings
        self.log = log
        # liefert (nimmt_auf, aktiver_slot) - damit die gerade wachsende Datei
        # auch dann ausgelassen wird, wenn das Deck ihre Groesse einfriert
        self.get_recording_state = get_recording_state or (lambda: (False, None))
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._request = None            # ("run", scope, grund) oder ("test",)
        self._seen = {}                 # relpath -> (size, zuerst gesehen [monotonic])
        self._last_error_text = ""
        self._last_error_at = 0.0
        self._last_run_mono = None
        self._clean_at_mono = None      # letzter Lauf ohne offene Dateien
        self._pending_paths = set()
        self._top_folders = []
        self.thread = None
        self.state = {
            "running": False,
            "phase": "Bereit",
            "current": "",
            "current_done": 0,
            "current_size": 0,
            "speed": 0.0,               # Bytes pro Sekunde
            "files_done": 0,
            "files_total": 0,
            "bytes_done": 0,
            "bytes_total": 0,
            "pending": 0,
            "last_run": "",
            "last_ok": "",
            "last_result": "",
            "error": "",
            "next_run_s": None,
            "last_test": "",
            "tree": [],                 # [{"name","files","bytes"}]
        }

    # ---- Steuerung von aussen --------------------------------------------

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="hyperdeck-backup", daemon=True)
            self.thread.start()

    def stop(self):
        self._stop.set()
        self._cancel.set()
        self._wake.set()

    def request_run(self, scope=None, reason="manuell"):
        with self._lock:
            if self.state["running"]:
                return False
            self._request = ("run", scope, reason)
        self._wake.set()
        return True

    def request_test(self):
        with self._lock:
            if self.state["running"]:
                return False
            self._request = ("test",)
        self._wake.set()
        return True

    def cancel(self):
        self._cancel.set()

    def snapshot(self):
        with self._lock:
            data = dict(self.state)
        data["next_run_s"] = self._seconds_until_next()
        return data

    def slot_folder(self, slot_id):
        """Oberster Ordner, dessen Name mit der Slot-Nummer endet (sd1, cfast2, 1)."""
        for name in self._top_folders:
            match = SLOT_FOLDER_RE.search(name)
            if match and int(match.group(1)) == int(slot_id):
                return name
        return None

    def is_clean(self, max_age_s, slot_id=None):
        """True, wenn der letzte vollstaendige Lauf juenger als max_age_s ist und
        keine Datei (des Slots) offen blieb."""
        if self._clean_at_mono is None or time.monotonic() - self._clean_at_mono > max_age_s:
            return False
        if slot_id is None:
            return not self._pending_paths
        folder = self.slot_folder(slot_id)
        if folder is None:
            return not self._pending_paths
        return not any(p.split("/", 1)[0] == folder for p in self._pending_paths)

    # ---- intern -----------------------------------------------------------

    def _set(self, **kwargs):
        with self._lock:
            self.state.update(kwargs)

    def _seconds_until_next(self):
        cfg = self.get_settings()
        if not cfg.get("backup_enabled"):
            return None
        interval = max(1, int(cfg.get("backup_interval", 15))) * 60
        if self._last_run_mono is None:
            return 0
        return max(0, int(self._last_run_mono + interval - time.monotonic()))

    def _log_error(self, text, source=None):
        """Dieselbe Stoerung nur alle 10 Minuten melden - beim ersten Mal mit
        dem FTP-Dialog, damit man sieht, was das Deck tatsaechlich geantwortet hat."""
        now = time.monotonic()
        if text != self._last_error_text or now - self._last_error_at > 600:
            self._last_error_text, self._last_error_at = text, now
            self.log(text, "err")
            if source is not None:
                self.log_dialog(source)

    def log_dialog(self, source, limit=25):
        try:
            lines = source.dialog()[-limit:]
        except Exception:
            return
        if lines:
            self.log("FTP-Dialog (letzte %d Zeilen):\n    %s"
                     % (len(lines), "\n    ".join(lines)))

    def _loop(self):
        while not self._stop.is_set():
            self._wake.wait(timeout=5)     # kurz, damit neue Einstellungen greifen
            self._wake.clear()
            if self._stop.is_set():
                break
            with self._lock:
                request, self._request = self._request, None
            cfg = self.get_settings()
            try:
                if request and request[0] == "test":
                    self._run_test(cfg)
                elif request and request[0] == "run":
                    self._run_pass(cfg, scope=request[1], reason=request[2])
                elif cfg.get("backup_enabled") and self._seconds_until_next() == 0:
                    self._run_pass(cfg, scope=None, reason="Intervall")
            except Exception as exc:              # der Thread darf nie sterben
                self._set(running=False, phase="Fehler", error=str(exc))
                self._log_error("Sicherung: unerwarteter Fehler - %s" % exc)
                self._last_run_mono = time.monotonic()

    # ---- Testlauf ---------------------------------------------------------

    def _run_test(self, cfg):
        self._set(running=True, phase="Prüfe Verbindung", error="")
        results = []
        source = self._make_source(cfg)
        try:
            files = source.walk(cfg.get("backup_source_path") or "/")
            tops = sorted(set(f.top for f in files if f.top))
            self._top_folders = tops
            results.append("Deck-FTP OK: %s, %s%s" % (
                n_files(len(files)), human_size(sum(f.size for f in files)),
                (" in " + ", ".join(tops)) if tops else ""))
            self._update_tree(files)
        except Exception as exc:
            results.append("Deck-FTP FEHLER: %s" % exc)
            self.log_dialog(source)
        finally:
            source.close()
        sink = make_sink(cfg)
        try:
            sink.prepare()
            results.append("Ziel OK (%s, beschreibbar): %s" % (sink.kind, sink.describe()))
        except Exception as exc:
            results.append("Ziel FEHLER: %s" % exc)
        finally:
            sink.close()
        text = " | ".join(results)
        level = "err" if "FEHLER" in text else "ok"
        self.log("Sicherungstest: " + text, level)
        self._set(running=False, phase="Bereit", last_test=text)

    # ---- Ein Spiegel-Lauf -------------------------------------------------

    def _make_source(self, cfg):
        return FtpClient(cfg.get("deck_ip", ""), cfg.get("deck_ftp_port", 21),
                         cfg.get("deck_ftp_user", ""), cfg.get("deck_ftp_pass", ""))

    def _update_tree(self, files):
        tree = {}
        for f in files:
            entry = tree.setdefault(f.top or "/", {"name": f.top or "/", "files": 0, "bytes": 0})
            entry["files"] += 1
            entry["bytes"] += f.size
        self._set(tree=[tree[k] for k in sorted(tree)])

    def _stable(self, files):
        """Trennt fertige Dateien von solchen, die noch wachsen koennten.
        Massstab ist allein die Groesse: bleibt sie STABLE_S Sekunden gleich,
        ist die Datei fertig. Zeitstempel des Decks werden dafuer bewusst nicht
        benutzt (unbekannte Zeitzone)."""
        now = time.monotonic()
        ready, unsure = [], []
        for f in files:
            size, first = self._seen.get(f.path, (None, None))
            if size != f.size:
                self._seen[f.path] = (f.size, now)
                first = now
            if now - first >= STABLE_S:
                ready.append(f)
            else:
                unsure.append(f)
        # Vergessene Dateien (am Deck geloescht/formatiert) aus dem Gedaechtnis werfen
        present = set(f.path for f in files)
        for path in list(self._seen):
            if path not in present:
                del self._seen[path]
        return ready, unsure

    def _without_active_recording(self, files):
        """Nimmt das Deck gerade auf, wird die juengste Datei des aktiven Slots
        (hoechste Nummer, der HyperDeck zaehlt fortlaufend) ausgelassen."""
        try:
            recording, active = self.get_recording_state()
        except Exception:
            return files
        if not recording or active not in (1, 2):
            return files
        folder = self.slot_folder(active)
        if folder is None:
            return files
        in_slot = [f for f in files if f.top == folder]
        if not in_slot:
            return files
        newest = max(in_slot, key=lambda f: f.name)
        return [f for f in files if f is not newest]

    def _run_pass(self, cfg, scope=None, reason="Intervall"):
        self._cancel.clear()
        self._set(running=True, phase="Lese Dateiliste vom Deck", error="", current="",
                  current_done=0, current_size=0, files_done=0, files_total=0,
                  bytes_done=0, bytes_total=0, speed=0.0)
        started = time.monotonic()
        source = self._make_source(cfg)
        sink = make_sink(cfg)
        copied, copied_bytes, failed = 0, 0, []
        try:
            root = cfg.get("backup_source_path") or "/"
            files = source.walk(root)
            self._top_folders = sorted(set(f.top for f in files if f.top))
            self._update_tree(files)
            files = self._without_active_recording(files)
            if scope:
                files = [f for f in files if f.path.split("/", 1)[0] == scope]
            ready, unsure = self._stable(files)
            if unsure and not any(self._seen[f.path][1] < started - STABLE_S for f in unsure):
                # Erste Sichtung: kurz warten und erneut listen, damit ein
                # manueller Lauf nicht mit leeren Haenden endet.
                self._set(phase="Warte %d s, ob Dateien noch wachsen" % STABLE_S)
                if self._cancel.wait(STABLE_S):
                    raise BackupCancelled()
                files = self._without_active_recording(source.walk(root))
                if scope:
                    files = [f for f in files if f.path.split("/", 1)[0] == scope]
                ready, unsure = self._stable(files)

            sink.prepare()
            todo = []
            for f in ready:
                name = self._target_rel(sink, f)
                if name is not None:
                    todo.append((f, name))
            total_bytes = sum(f.size for f, _ in todo)
            self._set(files_total=len(todo), bytes_total=total_bytes,
                      phase=("Kopiere" if todo else "Nichts zu tun"))
            if todo:
                self.log("Sicherung (%s): %s, %s zu kopieren -> %s" % (
                    reason, n_files(len(todo)), human_size(total_bytes), sink.describe()))

            for index, (f, rel) in enumerate(todo, 1):
                if self._cancel.is_set():
                    raise BackupCancelled()
                self._set(current=f.path, current_size=f.size, current_done=0,
                          phase="Kopiere %d/%d" % (index, len(todo)))
                try:
                    self._copy(source, sink, f, rel)
                    copied += 1
                    copied_bytes += f.size
                except BackupCancelled:
                    raise
                except Exception as exc:
                    failed.append(f.path)
                    self._log_error("Sicherung: %s fehlgeschlagen - %s" % (f.path, exc), source)
                    source.drop("nach Fehler")   # naechste Datei mit frischer Verbindung
                self._set(files_done=index, bytes_done=copied_bytes)

            self._pending_paths = set(failed) | set(f.path for f in unsure)
            took = int(time.monotonic() - started)
            if failed:
                result = "%s kopiert, %d FEHLER, %d noch offen (%s)" % (
                    n_files(copied), len(failed), len(unsure), human_size(copied_bytes))
                self._set(error="%s fehlgeschlagen" % n_files(len(failed)))
            else:
                result = "%s (%s) in %d s kopiert, %d noch in Aufnahme" % (
                    n_files(copied), human_size(copied_bytes), took, len(unsure))
                if not unsure or scope is None:
                    self._clean_at_mono = time.monotonic()
                if copied:
                    self.log("Sicherung fertig: " + result, "ok")
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            self._set(last_run=stamp, last_result=result, pending=len(self._pending_paths),
                      last_ok=(stamp if not failed else self.state["last_ok"]))
        except BackupCancelled:
            self._set(last_result="Abgebrochen (%s kopiert)" % n_files(copied), error="")
            self.log("Sicherung abgebrochen.", "warn")
        except Exception as exc:
            self._set(error=str(exc), last_result="Fehler: %s" % exc)
            self._log_error("Sicherung fehlgeschlagen: %s" % exc, source)
        finally:
            source.close()
            sink.close()
            self._last_run_mono = time.monotonic()
            self._set(running=False, phase="Bereit", current="", speed=0.0)

    def _target_rel(self, sink, info):
        """Zielpfad relativ zum Zielordner - oder None, wenn schon vorhanden."""
        base = target_name(info)
        candidate = "%s/%s" % (info.folder, base) if info.folder else base
        existing = sink.size_of(candidate)
        if existing is None:
            return candidate
        if existing == info.size:
            return None                                # schon gesichert
        alt = sized_name(base, info.size)
        candidate = "%s/%s" % (info.folder, alt) if info.folder else alt
        existing = sink.size_of(candidate)
        if existing == info.size:
            return None
        return candidate

    def _copy(self, source, sink, info, rel):
        """Laedt eine Datei ueber retrbinary - ftplib kuemmert sich dabei um
        Datenverbindung und Abschlussantwort, was den Steuerkanal sauber haelt."""
        root = self.get_settings().get("backup_source_path") or "/"
        folder = join_ftp(root, info.folder) if info.folder else root
        writer = sink.begin_write(rel)
        started = time.monotonic()
        tick = {"done": 0, "at": started, "bytes": 0, "logged": started, "speed": 0.0}
        with self._lock:                       # Stand des gesamten Laufs
            before = self.state["bytes_done"]
            total_all = self.state["bytes_total"]
            number = self.state["files_done"] + 1
            count = self.state["files_total"]

        def block(data):
            if self._cancel.is_set():
                raise BackupCancelled()
            writer.write(data)
            tick["done"] += len(data)
            now = time.monotonic()
            if now - tick["at"] < 0.5:
                return
            instant = (tick["done"] - tick["bytes"]) / (now - tick["at"])
            # Gleitender Durchschnitt - eine zappelnde Restzeit hilft niemandem.
            tick["speed"] = (instant if not tick["speed"]
                             else tick["speed"] + SPEED_SMOOTH * (instant - tick["speed"]))
            tick["at"], tick["bytes"] = now, tick["done"]
            self._set(current_done=tick["done"], speed=tick["speed"])
            if now - tick["logged"] >= LOG_PROGRESS_S:
                tick["logged"] = now
                line = "Sicherung %d/%d: %s %s" % (
                    number, count, info.path,
                    progress_text(tick["done"], info.size, tick["speed"]))
                rest = eta_text(before + tick["done"], total_all, tick["speed"])
                if rest and count > 1:
                    line += " | gesamt %s von %s, %s" % (
                        human_size(before + tick["done"]), human_size(total_all), rest)
                self.log(line)

        try:
            source.retrieve(folder, info.name, block, CHUNK)
            if tick["done"] != info.size:
                raise BackupError("Groesse stimmt nicht (%d statt %d Bytes)"
                                  % (tick["done"], info.size))
            writer.commit()
        except BaseException:
            writer.abort()
            # Nach Abbruch oder Fehler steht die Verbindung mitten im Transfer.
            # Sie wird weggeworfen, damit die naechste Datei sauber startet.
            source.drop("Uebertragung abgebrochen")
            raise
        finally:
            self._set(current_done=tick["done"])
        took = max(0.001, time.monotonic() - started)
        line = "Sicherung %d/%d: %s fertig - %s in %s (%s/s)" % (
            number, count, info.path, human_size(info.size), duration_text(took),
            human_size(info.size / took))
        rest = eta_text(before + info.size, total_all, info.size / took)
        if rest and number < count:
            line += " | gesamt %s von %s, %s" % (
                human_size(before + info.size), human_size(total_all), rest)
        self.log(line)
