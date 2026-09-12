# -*- coding: utf-8 -*-
"""Ende-zu-Ende: echter Dienst + simuliertes Deck, Bedienung nur ueber die API.

Start:  python tests/test_api.py      (oder: pytest tests/)
Konfiguration und Log landen in einem Temporaerordner (HYPERDECK_HOME).
"""
import datetime
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Stack(object):
    """Startet Fake-Deck und Dienst, raeumt am Ende auf."""

    def __init__(self, interval=5, stop_after=0.0):
        self.interval = interval
        self.stop_after = stop_after

    def __enter__(self):
        self.home = tempfile.mkdtemp(prefix="hdapi_")
        self.deck_port, self.web_port = free_port(), free_port()
        self.base = "http://127.0.0.1:%d" % self.web_port
        env = dict(os.environ, HYPERDECK_HOME=self.home, HYPERDECK_NO_PAUSE="1")
        deck_args = [sys.executable, os.path.join(HERE, "fake_deck.py"), str(self.deck_port)]
        if self.stop_after:
            deck_args += ["--stop-after", str(self.stop_after)]
        self.deck = subprocess.Popen(deck_args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        self.app = subprocess.Popen([sys.executable, os.path.join(ROOT, "hyperdeck_control.py"),
                                     "--ip", "127.0.0.1", "--port", str(self.deck_port),
                                     "--web-port", str(self.web_port),
                                     "--interval", str(self.interval),
                                     "--no-browser"], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            time.sleep(0.25)
            try:
                if self.get("/api/status")["connected"]:
                    return self
            except Exception:
                pass
        raise RuntimeError("Dienst kam nicht hoch")

    def __exit__(self, *exc):
        for proc in (self.app, self.deck):
            proc.terminate()
        for proc in (self.app, self.deck):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(self.home, ignore_errors=True)

    def get(self, path):
        return json.load(urllib.request.urlopen(self.base + path, timeout=5))

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=5))

    def text(self, path):
        return urllib.request.urlopen(self.base + path, timeout=5).read().decode("utf-8")


def wait_for(fn, timeout=12):
    for _ in range(int(timeout * 4)):
        if fn():
            return True
        time.sleep(0.25)
    return False


def test_notifications_beat_polling():
    """Das Deck meldet von selbst, wenn die Aufnahme endet - die Automatik muss
    sofort reagieren und nicht erst bei der naechsten Abfrage."""
    with Stack(interval=60, stop_after=2.0) as s:      # Abfrage erst in 60 s
        assert wait_for(lambda: s.get("/api/status")["notify"] is True), "notify nicht aktiv"
        assert wait_for(lambda: s.get("/api/status")["status"].startswith("record")), "Start"
        # Das Deck beendet die Aufnahme nach 2 s von selbst.
        assert wait_for(lambda: s.get("/api/status")["status"] == "stopped", 8), "Stopp gemeldet"
        began = time.monotonic()
        assert wait_for(lambda: s.get("/api/status")["status"].startswith("record"), 20), \
            "Auto-Record haette sofort neu starten muessen"
        took = time.monotonic() - began
        assert took < 20, "Reaktion dauerte %.1f s - das war wohl die Abfrage" % took
        log = s.text("/api/log.txt")
        assert "meldet Aenderungen ab jetzt von selbst" in log, log[-400:]


def test_timecode_streams_without_polling():
    """Mit "notify: display timecode" laeuft die Zeitanzeige weiter, auch wenn
    praktisch nie abgefragt wird - und das Log wird davon nicht geflutet."""
    with Stack(interval=3600) as s:                 # Kontrollabfrage faktisch aus
        assert wait_for(lambda: s.get("/api/status")["timecode_stream"] is True), \
            "Timecode-Strom nicht aktiv"
        assert wait_for(lambda: s.get("/api/status")["status"].startswith("record"))
        first = s.get("/api/status")["timecode"]
        time.sleep(2.0)
        second = s.get("/api/status")["timecode"]
        assert first != second, "Timecode muss ohne Abfrage weiterlaufen (%s)" % first
        assert second > first, (first, second)

        # Pro Bild eine Meldung darf weder das Log noch die Automatik beschaeftigen.
        text = s.text("/api/log.txt")
        assert text.count("Deck meldet:") <= 2, text[-600:]
        assert text.count("Deck steht") <= 1, text[-600:]

        # Abschalten laesst den Strom versiegen, die Anzeige friert ein.
        s.post("/api/settings", {"timecode_live": False})
        assert wait_for(lambda: s.get("/api/status")["timecode_stream"] is False)
        time.sleep(1.5)
        frozen = s.get("/api/status")["timecode"]
        time.sleep(1.5)
        assert s.get("/api/status")["timecode"] == frozen, "Strom haette enden muessen"


def test_end_to_end():
    with Stack() as s:
        d = s.get("/api/status")
        assert d["device"] == "HyperDeck Studio Test"
        assert d["log_reset"] is True and len(d["timers"]) == 3
        assert d["backup"]["phase"] == "Bereit" and "uptime_s" in d
        assert wait_for(lambda: s.get("/api/status")["status"].startswith("record")), "Auto-Record"

        # Log inkrementell
        seq = d["log_seq"]
        d2 = s.get("/api/status?since=%d" % seq)
        assert d2["log_reset"] is False
        assert s.get("/api/status?since=abc")["log_reset"] is True

        # Zeitplaene speichern und normalisieren
        r = s.post("/api/settings", {"timer_count": 2, "timers": [
            {"enabled": True, "days": [0, 1, 2, 3, 4], "start": "8:45", "end": "18:30"},
            {"enabled": True, "days": "5,6", "start": "10:00", "end": "12:00"},
            {"enabled": False, "days": [], "start": "x", "end": "y"}]})
        t = r["settings"]["timers"]
        assert t[0]["start"] == "08:45" and t[1]["days"] == [5, 6] and t[2]["start"] == "08:45"
        cfg = json.load(open(os.path.join(s.home, "hyperdeck_config.json")))
        assert cfg["timers"][1]["end"] == "12:00"
        assert not os.path.exists(os.path.join(s.home, "hyperdeck_config.json.tmp"))

        # Timer scharf: Fenster umfasst jetzt -> Aufnahme laeuft weiter, Fenster zu -> Stopp
        now = datetime.datetime.now()
        fmt = lambda dt: dt.strftime("%H:%M")
        s.post("/api/settings", {"timer_count": 1, "timer_enabled": True, "timers": [
            {"enabled": True, "days": list(range(7)), "start": fmt(now - datetime.timedelta(minutes=2)),
             "end": fmt(now + datetime.timedelta(minutes=5))}, {}, {}]})
        assert wait_for(lambda: s.get("/api/status")["timer_active"] == 1)
        s.post("/api/settings", {"timers": [
            {"enabled": True, "days": list(range(7)), "start": fmt(now - datetime.timedelta(minutes=30)),
             "end": fmt(now - datetime.timedelta(minutes=1))}, {}, {}]})
        assert wait_for(lambda: s.get("/api/status")["status"] == "stopped"), "Timer-Stopp"
        time.sleep(6)
        assert s.get("/api/status")["status"] == "stopped", "Auto-Record darf nicht dazwischenfunken"
        s.post("/api/settings", {"timer_enabled": False})
        assert wait_for(lambda: s.get("/api/status")["status"].startswith("record"), 15)

        # Passwoerter: nie im Klartext nach aussen, leer = unveraendert, "-" = loeschen
        s.post("/api/settings", {"backup_ftp_pass": "geheim"})
        d = s.get("/api/status")
        assert d["backup_ftp_pass"] == "" and d["backup_ftp_pass_set"] is True
        assert s.post("/api/settings", {"backup_ftp_pass": ""})["changed"] == {}
        s.post("/api/settings", {"backup_ftp_pass": "-"})
        assert s.get("/api/status")["backup_ftp_pass_set"] is False
        assert s.post("/api/settings", {"backup_mode": "unsinn"})["changed"] == {}

        # Sicherung ohne erreichbares Deck-FTP -> sauberer Fehler, Dienst lebt weiter
        s.post("/api/settings", {"backup_folder": os.path.join(s.home, "ziel"), "deck_ftp_port": 1})
        assert s.post("/api/command", {"action": "backup_test"})["ok"] is True
        assert wait_for(lambda: "FEHLER" in s.get("/api/status")["backup"]["last_test"])
        assert s.get("/api/status")["connected"] is True

        # Befehle
        assert s.post("/api/command", {"action": "poll"})["ok"] is True
        try:
            s.post("/api/command", {"action": "unsinn"})
            assert False, "400 erwartet"
        except urllib.error.HTTPError as exc:
            assert exc.code == 400

        # Oberflaeche und Logdatei
        html = s.text("/")
        assert "Sicherung der Aufnahmen" in html and "{{APP_VERSION}}" not in html
        assert "hyperdeck" in s.text("/ui/app.js").lower()
        log_text = s.text("/api/log.txt")
        assert "gestartet" in log_text
        assert os.path.exists(os.path.join(s.home, "hyperdeck.log"))


if __name__ == "__main__":
    test_notifications_beat_polling();      print("ok  Meldungen statt Abfragen")
    test_timecode_streams_without_polling(); print("ok  Timecode laeuft live")
    test_end_to_end();                 print("ok  Ende-zu-Ende")
    print("Alle API-Tests bestanden.")
