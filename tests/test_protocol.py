# -*- coding: utf-8 -*-
"""Protokollschicht: unaufgeforderte Meldungen des Decks.

Welchen Antwortcode ein Geraet fuer Timecode-Meldungen benutzt, legt das
Protokoll nicht eindeutig fest - dokumentiert sind 500, 502, 508, 510, 511,
519 und 520. Deshalb muss jede Meldung ausgewertet werden, in der ein Timecode
steht, und ein unbekannter Code sichtbar im Log landen.

Start:  python tests/test_protocol.py      (oder: pytest tests/)
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import hyperdeck_control as hc  # noqa: E402
from fake_deck import FakeDeck  # noqa: E402


class Connected(object):
    """Startet ein Simulat und verbindet den echten Protokoll-Leser damit."""

    def __init__(self, **deck_options):
        self.options = deck_options

    def __enter__(self):
        self.deck = FakeDeck(0)
        for key, value in self.options.items():
            setattr(self.deck, key, value)
        port = self.deck.serve()
        self.logs = []
        self._real_log = hc.log
        hc.log = lambda msg, level="info": self.logs.append(str(msg))
        hc._async_unknown.clear()
        hc._last_timecode_msg[0] = 0.0
        hc._async_seen.update(transport=False, slot=False)
        hc.STATE.update(status="stopped", timecode="--:--:--:--", active_slot=None)
        hc.deck.on_async = hc.handle_async
        hc.deck.connect("127.0.0.1", port)
        return self

    def __exit__(self, *exc):
        hc.log = self._real_log
        hc.deck.close()
        self.deck.close()

    def subscribe(self, timecode=True):
        hc.deck.command("notify: transport: true")
        hc.deck.command("notify: slot: true")
        if timecode:
            hc.deck.command("notify: display timecode: true")

    def wait_for_timecode(self, seconds=4.0):
        first = hc.STATE["timecode"]
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            hc.deck.pump(0.1)
            if hc.STATE["timecode"] not in (first, "--:--:--:--"):
                return True
        return False

    def streaming(self):
        return (time.monotonic() - hc._last_timecode_msg[0]) < hc.TIMECODE_STREAM_IDLE_S


def test_transport_notification_updates_state():
    """Der dokumentierte Fall: 508 mit vollem Block."""
    with Connected(status="record") as c:
        c.subscribe()
        assert c.wait_for_timecode(), "Timecode kam nicht an"
        assert hc.STATE["status"] == "record"
        assert c.streaming() is True


def test_display_timecode_513_is_known():
    """So macht es der HyperDeck Studio Mini: Code 513 mit nur dem Timecode.
    Im Protokoll steht dieser Code nicht - er ist am Geraet beobachtet."""
    with Connected(status="record", tc_code=hc.ASYNC_DISPLAY_TC, tc_short=True) as c:
        c.subscribe()
        assert c.wait_for_timecode(), "Timecode aus Code 513 wurde verworfen"
        assert c.streaming() is True
        assert not [l for l in c.logs if "unbekannt" in l], \
            "513 ist bekannt und gehoert nicht als Raetsel ins Log"


def test_unknown_code_with_timecode_is_used_and_reported():
    """Ein Geraet mit einem noch unbekannten Code darf nicht ins Leere laufen."""
    with Connected(status="record", tc_code=517, tc_short=True) as c:
        c.subscribe()
        assert c.wait_for_timecode(), "Timecode aus unbekanntem Code wurde verworfen"
        assert c.streaming() is True
        hinweis = [l for l in c.logs if "unbekannt" in l]
        assert hinweis and "517" in hinweis[0], c.logs
        assert len(hinweis) == 1, "der Hinweis gehoert genau einmal ins Log"


def test_partial_message_keeps_status():
    """Eine Kurzmeldung ohne status darf den Zustand nicht auf 'unbekannt'
    setzen - sonst wuerde Auto-Record mitten in der Aufnahme neu starten."""
    hc.STATE.update(status="record", active_slot=2)
    status, active, changed = hc.apply_transport({"display timecode": "10:00:00:05"})
    assert (status, active, changed) == ("record", 2, False)
    assert hc.STATE["timecode"] == "10:00:00:05"


def test_status_change_is_reported_once_per_change():
    """Bei 50 Meldungen je Sekunde darf nur der echte Wechsel ins Log."""
    with Connected(status="record") as c:
        c.subscribe()
        c.wait_for_timecode()
        vorher = len([l for l in c.logs if l.startswith("Deck meldet:")])
        for _ in range(20):
            hc.deck.pump(0.05)
        assert len([l for l in c.logs if l.startswith("Deck meldet:")]) == vorher, c.logs
        c.deck.set_status("stopped")
        for _ in range(20):
            hc.deck.pump(0.05)
        wechsel = [l for l in c.logs if l.startswith("Deck meldet:")]
        assert wechsel and wechsel[-1] == "Deck meldet: stopped", c.logs
        assert hc._async_seen["transport"] is True, "die Automatik muss anspringen"


def test_silent_rejection_is_detected():
    """Quittiert ein Deck den Wunsch mit ok, schaltet ihn aber nicht ein,
    muss das auffallen - sonst verspricht die Anzeige etwas Falsches."""
    with Connected(status="record", accept_tc_notify=False) as c:
        hc.update_settings({"timecode_live": True}, persist=False)
        hc.enable_notifications(announce=False)
        auskunft = [l for l in c.logs if "eigener Auskunft" in l]
        assert auskunft and "display timecode: false" in auskunft[0], c.logs
        warnung = [l for l in c.logs if "nicht eingeschaltet" in l]
        assert warnung, c.logs
        for _ in range(10):
            hc.deck.pump(0.05)
        assert c.streaming() is False, "ohne Meldungen darf kein Strom angezeigt werden"


def _chunk_run(mode, can_spill):
    """Stellt einen faelligen Abschnittswechsel nach und liefert, was passierte."""
    with Connected(status="record", can_spill=can_spill) as c:
        hc.update_settings({"chunk_interval": 1, "chunk_mode": mode,
                            "sync_timecode": False, "timer_enabled": False}, persist=False)
        hc.STATE.update(status="record", active_slot=2, manual_stop=False)
        hc.chunk_reset()
        hc._chunk_state["started"] = time.monotonic() - 61      # Abschnitt ist faellig
        hc.run_chunker()
        befehle = [x.lower() for x in c.deck.log]
        return {"spills": list(c.deck.spills), "gestoppt": "stop" in befehle,
                "intervall": hc.get_settings()["chunk_interval"], "logs": c.logs}


def test_chunk_is_seamless_by_default():
    """Der Regelfall: record spill auf denselben Slot, ohne Stopp."""
    result = _chunk_run("spill", True)
    assert result["spills"] == [(2, 2)], result
    assert result["gestoppt"] is False, "eine Luecke darf nicht entstehen"
    assert result["intervall"] == 1, "Auto-Chunk bleibt an"
    assert any("nahtlos" in l for l in result["logs"]), result["logs"]


def test_chunk_switches_itself_off_when_spill_is_unsupported():
    """Kann das Deck kein spill, wird abgeschaltet statt heimlich zu stoppen."""
    result = _chunk_run("spill", False)
    assert result["spills"] == [] and result["gestoppt"] is False
    assert result["intervall"] == 0, "muss sich abschalten"
    assert any("spill" in l and "abgeschaltet" in l for l in result["logs"]), result["logs"]


def test_chunk_restart_mode_accepts_the_gap():
    """Wer die Luecke ausdruecklich waehlt, bekommt Stopp und Neustart."""
    result = _chunk_run("restart", False)
    assert result["gestoppt"] is True, result
    assert any("gestoppt und neu gestartet" in l for l in result["logs"]), result["logs"]


def test_chunk_is_idle_without_recording():
    with Connected(status="stopped", can_spill=True) as c:
        hc.update_settings({"chunk_interval": 1}, persist=False)
        hc.STATE.update(status="stopped")
        hc._chunk_state["started"] = time.monotonic() - 600
        hc.run_chunker()
        assert c.deck.spills == [], "ohne Aufnahme wird nicht gestueckelt"
        assert hc.STATE["chunk_info"] == ""
    hc.update_settings({"chunk_interval": 0}, persist=False)


def test_duration_is_clock_notation():
    """Stunden:Minuten wie auf der Uhr - 90 Minuten sind 01:30."""
    assert hc.duration_to_minutes("00:01") == 1
    assert hc.duration_to_minutes("01:30") == 90
    assert hc.duration_to_minutes("1:30") == 90          # fuehrende Null darf fehlen
    assert hc.duration_to_minutes("02:00") == 120
    assert hc.duration_to_minutes("99:59") == 5999
    assert hc.minutes_to_duration(90) == "01:30"
    assert hc.minutes_to_duration(5999) == "99:59"
    assert hc.minutes_to_duration(0) == "00:00"

    # Wer "00:90" tippt, meint 90 Minuten - der Wert wird umgerechnet und
    # danach in richtiger Schreibweise angezeigt, nicht auf 59 gekuerzt.
    assert hc.duration_to_minutes("00:90") == 90
    assert hc.minutes_to_duration(hc.duration_to_minutes("00:90")) == "01:30"

    for unsinn in ("", "abc", "1:2:3", "01-30"):
        try:
            hc.duration_to_minutes(unsinn)
            assert False, "%r haette abgelehnt werden muessen" % unsinn
        except ValueError:
            pass

    hc.update_settings({"chunk_interval": "02:15"}, persist=False)
    assert hc.get_settings()["chunk_interval"] == 135
    hc.update_settings({"chunk_interval": "00:90"}, persist=False)
    assert hc.get_settings()["chunk_interval"] == 90, "Uhr-Schreibweise umrechnen"
    hc.update_settings({"chunk_interval": "99:59"}, persist=False)
    assert hc.get_settings()["chunk_interval"] == 5999, "Obergrenze erreichbar"
    hc.update_settings({"chunk_interval": "150:00"}, persist=False)
    assert hc.get_settings()["chunk_interval"] == 5999, "darueber wird begrenzt"
    hc.update_settings({"chunk_interval": 0}, persist=False)


if __name__ == "__main__":
    names = [n for n in dir() if n.startswith("test_")]
    for name in names:
        globals()[name]()
        print("ok  " + name)
    print("Alle Protokolltests bestanden (%d)." % len(names))
