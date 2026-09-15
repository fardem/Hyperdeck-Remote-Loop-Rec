# -*- coding: utf-8 -*-
"""FTP-Server, der sich wie der HyperDeck verhaelt - fuer die Tests.

Nachgebildete Eigenheiten (so tritt der Fehler "226 Closing data connection"
beim echten Geraet auf):
  * MLSD und LIST kennt das Geraet nicht ...
  * ... und laesst nach dem abgelehnten Datenbefehl eine unbeantwortete
    "226 Closing data connection" im Steuerkanal zurueck. Der naechste Befehl
    liest sie als seine eigene Antwort - ab da ist der Dialog verschoben.
  * Absolute Pfade als Argument werden abgelehnt; es geht nur CWD + blanker Name.

Start von Hand:  python tests/fake_deck_ftp.py <ordner> [port]
"""
import logging
import os
import sys
import threading

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

logging.getLogger("pyftpdlib").addHandler(logging.NullHandler())
logging.getLogger("pyftpdlib").setLevel(logging.CRITICAL)

UNSUPPORTED = ("MLSD", "MLST", "LIST", "STAT")
PATH_COMMANDS = ("NLST", "SIZE", "RETR", "MDTM", "DELE")


class DeckHandler(FTPHandler):
    banner = "220 HyperDeck Studio FTP"

    def decode(self, data):
        line = FTPHandler.decode(self, data)
        self._raw_line = line            # pyftpdlib normalisiert Pfade sonst weg
        return line

    def _raw_arg(self):
        parts = str(getattr(self, "_raw_line", "")).strip().split(" ", 1)
        return parts[1].strip() if len(parts) > 1 else ""

    def process_command(self, cmd, *args, **kwargs):
        if cmd in UNSUPPORTED:
            self.respond("500 Command not understood.")
            # Die Altlast: das Geraet meldet die geschlossene Datenverbindung,
            # obwohl gar keine Uebertragung stattfand.
            self.respond("226 Closing data connection.")
            return
        if cmd in PATH_COMMANDS and self._raw_arg().startswith("/"):
            self.respond("550 Absolute paths are not supported.")
            return
        return FTPHandler.process_command(self, cmd, *args, **kwargs)


def make_server(root, port=0):
    authorizer = DummyAuthorizer()
    authorizer.add_anonymous(root)
    handler = type("Handler", (DeckHandler,), {})
    handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", port), handler)
    return server, server.address[1]


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 2121
    srv, real = make_server(os.path.abspath(folder), port)
    print("Deck-FTP-Simulat auf 127.0.0.1:%d  (%s)" % (real, folder), flush=True)
    srv.serve_forever()
