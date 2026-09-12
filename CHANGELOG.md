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

## [3.3.2] – 2026-09-12

### Behoben
- **Der Timecode lief am echten Gerät nicht mit**, obwohl der Schalter an war.
  Verarbeitet wurden nur die Codes `508` und `502` – schickt ein Deck seine
  Timecode-Meldung unter einem anderen Code, landete sie im Nichts. Das
  Protokoll legt diesen Code nicht eindeutig fest. Jetzt wird **jede**
  unaufgeforderte Meldung ausgewertet, in der ein Timecode steht, und ein
  unbekannter Code einmal mit Feldliste ins Log geschrieben.
- **Die Anzeige versprach zu viel.** „Läuft" stand schon dort, wenn das Deck
  den Wunsch quittiert hatte. Jetzt gilt der Strom nur als lebendig, wenn in
  den letzten fünf Sekunden tatsächlich Meldungen ankamen – sonst steht
  „Eingeschaltet, aber das Deck schickt nichts".

### Neu
- Nach dem Abonnieren fragt das Programm das Deck mit `notify`, was es nun
  wirklich meldet, und schreibt die Antwort ins Log. Quittiert ein Gerät den
  Wunsch mit „ok", schaltet ihn aber nicht ein, steht das jetzt ausdrücklich
  da statt stillschweigend zu scheitern.
- `tests/test_protocol.py`: fünf Tests für die Meldungsschicht – fremder
  Antwortcode, Kurzmeldung ohne Status, kein Log-Sturm bei 50 Meldungen je
  Sekunde, stillschweigende Ablehnung. Das Simulat kann diese Fälle jetzt
  nachstellen.

---

## [3.3.1] – 2026-09-12

### Behoben
- **Eine nie gesicherte Karte konnte als „gesichert" durchgehen.** Die Prüfung
  vor dem Formatieren sah nur, *ob* zuletzt ein Lauf ohne offene Dateien
  stattfand – nicht, *welche* Karte dieser Lauf abgedeckt hatte. Ein gezielter
  Lauf für Slot 1 ließ damit auch Slot 2 als sauber gelten, und Slot 2 wäre
  geleert worden, ohne je gesichert worden zu sein. Trifft nur bei
  eingeschaltetem „Karte erst leeren, wenn gesichert" und ausgeschalteter
  automatischer Sicherung zu. Der Lauf merkt sich jetzt seinen Umfang.

### Dokumentation
- README erklärt mit Ablaufbild, **wann welche Karte** gesichert wird und dass
  laufend während der Aufnahme gesichert wird – nicht erst beim Kartenwechsel.

---

## [3.3.0] – 2026-09-12

### Neu
- **Der Timecode läuft jetzt live mit.** Bisher wurden nur `transport` und
  `slot` abonniert – die Zeitanzeige bewegte sich deshalb nur im Takt der
  Kontrollabfrage. Mit `notify: display timecode: true` schickt das Deck den
  Transportblock bei jeder Timecode-Änderung, also im Bildtakt.
  Neuer Schalter **„Timecode läuft mit"**, im laufenden Betrieb umschaltbar.

  Gemessen (voller Transportblock, 328 Byte je Meldung): **8,2 kB/s bei
  25 fps, 16,0 kB/s bei 50 fps** – rund 0,13 % einer 100-Mbit-Leitung und
  etwa 0,2 % dessen, was eine laufende FTP-Sicherung zieht.

### Behoben
- **Kurzmeldungen hätten den Status überschreiben können.** Eine
  Transport-Meldung ohne `status`-Feld hätte den Zustand auf „unbekannt“
  gesetzt und damit Auto-Record losgeschickt. Fehlende Felder behalten jetzt
  ihren bisherigen Wert.
- Log und Automatik reagieren nur noch auf **echte** Zustandswechsel. Ohne das
  hätte der Timecode-Strom im Bildtakt beides geflutet.

---

## [3.2.0] – 2026-09-12

### Neu
- **Das Deck meldet Änderungen selbst.** Nach dem Verbinden werden
  `notify: transport: true` und `notify: slot: true` abonniert. Die
  asynchronen `508 transport info:` und `502 slot info:` werden jetzt
  verarbeitet, statt verworfen zu werden. Endet eine Aufnahme oder wechselt
  eine Karte, greift die Automatik **in unter einer Sekunde** – vorher konnte
  es bis zur nächsten Abfrage dauern. Die regelmäßige Abfrage bleibt als
  Sicherheitsnetz; kann ein Deck kein `notify`, läuft alles wie bisher.
- Die Automatik sieht zusätzlich **jede Sekunde** nach, damit eine
  Wiederholsperre (Auto-Record, Timer) keinen Auslöser verschluckt.

### Geändert
- **Verständlichere Oberfläche.** Protokoll-Englisch wird übersetzt
  (`mounted` → „Karte bereit“, `stopped` → „GESTOPPT“), Einzahl und Mehrzahl
  stimmen („1 Minute frei“), lange Restzeiten stehen zusätzlich in Stunden,
  und die Ordner am Deck heißen in der Anzeige „Slot 2“ statt „2“.
- Jeder Abschnitt hat eine Zeile, die erklärt, wofür er da ist. Die Felder
  heißen nach dem, was sie bewirken („Vorbereiten, wenn nur noch … Minuten
  frei“ statt „Vorbereiten ab … Minuten Rest“) und haben kurze Hinweise.
- Selten gebrauchte technische Felder (FTP-Zugang zum Deck, Steuer-Port)
  liegen jetzt in aufklappbaren Bereichen.
- **Warnung, wenn es eng wird:** Läuft die Karte voll und steckt im anderen
  Slot keine, sagt die Oberfläche das deutlich – ebenso, wenn die
  Endlosautomatik dabei ausgeschaltet ist.

### Behoben
- **Windows-Verwaltungskram wurde mitgesichert.** `System Volume Information`,
  `$RECYCLE.BIN`, `.Trashes`, `Thumbs.db` und Konsorten werden jetzt
  übersprungen.

### Hinweis
- Der FTP-Server im HyperDeck verträgt **nur eine Verbindung**. Läuft das
  Programm zweimal oder hängt noch ein FTP-Client am Deck, antwortet es
  versetzt („226 …“, „200 …“). Dann alle anderen Zugriffe schließen.

---

## [3.1.1] – 2026-09-12

### Behoben
- **Die Sicherung scheiterte am echten Gerät** mit „226 Closing data
  connection“. Ursache: Der FTP-Server im HyperDeck kennt `MLSD` und `LIST`
  nicht und lässt nach einem abgelehnten Datenbefehl eine unbeantwortete
  `226` im Steuerkanal liegen. Der nächste Befehl liest sie als seine eigene
  Antwort – ab da ist der Dialog um eine Zeile verschoben, und irgendwann
  meldet ftplib genau diese `226` als Fehler.
  Die FTP-Schicht benutzt jetzt nur noch den kleinsten Befehlssatz, den das
  Gerät sicher beherrscht: `CWD` in den Ordner, dann `NLST`, `SIZE`, `MDTM`
  und `RETR` mit **blanken Dateinamen** (absolute Pfade lehnt das Deck ab).
  Der Download läuft über `retrbinary`, das die Abschlussantwort sauber
  wegliest. Bei jedem Verdacht auf einen verschobenen Dialog wird die
  Verbindung weggeworfen und neu aufgebaut.
- **„Timecode auf Uhrzeit“ blieb wirkungslos.** Es wurde nur
  `configuration: timecode preset` gesendet. Das Deck benutzt den Preset aber
  nur, wenn sein Timecode-Eingang auf `preset` steht – sonst zählt es den
  Timecode aus dem Videosignal weiter. Jetzt wird
  `configuration: timecode input: preset` mitgesendet und die gesetzte Uhrzeit
  im Log bestätigt.

### Neu
- **Tacho im Ereignis-Log:** während langer Übertragungen alle 30 Sekunden
  eine Zeile mit Prozent, übertragener Menge, Geschwindigkeit und Restzeit –
  **für die Datei und für den gesamten Lauf** –, dazu je Datei eine
  Abschlusszeile mit Dauer und Schnitt. Die Restzeit steht auch im
  Statusblock der Oberfläche und beruht auf einer geglätteten
  Geschwindigkeit, damit sie nicht springt.
- **FTP-Dialog im Log:** Geht etwas schief, stehen die letzten Zeilen des
  tatsächlichen FTP-Gesprächs im Log – Fehlersuche ohne Raten.
- **Abfrageintervall ab 1 Sekunde** einstellbar (vorher 5). Der Kartenstatus
  wird dabei auf höchstens alle 5 Sekunden ausgedünnt und Auto-Record
  versucht einen Neustart höchstens alle 10 Sekunden, damit ein kurzes
  Intervall das Deck nicht mit Befehlen überzieht.
- `tests/fake_deck_ftp.py`: FTP-Simulator, der die Eigenheiten des Decks
  nachbildet. Der Regressionstest weist beides nach – dass der alte Weg
  scheitert und der neue durchläuft.

### Hinweis
- Datum und Uhrzeit des Decks lassen sich über das Ethernet-Protokoll **nicht**
  setzen; der dokumentierte Befehlssatz kennt dafür nichts. Die Uhr wird am
  Gerät selbst gestellt. Sie bestimmt die Zeitstempel in den Zieldateinamen.

---

## [3.1.0] – 2026-09-12

### Neu
- **Sicherung der Aufnahmen per FTP** (`hyperdeck_backup.py`). Fertige Clips
  werden vom eingebauten FTP-Server des HyperDecks auf ein Netzlaufwerk
  (Ordner/UNC-Pfad) oder einen FTP-Server (NAS) gespiegelt – automatisch im
  Intervall, per „Jetzt sichern“ oder je Slot („Karte sichern“). Mit
  Fortschrittsanzeige, Abbruch, Verbindungstest und Anzeige des Deck-Inhalts.
  Zieldateien tragen den Aufnahmezeitpunkt im Namen, nichts wird überschrieben
  oder am Deck gelöscht; laufende Aufnahmen werden erkannt und ausgelassen.
- **„Karte erst leeren, wenn gesichert“**: Auto-Loop wartet mit dem
  Formatieren, bis die Clips der Karte gesichert sind.
- **Produktions-Webserver** `waitress` (kein Entwicklungs-Warnhinweis, keine
  Anfrageflut in der Konsole); der Flask-Server bleibt als Ersatz.
- **Rotierende Logdatei** `hyperdeck.log` (1 MB × 3) neben der Konfiguration,
  abrufbar über `/api/log.txt` und den Link „Vollständiges Protokoll“.
- **`HYPERDECK_HOME`**: eigener Ordner für Konfiguration und Log, z. B. für
  eine zweite Instanz mit einem zweiten Deck.
- **Automatisierte Tests** (`tests/`) mit HyperDeck-Simulator und GitHub Action.
- Oberfläche: Tab-Titel zeigt „● REC“, Laufzeit des Dienstes in der Fußzeile,
  Hinweis unter Auto-Record, solange der Timer das Sagen hat,
  „Nicht gespeichert“-Hinweis auch für die Einstellungen, Rückmeldungen als
  kurze Einblendung statt stiller Fehler.

### Geändert
- **Programmordner statt Einzeldatei.** Die Oberfläche liegt jetzt in `ui/`
  (`index.html`, `style.css`, `app.js`) statt als Text im Python-Skript. Beim
  Kopieren immer den ganzen Ordner mitnehmen – fehlt etwas, sagt der Start
  klar, was fehlt.
- Konfiguration wird atomar geschrieben (Temporärdatei + Umbenennen): ein
  Absturz beim Speichern hinterlässt keine kaputte `hyperdeck_config.json`.
- Mehrfaches „Jetzt abfragen“ wird zu einer Abfrage zusammengefasst; die
  Befehlswarteschlange ist begrenzt.
- Auswahlfelder werden serverseitig geprüft (nur erlaubte Werte).
- Passwörter verlassen den Dienst nie: API und Oberfläche zeigen nur, *ob*
  eines hinterlegt ist.

### Behoben
- Sicherung: Nach einer Verzeichnisliste stand die FTP-Verbindung im
  ASCII-Modus; Clips wären beim Kopieren verändert worden. Vor jedem Transfer
  wird jetzt ausdrücklich in den Binärmodus geschaltet und die Größe geprüft.

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
