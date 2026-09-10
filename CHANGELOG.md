# Änderungsprotokoll

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionsnummern folgen der [Semantischen Versionierung](https://semver.org/lang/de/):
**MAJOR.MINOR.PATCH** – MAJOR bei Verhaltensänderungen, MINOR bei neuen Funktionen,
PATCH bei Fehlerbehebungen.

> Die laufende Version steht oben rechts in der Weboberfläche, in der Fußzeile,
> in der Startmeldung der Konsole und in `hyperdeck_control.py` (`APP_VERSION`).
> Auf GitHub gehört zu jeder Version ein Tag (`v3.0.0`) und ein Release-Eintrag.

---

## [3.0.0] – 2026-09-10

### Neu
- **Timer-Aufnahme (Zeitsteuerung).** Bis zu drei Zeitpläne („Autorecord 1–3“)
  mit Wochentagen, Start- und Endzeit. Der Rekorder startet und stoppt ohne
  Zutun. Voreinstellung: Mo–Fr von **08:45 bis 18:30 Uhr**.
- **Anzahl der Zeitpläne einstellbar** (1–3): Es werden genau so viele Zeilen
  eingeblendet, wie eingestellt sind.
- **Zeitfenster über Mitternacht.** Ist die Endzeit kleiner als die Startzeit
  (z. B. 22:00–06:00), läuft die Aufnahme über den Tageswechsel hinweg.
- **Hauptschalter „Loop-Record“.** Schaltet die gesamte Endlos-Automatik
  (Auto-Record und Auto-Loop) auf einen Griff aus; die Unterschalter werden
  dann sichtbar gesperrt.
- **Versionsanzeige** in der Kopfzeile der Weboberfläche, in der Fußzeile und
  in der Startmeldung der Konsole.
- **Automatischer Browserstart.** Nach dem Start öffnet sich die Oberfläche von
  selbst mit der richtigen Adresse (`--no-browser` schaltet das ab).
- **`start.bat` neu geschrieben.** Sucht Python (`py` oder `python`),
  installiert die Abhängigkeiten sichtbar, zeigt alle Meldungen an und hält das
  Fenster in jedem Fall offen – auch bei Fehlern.
- `--version` und `--no-browser` als Startparameter, `LICENSE`, `CHANGELOG.md`
  und `.gitignore` ergänzt.

### Geändert
- Das Ereignis-Log wird nur noch **inkrementell** übertragen: Der Browser fragt
  im Sekundentakt nur die neuen Zeilen ab (`/api/status?since=…`) statt jedes
  Mal alle 250. Deutlich weniger Netzlast und Rechenarbeit.
- Bei scharfem Timer entscheidet allein der Zeitplan über Start und Stopp.
  Auto-Record kann einen Timer-Stopp nicht mehr überrennen.
- Verpasste Timer-Befehle (Deck offline, Netzwerkstörung) werden bis zu
  fünf Minuten lang wiederholt, statt verloren zu gehen.
- Eingaben werden serverseitig hart normalisiert: aus `8:45` wird `08:45`,
  unsinnige Werte fallen auf die Vorgabe zurück.

### Entfernt
- Der Hinweis **„Veraltete Oberfläche – neu laden“** samt Versionsabgleich
  zwischen Browser und Dienst. Das Zwischenspeichern wird bereits durch die
  `no-store`-Kopfzeilen verhindert; der Hinweis war überflüssig.

### Behoben
- **Leere Hinweisbalken.** `.notice{display:flex}` überstimmte das
  `hidden`-Attribut, dadurch blieben ausgeblendete Hinweise als leere Balken
  stehen (`[hidden]{display:none!important}`).
- **Verriegelung nach manuellem Stopp.** Ein manueller Stopp innerhalb eines
  Zeitfensters hätte alle folgenden Termine desselben Zeitplans blockiert.
  Jeder Termin wird jetzt einzeln erkannt (Kennung aus Zeitplan + Datum).
- Zahleneingaben wie `20.0` führten zu einem Abbruch der Übernahme.
- Umlaute konnten den Start auf Konsolen mit exotischer Codepage stören.

---

## [2.1.0] – 2026-08-16

### Neu
- Entkoppelte Architektur: genau ein Worker-Thread besitzt genau eine dauerhafte
  TCP-Verbindung, die Weboberfläche kommuniziert ausschließlich über eine Queue.
- Zeilenbasierter Protokoll-Parser nach Antwortcodes, asynchrone 5xx-Meldungen
  werden herausgefiltert.
- Auto-Record, Auto-Loop, Timecode-Synchronisation, Zwei-Phasen-Formatierung
  mit Token, Weboberfläche im Dunkelmodus, Live-Konfiguration.
