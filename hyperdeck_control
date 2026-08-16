import socket
import time
import re
import datetime
import sys
import msvcrt 

# --- EINSTELLUNGEN ---
HYPERDECK_IP = "172.17.100.119"
PORT = 9993

CHECK_INTERVAL = 60 
MIN_REMAINING_THRESHOLD = 2 

# Merker, um Mehrfach-Formatierungen zu verhindern
# Wir speichern hier die Nummer des Slots, den wir zuletzt "sauber" gemacht haben.
last_formatted_slot = None

# ---------------------------

def connect_socket():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((HYPERDECK_IP, PORT))
        s.recv(2048) 
        return s
    except Exception:
        return None

def send_command(sock, command, long_timeout=False):
    try:
        sock.sendall((command + "\n").encode('utf-8'))
        response = ""
        wait_limit = 6.0 if long_timeout else 2.5
        time.sleep(0.5) 
        start = time.time()
        while True:
            if time.time() - start > wait_limit: break
            try:
                chunk = sock.recv(4096).decode('utf-8')
                if not chunk: break
                response += chunk
                if "216 format ready" in response and "\n" in response.split("216 format ready")[1]:
                     break
                if response.endswith("\n\n") or response.endswith(":\n") or response.endswith("ok\n"):
                    break
            except socket.timeout: break
        return response
    except Exception: return ""

def parse_value(response, key):
    if not response: return None
    pattern = rf"{key}:\s*(.+)"
    match = re.search(pattern, response, re.IGNORECASE)
    if match: return match.group(1).strip()
    return None

def get_remaining_minutes(response):
    val = parse_value(response, "recording time")
    if val:
        try: return int(val) / 60
        except: return 0
    return 0

def format_slot_protocol_216(sock, slot_id):
    """Spezial-Formatierung für dein Gerät."""
    print(f"   >>> ACTION: Bereinige Slot {slot_id} für den bevorstehenden Wechsel...")
    
    info = send_command(sock, f"slot info: slot id: {slot_id}")
    if parse_value(info, "status") != "mounted":
        print("       ABBRUCH: Keine Karte erkannt.")
        return False

    cmd = f"format: slot id: {slot_id} prepare: exFAT name: LoopDump"
    resp = send_command(sock, cmd)
    
    token = None
    if "216 format ready" in resp:
        lines = resp.splitlines()
        for i, line in enumerate(lines):
            if "216 format ready" in line and i + 1 < len(lines):
                token = lines[i+1].strip()
                break
    
    if token:
        print(f"       Token erhalten: {token}. Bestätige...")
        confirm_cmd = f"format: confirm: {token}"
        confirm_resp = send_command(sock, confirm_cmd, long_timeout=True)
        
        if "200 ok" in confirm_resp or not confirm_resp:
            print(f"       >>> ERFOLG! Slot {slot_id} ist jetzt leer und bereit.")
            return True
        else:
            print(f"       FEHLER: {confirm_resp.strip()}")
            return False
    return False

def startup_sequence():
    global last_formatted_slot
    print("\n" + "="*50)
    print(" INITIALISIERUNG...")
    s = connect_socket()
    if s:
        send_command(s, "stop")
        s.close()    

    print("-" * 50)
    print(" START-OPTION: Beide Karten jetzt formatieren?")
    print(" Drücke 'j' für JA | 'n' für NEIN (10s Countdown)")
    print("-" * 50)
    
    timeout = 10
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        remaining = timeout - elapsed
        if remaining <= 0: break
        sys.stdout.write(f"\rWarte auf Eingabe... {int(remaining)} Sek. ")
        sys.stdout.flush()
        if msvcrt.kbhit():
            key = msvcrt.getch().lower()
            if key in [b'j', b'y']:
                print("\n\n>>> INITIAL-FORMATIERUNG...")
                s = connect_socket()
                if s:
                    format_slot_protocol_216(s, 1)
                    time.sleep(2)
                    format_slot_protocol_216(s, 2)
                    # Nach Initialisierung setzen wir den Merker auf Slot 2, 
                    # damit beim Start von Slot 1 nicht sofort wieder Slot 2 gelöscht wird.
                    last_formatted_slot = 2 
                    s.close()
                break
            elif key == b'n':
                print("\n\nÜbersprungen."); break
        time.sleep(0.1)

def main():
    global last_formatted_slot
    print(f"--- HYPERDECK LOOP CONTROL V12 ---")
    print(f"IP: {HYPERDECK_IP} | Trigger: < {MIN_REMAINING_THRESHOLD} Min. Restzeit")
    
    startup_sequence()
    
    print("-" * 50)
    print("Überwachungs-Modus aktiv.")

    while True:
        s = connect_socket()
        if not s:
            time.sleep(5); continue

        t_info = send_command(s, "transport info")
        status = parse_value(t_info, "status")
        tc = parse_value(t_info, "timecode")
        act_slot_str = parse_value(t_info, "slot id")

# Auto-Record (Falls wir gestoppt sind)
        if status and "record" not in status.lower():
            print(f"> Gerät steht auf '{status}'. Starte Start-Sequenz...")
            
            record_success = False # Merker, ob es geklappt hat

            # Wir versuchen es maximal 3 Mal
            for attempt in range(1, 4):
                print(f"\n> --- Start-Versuch {attempt} von 3 ---")
                
                # 1. Timecode setzen
                now = datetime.datetime.now()
                pc_timecode = now.strftime("%H:%M:%S:00")
                print(f"> Synchronisiere Timecode mit PC: {pc_timecode}")
                send_command(s, f"configuration: timecode preset: {pc_timecode}")
                
                # 2. Record senden
                print(f"> Sende RECORD Befehl...")
                send_command(s, "record")
                
                # 3. 10 Sekunden warten (Deine Anforderung)
                print("> Warte 10 Sekunden auf Bestätigung...")
                time.sleep(10)
                
                # 4. Prüfen ob es geklappt hat
                t_info = send_command(s, "transport info")
                status = parse_value(t_info, "status")
                act_slot_str = parse_value(t_info, "slot id") # Slot-ID auch aktualisieren!
                
                if status and "record" in status.lower():
                    print(f"> ERFOLG: Aufnahme läuft (Status: {status}).")
                    record_success = True
                    break # Erfolgreich, raus aus der Retry-Schleife
                else:
                    print(f"> FEHLSCHLAG: Gerät ist immer noch im Status '{status}'.")
            
            # Wenn nach 3 Versuchen immer noch keine Aufnahme läuft:
            if not record_success:
                print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print(" ALARM: Aufnahme konnte nach 3 Versuchen NICHT gestartet werden!")
                print(" Skript pausiert kurz und versucht es dann komplett neu.")
                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                s.close()
                print("-" * 50)
                time.sleep(CHECK_INTERVAL)
                continue # Springt sofort zum Anfang der Hauptschleife zurück (keine Überwachung)
    
        if act_slot_str:
            act_id = int(act_slot_str)
            inact_id = 2 if act_id == 1 else 1

            raw_act = send_command(s, f"slot info: slot id: {act_id}")
            raw_inact = send_command(s, f"slot info: slot id: {inact_id}")
            
            rem_act = get_remaining_minutes(raw_act)
            rem_inact = get_remaining_minutes(raw_inact)
            
            now = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] {status.upper()} | TC: {tc}")
            print(f"         Aktive Karte ({act_id}):   {int(rem_act)} Min. RESTZEIT")
            
            # Anzeige des Vorbereitungs-Status
            prep_status = "BEREIT" if last_formatted_slot == inact_id else "WIRD BEI BEDARF GELEERT"
            print(f"         Passive Karte ({inact_id}):  {int(rem_inact)} Min. RESTZEIT ({prep_status})")

            # LOOP LOGIK MIT EINMAL-SPERRE
            if status and "record" in status.lower():
                
                # Bedingung 1: Schwellenwert unterschritten
                if rem_act < MIN_REMAINING_THRESHOLD:
                    
                    # Bedingung 2: Haben wir DIESE Karte in diesem Zyklus schon mal formatiert?
                    if last_formatted_slot != inact_id:
                        # Nur wenn sie auch wirklich voll ist (wenig Restzeit hat)
                        if rem_inact < 10:
                            print(f">>> SCHWELLWERT UNTERSCHRITTEN. Starte einmalige Vorbereitung von Slot {inact_id}.")
                            if format_slot_protocol_216(s, inact_id):
                                last_formatted_slot = inact_id # Sperre für diesen Slot setzen
                        else:
                            # Falls die Karte schon leer ist, setzen wir die Sperre trotzdem,
                            # damit er nicht dauernd prüft.
                            last_formatted_slot = inact_id
                    else:
                        # Hier passiert nichts mehr, da last_formatted_slot == inact_id
                        pass
                
                # OPTIONAL: Wenn die aktive Karte wieder viel Zeit hat (Wechsel ist passiert),
                # könnte man die Sperre theoretisch auch hier managen, aber die Logik oben 
                # greift automatisch, sobald act_id und inact_id rotieren.
                
        s.close()
        print("-" * 50)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
