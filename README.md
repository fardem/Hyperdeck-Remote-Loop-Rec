# 🎛️ Blackmagic HyperDeck Web Control & Auto-Loop

Ein ausfallsicherer, thread-entkoppelter Web-Controller mit Endlosaufnahme-Automatik (**24/7 Loop-Recording**) für **Blackmagic Design HyperDeck Studio** Recorder über das Ethernet-Protokoll (Port 9993).

![Python](https://img.shields.io/badge/Python-3.7%2B-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/WebUI-Flask-black?logo=flask&logoColor=white)
![Hardware](https://img.shields.io/badge/Hardware-BM%20HyperDeck-red)
![Version](https://img.shields.io/badge/Version-3.1.0-blueviolet)
![Tests](https://github.com/fardem/Hyperdeck-Remote-Loop-Rec/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 📖 Inhaltsverzeichnis

1. [Überblick & Einsatzzwecke](#-überblick--einsatzzwecke)
2. [Hauptfunktionen](#-hauptfunktionen)
3. [Architektur & Stabilität](#️-architektur--stabilität)
4. [Installation & Schnellstart](#-installation--schnellstart)
5. [Aufruf der Weboberfläche](#-aufruf-der-weboberfläche)
6. [Übersicht der Web-UI & Einstellungen](#️-übersicht-der-web-ui--einstellungen)
7. [Timer-Aufnahme (Zeitsteuerung)](#-timer-aufnahme-zeitsteuerung)
8. [Sicherung der Aufnahmen (FTP)](#-sicherung-der-aufnahmen-ftp)
9. [CLI-Startparameter](#️-cli-startparameter)
10. [REST-API Dokumentation](#-rest-api-dokumentation)
11. [Tests](#-tests)
12. [Fehlerbehebung (Troubleshooting)](#-fehlerbehebung-troubleshooting)
13. [Versionierung & Änderungsprotokoll](#-versionierung--änderungsprotokoll)
14. [Lizenz](#-lizenz)

---

## 🎯 Überblick & Einsatzzwecke

Standardmäßig stoppt ein Blackmagic HyperDeck die Aufnahme, sobald beide eingelegten Speicherkarten voll sind. Dieses Tool überwacht das Deck kontinuierlich und ermöglicht eine **unterbrechungsfreie Endlosaufnahme über ein lange Zeit hinweg**. Droht die aktuell beschriebene Karte vollzulaufen, bereinigt das Skript die inaktive Nachbarkarte vollautomatisch über das offizielle 2-Phasen-Token-Protokoll von Blackmagic Design.

### Typische Einsatzbereiche:
* **24/7 Daueraufzeichnung (Dashcam-/Ringspeicher-Prinzip):** Für Studios, Kirchen, Hörsäle oder Überwachungs-Feeds, bei denen immer die letzten Stunden oder Tage verfügbar sein müssen, ohne manuell Speicherkarten zu tauschen oder zu leeren.
* **Compliance- & Sende-Logging:** Zuverlässige Protokollierung von Live-Sendungen und Event-Feeds zur rechtlichen Absicherung oder Fehlersuche.
* **Rack-Fernsteuerung (Studio / Ü-Wagen):** Volle Kontrolle über das Deck von jedem PC, Laptop, Tablet oder Smartphone im Netzwerk, ohne vor das 19"-Geräterack treten zu müssen.

---

## ✨ Hauptfunktionen

* 🔄 **Intelligenter Auto-Loop:** Erkennt, wenn die aktive Karte unter den eingestellten Schwellenwert fällt (z. B. `< 5 Min.`), und formatiert die inaktive Karte rechtzeitig vor dem automatischen Slot-Wechsel.
* 🔴 **Auto-Record:** Startet die Aufnahme selbstständig neu, falls das Gerät steht (z. B. nach Signalverlust oder Stromausfall).
* 🎚️ **Hauptschalter „Loop-Record“:** Schaltet die komplette Endlos-Automatik mit einem Klick aus – das Werkzeug wird dann zur reinen Fernbedienung.
* ⏰ **Timer-Aufnahme:** Bis zu drei Zeitpläne mit Wochentagen und Uhrzeiten (Vorgabe **Mo–Fr 08:45–18:30 Uhr**). Der Rekorder startet und stoppt ohne Zutun, auch über Mitternacht hinweg.
* 💾 **Sicherung der Aufnahmen:** Fertige Clips werden über den FTP-Server des HyperDecks auf ein **Netzlaufwerk** (UNC-Pfad, Laufwerksbuchstabe) oder einen **FTP-Server** (NAS) gespiegelt – automatisch im Intervall oder per Knopfdruck, mit Fortschrittsanzeige. Auf Wunsch leert Auto-Loop eine Karte erst, wenn ihre Clips gesichert sind.
* 🔒 **Manueller Stopp-Schutz (Safety Interlock):** Drückt ein Operator manuell auf „Stopp“, verriegelt sich Auto-Record. Die Automatik funkt nicht eigenmächtig dazwischen, bis sie explizit freigegeben oder eine neue Aufnahme gestartet wird.
* 🕒 **Timecode-Synchronisation:** Setzt den Start-Timecode des Decks auf Wunsch automatisch auf die aktuelle PC-Systemzeit (`HH:MM:SS:00`).
* ⚡ **BM-Token-Formatierung:** Vollständige Unterstützung des zweistufigen Blackmagic-Protokolls (`prepare` $\rightarrow$ `Token auslesen` $\rightarrow$ `confirm`) inklusive 180-Sekunden-Cooldown gegen Mehrfach-Löschungen.
* 🌐 **Responsives Dark-Mode Webinterface:** Timecode, Tally, Füllstandsbalken, Live-Countdown und Systemlog synchronisieren sich verzögerungsfrei und flüssig im Browser.
* 💾 **Live-Konfiguration:** Alle Parameter sind im laufenden Betrieb in der Web-UI änderbar und werden persistent in `hyperdeck_config.json` gespeichert.
* 🚀 **Startet und öffnet sich selbst:** `start.bat` (Windows) bzw. `start.sh` prüft Python, installiert die Abhängigkeiten und startet den Dienst – der Browser geht automatisch mit der richtigen Adresse auf. Das Konsolenfenster bleibt in jedem Fall offen.
* 🏷️ **Sichtbare Version:** Die laufende Programmversion steht in der Kopf- und Fußzeile der Oberfläche sowie in der Startmeldung der Konsole.
* 🧱 **Für den Dauerbetrieb gebaut:** Produktions-Webserver (waitress), rotierende Logdatei `hyperdeck.log`, atomar geschriebene Konfiguration, automatisierte Tests bei jedem Push.

---

## 🏗️ Architektur & Stabilität

Klassische Skripte frieren häufig ein, wenn Web-Anfragen und Überwachungsschleifen gleichzeitig auf denselben Socket zugreifen. Dieses System setzt auf ein **strikt entkoppeltes Actor-/Queue-Muster**:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Webbrowser (UI Client)                   │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON (alle 1s)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Flask Webserver                        │
│   (Liest RAM-Status verzögerungsfrei / Blockiert niemals)   │
└──────────────┬──────────────────────────────▲───────────────┘
               │ jobs.put(...)                │ STATE Update
               ▼                              │
┌──────────────────────────────┐ ┌────────────┴───────────────┐
│     Thread-Safe Queue        │ │       Shared State         │
└──────────────┬───────────────┘ └────────────────────────────┘
               │ job = jobs.get()
               ▼
┌─────────────────────────────────────────────────────────────┐
│               Dedizierter HyperDeck Worker-Thread           │
│   - Besitzt genau EINE dauerhafte TCP-Verbindung (9993)    │
│   - Zeilenbasierter Stream-Parser (ignoriert 5xx async)     │
│   - Automatischer Reconnect mit Exponential Backoff         │
└──────────────────────────────┬──────────────────────────────┘
                               │ TCP Raw Socket (Port 9993)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Blackmagic HyperDeck Studio                 │
└─────────────────────────────────────────────────────────────┘

- **Kein Socket-Konflikt:** Flask redet niemals direkt mit dem Deck, sondern legt Aufträge in eine Queue.
- **Sicherung getrennt:** Die FTP-Spiegelung läuft in einem eigenen Thread mit eigener Verbindung (Port 21). Sie kann die Steuerverbindung weder blockieren noch stören.
- **Echter Stream-Parser:** Antworten werden nach 3-stelligen Statuscodes (200 ok, 216 format ready) geparst. Unaufgeforderte asynchrone Statusmeldungen (5xx) werden sauber herausgefiltert.
- **Lokale Timer-Interpolation:** Der Countdown zur nächsten Abfrage zählt im Browser per JavaScript (`Date.now()`) flüssig herunter, ohne das Netzwerk zu belasten.

---


## 🚀 Installation & Schnellstart

### Aufbau des Programmordners

```text
hyperdeck_control.py    Dienst: Deck-Steuerung, Automatik, Timer, Web-API
hyperdeck_backup.py     Sicherung der Aufnahmen per FTP (eigener Thread)
ui/                     Weboberfläche (index.html, style.css, app.js)
start.bat / start.sh    Startdateien
requirements.txt        Abhängigkeiten (flask, waitress)
tests/                  automatisierte Tests + HyperDeck-Simulator
hyperdeck_config.json   wird beim ersten Speichern angelegt
hyperdeck.log           rotierende Logdatei (1 MB, drei Generationen)
```

> ⚠️ Immer den **kompletten Ordner** kopieren. Fehlt `ui/` oder `hyperdeck_backup.py`, bricht der Start mit einer klaren Meldung ab.

### 1. Voraussetzungen

- Python 3.7 oder neuer
- HyperDeck Studio im selben lokalen Netzwerk wie der Steuer-PC
- **Wichtig:** Am HyperDeck muss die Option „Remote" (Fernsteuerung) aktiviert sein (Taste auf der Frontblende oder im Gerätemenü).

### 2. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

(`flask` für die Oberfläche, `waitress` als Produktions-Webserver – fehlt waitress, läuft der Flask-Entwicklungsserver als Ersatz.)

### 3. Skript starten

**Der bequeme Weg (empfohlen):**

| System | Datei | Was passiert |
| --- | --- | --- |
| Windows | **`start.bat` doppelklicken** | Python wird gesucht, `flask` installiert, der Dienst gestartet, der Browser geöffnet. |
| Linux / macOS | `./start.sh` | dasselbe im Terminal |

Das Fenster **bleibt offen** und zeigt fortlaufend alle Meldungen an – auch dann,
wenn etwas schiefgeht (z. B. fehlendes Python oder belegter Port). Erst ein
Tastendruck schließt es. Beenden des Dienstes mit `Strg + C`.

> Der Web-Port lässt sich in `start.bat` in der Zeile `set "WEBPORT=5000"` ändern.

**Der klassische Weg:**

```bash
# Standardstart (öffnet den Browser automatisch)
python hyperdeck_control.py

# Optional: IP-Adresse und Web-Port direkt beim Start übergeben
python hyperdeck_control.py --ip 172.17.100.119 --web-port 5000

# Ohne automatischen Browserstart (z. B. auf einem Server)
python hyperdeck_control.py --no-browser
```

---

## 💻 Aufruf der Weboberfläche

Sobald das Skript läuft, ist das Dashboard über jeden modernen Browser erreichbar:

**Auf demselben PC:**
```text
http://localhost:5000
# oder
http://127.0.0.1:5000
```

**Im lokalen Netzwerk (Smartphone, Tablet, Regie-PC):**
```text
http://<IP-DEINES-STEUER-PCS>:5000
# Beispiel: http://192.168.1.150:5000
```

---

## 🎛️ Übersicht der Web-UI & Einstellungen

Die Weboberfläche ist in funktionale Bereiche gegliedert:

### 1. Status & Timecode

- **Tally-Anzeige:** Zeigt groß und blinkend `REC` bei laufender Aufnahme oder `STOP` / `OFFLINE`.
- **Timecode-Display:** Anzeige des aktuellen Timecodes in Echtzeit.
- **Polling-Countdown:** Ein Fortschrittsbalken mit Sekunden-Countdown visualisiert exakt, wann das HyperDeck das nächste Mal abgefragt wird.

### 2. Slot-Übersicht (Slot 1 & Slot 2)

- Zeigt den Einhänge-Status (`mounted`, `empty`) und den Volume-Namen.
- Visualisiert die verbleibende Aufnahmezeit in Minuten inklusive farbigem Fortschrittsbalken (grün = OK, orange = Schwellenwert unterschritten).
- Button **„Karte leeren"**: Manuelle Formatierung des Slots per Sicherheitsabfrage.
- Button **„Karte sichern"** (sobald ein Sicherungsziel eingestellt ist): Kopiert die fertigen Clips dieses Slots ins Ziel.

### 3. Direkte Steuerung (Buttons)

- **Aufnahme starten:** Startet die Aufnahme (inklusive optionalem Timecode-Sync).
- **Aufnahme stoppen:** Hält das Deck an und aktiviert die automatische Sicherheitsverriegelung.
- **Auto-Record freigeben:** Erscheint bei manuellem Stopp, um die Automatik wieder zu aktivieren.
- **Jetzt abfragen:** Führt sofort eine Hardware-Abfrage durch.
- **Neu verbinden:** Baut die Socket-Verbindung zum HyperDeck neu auf.

### 4. Sofort-Schalter (Toggles)

| Schalter | Funktion |
| --- | --- |
| **Loop-Record** | **Hauptschalter.** Aus = keinerlei Automatik; Auto-Record und Auto-Loop werden gesperrt und ausgegraut. |
| **Auto-Record** | Startet die Aufnahme automatisch, sobald das Deck steht. |
| **Auto-Loop** | Formatiert die inaktive Karte rechtzeitig vor Kartenüberlauf. |
| **Timecode auf Uhrzeit** | Synchronisiert den Startzeitcode mit der PC-Systemzeit (`HH:MM:SS:00`). |
| **Timer aktiv** | Schaltet die Zeitsteuerung scharf (siehe nächster Abschnitt). |
| **Automatisch sichern** | Spiegelt fertige Clips im eingestellten Intervall ins Sicherungsziel. |
| **Karte erst leeren, wenn gesichert** | Auto-Loop wartet mit dem Formatieren, bis die Clips der Karte gesichert sind. |

### 5. Parameter-Konfiguration (mit Speicher-Button)

| Parameter | Standard | Beschreibung |
| --- | --- | --- |
| **Deck-IP** | `172.17.100.119` | IP-Adresse des Ziel-HyperDecks im Netzwerk. |
| **Deck-Port** | `9993` | Steuer-Port des HyperDecks (Standard: 9993). |
| **Abfrage alle … Sekunden** | `20` | Zeitspanne zwischen zwei Statusabfragen (5–3600 Sek.). |
| **Vorbereiten ab … Minuten Rest** | `5` | Schwellenwert der aktiven Karte, ab dem die Nachbarkarte vorbereitet wird. |
| **Karte leeren unter … Minuten frei** | `15` | Ist auf der inaktiven Karte mehr Restzeit frei, wird sie nicht formatiert. |
| **Dateisystem** | `exFAT` | Formatierungsauswahl (exFAT oder HFS+). |
| **Datenträgername** | `LoopDump` | Name der SD-Karte / SSD nach der Formatierung. |

> 💡 Alle Eingaben werden persistent in der Datei `hyperdeck_config.json` gesichert und bleiben bei einem Neustart erhalten.

---

## ⏰ Timer-Aufnahme (Zeitsteuerung)

Das Panel **Timer-Aufnahme** nimmt bis zu drei Zeitpläne auf („Autorecord 1“ bis
„Autorecord 3“). Ist der Schalter **Timer aktiv** an, startet und stoppt der
Rekorder vollautomatisch zur eingestellten Uhrzeit – niemand muss vor Ort sein.

| Bedienelement | Bedeutung |
| --- | --- |
| **Timer aktiv** | Hauptschalter der Zeitsteuerung. |
| **Anzahl Zeitpläne** | 1 bis 3. Es werden genau so viele Zeilen eingeblendet. |
| **aktiv** (je Zeile) | Einzelnen Zeitplan ein- oder ausschalten, ohne ihn zu löschen. |
| **Mo … So** | Wochentage anklicken, an denen dieser Zeitplan gelten soll. |
| **Start / Ende** | Uhrzeiten im 24-Stunden-Format. |
| **Zeitpläne speichern** | Übernimmt die Zeilen. Vorher erscheint der Hinweis „Nicht gespeichert“. |
| **Verwerfen** | Holt den gespeicherten Stand zurück. |

**Voreinstellung:** Autorecord 1 = Mo–Fr, **08:45 bis 18:30 Uhr**.

Die Statuszeile über den Zeilen zeigt immer den aktuellen Stand, z. B.
`Autorecord 1 nimmt auf, Fenster bis 18:30 Uhr` oder
`Naechster Start: Autorecord 1 morgen um 08:45 Uhr`. Läuft ein Fenster, erscheint
zusätzlich oben ein grüner Hinweisbalken.

### Verhalten im Detail

- **Über Mitternacht:** Ist die Endzeit kleiner als die Startzeit (z. B.
  `22:00`–`06:00`), läuft das Fenster über den Tageswechsel. Maßgeblich ist der
  Wochentag des **Starts**.
- **Vorrang:** Bei scharfem Timer entscheidet allein der Zeitplan über Start und
  Stopp. Auto-Record funkt nicht dazwischen und kann den Timer-Stopp nicht
  überrennen. Auto-Loop (Kartenwechsel) arbeitet währenddessen normal weiter.
- **Ausfallsicher:** Bricht die Verbindung ab oder startet der PC neu, prüft der
  Dienst beim Verbinden erneut, ob gerade ein Fenster läuft, und nimmt die
  Aufnahme wieder auf. Ein verpasster Stopp wird bis zu fünf Minuten lang
  nachgeholt.
- **Manueller Stopp:** Drückt jemand während eines Fensters auf „Aufnahme
  stoppen“, bleibt es gestoppt – der **nächste** Termin startet aber wieder
  ganz normal.
- **Mehrere Zeitpläne** dürfen sich denselben Tag teilen (z. B. 08:45–12:00 und
  14:00–18:30). Der erste passende Zeitplan gewinnt.

---

## 💾 Sicherung der Aufnahmen (FTP)

Der HyperDeck stellt seine Karten über einen **eingebauten FTP-Server** bereit
(Port 21, anonym, Übertragung auch während der Aufnahme – das Deck drosselt
selbst). Das Panel **Sicherung der Aufnahmen** spiegelt die fertigen Clips von
dort in ein Ziel deiner Wahl:

| Ziel | Einstellung | Beispiel |
| --- | --- | --- |
| **Ordner / Netzlaufwerk** | Zielordner | `Z:\HyperDeck` oder `\\NAS\Aufnahmen\Deck1` (UNC) |
| **FTP-Server** | Server, Port, Benutzer, Passwort, Ordner | NAS mit FTP-Dienst, `/Aufnahmen/Deck1` |

### So läuft ein Sicherungslauf ab

1. Die Dateiliste des Decks wird gelesen (`sd1`, `sd2`, … – die Ordnernamen
   hängen vom Modell ab, z. B. auch `1`/`2` oder `cfast1`/`cfast2`).
2. Nur **fertige** Clips werden kopiert: Eine Datei gilt als fertig, wenn ihre
   Größe 20 Sekunden lang unverändert bleibt. Während das Deck aufnimmt, wird
   zusätzlich die jüngste Datei des aktiven Slots ausgelassen.
3. Jeder Clip bekommt den Aufnahmezeitpunkt vorangestellt:
   `sd1/2026-09-12_09-00-13_HyperDeck_0001.mov`. Der HyperDeck zählt nach
   jedem Formatieren wieder bei `0001` – ohne Zeitstempel würden sich Clips
   gegenseitig überschreiben. Gleicher Name bei anderer Größe → Größe wird
   angehängt. **Es wird nie überschrieben und am Deck nie gelöscht.**
4. Kopiert wird in eine `.part`-Datei, die erst nach vollständiger und
   größengeprüfter Übertragung umbenannt wird. Ein Abbruch hinterlässt keine
   halben Clips unter echtem Namen.
5. Bereits vorhandene Clips (gleicher Name, gleiche Größe) werden übersprungen –
   ein Lauf kostet also nur so viel, wie neu dazugekommen ist.

### Bedienung

| Element | Bedeutung |
| --- | --- |
| **Automatisch sichern** | Läuft alle *n* Minuten (Feld „Alle … Minuten prüfen“, Vorgabe 15). |
| **Karte erst leeren, wenn gesichert** | Auto-Loop formatiert die inaktive Karte erst, wenn ein Sicherungslauf ohne offene Dateien höchstens 15 Minuten zurückliegt; sonst wird sofort ein Lauf angestoßen und gewartet. Ist das Ziel dauerhaft nicht erreichbar, bleibt die Karte voll und das Log meldet es – **Daten gehen vor Endlosschleife.** Schalter aus = Sicherung ist „nur“ Komfort, die Schleife läuft immer. |
| **Jetzt sichern** | Sofortiger Lauf über alle Ordner. |
| **Karte sichern** (im Slot) | Nur die Clips dieses Slots. |
| **Verbindung testen** | Prüft Deck-FTP (Anzahl Dateien, Größe, Ordner) und ob das Ziel beschreibbar ist. |
| **Abbrechen** | Bricht den laufenden Lauf ab; die aktuelle `.part`-Datei wird entfernt. |
| Statusblock | Phase, Datei, Fortschritt, Geschwindigkeit, letztes Ergebnis, nächster Lauf, Inhalt des Decks. |

### Hinweise für den Betrieb

- **Netzlaufwerk unter Windows:** Laufwerksbuchstaben gelten nur für den
  angemeldeten Benutzer. Läuft das Programm unter einem anderen Konto oder als
  Dienst, den **UNC-Pfad** eintragen (`\\NAS\Freigabe\Ordner`) und
  sicherstellen, dass dieses Konto Schreibrechte hat.
- **Passwörter** werden in `hyperdeck_config.json` im Klartext gespeichert
  (wie bei jedem FTP-Client), verlassen den Dienst aber nie: die Oberfläche und
  die API zeigen sie nicht an. Leeres Passwortfeld = unverändert, `-` = löschen.
- **Zeitstempel** im Dateinamen kommen vom Deck (dessen Uhr/Zeitzone).
- Große Karten dauern: bei ~30 MB/s braucht eine volle 256-GB-Karte gut zwei
  Stunden. Deshalb läuft die Sicherung besser laufend im Intervall als „einmal
  am Ende“.
- Bei einem Lauf mit Fehlern (Ziel voll, Netz weg) bleiben die betroffenen
  Clips „offen“ und werden beim nächsten Lauf erneut versucht.

---

## ⌨️ CLI-Startparameter

Beim Start können Parameter übergeben werden, die die gespeicherten Einstellungen temporär überschreiben:

```bash
python hyperdeck_control.py [OPTIONEN]
```

| Parameter | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `--ip` | String | aus Config | IP-Adresse des HyperDecks |
| `--port` | Int | `9993` | Ethernet-Port des HyperDecks |
| `--interval` | Int | `20` | Abfrageintervall in Sekunden |
| `--web-port` | Int | `5000` | Lokaler Port für das Webinterface |
| `--bind` | String | `0.0.0.0` | Netzwerk-Bind-Adresse des Webservers |
| `--no-browser` | Flag | aus | Browser beim Start **nicht** automatisch öffnen |
| `--version` | Flag | – | Gibt die Programmversion aus und beendet sich |

Umgebungsvariable **`HYPERDECK_HOME`**: Ordner für `hyperdeck_config.json` und
`hyperdeck.log` (Standard: Programmordner). Damit lassen sich **zwei Decks mit
zwei Instanzen** betreiben:

```bat
set HYPERDECK_HOME=C:\HyperDeck\Deck2
python hyperdeck_control.py --ip 172.17.100.120 --web-port 5001
```

---

## 📡 REST-API Dokumentation

Zur Integration in Steuerungen wie Bitfocus Companion, Stream Deck, Node-RED oder Home Assistant:

### 1. Status abfragen

```http
GET /api/status
```

Gibt Gerätedaten, Timecode, Slots, Schalterzustände, Zeitpläne, die Version
(`app_version`) und das Log als JSON zurück.

Mit `?since=<log_seq>` werden nur die **neuen** Log-Zeilen geliefert – so bleibt
die Sekundenabfrage sparsam:

```http
GET /api/status?since=42
```

| Feld | Bedeutung |
| --- | --- |
| `log_seq` | Nummer der neuesten Log-Zeile – beim nächsten Aufruf als `since` mitgeben |
| `log_reset` | `true` = der Client muss sein Log leeren (z. B. nach einem Neustart des Dienstes) |
| `timer_active` | Nummer (1–3) des laufenden Zeitplans, sonst `null` |
| `timer_info` | Klartext für die Anzeige |
| `backup` | Zustand der Sicherung: `running`, `phase`, `current`, `files_done`/`files_total`, `bytes_done`/`bytes_total`, `speed`, `pending`, `last_run`, `last_result`, `error`, `next_run_s`, `last_test`, `tree` |
| `uptime_s` | Laufzeit des Dienstes in Sekunden |
| `*_pass_set` | `true`, wenn ein Passwort hinterlegt ist – das Passwort selbst wird nie ausgegeben |

Die komplette Logdatei gibt es als Text unter `GET /api/log.txt`.

### 2. Befehl senden

```http
POST /api/command
```

```json
// Aufnahme starten
{"action": "record"}

// Aufnahme stoppen (mit Interlock)
{"action": "stop"}

// Stopp-Verriegelung aufheben
{"action": "resume_auto"}

// Slot 2 manuell formatieren
{"action": "format", "slot_id": 2}

// Sofortige Abfrage triggern
{"action": "poll"}

// Socket neu verbinden
{"action": "reconnect"}

// Sicherung: alles, nur Slot 2, Verbindungstest, Abbruch
{"action": "backup"}
{"action": "backup", "slot_id": 2}
{"action": "backup_test"}
{"action": "backup_cancel"}
```

### 3. Einstellungen ändern

```http
POST /api/settings
```

```json
{
  "loop_record": true,
  "auto_record": true,
  "check_interval": 30,
  "min_remaining_threshold": 8
}
```

Zeitpläne setzen (die Liste enthält immer alle drei Einträge, `days`: 0 = Montag
… 6 = Sonntag):

```json
{
  "timer_enabled": true,
  "timer_count": 2,
  "timers": [
    {"enabled": true,  "days": [0,1,2,3,4], "start": "08:45", "end": "18:30"},
    {"enabled": true,  "days": [5,6],       "start": "10:00", "end": "12:00"},
    {"enabled": false, "days": [],          "start": "08:45", "end": "18:30"}
  ]
}
```

> Alle Werte werden serverseitig geprüft und normalisiert: aus `"8:45"` wird
> `"08:45"`, unsinnige Angaben fallen auf die Vorgabe zurück.

Sicherung einrichten (Netzlaufwerk bzw. FTP-Server):

```json
{"backup_enabled": true, "backup_interval": 15, "backup_mode": "folder",
 "backup_folder": "\\\\NAS\\Aufnahmen\\Deck1", "backup_block_format": true}
```

```json
{"backup_mode": "ftp", "backup_ftp_host": "nas.local", "backup_ftp_port": 21,
 "backup_ftp_user": "hyperdeck", "backup_ftp_pass": "geheim", "backup_ftp_path": "/Aufnahmen/Deck1"}
```

---

## 🧪 Tests

```bash
pip install -r requirements.txt pyftpdlib pytest
pytest -q tests/
```

| Datei | Prüft |
| --- | --- |
| `tests/test_timer.py` | Zeitplan-Logik und Zustandsautomat (Fenster, Mitternacht, Verriegelung, Nachholen) |
| `tests/test_backup.py` | FTP-Sicherung gegen zwei lokale FTP-Server (Wachsen, Kollisionen, FTP-Ziel, Abbruch, Fehler) |
| `tests/test_api.py` | Dienst + simuliertes Deck, komplett über die API |
| `tests/fake_deck.py` | HyperDeck-Simulator – auch zum Ausprobieren der Oberfläche ohne Gerät |

Die GitHub Action `.github/workflows/tests.yml` führt alles bei jedem Push aus.

---

## 🔍 Fehlerbehebung (Troubleshooting)

| Problem | Ursache | Lösung |
| --- | --- | --- |
| Status: `offline` / Keine Verbindung | IP/Port falsch oder HyperDeck nicht im selben Subnetz. | IP in den Einstellungen prüfen. `ping <DECK-IP>` im Terminal testen. |
| Befehl abgelehnt (Code 111) | Fernsteuerung am Deck deaktiviert. | Am HyperDeck die Taste „REMOTE" drücken (muss leuchten). |
| Formatierung schlägt fehl | Keine Karte eingelegt oder beschädigt. | Überprüfen, ob die Karte gemountet ist. Gegebenenfalls am PC formatieren. |
| Aufnahme startet nicht automatisch | Manueller Stopp aktiv. | In der UI auf „Auto-Record freigeben" oder „Aufnahme starten" klicken. |
| Timer startet nicht | Timer nicht scharf, falscher Wochentag, oder die Zeile ist über „Anzahl Zeitpläne" ausgeblendet. | Statuszeile im Timer-Panel lesen – dort steht, was als Nächstes passiert. |
| Timer stoppt nicht | Ein zweiter Zeitplan überlappt das Fenster. | Zeitpläne auf Überschneidungen prüfen. |
| Fenster schließt sich sofort | Python fehlt oder ist nicht im PATH. | `start.bat` benutzen – es zeigt die Ursache an und bleibt offen. |
| Uhrzeitfelder zeigen AM/PM | Anzeigeformat des Browsers/Systems. | Nur die Anzeige, gespeichert wird immer 24-Stunden-Zeit. Systemsprache auf Deutsch stellen. |
| Sicherung: „Deck-FTP FEHLER“ | FTP am Deck nicht erreichbar (Port 21 gesperrt, Deck aus, falsche IP). | Im Browser `ftp://<DECK-IP>` öffnen bzw. mit FileZilla testen. Firewall am PC prüfen. |
| Sicherung: „Ziel FEHLER“ | Ordner nicht beschreibbar, Laufwerksbuchstabe für dieses Konto nicht vorhanden, FTP-Login falsch. | UNC-Pfad statt Laufwerksbuchstabe; Rechte des Kontos prüfen; „Verbindung testen“ nutzen. |
| Karte wird nicht geleert, Log meldet „wartet auf Sicherung“ | „Karte erst leeren, wenn gesichert“ ist an und die Sicherung kommt nicht durch. | Ziel reparieren – oder den Schalter ausschalten, wenn die Schleife wichtiger ist als die Daten. |
| Clip fehlt im Ziel | Datei wuchs noch (läuft), oder sie ist die jüngste des aufnehmenden Slots. | Kommt beim nächsten Lauf, sobald der Clip abgeschlossen ist. |

---

## 🔖 Versionierung & Änderungsprotokoll

Das Projekt folgt der [Semantischen Versionierung](https://semver.org/lang/de/)
(**MAJOR.MINOR.PATCH**). Die laufende Version steht

- oben rechts in der Kopfzeile der Weboberfläche (z. B. `v3.1.0`),
- in der Fußzeile unter dem Ereignis-Log,
- in der Startmeldung des Konsolenfensters,
- in `hyperdeck_control.py` in der Konstanten `APP_VERSION`,
- und über die API unter `app_version`.

Alle Änderungen sind im **[Änderungsprotokoll](CHANGELOG.md)** festgehalten.

Bei einer neuen Version zusätzlich auf GitHub einen Tag und ein Release anlegen –
dann ist die Version auch dort sichtbar und herunterladbar:

```bash
git tag -a v3.1.0 -m "Sicherung per FTP, Produktionsserver, Tests"
git push origin v3.1.0
```

---

## 📄 Lizenz

Dieses Projekt steht unter der **MIT-Lizenz** – siehe [LICENSE](LICENSE).
Freie Nutzung, Anpassung und Weitergabe sind ausdrücklich gestattet.
```
