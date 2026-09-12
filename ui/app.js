var $ = function(id){ return document.getElementById(id); };
var dirty = {};          // vom Benutzer angefasste Felder nicht ueberschreiben
var timerDirty = false;  // ungespeicherte Aenderung an den Zeitplaenen
var logSeq = 0;          // zuletzt empfangene Log-Zeile
var lastInterval = 60;
var settingsDirty = false;   // ungespeicherte Aenderung in einem Eingabefeld
var DAYS = ['Mo','Di','Mi','Do','Fr','Sa','So'];

// Das Deck antwortet in Protokollsprache - hier wird daraus Deutsch.
var TRANSPORT_TEXT = {
  record: 'REC', stopped: 'GESTOPPT', play: 'WIEDERGABE', preview: 'VORSCHAU',
  forward: 'VORLAUF', rewind: 'RÜCKLAUF', jog: 'JOG', shuttle: 'SHUTTLE',
  offline: 'OFFLINE', unbekannt: 'UNBEKANNT'
};
var SLOT_TEXT = {
  mounted: 'Karte bereit', mounting: 'Karte wird gelesen', empty: 'keine Karte',
  error: 'Kartenfehler', unknown: 'unbekannt'
};

function minutesText(n){
  n = Number(n);
  if (!isFinite(n)) return '—';
  return n === 1 ? '1 Minute' : n + ' Minuten';
}

function hoursHint(mins){
  mins = Number(mins) || 0;
  if (mins < 90) return '';
  var h = Math.floor(mins / 60), m = mins % 60;
  return 'gut ' + h + ':' + (m < 10 ? '0' : '') + m + ' h';
}

function slotLabel(folder){
  // Die Ordner am Deck heissen je nach Modell "2", "sd2" oder "cfast2".
  var m = String(folder).match(/(\d)$/);
  return m ? 'Slot ' + m[1] : String(folder);
}
var HINT_DEFAULT = {
  saveHint: 'Werden in hyperdeck_config.json gesichert.',
  bkSaveHint: 'Dateien werden nie überschrieben oder am Deck gelöscht.'
};

function fmtBytes(n){
  n = Number(n) || 0;
  var units = ['B','KB','MB','GB','TB'], i = 0;
  while (n >= 1024 && i < units.length - 1){ n /= 1024; i++; }
  return (i === 0 ? String(Math.round(n)) : n.toFixed(1).replace('.', ',')) + ' ' + units[i];
}

function fmtDur(sec){
  sec = Math.max(0, Math.round(Number(sec) || 0));
  if (sec < 60) return sec + ' s';
  var two = function(n){ return (n < 10 ? '0' : '') + n; };
  if (sec < 3600) return Math.floor(sec / 60) + ':' + two(sec % 60) + ' min';
  var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h < 24) return h + ':' + two(m) + ' h';
  var d = Math.floor(h / 24);
  return d + ' Tag' + (d === 1 ? '' : 'en') + ' ' + (h % 24) + ' h';
}

function etaText(done, total, speed){
  if (!(speed > 0) || !total || total <= done) return '';
  return 'noch etwa ' + fmtDur((total - done) / speed);
}

function setHint(id, text, resetAfter){
  var el = $(id);
  if (!el) return;
  el.textContent = text;
  if (resetAfter){
    setTimeout(function(){ if (!settingsDirty) el.textContent = HINT_DEFAULT[id] || ''; }, resetAfter);
  }
}

var toastTimer = null;
function toast(text){
  var el = $('toast');
  if (!el){
    el = document.createElement('div');
    el.id = 'toast'; el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.className = 'toast show';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){ el.className = 'toast'; }, 4000);
}

// Countdown laeuft lokal weiter, damit er auch zwischen zwei Serverantworten tickt
var cdValue = null;
var cdStamp = 0;
var busyNow = '';

function num(v){
  var n = Number(v);
  return (v === null || v === '' || typeof v === 'undefined' || !isFinite(n)) ? null : n;
}

function esc(s){
  return String(s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}

async function api(path, body){
  var opt = {};
  if (body){
    opt = { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) };
  }
  var res = await fetch(path, opt);
  return res.json();
}

async function send(action, extra){
  var payload = { action: action };
  if (extra){ for (var k in extra){ payload[k] = extra[k]; } }
  var res;
  try {
    res = await api('/api/command', payload);
  } catch (e){
    toast('Befehl konnte nicht gesendet werden.');
    return;
  }
  if (res && res.ok === false && res.error) toast(res.error);
  refresh();
}

async function setFlag(key, value){
  var body = {};
  body[key] = value;
  await api('/api/settings', body);
  refresh();
}

async function formatSlot(id){
  var text = 'Slot ' + id + ' wirklich formatieren? Alle Aufnahmen auf dieser Karte gehen verloren.';
  if (backupTarget) text += '\n\nNoch nicht gesicherte Clips sind danach weg - im Zweifel erst "Karte sichern".';
  if (!confirm(text)) return;
  await send('format', { slot_id: id });
}

var backupTarget = false;

function backupSlot(id){
  send('backup', { slot_id: id });
  toast('Sicherung von Slot ' + id + ' angestoßen.');
}

/* ---------- Zeitplaene ------------------------------------------------ */

function buildTimerRows(){
  var html = '';
  for (var i = 0; i < 3; i++){
    var d = '';
    for (var k = 0; k < 7; k++){
      d += '<button type="button" class="day" id="t' + i + '_d' + k +
           '" onclick="toggleDay(' + i + ',' + k + ')">' + DAYS[k] + '</button>';
    }
    html +=
      '<div class="trow" id="trow' + i + '" hidden>' +
        '<div class="trow-head">' +
          '<div><div class="trow-name">Autorecord ' + (i + 1) + '</div>' +
          '<div class="trow-sum" id="t' + i + '_sum"></div></div>' +
          '<label class="toggle-mini">aktiv' +
            '<input type="checkbox" id="t' + i + '_on" onchange="timerTouched()">' +
            '<span class="track" id="t' + i + '_tr"></span>' +
          '</label>' +
        '</div>' +
        '<div class="days">' + d + '</div>' +
        '<div class="times">' +
          '<div class="field"><label for="t' + i + '_start">Start</label>' +
            '<input type="time" id="t' + i + '_start" onchange="timerTouched()"></div>' +
          '<div class="field"><label for="t' + i + '_end">Ende</label>' +
            '<input type="time" id="t' + i + '_end" onchange="timerTouched()"></div>' +
        '</div>' +
      '</div>';
  }
  $('timerRows').innerHTML = html;
}

function toggleDay(i, k){
  var el = $('t' + i + '_d' + k);
  el.className = (el.className.indexOf('on') >= 0) ? 'day' : 'day on';
  timerTouched();
}

function timerTouched(){
  timerDirty = true;
  $('timerHint').textContent = 'Nicht gespeichert - auf "Zeitpläne speichern" klicken.';
  for (var i = 0; i < 3; i++){ paintRow(i); }
}

function paintRow(i){
  var on = $('t' + i + '_on').checked;
  $('t' + i + '_tr').className = on ? 'track on' : 'track';
  $('trow' + i).className = on ? 'trow' : 'trow off';
  var days = [];
  for (var k = 0; k < 7; k++){
    if ($('t' + i + '_d' + k).className.indexOf('on') >= 0) days.push(DAYS[k]);
  }
  var s = $('t' + i + '_start').value, e = $('t' + i + '_end').value;
  var over = (s && e && e <= s) ? ' (über Mitternacht)' : '';
  $('t' + i + '_sum').textContent = !on ? 'ausgeschaltet'
    : (!days.length ? 'kein Wochentag gewählt'
    : days.join(' ') + ' · ' + s + '–' + e + ' Uhr' + over);
}

function fillTimers(d){
  var count = num(d.timer_count) || 1;
  for (var i = 0; i < 3; i++){ $('trow' + i).hidden = (i >= count); }
  if (document.activeElement !== $('timerCount')) $('timerCount').value = count;
  if (timerDirty) return;                       // Eingaben nicht ueberschreiben
  var list = d.timers || [];
  for (var j = 0; j < 3; j++){
    var t = list[j] || {};
    $('t' + j + '_on').checked = !!t.enabled;
    if (document.activeElement !== $('t' + j + '_start')) $('t' + j + '_start').value = t.start || '';
    if (document.activeElement !== $('t' + j + '_end')) $('t' + j + '_end').value = t.end || '';
    var days = t.days || [];
    for (var k = 0; k < 7; k++){
      $('t' + j + '_d' + k).className = (days.indexOf(k) >= 0) ? 'day on' : 'day';
    }
    paintRow(j);
  }
}

async function setCount(value){
  await api('/api/settings', { timer_count: value });
  refresh();
}

async function saveTimers(){
  var list = [];
  for (var i = 0; i < 3; i++){
    var days = [];
    for (var k = 0; k < 7; k++){
      if ($('t' + i + '_d' + k).className.indexOf('on') >= 0) days.push(k);
    }
    list.push({
      enabled: $('t' + i + '_on').checked,
      days: days,
      start: $('t' + i + '_start').value || '00:00',
      end: $('t' + i + '_end').value || '00:00'
    });
  }
  await api('/api/settings', { timers: list, timer_count: $('timerCount').value });
  timerDirty = false;
  $('timerHint').textContent = 'Gespeichert.';
  setTimeout(function(){ $('timerHint').textContent = 'Uhrzeiten wirken sofort nach dem Speichern.'; }, 4000);
  refresh();
}

function discardTimers(){
  timerDirty = false;
  $('timerHint').textContent = 'Änderungen verworfen.';
  refresh();
}

async function saveSettings(hintId){
  hintId = hintId || 'saveHint';
  var body = {};
  var nodes = document.querySelectorAll('[data-key]');
  for (var i = 0; i < nodes.length; i++){
    var el = nodes[i];
    if (el.type === 'password' && el.value === '') continue;   // leer = unveraendert
    body[el.dataset.key] = el.value;
  }
  var res = await api('/api/settings', body);
  dirty = {};
  settingsDirty = false;
  for (var j = 0; j < nodes.length; j++){ if (nodes[j].type === 'password') nodes[j].value = ''; }
  var keys = Object.keys(res.changed || {});
  var text = keys.length ? ('Gespeichert: ' + keys.join(', ')) : 'Keine Änderung.';
  setHint('saveHint', hintId === 'saveHint' ? text : HINT_DEFAULT.saveHint, 4000);
  setHint('bkSaveHint', hintId === 'bkSaveHint' ? text : HINT_DEFAULT.bkSaveHint, 4000);
  refresh();
}

function markSettingsDirty(){
  if (settingsDirty) return;
  settingsDirty = true;
  setHint('saveHint', 'Nicht gespeichert - auf "Einstellungen speichern" klicken.');
  setHint('bkSaveHint', 'Nicht gespeichert - auf "Sicherung speichern" klicken.');
}

document.addEventListener('input', function(e){
  if (e.target && e.target.dataset && e.target.dataset.key){ dirty[e.target.dataset.key] = true; markSettingsDirty(); }
});
document.addEventListener('change', function(e){
  if (e.target && e.target.dataset && e.target.dataset.key){ dirty[e.target.dataset.key] = true; markSettingsDirty(); }
});

function fillField(id, key, value){
  var el = $(id);
  if (!el || el.type === 'password' || dirty[key] || document.activeElement === el) return;
  if (el.value !== String(value)) el.value = value;
}

function setSwitch(key, on){
  var box = $('sw_' + key), track = $('tr_' + key);
  if (!box) return;
  box.checked = !!on;
  track.className = on ? 'track on' : 'track';
}

function renderSlots(d){
  if (!d.slots || !d.slots.length){
    $('slots').innerHTML = '<div class="panel">Keine Slot-Daten vom Deck.</div>';
    return;
  }
  var scale = 60;
  for (var i = 0; i < d.slots.length; i++){ scale = Math.max(scale, num(d.slots[i].remaining_min) || 0); }
  var threshold = num(d.min_remaining_threshold) || 0;
  var html = '';
  for (var j = 0; j < d.slots.length; j++){
    var s = d.slots[j];
    var mins = num(s.remaining_min);
    var isActive = d.active_slot === s.id;
    var rec = isActive && String(d.status).indexOf('record') === 0;
    var low = rec && mins !== null && mins <= threshold;
    var pct = Math.max(2, Math.min(100, Math.round((mins || 0) / scale * 100)));
    var mounted = s.status === 'mounted' && mins !== null;
    var lf = (d.last_format || {})[String(s.id)];
    var stamp = lf ? 'zuletzt geleert ' + esc(lf) : '';
    html += '<div class="slot' + (isActive ? ' active' : '') + (low ? ' low' : '') + '">' +
      '<div class="slot-head"><div class="slot-name">Slot ' + s.id +
        (s.volume ? ' · <span style="color:var(--dim2);font-weight:400">' + esc(s.volume) + '</span>' : '') +
      '</div>' +
      (isActive ? '<span class="tag' + (rec ? ' rec' : '') + '">' + (rec ? 'nimmt auf' : 'in Benutzung') + '</span>' : '') +
      '</div>' +
      '<div class="mins">' + (mounted ? mins : '—') +
        '<small>' + (mounted ? (mins === 1 ? 'Minute frei' : 'Minuten frei') : 'keine Angabe') +
        (mounted && hoursHint(mins) ? ' · ' + hoursHint(mins) : '') + '</small></div>' +
      '<div class="bar"><span class="' + (low ? 'low' : '') + '" style="width:' + (mounted ? pct : 0) + '%"></span></div>' +
      '<div class="meta"><span>' + esc(SLOT_TEXT[s.status] || s.status || 'unbekannt') +
        '</span><span>' + stamp + '</span></div>' +
      '<div class="slot-actions"><button class="b-sm b-ghost" ' + (mounted ? '' : 'disabled ') +
        'onclick="formatSlot(' + s.id + ')">Karte leeren</button>' +
        (backupTarget ? '<button class="b-sm b-ghost" ' + (mounted ? '' : 'disabled ') +
          'onclick="backupSlot(' + s.id + ')">Karte sichern</button>' : '') + '</div>' +
      '</div>';
  }
  $('slots').innerHTML = html;
}

function cardWarning(d){
  var slots = d.slots || [], active = null, other = null;
  for (var i = 0; i < slots.length; i++){
    if (slots[i].id === d.active_slot) active = slots[i]; else other = slots[i];
  }
  if (!active || String(d.status).indexOf('record') !== 0) return '';
  var limit = num(d.min_remaining_threshold) || 5;
  if (active.remaining_min > limit) return '';
  var rest = 'Slot ' + active.id + ' hat nur noch ' + minutesText(active.remaining_min) + ' frei';
  if (!other || other.status !== 'mounted'){
    return rest + ' und im anderen Slot steckt keine Karte. Bitte eine einlegen.';
  }
  if (!d.loop_record || !d.auto_loop){
    return rest + '. Die Endlosautomatik ist aus – das Deck wechselt auf Slot ' +
           other.id + ', danach ist Schluss.';
  }
  return '';
}

function renderLog(d){
  var logs = d.logs || [];
  var box = $('log');
  if (d.log_reset) box.innerHTML = '';
  if (typeof d.log_seq === 'number') logSeq = d.log_seq;
  if (!logs.length) return;
  var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  var html = '';
  for (var i = 0; i < logs.length; i++){
    html += '<div><span class="t">' + esc(logs[i].time) + '</span> <span class="' +
      esc(logs[i].level) + '">' + esc(logs[i].msg) + '</span></div>';
  }
  box.insertAdjacentHTML('beforeend', html);   // nur die neuen Zeilen anhaengen
  while (box.childElementCount > 250) box.removeChild(box.firstElementChild);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

/* ---------- Sicherung ------------------------------------------------- */

function updateBackupMode(){
  var mode = $('f_backup_mode').value;
  $('bkFolderWrap').hidden = mode !== 'folder';
  $('bkFtpWrap').hidden = mode !== 'ftp';
}

function renderBackup(d){
  var b = d.backup || {};
  var running = !!b.running;
  var done = (Number(b.bytes_done) || 0) + (running ? (Number(b.current_done) || 0) : 0);
  $('bkPhase').textContent = running ? (b.phase || 'Läuft')
    : (d.backup_enabled ? 'Bereit – sichert automatisch' : 'Bereit – nur auf Knopfdruck');
  var totalEta = etaText(done, b.bytes_total, b.speed);
  $('bkDetail').textContent = (running && b.files_total)
    ? (b.files_done + ' von ' + b.files_total + ' Dateien · ' + fmtBytes(done) + ' / ' +
       fmtBytes(b.bytes_total) + (totalEta ? ' · ' + totalEta : ''))
    : '';
  var pct = (running && b.bytes_total) ? Math.min(100, Math.round(done / b.bytes_total * 100)) : 0;
  $('bkBar').style.width = pct + '%';
  $('bkBar').parentNode.hidden = !running;
  $('bkFile').textContent = running && b.current ? b.current : '';
  var fileEta = etaText(b.current_done, b.current_size, b.speed);
  $('bkSpeed').textContent = running && b.speed
    ? fmtBytes(b.speed) + '/s' + (fileEta ? ' · Datei ' + fileEta : '') : '';
  $('bkCancel').hidden = !running;
  $('bkStatus').className = 'bk-status' + (running ? ' run' : '') + (b.error ? ' err' : '');

  var lines = [];
  if (b.last_run) lines.push('Letzter Lauf ' + b.last_run + ': ' + (b.last_result || ''));
  if (b.error) lines.push('Fehler: ' + b.error);
  if (b.pending) lines.push(b.pending + ' Datei(en) noch offen (in Aufnahme oder fehlgeschlagen)');
  if (!running && d.backup_enabled && b.next_run_s !== null && typeof b.next_run_s !== 'undefined'){
    lines.push('Nächster automatischer Lauf in ' + fmtDur(b.next_run_s));
  }
  if (b.last_test) lines.push('Verbindungstest: ' + b.last_test);
  $('bkLast').textContent = lines.join('\n');

  var tree = (b.tree || []).map(function(t){
    return slotLabel(t.name) + ' – ' + t.files + (t.files === 1 ? ' Datei' : ' Dateien') +
           ', ' + fmtBytes(t.bytes);
  });
  $('bkTree').textContent = tree.length ? 'Auf dem Deck liegen: ' + tree.join('  ·  ') : '';
  $('bkAutoHint').textContent = 'Kopiert fertige Clips alle ' + (num(d.backup_interval) || 15) +
    ' Minuten vom Deck ins Ziel';
  $('f_backup_ftp_pass').placeholder = d.backup_ftp_pass_set
    ? 'gespeichert · leer = unverändert · "-" = löschen' : 'Passwort';
  $('f_deck_ftp_pass').placeholder = d.deck_ftp_pass_set
    ? 'gespeichert · leer = unverändert · "-" = löschen' : 'leer = anonym';
}

function localCountdown(){
  if (cdValue === null) return null;
  return Math.max(0, cdValue - (Date.now() - cdStamp) / 1000);
}

function paintCountdown(){
  var v = localCountdown();
  if (busyNow){
    $('cd').textContent = '…';
    $('cdBar').style.width = '100%';
    return;
  }
  $('cd').textContent = (v === null) ? '--' : Math.ceil(v);
  $('cdBar').style.width = (v === null ? 0 : Math.max(0, Math.min(100, v / lastInterval * 100))) + '%';
}

async function refresh(){
  var d;
  try {
    d = await api('/api/status?since=' + logSeq);
  } catch (e){
    $('dot').className = 'dot off';
    $('linkTxt').textContent = 'Webserver nicht erreichbar';
    return;
  }

  $('device').textContent = d.device || 'HyperDeck Control';
  if (d.app_version) $('ver').textContent = 'v' + d.app_version;
  $('host').textContent = d.deck_ip + ':' + d.deck_port;
  $('dot').className = 'dot ' + (d.connected ? 'on' : 'off');
  $('linkTxt').textContent = d.connected ? 'verbunden' : 'keine Verbindung';

  var recording = String(d.status).indexOf('record') === 0;
  document.title = (recording ? '● REC · ' : '') + (d.device || 'HyperDeck Control');
  $('tally').className = recording ? 'tally live' : 'tally';
  var statusKey = String(d.status || '').toLowerCase();
  $('tallyWord').textContent = recording ? 'REC'
    : (TRANSPORT_TEXT[statusKey] || String(d.status || '--').toUpperCase());
  $('tallySub').textContent = recording ? 'Aufnahme läuft'
    : (d.connected ? 'Deck steht' : 'keine Verbindung');
  $('tc').textContent = d.timecode;
  $('tcLabel').textContent = d.active_slot ? ('Timecode · Slot ' + d.active_slot) : 'Timecode';

  lastInterval = num(d.check_interval) || 60;
  var server = num(d.seconds_until_check);
  if (!d.connected || server === null){
    cdValue = null;
  } else if (cdValue === null || Math.abs(server - localCountdown()) > 1.5){
    cdValue = server; cdStamp = Date.now();     // neu synchronisieren
  }
  busyNow = d.busy || '';
  paintCountdown();
  $('pollLabel').textContent = d.notify
    ? ((d.timecode_stream ? 'Timecode und Zustand kommen live vom Deck'
                          : 'Das Deck meldet Änderungen sofort') + ' · Kontrollabfrage in ')
    : 'Nächste Abfrage in ';
  $('lastPoll').textContent = d.last_poll ? ('zuletzt ' + d.last_poll) : '';

  $('foot').textContent = 'HyperDeck Web Control v' + (d.app_version || '?') +
    ' · Deck ' + d.deck_ip + ':' + d.deck_port;

  $('timerState').textContent = d.timer_info || 'Timer aus';
  $('noticeTimer').hidden = !d.timer_active;
  $('timerTxt').textContent = d.timer_info || '';

  var warning = cardWarning(d);
  $('noticeCard').hidden = !warning;
  $('cardTxt').textContent = warning;

  $('noticeLock').hidden = !d.manual_stop;
  $('noticeBusy').hidden = !d.busy;
  $('busyTxt').textContent = d.busy ? (d.busy + ' … das kann eine Weile dauern.') : '';
  var showErr = !d.connected && d.connection_error;
  $('noticeErr').hidden = !showErr;
  if (showErr) $('errTxt').textContent = 'Deck nicht erreichbar: ' + d.connection_error;

  setSwitch('loop_record', d.loop_record);
  setSwitch('auto_record', d.auto_record);
  setSwitch('auto_loop', d.auto_loop);
  setSwitch('sync_timecode', d.sync_timecode);
  setSwitch('timer_enabled', d.timer_enabled);
  setSwitch('timecode_live', d.timecode_live);
  $('tcLiveHint').textContent = d.timecode_stream
    ? 'Läuft – das Deck schickt den Timecode im Bildtakt (etwa 16 kB/s)'
    : 'Das Deck schickt den Timecode laufend statt nur bei der Kontrollabfrage';
  setSwitch('backup_enabled', d.backup_enabled);
  setSwitch('backup_block_format', d.backup_block_format);
  $('autoRecHint').textContent = d.timer_enabled
    ? 'Ruht, solange der Timer aktiv ist - der Zeitplan entscheidet'
    : 'Startet die Aufnahme neu, wenn das Deck steht';
  backupTarget = !!(d.backup_mode === 'ftp' ? d.backup_ftp_host : d.backup_folder);

  // Die Unterschalter haengen am Hauptschalter Loop-Record
  var lr = !!d.loop_record;
  ['auto_record','auto_loop'].forEach(function(key){
    var box = $('sw_' + key);
    box.disabled = !lr;
    var row = box.parentNode;
    if (row && row.style) row.style.opacity = lr ? '' : '.45';
  });

  fillTimers(d);

  renderSlots(d);

  fillField('f_deck_ip', 'deck_ip', d.deck_ip);
  fillField('f_deck_port', 'deck_port', d.deck_port);
  fillField('f_check_interval', 'check_interval', d.check_interval);
  fillField('f_min_remaining_threshold', 'min_remaining_threshold', d.min_remaining_threshold);
  fillField('f_inactive_min_free', 'inactive_min_free', d.inactive_min_free);
  fillField('f_format_filesystem', 'format_filesystem', d.format_filesystem);
  fillField('f_format_name', 'format_name', d.format_name);

  fillField('f_backup_mode', 'backup_mode', d.backup_mode);
  fillField('f_backup_interval', 'backup_interval', d.backup_interval);
  fillField('f_backup_folder', 'backup_folder', d.backup_folder);
  fillField('f_backup_ftp_host', 'backup_ftp_host', d.backup_ftp_host);
  fillField('f_backup_ftp_port', 'backup_ftp_port', d.backup_ftp_port);
  fillField('f_backup_ftp_user', 'backup_ftp_user', d.backup_ftp_user);
  fillField('f_backup_ftp_path', 'backup_ftp_path', d.backup_ftp_path);
  fillField('f_backup_source_path', 'backup_source_path', d.backup_source_path);
  fillField('f_deck_ftp_port', 'deck_ftp_port', d.deck_ftp_port);
  fillField('f_deck_ftp_user', 'deck_ftp_user', d.deck_ftp_user);
  updateBackupMode();
  renderBackup(d);
  $('uptime').textContent = 'Dienst läuft seit ' + fmtDur(d.uptime_s);

  renderLog(d);
}

buildTimerRows();
setInterval(function(){ if (!document.hidden) refresh(); }, 1000);
setInterval(function(){ if (!document.hidden) paintCountdown(); }, 250);
refresh();
