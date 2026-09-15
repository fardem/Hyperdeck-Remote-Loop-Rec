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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
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

def test_mdtm_is_converted_to_local_time():
    """FTP meldet Zeitstempel laut RFC 3659 in UTC. Im Dateinamen soll aber die
    Ortszeit stehen - sonst sind die Namen im Sommer zwei Stunden zu frueh."""
    import time as _time
    alt_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Berlin"
        if hasattr(_time, "tzset"):
            _time.tzset()
        else:
            return                                  # Windows: nicht umschaltbar
        roh = hb.parse_mdtm("20260913124611")
        assert roh == datetime.datetime(2026, 9, 13, 12, 46, 11), roh
        lokal = hb.to_local_time(roh)
        assert lokal == datetime.datetime(2026, 9, 13, 14, 46, 11), lokal   # MESZ
        assert hb.to_local_time(roh, assume_utc=False) == roh, "Geraet meldet Ortszeit"

        info = hb.FileInfo("2/Clip_0007.mp4", 100, lokal, roh)
        assert hb.target_name(info) == "2026-09-13_14-46-11_Clip_0007.mp4"
        assert hb.legacy_name(info) == "2026-09-13_12-46-11_Clip_0007.mp4"

        # Im Winter gilt MEZ, also nur eine Stunde Unterschied.
        winter = hb.to_local_time(hb.parse_mdtm("20260113124611"))
        assert winter == datetime.datetime(2026, 1, 13, 13, 46, 11), winter

        gleich = hb.FileInfo("x.mp4", 1, roh, roh)
        assert hb.legacy_name(gleich) is None, "ohne Verschiebung kein zweiter Name"
    finally:
        if alt_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = alt_tz
        if hasattr(_time, "tzset"):
            _time.tzset()


def test_already_saved_under_the_old_name_is_not_copied_again():
    """Nach der Korrektur heissen neue Dateien anders. Ein Clip, der unter dem
    alten Namen schon im Ziel liegt, darf nicht ein zweites Mal kommen."""
    work = tempfile.mkdtemp(prefix="hdtz_")
    try:
        sink = hb.LocalSink(work)
        sink.prepare()
        roh = datetime.datetime(2026, 9, 13, 12, 46, 11)
        lokal = datetime.datetime(2026, 9, 13, 14, 46, 11)
        info = hb.FileInfo("2/Clip_0007.mp4", 4096, lokal, roh)
        mirror = hb.Mirror(lambda: {}, log)

        assert mirror._target_rel(sink, info) == "2/2026-09-13_14-46-11_Clip_0007.mp4"
        write_file(os.path.join(work, "2", hb.legacy_name(info)), 4096)
        assert mirror._target_rel(sink, info) is None, "alter Name zaehlt als gesichert"

        anders = hb.FileInfo("2/Clip_0007.mp4", 9999, lokal, roh)
        assert mirror._target_rel(sink, anders) is not None, "andere Groesse = anderer Clip"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_system_entries_are_skipped():
    for name in ("System Volume Information", "$RECYCLE.BIN", ".Trashes",
                 "Thumbs.db", "WPSettings.dat", "IndexerVolumeGuid", ".DS_Store",
                 "halbe_datei.tmp", ".fseventsd"):
        assert hb.is_system_entry(name), name
    for name in ("HyperDeck_0001.mov", "Blackmagic HyperDeck Studio Mini_0002.mp4",
                 "sd1", "2", "Aufnahme.braw"):
        assert not hb.is_system_entry(name), name


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
    assert hb.n_files(1) == "1 Datei" and hb.n_files(3) == "3 Dateien"


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
    write_file(os.path.join(deck_dir, "System Volume Information", "WPSettings.dat"), 12)
    write_file(os.path.join(deck_dir, "System Volume Information", "IndexerVolumeGuid"), 76)
    write_file(os.path.join(deck_dir, "sd1", "Thumbs.db"), 4096)
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
    assert not any("WPSettings" in r or "Thumbs" in r or "System Volume" in r
                   for r, _ in got), "Systemdateien duerfen nicht mitkommen"
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

    print("-- Ein Lauf fuer einen Slot darf den anderen nicht freigeben")
    mirror._seen.clear()
    mirror._run_pass(cfg, scope="sd1", reason="Test")
    assert mirror.is_clean(60, slot_id=1) is True, "sd1 wurde gerade gesichert"
    assert mirror.is_clean(60, slot_id=2) is False, \
        "sd2 war nicht Teil des Laufs und darf nicht als gesichert gelten"
    assert mirror.is_clean(60) is False, "ein Teil-Lauf sagt nichts ueber das Ganze"
    mirror._seen.clear()
    mirror._run_pass(cfg, reason="Test")
    assert mirror.is_clean(60, slot_id=2) is True, "nach dem vollen Lauf ist sd2 gesichert"

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
    sizes_deck = sorted(size for rel, size in list_tree(deck_dir)
                        if size > 10 and not any(hb.is_system_entry(part)
                                                 for part in rel.split("/")))
    assert st["error"] == "" and st["files_done"] == len(sizes_deck), (st, nas_files)
    assert all(r.startswith("sicherung/deck1/sd") for r, _ in nas_files), nas_files
    assert not any(r.endswith(".part") for r, _ in nas_files)
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


def test_hyperdeck_quirks():
    """Der HyperDeck kennt kein MLSD, mag keine absoluten Pfade und laesst nach
    einem abgelehnten Datenbefehl eine 226 im Steuerkanal liegen. Genau daran
    ist die Sicherung in Version 3.1.0 gescheitert."""
    if not HAVE_FTPD:
        return
    from fake_deck_ftp import make_server
    work = tempfile.mkdtemp(prefix="deckquirk_")
    try:
        os.makedirs(os.path.join(work, "sd1"))
        os.makedirs(os.path.join(work, "sd2"))
        write_file(os.path.join(work, "sd1", "HyperDeck_0001.mov"), 300000)
        write_file(os.path.join(work, "sd1", "HyperDeck_0002.mov"), 150000)
        write_file(os.path.join(work, "sd2", "HyperDeck_0001.mov"), 90000)
        server, port = make_server(work)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        # So sah der Fehler aus: MLSD scheitert und vergiftet den Steuerkanal.
        import ftplib
        raw = ftplib.FTP()
        raw.connect("127.0.0.1", port, timeout=10)
        raw.login()
        try:
            list(raw.mlsd("/", ["type", "size"]))
            assert False, "MLSD sollte scheitern"
        except ftplib.error_perm:
            pass
        try:
            raw.retrlines("LIST /", lambda line: None)
            poisoned = False
        except ftplib.error_reply:
            poisoned = True            # der Folgefehler, den der Nutzer sah
        assert poisoned, "Steuerkanal muesste jetzt verschoben sein"
        try:
            raw.close()
        except Exception:
            pass

        # Und so geht es richtig: CWD + NLST + SIZE + MDTM + RETR
        client = hb.FtpClient("127.0.0.1", port)
        files = client.walk("/")
        assert {f.path for f in files} == {
            "sd1/HyperDeck_0001.mov", "sd1/HyperDeck_0002.mov", "sd2/HyperDeck_0001.mov"}, files
        assert all(f.mtime is not None for f in files), "MDTM fehlt"
        assert [f.size for f in sorted(files, key=lambda f: f.path)] == [300000, 150000, 90000]

        blocks = []
        client.retrieve("/sd1", "HyperDeck_0001.mov", blocks.append, 65536)
        with open(os.path.join(work, "sd1", "HyperDeck_0001.mov"), "rb") as fh:
            assert b"".join(blocks) == fh.read(), "Kopie nicht bitgenau"
        assert len(client.walk("/")) == 3, "Verbindung nach dem Download unbrauchbar"
        assert any("CWD" in line for line in client.dialog()), client.dialog()

        # Kompletter Lauf ueber den Mirror gegen dasselbe Deck
        target = os.path.join(work, "ziel")
        cfg = {
            "deck_ip": "127.0.0.1", "deck_ftp_port": port, "deck_ftp_user": "", "deck_ftp_pass": "",
            "backup_enabled": False, "backup_interval": 15, "backup_mode": "folder",
            "backup_folder": target, "backup_source_path": "/", "backup_block_format": True,
            "backup_ftp_host": "", "backup_ftp_port": 21, "backup_ftp_user": "",
            "backup_ftp_pass": "", "backup_ftp_path": "/",
        }
        mirror = hb.Mirror(lambda: dict(cfg), log)
        mirror._run_pass(cfg, reason="Test")
        state = mirror.snapshot()
        assert state["error"] == "" and state["files_done"] == 3, state
        copied = list_tree(target)
        assert len(copied) == 3, copied
        assert all(name.split("/")[-1][:2] == "20" for name, _ in copied), copied
        mirror._run_test(cfg)
        assert "Deck-FTP OK" in mirror.snapshot()["last_test"], mirror.snapshot()["last_test"]
        client.close()
        server.close_all()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_eta_in_log():
    """Tacho- und Abschlusszeilen muessen Restzeit fuer die Datei UND fuer den
    gesamten Lauf enthalten - sonst weiss niemand, wie lange es noch dauert."""
    if not HAVE_FTPD:
        return
    from fake_deck_ftp import make_server
    work = tempfile.mkdtemp(prefix="hdeta_")
    stable, progress, chunk = hb.STABLE_S, hb.LOG_PROGRESS_S, hb.CHUNK
    begin_write = hb.LocalSink.begin_write
    try:
        hb.STABLE_S, hb.LOG_PROGRESS_S, hb.CHUNK = 1, 0.6, 32 * 1024
        os.makedirs(os.path.join(work, "2"))
        for index, mb in enumerate((4, 6, 10)):
            write_file(os.path.join(work, "2", "HyperDeck_%04d.mp4" % index), mb * 1024 * 1024)
        server, port = make_server(work)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def slow(self, rel):                 # Uebertragung bremsen, sonst misst niemand etwas
            writer = begin_write(self, rel)
            inner = writer.write
            writer.write = lambda data: (time.sleep(0.012), inner(data))[1]
            return writer
        hb.LocalSink.begin_write = slow

        lines = []
        cfg = {
            "deck_ip": "127.0.0.1", "deck_ftp_port": port, "deck_ftp_user": "", "deck_ftp_pass": "",
            "backup_enabled": False, "backup_interval": 15, "backup_mode": "folder",
            "backup_folder": os.path.join(work, "ziel"), "backup_source_path": "/",
            "backup_block_format": True, "backup_ftp_host": "", "backup_ftp_port": 21,
            "backup_ftp_user": "", "backup_ftp_pass": "", "backup_ftp_path": "/",
        }
        hb.Mirror(lambda: dict(cfg), lambda m, level="info": lines.append(str(m)))._run_pass(
            cfg, reason="Test")
        server.close_all()

        ticks = [l for l in lines if "%" in l]
        done = [l for l in lines if "fertig -" in l]
        assert ticks, lines
        assert all(l.startswith("Sicherung ") and "/3:" in l for l in ticks), ticks
        assert all("MB/s" in l for l in ticks), ticks
        assert any("noch etwa" in l and "gesamt" in l for l in ticks), ticks
        assert len(done) == 3, done
        assert any("gesamt" in l and "noch etwa" in l for l in done[:2]), done
        assert "gesamt" not in done[-1], "die letzte Datei braucht keine Gesamtrestzeit"
        assert "noch etwa unter" not in " ".join(lines), "unschoene Formulierung"
    finally:
        hb.STABLE_S, hb.LOG_PROGRESS_S, hb.CHUNK = stable, progress, chunk
        hb.LocalSink.begin_write = begin_write
        shutil.rmtree(work, ignore_errors=True)


def test_progress_text():
    assert hb.duration_text(45) == "45 s"
    assert hb.duration_text(90) == "1:30 min"
    assert hb.duration_text(7200) == "2:00 h"
    text = hb.progress_text(50 * 1024 * 1024, 100 * 1024 * 1024, 10 * 1024 * 1024)
    assert text.startswith("50 % (50,0 MB von 100,0 MB)"), text
    assert "10,0 MB/s" in text and "noch etwa 5 s" in text, text
    assert hb.eta_text(0, 500, 1000) == "gleich fertig"      # eine halbe Sekunde
    assert hb.eta_text(90, 100, 0) == "" and hb.eta_text(100, 100, 10) == ""
    assert hb.eta_text(0, 64 * 1024**3, 8.8 * 1024**2) == "noch etwa 2:04 h"
    assert hb.parse_mdtm("20260912090013") == datetime.datetime(2026, 9, 12, 9, 0, 13)
    assert hb.parse_mdtm("Unsinn") is None


if __name__ == "__main__":
    test_progress_text(); print("ok  Tacho-Texte")
    test_names();            print("ok  Namensbildung")
    test_system_entries_are_skipped(); print("ok  Systemdateien ausgefiltert")
    test_mdtm_is_converted_to_local_time(); print("ok  Zeitstempel in Ortszeit")
    test_already_saved_under_the_old_name_is_not_copied_again(); print("ok  kein Doppel-Download")
    if HAVE_FTPD:
        test_hyperdeck_quirks(); print("ok  HyperDeck-Eigenheiten")
        test_eta_in_log();       print("ok  Restzeit im Log")
        run_server_tests();      print("ok  Servertests")
    else:
        print("!!  pyftpdlib fehlt - Servertests uebersprungen")
    print("Alle Backup-Tests bestanden.")
