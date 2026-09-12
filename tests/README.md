# Tests

| Datei | Prüft | Braucht |
| --- | --- | --- |
| `test_timer.py` | Zeitplan-Logik und Zustandsautomat des Timers | nichts |
| `test_backup.py` | FTP-Sicherung gegen zwei lokale FTP-Server | `pip install pyftpdlib` |
| `test_api.py` | Weboberfläche und API gegen ein simuliertes Deck | nichts |
| `fake_deck.py` | HyperDeck-Simulator (Port 9993 oder Argument) für Handtests | nichts |

Alles auf einmal: `pytest -q tests/` – oder jede Datei einzeln mit `python tests/<datei>.py`.
Der Simulator lässt sich auch allein starten, um die Oberfläche ohne Deck auszuprobieren:

```bash
python tests/fake_deck.py            # Port 9993
python hyperdeck_control.py --ip 127.0.0.1
```
