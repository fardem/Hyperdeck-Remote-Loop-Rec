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

## [3.6.0] – 2026-09-15

Die Oberfläche aus 3.5.0 bleibt, der Unterbau kehrt zu Python zurück.

### Behoben
- **Die Sicherung sicherte nichts.** In 3.5.0 war sie eine Attrappe: ein Timer
  zählte bis sechs und meldete dann „3 Dateien gesichert (24 GB)“ – mit fest
  einprogrammierten Dateinamen, ohne eine Zeile Kopiercode und ohne FTP-Bibliothek
  im Projekt. Auch „Verbindung testen“ meldete Erfolg, ohne etwas zu prüfen.
  Wer darauf vertraut und anschließend eine Karte leert, verliert die Aufnahmen.
  Das echte Sicherungsmodul (`hyperdeck_backup.py`) ist zurück.
- **Ein nicht erreichbares Deck galt als verbunden.** Schlug der Verbindungsaufbau
  fehl, meldete der Dienst „bereit“ und lieferte erfundene Kartenfüllstände,
  einen selbst hochgezählten Timecode und den Zustand „verbunden“. Ein WLAN-Aussetzer
  war damit nicht mehr zu erkennen. Jetzt steht wieder der Fehler da.
- **Das Formatieren war falsch aufgesetzt.** Gesendet wurde ein einzelnes
  `format: slot: {n} …`; das Protokoll verlangt zwei Schritte
  (`format: slot id: {n} prepare: …` → Token → `format: confirm: {token}`).
  Die Oberfläche meldete den Erfolg trotzdem – per Zeitschaltung, nicht nach
  Antwort des Decks. Ebenso `slot info: {n}` statt `slot info: slot id: {n}`.
- **Die Sperre „erst sichern, dann leeren“ war wirkungslos.** `backup_block_format`
  stand in den Einstellungen, wurde im Code aber nie abgefragt.
- **Auto-Chunk, die UTC-Korrektur und die Live-Timecode-Meldungen (Code 513)**
  waren als Schalter vorhanden, ohne Funktion dahinter.
- **Ein verpasster Timer-Stopp wurde nach fünf Minuten aufgegeben.** Fiel das
  Deck genau zum Fensterende kurz aus, lief die Aufnahme die ganze Nacht weiter.
  Der Stopp bleibt jetzt offen, bis er greift – eine später von Hand gestartete
  Aufnahme hebt ihn auf.

### Neu
- Läuft eine Aufnahme außerhalb aller Zeitfenster, weist das Protokoll einmalig
  darauf hin. Gestoppt wird sie nicht, denn sie kann von Hand gestartet worden sein.

### Geändert
- **Bis zu 10 Zeitpläne** statt drei, passend zur neuen Oberfläche.
- Die Oberfläche aus 3.5.0 bleibt unverändert: Reiter-Navigation, kompakte
  Kartenslots, ruhiger Countdown ohne wandernden Balken.
- `start.bat`, die Tests und der CI-Ablauf sind zurück; `server.ts`,
  `package.json`, `tsconfig.json` und `metadata.json` sind entfernt.

---

## [3.5.0] – 2026-09-13

### Neu
- **Bis zu 10 flexible Zeitpläne:** Das Timer-Modul unterstützt jetzt 1 bis 10 unabhängig
  konfigurierbare Zeitpläne mit Wochentagsauswahl, Start- und Endzeit (vorher auf 3 begrenzt).
- **Punktgenauer Timer-Stopp:** Das automatische Stoppen beim Erreichen der Endzeit eines
  Zeitplans wurde fest im Scheduler verankert. Das Deck stoppt planmäßig und schaltet in
  den Modus GESTOPPT.
- **Präzise Countdown- und Statusanzeige:** Der Timer zeigt bei laufender Aufnahme die
  verbleibende Restzeit und außerhalb von Zeitfenstern den nächsten anstehenden Starttermin
  inklusive Wochentag und Countdown (z. B. „Nächster Start: Morgen um 09:00 Uhr in 14 h“).
- **Windows-Dateibrowser / Ordnerauswahl:** Grafischer Verzeichnis-Browser zur bequemen
  Auswahl des lokalen Sicherungsordners ohne manuelle Pfadeingabe.
- **Datumsbasierte Datenträger-Benennung:** Einstellbares Namensmuster für Kartenformatierungen
  mit Platzhaltern (z. B. `Deck_{YYYYMMDD}` oder `Deck_{YYYY-MM-DD}`).
- **Strukturierte Reiter-Navigation:** Aufteilung der Weboberfläche in logische Tabs
  (Steuerung & Automatik, Zeitpläne, Datensicherung, Einstellungen, Protokoll) für
  eine aufgeräumte und übersichtliche Bedienung.

### Geändert
- **Auto-Record vollständig entfernt:** Das eigenmächtige Neustarten der Aufnahme bei Stillstand
  des Decks wurde komplett ausgebaut, um Konflikte mit manuellen Stopps und Timerplänen
  zuverlässig zu verhindern. Aufnahmen erfolgen ausschließlich bewusst manuell oder nach Zeitplan.
- **Beruhigte Kartenslot-Optik:** Wandernde Animationsbalken wurden entfernt, die Slot-Karten
  sind kompakter und übersichtlicher gestaltet.

---

## [3.4.2] – 2026-09-13

### Behoben
- **Die Zeitstempel in den Dateinamen waren UTC statt Ortszeit.** Der Wert
  kommt über `MDTM` vom Deck und ist laut RFC 3659 in UTC – er wurde aber roh
  in den Namen übernommen. Im Sommer waren die Namen damit zwei Stunden zu
  früh, im Winter eine. Jetzt wird in die Ortszeit dieses PCs umgerechnet.
- Ein Clip, der unter dem **alten** Namen bereits im Ziel liegt, wird nicht
  noch einmal geholt. Ohne das hätte die Korrektur das gesamte Archiv erneut
  kopiert, bloß weil die Dateien jetzt anders heißen.

### Neu
- Umschaltung **„Zeitstempel des Decks sind UTC / sind bereits Ortszeit"** für
  Geräte, die sich nicht an die Vorgabe halten.
- „Verbindung testen" zeigt den Vergleich, mit dem sich das prüfen lässt:
  `Deck meldet 13.09. 12:46:11 (UTC) = 14:46:11 Ortszeit, PC-Uhr 14:46:13`.

---

## [3.4.1] – 2026-09-13

### Behoben
- **Auto-Chunk schaltete sich am HyperDeck Studio Mini sofort ab.** Das Gerät
  antwortet auf `record: spill: slot id: {n}` mit `101 unsupported parameter` –
  der Befehl `record spill` existiert also, nur der im Protokoll dokumentierte
  Parameter `slot id` nicht.

  Jetzt gibt es einen Rückfallweg: Lehnt das Deck die Slot-Nummer ab, wird
  `record spill` ohne Parameter geschickt. Die Aufnahme läuft **weiterhin
  nahtlos** weiter, nur eben auf der Nachbarkarte. Das Log erklärt das beim
  ersten Mal, und der aussichtslose Versuch wird danach nicht wiederholt.
  Erst wenn auch das scheitert, schaltet sich die Stückelung ab.

### Dokumentation
- README nennt beide Befehlsformen aus dem Protokoll, den beobachteten
  Unterschied zur Firmware des Studio Mini und die Folge: nahtlos ohne
  Kartenwechsel geht auf diesem Gerät nicht – man hat die Wahl zwischen
  Kartenwechsel (nahtlos) und kurzer Lücke (gleiche Karte). Außerdem: einen
  zeitgesteuerten „Auto-Spill" kennt das Protokoll nicht.

---

## [3.4.0] – 2026-09-12

### Neu
- **Auto-Chunk: Aufnahme in Abschnitte teilen.** Eine laufende Aufnahme ist
  eine offene Datei und kann nicht gesichert werden. Das neue Feld
  **„Aufnahme stückeln alle (HH:MM)"** schließt sie in festem Abstand
  (`00:01` bis `99:59`, `00:00` = aus).

  Die Zeit steht im **Uhr-Raster Stunden:Minuten** – 90 Minuten sind `01:30`.
  Das Feld räumt die Eingabe selbst auf (`00:90` → `01:30`, `45` → `00:45`)
  und erklärt die Schreibweise kurz, statt einen Wert stillschweigend zu
  kürzen.

  Der Regelfall ist **nahtlos**: `record: spill: slot id: {n}` mit der eigenen
  Slot-Nummer. Laut Protokoll wechselt das Deck damit die Datei, **ohne die
  Aufnahme zu unterbrechen** – keine Lücke. Kann ein Gerät das nicht, schaltet
  sich die Stückelung ab und sagt es im Log, statt heimlich zu stoppen. Wer
  die Lücke in Kauf nimmt, stellt die Betriebsart auf „Stopp und neu starten".

### Geändert
- **`513 display timecode` ist jetzt ein bekannter Code.** Am HyperDeck Studio
  Mini bestätigt: Er schickt seine Timecode-Meldungen unter diesem im Protokoll
  nicht dokumentierten Code, mit nur diesem einen Feld. Er wird nicht mehr als
  „unbekannt" gemeldet – die Behandlung fremder Codes bleibt für andere Modelle
  bestehen.

### Dokumentation
- README beantwortet, **von welcher Karte** geholt wird: von beiden, gezielt
  über den jeweiligen FTP-Ordner. Welche Karte das Deck beschreibt, spielt
  dafür keine Rolle. Dazu der Hinweis, dass das Protokolldokument zu FTP
  nichts sagt – das steht im Gerätehandbuch.

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
