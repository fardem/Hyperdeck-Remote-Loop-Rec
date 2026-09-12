# -*- coding: utf-8 -*-
"""Tests fuer hyperdeck_backup.py gegen zwei lokale FTP-Server (pyftpdlib).

Start:  python tests/test_backup.py      (oder: pytest tests/)
Ohne pyftpdlib werden die Servertests uebersprungen.
"""
import datetime
import logging
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hyperdeck_backup as hb  # noqa: E402

try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    HAVE_FTPD = True
except ImportError:                          # pragma: no cover
    HAVE_FTPD = False

logging.getLogger("pyftpdlib").setLevel(logging.WARNING)
hb.STABLE_S = 2                              # Tests sollen nicht 20 s warten
LOGS = []


def log(msg, level="info"):
    LOGS.append((level, msg))
    print("   [%s] %s" % (level, msg))


# ---------------------------------------------------------------- Helfer

def write_file(path, size, age_s=3600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(os.urandom(min(size, 4096)) * (size // 4096) + b"x" * (size % 4096))
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))


def make_ftpd(root, user=None, password=None):
    """Legt einen FTP-Server an. pyftpdlib teilt sich eine Ereignisschleife,
    deshalb werden alle Server erst angelegt und dann gemeinsam gestartet."""
    authorizer = DummyAuthorizer()
    if user:
        authorizer.add_user(user, password, root, perm="elradfmwMT")
    else:
        authorizer.add_anonymous(root)
    handler = type("Handler", (FTPHandler,), {})
    handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), handler)
    return server, server.address[1]


def serve_all(server):
    logging.getLogger("pyftpdlib").addHandler(logging.NullHandler())
    threading.Thread(target=server.serve_forever, daemon=True).start()


def list_tree(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/")
            out.append((rel, os.path.getsize(os.path.join(base, name))))
    return sorted(out)


# ---------------------------------------------------------------- reine Logik

def test_parse_list_lines():
    now = datetime.datetime(2026, 9, 12, 12, 0)
    name, is_dir, size, mtime = hb.parse_list_line(
        "-rw-r--r--   1 ftp ftp  123456789 Sep 12 09:00 HyperDeck_0001.mov", now)
    assert (name, is_dir, size) == ("HyperDeck_0001.mov", False, 123456789)
    assert mtime == datetime.datetime(2026, 9, 12, 9, 0)
    name, is_dir, size, mtime = hb.parse_list_line(
        "drwxr-xr-x   2 ftp ftp       4096 Jan 03  2025 sd1", now)
    assert (name, is_dir, mtime) == ("sd1", True, datetime.datetime(2025, 1, 3))
    name, is_dir, size, mtime = hb.parse_list_line(
        "-rw-r--r--   1 ftp ftp  10 Dec 30 23:59 mit Leerzeichen.mov", now)
    assert name == "mit Leerzeichen.mov" and mtime.year == 2025      # Jahreswechsel
    name, is_dir, size, mtime = hb.parse_list_line(
        "09-12-26  09:00AM             5000 clip.mp4", now)
    assert (name, size, mtime) == ("clip.mp4", 5000, datetime.datetime(2026, 9, 12, 9, 0))
    name, is_dir, size, mtime = hb.parse_list_line("09-12-26  01:30PM       <DIR>          sd2", now)
    assert (name, is_dir, mtime.hour) == ("sd2", True, 13)
    assert hb.parse_list_line("total 12", now) is None


def test_names():
    info = hb.FileInfo("sd1/HyperDeck_0001.mov", 100, datetime.datetime(2026, 9, 12, 9, 0, 13))
    assert hb.target_name(info) == "2026-09-12_09-00-13_HyperDeck_0001.mov"
    assert hb.target_name(hb.FileInfo("x.mov", 1)) == "x.mov"
    assert hb.sized_name("a_b.mov", 555) == "a_b_555.mov"
    assert hb.join_ftp("/", "sd1", "a.mov") == "/sd1/a.mov"
    assert hb.join_ftp("sicherung", "sd1") == "sicherung/sd1"
    assert hb.join_ftp("/sicherung/", "/sd1/") == "/sicherung/sd1"
    assert (info.top, info.folder, info.name) == ("sd1", "sd1", "HyperDeck_0001.mov")
    assert hb.human_size(1536) == "1,5 KB" and hb.human_size(5) == "5 B"


# ---------------------------------------------------------------- mit FTP-Servern

def run_server_tests():
    work = tempfile.mkdtemp(prefix="hdbackup_")
    deck_dir = os.path.join(work, "deck")
    local_target = os.path.join(work, "netzlaufwerk")
    nas_dir = os.path.join(work, "nas")
    os.makedirs(nas_dir)
    write_file(os.path.join(deck_dir, "sd1", "HyperDeck_0001.mov"), 3 * 1024 * 1024)
    write_file(os.path.join(deck_dir, "sd1", "HyperDeck_0002.mov"), 1024 * 1024, age_s=0)   # waechst
    write_file(os.path.join(deck_dir, "sd2", "HyperDeck_0001.mov"), 2 * 1024 * 1024)
    write_file(os.path.join(deck_dir, "sd2", ".versteckt"), 10)
    deck, deck_port = make_ftpd(deck_dir)
    nas, nas_port = make_ftpd(nas_dir, "nas", "geheim")
    serve_all(deck)                    # eine Schleife bedient beide Server
    cfg = {
        "deck_ip": "127.0.0.1", "deck_ftp_port": deck_port, "deck_ftp_user": "", "deck_ftp_pass": "",
        "backup_enabled": False, "backup_interval": 15, "backup_mode": "folder",
        "backup_folder": local_target, "backup_source_path": "/", "backup_block_format": True,
        "backup_ftp_host": "127.0.0.1", "backup_ftp_port": nas_port, "backup_ftp_user": "nas",
        "backup_ftp_pass": "geheim", "backup_ftp_path": "/sicherung/deck1",
    }
    rec_state = {"value": (False, None)}
    mirror = hb.Mirror(lambda: dict(cfg), log, lambda: rec_state["value"])

    print("-- Lauf 1: zwei fertige Dateien, eine waechst noch")
    grow = os.path.join(deck_dir, "sd1", "HyperDeck_0002.mov")
    growing = {"on": True}

    def feed():
        while growing["on"]:
            with open(grow, "ab") as fh:
                fh.write(b"x" * 4096)
            time.sleep(0.3)
    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    mirror._run_pass(cfg, reason="Test")
    st = mirror.snapshot()
    got = list_tree(local_target)
    assert len(got) == 2, got
    assert all(rel.split("/")[0] in ("sd1", "sd2") for rel, _ in got)
    assert all("_HyperDeck_0001.mov" in rel for rel, _ in got), got
    assert st["files_done"] == 2 and st["pending"] == 1 and st["error"] == "", st
    assert mirror.slot_folder(1) == "sd1" and mirror.slot_folder(2) == "sd2" and mirror.slot_folder(3) is None
    assert mirror.is_clean(60, slot_id=2) is True     # sd2 komplett
    assert mirror.is_clean(60, slot_id=1) is False    # sd1 hat noch die wachsende Datei
    assert [t["name"] for t in st["tree"]] == ["sd1", "sd2"]
    assert st["tree"][0]["files"] == 2

    print("-- Lauf 2: Datei waechst weiter -> nichts Neues zu kopieren")
    mirror._run_pass(cfg, reason="Test")
    st = mirror.snapshot()
    assert st["files_total"] == 0 and list_tree(local_target) == got, st
    growing["on"] = False
    feeder.join()

    print("-- Lauf 3: Datei waechst nicht mehr -> wird nachgeholt")
    mirror._run_pass(cfg, reason="Test")
    st = mirror.snapshot()
    assert st["files_done"] == 1 and st["pending"] == 0, st
    copied_size = [s for r, s in list_tree(local_target) if "HyperDeck_0002" in r][0]
    assert copied_size == os.path.getsize(grow), "Kopie muss bitgenau sein"

    print("-- Deck nimmt auf Slot 1 auf: juengste Datei in sd1 wird ausgelassen")
    write_file(os.path.join(deck_dir, "sd1", "HyperDeck_0005.mov"), 64 * 1024)
    rec_state["value"] = (True, 1)
    mirror._run_pass(cfg, reason="Test")
    assert not any("HyperDeck_0005" in r for r, _ in list_tree(local_target))
    rec_state["value"] = (False, None)
    mirror._run_pass(cfg, reason="Test")
    assert any("HyperDeck_0005" in r for r, _ in list_tree(local_target))
    assert mirror.is_clean(60) is True and mirror.is_clean(0) is False

    print("-- Namenskollision: gleicher Name + Zeit, andere Groesse -> Suffix")
    first = [r for r, _ in list_tree(local_target) if r.startswith("sd2/")][0]
    old_stat = os.stat(os.path.join(deck_dir, "sd2", "HyperDeck_0001.mov"))
    write_file(os.path.join(deck_dir, "sd2", "HyperDeck_0001.mov"), 512 * 1024)
    os.utime(os.path.join(deck_dir, "sd2", "HyperDeck_0001.mov"), (old_stat.st_mtime, old_stat.st_mtime))
    mirror._seen.clear()
    mirror._run_pass(cfg, reason="Test")
    names = [r for r, _ in list_tree(local_target) if r.startswith("sd2/")]
    assert first in names and any(r.endswith("_524288.mov") for r in names), names
    assert not any(r.endswith(".part") for r, _ in list_tree(local_target))

    print("-- Nur ein Slot (scope)")
    write_file(os.path.join(deck_dir, "sd1", "HyperDeck_0003.mov"), 100 * 1024)
    write_file(os.path.join(deck_dir, "sd2", "HyperDeck_0002.mov"), 100 * 1024)
    mirror._run_pass(cfg, scope="sd2", reason="Test")
    rels = [r for r, _ in list_tree(local_target)]
    assert any("sd2/" in r and "HyperDeck_0002" in r for r in rels)
    assert not any("HyperDeck_0003" in r for r in rels)

    print("-- FTP-Ziel (NAS)")
    cfg["backup_mode"] = "ftp"
    mirror._seen.clear()
    mirror._run_pass(cfg, reason="Test")
    st = mirror.snapshot()
    nas_files = list_tree(nas_dir)
    assert st["error"] == "" and st["files_done"] == 6, (st, nas_files)
    assert all(r.startswith("sicherung/deck1/sd") for r, _ in nas_files), nas_files
    assert not any(r.endswith(".part") for r, _ in nas_files)
    sizes_deck = sorted(s for _, s in list_tree(deck_dir) if s > 10)
    assert sorted(s for _, s in nas_files) == sizes_deck, "FTP-Ziel muss bitgenau sein"
    mirror._run_pass(cfg, reason="Test")
    assert mirror.snapshot()["files_total"] == 0        # zweiter Lauf: alles da

    print("-- Testfunktion")
    mirror._run_test(cfg)
    st = mirror.snapshot()
    assert "Deck-FTP OK" in st["last_test"] and "Ziel OK" in st["last_test"], st["last_test"]

    print("-- Ziel nicht erreichbar -> sauberer Fehler, kein Absturz")
    cfg["backup_ftp_port"] = 1
    mirror._run_pass(cfg, reason="Test")
    st = mirror.snapshot()
    assert st["error"] and st["running"] is False and st["last_result"].startswith("Fehler"), st
    cfg["backup_mode"] = "folder"
    cfg["backup_folder"] = os.path.join(deck_dir, "sd1", "HyperDeck_0001.mov", "unmoeglich")
    mirror._run_pass(cfg, reason="Test")
    assert mirror.snapshot()["error"], mirror.snapshot()

    print("-- Abbruch waehrend der Wartephase")
    cfg["backup_folder"] = local_target
    write_file(os.path.join(deck_dir, "sd1", "HyperDeck_0009.mov"), 1024, age_s=0)
    mirror._seen.clear()
    hb.STABLE_S = 5
    threading.Timer(0.5, mirror.cancel).start()
    t0 = time.monotonic()
    mirror._run_pass(cfg, reason="Test")
    assert time.monotonic() - t0 < 4, "Abbruch hat nicht gegriffen"
    assert mirror.snapshot()["last_result"].startswith("Abgebrochen")
    hb.STABLE_S = 2

    print("-- Thread: Anfrage + Warten")
    mirror.start()
    assert mirror.request_run(reason="Thread") is True
    for _ in range(100):
        time.sleep(0.1)
        if mirror.snapshot()["last_result"] and not mirror.snapshot()["running"]:
            break
    assert mirror.request_test() is True
    time.sleep(1.0)
    mirror.stop()

    deck.close_all()
    nas.close_all()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    test_parse_list_lines(); print("ok  LIST-Parser")
    test_names();            print("ok  Namensbildung")
    if HAVE_FTPD:
        run_server_tests();  print("ok  Servertests")
    else:
        print("!!  pyftpdlib fehlt - Servertests uebersprungen")
    print("Alle Backup-Tests bestanden.")
