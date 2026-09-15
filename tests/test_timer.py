# -*- coding: utf-8 -*-
"""Zeitplan-Logik und Zustandsautomat des Timers - ohne Deck, ohne Netz.

Start:  python tests/test_timer.py      (oder: pytest tests/)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hyperdeck_control as hc  # noqa: E402

MO = datetime.datetime(2026, 9, 7, 0, 0)          # ein Montag


def at(day_offset, hour, minute):
    return MO + datetime.timedelta(days=day_offset, hours=hour, minutes=minute)


def base_cfg(**over):
    cfg = dict(hc.DEFAULT_SETTINGS)
    cfg["timers"] = hc.normalize_timers([])
    cfg["timer_count"] = 1
    cfg["timer_enabled"] = True
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------- Normalisierung

def test_parse_hhmm():
    assert hc.parse_hhmm("8:45") == "08:45"
    assert hc.parse_hhmm("08:45:00") == "08:45"
    assert hc.parse_hhmm("abc", "18:30") == "18:30"
    assert hc.parse_hhmm("99:99", "07:00") == "07:00"


def test_normalize_days():
    assert hc.normalize_days("0,1,2", []) == [0, 1, 2]
    assert hc.normalize_days("Mo,Fr,So", []) == [0, 4, 6]
    assert hc.normalize_days([4, 0, 4, 9, -1], []) == [0, 4]


def test_normalize_timers():
    timers = hc.normalize_timers([])
    assert len(timers) == hc.TIMER_SLOTS
    assert timers[0] == {"enabled": True, "days": [0, 1, 2, 3, 4], "start": "08:45", "end": "18:30"}
    junk = hc.normalize_timers([{"enabled": "on", "days": "1", "start": "7", "end": "x"}])[0]
    assert junk == {"enabled": True, "days": [1], "start": "08:45", "end": "18:30"}
    assert hc.describe_days([0, 1, 2, 3, 4]) == "Mo-Fr"
    assert hc.describe_days([1, 3]) == "Di+Do"


# ---------------------------------------------------------------- Fenster

def test_default_window():
    cfg = base_cfg()
    assert hc.find_active_timer(cfg, at(0, 8, 44))[0] is None
    assert hc.find_active_timer(cfg, at(0, 8, 45))[0] == 0
    assert hc.find_active_timer(cfg, at(0, 18, 29))[0] == 0
    assert hc.find_active_timer(cfg, at(0, 18, 30))[0] is None
    assert hc.find_active_timer(cfg, at(5, 12, 0))[0] is None          # Samstag


def test_multiple_plans_and_count():
    cfg = base_cfg(timer_count=2, timers=hc.normalize_timers([
        {"enabled": True, "days": [0, 1, 2, 3, 4], "start": "08:45", "end": "18:30"},
        {"enabled": True, "days": [5, 6], "start": "10:00", "end": "12:00"},
        {"enabled": True, "days": [0], "start": "20:00", "end": "21:00"},
    ]))
    assert hc.find_active_timer(cfg, at(5, 11, 0))[0] == 1
    assert hc.find_active_timer(cfg, at(5, 13, 0))[0] is None
    assert hc.find_active_timer(cfg, at(0, 20, 30))[0] is None         # Plan 3 nicht gezaehlt
    cfg["timer_count"] = 3
    assert hc.find_active_timer(cfg, at(0, 20, 30))[0] == 2


def test_overnight_window():
    cfg = base_cfg(timers=hc.normalize_timers(
        [{"enabled": True, "days": [4], "start": "22:00", "end": "06:00"}]))
    assert hc.find_active_timer(cfg, at(4, 21, 59))[0] is None
    assert hc.find_active_timer(cfg, at(4, 23, 30))[0] == 0
    assert hc.find_active_timer(cfg, at(5, 5, 59))[0] == 0
    assert hc.find_active_timer(cfg, at(5, 6, 0))[0] is None
    assert hc.find_active_timer(cfg, at(6, 23, 30))[0] is None
    # Kennung bleibt ueber Mitternacht dieselbe
    assert hc.find_active_timer(cfg, at(4, 23, 30))[2] == hc.find_active_timer(cfg, at(5, 5, 59))[2]


def test_next_start_and_degenerate_windows():
    cfg = base_cfg()
    when, idx = hc.next_timer_start(cfg, at(0, 7, 0))
    assert (when.day, when.hour, when.minute, idx) == (7, 8, 45, 0)
    when, _ = hc.next_timer_start(cfg, at(0, 19, 0))
    assert (when.day, when.hour) == (8, 8)
    when, _ = hc.next_timer_start(cfg, at(4, 19, 0))
    assert when.day == 14                                              # Montag drauf
    off = base_cfg(timers=hc.normalize_timers([{"enabled": False}] * 3))
    assert hc.next_timer_start(off, at(0, 7, 0))[0] is None
    zero = base_cfg(timers=hc.normalize_timers(
        [{"enabled": True, "days": [0], "start": "09:00", "end": "09:00"}]))
    assert hc.find_active_timer(zero, at(0, 9, 30))[0] is None
    nodays = base_cfg(timers=hc.normalize_timers(
        [{"enabled": True, "days": [], "start": "00:00", "end": "23:59"}]))
    assert hc.find_active_timer(nodays, at(0, 9, 30))[0] is None


# ---------------------------------------------------------------- Zustandsautomat

class FakeClock(object):
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def time(self):
        return self.t


class Harness(object):
    """Ersetzt Deckbefehle und Uhr, protokolliert die Befehle."""

    def __init__(self):
        self.calls = []
        self.clock = FakeClock()
        self._real_time = hc.time
        self._real_record, self._real_stop = hc.do_record, hc.do_stop

    def __enter__(self):
        hc.time = self.clock
        hc.do_record = self.record
        hc.do_stop = self.stop
        return self

    def __exit__(self, *exc):
        hc.time = self._real_time
        hc.do_record, hc.do_stop = self._real_record, self._real_stop

    def record(self, manual=False):
        self.calls.append("record")
        hc.set_state(status="record", manual_stop=False)
        return True

    def stop(self, manual=False):
        self.calls.append("stop")
        hc.set_state(status="stopped")
        if manual:
            hc.set_state(manual_stop=True)
        return True

    def reset(self, timer_enabled=True, count=1, timers=None, status="stopped"):
        self.calls[:] = []
        self.clock.t = 1000.0
        hc._timer_state.update({"window": None, "index": None, "next_try": 0.0,
                                "stop_until": 0.0, "next_desc": 0.0})
        hc.update_settings({
            "timer_enabled": timer_enabled, "timer_count": count,
            "timers": timers if timers is not None else hc.normalize_timers([]),
        }, persist=False)
        hc.set_state(status=status, manual_stop=False, timer_active=None)


def test_state_machine_default_day():
    with Harness() as h:
        h.reset()
        hc.run_timer(at(0, 8, 0));    assert h.calls == []
        hc.run_timer(at(0, 8, 45));   assert h.calls == ["record"]
        hc.run_timer(at(0, 12, 0));   assert h.calls == ["record"]
        assert hc.STATE["timer_active"] == 1
        hc.run_timer(at(0, 18, 30));  assert h.calls == ["record", "stop"]
        assert hc.STATE["timer_active"] is None
        h.clock.t += 30
        hc.run_timer(at(0, 18, 31));  assert h.calls == ["record", "stop"]


def test_state_machine_recovers_lost_recording():
    with Harness() as h:
        h.reset()
        hc.run_timer(at(0, 9, 0));    assert h.calls == ["record"]
        hc.set_state(status="stopped")
        hc.run_timer(at(0, 9, 1));    assert h.calls == ["record"]          # Wiederholsperre
        h.clock.t += hc.TIMER_RETRY_S + 1
        hc.run_timer(at(0, 9, 2));    assert h.calls == ["record", "record"]


def test_state_machine_manual_stop_and_next_day():
    with Harness() as h:
        h.reset()
        hc.run_timer(at(0, 9, 0))
        hc.do_stop(manual=True)
        h.clock.t += 60
        hc.run_timer(at(0, 9, 5));    assert h.calls == ["record", "stop"]
        hc.run_timer(at(1, 8, 45));   assert h.calls == ["record", "stop", "record"]
        assert hc.STATE["manual_stop"] is False


def test_records_at_start_time_and_stops_at_end_time():
    """Der Kern des Zeitplans: Punkt 08:45 laeuft die Aufnahme, Punkt 18:30 nicht mehr."""
    with Harness() as h:
        h.reset()
        hc.run_timer(at(0, 8, 44));   assert h.calls == []          # eine Minute davor
        hc.run_timer(at(0, 8, 45));   assert h.calls == ["record"]  # auf die Minute
        hc.set_state(status="record")
        hc.run_timer(at(0, 12, 0));   assert h.calls == ["record"]  # laeuft durch
        hc.run_timer(at(0, 18, 30));  assert h.calls == ["record", "stop"]


def test_missed_stop_is_retried_until_it_works():
    """Ein Aussetzer zum Feierabend darf die Aufnahme nicht die Nacht durchlaufen
    lassen. Frueher wurde der Stopp nach fuenf Minuten aufgegeben."""
    with Harness() as h:
        h.reset()
        hc.run_timer(at(0, 9, 0))
        hc.set_state(status="record")
        hc.run_timer(at(0, 18, 30));  assert h.calls == ["record", "stop"]

        # Das Deck ist eine Dreiviertelstunde nicht erreichbar, nimmt also weiter auf.
        for minute in (31, 45, 59):
            hc.set_state(status="record")
            h.clock.t += hc.TIMER_RETRY_S + 1
            hc.run_timer(at(0, 18, minute))
        assert h.calls == ["record", "stop", "stop", "stop", "stop"]

        # Sobald das Deck antwortet, ist Ruhe - es wird nicht weiter gestoppt.
        hc.set_state(status="stopped")
        h.clock.t += hc.TIMER_RETRY_S + 1
        hc.run_timer(at(0, 19, 30));  assert h.calls == ["record", "stop", "stop", "stop", "stop"]


def test_manual_record_after_the_window_is_left_alone():
    """Wer nach Feierabend bewusst auf Aufnahme drueckt, wird nicht ausgebremst."""
    with Harness() as h:
        h.reset()
        hc.run_timer(at(0, 9, 0))
        hc.set_state(status="record")
        hc.run_timer(at(0, 18, 30));  assert h.calls == ["record", "stop"]

        hc.handle_job({"action": "record"})       # von Hand, ausserhalb des Fensters
        hc.set_state(status="record")
        h.clock.t += hc.TIMER_RETRY_S + 1
        hc.run_timer(at(0, 19, 0))
        assert h.calls == ["record", "stop", "record"]    # kein erneuter Stopp


def test_state_machine_disabled_and_two_plans():
    with Harness() as h:
        h.reset(timer_enabled=False)
        hc.run_timer(at(0, 8, 45));   assert h.calls == []
        assert hc.STATE["timer_info"] == "Timer aus"
        h.reset(count=2, timers=hc.normalize_timers([
            {"enabled": True, "days": [0], "start": "08:45", "end": "12:00"},
            {"enabled": True, "days": [0], "start": "14:00", "end": "18:30"},
        ]))
        hc.run_timer(at(0, 9, 0));    assert h.calls == ["record"]
        hc.run_timer(at(0, 12, 0));   assert h.calls == ["record", "stop"]
        h.clock.t += 60
        hc.run_timer(at(0, 13, 0));   assert h.calls == ["record", "stop"]
        hc.run_timer(at(0, 14, 0));   assert h.calls == ["record", "stop", "record"]
        assert hc.STATE["timer_active"] == 2


def test_automation_gating():
    with Harness() as h:
        h.reset()
        hc.update_settings({"loop_record": True, "auto_record": True}, persist=False)
        hc.set_state(status="stopped", manual_stop=False)
        h.calls[:] = []
        hc.run_automation("stopped", None, [])
        assert h.calls == []                                   # Timer scharf -> Auto-Record schweigt
        hc.update_settings({"timer_enabled": False}, persist=False)
        hc.run_automation("stopped", None, [])
        assert h.calls == ["record"]
        hc.update_settings({"loop_record": False}, persist=False)
        h.calls[:] = []
        hc.set_state(status="stopped")
        hc.run_automation("stopped", None, [])
        assert h.calls == []                                   # Hauptschalter aus


if __name__ == "__main__":
    names = [n for n in dir() if n.startswith("test_")]
    for name in names:
        globals()[name]()
        print("ok  " + name)
    print("Alle Timer-Tests bestanden (%d)." % len(names))
