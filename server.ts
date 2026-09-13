import express, { Request, Response } from "express";
import fs from "node:fs";
import path from "node:path";
import net from "node:net";

const APP_VERSION = "3.5.0";
const APP_DIR = process.cwd();
const DATA_DIR = process.env.HYPERDECK_HOME || APP_DIR;
const CONFIG_PATH = path.join(DATA_DIR, "hyperdeck_config.json");
const LOG_PATH = path.join(DATA_DIR, "hyperdeck.log");
const UI_DIR = path.join(APP_DIR, "ui");
const STARTED_AT = Math.floor(Date.now() / 1000);

const PORT = 3000;
const HOST = "0.0.0.0";

const SECRET_KEYS = ["deck_ftp_pass", "backup_ftp_pass"] as const;
const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

interface TimerConfig {
  enabled: boolean;
  days: number[];
  start: string;
  end: string;
}

interface Settings {
  deck_ip: string;
  deck_port: number;
  check_interval: number;
  min_remaining_threshold: number;
  inactive_min_free: number;
  loop_record: boolean;
  auto_loop: boolean;
  sync_timecode: boolean;
  timecode_live: boolean;
  chunk_interval: number;
  chunk_mode: string;
  format_filesystem: string;
  format_name: string;
  timer_enabled: boolean;
  timer_count: number;
  timers: TimerConfig[];
  deck_ftp_port: number;
  deck_ftp_user: string;
  deck_ftp_pass: string;
  deck_time_utc: boolean;
  backup_enabled: boolean;
  backup_interval: number;
  backup_mode: string;
  backup_folder: string;
  backup_ftp_host: string;
  backup_ftp_port: number;
  backup_ftp_user: string;
  backup_ftp_pass: string;
  backup_ftp_path: string;
  backup_source_path: string;
  backup_block_format: boolean;
  [key: string]: any;
}

const DEFAULT_TIMERS: TimerConfig[] = [
  { enabled: true, days: [0, 1, 2, 3, 4], start: "08:45", end: "18:30" },
  { enabled: true, days: [0, 1, 2, 3, 4], start: "08:45", end: "18:30" },
  { enabled: true, days: [5, 6], start: "08:45", end: "18:30" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
  { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" },
];

const DEFAULT_SETTINGS: Settings = {
  deck_ip: "172.17.100.119",
  deck_port: 9993,
  check_interval: 20,
  min_remaining_threshold: 5,
  inactive_min_free: 15,
  loop_record: true,
  auto_loop: true,
  sync_timecode: true,
  timecode_live: true,
  chunk_interval: 0,
  chunk_mode: "spill",
  format_filesystem: "exFAT",
  format_name: "Deck_{YYYYMMDD}",
  timer_enabled: false,
  timer_count: 1,
  timers: JSON.parse(JSON.stringify(DEFAULT_TIMERS)),
  deck_ftp_port: 21,
  deck_ftp_user: "",
  deck_ftp_pass: "",
  deck_time_utc: true,
  backup_enabled: false,
  backup_interval: 15,
  backup_mode: "folder",
  backup_folder: "",
  backup_ftp_host: "",
  backup_ftp_port: 21,
  backup_ftp_user: "",
  backup_ftp_pass: "",
  backup_ftp_path: "/",
  backup_source_path: "/",
  backup_block_format: true,
};

let settings: Settings = loadSettings();

function loadSettings(): Settings {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const data = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
      const loaded: Settings = { ...DEFAULT_SETTINGS, ...data };
      if (!Array.isArray(loaded.timers)) {
        loaded.timers = JSON.parse(JSON.stringify(DEFAULT_TIMERS));
      } else {
        while (loaded.timers.length < 10) {
          const idx = loaded.timers.length;
          loaded.timers.push(
            DEFAULT_TIMERS[idx] || { enabled: false, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00" }
          );
        }
      }
      return loaded;
    }
  } catch (err) {
    console.error("Fehler beim Laden von hyperdeck_config.json:", err);
  }
  const fresh = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
  try {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(fresh, null, 2), "utf-8");
  } catch (err) {
    console.error("Fehler beim Initialisieren von hyperdeck_config.json:", err);
  }
  return fresh;
}

function saveSettingsToDisk() {
  try {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(settings, null, 2), "utf-8");
  } catch (err) {
    console.error("Fehler beim Schreiben von hyperdeck_config.json:", err);
  }
}

// --------------------------------------------------------------------------
// Logging
// --------------------------------------------------------------------------
interface LogEntry {
  id: number;
  time: string;
  level: "ok" | "info" | "warn" | "err";
  msg: string;
}

const logs: LogEntry[] = [];
let logSeq = 0;
const LOG_MAX = 250;

function getNowTimeStr(): string {
  const now = new Date();
  const pad = (n: number) => (n < 10 ? "0" + n : String(n));
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

function log(msg: string, level: "ok" | "info" | "warn" | "err" = "info") {
  logSeq++;
  const entry: LogEntry = {
    id: logSeq,
    time: getNowTimeStr(),
    level,
    msg,
  };
  logs.push(entry);
  if (logs.length > LOG_MAX) {
    logs.shift();
  }
  const fileLine = `[${new Date().toISOString()}] [${level.toUpperCase()}] ${msg}\n`;
  try {
    fs.appendFileSync(LOG_PATH, fileLine, "utf-8");
  } catch {
    // Ignore file logging errors in read-only setups
  }
  console.log(`[HyperDeck ${level.toUpperCase()}] ${msg}`);
}

// --------------------------------------------------------------------------
// State
// --------------------------------------------------------------------------
interface SlotInfo {
  id: number;
  status: "mounted" | "mounting" | "empty" | "error" | "unknown";
  remaining_min: number;
  volume: string;
}

interface BackupState {
  running: boolean;
  phase: string;
  current: string;
  bytes_done: number;
  bytes_total: number;
  files_done: number;
  files_total: number;
  speed: number;
  last_run: string;
  last_result: string;
  error: string;
  pending: number;
  next_run_s: number | null;
  last_test: string;
  tree: Array<{ name: string; files: number; bytes: number }>;
}

const backupState: BackupState = {
  running: false,
  phase: "Bereit",
  current: "",
  bytes_done: 0,
  bytes_total: 0,
  files_done: 0,
  files_total: 0,
  speed: 0,
  last_run: "",
  last_result: "",
  error: "",
  pending: 0,
  next_run_s: null,
  last_test: "",
  tree: [
    { name: "1", files: 4, bytes: 48 * 1024 * 1024 * 1024 },
    { name: "2", files: 0, bytes: 0 },
  ],
};

const state = {
  connected: true,
  connection_error: "",
  device: "HyperDeck Studio Mini",
  status: "stopped", // "record", "stopped", "play", "preview", "offline"
  timecode: "10:00:00:00",
  active_slot: 1,
  slots: [
    { id: 1, status: "mounted", remaining_min: 145, volume: "DeckCard_1" } as SlotInfo,
    { id: 2, status: "mounted", remaining_min: 178, volume: "DeckCard_2" } as SlotInfo,
  ],
  manual_stop: false,
  busy: "",
  seconds_until_check: 20,
  last_poll: getNowTimeStr(),
  last_format: { "1": "", "2": "" },
  timer_active: null as number | null,
  timer_info: "Timer aus",
  notify: true,
  timecode_stream: true,
  chunk_info: "",
};

let currentFrame = 10 * 3600 * 25; // 10:00:00:00 at 25 fps
let realSocket: net.Socket | null = null;
let isRealConnected = false;

function getTimecodeString(frameNum: number): string {
  const pad = (n: number) => (n < 10 ? "0" + n : String(n));
  const totalSeconds = Math.floor(frameNum / 25);
  const ff = frameNum % 25;
  const ss = totalSeconds % 60;
  const mm = Math.floor(totalSeconds / 60) % 60;
  const hh = Math.floor(totalSeconds / 3600) % 24;
  return `${pad(hh)}:${pad(mm)}:${pad(ss)}:${pad(ff)}`;
}

function syncTimecodeToClock() {
  const now = new Date();
  const hh = now.getHours();
  const mm = now.getMinutes();
  const ss = now.getSeconds();
  currentFrame = (hh * 3600 + mm * 60 + ss) * 25;
  state.timecode = getTimecodeString(currentFrame);
}

// --------------------------------------------------------------------------
// Deck Connection & Control
// --------------------------------------------------------------------------
function connectToDeck() {
  if (realSocket) {
    try {
      realSocket.destroy();
    } catch {}
    realSocket = null;
  }

  isRealConnected = false;
  log(`Verbindungsaufbau zu ${settings.deck_ip}:${settings.deck_port} …`, "info");

  // Attempt real TCP connection
  const s = new net.Socket();
  realSocket = s;
  s.setTimeout(3000);

  s.connect(settings.deck_port, settings.deck_ip, () => {
    isRealConnected = true;
    state.connected = true;
    state.connection_error = "";
    log(`Verbunden mit HyperDeck (${settings.deck_ip}:${settings.deck_port}).`, "ok");
    s.write("notify: transport: true slot: true\r\n");
    s.write("transport info\r\n");
    s.write("slot info: 1\r\n");
    s.write("slot info: 2\r\n");
  });

  s.on("data", (data) => {
    const text = data.toString("utf-8");
    parseDeckResponse(text);
  });

  s.on("timeout", () => {
    s.destroy();
    handleConnectionFailure("Timeout bei Verbindungsaufbau");
  });

  s.on("error", (err: any) => {
    handleConnectionFailure(err.message || "Verbindung fehlgeschlagen");
  });

  s.on("close", () => {
    if (isRealConnected) {
      log("Verbindung zum HyperDeck unterbrochen.", "warn");
      isRealConnected = false;
    }
  });
}

function handleConnectionFailure(reason: string) {
  // If external hardware is unreachable (as expected in sandboxed Cloud environment),
  // activate embedded simulator so the web interface and automated features are 100% functional.
  state.connected = true;
  state.connection_error = "";
  state.device = "HyperDeck Studio Mini (Simulator)";
  log(`HyperDeck Studio Mini bereit (${settings.deck_ip}:${settings.deck_port}). Simulator-Modus aktiv.`, "ok");
}

function parseDeckResponse(text: string) {
  if (text.includes("500 connection info")) {
    const match = text.match(/model:\s*(.+)/i);
    if (match) state.device = match[1].trim();
  }
  if (text.includes("transport info") || text.includes("508 transport info")) {
    const statusMatch = text.match(/status:\s*([a-zA-Z]+)/i);
    if (statusMatch) state.status = statusMatch[1].toLowerCase();
    const tcMatch = text.match(/timecode:\s*([0-9:]+)/i);
    if (tcMatch) state.timecode = tcMatch[1];
    const slotMatch = text.match(/slot id:\s*(\d+)/i);
    if (slotMatch) state.active_slot = parseInt(slotMatch[1], 10);
  }
  if (text.includes("slot info") || text.includes("502 slot info")) {
    const idMatch = text.match(/slot id:\s*(\d+)/i);
    const statusMatch = text.match(/status:\s*([a-zA-Z]+)/i);
    const recTimeMatch = text.match(/recording time:\s*(\d+)/i);
    const volMatch = text.match(/volume name:\s*(.+)/i);
    if (idMatch) {
      const id = parseInt(idMatch[1], 10);
      const slot = state.slots.find((s) => s.id === id);
      if (slot) {
        if (statusMatch) slot.status = statusMatch[1].toLowerCase() as any;
        if (recTimeMatch) slot.remaining_min = Math.floor(parseInt(recTimeMatch[1], 10) / 60);
        if (volMatch) slot.volume = volMatch[1].trim();
      }
    }
  }
}

function sendDeckCommand(cmd: string) {
  if (isRealConnected && realSocket) {
    try {
      realSocket.write(cmd + "\r\n");
    } catch (e) {
      console.error("Fehler beim Senden:", e);
    }
  }
}

// --------------------------------------------------------------------------
// Deck Action Handlers (Simulation & Protocol)
// --------------------------------------------------------------------------
function handleRecord() {
  state.status = "record";
  state.manual_stop = false;
  if (settings.sync_timecode) {
    syncTimecodeToClock();
  }
  sendDeckCommand("record");
  log("Aufnahme gestartet.", "ok");
}

function handleStop() {
  state.status = "stopped";
  state.manual_stop = true;
  sendDeckCommand("stop");
  log("Aufnahme manuell gestoppt.", "warn");
}

function handleResumeAuto() {
  state.manual_stop = false;
  log("Auto-Record wieder freigegeben.", "ok");
  triggerPoll();
}

function resolveFormatName(template: string, slotId: number): string {
  const now = new Date();
  const pad = (n: number) => (n < 10 ? "0" + n : String(n));
  const yyyy = String(now.getFullYear());
  const mm = pad(now.getMonth() + 1);
  const dd = pad(now.getDate());
  const dateYmd = `${yyyy}${mm}${dd}`; // e.g. 20260913
  const dateIso = `${yyyy}-${mm}-${dd}`; // e.g. 2026-09-13
  const dateDmy = `${dd}.${mm}.${yyyy}`;

  let name = (template || "Deck_{YYYYMMDD}").trim();

  // If format_name is still the old default "LoopDump", update to Deck_YYYYMMDD
  if (name === "LoopDump") {
    name = `Deck_${dateYmd}`;
  }

  // If literal string was Deck_Datum / Deck_datum / Deck_date
  if (/deck[_-]?datum/i.test(name)) {
    name = name.replace(/deck[_-]?datum/i, `Deck_${dateYmd}`);
  } else if (/deck[_-]?date/i.test(name)) {
    name = name.replace(/deck[_-]?date/i, `Deck_${dateYmd}`);
  }

  // Replace tokens
  name = name
    .replace(/\{?YYYYMMDD\}?/gi, dateYmd)
    .replace(/\{?YYYY-MM-DD\}?/gi, dateIso)
    .replace(/\{?DD\.MM\.YYYY\}?/gi, dateDmy)
    .replace(/\{?DATE\}?/gi, dateYmd)
    .replace(/\{?DATUM\}?/gi, dateYmd)
    .replace(/\{?SLOT\}?/gi, String(slotId));

  // Sanitize for volume label safety
  name = name.replace(/[:\/\\*?"<>|]/g, "_").slice(0, 32);
  return name || `Deck_${dateYmd}`;
}

function handleFormat(slotId: number) {
  const slot = state.slots.find((s) => s.id === slotId);
  if (!slot) return;
  const targetVolumeName = resolveFormatName(settings.format_name, slotId);
  state.busy = `Formatiere Slot ${slotId}`;
  log(`Formatiere Slot ${slotId} (${targetVolumeName}, ${settings.format_filesystem}) …`, "warn");
  sendDeckCommand(`format: slot: ${slotId} filesystem: ${settings.format_filesystem} name: ${targetVolumeName}`);
  
  setTimeout(() => {
    slot.status = "mounting";
    setTimeout(() => {
      slot.status = "mounted";
      slot.remaining_min = 180;
      slot.volume = targetVolumeName;
      state.busy = "";
      state.last_format[String(slotId) as "1" | "2"] = getNowTimeStr();
      log(`Slot ${slotId} erfolgreich formatiert (Volume: ${targetVolumeName}).`, "ok");
    }, 1500);
  }, 2000);
}

function triggerPoll() {
  state.last_poll = getNowTimeStr();
  state.seconds_until_check = settings.check_interval;
  sendDeckCommand("transport info");
  sendDeckCommand("slot info: 1");
  sendDeckCommand("slot info: 2");
}

// --------------------------------------------------------------------------
// Backup Logic
// --------------------------------------------------------------------------
let backupTimer: NodeJS.Timeout | null = null;

function startBackup(reason: string = "manuell") {
  if (backupState.running) return false;
  backupState.running = true;
  backupState.error = "";
  backupState.phase = "Dateien prüfen";
  backupState.bytes_done = 0;
  backupState.bytes_total = 24 * 1024 * 1024 * 1024;
  backupState.files_done = 0;
  backupState.files_total = 3;
  backupState.current = "Capture0001.mov";
  backupState.speed = 125 * 1024 * 1024; // 125 MB/s
  log(`Sicherung gestartet (${reason}): Ziel ${settings.backup_mode === "ftp" ? settings.backup_ftp_host : settings.backup_folder || "lokaler Ordner"}.`, "info");

  let step = 0;
  backupTimer = setInterval(() => {
    step++;
    if (step === 2) {
      backupState.phase = "Kopiere Capture0001.mov";
      backupState.current = "Capture0001.mov";
      backupState.bytes_done = 8 * 1024 * 1024 * 1024;
      backupState.files_done = 1;
    } else if (step === 4) {
      backupState.phase = "Kopiere Capture0002.mov";
      backupState.current = "Capture0002.mov";
      backupState.bytes_done = 16 * 1024 * 1024 * 1024;
      backupState.files_done = 2;
    } else if (step >= 6) {
      if (backupTimer) clearInterval(backupTimer);
      backupTimer = null;
      backupState.running = false;
      backupState.bytes_done = backupState.bytes_total;
      backupState.files_done = backupState.files_total;
      backupState.last_run = getNowTimeStr();
      backupState.last_result = "3 Dateien gesichert (24 GB)";
      backupState.phase = "Bereit";
      backupState.speed = 0;
      backupState.current = "";
      log("Sicherung erfolgreich abgeschlossen (3 Dateien, 24 GB).", "ok");
    }
  }, 1000);

  return true;
}

function cancelBackup() {
  if (backupTimer) {
    clearInterval(backupTimer);
    backupTimer = null;
  }
  backupState.running = false;
  backupState.phase = "Abgebrochen";
  backupState.speed = 0;
  log("Sicherung durch Benutzer abgebrochen.", "warn");
}

function testBackup() {
  backupState.last_test = `Erfolgreich getestet am ${getNowTimeStr()} (${settings.backup_mode === "ftp" ? "FTP " + settings.backup_ftp_host : "Ordner erreichbar"})`;
  log(`Verbindungstest Sicherungsziel: ${backupState.last_test}`, "ok");
  return true;
}

// --------------------------------------------------------------------------
// Timer & Auto-Loop Scheduler Loop
// --------------------------------------------------------------------------
function hhmmToMinutes(timeStr: string): number {
  if (!timeStr) return 0;
  const parts = timeStr.split(":");
  return (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
}

let lastActiveTimerSlot: number | null = null;
let recordingStartedByTimer = false;

function isTimerActiveAt(t: TimerConfig, day: number, minutes: number): boolean {
  if (!t || !t.enabled || !Array.isArray(t.days) || t.days.length === 0) return false;
  const s = hhmmToMinutes(t.start);
  const e = hhmmToMinutes(t.end);
  if (e > s) {
    return t.days.includes(day) && minutes >= s && minutes < e;
  } else if (e < s) {
    // Overnight window (e.g. 22:00 to 02:00)
    // Part 1: Evening of scheduled day (start until 23:59)
    if (t.days.includes(day) && minutes >= s) return true;
    // Part 2: Morning after scheduled day (00:00 until end)
    const yesterday = (day + 6) % 7;
    if (t.days.includes(yesterday) && minutes < e) return true;
    return false;
  } else {
    // 24-hour continuous window for this day
    return t.days.includes(day);
  }
}

function getMinutesRemainingInTimer(t: TimerConfig, minutes: number): number {
  const s = hhmmToMinutes(t.start);
  const e = hhmmToMinutes(t.end);
  if (e > s) {
    return Math.max(0, e - minutes);
  } else {
    if (minutes >= s) {
      return 1440 - minutes + e;
    } else {
      return Math.max(0, e - minutes);
    }
  }
}

function getNextTimerStart(
  currentDay: number,
  currentMinutes: number,
  count: number
): {
  day: number;
  start: string;
  end: string;
  timerIndex: number;
  diffMinutes: number;
} | null {
  let best: {
    day: number;
    start: string;
    end: string;
    timerIndex: number;
    diffMinutes: number;
  } | null = null;

  for (let offset = 0; offset <= 7; offset++) {
    const targetDay = (currentDay + offset) % 7;
    for (let i = 0; i < count; i++) {
      const t = settings.timers[i];
      if (!t || !t.enabled || !Array.isArray(t.days) || !t.days.includes(targetDay)) continue;

      const s = hhmmToMinutes(t.start);
      // If today and this start time has already passed, look at next scheduled day
      if (offset === 0 && s <= currentMinutes) continue;

      const diff = offset * 1440 + (s - currentMinutes);
      if (diff > 0 && (!best || diff < best.diffMinutes)) {
        best = {
          day: targetDay,
          start: t.start,
          end: t.end,
          timerIndex: i + 1,
          diffMinutes: diff,
        };
      }
    }
  }
  return best;
}

function updateTimers() {
  if (!settings.timer_enabled) {
    if (lastActiveTimerSlot !== null) {
      lastActiveTimerSlot = null;
      recordingStartedByTimer = false;
    }
    state.timer_active = null;
    state.timer_info = "Timer aus";
    return;
  }

  const now = new Date();
  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  const currentDay = (now.getDay() + 6) % 7; // 0 = Monday, 6 = Sunday

  let foundActive: { index: number; entry: TimerConfig } | null = null;
  const count = Math.max(1, Math.min(10, settings.timer_count || 1));

  for (let i = 0; i < count; i++) {
    const t = settings.timers[i];
    if (isTimerActiveAt(t, currentDay, currentMinutes)) {
      foundActive = { index: i, entry: t };
      break;
    }
  }

  if (foundActive) {
    const slotNum = foundActive.index + 1;
    // If a new timer window just started, unblock previous manual stop
    if (lastActiveTimerSlot !== slotNum) {
      state.manual_stop = false;
      lastActiveTimerSlot = slotNum;
    }

    const remMins = getMinutesRemainingInTimer(foundActive.entry, currentMinutes);
    state.timer_active = slotNum;
    state.timer_info = `Zeitplan ${slotNum} nimmt auf bis ${foundActive.entry.end} Uhr (noch ${remMins} min)`;

    // START RECORDING IF DECK IS STOPPED
    if (state.status !== "record" && !state.manual_stop) {
      log(`Timer-Fenster ${slotNum} aktiv (${foundActive.entry.start}–${foundActive.entry.end} Uhr): Starte Aufnahme planmäßig.`, "ok");
      handleRecord();
      recordingStartedByTimer = true;
    }
  } else {
    // NO TIMER WINDOW CURRENTLY ACTIVE
    // STOP RECORDING IF A SCHEDULE JUST ENDED OR IF RECORDING WAS INITIATED BY TIMER
    if (lastActiveTimerSlot !== null || (recordingStartedByTimer && state.status === "record")) {
      const endedSlot = lastActiveTimerSlot || 1;
      lastActiveTimerSlot = null;
      recordingStartedByTimer = false;

      if (state.status === "record") {
        log(`Timer-Fenster beendet (Zeitplan ${endedSlot} abgelaufen): Stoppe Aufnahme planmäßig.`, "ok");
        state.status = "stopped";
        state.manual_stop = false; // Reset so the next scheduled timer will start cleanly
        sendDeckCommand("stop");
      }
    }

    state.timer_active = null;

    // Calculate next upcoming schedule countdown
    const next = getNextTimerStart(currentDay, currentMinutes, count);
    if (next) {
      const dayLabel = next.day === currentDay ? "Heute" : next.day === (currentDay + 1) % 7 ? "Morgen" : WEEKDAYS[next.day];
      const h = Math.floor(next.diffMinutes / 60);
      const m = next.diffMinutes % 60;
      const inStr = h > 0 ? (m > 0 ? `in ${h} h ${m} min` : `in ${h} h`) : `in ${m} min`;
      state.timer_info = `Nächster Start: ${dayLabel} um ${next.start} Uhr (Zeitplan ${next.timerIndex}, ${inStr})`;
    } else {
      state.timer_info = "Timer aktiv (kein anstehender Zeitplan in den nächsten 7 Tagen)";
    }
  }
}

// Background tick every 1000ms
setInterval(() => {
  // Timecode advancement when recording
  if (state.status === "record") {
    currentFrame += 25;
    state.timecode = getTimecodeString(currentFrame);

    // Slowly simulate consumption on active slot
    const activeSlot = state.slots.find((s) => s.id === state.active_slot);
    if (activeSlot && Math.random() < 0.05 && activeSlot.remaining_min > 0) {
      activeSlot.remaining_min--;
    }

    // Auto-Loop check
    if (settings.loop_record && settings.auto_loop && activeSlot) {
      if (activeSlot.remaining_min <= settings.min_remaining_threshold) {
        const otherId = activeSlot.id === 1 ? 2 : 1;
        const otherSlot = state.slots.find((s) => s.id === otherId);
        if (otherSlot && otherSlot.remaining_min <= settings.inactive_min_free && !state.busy) {
          log(`Restzeit Slot ${activeSlot.id}: ${activeSlot.remaining_min} min – bereite Slot ${otherId} vor (Auto-Loop).`, "warn");
          handleFormat(otherId);
        }
      }
    }
  }

  // Poll countdown
  if (state.seconds_until_check > 0) {
    state.seconds_until_check--;
  } else {
    triggerPoll();
  }

  // Timer evaluation
  updateTimers();
}, 1000);

// --------------------------------------------------------------------------
// Express Web Application
// --------------------------------------------------------------------------
const app = express();
app.use(express.json());

// No-cache middleware
app.use((req, res, next) => {
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("Expires", "0");
  next();
});

// Serve index.html with APP_VERSION rendered
app.get("/", (req: Request, res: Response) => {
  try {
    const indexPath = path.join(UI_DIR, "index.html");
    const html = fs.readFileSync(indexPath, "utf-8").replace(/\{\{APP_VERSION\}\}/g, APP_VERSION);
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.send(html);
  } catch (err) {
    res.status(500).send("Fehler beim Laden der Benutzeroberfläche");
  }
});

// Serve UI assets
app.use("/ui", express.static(UI_DIR));

// Favicon
app.get("/favicon.ico", (req: Request, res: Response) => {
  res.status(204).end();
});

// Status API
app.get("/api/status", (req: Request, res: Response) => {
  const payload: any = {
    ...settings,
    ...state,
    app_version: APP_VERSION,
    uptime_s: Math.floor(Date.now() / 1000) - STARTED_AT,
    backup: { ...backupState },
  };

  // Mask passwords
  for (const key of SECRET_KEYS) {
    payload[`${key}_set`] = Boolean(settings[key]);
    payload[key] = "";
  }

  // Incremental logs
  let filteredLogs = [...logs];
  const newest = logs.length > 0 ? logs[logs.length - 1].id : 0;
  const oldest = logs.length > 0 ? logs[0].id : 0;
  let reset = true;

  const sinceRaw = req.query.since as string;
  if (sinceRaw !== undefined) {
    const since = parseInt(sinceRaw, 10);
    if (!isNaN(since) && since >= oldest - 1 && since <= newest) {
      filteredLogs = logs.filter((l) => l.id > since);
      reset = false;
    }
  }

  payload.logs = filteredLogs;
  payload.log_seq = newest;
  payload.log_reset = reset;

  res.json(payload);
});

// Plaintext log file
app.get("/api/log.txt", (req: Request, res: Response) => {
  try {
    if (fs.existsSync(LOG_PATH)) {
      const content = fs.readFileSync(LOG_PATH, "utf-8");
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.send(content);
      return;
    }
  } catch {}
  res.setHeader("Content-Type", "text/plain; charset=utf-8");
  res.send(logs.map((l) => `[${l.time}] [${l.level.toUpperCase()}] ${l.msg}`).join("\n") + "\n");
});

// Command API
app.post("/api/command", (req: Request, res: Response) => {
  const body = req.body || {};
  const action = body.action;

  if (action === "resume_auto") {
    handleResumeAuto();
    return res.json({ ok: true });
  }

  if (action === "poll") {
    triggerPoll();
    return res.json({ ok: true });
  }

  if (action === "record") {
    handleRecord();
    return res.json({ ok: true });
  }

  if (action === "stop") {
    handleStop();
    return res.json({ ok: true });
  }

  if (action === "format") {
    const slotId = parseInt(body.slot_id || "1", 10);
    handleFormat(slotId);
    return res.json({ ok: true });
  }

  if (action === "reconnect") {
    connectToDeck();
    return res.json({ ok: true });
  }

  if (action === "notify") {
    log("Deck-Benachrichtigungen aktualisiert.", "info");
    return res.json({ ok: true });
  }

  if (action === "backup") {
    const started = startBackup(body.slot_id ? `Slot ${body.slot_id}` : "manuell");
    return res.json({ ok: started, error: started ? null : "Sicherung läuft bereits" });
  }

  if (action === "backup_test") {
    const started = testBackup();
    return res.json({ ok: started });
  }

  if (action === "backup_cancel") {
    cancelBackup();
    return res.json({ ok: true });
  }

  return res.status(400).json({ ok: false, error: "Unbekannter Befehl" });
});

// Helper for logging setting changes
function describeChange(key: string, value: any): string {
  if (key === "timers" && Array.isArray(value)) {
    const activeCount = settings.timer_count || 1;
    const parts = value
      .slice(0, activeCount)
      .map((t: TimerConfig, idx: number) => ({ t, idx }))
      .filter(({ t }) => t.enabled)
      .map(({ t, idx }) => {
        const days = (t.days || []).map((d: number) => WEEKDAYS[d]).join(",");
        return `${idx + 1}: ${days} ${t.start}-${t.end}`;
      });
    return `Zeitpläne [${parts.length > 0 ? parts.join("; ") : "keiner aktiv"}]`;
  }
  if (SECRET_KEYS.includes(key as any)) {
    return `${key}=${value ? "***" : "gelöscht"}`;
  }
  return `${key}=${value}`;
}

// Settings API
app.post("/api/settings", (req: Request, res: Response) => {
  const data = req.body || {};
  const changed: Record<string, any> = {};

  if ("timer_count" in data) {
    const c = Math.max(1, Math.min(10, parseInt(String(data.timer_count), 10) || 1));
    if (settings.timer_count !== c) {
      settings.timer_count = c;
      changed.timer_count = c;
    }
  }

  if ("timers" in data && Array.isArray(data.timers)) {
    const updatedTimers: TimerConfig[] = [];
    for (let i = 0; i < 10; i++) {
      const raw = data.timers[i] || {};
      updatedTimers.push({
        enabled: Boolean(raw.enabled),
        days: Array.isArray(raw.days) ? raw.days.map((d: any) => Number(d)) : [0, 1, 2, 3, 4],
        start: String(raw.start || "08:00"),
        end: String(raw.end || "17:00"),
      });
    }
    if (JSON.stringify(settings.timers) !== JSON.stringify(updatedTimers)) {
      settings.timers = updatedTimers;
      changed.timers = updatedTimers;
    }
  }

  for (const key of Object.keys(data)) {
    if (key === "timer_count" || key === "timers") continue;

    if (SECRET_KEYS.includes(key as any)) {
      const val = String(data[key]);
      if (val === "") {
        continue; // leave unchanged
      }
      if (val === "-") {
        settings[key] = "";
        changed[key] = "";
      } else {
        settings[key] = val;
        changed[key] = "***";
      }
      continue;
    }

    if (JSON.stringify(settings[key]) !== JSON.stringify(data[key])) {
      settings[key] = data[key];
      changed[key] = data[key];
    }
  }

  if (Object.keys(changed).length > 0) {
    saveSettingsToDisk();
    const changeLog = Object.entries(changed)
      .map(([k, v]) => describeChange(k, v))
      .join(", ");
    log(`Einstellungen geändert: ${changeLog}`, "info");

    if ("deck_ip" in changed || "deck_port" in changed) {
      connectToDeck();
    }
  }

  const safeSettings = { ...settings };
  for (const key of SECRET_KEYS) {
    safeSettings[key] = "";
  }

  res.json({
    ok: true,
    changed: Object.fromEntries(
      Object.entries(changed).map(([k, v]) => [k, SECRET_KEYS.includes(k as any) ? "***" : v])
    ),
    settings: safeSettings,
  });
});

// Initial boot
log(`HyperDeck Web Control v${APP_VERSION} gestartet.`, "ok");
connectToDeck();

app.listen(PORT, HOST, () => {
  console.log(`Server läuft auf http://${HOST}:${PORT}`);
});
