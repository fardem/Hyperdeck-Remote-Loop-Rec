# -*- coding: utf-8 -*-
"""HyperDeck-Simulat (Ethernet-Protokoll, Port 9993) fuer Tests und Handproben.

Kann das Noetigste: transport info, slot info, record, stop, format-Antworten -
und vor allem "notify": dann meldet es Aenderungen von sich aus als
asynchrone 508/502-Bloecke, genau wie ein echtes Geraet.

Start:  python tests/fake_deck.py [port] [--stop-after SEKUNDEN]
        --stop-after laesst die Aufnahme von selbst enden (Signalverlust proben)
"""
import socket
import sys
import threading
import time

CRLF = "\r\n"


class FakeDeck(object):
    def __init__(self, port=9993, stop_after=0.0, model="HyperDeck Studio Test"):
        self.port = port
        self.stop_after = stop_after
        self.model = model
        self.status = "stopped"
        self.slots = {1: {"status": "mounted", "volume": "TestCard", "recording time": 3600},
                      2: {"status": "mounted", "volume": "TestCard2", "recording time": 3600}}
        self.active = 1
        self.frame = 0                      # zaehlt den Timecode hoch
        self.tc_rate = 0.04                 # 25 Bilder je Sekunde
        self.tc_code = 508                  # Code der Timecode-Meldung
        self.tc_short = False               # nur Timecode statt vollem Block
        self.accept_tc_notify = True        # False: Wunsch wird nur quittiert
        self.log = []
        self.clients = []
        self.lock = threading.Lock()
        self.server = None

    # ---- Antwortbausteine -------------------------------------------------

    def timecode(self):
        total = self.frame
        return "%02d:%02d:%02d:%02d" % (10 + total // (25 * 3600),
                                        (total // (25 * 60)) % 60,
                                        (total // 25) % 60, total % 25)

    def transport_block(self, code=208):
        """Vollstaendiger Block wie im Protokoll - damit Messungen der
        Netzlast auch etwas taugen."""
        tc = self.timecode()
        fields = [
            ("status", self.status),
            ("speed", "0"),
            ("slot id", str(self.active)),
            ("slot name", self.slots[self.active]["volume"]),
            ("device name", "HyperDeck Studio Mini"),
            ("clip id", "3"),
            ("single clip", "false"),
            ("display timecode", tc),
            ("timecode", tc),
            ("video format", "1080p25"),
            ("loop", "false"),
            ("timeline", "1"),
            ("input video format", "1080p25"),
            ("dynamic range", "none"),
            ("reference locked", "false"),
        ]
        body = "".join("%s: %s%s" % (key, value, CRLF) for key, value in fields)
        return "%d transport info:%s%s%s" % (code, CRLF, body, CRLF)

    def slot_block(self, slot_id, code=202):
        slot = self.slots[slot_id]
        return ("%d slot info:%sslot id: %d%sstatus: %s%svolume name: %s%s"
                "recording time: %d%s%s" % (code, CRLF, slot_id, CRLF, slot["status"], CRLF,
                                            slot["volume"], CRLF, slot["recording time"],
                                            CRLF, CRLF))

    # ---- unaufgeforderte Meldungen ---------------------------------------

    def announce(self, what, slot_id=None):
        """Schickt allen Клients, die es abonniert haben, eine 5xx-Meldung."""
        with self.lock:
            targets = list(self.clients)
        for conn, wants in targets:
            if not wants.get(what if what != "timecode" else "display timecode"):
                continue
            text = (self.transport_block(508) if what == "transport"
                    else self.slot_block(slot_id or self.active, 502))
            try:
                conn.sendall(text.encode("utf-8"))
            except OSError:
                pass

    def set_status(self, status, announce=True):
        self.status = status
        if announce:
            self.announce("transport")

    def set_slot(self, slot_id, **fields):
        self.slots[slot_id].update(fields)
        self.announce("slot", slot_id)

    # ---- Verbindungen -----------------------------------------------------

    def timecode_message(self):
        """Voller Transportblock oder nur der Timecode - je nach Einstellung.
        Echte Geraete unterscheiden sich hier, deshalb beides pruefbar."""
        if not self.tc_short:
            return self.transport_block(self.tc_code)
        return ("%d display timecode:%sdisplay timecode: %s%stimecode: %s%s%s"
                % (self.tc_code, CRLF, self.timecode(), CRLF, self.timecode(), CRLF, CRLF))

    def _timecode_ticker(self):
        """Schickt Timecode-Meldungen im Bildtakt - so wie ein echtes Deck mit
        'notify: display timecode: true'."""
        while True:
            time.sleep(self.tc_rate)
            self.frame += 1
            if not self.accept_tc_notify:
                continue
            with self.lock:
                listeners = [(c, w) for c, w in self.clients if w.get("display timecode")]
            for conn, _wants in listeners:
                try:
                    conn.sendall(self.timecode_message().encode("utf-8"))
                except OSError:
                    pass

    def serve(self):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", self.port))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._timecode_ticker, daemon=True).start()
        return self.port

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def close(self):
        try:
            self.server.close()
        except Exception:
            pass

    def _client(self, conn):
        wants = {"transport": False, "slot": False, "display timecode": False}
        with self.lock:
            self.clients.append((conn, wants))
        conn.sendall(("500 connection info:%sprotocol version: 1.11%smodel: %s%s%s"
                      % (CRLF, CRLF, self.model, CRLF, CRLF)).encode("utf-8"))
        buf = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = line.decode("utf-8", "replace").strip()
                    if cmd:
                        self._command(conn, wants, cmd)
        except OSError:
            return
        finally:
            with self.lock:
                self.clients = [(c, w) for c, w in self.clients if c is not conn]
            try:
                conn.close()
            except Exception:
                pass

    def _command(self, conn, wants, cmd):
        self.log.append(cmd)
        low = cmd.lower()
        send = lambda text: conn.sendall(text.encode("utf-8"))

        if low == "transport info":
            send(self.transport_block())
        elif low.startswith("slot info"):
            slot_id = 2 if "slot id: 2" in low else 1
            send(self.slot_block(slot_id))
        elif low.startswith("notify:"):
            for key in ("transport", "slot", "display timecode"):
                if "%s: true" % key in low:
                    wants[key] = True
                elif "%s: false" % key in low:
                    wants[key] = False
            send("200 ok" + CRLF)
        elif low == "notify":
            # Auskunft ueber den tatsaechlichen Zustand. Ein Geraet, das
            # accept_tc_notify=False hat, gibt hier ehrlich "false" zurueck.
            live = wants["display timecode"] and self.accept_tc_notify
            send("209 notify:%stransport: %s%sslot: %s%sremote: false%s"
                 "configuration: false%sdisplay timecode: %s%s%s"
                 % (CRLF, str(wants["transport"]).lower(), CRLF,
                    str(wants["slot"]).lower(), CRLF, CRLF, CRLF,
                    str(live).lower(), CRLF, CRLF))
        elif low == "record":
            self.set_status("record")          # Meldung kommt VOR der Antwort
            send("200 ok" + CRLF)
            if self.stop_after > 0:
                threading.Timer(self.stop_after, self._spontaneous_stop).start()
        elif low == "stop":
            self.set_status("stopped")
            send("200 ok" + CRLF)
        else:
            send("200 ok" + CRLF)

    def _spontaneous_stop(self):
        """Das Deck hoert von selbst auf - z. B. Signalverlust."""
        if self.status == "record":
            self.set_status("stopped")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    port = 9993
    stop_after = 0.0
    if args and args[0].isdigit():
        port = int(args.pop(0))
    if "--stop-after" in args:
        stop_after = float(args[args.index("--stop-after") + 1])
    deck = FakeDeck(port, stop_after)
    print("Fake-Deck laeuft auf 127.0.0.1:%d" % deck.serve(), flush=True)
    while True:
        time.sleep(3600)
