# -*- coding: utf-8 -*-
"""Minimales HyperDeck-Simulat (Ethernet-Protokoll) fuer Tests.

Start: python tests/fake_deck.py [port]   (Standard 9993)
"""
import socket, threading, sys, time

state = {"status": "stopped", "log": []}

def client(conn):
    conn.sendall(b"500 connection info:\r\nprotocol version: 1.11\r\nmodel: HyperDeck Studio Test\r\n\r\n")
    buf = b""
    while True:
        try:
            chunk = conn.recv(4096)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            cmd = line.decode("utf-8", "replace").strip()
            if not cmd:
                continue
            state["log"].append(cmd)
            print("DECK <- %s" % cmd, flush=True)
            if cmd == "transport info":
                conn.sendall(("208 transport info:\r\nstatus: %s\r\nslot id: 1\r\n"
                              "timecode: 10:00:00:00\r\n\r\n" % state["status"]).encode())
            elif cmd.startswith("slot info"):
                sid = cmd.strip()[-1]
                conn.sendall(("202 slot info:\r\nslot id: %s\r\nstatus: mounted\r\n"
                              "volume name: TestCard\r\nrecording time: 3600\r\n\r\n" % sid).encode())
            elif cmd == "record":
                state["status"] = "record"
                conn.sendall(b"200 ok\r\n")
            elif cmd == "stop":
                state["status"] = "stopped"
                conn.sendall(b"200 ok\r\n")
            else:
                conn.sendall(b"200 ok\r\n")

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9993
srv.bind(("127.0.0.1", PORT))
srv.listen(5)
print("Fake-Deck laeuft auf 127.0.0.1:%d" % PORT, flush=True)
while True:
    conn, _ = srv.accept()
    threading.Thread(target=client, args=(conn,), daemon=True).start()
