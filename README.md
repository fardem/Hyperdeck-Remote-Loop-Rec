# 🎛️ Blackmagic HyperDeck Web Control & Auto-Loop

Ein ausfallsicherer, thread-entkoppelter Web-Controller mit Endlosaufnahme-Automatik (**24/7 Loop-Recording**) für **Blackmagic Design HyperDeck Studio** Recorder über das Ethernet-Protokoll (Port 9993).

![Python](https://img.shields.io/badge/Python-3.7%2B-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/WebUI-Flask-black?logo=flask&logoColor=white)
![Hardware](https://img.shields.io/badge/Hardware-BM%20HyperDeck-red)
![Version](https://img.shields.io/badge/Version-3.0.0-blueviolet)
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
8. [CLI-Startparameter](#️-cli-startparameter)
9. [REST-API Dokumentation](#-rest-api-dokumentation)
10. [Fehlerbehebung (Troubleshooting)](#-fehlerbehebung-troubleshooting)
11. [Versionierung & Änderungsprotokoll](#-versionierung--änderungsprotokoll)
12. [Lizenz](#-lizenz)

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
* 🔒 **Manueller Stopp-Schutz (Safety Interlock):** Drückt ein Operator manuell auf „Stopp“, verriegelt sich Auto-Record. Die Automatik funkt nicht eigenmächtig dazwischen, bis sie explizit freigegeben oder eine neue Aufnahme gestartet wird.
* 🕒 **Timecode-Synchronisation:** Setzt den Start-Timecode des Decks auf Wunsch automatisch auf die aktuelle PC-Systemzeit (`HH:MM:SS:00`).
* ⚡ **BM-Token-Formatierung:** Vollständige Unterstützung des zweistufigen Blackmagic-Protokolls (`prepare` $\rightarrow$ `Token auslesen` $\rightarrow$ `confirm`) inklusive 180-Sekunden-Cooldown gegen Mehrfach-Löschungen.
* 🌐 **Responsives Dark-Mode Webinterface:** Timecode, Tally, Füllstandsbalken, Live-Countdown und Systemlog synchronisieren sich verzögerungsfrei und flüssig im Browser.
* 💾 **Live-Konfiguration:** Alle Parameter sind im laufenden Betrieb in der Web-UI änderbar und werden persistent in `hyperdeck_config.json` gespeichert.
* 🚀 **Startet und öffnet sich selbst:** `start.bat` (Windows) bzw. `start.sh` prüft Python, installiert die Abhängigkeiten und startet den Dienst – der Browser geht automatisch mit der richtigen Adresse auf. Das Konsolenfenster bleibt in jedem Fall offen.
* 🏷️ **Sichtbare Version:** Die laufende Programmversion steht in der Kopf- und Fußzeile der Oberfläche sowie in der Startmeldung der Konsole.

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
- **Echter Stream-Parser:** Antworten werden nach 3-stelligen Statuscodes (200 ok, 216 format ready) geparst. Unaufgeforderte asynchrone Statusmeldungen (5xx) werden sauber herausgefiltert.
- **Lokale Timer-Interpolation:** Der Countdown zur nächsten Abfrage zählt im Browser per JavaScript (`Date.now()`) flüssig herunter, ohne das Netzwerk zu belasten.

---


## 🚀 Installation & Schnellstart

### 1. Voraussetzungen

- Python 3.7 oder neuer
- HyperDeck Studio im selben lokalen Netzwerk wie der Steuer-PC
- **Wichtig:** Am HyperDeck muss die Option „Remote" (Fernsteuerung) aktiviert sein (Taste auf der Frontblende oder im Gerätemenü).

### 2. Abhängigkeit installieren

```bash
pip install flask
```

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

---

## 🔖 Versionierung & Änderungsprotokoll

Das Projekt folgt der [Semantischen Versionierung](https://semver.org/lang/de/)
(**MAJOR.MINOR.PATCH**). Die laufende Version steht

- oben rechts in der Kopfzeile der Weboberfläche (z. B. `v3.0.0`),
- in der Fußzeile unter dem Ereignis-Log,
- in der Startmeldung des Konsolenfensters,
- in `hyperdeck_control.py` in der Konstanten `APP_VERSION`,
- und über die API unter `app_version`.

Alle Änderungen sind im **[Änderungsprotokoll](CHANGELOG.md)** festgehalten.

Bei einer neuen Version zusätzlich auf GitHub einen Tag und ein Release anlegen –
dann ist die Version auch dort sichtbar und herunterladbar:

```bash
git tag -a v3.0.0 -m "Timer-Aufnahme, Loop-Hauptschalter, Autostart"
git push origin v3.0.0
```

---

## 📄 Lizenz

Dieses Projekt steht unter der **MIT-Lizenz** – siehe [LICENSE](LICENSE).
Freie Nutzung, Anpassung und Weitergabe sind ausdrücklich gestattet.
```
