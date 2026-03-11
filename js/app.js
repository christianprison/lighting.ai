/**
 * js/app.js — lighting.ai DB Editor
 *
 * Meilenstein 2: Vollstaendiger DB Editor mit Song-Detail,
 * Bar-Editor mit 16tel-Accent-Raster und Summary-Bar.
 */

import { loadDB, loadDBLocal, saveDB, testConnection, uploadFile, deleteFile, getSha } from './db.js';
import * as audio from './audio-engine.js';
import * as integrity from './integrity.js';

/* ── Version (single source of truth) ──────────────── */
const APP_VERSION = 'v1.6.6';

/* ── State ─────────────────────────────────────────── */
let db = null;
let dbSha = null;
let dirty = false;
let readOnly = true;
let activeTab = 'editor';
let selectedSongId = null;
let selectedBarNum = null;


/* ── Takte Tab State ─────────────────────────────── */
let takteTabFilterSong = '';
let takteTabSelectedBar = null;  // {songId, barNum}

/* ── Lyrics Editor State (Block-based Canvas) ──── */
let _leBlocks = [];             // [{type:'bar'|'word', id, content, barNum}]
let _leInitSongId = null;       // songId for which blocks were built
let _leDrag = null;             // active drag state
let _leContextMenu = null;      // active context menu element
let _leClipboard = null;        // copied word block for paste

/* ── Audio Split State ────────────────────────────── */
let audioMeta = null;          // {duration, sampleRate, channels}
let audioFileName = null;      // name of loaded file
let markers = [];              // [{time}] sorted by time
let tapHistory = [];           // [{time}] for undo
let animFrameId = null;        // requestAnimationFrame for playhead
let exportInProgress = false;
let playbackSpeed = 1.0;       // current playback speed multiplier
let waveformZoom = 1.0;        // waveform zoom level (linked to speed)
const _audioRefCache = {};     // songId → ArrayBuffer (cached reference audio)

/* ── Waveform Marker Drag State ──────────────────── */
let _dragMarker = null;        // { marker: ref, originalTime: number }
let _isDragging = false;       // true while actively dragging (moved > threshold)
let _dragStartX = 0;           // mouse/touch start X for drag threshold
let _dragSuppressClick = false; // prevent seek after drag ends
let clickEnabled = false;        // click track on/off
let _suppressAutoScroll = false; // prevent auto-scroll after drag finalize
let _isTouchDrag = false;       // true when drag was initiated by touch (not mouse)

const SETTINGS_KEY = 'lightingai_settings';

/* ── Constants ─────────────────────────────────────── */

// Light templates — identisch zu den Gruppen in live/ui/config.html (QLC+ Szenen)
// Gruppiert als Baumstruktur: { label: string, items: string[] }[]
const LIGHT_TEMPLATE_GROUPS = [
  { label: 'Basis-Szenen', items: [
    '00 blackout',
    '01 statisch bunt',
    '02 slow blue',
    '03 walking',
    '04 up\'n\'down',
    '05 left\'n\'right',
    '06 blinking',
    '07 round\'n\'round',
    '08 swimming',
  ]},
  { label: 'Alarm / Strobe / Stop', items: [
    '09 Alarm',
    '10 Alarm \uD83D\uDD14\uD83D\uDD14',
    '10 Strobe',
    '11 Stop',
  ]},
  { label: 'Farb-Szenen', items: [
    '12 slow red',
    '16 Searchlight',
  ]},
  { label: 'White Fan / Blind', items: [
    '20 white Fan up',
    '21 white fan down',
    '22 blind',
  ]},
  { label: 'D O R up W', items: [
    'D O R up W',
  ]},
  { label: 'Einzelszenen', items: [
    'Chor (collection)',
    'Heads Cross White',
    'Heads Publikum',
    'heads white open',
    'PAR Blue + Fog',
    'PAR Green + Fog',
    'red and green alternating',
    'S\u00e4ulen red drip',
    'static dark blue',
    'stripes from center',
    'strips twinkle',
    'TMHs center stage yellow',
    'up\'n\'down (ohne effects)',
  ]},
  { label: 'Song-spezifisch', items: [
    'The Reason Intro',
    'Valerie Verse 2b',
    'Valerie Verse 3a (a capella)',
  ]},
  { label: 'Spots & Combos', items: [
    '03 walking + PARs Pete',
    'Inside Spot auf Axel und Tim',
    'Spot auf Axel & Bibo',
    'Spot auf Axel',
    'Spot auf Axel blackout',
    'Spot auf Bibo',
    'Spot auf PAC',
    'Spot auf PAC + Blinder',
    'Spot auf Pete',
    'Spot auf Tim',
    'Spot auf Tim hot',
  ]},
  { label: 'Accent / Utility', items: [
    'blind (accent)',
    'blackout (scene)',
    'Fog 10s',
    'Fog on',
    'Fog off',
    'Alarm neu (rot/gr\u00fcn)',
  ]},
];

/** Build <option> + <optgroup> HTML for the light template select */
function buildTemplateOptions(selected) {
  let html = '';
  for (const grp of LIGHT_TEMPLATE_GROUPS) {
    html += `<optgroup label="${grp.label}">`;
    for (const t of grp.items) {
      html += `<option value="${t}"${t === selected ? ' selected' : ''}>${t}</option>`;
    }
    html += '</optgroup>';
  }
  return html;
}

const ACCENT_TYPES = ['bl', 'bo', 'hl', 'st', 'fg'];

const ACCENT_INFO = {
  bl: 'Blinder', bo: 'Blackout', hl: 'Highlight', st: 'Strobe', fg: 'Fog'
};

const BEAT_LABELS = ['1','e','+','e','2','e','+','e','3','e','+','e','4','e','+','e'];

/* ── QLC+ QXW Constants ──────────────────────────── */

const QXW_INFINITE_HOLD = 4294967294;  // 0xFFFFFFFE — manual advance
const QXW_STOP_ID = 82;               // "11 Stop" — title/end marker

const QXW_BASE_COLLECTIONS = {
  70: '02 slow blue', 71: '01 statisch bunt', 74: '03 walking',
  75: "04 up'n'down", 76: "05 left'n'right", 77: '06 blinking',
  78: "07 round'n'round", 79: '08 swimming', 80: '09 Alarm',
  81: '10 Strobe', 82: '11 Stop', 83: '16 Searchlight',
  181: '20 white Fan up', 182: '21 white fan down',
  224: 'Spot auf Axel', 226: 'Spot auf Axel hot', 227: 'Spot auf Bibo',
  228: 'Spot auf Pete', 229: 'Spot auf Tim', 14: 'Spot auf Tim hot',
  212: 'blind (accent)',
  36: 'blackout (scene)',
};

/** QXW file content cache */
let _qxwCache = null; // { xml: string, chasers: Map<songName, steps[]> }

/* ── Settings ──────────────────────────────────────── */

function getSettings() {
  try { return JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; }
  catch { return {}; }
}

function saveSettings(s) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

function hasSettings() {
  const s = getSettings();
  return !!(s.repo && s.token && s.path);
}

/* ── DOM refs ──────────────────────────────────────── */
let els = {};

function cacheDom() {
  els = {
    syncStatus:    document.getElementById('sync-status'),
    tabEditor:     document.getElementById('tab-editor'),
    tabTakte:      document.getElementById('tab-takte'),
    tabAudio:      document.getElementById('tab-audio'),
    tabLyrics:     document.getElementById('tab-lyrics'),
    tabAccents:    document.getElementById('tab-accents'),
    tabSetlist:    document.getElementById('tab-setlist'),
    btnSettings:   document.getElementById('btn-settings'),
    btnSave:       document.getElementById('btn-save'),
    btnUndo:       document.getElementById('btn-undo'),
    searchBox:     document.getElementById('search-box'),
    songCount:     document.getElementById('song-count'),
    songList:      document.getElementById('song-list'),
    content:       document.getElementById('content'),
    modalOverlay:  document.getElementById('settings-modal'),
    inputRepo:     document.getElementById('set-repo'),
    inputToken:    document.getElementById('set-token'),
    inputPath:     document.getElementById('set-path'),
    btnTest:       document.getElementById('btn-test-conn'),
    testResult:    document.getElementById('test-result'),
    btnSaveSettings: document.getElementById('btn-save-settings'),
    btnCancelSettings: document.getElementById('btn-cancel-settings'),
    toastContainer: document.getElementById('toast-container'),
    btnHelp:       document.getElementById('btn-help'),
    helpModal:     document.getElementById('help-modal'),
    btnCloseHelp:  document.getElementById('btn-close-help'),
    sidebarToggle: document.getElementById('sidebar-toggle'),
    appEl:         document.getElementById('app'),
    confirmModal:  document.getElementById('confirm-modal'),
    confirmTitle:  document.getElementById('confirm-title'),
    confirmMsg:    document.getElementById('confirm-message'),
    confirmOk:     document.getElementById('confirm-ok'),
    confirmCancel: document.getElementById('confirm-cancel'),
  };
}

/* ── Sync Status ───────────────────────────────────── */

function setSyncStatus(status) {
  const labels = {
    saved: 'SAVED', unsaved: 'UNSAVED', saving: 'SAVING...',
    error: 'ERROR', loading: 'LOADING...', readonly: 'READ-ONLY',
  };
  els.syncStatus.dataset.status = status;
  els.syncStatus.textContent = labels[status] || status;
}

/* ── Clipboard (fallback for non-secure contexts) ──── */

function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback: execCommand('copy') for HTTP contexts
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    document.body.removeChild(ta);
    return Promise.resolve();
  } catch (e) {
    document.body.removeChild(ta);
    return Promise.reject(e);
  }
}

/* ── Toast ─────────────────────────────────────────── */

function toast(msg, type = 'info', duration = 3000) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  els.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

/* ── Utility ───────────────────────────────────────── */

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function calcBarsDuration(bars, bpm) {
  if (!bars || !bpm) return 0;
  return Math.round(bars * 4 * 60 / bpm);
}

function fmtDur(sec) {
  if (!sec) return '\u2014';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Sanitize a string for use as a folder/file name.
 * Replaces special chars with underscores, trims, collapses multiple underscores.
 */
function sanitizePath(str) {
  return (str || 'unknown')
    .replace(/[\/\\:*?"<>|#%&{}$!@`=^~]/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/_+/g, '_');
}

/**
 * Build the GitHub path for the reference audio file.
 * Format: audio/{Song Title}/{Song Title} - Full Song.mp3
 */
function buildRefAudioPath(song) {
  const songDir = sanitizePath(song.name);
  return `audio/${songDir}/${songDir} - Full Song.mp3`;
}

/**
 * Build the GitHub path for a bar audio file.
 * Format: audio/{Song Title}/{GlobalBarNum} {Song Title}.mp3
 * @param {object} song - the song object
 * @param {object} part - {id, pos, name, bars, ...}
 * @param {number} barNum - bar number within the part (1-based)
 * @param {number} globalBarNum - bar number within the song (1-based)
 */

/**
 * Try fetching an audio URL. If the new-format path fails (404),
 * try the GitHub API as fallback, then try the legacy ID-based path.
 * Returns an ArrayBuffer or null.
 */
async function fetchAudioUrl(url) {
  const s = getSettings();

  // 1. Direct fetch (works on GitHub Pages / local dev)
  try {
    const encodedUrl = url.split('/').map(encodeURIComponent).join('/');
    const res = await fetch(encodedUrl);
    if (res.ok) {
      const ct = res.headers.get('content-type') || '';
      if (!ct.includes('text/html')) return await res.arrayBuffer();
    }
  } catch { /* fall through */ }

  // 2. GitHub API fetch
  if (s.token && s.repo) {
    try {
      const encodedPath = url.split('/').map(encodeURIComponent).join('/');
      const apiUrl = `https://api.github.com/repos/${s.repo}/contents/${encodedPath}`;
      const res = await fetch(apiUrl, {
        headers: { 'Authorization': `token ${s.token}`, 'Accept': 'application/vnd.github.v3.raw' },
      });
      if (res.ok) return await res.arrayBuffer();
    } catch { /* fall through */ }
  }

  return null;
}

function ensureCollections() {
  if (!db.bars) db.bars = {};
  if (!db.accents) db.accents = {};
}

/** Get all bars for a song, sorted by bar_num */
function getBarsForSong(songId) {
  ensureCollections();
  return Object.entries(db.bars)
    .filter(([, b]) => b.song_id === songId)
    .map(([id, b]) => ({ id, ...b }))
    .sort((a, b) => a.bar_num - b.bar_num);
}

/** Get total bar count for a song */
function getTotalBars(songId) {
  const song = db.songs[songId];
  if (!song) return 0;
  return song.total_bars || 0;
}

function findBar(songId, barNum) {
  ensureCollections();
  for (const [id, b] of Object.entries(db.bars)) {
    if (b.song_id === songId && b.bar_num === barNum) return [id, b];
  }
  return null;
}

function getAccentsForBar(barId) {
  ensureCollections();
  return Object.entries(db.accents)
    .filter(([, a]) => a.bar_id === barId)
    .map(([id, a]) => ({ id, ...a }))
    .sort((a, b) => a.pos_16th - b.pos_16th);
}


function getOrCreateBar(songId, barNum) {
  const existing = findBar(songId, barNum);
  if (existing) return existing;
  const barId = nextId('B', db.bars);
  db.bars[barId] = { song_id: songId, bar_num: barNum, lyrics: '', audio: '', has_accents: false };
  return [barId, db.bars[barId]];
}

/** Reconcile total_bars with actual db.bars entries for a song */
function reconcileBars(songId) {
  const song = db.songs[songId];
  if (!song) return;
  ensureCollections();
  const actualBars = getBarsForSong(songId).length;
  if (actualBars !== (song.total_bars || 0)) {
    song.total_bars = actualBars;
    // recalcSongDuration uses selectedSongId – inline the logic for any songId
    const _bpm = song.bpm || 0;
    const _totalSec = calcBarsDuration(song.total_bars || 0, _bpm);
    song.duration_sec = _totalSec;
    song.duration = fmtDur(_totalSec);
  }
}

function nextId(prefix, collection) {
  const nums = Object.keys(collection)
    .map(k => parseInt(k.replace(prefix, ''), 10))
    .filter(n => !isNaN(n));
  const max = nums.length ? Math.max(...nums) : 0;
  return `${prefix}${String(max + 1).padStart(4, '0')}`;
}


function recalcSongDuration() {
  const song = db.songs[selectedSongId];
  if (!song) return;
  const totalSec = calcBarsDuration(song.total_bars || 0, song.bpm || 0);
  song.duration_sec = totalSec;
  song.duration = fmtDur(totalSec);
}

/* ── Song Progress Checklist ───────────────────────── */

/**
 * Detailed checklist grouped by category.
 * Each step has: id, label, category, tab, check(song, barIds, db)
 */
const PROGRESS_CATEGORIES = [
  { id: 'stammdaten', label: 'Stammdaten', icon: '&#9998;' },
  { id: 'audio',      label: 'Audio', icon: '&#9835;' },
  { id: 'lyrics',     label: 'Lyrics', icon: '&#9998;' },
  { id: 'licht',      label: 'Licht', icon: '&#9728;' },
  { id: 'live',       label: 'Live-Ready', icon: '&#9654;' },
];

const SONG_CHECKLIST = [
  // ── Stammdaten ──
  { id: 'has_name',     label: 'Name gesetzt',          cat: 'stammdaten', tab: 'editor',
    check: (s) => !!(s.name && s.name.trim()) },
  { id: 'has_artist',   label: 'Artist gesetzt',        cat: 'stammdaten', tab: 'editor',
    check: (s) => !!(s.artist && s.artist.trim()) },
  { id: 'has_bpm',      label: 'BPM gesetzt',           cat: 'stammdaten', tab: 'editor',
    check: (s) => !!(s.bpm && s.bpm > 0) },
  { id: 'has_key',      label: 'Key gesetzt',           cat: 'stammdaten', tab: 'editor',
    check: (s) => !!(s.key && s.key.trim()) },
  { id: 'has_year',     label: 'Jahr gesetzt',          cat: 'stammdaten', tab: 'editor',
    check: (s) => !!(s.year && s.year.trim()) },
  { id: 'has_gema',     label: 'GEMA Nr. gesetzt',      cat: 'stammdaten', tab: 'editor',
    check: (s) => !!(s.gema_nr && s.gema_nr.trim()) },

  // ── Audio ──
  { id: 'audio_ref',    label: 'Referenz-Audio geladen', cat: 'audio', tab: 'audio',
    check: (s) => !!s.audio_ref },
  { id: 'bar_markers',  label: 'Alle Takte identifiziert', cat: 'audio', tab: 'audio',
    check: () => false },  // Manuell abhaken — kein Auto-Check
  { id: 'audio_exported', label: 'Audio-Segmente exportiert', cat: 'audio', tab: 'audio',
    check: (s, barIds, theDb) => {
      return barIds.some(bId => theDb.bars[bId]?.audio);
    }},

  // ── Lyrics ──
  { id: 'lyrics_raw',    label: 'Rohtext eingefuegt',     cat: 'lyrics', tab: 'lyrics',
    check: (s) => !!(s.lyrics_raw && s.lyrics_raw.trim()) },
  { id: 'lyrics_bars',   label: 'Lyrics auf Takte verteilt', cat: 'lyrics', tab: 'lyrics',
    check: (s, barIds, theDb) => {
      if (barIds.length === 0) return false;
      let withLyrics = 0;
      for (const bId of barIds) {
        if (theDb.bars[bId]?.lyrics) withLyrics++;
      }
      return barIds.length > 0 && (withLyrics / barIds.length) >= 0.3;
    }},
  // ── Licht ──
  { id: 'templates_set', label: 'Light-Template gesetzt', cat: 'licht', tab: 'editor',
    check: (s) => !!(s.light_template && s.light_template !== '') },
  { id: 'accents_any',   label: 'Accents gesetzt (min. 1)', cat: 'licht', tab: 'accents',
    check: (s, barIds, theDb) => {
      return barIds.some(bId => Object.values(theDb.accents).some(a => a.bar_id === bId));
    }},

  // ── Live-Ready ──
  { id: 'in_setlist',    label: 'fertig f\u00fcr Playlist', cat: 'live', tab: 'setlist',
    check: (s, barIds, theDb) => {
      return theDb.setlist?.items?.some(i => i.type === 'song' && i.song_id === s._id);
    }},
];

/** Track previously completed steps per song to detect newly completed ones */
let _prevProgress = {};
let _suppressCelebration = false; // songId → Set of completed step ids

/**
 * Get or initialize the TMS data for a song.
 * Stored in db.songs[songId].tms = { manual_done: [], user_tasks: [] }
 * manual_done: array of default step IDs manually marked as done
 * user_tasks: array of { id, cat, label, done }
 */
function getSongTms(songId) {
  if (!songId || !db?.songs[songId]) return { manual_done: [], user_tasks: [] };
  const song = db.songs[songId];
  if (!song.tms) song.tms = { manual_done: [], manual_undone: [], user_tasks: [] };
  if (!song.tms.manual_done) song.tms.manual_done = [];
  if (!song.tms.manual_undone) song.tms.manual_undone = [];
  if (!song.tms.user_tasks) song.tms.user_tasks = [];
  return song.tms;
}

function getSongProgress(songId) {
  if (!songId || !db?.songs[songId]) return { steps: [], pct: 0, next: null, categories: [], hasOpenUserTasks: false };
  const song = { ...db.songs[songId], _id: songId };
  ensureCollections();

  // Collect bar IDs for this song
  const barIds = Object.entries(db.bars)
    .filter(([, b]) => b.song_id === songId)
    .map(([bId]) => bId);

  const tms = getSongTms(songId);

  const completed = new Set();
  const steps = SONG_CHECKLIST.map(s => {
    const autoCheck = s.check(song, barIds, db);
    const manualDone = tms.manual_done.includes(s.id);
    const manualUndone = tms.manual_undone.includes(s.id);
    const done = (autoCheck || manualDone) && !manualUndone;
    if (done) completed.add(s.id);
    return { ...s, done, autoCheck, manualDone, manualUndone, isUser: false };
  });

  // Add user-created tasks
  for (const ut of tms.user_tasks) {
    const step = { id: ut.id, label: ut.label, cat: ut.cat, tab: '', done: !!ut.done, autoCheck: false, manualDone: !!ut.done, isUser: true };
    steps.push(step);
    if (step.done) completed.add(step.id);
  }

  // Group by category
  const categories = PROGRESS_CATEGORIES.map(cat => {
    const catSteps = steps.filter(s => s.cat === cat.id);
    const catDone = catSteps.filter(s => s.done).length;
    return { ...cat, steps: catSteps, done: catDone, total: catSteps.length, allDone: catDone === catSteps.length };
  });

  // Weighted progress: all Stammdaten tasks together count as 1 task
  const stammdatenSteps = steps.filter(s => s.cat === 'stammdaten');
  const otherSteps = steps.filter(s => s.cat !== 'stammdaten');
  const stammdatenDone = stammdatenSteps.filter(s => s.done).length;
  const stammdatenWeight = stammdatenSteps.length > 0
    ? stammdatenDone / stammdatenSteps.length   // 0..1 (counts as 1 task)
    : 0;
  const otherDone = otherSteps.filter(s => s.done).length;
  const totalWeighted = 1 + otherSteps.length;  // Stammdaten = 1 + rest
  const doneWeighted = stammdatenWeight + otherDone;
  const pct = Math.round((doneWeighted / totalWeighted) * 100);
  const next = steps.find(s => !s.done) || null;

  // Check if any user-created tasks are still open
  const hasOpenUserTasks = tms.user_tasks.some(ut => !ut.done);

  return { steps, pct, next, completed, categories, hasOpenUserTasks };
}

/** Check for newly completed steps and fire confetti toast */
function checkProgressAndCelebrate(songId) {
  if (!songId) return;
  const { completed, pct } = getSongProgress(songId);
  const prev = _prevProgress[songId];
  if (!prev) { _prevProgress[songId] = completed; return; }

  if (!_suppressCelebration) {
    for (const stepId of completed) {
      if (!prev.has(stepId)) {
        const step = SONG_CHECKLIST.find(s => s.id === stepId);
        if (step) {
          fireworksCelebration(`${step.label} erledigt!`, pct);
        }
      }
    }
  }
  _suppressCelebration = false;
  _prevProgress[songId] = completed;
}

/* ── TMS Modal ──────────────────────────────────────── */

let _tmsCollapsed = new Set();

function openTmsModal(songId) {
  if (!songId || !db?.songs[songId]) return;
  closeTmsModal();
  // Reset collapsed state: auto-collapse completed categories
  _tmsCollapsed = new Set();
  const prog = getSongProgress(songId);
  for (const cat of prog.categories) {
    if (cat.allDone) _tmsCollapsed.add(cat.id);
  }
  const overlay = document.createElement('div');
  overlay.className = 'tms-modal-overlay';
  overlay.id = 'tms-modal-overlay';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeTmsModal(); });
  document.body.appendChild(overlay);

  const modal = document.createElement('div');
  modal.className = 'tms-modal';
  modal.id = 'tms-modal';
  document.body.appendChild(modal);

  renderTmsModalContent(songId);
  showTmsModalTip();

  // Event delegation for modal
  modal.addEventListener('click', (e) => {
    const el = e.target;

    // Close button
    if (el.closest('.tms-close-btn')) { closeTmsModal(); return; }

    // Toggle category collapse
    const catToggle = el.closest('[data-tms-cat-toggle]');
    if (catToggle) {
      const catId = catToggle.dataset.tmsCatToggle;
      if (_tmsCollapsed.has(catId)) _tmsCollapsed.delete(catId);
      else _tmsCollapsed.add(catId);
      renderTmsModalContent(songId);
      return;
    }

    // Toggle manual completion of default task (no celebration)
    const manualToggle = el.closest('[data-tms-toggle]');
    if (manualToggle) {
      const stepId = manualToggle.dataset.tmsToggle;
      const tms = getSongTms(songId);
      const prog = getSongProgress(songId);
      const step = prog.steps.find(s => s.id === stepId);
      if (step && step.done) {
        // Currently done → mark as undone
        tms.manual_done = tms.manual_done.filter(id => id !== stepId);
        if (step.autoCheck && !tms.manual_undone.includes(stepId)) {
          tms.manual_undone.push(stepId);
        }
      } else {
        // Currently undone → mark as done
        tms.manual_undone = tms.manual_undone.filter(id => id !== stepId);
        if (!tms.manual_done.includes(stepId)) {
          tms.manual_done.push(stepId);
        }
      }
      _suppressCelebration = true;
      markDirty();
      renderTmsModalContent(songId);
      renderSongList(els.searchBox.value);
      return;
    }

    // Toggle user task (no celebration)
    const userToggle = el.closest('[data-tms-user-toggle]');
    if (userToggle) {
      const taskId = userToggle.dataset.tmsUserToggle;
      const tms = getSongTms(songId);
      const task = tms.user_tasks.find(t => t.id === taskId);
      if (task) {
        task.done = !task.done;
        _suppressCelebration = true;
        markDirty();
      }
      renderTmsModalContent(songId);
      renderSongList(els.searchBox.value);
      return;
    }

    // Delete user task
    const delBtn = el.closest('[data-tms-user-delete]');
    if (delBtn) {
      const taskId = delBtn.dataset.tmsUserDelete;
      const tms = getSongTms(songId);
      tms.user_tasks = tms.user_tasks.filter(t => t.id !== taskId);
      markDirty();
      renderTmsModalContent(songId);
      renderSongList(els.searchBox.value);
      return;
    }

    // Add user task button
    const addBtn = el.closest('[data-tms-add-task]');
    if (addBtn) {
      const catId = addBtn.dataset.tmsAddTask;
      const input = modal.querySelector(`input[data-tms-new-task="${catId}"]`);
      if (input && input.value.trim()) {
        const tms = getSongTms(songId);
        tms.user_tasks.push({
          id: 'ut_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6),
          cat: catId,
          label: input.value.trim(),
          done: false
        });
        markDirty();
        renderTmsModalContent(songId);
        renderSongList(els.searchBox.value);
      }
      return;
    }

    // Navigate to tab
    const gotoBtn = el.closest('[data-tms-goto]');
    if (gotoBtn) {
      const tab = gotoBtn.dataset.tmsGoto;
      closeTmsModal();
      switchTab(tab);
      return;
    }
  });

  // Enter key in new-task inputs
  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const input = e.target.closest('input[data-tms-new-task]');
      if (input) {
        const catId = input.dataset.tmsNewTask;
        const addBtn = modal.querySelector(`[data-tms-add-task="${catId}"]`);
        if (addBtn) addBtn.click();
      }
    }
  });
}

function closeTmsModal() {
  document.getElementById('tms-modal')?.remove();
  document.getElementById('tms-modal-overlay')?.remove();
  document.querySelector('.tip-bubble')?.remove();
}

function showTmsModalTip() {
  const modal = document.getElementById('tms-modal');
  if (!modal) return;

  // Tip 1: Custom tasks (on add-row)
  const tipCustom = 'tms-custom-tasks';
  const seen = getTipsSeen();
  if (!seen.includes(tipCustom)) {
    setTimeout(() => {
      const m = document.getElementById('tms-modal');
      if (!m) return;
      const addRow = m.querySelector('.tms-category:not(.collapsed) .tms-add-row')
                  || m.querySelector('.tms-add-row');
      if (!addRow) return;
      document.querySelector('.tip-bubble')?.remove();
      const bubble = document.createElement('div');
      bubble.className = 'tip-bubble tip-arrow-down';
      bubble.dataset.tipId = tipCustom;
      bubble.innerHTML = `${esc('Hier kannst du eigene Aufgaben anlegen, diese erscheinen dann als kleiner Punkt in der Songliste')}<button class="tip-close" aria-label="Schliessen">&times;</button>`;
      bubble.style.maxWidth = '260px';
      addRow.style.position = 'relative';
      addRow.appendChild(bubble);
      bubble.style.position = 'absolute';
      bubble.style.bottom = 'calc(100% + 10px)';
      bubble.style.left = '0';
      bubble.style.zIndex = '1';
      bubble.querySelector('.tip-close').addEventListener('click', (e) => { e.stopPropagation(); dismissTip(); });
      bubble.addEventListener('click', dismissTip);
    }, 500);
    return; // show only one tip at a time
  }

  // Tip 2: Goto buttons (on first goto-btn)
  const tipGoto = 'tms-goto-buttons';
  if (!seen.includes(tipGoto)) {
    setTimeout(() => {
      const m = document.getElementById('tms-modal');
      if (!m) return;
      const gotoBtn = m.querySelector('.tms-goto-btn');
      if (!gotoBtn) return;
      document.querySelector('.tip-bubble')?.remove();
      const step = gotoBtn.closest('.tms-step');
      if (!step) return;
      const bubble = document.createElement('div');
      bubble.className = 'tip-bubble tip-arrow-up';
      bubble.dataset.tipId = tipGoto;
      bubble.innerHTML = `${esc('Springe direkt an die Stelle, wo du diese Aufgabe erledigen kannst')}<button class="tip-close" aria-label="Schliessen">&times;</button>`;
      bubble.style.maxWidth = '260px';
      step.style.position = 'relative';
      step.appendChild(bubble);
      bubble.style.position = 'absolute';
      bubble.style.top = 'calc(100% + 10px)';
      bubble.style.right = '0';
      bubble.style.zIndex = '1';
      bubble.querySelector('.tip-close').addEventListener('click', (e) => { e.stopPropagation(); dismissTip(); });
      bubble.addEventListener('click', dismissTip);
    }, 500);
  }
}

function renderTmsModalContent(songId) {
  const modal = document.getElementById('tms-modal');
  if (!modal) return;

  const prog = getSongProgress(songId);
  const song = db.songs[songId];
  const pctColor = prog.pct === 100 ? 'var(--green)' : prog.pct >= 50 ? 'var(--amber)' : 'var(--red)';

  modal.innerHTML = `
    <div class="tms-header">
      <div class="tms-ring-wrap">
        <svg viewBox="0 0 48 48" width="44" height="44">
          <circle cx="24" cy="24" r="20" fill="none" stroke="var(--border2)" stroke-width="3"/>
          <circle cx="24" cy="24" r="20" fill="none" stroke="${pctColor}" stroke-width="3"
            stroke-dasharray="${Math.PI * 40}" stroke-dashoffset="${Math.PI * 40 * (1 - prog.pct / 100)}"
            transform="rotate(-90 24 24)" stroke-linecap="round"/>
        </svg>
        <span class="tms-ring-pct mono">${prog.pct}%</span>
      </div>
      <div class="tms-header-info">
        <div class="tms-title">${esc(song.name)}</div>
        ${prog.next
          ? `<div class="tms-next text-t2">Naechster Schritt: <strong>${esc(prog.next.label)}</strong></div>`
          : `<div class="tms-next text-green">Alle Schritte erledigt!</div>`}
      </div>
      <button class="btn btn-sm tms-close-btn" title="Schliessen">&times;</button>
    </div>
    <div class="tms-body">
      ${prog.categories.map(cat => `
        <div class="tms-category${_tmsCollapsed.has(cat.id) ? ' collapsed' : ''}" data-tms-cat="${cat.id}">
          <div class="tms-cat-header" data-tms-cat-toggle="${cat.id}">
            <span class="tms-cat-chevron">&#9660;</span>
            <span class="tms-cat-icon">${cat.icon}</span>
            <span class="tms-cat-title">${esc(cat.label)}</span>
            <span class="tms-cat-count mono ${cat.allDone ? 'text-green' : 'text-t3'}">${cat.done}/${cat.total}</span>
            ${cat.allDone ? '<span class="tms-cat-check text-green">&#10003;</span>' : ''}
          </div>
          <div class="tms-cat-body">
            ${cat.steps.map(s => `
              <div class="tms-step ${s.done ? 'done' : ''}">
                <button class="tms-check-btn" ${s.isUser ? `data-tms-user-toggle="${s.id}"` : `data-tms-toggle="${s.id}"`}
                  title="${s.done ? (s.autoCheck && !s.manualUndone && !s.isUser ? 'Automatisch erkannt — Tap zum Zuruecksetzen' : 'Als offen markieren') : 'Als erledigt markieren'}">
                  ${s.done ? (s.autoCheck && !s.manualUndone && !s.isUser ? '&#10003;' : '&#10004;') : '&#9675;'}
                </button>
                <span class="tms-step-label">${esc(s.label)}</span>
                ${s.isUser ? `<button class="tms-delete-btn" data-tms-user-delete="${s.id}" title="Task loeschen">&times;</button>` : ''}
                ${!s.done && s.tab ? `<button class="btn btn-xs tms-goto-btn" data-tms-goto="${s.tab}">&#8594; ${s.tab.toUpperCase()}</button>` : ''}
              </div>
            `).join('')}
            <div class="tms-add-row">
              <input type="text" class="tms-add-input" data-tms-new-task="${cat.id}" placeholder="Neuer Task...">
              <button class="btn btn-xs tms-add-btn" data-tms-add-task="${cat.id}">+</button>
            </div>
          </div>
        </div>
      `).join('')}
    </div>`;
}

/* ── Fireworks Celebration (Fullscreen) ──────────── */

function fireworksCelebration(msg, pct) {
  // Create fullscreen overlay
  const overlay = document.createElement('div');
  overlay.className = 'fireworks-overlay';
  overlay.innerHTML = `
    <canvas class="fireworks-canvas"></canvas>
    <div class="fireworks-msg">
      <span class="fireworks-icon">&#127881;</span>
      <span class="fireworks-text">${esc(msg)}</span>
      ${pct !== undefined ? `<span class="fireworks-pct">${pct}%</span>` : ''}
    </div>`;
  document.body.appendChild(overlay);

  const canvas = overlay.querySelector('.fireworks-canvas');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const W = window.innerWidth, H = window.innerHeight;

  // Play fireworks sound via Web Audio API
  playFireworksSound();

  // Fireworks + confetti particles
  const colors = ['#00dc82', '#f0a030', '#38bdf8', '#ff3b5c', '#eef0f6', '#a855f7', '#ff6b9d', '#c084fc'];
  const particles = [];
  const rockets = [];

  // Launch multiple rockets in sequence
  function launchRocket() {
    rockets.push({
      x: W * (0.2 + Math.random() * 0.6),
      y: H,
      targetY: H * (0.15 + Math.random() * 0.3),
      vy: -12 - Math.random() * 4,
      exploded: false,
      trail: [],
    });
  }

  // Initial rockets
  launchRocket();
  setTimeout(launchRocket, 200);
  setTimeout(launchRocket, 500);
  setTimeout(launchRocket, 900);
  setTimeout(launchRocket, 1300);

  function explode(x, y) {
    const count = 80 + Math.floor(Math.random() * 40);
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.3;
      const speed = 2 + Math.random() * 6;
      particles.push({
        x, y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: Math.random() * 4 + 1.5,
        color: colors[Math.floor(Math.random() * colors.length)],
        life: 1,
        decay: 0.008 + Math.random() * 0.012,
        type: 'spark',
      });
    }
    // Confetti pieces
    for (let i = 0; i < 30; i++) {
      particles.push({
        x, y,
        vx: (Math.random() - 0.5) * 10,
        vy: (Math.random() - 0.5) * 10 - 2,
        size: Math.random() * 8 + 4,
        color: colors[Math.floor(Math.random() * colors.length)],
        life: 1,
        decay: 0.005 + Math.random() * 0.008,
        rot: Math.random() * Math.PI * 2,
        rotV: (Math.random() - 0.5) * 0.2,
        type: 'confetti',
      });
    }
  }

  let frame = 0;
  const totalFrames = 240; // ~4 seconds at 60fps

  function tick() {
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = 'rgba(8, 9, 13, 0.15)';
    ctx.fillRect(0, 0, W, H);

    ctx.globalCompositeOperation = 'lighter';

    // Update rockets
    for (const r of rockets) {
      if (r.exploded) continue;
      r.y += r.vy;
      r.trail.push({ x: r.x, y: r.y, life: 1 });
      if (r.trail.length > 15) r.trail.shift();

      // Draw trail
      for (const t of r.trail) {
        ctx.globalAlpha = t.life * 0.6;
        ctx.fillStyle = '#f0a030';
        ctx.beginPath();
        ctx.arc(t.x, t.y, 2, 0, Math.PI * 2);
        ctx.fill();
        t.life -= 0.08;
      }

      // Draw rocket head
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#eef0f6';
      ctx.beginPath();
      ctx.arc(r.x, r.y, 3, 0, Math.PI * 2);
      ctx.fill();

      if (r.y <= r.targetY) {
        r.exploded = true;
        explode(r.x, r.y);
      }
    }

    // Update particles
    for (const p of particles) {
      if (p.life <= 0) continue;
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.06; // gravity
      p.vx *= 0.99; // drag
      p.life -= p.decay;
      if (p.life <= 0) continue;

      ctx.globalAlpha = p.life;

      if (p.type === 'spark') {
        // Glowing spark
        const r1 = Math.max(0.1, p.size * p.life);
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r1, 0, Math.PI * 2);
        ctx.fill();
        // Glow
        ctx.globalAlpha = p.life * 0.3;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r1 * 3, 0, Math.PI * 2);
        ctx.fill();
      } else {
        // Confetti rectangle
        ctx.save();
        ctx.translate(p.x, p.y);
        p.rot += p.rotV;
        ctx.rotate(p.rot);
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size * 0.5);
        ctx.restore();
      }
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';

    frame++;
    if (frame < totalFrames) {
      requestAnimationFrame(tick);
    }
  }

  requestAnimationFrame(tick);

  // Fade out overlay and remove
  setTimeout(() => overlay.classList.add('fireworks-fade'), 3200);
  setTimeout(() => overlay.remove(), 4000);

  // Click to dismiss early
  overlay.addEventListener('click', () => {
    overlay.classList.add('fireworks-fade');
    setTimeout(() => overlay.remove(), 400);
  });
}

/** Synthesize a fireworks sound using Web Audio API */
function playFireworksSound() {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const master = ac.createGain();
    master.gain.value = 0.3;
    master.connect(ac.destination);

    function boom(time, freq, dur) {
      // Noise burst for explosion
      const bufLen = ac.sampleRate * dur;
      const buf = ac.createBuffer(1, bufLen, ac.sampleRate);
      const data = buf.getChannelData(0);
      for (let i = 0; i < bufLen; i++) {
        data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / bufLen, 3);
      }
      const src = ac.createBufferSource();
      src.buffer = buf;

      const filt = ac.createBiquadFilter();
      filt.type = 'lowpass';
      filt.frequency.setValueAtTime(freq, time);
      filt.frequency.exponentialRampToValueAtTime(100, time + dur);

      const gain = ac.createGain();
      gain.gain.setValueAtTime(0.6, time);
      gain.gain.exponentialRampToValueAtTime(0.001, time + dur);

      src.connect(filt);
      filt.connect(gain);
      gain.connect(master);
      src.start(time);
      src.stop(time + dur);
    }

    function whistle(time, dur) {
      const osc = ac.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(800, time);
      osc.frequency.linearRampToValueAtTime(2000, time + dur);

      const gain = ac.createGain();
      gain.gain.setValueAtTime(0.08, time);
      gain.gain.exponentialRampToValueAtTime(0.001, time + dur);

      osc.connect(gain);
      gain.connect(master);
      osc.start(time);
      osc.stop(time + dur);
    }

    function crackle(time, dur) {
      const bufLen = ac.sampleRate * dur;
      const buf = ac.createBuffer(1, bufLen, ac.sampleRate);
      const data = buf.getChannelData(0);
      for (let i = 0; i < bufLen; i++) {
        data[i] = Math.random() > 0.97 ? (Math.random() * 2 - 1) : 0;
      }
      const src = ac.createBufferSource();
      src.buffer = buf;
      const gain = ac.createGain();
      gain.gain.setValueAtTime(0.4, time);
      gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
      src.connect(gain);
      gain.connect(master);
      src.start(time);
      src.stop(time + dur);
    }

    const now = ac.currentTime;
    // Rocket 1
    whistle(now, 0.3);
    boom(now + 0.3, 400, 0.8);
    crackle(now + 0.4, 1.2);
    // Rocket 2
    whistle(now + 0.2, 0.25);
    boom(now + 0.5, 300, 0.7);
    crackle(now + 0.6, 1.0);
    // Rocket 3
    boom(now + 0.9, 500, 0.6);
    crackle(now + 1.0, 1.5);
    // Rocket 4
    whistle(now + 1.1, 0.2);
    boom(now + 1.3, 350, 0.9);
    crackle(now + 1.4, 1.2);

    // Cleanup
    setTimeout(() => ac.close(), 4000);
  } catch (e) {
    // Audio not available — silent fallback
  }
}

/* ── Song List ─────────────────────────────────────── */

function getSortedSongs() {
  if (!db || !db.songs) return [];
  return Object.entries(db.songs)
    .map(([id, song]) => ({ id, ...song }))
    .sort((a, b) => a.name.localeCompare(b.name, 'de'));
}

function renderSongList(filter = '') {
  const songs = getSortedSongs();
  const q = filter.toLowerCase().trim();
  const filtered = q
    ? songs.filter(s => s.name.toLowerCase().includes(q) || s.artist.toLowerCase().includes(q))
    : songs;

  els.songCount.textContent = `${filtered.length} / ${songs.length} Songs`;
  const allActive = selectedSongId === null && !q;
  els.songList.innerHTML =
    (!q ? `<div class="song-item song-item-all${allActive ? ' active' : ''}" data-id="__all__">
      <div style="flex:1;min-width:0">
        <div class="song-name">Alle Songs</div>
        <div class="song-artist">${songs.length} Songs</div>
      </div>
    </div>` : '') +
    filtered.map(s => {
      const prog = getSongProgress(s.id);
      return `
    <div class="song-item${s.id === selectedSongId ? ' active' : ''}" data-id="${s.id}">
      <div style="flex:1;min-width:0">
        <div class="song-name">${esc(s.name)}</div>
        <div class="song-artist">${esc(s.artist)}</div>
      </div>
      <div class="song-progress-mini" data-tms-open="${s.id}" title="${prog.pct}% — ${prog.next ? prog.next.label : 'Komplett'}">
        <svg viewBox="0 0 24 24" width="20" height="20">
          <circle cx="12" cy="12" r="10" fill="none" stroke="var(--border2)" stroke-width="2"/>
          <circle cx="12" cy="12" r="10" fill="none" stroke="${prog.pct === 100 ? 'var(--green)' : 'var(--amber)'}" stroke-width="2"
            stroke-dasharray="${Math.PI * 20}" stroke-dashoffset="${Math.PI * 20 * (1 - prog.pct / 100)}"
            transform="rotate(-90 12 12)" stroke-linecap="round"/>
        </svg>
        ${prog.hasOpenUserTasks ? '<span class="song-tms-dot"></span>' : ''}
      </div>
    </div>`;
    }).join('');
}

/* ── Tab Routing ───────────────────────────────────── */

function switchTab(tab) {
  // Stop playhead animation when leaving audio tab
  if (activeTab === 'audio' && tab !== 'audio') {
    cancelAnimationFrame(animFrameId);
    // Persist markers and sync db.bars when leaving Audio Split tab
    if (selectedSongId && markers.length > 0) {
      saveMarkersToSong();
      markDirty();
    }
  }
  // Stop lyrics part playback when leaving lyrics tab
  if (activeTab === 'lyrics' && tab !== 'lyrics') {
  }
  // Pre-warm AudioContext for tabs with playback
  if (tab === 'lyrics' || tab === 'audio' || tab === 'takte' || tab === 'accents') {
    audio.warmup();
  }
  // Ensure bar data is consistent when entering data-dependent tabs
  if ((tab === 'takte' || tab === 'lyrics' || tab === 'accents') && selectedSongId) {
    reconcileBars(selectedSongId);
  }
  activeTab = tab;
  els.tabEditor?.classList.toggle('active', tab === 'editor');
  els.tabTakte?.classList.toggle('active', tab === 'takte');
  els.tabAudio?.classList.toggle('active', tab === 'audio');
  els.tabLyrics?.classList.toggle('active', tab === 'lyrics');
  els.tabAccents?.classList.toggle('active', tab === 'accents');
  els.tabSetlist?.classList.toggle('active', tab === 'setlist');
  renderContent();
  showTabTip(tab);
}

function renderContent() {
  if (!db) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9881;</div><p>DB wird geladen...</p></div>`;
    return;
  }
  if (activeTab === 'editor') renderEditorTab();
  else if (activeTab === 'takte') renderTakteTab();
  else if (activeTab === 'audio') renderAudioTab();
  else if (activeTab === 'lyrics') renderLyricsTab();
  else if (activeTab === 'accents') renderAccentsTab();
  else if (activeTab === 'setlist') renderSetlistTab();
  updateDebugPanel();
}

/* ══════════════════════════════════════════════════════
   EDITOR TAB — Rendering
   ══════════════════════════════════════════════════════ */

function renderEditorTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Song aus der Liste links ausw&auml;hlen.</p></div>`;
    return;
  }

  els.content.innerHTML = `
    <div class="editor-panel">
      <div class="editor-scroll" id="editor-scroll">
        <div id="song-fields-area"></div>
        <div id="bar-area"></div>
      </div>
      <div id="summary-area"></div>
    </div>`;

  renderSongFields();
  renderBarSection();
  renderSummary();

  // Initialize progress tracking for this song
  if (selectedSongId && !_prevProgress[selectedSongId]) {
    _prevProgress[selectedSongId] = getSongProgress(selectedSongId).completed;
  }
}

/* ── Song Progress Panel (moved to TMS Modal) ────── */

/* ── Song Fields ───────────────────────────────────── */

function renderSongFields() {
  const song = db.songs[selectedSongId];
  const area = document.getElementById('song-fields-area');
  if (!area) return;

  area.innerHTML = `
    <div class="song-fields">
      <div class="sf-wide">
        <label>Name</label>
        <input type="text" value="${esc(song.name)}" data-song-field="name">
      </div>
      <div class="sf-wide">
        <label>Artist</label>
        <input type="text" value="${esc(song.artist)}" data-song-field="artist">
      </div>
      <div>
        <label>BPM</label>
        <input type="number" value="${song.bpm || ''}" data-song-field="bpm" class="mono" min="0" inputmode="numeric">
      </div>
      <div>
        <label>Key</label>
        <input type="text" value="${esc(song.key || '')}" data-song-field="key">
      </div>
      <div>
        <label>Jahr</label>
        <input type="text" value="${esc(song.year || '')}" data-song-field="year" inputmode="numeric">
      </div>
      <div>
        <label>Dauer</label>
        <input type="text" value="${esc(song.duration || '')}" data-song-field="duration" readonly class="mono text-t3" id="song-duration-field">
      </div>
      <div>
        <label>GEMA Nr.</label>
        <div class="field-with-action">
          <input type="text" value="${esc(song.gema_nr || '')}" data-song-field="gema_nr" class="mono">
          <a href="https://www.gema.de/repertoiresuche" target="_blank" rel="noopener" class="btn btn-sm btn-field-action" title="GEMA Werksuche &ouml;ffnen">&#128269;</a>
        </div>
      </div>
      <div>
        <label>Pick</label>
        <input type="text" value="${esc(song.pick || '')}" data-song-field="pick">
      </div>
      <div class="sf-full">
        <label>Notes</label>
        <textarea data-song-field="notes" rows="2" placeholder="Notizen...">${esc(song.notes || '')}</textarea>
      </div>
      <div class="sf-full sf-delete">
        <button class="btn btn-sm btn-danger" data-action="delete-song">SONG LÖSCHEN</button>
      </div>
    </div>`;
}

/* ── Parts Table ───────────────────────────────────── */

/**
 * Get audio bars for a song (bars that have audio files).
 */
function getAudioBarsForSong(songId) {
  ensureCollections();
  return Object.entries(db.bars)
    .filter(([, b]) => b.song_id === songId && b.audio)
    .map(([id, b]) => ({ id, ...b }))
    .sort((a, b) => a.bar_num - b.bar_num);
}



/* ── Bar Section ───────────────────────────────────── */

function renderBarSection() {
  const area = document.getElementById('bar-area');
  if (!area) return;

  const song = db.songs[selectedSongId];
  if (!song) { area.innerHTML = ''; return; }

  const barCount = song.total_bars || 0;
  if (barCount === 0) {
    area.innerHTML = `<div class="bar-section"><p class="text-t3">Keine Bars \u2014 setze die Takte-Anzahl oben.</p></div>`;
    return;
  }

  ensureCollections();

  const blocks = Array.from({ length: barCount }, (_, i) => {
    const absN = i + 1;
    const found = findBar(selectedSongId, absN);
    const hasAcc = found ? getAccentsForBar(found[0]).length > 0 : false;
    const hasLyr = found && found[1].lyrics;
    return `<div class="bar-block${absN === selectedBarNum ? ' active' : ''}${hasAcc ? ' has-accents' : ''}${hasLyr ? ' has-lyrics' : ''}" data-bar-num="${absN}">${absN}</div>`;
  }).join('');

  let editor = '';
  if (selectedBarNum && selectedBarNum >= 1 && selectedBarNum <= barCount) {
    editor = buildBarEditor();
  }

  area.innerHTML = `
    <div class="bar-section">
      <h3>Bars <span class="text-t3">(${barCount} Takte)</span></h3>
      <div class="bar-blocks">${blocks}</div>
      ${editor}
    </div>`;
}

function buildBarEditor() {
  const [barId, barData] = getOrCreateBar(selectedSongId, selectedBarNum);
  const accents = getAccentsForBar(barId);

  const cells = Array.from({ length: 16 }, (_, i) => {
    const pos = i + 1;
    const accent = accents.find(a => a.pos_16th === pos);
    const type = accent ? accent.type : '';
    const isBeat = (i % 4 === 0);
    const tip = `${pos}: ${BEAT_LABELS[i]}${type ? ' \u2014 ' + ACCENT_INFO[type] : ''}`;
    return `<div class="accent-cell${type ? ' ' + type : ''}${isBeat ? ' beat' : ''}" data-pos16="${pos}" title="${tip}">
        <span class="accent-num">${BEAT_LABELS[i]}</span>
        ${type ? `<span class="accent-tag">${type}</span>` : ''}
      </div>`;
  }).join('');

  return `
    <div class="bar-editor">
      <div class="bar-editor-header">
        <span class="mono text-t1">Bar ${selectedBarNum}</span>
        <span class="accent-legend">
          <span class="legend-item bl">bl</span>
          <span class="legend-item bo">bo</span>
          <span class="legend-item hl">hl</span>
          <span class="legend-item st">st</span>
          <span class="legend-item fg">fg</span>
        </span>
      </div>
      <div class="form-group" style="margin-bottom:12px">
        <label>Lyrics</label>
        <input type="text" value="${esc(barData.lyrics || '')}" data-bar-lyrics placeholder="Lyrics f\u00fcr Bar ${selectedBarNum}...">
      </div>
      <div class="form-group">
        <label>Accents (16tel-Raster)</label>
        <div class="accent-grid">${cells}</div>
      </div>
    </div>`;
}

/* ── Summary Bar ───────────────────────────────────── */

function renderSummary() {
  const song = db.songs[selectedSongId];
  if (!song) return;
  const area = document.getElementById('summary-area');
  if (!area) return;

  const totalBars = song.total_bars || 0;
  const totalSec = calcBarsDuration(totalBars, song.bpm || 0);

  area.innerHTML = `
    <div class="summary-bar">
      <span class="summary-item"><span class="summary-label">Takte</span><span class="mono">${totalBars}</span></span>
      <span class="summary-item"><span class="summary-label">Dauer</span><span class="mono">${fmtDur(totalSec)}</span></span>
      <span class="summary-item"><span class="summary-label">BPM</span><span class="mono">${song.bpm || '\u2014'}</span></span>
    </div>`;
}

/* ══════════════════════════════════════════════════════
   EDITOR TAB — Event Handlers
   ══════════════════════════════════════════════════════ */

function handleEditorChange(e) {
  const el = e.target;

  /* ── Song field ── */
  if (el.dataset.songField) {
    const field = el.dataset.songField;
    const song = db.songs[selectedSongId];
    if (!song) return;

    if (field === 'total_bars') {
      song.total_bars = parseInt(el.value, 10) || 0;
      recalcSongDuration();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
      renderBarSection();
      renderSummary();
      markDirty();
      return;
    }
    if (field === 'bpm') {
      song.bpm = parseInt(el.value, 10) || 0;
      recalcSongDuration();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
          renderSummary();
      renderSongList(els.searchBox.value);
    } else if (field === 'notes') {
      song.notes = el.value;
    } else if (field === 'duration') {
      return; // readonly
    } else {
      song[field] = el.value;
      if (field === 'name' || field === 'artist') renderSongList(els.searchBox.value);
    }
    markDirty();
    return;
  }

  /* ── Bar lyrics ── */
  if (el.hasAttribute('data-bar-lyrics')) {
    if (!selectedBarNum) return;
    const [, barData] = getOrCreateBar(selectedSongId, selectedBarNum);
    barData.lyrics = el.value;
    markDirty();
    return;
  }
}

function handleEditorClick(e) {
  const el = e.target;


  /* ── Delete song ── */
  if (el.closest('[data-action="delete-song"]')) {
    handleDeleteSong();
    return;
  }


  /* ── Accent cell ── */
  const accentCell = el.closest('[data-pos16]');
  if (accentCell) {
    handleAccentToggle(parseInt(accentCell.dataset.pos16, 10));
    return;
  }

  /* ── Bar block ── */
  const barBlock = el.closest('[data-bar-num]');
  if (barBlock && !barBlock.closest('.bar-editor')) {
    handleBarSelect(parseInt(barBlock.dataset.barNum, 10));
    return;
  }


}


function handleBarSelect(barNum) {
  selectedBarNum = (selectedBarNum === barNum) ? null : barNum;
  renderBarSection();
}

async function handleDeleteSong() {
  if (!selectedSongId || !db.songs[selectedSongId]) return;
  const song = db.songs[selectedSongId];
  const barCount = Object.values(db.bars || {}).filter(b => b.song_id === selectedSongId).length;
  const inSetlist = (db.setlist?.items || []).some(i => i.type === 'song' && i.song_id === selectedSongId);

  let details = `<strong>${esc(song.name)}</strong> (${esc(song.artist)})<br>`;
  details += `${barCount} Takte`;
  if (inSetlist) details += ', in Setlist referenziert';
  details += ' — alles wird unwiderruflich gelöscht.';

  const ok = await showConfirm('Song löschen?', details, 'Löschen');
  if (!ok) return;

  integrity.deleteSong(db, selectedSongId);
  selectedSongId = null;
  
  selectedBarNum = null;
  markDirty();
  renderSongList(els.searchBox.value);
  renderEditorTab();
  toast(`Song "${song.name}" gelöscht`, 'success');
}


async function handleBarPlay(songId, barNum) {
  audio.warmup(); // iOS: resume AudioContext in gesture handler
  ensureCollections();
  const found = findBar(songId, barNum);
  const barId = found ? found[0] : null;
  const barData = found ? found[1] : {};

  // If already playing this bar → stop
  if (_barPlayId === barId && _partPlayActive) {
    _barPlayId = null;
    renderTakteTab();
    return;
  }

  _barPlayId = barId;
  _partPlayActive = true;

  try {
    const ac = _getAudioCtx();
    if (ac.state === 'suspended') await ac.resume();

    // Strategy 1: Use split audio file if available
    if (barData.audio) {
      const arrBuf = await fetchAudioUrl(barData.audio);
      if (arrBuf) {
        const decoded = await ac.decodeAudioData(arrBuf);
        const src = ac.createBufferSource();
        src.buffer = decoded;
        src.connect(ac.destination);
        src.onended = () => {
          if (_barPlayId === barId) { _barPlayId = null; _partPlayActive = false; renderTakteTab(); }
        };
        src.start(0);
        _partPlaySources = [src];
        _partPlayBuffers = [decoded];
        renderTakteTab();
        return;
      }
    }

    // Strategy 2: Play from reference audio buffer using bar time range
    const refBuffer = audio.getBuffer();
    if (refBuffer) {
      // Bar time range from markers (simplified)
      if (range) {
        const src = ac.createBufferSource();
        src.buffer = refBuffer;
        src.connect(ac.destination);
        const dur = range.end - range.start;
        src.onended = () => {
          if (_barPlayId === barId) { _barPlayId = null; _partPlayActive = false; renderTakteTab(); }
        };
        src.start(0, range.start, dur);
        _partPlaySources = [src];
        _partPlayBuffers = [refBuffer];
        renderTakteTab();
        return;
      }
    }

    throw new Error('Kein Audio verfügbar');
  } catch (err) {
    console.error('Bar playback error:', err);
    toast(`Wiedergabe-Fehler: ${err.message}`, 'error');
    _barPlayId = null;
  }
}

function handleAccentToggle(pos16) {
  if (!selectedBarNum) return;
  ensureCollections();
  const [barId, barData] = getOrCreateBar(selectedSongId, selectedBarNum);

  // Find existing accent
  const existingEntry = Object.entries(db.accents)
    .find(([, a]) => a.bar_id === barId && a.pos_16th === pos16);

  if (existingEntry) {
    const [accId, acc] = existingEntry;
    const idx = ACCENT_TYPES.indexOf(acc.type);
    if (idx < ACCENT_TYPES.length - 1) {
      acc.type = ACCENT_TYPES[idx + 1];
    } else {
      delete db.accents[accId];
    }
  } else {
    const newId = nextId('A', db.accents);
    db.accents[newId] = { bar_id: barId, pos_16th: pos16, type: ACCENT_TYPES[0], notes: '' };
  }

  barData.has_accents = Object.values(db.accents).some(a => a.bar_id === barId);
  markDirty();
  renderBarSection();
}

/* ══════════════════════════════════════════════════════
   AUDIO SPLIT TAB — Meilenstein 3
   ══════════════════════════════════════════════════════ */

let _barPlayId = null;        // currently playing bar ID
let _partPlayActive = false;  // whether bar playback is active
let _partPlaySources = [];    // active AudioBufferSourceNode(s)
let _refLoadingFor = null; // songId currently loading reference for
let _refLoadingPromise = null; // pending loadReferenceAudio promise

function renderAudioTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9836;</div><p>Song aus der Liste links ausw\u00e4hlen, um Audio zu splitten.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const hasBuf = !!audio.getBuffer();
  const isPlay = audio.isPlaying();

  // Auto-load reference audio if available and not yet loaded
  if (!hasBuf && song.audio_ref && _refLoadingFor !== selectedSongId) {
    _refLoadingFor = selectedSongId;
    _refLoadingPromise = loadReferenceAudio().finally(() => { _refLoadingFor = null; _refLoadingPromise = null; });
  }

  els.content.innerHTML = `
    <div class="audio-panel">
      <div class="audio-scroll" id="audio-scroll">
        ${buildSongHeader(song)}
        ${buildDropZone(song)}
        ${hasBuf ? buildWaveform() : ''}
        ${hasBuf ? buildTransport() : ''}
        ${hasBuf ? buildTapButtons(isPlay) : ''}
        ${hasBuf ? buildBpmBanner(song) : ''}
        ${hasBuf ? buildExportSection() : ''}
      </div>
      ${hasBuf ? buildAudioSummary() : ''}
    </div>`;

  if (hasBuf) {
    requestAnimationFrame(() => {
      drawWaveform();
      initWaveformDrag();
    });
  }
}

function buildSongHeader(song) {
  return `
    <div class="audio-song-header">
      <div>
        <div class="ash-name">${esc(song.name)}</div>
        <div class="ash-artist">${esc(song.artist)}</div>
      </div>
      <div class="ash-bpm">${song.bpm || '\u2014'} BPM</div>
    </div>`;
}

function buildDropZone(song) {
  if (audioMeta) {
    const durStr = fmtTime(audioMeta.duration);
    const sr = (audioMeta.sampleRate / 1000).toFixed(1);
    return `
      <div class="audio-dropzone has-file" id="audio-dropzone">
        <div class="dz-info">
          <span class="dz-filename">${esc(audioFileName)}</span>
          <span>${durStr}</span>
          <span>${sr} kHz</span>
          <span>${audioMeta.channels}ch</span>
        </div>
        <span class="dz-change">Klick zum Wechseln</span>
      </div>`;
  }
  if (_refLoadingFor === selectedSongId) {
    return `
      <div class="audio-dropzone loading" id="audio-dropzone">
        <div class="dz-text">Referenz-Audio wird geladen...</div>
      </div>`;
  }
  const hasRef = song && song.audio_ref;
  return `
    <div class="audio-dropzone" id="audio-dropzone">
      <div class="dz-icon">&#127925;</div>
      <div class="dz-text">${hasRef ? 'Referenz-Audio wird geladen... oder neue Datei ablegen' : 'Audio-Datei hier ablegen oder klicken'}</div>
      <div class="dz-formats">.wav .mp3 .m4a .ogg</div>
    </div>`;
}

function buildWaveform() {
  return `<div class="waveform-wrap" id="waveform-wrap"><div class="waveform-scroll" id="waveform-scroll"><canvas id="waveform-canvas"></canvas></div></div>`;
}

function buildTransport() {
  const isPlay = audio.isPlaying();
  const cur = audio.getCurrentTime();
  const dur = audioMeta ? audioMeta.duration : 0;
  const pct = dur > 0 ? (cur / dur * 100) : 0;
  const speedLabel = playbackSpeed === 1 ? '1\u00d7' : playbackSpeed.toFixed(2).replace(/0$/, '') + '\u00d7';
  const zoomLabel = waveformZoom === 1 ? '1\u00d7' : waveformZoom.toFixed(1) + '\u00d7';
  const songBpm = selectedSongId && db && db.songs[selectedSongId] ? db.songs[selectedSongId].bpm : 0;
  const clickAvailable = songBpm > 0;
  return `
    <div class="transport-bar" id="transport-bar">
      <button class="t-btn" id="t-skip" title="Zum Anfang">&#9198;</button>
      <button class="t-btn${isPlay ? ' playing' : ''}" id="t-play" title="${isPlay ? 'Pause' : 'Play'}">
        ${isPlay ? '&#9646;&#9646;' : '&#9654;'}
      </button>
      <span class="t-time" id="t-time">${fmtTime(cur)} / ${fmtTime(dur)}</span>
      <div class="t-progress-wrap" id="t-progress-wrap">
        <div class="t-progress" id="t-progress" style="width:${pct}%"></div>
      </div>
      <div class="t-speed" id="t-speed">
        <button class="t-speed-btn" id="t-speed-down" title="Langsamer">&minus;</button>
        <span class="t-speed-label" id="t-speed-label">${speedLabel}</span>
        <button class="t-speed-btn" id="t-speed-up" title="Schneller">+</button>
      </div>
      ${clickAvailable ? `<button class="t-click${clickEnabled ? ' active' : ''}" id="t-click" title="Click Track (${songBpm} BPM)">
        <span class="t-click-icon">&#9834;</span><span class="t-click-bpm">${songBpm}</span>
      </button>` : ''}
      <div class="t-zoom" id="t-zoom">
        <button class="t-zoom-btn" id="t-zoom-out" title="Zoom Out">&minus;</button>
        <span class="t-zoom-label" id="t-zoom-label">&#128269; ${zoomLabel}</span>
        <button class="t-zoom-btn" id="t-zoom-in" title="Zoom In">+</button>
      </div>
    </div>`;
}

function buildTapButtons(isPlay) {
  const nextAbsBar = markers.length + 1;
  const barLabel = `Bar ${nextAbsBar}`;

  return `
    <div class="tap-row" id="tap-row">
      <button class="tap-btn tap-bar" id="tap-bar" ${!isPlay ? 'disabled' : ''}>
        <span class="tap-label">BAR TAP <kbd>B</kbd></span>
        <span class="tap-info">${barLabel}</span>
      </button>
      <button class="tap-btn tap-undo" id="tap-undo" ${tapHistory.length === 0 ? 'disabled' : ''}>
        <span class="tap-label">UNDO <kbd>Z</kbd></span>
      </button>
      <button class="tap-btn tap-btn-snap" id="tap-snap-peaks" ${markers.length === 0 ? 'disabled' : ''} title="Alle Marker auf naechsten Audio-Peak verschieben">
        <span class="tap-label">SNAP</span>
        <span class="tap-info">&#8614; Peak</span>
      </button>
      <button class="tap-btn tap-btn-del" id="tap-delete-bars" ${markers.length === 0 ? 'disabled' : ''}>
        <span class="tap-label">DEL BARS</span>
        <span class="tap-info">${markers.length}</span>
      </button>
    </div>`;
}


function buildBpmBanner(song) {
  const est = estimateBpm();
  if (!est || !song.bpm) return '';
  const diff = Math.abs(est - song.bpm);
  if (diff <= 3) return '';
  return `
    <div class="bpm-banner" id="bpm-banner">
      <span class="bpm-banner-text">Gesch\u00e4tztes BPM: <strong>${est}</strong> (Song: ${song.bpm}) \u2014 Differenz: ${diff}</span>
      <button class="btn btn-sm" id="btn-update-bpm">BPM aktualisieren</button>
    </div>`;
}

function buildSplitResult() {
  return '';
}

function buildExportSection() {
  if (markers.length === 0) return '';

  if (exportInProgress) {
    return `
      <div class="export-section" id="export-section">
        <div class="export-header"><h3>Export</h3></div>
        <div class="export-progress">
          <div class="export-progress-bar"><div class="export-progress-fill" id="export-fill" style="width:0%"></div></div>
          <div class="export-progress-text" id="export-text">Exportiere...</div>
        </div>
      </div>`;
  }

  return `
    <div class="export-section" id="export-section">
      <div class="export-header">
        <h3>Export nach GitHub</h3>
        <button class="btn btn-primary" id="btn-export">EXPORT</button>
      </div>
      <div style="font-size:0.8rem;color:var(--t3)">
        ${markers.length} Bars als MP3-Segmente nach <span class="mono">audio/${sanitizePath(db.songs[selectedSongId]?.name || '')}/</span> hochladen.
      </div>
    </div>`;
}

function buildAudioSummary() {
  const totalBars = markers.length;
  const est = estimateBpm();
  const irregCount = getIrregularBars().size;
  const irregHtml = irregCount > 0
    ? `<span class="summary-item"><span class="summary-label">Unregelmäßig</span><span class="mono text-red">${irregCount}</span></span>`
    : '';
  return `
    <div class="summary-bar">
      <span class="summary-item"><span class="summary-label">Takte</span><span class="mono">${totalBars}</span></span>
      <span class="summary-item"><span class="summary-label">BPM (est.)</span><span class="mono">${est || '\u2014'}</span></span>
      ${irregHtml}
      <span class="summary-item"><span class="summary-label">Storage</span><span class="mono text-green">GitHub</span></span>
    </div>`;
}

/* ── Audio Helper Functions ────────────────────────── */

/**
 * Detect irregular bars: bars whose duration deviates > 5% from median.
 * Uses median instead of average to be robust against outliers (fewer false negatives).
 * Returns a Set of marker references whose *preceding* interval is irregular.
 */
function getIrregularBars() {
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  const irregular = new Set();
  if (sorted.length < 3) return irregular; // need at least 2 intervals
  const intervals = [];
  for (let i = 1; i < sorted.length; i++) {
    intervals.push(sorted[i].time - sorted[i - 1].time);
  }
  const sortedIntervals = [...intervals].sort((a, b) => a - b);
  const mid = Math.floor(sortedIntervals.length / 2);
  const median = sortedIntervals.length % 2 === 0
    ? (sortedIntervals[mid - 1] + sortedIntervals[mid]) / 2
    : sortedIntervals[mid];
  if (median <= 0) return irregular;
  for (let i = 0; i < intervals.length; i++) {
    if (Math.abs(intervals[i] - median) / median > 0.05) {
      irregular.add(sorted[i + 1]); // the marker that ends the irregular interval
    }
  }
  return irregular;
}

function fmtTime(sec) {
  if (sec == null || isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec % 1) * 10);
  return `${m}:${String(s).padStart(2, '0')}.${ms}`;
}


function estimateBpm() {
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  if (sorted.length < 2) return null;
  const intervals = [];
  for (let i = 1; i < sorted.length; i++) {
    const dt = sorted[i].time - sorted[i - 1].time;
    if (dt >= 0.3 && dt <= 4.0) intervals.push(dt);
  }
  if (intervals.length === 0) return null;
  const avg = intervals.reduce((a, b) => a + b, 0) / intervals.length;
  return Math.round(240 / avg);
}

function resetAudioSplit() {
  markers = [];
  tapHistory = [];
  exportInProgress = false;
  playbackSpeed = 1.0;
  waveformZoom = 1.0;
  audio.setPlaybackRate(1.0);
}

/**
 * Save current markers[] into the song object in the DB.
 * Called after tapping is done (export) and can be restored on reload.
 */
function saveMarkersToSong() {
  if (!selectedSongId || !db.songs[selectedSongId]) return;
  const song = db.songs[selectedSongId];

  song.split_markers = {
    markers: markers.map(m => ({ time: m.time })),
  };

  // Update total_bars from marker count
  song.total_bars = markers.length;

  // Ensure db.bars entries exist for each bar
  ensureCollections();
  for (let b = 1; b <= markers.length; b++) {
    getOrCreateBar(selectedSongId, b);
  }
}

/**
 * Restore markers[] from the song object in the DB.
 * Called after loading reference audio.
 */
function restoreMarkersFromSong() {
  if (!selectedSongId || !db.songs[selectedSongId]) return;
  const song = db.songs[selectedSongId];
  if (!song.split_markers) return;

  const sm = song.split_markers;
  if (!Array.isArray(sm.markers) || sm.markers.length === 0) return;

  markers = sm.markers
    .map(m => ({ time: m.time }))
    .sort((a, b) => a.time - b.time);
}

/* ── Waveform Drawing ──────────────────────────────── */

function drawWaveform() {
  const canvas = document.getElementById('waveform-canvas');
  if (!canvas) return;
  const wrap = document.getElementById('waveform-wrap');
  const scroll = document.getElementById('waveform-scroll');
  if (!wrap || !scroll) return;

  const dpr = window.devicePixelRatio || 1;
  const wrapRect = wrap.getBoundingClientRect();
  const baseW = wrapRect.width;
  const totalW = baseW * waveformZoom;
  const h = wrapRect.height || 120;
  const viewW = baseW;
  const scrollLeft = wrap.scrollLeft;

  scroll.style.width = totalW + 'px';
  canvas.width = viewW * dpr;
  canvas.height = h * dpr;
  canvas.style.width = viewW + 'px';
  canvas.style.height = '100%';
  canvas.style.position = 'sticky';
  canvas.style.left = '0px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, viewW, h);

  const buf = audio.getBuffer();
  if (!buf) return;
  const duration = buf.duration;

  const vToC = (vx) => vx - scrollLeft;
  const tStart = (scrollLeft / totalW) * duration;
  const tEnd = ((scrollLeft + viewW) / totalW) * duration;
  const pxPerSec = totalW / duration;

  const buckets = Math.floor(viewW);
  const peaks = audio.getPeaksRange(tStart, tEnd, buckets);
  const mid = h / 2;

  ctx.strokeStyle = 'rgba(92, 96, 128, 0.2)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(viewW, mid);
  ctx.stroke();

  for (let i = 0; i < buckets; i++) {
    const amp = peaks[i];
    const barH = amp * (h * 0.9);
    const opacity = 0.3 + amp * 0.7;
    ctx.fillStyle = `rgba(0, 220, 130, ${opacity})`;
    ctx.fillRect(i, mid - barH / 2, Math.max(0.5, 1), barH || 1);
  }

  const margin = 80;
  const inView = (vx) => vx >= scrollLeft - margin && vx <= scrollLeft + viewW + margin;

  // Compute absolute bar number for each marker
  let absBarNum = 0;
  const sortedMarkers = [...markers].sort((a, b) => a.time - b.time);
  const markerAbsBar = new Map();
  for (const m of sortedMarkers) {
    absBarNum++;
    markerAbsBar.set(m, absBarNum);
  }

  // Detect irregular bars for red flag display
  const irregularSet = getIrregularBars();

  // Draw all markers (cyan = normal, red = irregular)
  for (const m of sortedMarkers) {
    const vx = (m.time / duration) * totalW;
    if (!inView(vx)) continue;
    const x = vToC(vx);
    const isDragTarget = _isDragging && _dragMarker && _dragMarker.marker === m;
    const isIrregular = irregularSet.has(m);

    const cyanLine = isDragTarget ? 'rgba(56, 189, 248, 0.9)' : 'rgba(56, 189, 248, 0.4)';
    const redLine = isDragTarget ? 'rgba(255, 59, 92, 0.9)' : 'rgba(255, 59, 92, 0.5)';
    ctx.strokeStyle = isIrregular ? redLine : cyanLine;
    ctx.lineWidth = isDragTarget ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();

    const label = String(markerAbsBar.get(m) || '');
    ctx.font = '9px "DM Mono", monospace';
    const tw = ctx.measureText(label).width;
    const flagW = tw + 6;
    const flagH = 14;
    const flagX = x;
    const flagY = h - flagH;
    const cyanFlag = isDragTarget ? 'rgba(56, 189, 248, 1.0)' : 'rgba(56, 189, 248, 0.7)';
    const redFlag = isDragTarget ? 'rgba(255, 59, 92, 1.0)' : 'rgba(255, 59, 92, 0.8)';
    ctx.fillStyle = isIrregular ? redFlag : cyanFlag;
    ctx.fillRect(flagX, flagY, flagW, flagH);
    ctx.fillStyle = isIrregular ? '#fff' : '#08090d';
    ctx.fillText(label, flagX + 3, flagY + 10);

    if (isDragTarget) {
      ctx.font = '10px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(56, 189, 248, 0.95)';
      ctx.fillText(fmtTime(m.time), x + 4, h / 2);
    }
  }

  // Playhead (green with glow)
  const cur = audio.getCurrentTime();
  if (cur > 0 || audio.isPlaying()) {
    const vpx = (cur / duration) * totalW;
    const px = vToC(vpx);
    if (px >= -5 && px <= viewW + 5) {
      ctx.shadowColor = '#00dc82';
      ctx.shadowBlur = 6;
      ctx.strokeStyle = '#00dc82';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, h);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    if (waveformZoom > 1 && !_suppressAutoScroll) {
      if (vpx < scrollLeft + 40 || vpx > scrollLeft + viewW - 40) {
        wrap.scrollLeft = vpx - viewW * 0.3;
      }
    }
  }
}

function startPlayheadAnimation() {
  cancelAnimationFrame(animFrameId);
  function tick() {
    drawWaveform();
    updateTransportDisplay();
    if (audio.isPlaying()) {
      animFrameId = requestAnimationFrame(tick);
    }
  }
  animFrameId = requestAnimationFrame(tick);
}

function stopPlayheadAnimation() {
  cancelAnimationFrame(animFrameId);
  drawWaveform();
  updateTransportDisplay();
}

function updateTransportDisplay() {
  const timeEl = document.getElementById('t-time');
  const progressEl = document.getElementById('t-progress');
  if (!timeEl || !progressEl || !audioMeta) return;

  const cur = audio.getCurrentTime();
  const dur = audioMeta.duration;
  timeEl.textContent = `${fmtTime(cur)} / ${fmtTime(dur)}`;
  progressEl.style.width = `${(cur / dur * 100)}%`;
}

/* ── Mini Waveform Rendering ──────────────────────── */

/**
 * Draw a mini waveform onto a canvas element using reference audio peaks.
 * @param {HTMLCanvasElement} canvas
 * @param {number} startSec - start time in seconds
 * @param {number} endSec - end time in seconds
 * @param {string} [color='#00dc82'] - waveform bar color
 */
function drawMiniWaveform(canvas, startSec, endSec, color = '#00dc82') {
  if (!canvas || !audio.getBuffer()) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w <= 0 || h <= 0) return;

  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const buckets = Math.floor(w);
  const peaks = audio.getPeaksRange(startSec, endSec, buckets);
  const mid = h / 2;

  for (let i = 0; i < buckets; i++) {
    const amp = peaks[i];
    const barH = amp * (h * 0.85);
    const opacity = 0.35 + amp * 0.65;
    ctx.fillStyle = color.replace(')', `, ${opacity})`).replace('rgb', 'rgba');
    ctx.fillRect(i, mid - barH / 2, 1, barH || 1);
  }
}

/**
 * After rendering a tab with mini waveform canvases, call this to draw them.
 * Each canvas should have: data-wave-start, data-wave-end, and optionally data-wave-color.
 */
function renderMiniWaveforms(container) {
  if (!audio.getBuffer()) return;
  const canvases = (container || document).querySelectorAll('canvas[data-wave-start]');
  for (const c of canvases) {
    const start = parseFloat(c.dataset.waveStart);
    const end = parseFloat(c.dataset.waveEnd);
    const color = c.dataset.waveColor || 'rgb(0, 220, 130)';
    if (!isNaN(start) && !isNaN(end) && end > start) {
      drawMiniWaveform(c, start, end, color);
    }
  }
}


/* ── Waveform Marker Drag System ──────────────────── */

const DRAG_HIT_PX = 10;    // pixel threshold to grab a marker
const DRAG_MOVE_PX = 3;    // min pixels before drag activates

/* ── Floating Touch Drag Balloon ──────────────────── */

let _dragBalloon = null;

function showDragBalloon(label, time, color, clientX, clientY) {
  if (!_dragBalloon) {
    _dragBalloon = document.createElement('div');
    _dragBalloon.className = 'drag-balloon';
    document.body.appendChild(_dragBalloon);
  }
  const timeHtml = time ? `<span class="db-time">${fmtTime(time)}</span>` : '';
  _dragBalloon.innerHTML = `<span class="db-label">${esc(label)}</span>${timeHtml}`;
  _dragBalloon.style.setProperty('--db-color', color);
  _dragBalloon.classList.add('visible');
  // Position: centered on X, 70px above touch point
  const bw = _dragBalloon.offsetWidth || 100;
  const left = Math.max(4, Math.min(window.innerWidth - bw - 4, clientX - bw / 2));
  _dragBalloon.style.left = left + 'px';
  _dragBalloon.style.top = (clientY - 76) + 'px';
}

function hideDragBalloon() {
  if (_dragBalloon) {
    _dragBalloon.classList.remove('visible');
  }
}

/**
 * Find the nearest marker to a given x pixel position on the waveform.
 * Returns { marker: ref, distPx: number } or null.
 */
function hitTestMarker(xPx, yPx) {
  if (!audioMeta) return null;
  const scroll = document.getElementById('waveform-scroll');
  if (!scroll) return null;
  const totalW = scroll.getBoundingClientRect().width;
  const duration = audioMeta.duration;
  const wrap = document.getElementById('waveform-wrap');
  const canvasH = wrap ? wrap.getBoundingClientRect().height : 100;
  if (duration <= 0 || totalW <= 0) return null;

  let best = null;

  // Compute absolute bar numbers for flag label widths
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  let absNum = 0;

  for (const m of sorted) {
    absNum++;
    const mx = (m.time / duration) * totalW;

    // Bar markers — draggable via bottom flag
    const FLAG_H_BAR = 18;
    if (yPx !== undefined && yPx < canvasH - FLAG_H_BAR) continue;
    const label = String(absNum);
    const flagW = label.length * 7 + 6;
    const inFlag = xPx >= mx && xPx <= mx + flagW;
    const nearLine = Math.abs(xPx - mx) <= DRAG_HIT_PX;
    if (inFlag || nearLine) {
      best = { marker: m, distPx: 0 };
      break;
    }
  }

  return best;
}

/**
 * Convert a mouse/touch event to an X position relative to the scrollable waveform content.
 */
function waveformEventX(e) {
  const wrap = document.getElementById('waveform-wrap');
  if (!wrap) return 0;
  const rect = wrap.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  return clientX - rect.left + wrap.scrollLeft;
}

/** Get Y position relative to the waveform canvas. */
function waveformEventY(e) {
  const wrap = document.getElementById('waveform-wrap');
  if (!wrap) return 0;
  const rect = wrap.getBoundingClientRect();
  const clientY = e.touches ? e.touches[0].clientY : e.clientY;
  return clientY - rect.top;
}

function onWaveformPointerDown(e) {
  if (!audioMeta) return;
  // Only handle primary button (left click) or single touch
  if (e.type === 'mousedown' && e.button !== 0) return;
  if (e.touches && e.touches.length > 1) return; // Ignore multi-touch

  const x = waveformEventX(e);
  const y = waveformEventY(e);
  const hit = hitTestMarker(x, y);
  if (!hit) return; // No marker hit → let click handler do seek

  // Start potential drag
  _dragMarker = {
    marker: hit.marker,
        originalTime: hit.marker.time,
  };
  _isDragging = false;
  _isTouchDrag = !!e.touches;
  _dragStartX = e.touches ? e.touches[0].clientX : e.clientX;

  // Prevent text selection during drag
  e.preventDefault();
}

/**
 * Compute drag boundaries for a marker so it cannot be dragged past its neighbours.
 * Returns { min, max } in seconds. Includes a small gap (MIN_MARKER_GAP) to prevent overlap.
 */
const MIN_MARKER_GAP = 0.05; // 50ms minimum gap between markers
function getDragBounds(markerRef) {
  const duration = audioMeta ? audioMeta.duration : Infinity;
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  const idx = sorted.indexOf(markerRef);
  const min = idx > 0 ? sorted[idx - 1].time + MIN_MARKER_GAP : 0;
  const max = idx < sorted.length - 1 ? sorted[idx + 1].time - MIN_MARKER_GAP : duration;

  return { min, max };
}

function onWaveformPointerMove(e) {
  const wrap = document.getElementById('waveform-wrap');
  if (!wrap || !audioMeta) return;

  // Ignore multi-touch moves
  if (e.touches && e.touches.length > 1) {
    cancelDrag();
    return;
  }

  if (_dragMarker) {
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const dx = Math.abs(clientX - _dragStartX);

    // Activate drag after threshold
    if (!_isDragging && dx >= DRAG_MOVE_PX) {
      _isDragging = true;
      wrap.classList.add('dragging');
    }

    if (_isDragging) {
      e.preventDefault();
      const x = waveformEventX(e);
      const scroll = document.getElementById('waveform-scroll');
      if (!scroll || !audioMeta) return;
      const totalW = scroll.getBoundingClientRect().width;
      const duration = audioMeta.duration;
      const rawTime = (x / totalW) * duration;

      // Clamp to drag bounds so markers cannot cross neighbours
      const bounds = getDragBounds(_dragMarker.marker);
      const newTime = Math.max(bounds.min, Math.min(bounds.max, rawTime));

      // Update marker time
      _dragMarker.marker.time = newTime;

      drawWaveform();

      // Show floating balloon above finger during touch drag
      if (_isTouchDrag) {
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        const sorted = [...markers].sort((a, b) => a.time - b.time);
        const absNum = sorted.indexOf(_dragMarker.marker) + 1;
        const label = `Bar ${absNum}`;
        const color = '#38bdf8';
        showDragBalloon(label, newTime, color, clientX, clientY);
      }
    }
  } else {
    // Hover cursor: show grab when near a marker/flag
    const x = waveformEventX(e);
    const y = waveformEventY(e);
    const hit = hitTestMarker(x, y);
    wrap.style.cursor = hit ? 'grab' : 'crosshair';
  }
}

/** Cancel an in-progress drag, reverting the marker to its original position. */
function cancelDrag() {
  if (_dragMarker) {
    if (_isDragging) {
      _dragMarker.marker.time = _dragMarker.originalTime;
      drawWaveform();
    }
  }
  hideDragBalloon();
  const wrap = document.getElementById('waveform-wrap');
  if (wrap) {
    wrap.classList.remove('dragging');
    wrap.style.cursor = 'crosshair';
  }
  _dragMarker = null;
  _isDragging = false;
}

function onWaveformPointerUp(e) {
  hideDragBalloon();
  const wrap = document.getElementById('waveform-wrap');
  if (wrap) {
    wrap.classList.remove('dragging');
    wrap.style.cursor = 'crosshair';
  }

  // Tap without drag on a bar marker → show context menu
  if (_dragMarker && !_isDragging) {
    const clientX = e.changedTouches ? e.changedTouches[0].clientX : e.clientX;
    const clientY = e.changedTouches ? e.changedTouches[0].clientY : e.clientY;
    const globalIdx = markers.indexOf(_dragMarker.marker);
    if (globalIdx >= 0) {
      showBarContextMenu(clientX, clientY, globalIdx, 'split');
    }
    _dragMarker = null;
    _isDragging = false;
    return;
  }

  if (_dragMarker && _isDragging) {
    // If a part-start marker was dragged far enough, leave a bar marker at the original position
    if (_dragMarker.isPartStart) {
      const origTime = _dragMarker.originalTime;
      const newTime = _dragMarker.marker.time;
      const displacement = Math.abs(newTime - origTime);
      const song = db.songs[selectedSongId];
      const bpm = song ? (song.bpm || 120) : 120;
      const quarterBar = 60 / bpm;
      if (displacement > quarterBar * 0.25) {
        const hasBarAtOrig = markers.some(m => Math.abs(m.time - origTime) < 0.05 && m !== _dragMarker.marker);
        if (!hasBarAtOrig) {
          
          if (partId) {
            markers.push({ time: origTime });
          }
        }
      }
    }

    // Sort markers by time to maintain order
    markers.sort((a, b) => a.time - b.time);

    // Persist and update UI — preserve scroll positions across re-render
    saveMarkersToSong();
    markDirty();

    const scrollEl = document.getElementById('audio-scroll');
    const savedScrollTop = scrollEl ? scrollEl.scrollTop : 0;
    const savedWrapScroll = wrap ? wrap.scrollLeft : 0;

    _suppressAutoScroll = true;
    renderAudioTab();

    // Restore scroll after renderAudioTab's requestAnimationFrame has run
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const scrollEl2 = document.getElementById('audio-scroll');
        if (scrollEl2) scrollEl2.scrollTop = savedScrollTop;
        const wrap2 = document.getElementById('waveform-wrap');
        if (wrap2) wrap2.scrollLeft = savedWrapScroll;
        _suppressAutoScroll = false;
      });
    });

    _dragSuppressClick = true;
  }

  _dragMarker = null;
  _isDragging = false;
}


/* ── Bar Marker Context Menu (Delete) ──────────────── */

let _barCtxMenu = null;

/**
 * Show context menu near a tapped bar marker to allow deletion.
 * @param {number} clientX - screen X
 * @param {number} clientY - screen Y
 * @param {number} barIndex - index in markers array
 * @param {string} context - 'split' or 'pw' (part waveform editor)
 */
function showBarContextMenu(clientX, clientY, barIndex, context) {
  hideBarContextMenu();
  const barNum = barIndex + 1;
  const menu = document.createElement('div');
  menu.className = 'bar-ctx-menu';
  menu.innerHTML = `<button data-action="delete">&#128465; Takt ${barNum} l&ouml;schen</button>`;
  menu.style.left = clientX + 'px';
  menu.style.top = clientY + 'px';
  document.body.appendChild(menu);
  _barCtxMenu = menu;

  // Clamp to viewport
  const r = menu.getBoundingClientRect();
  if (r.right > window.innerWidth) menu.style.left = (window.innerWidth - r.width - 8) + 'px';
  if (r.bottom > window.innerHeight) menu.style.top = (window.innerHeight - r.height - 8) + 'px';

  menu.querySelector('[data-action="delete"]').onclick = () => {
    hideBarContextMenu();
    deleteBarMarker(barIndex, context);
  };

  // Close on click outside
  setTimeout(() => {
    document.addEventListener('pointerdown', _barCtxOutside, { once: true });
  }, 50);
}

function _barCtxOutside(e) {
  if (_barCtxMenu && !_barCtxMenu.contains(e.target)) hideBarContextMenu();
}

function hideBarContextMenu() {
  if (_barCtxMenu) { _barCtxMenu.remove(); _barCtxMenu = null; }
  document.removeEventListener('pointerdown', _barCtxOutside);
}

/**
 * Delete a bar marker and renumber remaining bars in that part.
 */
function deleteBarMarker(barIndex, context) {
  if (barIndex < 0 || barIndex >= markers.length) return;
  const removed = markers[barIndex];
  markers.splice(barIndex, 1);

  // Persist to song and update bar counts
  saveMarkersToSong();
  markDirty();

  if (context === 'pw') {
    // Refresh Finetuning modal
    _pwDrawWaveform();
    _pwUpdateUI();
  } else {
    // Refresh Splitting tab
    const scrollEl = document.getElementById('audio-scroll');
    const savedScrollTop = scrollEl ? scrollEl.scrollTop : 0;
    const wrap = document.getElementById('waveform-wrap');
    const savedWrapScroll = wrap ? wrap.scrollLeft : 0;
    _suppressAutoScroll = true;
    renderAudioTab();
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const scrollEl2 = document.getElementById('audio-scroll');
        if (scrollEl2) scrollEl2.scrollTop = savedScrollTop;
        const wrap2 = document.getElementById('waveform-wrap');
        if (wrap2) wrap2.scrollLeft = savedWrapScroll;
        _suppressAutoScroll = false;
      });
    });
  }
  toast('Takt-Marker gelöscht', 'success');
}


/**
 * Attach drag event listeners to the waveform wrap element.
 * Called after each renderAudioTab since innerHTML replaces the elements.
 */
/* ── Pinch-to-Zoom state ──────────────────────────── */
let _pinchActive = false;
let _pinchStartDist = 0;
let _pinchStartZoom = 1;

function getTouchDist(t1, t2) {
  const dx = t1.clientX - t2.clientX;
  const dy = t1.clientY - t2.clientY;
  return Math.sqrt(dx * dx + dy * dy);
}

function onPinchStart(e) {
  if (e.touches.length !== 2) return;
  _pinchActive = true;
  _pinchStartDist = getTouchDist(e.touches[0], e.touches[1]);
  _pinchStartZoom = waveformZoom;
  e.preventDefault();
}

function onPinchMove(e) {
  if (!_pinchActive || e.touches.length !== 2) return;
  e.preventDefault();
  const dist = getTouchDist(e.touches[0], e.touches[1]);
  const scale = dist / _pinchStartDist;
  const minZoom = ZOOM_STEPS[0];
  const maxZoom = ZOOM_STEPS[ZOOM_STEPS.length - 1];
  const newZoom = Math.max(minZoom, Math.min(maxZoom, _pinchStartZoom * scale));

  // Snap to nearest step for rendering
  let best = ZOOM_STEPS[0];
  for (const s of ZOOM_STEPS) {
    if (Math.abs(s - newZoom) < Math.abs(best - newZoom)) best = s;
  }

  if (best !== waveformZoom) {
    const wrap = document.getElementById('waveform-wrap');
    const oldZoom = waveformZoom;
    waveformZoom = best;

    // Preserve scroll center
    if (wrap && oldZoom > 0) {
      const viewCenter = wrap.scrollLeft + wrap.clientWidth / 2;
      const oldWidth = wrap.clientWidth * oldZoom;
      const ratio = oldWidth > 0 ? viewCenter / oldWidth : 0;
      drawWaveform();
      const newWidth = wrap.clientWidth * waveformZoom;
      wrap.scrollLeft = ratio * newWidth - wrap.clientWidth / 2;
    } else {
      drawWaveform();
    }

    const label = document.getElementById('t-zoom-label');
    if (label) label.textContent = '\uD83D\uDD0D ' + (waveformZoom === 1 ? '1\u00d7' : waveformZoom.toFixed(1) + '\u00d7');
  }
}

function onPinchEnd(e) {
  if (_pinchActive) {
    _pinchActive = false;
    // Suppress the next click/tap that fires after pinch
    _dragSuppressClick = true;
    setTimeout(() => { _dragSuppressClick = false; }, 300);
  }
}

function initWaveformDrag() {
  const wrap = document.getElementById('waveform-wrap');
  if (!wrap) return;

  // Remove old document-level listeners to prevent duplicates
  document.removeEventListener('mousemove', onWaveformPointerMove);
  document.removeEventListener('mouseup', onWaveformPointerUp);
  document.removeEventListener('touchmove', onWaveformPointerMove);
  document.removeEventListener('touchend', onWaveformPointerUp);
  document.removeEventListener('touchcancel', cancelDrag);

  // Mouse events
  wrap.addEventListener('mousedown', onWaveformPointerDown);
  document.addEventListener('mousemove', onWaveformPointerMove);
  document.addEventListener('mouseup', onWaveformPointerUp);

  // Touch events (iPad support): single-finger drag + two-finger pinch
  wrap.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2) {
      onPinchStart(e);
    } else if (e.touches.length === 1 && !_pinchActive) {
      onWaveformPointerDown(e);
    }
  }, { passive: false });
  document.addEventListener('touchmove', (e) => {
    if (_pinchActive) {
      onPinchMove(e);
    } else {
      onWaveformPointerMove(e);
    }
  }, { passive: false });
  document.addEventListener('touchend', (e) => {
    if (_pinchActive) {
      onPinchEnd(e);
    } else {
      onWaveformPointerUp(e);
    }
  });
  document.addEventListener('touchcancel', (e) => {
    if (_pinchActive) onPinchEnd(e);
    else cancelDrag(e);
  });

  // Redraw on scroll so viewport-rendered waveform stays in sync
  wrap.addEventListener('scroll', () => drawWaveform(), { passive: true });
}

/* ── Audio Split Event Handlers ────────────────────── */

function handleAudioFileLoad(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    const arrayBuf = e.target.result;

    // Clone BEFORE decodeAudio — decodeAudioData detaches the original ArrayBuffer!
    const uploadBuf = arrayBuf.slice(0);

    // Check if a reference audio already exists
    const song = selectedSongId ? db.songs[selectedSongId] : null;
    if (song && song.audio_ref) {
      const confirmed = await showConfirm(
        'Referenz-Audio ersetzen?',
        `F\u00fcr <strong>${esc(song.name)}</strong> existiert bereits eine Referenz-Audiodatei.<br><br>` +
        `Durch das Ersetzen k\u00f6nnen alle bestehenden Zeitinformationen (Bar-Marker, Audio-Segmente) ung\u00fcltig werden.<br><br>` +
        `<strong>Trotzdem ersetzen?</strong>`,
        'Ersetzen'
      );
      if (!confirmed) {
        toast('Lade bestehende Referenz-Audio...', 'info');
        await loadReferenceAudio();
        return;
      }
      // Reset audio-dependent TMS tasks when replacing reference audio
      const tms = getSongTms(selectedSongId);
      const audioDepTasks = ['bar_markers', 'audio_exported'];
      const before = tms.manual_done.length;
      tms.manual_done = tms.manual_done.filter(id => !audioDepTasks.includes(id));
      if (tms.manual_done.length < before) {
        song.tms = tms;
        markDirty();
        toast('Audio-abhängige TMS-Aufgaben zurückgesetzt', 'info');
      }
    }

    // 1. Decode audio for playback (detaches arrayBuf — that's why we cloned above)
    try {
      const meta = await audio.decodeAudio(arrayBuf);
      audioMeta = meta;
      audioFileName = file.name;
      resetAudioSplit();
      renderAudioTab();
      toast(`Audio geladen: ${fmtTime(meta.duration)}`, 'success');
    } catch (err) {
      console.error('Audio decode error:', err);
      toast(`Audio-Decode-Fehler: ${err.message}`, 'error');
      return;
    }

    // 2. Upload to GitHub (separate try/catch — decode success should not be rolled back)
    try {
      await uploadReferenceAudio(uploadBuf, file.name);
    } catch (err) {
      console.error('Reference upload error:', err);
      toast(`Upload-Fehler: ${err.message}`, 'error', 5000);
    }
  };
  reader.readAsArrayBuffer(file);
}

/**
 * Upload the full reference audio to GitHub and store path in song.
 */
async function uploadReferenceAudio(arrayBuffer, fileName) {
  const songId = selectedSongId;
  if (!songId) return;

  const song = db.songs[songId];
  if (!song) return;

  const path = buildRefAudioPath(song);

  // Always cache in memory for instant reload on song switch
  _audioRefCache[songId] = arrayBuffer.slice(0);

  // Always set audio_ref in DB (in-memory) so other tabs know it exists
  song.audio_ref = path;
  song.audio_ref_name = fileName;
  markDirty();

  const s = getSettings();
  if (!s.token || !s.repo) {
    toast('Kein GitHub-Token \u2014 Audio nur im Speicher, nicht auf GitHub', 'info', 4000);
    return;
  }

  try {
    toast('Referenz-Audio wird auf GitHub hochgeladen...', 'info');

    // Convert ArrayBuffer to base64
    const bytes = new Uint8Array(arrayBuffer);
    const chunkSize = 8192;
    let binary = '';
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    const base64 = btoa(binary);

    await uploadFile(s.repo, path, s.token, base64,
      `Referenz-Audio: ${song.name}`);

    toast('Referenz-Audio auf GitHub gespeichert \u2713', 'success');

    // Auto-save DB so audio_ref persists across page reloads
    await handleSave(false);

    // Re-render if still on the same song
    if (selectedSongId === songId) {
      if (activeTab === 'audio') renderAudioTab();
      else if (activeTab === 'lyrics') renderLyricsTab();
    }
  } catch (err) {
    console.error('Reference upload failed:', err);
    toast(`Upload fehlgeschlagen: ${err.message}`, 'error', 5000);
  }
}

/**
 * Load reference audio from GitHub for current song.
 */
async function loadReferenceAudio() {
  if (!selectedSongId) return;
  const song = db.songs[selectedSongId];
  if (!song || !song.audio_ref) return;
  if (audioMeta) return; // already loaded

  const songId = selectedSongId;
  const s = getSettings();
  const refName = song.audio_ref_name || song.audio_ref.split('/').pop();

  try {
    let arrayBuf;

    // 1. Check in-memory cache first (instant, no network)
    if (_audioRefCache[songId]) {
      arrayBuf = _audioRefCache[songId];
    }

    // 2. Try fetching (direct + GitHub API fallback)
    if (!arrayBuf) {
      toast(`Lade Referenz-Audio: ${refName}...`, 'info');
      arrayBuf = await fetchAudioUrl(song.audio_ref);
    }

    // 3. Legacy fallback: try old ID-based path (audio/{songId}/reference.mp3)
    if (!arrayBuf) {
      const legacyPath = `audio/${songId}/reference.mp3`;
      arrayBuf = await fetchAudioUrl(legacyPath);
    }

    if (!arrayBuf) {
      toast(`Referenz-Audio nicht gefunden: ${refName}`, 'error');
      return;
    }

    // Cache for quick reload on song switch
    _audioRefCache[songId] = arrayBuf.slice(0);

    const meta = await audio.decodeAudio(arrayBuf);
    audioMeta = meta;
    audioFileName = refName;

    // Restore part/bar markers from DB if available
    restoreMarkersFromSong();

    // Re-render the active tab that uses audio (but don't interrupt bar playback)
    if (selectedSongId === songId) {
      if (activeTab === 'audio') renderAudioTab();
      else if (activeTab === 'lyrics') renderLyricsTab();
          else if (activeTab === 'takte' && !_partPlayActive) renderTakteTab();
    }
    toast(`Referenz-Audio geladen: ${fmtTime(meta.duration)}`, 'success');
  } catch (err) {
    console.error('Reference load failed:', err);
    toast(`Referenz-Audio Fehler: ${err.message}`, 'error');
  }
}

function handleWaveformClick(e) {
  // Suppress seek after a drag operation
  if (_dragSuppressClick) {
    _dragSuppressClick = false;
    return;
  }
  if (!audioMeta) return;
  const wrap = document.getElementById('waveform-wrap');
  const scroll = document.getElementById('waveform-scroll');
  if (!wrap || !scroll) return;
  const rect = wrap.getBoundingClientRect();
  const x = e.clientX - rect.left + wrap.scrollLeft;
  const totalW = scroll.getBoundingClientRect().width;

  // Don't seek if clicking on a marker/flag — drag handles that
  const y = e.clientY - rect.top;
  const hit = hitTestMarker(x, y);
  if (hit) return;

  const pct = x / totalW;
  const time = pct * audioMeta.duration;
  audio.seek(time);
  if (audio.isPlaying()) audio.startClick(time);
  drawWaveform();
  updateTransportDisplay();
}

function handlePlayPause() {
  if (!audio.getBuffer()) return;
  audio.warmup(); // Ensure AudioContext is running (iOS gesture requirement)
  if (audio.isPlaying()) {
    audio.pause();
    audio.stopClick();
    stopPlayheadAnimation();
    updateTapButtonStates();
  } else {
    // play() is synchronous — starts source immediately.
    // If AudioContext was suspended, audio + playhead sync via statechange listener.
    audio.play(() => {
      audio.stopClick();
      stopPlayheadAnimation();
      updateTapButtonStates();
      updatePlayButton();
    });
    syncClickToSong();
    audio.startClick(audio.getCurrentTime());
    startPlayheadAnimation();
    updateTapButtonStates();
  }
  updatePlayButton();
}

function handleSkipToStart() {
  audio.seek(0);
  if (audio.isPlaying()) audio.startClick(0);
  drawWaveform();
  updateTransportDisplay();
}

function handleProgressClick(e) {
  if (!audioMeta) return;
  const wrap = document.getElementById('t-progress-wrap');
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  const pct = (e.clientX - rect.left) / rect.width;
  const time = pct * audioMeta.duration;
  audio.seek(time);
  if (audio.isPlaying()) audio.startClick(time);
  drawWaveform();
  updateTransportDisplay();
}

function updatePlayButton() {
  const btn = document.getElementById('t-play');
  if (!btn) return;
  const isPlay = audio.isPlaying();
  btn.classList.toggle('playing', isPlay);
  btn.innerHTML = isPlay ? '&#9646;&#9646;' : '&#9654;';
  btn.title = isPlay ? 'Pause' : 'Play';
}

function updateTapButtonStates() {
  const isPlay = audio.isPlaying();
  const barBtn = document.getElementById('tap-bar');
  const undoBtn = document.getElementById('tap-undo');
  const delBarsBtn = document.getElementById('tap-delete-bars');

  if (barBtn) barBtn.disabled = !isPlay;
  if (undoBtn) undoBtn.disabled = tapHistory.length === 0;
  if (delBarsBtn) delBarsBtn.disabled = markers.length === 0;
}


function handleBarTap() {
  if (!audio.isPlaying()) return;

  // Compensate for audio output latency
  const time = Math.max(0, audio.getCurrentTime() - audio.getOutputLatency());

  markers.push({ time });
  markers.sort((a, b) => a.time - b.time);
  tapHistory.push({ time });

  // Persist markers to song object
  saveMarkersToSong();
  markDirty();

  drawWaveform();
  updateTapInfo();
  updateSplitResultLive();
  updateAudioSummaryLive();
}

function handleUndoTap() {
  if (tapHistory.length === 0) return;
  const last = tapHistory.pop();

  // Remove the marker (match by time)
  markers = markers.filter(m => Math.abs(m.time - last.time) > 0.001);

  // Persist updated markers
  saveMarkersToSong();
  markDirty();

  drawWaveform();
  updateTapInfo();
  updateSplitResultLive();
  updateAudioSummaryLive();
  updateTapButtonStates();
}


function handleSnapToPeaks() {
  if (!audio.getBuffer()) return;
  if (markers.length === 0) return;

  let snapped = 0;
  for (const m of markers) {
    const newTime = audio.findPeakNear(m.time, 80);
    if (Math.abs(newTime - m.time) > 0.001) { m.time = newTime; snapped++; }
  }

  markers.sort((a, b) => a.time - b.time);
  saveMarkersToSong();
  markDirty();
  drawWaveform();
  updateAudioSummaryLive();
  toast(`${snapped} Marker auf Peaks verschoben`, 'success');
}

async function handleDeleteAllBarMarkers() {
  if (markers.length === 0) return;
  const ok = await showConfirm(
    'Alle Marker löschen?',
    `Alle <strong>${markers.length} Marker</strong> werden entfernt.`,
    'Löschen'
  );
  if (!ok) return;
  markers = [];
  tapHistory = [];
  saveMarkersToSong();
  // Sync: also delete db.bars and db.accents for this song
  if (selectedSongId) {
    ensureCollections();
    for (const [barId, bar] of Object.entries(db.bars)) {
      if (bar.song_id === selectedSongId) {
        for (const [accId, acc] of Object.entries(db.accents)) {
          if (acc.bar_id === barId) delete db.accents[accId];
        }
        delete db.bars[barId];
      }
    }
  }
  markDirty();
  renderAudioTab();
}

/* ── Click Track Toggle ──────────────────────────── */

function handleClickToggle() {
  clickEnabled = !clickEnabled;
  audio.setClickEnabled(clickEnabled);
  if (clickEnabled) {
    const songBpm = selectedSongId && db && db.songs[selectedSongId] ? db.songs[selectedSongId].bpm : 0;
    audio.setClickBpm(songBpm);
    if (audio.isPlaying()) {
      audio.startClick(audio.getCurrentTime());
    }
  } else {
    audio.stopClick();
  }
  // Update button visual
  const btn = document.getElementById('t-click');
  if (btn) btn.classList.toggle('active', clickEnabled);
}

/**
 * Sync click BPM when song BPM changes, and start/stop click on playback events.
 */
function syncClickToSong() {
  const songBpm = selectedSongId && db && db.songs[selectedSongId] ? db.songs[selectedSongId].bpm : 0;
  audio.setClickBpm(songBpm);
}

/* ── Speed / Zoom / Marker Edit ───────────────── */

const SPEED_STEPS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5];
const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6, 8, 10, 14, 20];

function handleSpeedChange(dir) {
  const curIdx = SPEED_STEPS.indexOf(playbackSpeed);
  const idx = curIdx === -1 ? SPEED_STEPS.indexOf(1.0) : curIdx;
  const newIdx = Math.max(0, Math.min(SPEED_STEPS.length - 1, idx + dir));
  playbackSpeed = SPEED_STEPS[newIdx];
  audio.setPlaybackRate(playbackSpeed);
  // Restart click track with new speed timing
  if (audio.isPlaying()) audio.startClick(audio.getCurrentTime());
  const label = document.getElementById('t-speed-label');
  if (label) label.textContent = (playbackSpeed === 1 ? '1\u00d7' : playbackSpeed.toFixed(2).replace(/0$/, '') + '\u00d7');
}

function handleZoomChange(dir) {
  const curIdx = ZOOM_STEPS.indexOf(waveformZoom);
  const idx = curIdx === -1 ? 0 : curIdx;
  const newIdx = Math.max(0, Math.min(ZOOM_STEPS.length - 1, idx + dir));
  const oldZoom = waveformZoom;
  waveformZoom = ZOOM_STEPS[newIdx];

  // Preserve scroll position relative to current playhead / view center
  const wrap = document.getElementById('waveform-wrap');
  let scrollRatio = 0;
  if (wrap && oldZoom > 0) {
    const viewCenter = wrap.scrollLeft + wrap.clientWidth / 2;
    const oldWidth = wrap.clientWidth * oldZoom;
    scrollRatio = oldWidth > 0 ? viewCenter / oldWidth : 0;
  }

  drawWaveform();

  // Restore scroll so the same time position stays centered
  if (wrap && waveformZoom > 1) {
    const newWidth = wrap.clientWidth * waveformZoom;
    wrap.scrollLeft = scrollRatio * newWidth - wrap.clientWidth / 2;
  } else if (wrap) {
    wrap.scrollLeft = 0;
  }

  const label = document.getElementById('t-zoom-label');
  if (label) label.textContent = '\uD83D\uDD0D ' + (waveformZoom === 1 ? '1\u00d7' : waveformZoom.toFixed(1) + '\u00d7');
}


function updateTapInfo() {
  const barBtn = document.getElementById('tap-bar');
  if (barBtn) {
    const info = barBtn.querySelector('.tap-info');
    if (info) info.textContent = `Bar ${markers.length + 1}`;
    barBtn.disabled = !audio.isPlaying();
  }

  const undoBtn = document.getElementById('tap-undo');
  if (undoBtn) undoBtn.disabled = tapHistory.length === 0;

  const delBarsBtn = document.getElementById('tap-delete-bars');
  if (delBarsBtn) {
    delBarsBtn.disabled = markers.length === 0;
    const info = delBarsBtn.querySelector('.tap-info');
    if (info) info.textContent = `${markers.length} Takte`;
  }
}

function updateSplitResultLive() {
}

function updateAudioSummaryLive() {
  const bar = document.querySelector('.audio-panel .summary-bar');
  if (!bar) return;
  const items = bar.querySelectorAll('.summary-item .mono');
  if (items[0]) items[0].textContent = markers.length;
  if (items[1]) items[1].textContent = estimateBpm() || '\u2014';
}

/* ── BPM Update ────────────────────────────────────── */

function handleBpmUpdate() {
  const est = estimateBpm();
  if (!est || !selectedSongId) return;
  const song = db.songs[selectedSongId];
  if (!song) return;
  song.bpm = est;
  markDirty();
  toast(`BPM auf ${est} aktualisiert`, 'success');
  renderAudioTab();
}

/* ── Audio Export to GitHub ─────────────────────────── */

async function handleAudioExport() {
  if (!selectedSongId || !audioMeta || exportInProgress) return;
  const s = getSettings();
  if (!s.token || !s.repo) {
    toast('GitHub Token in Settings erforderlich', 'error');
    return;
  }
  if (markers.length === 0) return;

  exportInProgress = true;
  const totalBars = markers.length;
  let done = 0;
  toast(`Audio-Export: 0/${totalBars} Takte...`, 'info');
  ensureCollections();

  try {
    const song = db.songs[selectedSongId];
    const songName = song.name;
    const sortedMarkers = [...markers].sort((a, b) => a.time - b.time);

    for (let b = 0; b < sortedMarkers.length; b++) {
      const barStart = sortedMarkers[b].time;
      const barEnd = (b + 1 < sortedMarkers.length) ? sortedMarkers[b + 1].time : audioMeta.duration;
      const globalBarNum = b + 1;

      const base64mp3 = await audio.exportSegmentMp3(barStart, barEnd);
      const path = `audio/${sanitizePath(songName)}/bar_${String(globalBarNum).padStart(3, '0')}.mp3`;

      await uploadFile(s.repo, path, s.token, base64mp3, `Audio: Bar ${globalBarNum} (${songName})`);

      const [barId, barData] = getOrCreateBar(selectedSongId, globalBarNum);
      barData.audio = path;

      done++;
      if (done % 10 === 0 || done === totalBars) {
        toast(`Audio-Export: ${done}/${totalBars} Takte...`, 'info');
      }
    }

    saveMarkersToSong();
    markDirty();
    toast(`${done} Bar-Segmente exportiert`, 'success');
  } catch (err) {
    toast(`Export-Fehler: ${err.message}`, 'error', 5000);
  } finally {
    exportInProgress = false;
    if (done > 0 && dirty) {
      try {
        const newSha = await saveDB(s.repo, s.path, s.token, db, dbSha);
        dbSha = newSha;
        dirty = false;
        setSyncStatus('saved');
      } catch { /* DB save after export is best-effort */ }
    }
  }
}

/* ── Audio Tab Event Delegation ────────────────────── */

function handleAudioClick(e) {
  const el = e.target;

  // Drop zone
  if (el.closest('#audio-dropzone')) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.wav,.mp3,.m4a,.ogg';
    input.onchange = () => { if (input.files[0]) handleAudioFileLoad(input.files[0]); };
    input.click();
    return;
  }

  // Waveform seek
  if (el.closest('#waveform-wrap')) {
    handleWaveformClick(e);
    return;
  }

  // Transport
  if (el.closest('#t-skip')) { handleSkipToStart(); return; }
  if (el.closest('#t-play')) { handlePlayPause(); return; }
  if (el.closest('#t-progress-wrap')) { handleProgressClick(e); return; }

  // Click track toggle
  if (el.closest('#t-click')) { handleClickToggle(); return; }

  // Speed control
  if (el.closest('#t-speed-down')) { handleSpeedChange(-1); return; }
  if (el.closest('#t-speed-up')) { handleSpeedChange(1); return; }

  // Zoom control
  if (el.closest('#t-zoom-out')) { handleZoomChange(-1); return; }
  if (el.closest('#t-zoom-in')) { handleZoomChange(1); return; }


  // Tap buttons
  if (el.closest('#tap-bar') && !el.closest('#tap-bar').disabled) { handleBarTap(); return; }
  if (el.closest('#tap-undo') && !el.closest('#tap-undo').disabled) { handleUndoTap(); return; }
  if (el.closest('#tap-snap-peaks') && !el.closest('#tap-snap-peaks').disabled) { handleSnapToPeaks(); return; }
  if (el.closest('#tap-delete-bars') && !el.closest('#tap-delete-bars').disabled) { handleDeleteAllBarMarkers(); return; }

  // BPM update
  if (el.closest('#btn-update-bpm')) { handleBpmUpdate(); return; }

  // Export
  if (el.closest('#btn-export')) { handleAudioExport(); return; }
}

function handleAudioDragOver(e) {
  e.preventDefault();
  const dz = document.getElementById('audio-dropzone');
  if (dz) dz.classList.add('dragover');
}

function handleAudioDragLeave(e) {
  const dz = document.getElementById('audio-dropzone');
  if (dz) dz.classList.remove('dragover');
}

function handleAudioDrop(e) {
  e.preventDefault();
  const dz = document.getElementById('audio-dropzone');
  if (dz) dz.classList.remove('dragover');
  const file = e.dataTransfer?.files[0];
  if (file) handleAudioFileLoad(file);
}


/* ══════════════════════════════════════════════════════
   LYRICS EDITOR — Block-based Canvas
   Bausteine: part (orange), bar (cyan), word (weiß)
   Layout: flex-wrap, Drag & Drop, Kontextmenü
   ══════════════════════════════════════════════════════ */

/**
 * Check if any bars have lyrics assigned.
 */
function leHasAnyBarLyrics() {
  ensureCollections();
  for (const [, b] of Object.entries(db.bars)) {
    if (b.song_id === selectedSongId && b.lyrics) return true;
  }
  return false;
}

/**
 * Build the block array from song data.
 * Blocks: [{type:'bar'|'word', content, barNum, id}]
 * Order: Bar 1 → words... → Bar 2 → words...
 */
function leBuildBlocks(songId) {
  const song = db.songs[songId];
  if (!song) return [];
  ensureCollections();

  const blocks = [];
  let blockId = 0;
  const totalBars = song.total_bars || 0;

  let nextBarNewline = false;
  for (let b = 1; b <= totalBars; b++) {
    const barBlock = {
      type: 'bar',
      content: String(b),
      barNum: b,
      id: `lb_${blockId++}`
    };
    if (nextBarNewline) {
      barBlock.newline = true;
      nextBarNewline = false;
    }
    blocks.push(barBlock);

    // Word blocks from bar lyrics
    const found = findBar(songId, b);
    let lyrics = found ? (found[1].lyrics || '').trim() : '';

    // Trailing \n means next bar starts on a new line
    if (lyrics.endsWith('\n')) {
      nextBarNewline = true;
      lyrics = lyrics.slice(0, -1).trim();
    }

    if (lyrics) {
      const words = lyrics.split(/\s+/).filter(w => w.length > 0);
      for (let wi = 0; wi < words.length; wi++) {
        blocks.push({
          type: 'word',
          content: words[wi],
          barNum: b,
          wordIndexInBar: wi,
          wordCountInBar: words.length,
          id: `lb_${blockId++}`
        });
      }
    }
  }

  return blocks;
}

/**
 * Distribute raw text words evenly across non-instrumental bars.
 */
function leDistributeText(songId, rawText) {
  const song = db.songs[songId];
  if (!song) return [];
  ensureCollections();

  // Parse words from raw text (strip section headers)
  const cleanText = rawText.replace(/\[.*?\]/g, '').trim();
  const allWords = cleanText.split(/\s+/).filter(w => w.length > 0);
  if (allWords.length === 0) return _leBlocks;

  // All bars
  const totalBars = song.total_bars || 0;
  if (totalBars === 0) return _leBlocks;

  // Distribute words evenly
  const wordsPerBar = Math.ceil(allWords.length / bars.length);
  let wordIdx = 0;

  const blocks = [];
  let blockId = 0;

  for (let b = 1; b <= totalBars; b++) {
    blocks.push({
      type: 'bar',
      content: String(b),
      barNum: b,
      id: `lb_${blockId++}`
    });

    const barWords = allWords.slice(wordIdx, wordIdx + wordsPerBar);
    wordIdx += wordsPerBar;
    for (const w of barWords) {
      blocks.push({
        type: 'word',
        content: w,
        barNum: b,
        id: `lb_${blockId++}`
      });
    }
  }

  return blocks;
}

/**
 * Initialize the block canvas for a song.
 */
function leInitFromSong(song) {
  _leInitSongId = selectedSongId;
  _leBlocks = leBuildBlocks(selectedSongId);
}

/* ── Lyrics Editor: Rendering ────────────────────── */

function renderLyricsTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Song aus der Liste links ausw&auml;hlen.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  ensureCollections();

  // Check if song has any bars defined
  const totalBars = song.total_bars || 0;
  if (totalBars === 0) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Bitte erst Takte anlegen.</p></div>`;
    return;
  }

  // Auto-load reference audio
  if (!audio.getBuffer() && song.audio_ref && _refLoadingFor !== selectedSongId) {
    _refLoadingFor = selectedSongId;
    _refLoadingPromise = loadReferenceAudio().finally(() => { _refLoadingFor = null; _refLoadingPromise = null; });
  }

  // Initialize blocks if needed
  if (_leInitSongId !== selectedSongId) {
    leInitFromSong(song);
  }

  const hasWords = _leBlocks.some(b => b.type === 'word');
  const searchQ = encodeURIComponent(song.name + ' ' + song.artist);
  const geniusUrl = `https://genius.com/search?q=${searchQ}`;
  const musixUrl = `https://www.musixmatch.com/search/${searchQ}`;

  let html = `<div class="lyrics-panel le-panel">
    <div class="audio-song-header">
      <div>
        <div class="ash-name">${esc(song.name)}</div>
        <div class="ash-artist">${esc(song.artist)}</div>
      </div>
      <div class="le-header-actions">
        <button class="btn btn-sm lyrics-genius-link" id="le-genius-quick" title="Lyrics direkt von Genius laden">&#127925; Genius Auto</button>
        <a href="${geniusUrl}" target="_blank" rel="noopener" class="btn btn-sm" title="Genius-Suche &ouml;ffnen">&#128269; Genius</a>
        <a href="${musixUrl}" target="_blank" rel="noopener" class="btn btn-sm lyrics-musix-link" title="Musixmatch-Suche &ouml;ffnen">&#128269; Musixmatch</a>
        <button class="btn btn-sm" id="le-paste-btn" title="Text einfügen und auf Takte verteilen">&#128203; Text einf&uuml;gen</button>
        ${hasWords ? '<button class="btn btn-sm le-btn-save" id="le-save-lyrics">&#128190; Speichern</button>' : ''}
        ${hasWords ? '<button class="btn btn-sm le-btn-danger" id="le-clear-words" title="Alle Wörter entfernen">W&ouml;rter l&ouml;schen</button>' : ''}
      </div>
    </div>`;

  // Block canvas
  html += `<div class="le-canvas" id="le-canvas">`;
  html += leRenderBlocks();
  html += `</div>`;

  // Legend
  html += `<div class="le-legend">
    <span class="le-legend-item"><span class="le-legend-swatch le-swatch-bar"></span> Takt</span>
    <span class="le-legend-item"><span class="le-legend-swatch le-swatch-word"></span> Wort</span>
  </div>`;

  html += '</div>';
  els.content.innerHTML = html;

  // Wire canvas events
  leWireCanvasEvents();
}

/**
 * Render all blocks as HTML elements in the canvas.
 */
function leRenderBlocks() {
  let html = '';
  for (let i = 0; i < _leBlocks.length; i++) {
    const b = _leBlocks[i];
    // Line break before part blocks, before first bar of each part, and blocks with newline flag
    if (b.newline) {
      html += '<span class="le-break"></span>';
    }
    let cls = `le-block le-block-${b.type}`;
    // Mark last word before a newline bar with ↵ indicator
    let displayContent = esc(b.content);
    if (b.type === 'word') {
      const next = i + 1 < _leBlocks.length ? _leBlocks[i + 1] : null;
      if (next && next.type === 'bar' && next.newline) {
        displayContent += '<span class="le-newline-marker">↵</span>';
      }
    }
    const draggable = 'draggable="true"';
    html += `<span class="${cls}" ${draggable} data-idx="${i}" data-type="${b.type}" data-id="${b.id}">${displayContent}</span>`;

  }
  return html;
}

/**
 * Re-render only the canvas content (blocks), not the whole tab.
 */
function leRefreshCanvas() {
  const canvas = document.getElementById('le-canvas');
  if (!canvas) return;
  canvas.innerHTML = leRenderBlocks();
}

/* ── Lyrics Editor: Canvas Events (Drag & Drop + Context Menu) ── */

function leWireCanvasEvents() {
  const canvas = document.getElementById('le-canvas');
  if (!canvas) return;

  // Drag start
  canvas.addEventListener('dragstart', (e) => {
    const block = e.target.closest('.le-block');
    if (!block) return;
    const idx = parseInt(block.dataset.idx, 10);
    const blockData = _leBlocks[idx];
    if (!blockData) return;

    _leDrag = { idx, type: blockData.type, id: blockData.id };
    block.classList.add('le-dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(idx));
  });

  canvas.addEventListener('dragend', (e) => {
    document.querySelectorAll('.le-block.le-dragging').forEach(el => el.classList.remove('le-dragging'));
    document.querySelectorAll('.le-drop-indicator').forEach(el => el.remove());
    _leDrag = null;
  });

  // Drag over: show drop indicator
  canvas.addEventListener('dragover', (e) => {
    if (!_leDrag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    // Find nearest block boundary
    const targetBlock = e.target.closest('.le-block');
    if (!targetBlock) return;

    // Remove old indicators
    document.querySelectorAll('.le-drop-indicator').forEach(el => el.remove());

    const targetIdx = parseInt(targetBlock.dataset.idx, 10);
    const dropIdx = targetIdx; // always drop BEFORE target

    // Validate drop position for part/bar blocks
    if (_leDrag.type === 'part' || _leDrag.type === 'bar') {
      if (!leIsValidDrop(_leDrag.idx, dropIdx, _leDrag.type)) {
        e.dataTransfer.dropEffect = 'none';
        return;
      }
    }

    // Show indicator before target block
    const indicator = document.createElement('span');
    indicator.className = 'le-drop-indicator';
    targetBlock.parentNode.insertBefore(indicator, targetBlock);
  });

  // Drop
  canvas.addEventListener('drop', (e) => {
    e.preventDefault();
    document.querySelectorAll('.le-drop-indicator').forEach(el => el.remove());
    if (!_leDrag) return;

    const targetBlock = e.target.closest('.le-block');
    if (!targetBlock) return;

    const fromIdx = _leDrag.idx;
    const targetIdx = parseInt(targetBlock.dataset.idx, 10);
    let toIdx = targetIdx; // always drop BEFORE target

    // Validate
    if (_leDrag.type === 'part' || _leDrag.type === 'bar') {
      if (!leIsValidDrop(fromIdx, toIdx, _leDrag.type)) return;
    }

    // Move the block
    const [block] = _leBlocks.splice(fromIdx, 1);
    if (toIdx > fromIdx) toIdx--;
    _leBlocks.splice(toIdx, 0, block);

    _leDrag = null;
    markDirty();
    leRefreshCanvas();
  });

  // Touch-based drag for iPad
  let touchDrag = null;
  canvas.addEventListener('touchstart', (e) => {
    const block = e.target.closest('.le-block');
    if (!block) return;

    const touch = e.touches[0];
    touchDrag = {
      idx: parseInt(block.dataset.idx, 10),
      startX: touch.clientX,
      startY: touch.clientY,
      el: block,
      moved: false
    };
  }, { passive: true });

  canvas.addEventListener('touchmove', (e) => {
    if (!touchDrag) return;
    const touch = e.touches[0];
    const dx = Math.abs(touch.clientX - touchDrag.startX);
    const dy = Math.abs(touch.clientY - touchDrag.startY);
    if (dx > 10 || dy > 10) {
      touchDrag.moved = true;
      e.preventDefault();
      touchDrag.el.classList.add('le-dragging');

      // Find drop target
      const el = document.elementFromPoint(touch.clientX, touch.clientY);
      const targetBlock = el?.closest?.('.le-block');
      document.querySelectorAll('.le-drop-hover').forEach(el => el.classList.remove('le-drop-hover'));
      if (targetBlock && targetBlock !== touchDrag.el) {
        targetBlock.classList.add('le-drop-hover');
      }
    }
  }, { passive: false });

  canvas.addEventListener('touchend', (e) => {
    if (!touchDrag) return;

    if (touchDrag.moved) {
      touchDrag.el.classList.remove('le-dragging');
      document.querySelectorAll('.le-drop-hover').forEach(el => el.classList.remove('le-drop-hover'));

      // Find final drop position
      const touch = e.changedTouches[0];
      const el = document.elementFromPoint(touch.clientX, touch.clientY);
      const targetBlock = el?.closest?.('.le-block');

      if (targetBlock && targetBlock !== touchDrag.el) {
        const fromIdx = touchDrag.idx;
        const targetIdx = parseInt(targetBlock.dataset.idx, 10);
        const blockData = _leBlocks[fromIdx];
        let toIdx = targetIdx; // always drop BEFORE target

        if (blockData.type === 'part' || blockData.type === 'bar') {
          if (!leIsValidDrop(fromIdx, toIdx, blockData.type)) { touchDrag = null; return; }
        }

        const [block] = _leBlocks.splice(fromIdx, 1);
        if (toIdx > fromIdx) toIdx--;
        _leBlocks.splice(toIdx, 0, block);
        markDirty();
        leRefreshCanvas();
      }
    } else {
      // Tap (no drag) → context menu for words/bars
      const block = touchDrag.el;
      if (block.dataset.type === 'part') {
        e.preventDefault();
        } else if (block.dataset.type === 'word' || block.dataset.type === 'bar') {
        e.preventDefault();
        leShowContextMenu(parseInt(block.dataset.idx, 10), block);
      }
    }
    touchDrag = null;
  });

  // Click → context menu for words/bars (desktop)
  canvas.addEventListener('click', (e) => {
    leCloseContextMenu();
    const block = e.target.closest('.le-block');
    if (!block) return;
    if (block.dataset.type === 'word' || block.dataset.type === 'bar') {
      leShowContextMenu(parseInt(block.dataset.idx, 10), block);
    }
  });

  // Close context menu on outside click
  document.addEventListener('click', (e) => {
    if (_leContextMenu && !e.target.closest('.le-ctx-menu') && !e.target.closest('.le-block')) {
      leCloseContextMenu();
    }
  }, { once: false });
}

/**
 * Check if moving a bar block from fromIdx to toIdx is valid.
 * Bars can't cross their neighboring bars.
 */
function leIsValidDrop(fromIdx, toIdx, type) {
  if (fromIdx === toIdx || fromIdx + 1 === toIdx) return false; // no-op

  if (type === 'bar') {
    // Find previous and next bar blocks
    let prevBar = -1, nextBar = _leBlocks.length;
    for (let i = fromIdx - 1; i >= 0; i--) {
      if (_leBlocks[i].type === 'bar') { prevBar = i; break; }
    }
    for (let i = fromIdx + 1; i < _leBlocks.length; i++) {
      if (_leBlocks[i].type === 'bar') { nextBar = i; break; }
    }
    const effectiveToIdx = toIdx > fromIdx ? toIdx - 1 : toIdx;
    return effectiveToIdx > prevBar && effectiveToIdx < nextBar;
  }

  return true;
}

/* ── Context Menu for Blocks ──────────────────────── */

function leShowContextMenu(idx, blockEl) {
  leCloseContextMenu();
  const block = _leBlocks[idx];
  if (!block) return;

  const menu = document.createElement('div');
  menu.className = 'le-ctx-menu';

  if (block.type === 'word') {
    menu.innerHTML = `
      <button data-action="edit" class="le-ctx-item">&#9998; Editieren</button>
      <button data-action="duplicate" class="le-ctx-item">&#10697; Duplizieren</button>
      <button data-action="copy" class="le-ctx-item">&#128203; Kopieren</button>
      <button data-action="paste" class="le-ctx-item"${_leClipboard ? '' : ' disabled'}>&#128203; Einf&uuml;gen</button>
      <button data-action="delete" class="le-ctx-item le-ctx-delete">&#128465; L&ouml;schen</button>
      <button data-action="split" class="le-ctx-item">&#9986; Trennen</button>
      <button data-action="merge" class="le-ctx-item">&#128279; Zusammensetzen</button>
      <button data-action="insert" class="le-ctx-item">&#10133; Neues Wort</button>
    `;
  } else if (block.type === 'bar') {
    const nlLabel = block.newline ? '&#8629; Neue Zeile entfernen' : '&#8629; Neue Zeile';
    menu.innerHTML = `
      <button data-action="newline" class="le-ctx-item">${nlLabel}</button>
    `;
  } else {
    return;
  }

  // Position below the block — use offsetLeft/offsetTop (CSS-px, zoom-safe)
  const canvas = document.getElementById('le-canvas');
  menu.style.position = 'absolute';
  menu.style.left = `${blockEl.offsetLeft}px`;
  menu.style.top = `${blockEl.offsetTop + blockEl.offsetHeight + 4}px`;

  menu.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    leCloseContextMenu();
    leHandleContextAction(action, idx);
  });

  canvas.appendChild(menu);
  _leContextMenu = menu;
  blockEl.classList.add('le-block-selected');

  // Ensure menu is visible within canvas scroll area
  const menuBottom = blockEl.offsetTop + blockEl.offsetHeight + 4 + menu.offsetHeight;
  if (menuBottom > canvas.scrollTop + canvas.clientHeight) {
    canvas.scrollTop = menuBottom - canvas.clientHeight + 8;
  }
}

function leCloseContextMenu() {
  if (_leContextMenu) {
    _leContextMenu.remove();
    _leContextMenu = null;
  }
  document.querySelectorAll('.le-block-selected').forEach(el => el.classList.remove('le-block-selected'));
}

async function leHandleContextAction(action, idx) {
  const block = _leBlocks[idx];
  if (!block) return;

  if (action === 'edit') {
    const newVal = prompt(`Wort bearbeiten:`, block.content);
    if (newVal === null || !newVal.trim() || newVal.trim() === block.content) return;
    block.content = newVal.trim();
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'delete') {
    _leBlocks.splice(idx, 1);
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'split') {
    const word = block.content;
    const input = prompt(`Trennen mit Bindestrich (-) oder Leerzeichen in "${word}":`, word);
    if (!input || input === word) return;
    // Split by spaces first, then by hyphens (keeping hyphens attached)
    const tokens = [];
    input.split(/\s+/).filter(s => s.length > 0).forEach(chunk => {
      if (chunk.includes('-')) {
        const hParts = chunk.split('-').filter(s => s.length > 0);
        hParts.forEach((p, i) => tokens.push(i < hParts.length - 1 ? p + '-' : p));
      } else {
        tokens.push(chunk);
      }
    });
    if (tokens.length < 2) return;
    const newBlocks = tokens.map((t, i) => ({
      type: 'word',
      content: t,
      
      barNum: block.barNum,
      id: `lb_${Date.now()}_${i}`
    }));
    _leBlocks.splice(idx, 1, ...newBlocks);
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'merge') {
    // Merge with next word block
    let nextWordIdx = -1;
    for (let i = idx + 1; i < _leBlocks.length; i++) {
      if (_leBlocks[i].type === 'word') { nextWordIdx = i; break; }
      if (_leBlocks[i].type === 'bar' || _leBlocks[i].type === 'part') break; // don't cross structural blocks
    }
    if (nextWordIdx < 0) {
      toast('Kein Wort dahinter zum Zusammensetzen', 'warn');
      return;
    }
    block.content = block.content + ' ' + _leBlocks[nextWordIdx].content;
    _leBlocks.splice(nextWordIdx, 1);
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'duplicate') {
    const dup = {
      type: 'word',
      content: block.content,
      
      barNum: block.barNum,
      id: `lb_${Date.now()}_dup`
    };
    _leBlocks.splice(idx + 1, 0, dup);
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'copy') {
    _leClipboard = { content: block.content, barNum: block.barNum };
    toast('Wort kopiert: ' + block.content);
  }

  else if (action === 'paste') {
    if (!_leClipboard) { toast('Nichts kopiert', 'warn'); return; }
    const pasted = {
      type: 'word',
      content: _leClipboard.content,
      
      barNum: block.barNum,
      id: `lb_${Date.now()}_paste`
    };
    _leBlocks.splice(idx, 0, pasted);
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'insert') {
    const newWord = prompt('Neues Wort eingeben:');
    if (!newWord || !newWord.trim()) return;
    const words = newWord.trim().split(/\s+/);
    const newBlocks = words.map((w, i) => ({
      type: 'word',
      content: w,
      
      barNum: block.barNum,
      id: `lb_${Date.now()}_ins_${i}`
    }));
    _leBlocks.splice(idx + 1, 0, ...newBlocks);
    markDirty();
    leRefreshCanvas();
  }

  else if (action === 'newline') {
    // Toggle line break before this bar block
    block.newline = !block.newline;
    markDirty();
    leRefreshCanvas();
  }
}

/* ── Lyrics Editor: Save Logic ───────────────────── */

/**
 * Save lyrics from block positions back to bar DB entries.
 * Words between two bar blocks belong to the first bar.
 */
function leSaveLyrics() {
  if (!selectedSongId) return;
  ensureCollections();

  // First, clear all existing bar lyrics for this song
  for (const [, b] of Object.entries(db.bars)) {
    if (b.song_id === selectedSongId) b.lyrics = '';
  }

  // Walk through blocks, collect words per bar
  let currentBarNum = null;
  let currentWords = [];
  let filledBars = 0;

  function flushWords(nextBarHasNewline) {
    if (currentBarNum && currentWords.length > 0) {
      const [, barData] = getOrCreateBar(selectedSongId, currentBarNum);
      let text = currentWords.join(' ');
      // Persist newline: append \n to last word if next bar starts a new line
      if (nextBarHasNewline) text += '\n';
      barData.lyrics = text;
      filledBars++;
    }
    currentWords = [];
  }

  for (const block of _leBlocks) {
    if (block.type === 'bar') {
      flushWords(block.newline || false);

      currentBarNum = block.barNum;
    } else if (block.type === 'word') {
      currentWords.push(block.content);
    }
  }
  flushWords(false);

  // Also save lyrics_raw from all words in order
  const song = db.songs[selectedSongId];
  if (song) {
    const rawWords = [];
    for (const block of _leBlocks) {
      if (block.type === 'word') {
        rawWords.push(block.content + ' ');
      }
    }
    song.lyrics_raw = rawWords.join('').trim();
  }

  markDirty();
  handleSave(false);
  toast(`Lyrics f\u00fcr ${filledBars} Takte gespeichert`, 'success');
}

/* ── Lyrics Editor: Text Paste / Import ──────────── */

/**
 * Fetch lyrics from a URL via CORS proxy.
 * Supports Genius, AZLyrics, Musixmatch and generic extraction.
 */
/**
 * Fetch first song URL from Genius search API.
 * Returns the URL string or null.
 */
async function leGeniusFirstUrl(query) {
  const proxyUrl = 'https://api.allorigins.win/raw?url=' + encodeURIComponent(
    'https://genius.com/api/search?q=' + encodeURIComponent(query)
  );
  const resp = await fetch(proxyUrl);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  const hits = data?.response?.hits;
  if (hits && hits.length > 0) {
    return hits[0].result?.url || null;
  }
  return null;
}

async function leFetchLyricsFromUrl(url) {
  const proxyUrl = 'https://api.allorigins.win/raw?url=' + encodeURIComponent(url);
  const resp = await fetch(proxyUrl);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const html = await resp.text();
  const doc = new DOMParser().parseFromString(html, 'text/html');

  // Remove script/style tags
  doc.querySelectorAll('script, style, noscript').forEach(el => el.remove());

  let lines = [];

  // Genius: data-lyrics-container divs
  const geniusEls = doc.querySelectorAll('[data-lyrics-container="true"]');
  if (geniusEls.length > 0) {
    for (const el of geniusEls) {
      // Replace <br> with newlines before extracting text
      el.innerHTML = el.innerHTML.replace(/<br\s*\/?>/gi, '\n');
      const text = el.textContent.trim();
      if (text) lines.push(text);
    }
    return lines.join('\n');
  }

  // AZLyrics: div between comments
  const azDiv = doc.querySelector('.ringtone ~ div:not([class])');
  if (azDiv) {
    return azDiv.textContent.trim();
  }

  // Musixmatch: lyrics body
  const mxm = doc.querySelectorAll('[class*="Lyrics__Container"], .lyrics__content__ok, .mxm-lyrics span');
  if (mxm.length > 0) {
    for (const el of mxm) {
      const text = el.textContent.trim();
      if (text) lines.push(text);
    }
    return lines.join('\n');
  }

  // Generic fallback: look for common lyrics containers
  const fallbackSelectors = [
    '.lyrics', '.lyric-body', '.song-text', '[class*="lyric"]',
    '.entry-content', 'article', '.content'
  ];
  for (const sel of fallbackSelectors) {
    const el = doc.querySelector(sel);
    if (el && el.textContent.trim().length > 100) {
      return el.textContent.trim();
    }
  }

  // Last resort: largest text block in body
  const body = doc.querySelector('body');
  if (body) return body.textContent.trim().slice(0, 5000);
  throw new Error('Keine Lyrics gefunden');
}

async function leShowPasteDialog() {
  // Try to pre-fill from clipboard
  let clipText = '';
  try { clipText = await navigator.clipboard.readText(); } catch {}

  // Pre-fill from existing lyrics_raw if available
  const song = db.songs[selectedSongId];
  const existing = song ? (song.lyrics_raw || '') : '';
  const prefill = clipText || existing;

  const searchQ = encodeURIComponent(song.name + ' ' + song.artist);

  // Modal overlay
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal le-paste-modal">
      <div class="modal-header">
        <h3>Songtext einf&uuml;gen</h3>
        <button class="modal-close" id="le-paste-close">&times;</button>
      </div>
      <div class="le-paste-body">
        <p class="text-t2">Lyrics-URL eingeben oder Text manuell einf&uuml;gen. Abschnitts-Header wie [Verse], [Chorus] werden automatisch entfernt.</p>
        <div class="le-paste-links">
          <button class="btn btn-sm lyrics-genius-link" id="le-genius-auto" title="Ersten Genius-Treffer suchen &amp; Lyrics laden">&#127925; Genius Auto-Fetch</button>
          <a href="https://genius.com/search?q=${searchQ}" target="_blank" rel="noopener" class="btn btn-sm" title="Genius-Suche manuell &ouml;ffnen">&#128269; Genius</a>
          <a href="https://www.musixmatch.com/search/${searchQ}" target="_blank" rel="noopener" class="btn btn-sm lyrics-musix-link" title="Musixmatch-Suche manuell &ouml;ffnen">&#128269; Musixmatch</a>
        </div>
        <div class="le-url-row">
          <input type="url" id="le-url-input" class="le-url-input" placeholder="Lyrics-URL einf&uuml;gen (z.B. genius.com/...)" />
          <button class="btn btn-primary btn-sm" id="le-url-fetch">Lyrics holen</button>
        </div>
        <div id="le-url-status" class="le-url-status"></div>
        <textarea id="le-paste-textarea" class="le-paste-textarea" rows="15" placeholder="Songtext hier einf&uuml;gen...">${esc(prefill)}</textarea>
        <div class="le-paste-footer">
          <button class="btn" id="le-paste-cancel">Abbrechen</button>
          <button class="btn btn-primary" id="le-paste-apply">&Uuml;bernehmen &amp; verteilen</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const textarea = overlay.querySelector('#le-paste-textarea');
  const urlInput = overlay.querySelector('#le-url-input');
  const urlStatus = overlay.querySelector('#le-url-status');
  textarea.focus();
  // Select all if pre-filled from clipboard so user can easily replace
  if (clipText) textarea.select();

  // If clipboard contains a URL, put it in the URL field instead
  if (clipText && /^https?:\/\/.+/i.test(clipText.trim())) {
    textarea.value = existing;
    urlInput.value = clipText.trim();
    urlInput.focus();
  }

  // Fetch lyrics from URL
  const fetchFromUrl = async () => {
    const url = urlInput.value.trim();
    if (!url) { toast('Keine URL eingegeben', 'error'); return; }
    if (!/^https?:\/\//i.test(url)) { toast('Ung\u00fcltige URL', 'error'); return; }

    const fetchBtn = overlay.querySelector('#le-url-fetch');
    fetchBtn.disabled = true;
    fetchBtn.textContent = 'Laden...';
    urlStatus.textContent = 'Lyrics werden geladen...';
    urlStatus.className = 'le-url-status le-url-loading';

    try {
      const lyrics = await leFetchLyricsFromUrl(url);
      textarea.value = lyrics;
      urlStatus.textContent = 'Lyrics geladen!';
      urlStatus.className = 'le-url-status le-url-success';
    } catch (err) {
      urlStatus.textContent = 'Fehler: ' + err.message;
      urlStatus.className = 'le-url-status le-url-error';
    } finally {
      fetchBtn.disabled = false;
      fetchBtn.textContent = 'Lyrics holen';
    }
  };

  overlay.querySelector('#le-url-fetch').onclick = fetchFromUrl;
  urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') fetchFromUrl(); });

  // Genius Auto-Fetch: search → first result URL → fetch lyrics
  overlay.querySelector('#le-genius-auto').onclick = async () => {
    const autoBtn = overlay.querySelector('#le-genius-auto');
    autoBtn.disabled = true;
    autoBtn.textContent = 'Suche...';
    urlStatus.textContent = 'Genius wird durchsucht...';
    urlStatus.className = 'le-url-status le-url-loading';
    try {
      const gUrl = await leGeniusFirstUrl(song.name + ' ' + song.artist);
      if (!gUrl) throw new Error('Kein Treffer auf Genius');
      urlInput.value = gUrl;
      urlStatus.textContent = 'Treffer gefunden, lade Lyrics...';
      await fetchFromUrl();
    } catch (err) {
      urlStatus.textContent = 'Fehler: ' + err.message;
      urlStatus.className = 'le-url-status le-url-error';
    } finally {
      autoBtn.disabled = false;
      autoBtn.textContent = '\u{1F3B5} Genius Auto-Fetch';
    }
  };

  // Wire events
  const close = () => overlay.remove();
  overlay.querySelector('#le-paste-close').onclick = close;
  overlay.querySelector('#le-paste-cancel').onclick = close;
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

  overlay.querySelector('#le-paste-apply').onclick = () => {
    const text = textarea.value.trim();
    if (!text) { toast('Kein Text eingegeben', 'error'); return; }

    _leBlocks = leDistributeText(selectedSongId, text);
    if (song) song.lyrics_raw = text;
    markDirty();
    leRefreshCanvas();
    close();
    toast('Text auf Takte verteilt', 'success');
  };
}

/* ── Lyrics Editor: Clear Words ──────────────────── */

function leClearWords() {
  _leBlocks = _leBlocks.filter(b => b.type !== 'word');

  // Clear bar lyrics in DB
  ensureCollections();
  for (const [, b] of Object.entries(db.bars)) {
    if (b.song_id === selectedSongId) b.lyrics = '';
  }

  const song = db.songs[selectedSongId];
  if (song) song.lyrics_raw = '';

  markDirty();
  renderLyricsTab();
}

/* ── Lyrics Editor: Event Handlers ───────────────── */

function handleLyricsClick(e) {
  const btn = e.target.closest('button') || e.target.closest('a');
  if (!btn) return;
  const id = btn.id;

  if (id === 'le-paste-btn') leShowPasteDialog();
  else if (id === 'le-genius-quick') leGeniusQuickFetch();
  else if (id === 'le-save-lyrics') leSaveLyrics();
  else if (id === 'le-clear-words') {
    if (confirm('Alle W\u00f6rter entfernen?')) leClearWords();
  }
}

function handleLyricsChange(e) {
  // No-op for now
}

/**
 * Quick-fetch lyrics from Genius: search → first result → extract → distribute.
 */
async function leGeniusQuickFetch() {
  const song = db.songs[selectedSongId];
  if (!song) return;
  const btn = document.getElementById('le-genius-quick');
  if (btn) { btn.disabled = true; btn.textContent = 'Suche...'; }
  toast('Genius wird durchsucht...', 'info');
  try {
    const gUrl = await leGeniusFirstUrl(song.name + ' ' + song.artist);
    if (!gUrl) throw new Error('Kein Treffer auf Genius');
    toast('Treffer gefunden, lade Lyrics...', 'info');
    const lyrics = await leFetchLyricsFromUrl(gUrl);
    if (!lyrics || lyrics.length < 20) throw new Error('Keine Lyrics gefunden');
    _leBlocks = leDistributeText(selectedSongId, lyrics);
    song.lyrics_raw = lyrics;
    markDirty();
    leRefreshCanvas();
    toast('Lyrics von Genius geladen & verteilt', 'success');
  } catch (err) {
    toast('Genius: ' + err.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '\u{1F3B5} Genius Auto'; }
  }
}

function saveLyricsRawText() {
  // Compatibility stub
}

let _leHighlightRAF = null;
let _leHighlightBarNums = [];   // [{barNum, startTime, endTime}] relative to play start
let _leHighlightStart = 0;      // ac.currentTime when playback started
let _leHighlightMode = null;    // 'segment' | 'bars'


/* ══════════════════════════════════════════════════════
   ACCENTS TAB
   ══════════════════════════════════════════════════════ */

let _accentsSelectedBar = null;   // barNum

function renderAccentsTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Song aus der Liste links ausw&auml;hlen.</p></div>`;
    return;
  }

  const scrollEl = document.getElementById('accents-scroll');
  const prevScroll = scrollEl ? scrollEl.scrollTop : 0;

  const song = db.songs[selectedSongId];
  const bars = getBarsForSong(selectedSongId);
  ensureCollections();
  const totalBars = song.total_bars || 0;
  const allBarIds = new Set(bars.map(b => b.id));
  const totalAccents = Object.values(db.accents).filter(a => allBarIds.has(a.bar_id)).length;

  els.content.innerHTML = `
    <div class="accents-panel">
      <div class="accents-scroll" id="accents-scroll">
        ${buildSongHeader(song)}
        <div class="accents-legend">
          ${Object.entries(ACCENT_INFO).map(([k, v]) => `<span class="legend-item ${k}">${v}</span>`).join('')}
        </div>
        <div class="accents-bar-list" id="accents-bar-list">
          ${totalBars === 0 ? '<div class="empty-state"><p>Keine Takte vorhanden.</p></div>' : buildAccentsBarList(totalBars)}
        </div>
      </div>
      <div class="summary-bar">
        <span class="summary-item"><span class="summary-label">Takte</span><span class="mono">${totalBars}</span></span>
        <span class="summary-item"><span class="summary-label">Accents</span><span class="mono">${totalAccents}</span></span>
      </div>
    </div>`;

  const newScrollEl = document.getElementById('accents-scroll');
  if (newScrollEl && prevScroll) newScrollEl.scrollTop = prevScroll;
}

function buildAccentsBarList(totalBars) {
  let html = '<div class="acc-blocks">';
  for (let b = 1; b <= totalBars; b++) {
    const isBarSel = _accentsSelectedBar === b;
    const found = findBar(selectedSongId, b);
    const accCount = found ? getAccentsForBar(found[0]).length : 0;
    const hasAccents = accCount > 0;
    html += `<span class="acc-block${hasAccents ? ' has-acc' : ''}${isBarSel ? ' selected' : ''}" data-accent-bar="${b}">${b}</span>`;
  }
  html += '</div>';

  if (_accentsSelectedBar !== null && _accentsSelectedBar >= 1 && _accentsSelectedBar <= totalBars) {
    html += buildAccentsBarEditor(selectedSongId, _accentsSelectedBar);
  }
  return html;
}


function buildAccentsBarEditor(songId, barNum) {
  const [barId, barData] = getOrCreateBar(songId, barNum);
  const accents = getAccentsForBar(barId);
  const hasAudio = barData?.audio ? true : false;
  const isBarPlaying = _barPlayId === barId && _partPlayActive;

  const blocks = Array.from({ length: 16 }, (_, i) => {
    const pos = i + 1;
    const accent = accents.find(a => a.pos_16th === pos);
    const isBeat = (pos - 1) % 4 === 0;
    const typeClass = accent ? ` acc-16-${accent.type}` : '';
    const beatClass = isBeat ? ' acc-16-beat' : '';
    const label = BEAT_LABELS[i];
    const display = accent ? accent.type.toUpperCase() : label;
    return `<span class="acc-16${beatClass}${typeClass}" data-accent-pos16="${pos}">${display}</span>`;
  }).join('');

  return `
    <div class="acc-editor">
      <div class="acc-editor-head">
        <span class="acc-editor-title mono">Takt ${barNum}</span>
        ${barData.lyrics ? `<span class="acc-editor-lyrics text-t2">${esc(barData.lyrics)}</span>` : ''}
        ${hasAudio ? `<button class="btn-bar-play${isBarPlaying ? ' playing' : ''}" data-action="accent-play-bar" data-play-song-id="${songId}" data-play-bar-num="${barNum}" title="${isBarPlaying ? 'Stop' : 'Takt abspielen'}">${isBarPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}
      </div>
      <div class="acc-16-row">${blocks}</div>
    </div>`;
}

function handleAccentsTabClick(e) {
  const el = e.target;

  // Accent 16th-note block click
  const accentCell = el.closest('[data-accent-pos16]');
  if (accentCell && _accentsSelectedBar) {
    const pos = parseInt(accentCell.dataset.accentPos16, 10);
    handleAccentsTabToggle(selectedSongId, _accentsSelectedBar, pos);
    return;
  }

  // Play bar button
  const playBtn = el.closest('[data-action="accent-play-bar"]');
  if (playBtn) {
    handleAccentBarPlay(playBtn.dataset.playSongId || selectedSongId, parseInt(playBtn.dataset.playBarNum, 10));
    return;
  }

  // Select bar block
  const barBlock = el.closest('[data-accent-bar]');
  if (barBlock) {
    const barNum = parseInt(barBlock.dataset.accentBar, 10);
    _accentsSelectedBar = (_accentsSelectedBar === barNum) ? null : barNum;
    renderAccentsTab();
    return;
  }
}

async function handleAccentBarPlay(songId, barNum) {
  audio.warmup();
  ensureCollections();
  const found = findBar(songId, barNum);
  if (!found) return;
  const [barId, barData] = found;
  if (!barData.audio) return;

  if (_barPlayId === barId && _partPlayActive) {
    _barPlayId = null;
    renderAccentsTab();
    return;
  }

  _barPlayId = barId;
  _partPlayActive = true;
  renderAccentsTab();

  try {
    const ac = _getAudioCtx();
    if (ac.state === 'suspended') await ac.resume();
    const arrBuf = await fetchAudioUrl(barData.audio);
    if (!arrBuf) throw new Error(`Audio nicht gefunden: ${barData.audio}`);
    const decoded = await ac.decodeAudioData(arrBuf);
    const src = ac.createBufferSource();
    src.buffer = decoded;
    src.connect(ac.destination);
    src.onended = () => {
      if (_barPlayId === barId) { _barPlayId = null; _partPlayActive = false; renderAccentsTab(); }
    };
    src.start(0);
    _partPlaySources = [src];
    _partPlayBuffers = [decoded];
  } catch (err) {
    console.error('Bar playback error (accents):', err);
    toast(`Wiedergabe-Fehler: ${err.message}`, 'error');
    _barPlayId = null;
    renderAccentsTab();
  }
}

function handleAccentsTabToggle(songId, barNum, pos16) {
  const [barId] = getOrCreateBar(songId, barNum);
  ensureCollections();

  const existingId = Object.keys(db.accents).find(
    id => db.accents[id].bar_id === barId && db.accents[id].pos_16th === pos16
  );

  if (existingId) {
    const current = db.accents[existingId];
    const typeIdx = ACCENT_TYPES.indexOf(current.type);
    if (typeIdx < ACCENT_TYPES.length - 1) {
      current.type = ACCENT_TYPES[typeIdx + 1];
    } else {
      delete db.accents[existingId];
    }
  } else {
    const newId = nextId('A', db.accents);
    db.accents[newId] = { bar_id: barId, pos_16th: pos16, type: ACCENT_TYPES[0], notes: '' };
  }

  const [, barData] = getOrCreateBar(songId, barNum);
  barData.has_accents = getAccentsForBar(barId).length > 0;
  markDirty();
  renderAccentsTab();
}

/* ══════════════════════════════════════════════════════
   SETLIST TAB — Meilenstein 4
   ══════════════════════════════════════════════════════ */

function ensureSetlist() {
  if (!db.setlist) db.setlist = { name: 'Setlist', items: [] };
  if (!db.setlist.items) db.setlist.items = [];
}

function renderSetlistTab() {
  ensureSetlist();
  const sl = db.setlist;
  const items = sl.items || [];

  // Compute summary
  const songItems = items.filter(i => i.type === 'song');
  const pauseCount = items.filter(i => i.type === 'pause').length;
  const totalSec = songItems.reduce((sum, i) => {
    const s = db.songs[i.song_id];
    return sum + (s ? (s.duration_sec || 0) : 0);
  }, 0);
  const sets = pauseCount + 1;

  els.content.innerHTML = `
    <div class="setlist-panel">
      <div class="setlist-scroll" id="setlist-scroll">
        <div class="setlist-header">
          <input type="text" class="setlist-name-input" id="setlist-name" value="${esc(sl.name || 'Setlist')}" placeholder="Setlist-Name">
          <div class="setlist-actions">
            <button class="btn btn-sm" id="sl-add-song">+ SONG</button>
            <button class="btn btn-sm" id="sl-add-pause">+ PAUSE</button>
            <button class="btn btn-sm btn-primary" id="sl-export">EXPORT</button>
          </div>
        </div>
        <div class="setlist-items" id="setlist-items">
          ${buildSetlistItems(items)}
        </div>
      </div>
      <div class="summary-bar">
        <span class="summary-item"><span class="summary-label">Songs</span><span class="mono">${songItems.length}</span></span>
        <span class="summary-item"><span class="summary-label">Pausen</span><span class="mono">${pauseCount}</span></span>
        <span class="summary-item"><span class="summary-label">Sets</span><span class="mono">${sets}</span></span>
        <span class="summary-item"><span class="summary-label">Dauer</span><span class="mono">${fmtDur(totalSec)}</span></span>
      </div>
    </div>`;

  wireSetlistDragDrop();
}

function buildSetlistItems(items) {
  if (!items.length) {
    return '<div class="empty-state" style="padding:40px 0"><div class="icon">&#9835;</div><p>Noch keine Songs in der Setlist.</p></div>';
  }
  let setNum = 1;
  let songNum = 1;
  const parts = [];
  for (let idx = 0; idx < items.length; idx++) {
    const item = items[idx];
    if (item.type === 'pause') {
      parts.push(`<div class="setlist-card pause" data-idx="${idx}" draggable="true">
        <span class="sl-grip" title="Verschieben">&#8942;&#8942;</span>
        <span class="sl-pause-label">&#9646;&#9646; PAUSE &mdash; Set ${setNum} / Set ${setNum + 1}</span>
        <div class="sl-btns">
          <button class="sl-btn sl-remove" title="Entfernen" data-action="remove" data-idx="${idx}">&times;</button>
        </div>
      </div>`);
      setNum++;
      continue;
    }
    const song = db.songs[item.song_id];
    if (!song) continue;

    const dur = song.duration || fmtDur(song.duration_sec || 0);
    parts.push(`<div class="setlist-card" data-idx="${idx}" data-song-id="${item.song_id}" draggable="true">
      <span class="sl-grip" title="Verschieben">&#8942;&#8942;</span>
      <span class="sl-pos">${songNum}</span>
      <span class="sl-name">${esc(song.name)}</span>
      <span class="sl-artist">${esc(song.artist || '')}</span>
      <div class="sl-meta">
        <span>${song.bpm || '\u2014'} bpm</span>
        <span>${dur}</span>
      </div>
      <div class="sl-btns">
        <button class="sl-btn sl-edit" title="Im DB Editor anzeigen" data-action="edit" data-idx="${idx}">&#9998;</button>
        <button class="sl-btn sl-remove" title="Entfernen" data-action="remove" data-idx="${idx}">&times;</button>
      </div>
    </div>`);
    songNum++;
  }
  return parts.join('');
}

/* ── Setlist Drag & Drop (mouse + touch) ──────────── */

let _slDragIdx = null;
let _slDropIdx = null;
let _slDragEl = null;
let _slTouchClone = null;

function wireSetlistDragDrop() {
  const container = document.getElementById('setlist-items');
  if (!container) return;

  // Mouse drag
  container.addEventListener('dragstart', slDragStart);
  container.addEventListener('dragover', slDragOver);
  container.addEventListener('dragleave', slDragLeave);
  container.addEventListener('drop', slDrop);
  container.addEventListener('dragend', slDragEnd);

  // Touch drag
  container.addEventListener('touchstart', slTouchStart, { passive: false });
}

function slDragStart(e) {
  const card = e.target.closest('.setlist-card');
  if (!card || !e.target.closest('.sl-grip')) { e.preventDefault(); return; }
  _slDragIdx = parseInt(card.dataset.idx);
  _slDragEl = card;
  card.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', _slDragIdx);
}

function slDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  removeDropIndicators();
  const target = getDropTarget(e.clientY);
  if (target !== null && target !== _slDragIdx) {
    showDropIndicator(target);
    _slDropIdx = target;
  }
}

function slDragLeave(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) removeDropIndicators();
}

function slDrop(e) {
  e.preventDefault();
  removeDropIndicators();
  if (_slDragIdx !== null && _slDropIdx !== null && _slDragIdx !== _slDropIdx) {
    moveSetlistItem(_slDragIdx, _slDropIdx);
  }
  slDragEnd();
}

function slDragEnd() {
  if (_slDragEl) _slDragEl.classList.remove('dragging');
  _slDragIdx = null;
  _slDropIdx = null;
  _slDragEl = null;
  removeDropIndicators();
}

/* Touch drag support */
function slTouchStart(e) {
  const grip = e.target.closest('.sl-grip');
  if (!grip) return;
  const card = grip.closest('.setlist-card');
  if (!card) return;
  e.preventDefault();

  _slDragIdx = parseInt(card.dataset.idx);
  _slDragEl = card;
  card.classList.add('dragging');

  // Create a floating clone
  const rect = card.getBoundingClientRect();
  _slTouchClone = card.cloneNode(true);
  _slTouchClone.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;opacity:0.8;z-index:9999;pointer-events:none;`;
  document.body.appendChild(_slTouchClone);

  document.addEventListener('touchmove', slTouchMove, { passive: false });
  document.addEventListener('touchend', slTouchEnd);
}

function slTouchMove(e) {
  e.preventDefault();
  const touch = e.touches[0];
  if (_slTouchClone) {
    _slTouchClone.style.top = (touch.clientY - 20) + 'px';
  }
  removeDropIndicators();
  const target = getDropTarget(touch.clientY);
  if (target !== null && target !== _slDragIdx) {
    showDropIndicator(target);
    _slDropIdx = target;
  }
}

function slTouchEnd() {
  document.removeEventListener('touchmove', slTouchMove);
  document.removeEventListener('touchend', slTouchEnd);
  if (_slTouchClone) { _slTouchClone.remove(); _slTouchClone = null; }
  removeDropIndicators();
  if (_slDragIdx !== null && _slDropIdx !== null && _slDragIdx !== _slDropIdx) {
    moveSetlistItem(_slDragIdx, _slDropIdx);
  }
  slDragEnd();
}

function getDropTarget(clientY) {
  const container = document.getElementById('setlist-items');
  if (!container) return null;
  const cards = [...container.querySelectorAll('.setlist-card')];
  for (let i = 0; i < cards.length; i++) {
    const rect = cards[i].getBoundingClientRect();
    const mid = rect.top + rect.height / 2;
    if (clientY < mid) return i;
  }
  return cards.length; // After last item
}

function showDropIndicator(idx) {
  const container = document.getElementById('setlist-items');
  if (!container) return;
  const cards = [...container.querySelectorAll('.setlist-card')];
  const indicator = document.createElement('div');
  indicator.className = 'setlist-drop-indicator';
  if (idx < cards.length) {
    container.insertBefore(indicator, cards[idx]);
  } else {
    container.appendChild(indicator);
  }
}

function removeDropIndicators() {
  document.querySelectorAll('.setlist-drop-indicator').forEach(el => el.remove());
}

function moveSetlistItem(fromIdx, toIdx) {
  ensureSetlist();
  const items = db.setlist.items;
  if (fromIdx < 0 || fromIdx >= items.length) return;
  const [item] = items.splice(fromIdx, 1);
  const insertAt = toIdx > fromIdx ? toIdx - 1 : toIdx;
  items.splice(insertAt, 0, item);
  renumberSetlist();
  markDirty();
  renderSetlistTab();
}

function renumberSetlist() {
  ensureSetlist();
  let pos = 1;
  for (const item of db.setlist.items) {
    if (item.type === 'song') {
      item.pos = pos++;
    }
  }
}

/* ── Setlist Event Handlers ───────────────────────── */

function handleSetlistClick(e) {
  const el = e.target;

  // Add Song button
  if (el.closest('#sl-add-song')) {
    openSongSearchOverlay();
    return;
  }

  // Add Pause button
  if (el.closest('#sl-add-pause')) {
    ensureSetlist();
    db.setlist.items.push({ type: 'pause' });
    markDirty();
    renderSetlistTab();
    return;
  }

  // Export button
  if (el.closest('#sl-export')) {
    exportSetlist();
    return;
  }

  // Remove item
  const removeBtn = el.closest('[data-action="remove"]');
  if (removeBtn) {
    const idx = parseInt(removeBtn.dataset.idx);
    ensureSetlist();
    db.setlist.items.splice(idx, 1);
    renumberSetlist();
    markDirty();
    renderSetlistTab();
    return;
  }

  // Edit (jump to DB Editor)
  const editBtn = el.closest('[data-action="edit"]');
  if (editBtn) {
    const card = editBtn.closest('.setlist-card');
    const songId = card?.dataset.songId;
    if (songId && db.songs[songId]) {
      selectedSongId = songId;
      renderSongList(els.searchBox.value);
      switchTab('editor');
    }
    return;
  }
}

function handleSetlistChange(e) {
  const el = e.target;
  if (el.id === 'setlist-name') {
    ensureSetlist();
    db.setlist.name = el.value.trim() || 'Setlist';
    markDirty();
  }
}

/* ── Song Search Overlay ──────────────────────────── */

function openSongSearchOverlay() {
  // Create overlay if not present
  let overlay = document.getElementById('song-search-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'song-search-overlay';
    overlay.className = 'song-search-overlay';
    overlay.innerHTML = `
      <div class="song-search-panel">
        <div class="song-search-header">
          <input type="text" id="sl-song-search" class="search-box" placeholder="Song suchen...">
          <button class="icon-btn" id="sl-search-close" title="Schliessen">&#10005;</button>
        </div>
        <div class="song-search-list" id="sl-song-list"></div>
      </div>`;
    document.body.appendChild(overlay);

    // Close on overlay background click
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeSongSearchOverlay();
    });
    document.getElementById('sl-search-close').addEventListener('click', closeSongSearchOverlay);
    document.getElementById('sl-song-search').addEventListener('input', (e) => {
      renderSongSearchList(e.target.value);
    });
    document.getElementById('sl-song-list').addEventListener('click', (e) => {
      const item = e.target.closest('.song-search-item');
      if (!item) return;
      const songId = item.dataset.songId;
      if (songId) addSongToSetlist(songId);
    });
  }

  overlay.classList.add('open');
  const searchInput = document.getElementById('sl-song-search');
  searchInput.value = '';
  renderSongSearchList('');
  setTimeout(() => searchInput.focus(), 100);
}

function closeSongSearchOverlay() {
  const overlay = document.getElementById('song-search-overlay');
  if (overlay) overlay.classList.remove('open');
}

function renderSongSearchList(filter) {
  const list = document.getElementById('sl-song-list');
  if (!list) return;
  const songs = getSortedSongs();
  const q = filter.toLowerCase().trim();
  const filtered = q
    ? songs.filter(s => s.name.toLowerCase().includes(q) || (s.artist || '').toLowerCase().includes(q))
    : songs;

  const inSetlist = new Set((db.setlist?.items || []).filter(i => i.type === 'song').map(i => i.song_id));

  list.innerHTML = filtered.map(s => `
    <div class="song-search-item${inSetlist.has(s.id) ? ' in-setlist' : ''}" data-song-id="${s.id}">
      <div style="flex:1;min-width:0">
        <div class="ssi-name">${esc(s.name)}</div>
        <div class="ssi-artist">${esc(s.artist || '')}</div>
      </div>
      <span class="ssi-bpm">${s.bpm || ''}</span>
    </div>
  `).join('');
}

function addSongToSetlist(songId) {
  ensureSetlist();
  const items = db.setlist.items;
  items.push({ type: 'song', pos: items.filter(i => i.type === 'song').length + 1, song_id: songId });
  markDirty();
  // Update the search list (mark as in-setlist) and re-render setlist
  renderSongSearchList(document.getElementById('sl-song-search')?.value || '');
  renderSetlistTab();
  // Re-open overlay since renderSetlistTab redraws content
  const overlay = document.getElementById('song-search-overlay');
  if (overlay) overlay.classList.add('open');
}

/* ── Setlist Export ────────────────────────────────── */

function exportSetlist() {
  ensureSetlist();
  const sl = db.setlist;
  const items = sl.items || [];
  const band = db.band || 'The Pact';
  const date = new Date().toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });

  let setNum = 1;
  let songNum = 1;
  let totalSec = 0;

  let rows = '';
  for (const item of items) {
    if (item.type === 'pause') {
      rows += `<tr class="pause-row"><td colspan="5"><div class="pause-line">PAUSE &mdash; Ende Set ${setNum}</div></td></tr>\n`;
      setNum++;
      continue;
    }
    const song = db.songs[item.song_id];
    if (!song) continue;
    totalSec += song.duration_sec || 0;
    if (songNum === 1 || rows.includes('pause-row')) {
      // Set header (only on first row after a pause or at start)
    }
    rows += `<tr>
      <td class="nr">${songNum}</td>
      <td class="name">${esc(song.name)}</td>
      <td class="artist">${esc(song.artist || '')}</td>
      <td class="bpm">${song.bpm || ''}</td>
      <td class="dur">${song.duration || fmtDur(song.duration_sec || 0)}</td>
    </tr>\n`;
    songNum++;
  }

  const html = `<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>${esc(band)} &mdash; ${esc(sl.name || 'Setlist')}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Sora:wght@300;400;500;600&display=swap');
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Sora', sans-serif; font-size: 13px; color: #222; padding: 24px; max-width: 700px; margin: 0 auto; }
    h1 { font-size: 1.4rem; margin-bottom: 2px; }
    .subtitle { font-size: 0.85rem; color: #666; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: #999; padding: 6px 8px; border-bottom: 2px solid #333; }
    td { padding: 7px 8px; border-bottom: 1px solid #ddd; font-size: 0.9rem; }
    .nr { width: 30px; text-align: center; font-family: 'DM Mono', monospace; color: #999; }
    .name { font-weight: 500; }
    .artist { color: #666; }
    .bpm { width: 50px; text-align: center; font-family: 'DM Mono', monospace; color: #888; }
    .dur { width: 50px; text-align: right; font-family: 'DM Mono', monospace; color: #888; }
    .pause-row td { border-bottom: none; padding: 4px 0; }
    .pause-line { text-align: center; font-family: 'DM Mono', monospace; font-size: 0.75rem; font-weight: 500; letter-spacing: 0.1em; color: #999; border-top: 2px solid #333; border-bottom: 2px solid #333; padding: 6px 0; margin: 8px 0; }
    .footer { margin-top: 16px; font-family: 'DM Mono', monospace; font-size: 0.75rem; color: #999; display: flex; gap: 24px; }
    @media print {
      body { padding: 12px; font-size: 12px; }
      .no-print { display: none; }
      td { padding: 5px 6px; }
    }
  </style>
</head>
<body>
  <h1>${esc(band)}</h1>
  <div class="subtitle">${esc(sl.name || 'Setlist')} &mdash; ${date}</div>
  <table>
    <thead><tr><th>#</th><th>Song</th><th>Artist</th><th>BPM</th><th style="text-align:right">Dauer</th></tr></thead>
    <tbody>
      ${rows}
    </tbody>
  </table>
  <div class="footer">
    <span>${songNum - 1} Songs</span>
    <span>${setNum} Set${setNum > 1 ? 's' : ''}</span>
    <span>Gesamtdauer: ${fmtDur(totalSec)}</span>
  </div>
  <div class="no-print" style="margin-top:24px;text-align:center">
    <button onclick="window.print()" style="font-family:'Sora',sans-serif;padding:8px 24px;font-size:0.9rem;cursor:pointer;border:1px solid #ccc;border-radius:6px;background:#fff">Drucken / PDF</button>
  </div>
</body>
</html>`;

  const win = window.open('', '_blank');
  win.document.write(html);
  win.document.close();
}

/* ══════════════════════════════════════════════════════
   QLC+ QXW CHASER IMPORT
   ══════════════════════════════════════════════════════ */

/**
 * Parse a QLC+ QXW XML string and extract song chasers.
 * Returns Map<chaserName, steps[]> where each step = { note, functionId, functionName, holdMs, isTitle }
 */
function parseQxwChasers(xmlStr) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmlStr, 'text/xml');
  const engine = doc.querySelector('Engine');
  if (!engine) return new Map();

  // Pass 1: collect all function names by ID
  const funcNames = {};
  for (const fn of engine.querySelectorAll('Function')) {
    const id = parseInt(fn.getAttribute('ID') || '-1');
    funcNames[id] = fn.getAttribute('Name') || '';
  }

  // Pass 2: extract song chasers (Path="Pact Songs", Type="Chaser")
  const chasers = new Map();
  for (const fn of engine.querySelectorAll('Function')) {
    if (fn.getAttribute('Type') !== 'Chaser') continue;
    if (fn.getAttribute('Path') !== 'Pact Songs') continue;
    const name = fn.getAttribute('Name') || '';
    const steps = [];
    for (const step of fn.querySelectorAll('Step')) {
      const funcId = parseInt((step.textContent || '').trim()) || 0;
      const hold = parseInt(step.getAttribute('Hold') || '0');
      const note = step.getAttribute('Note') || '';
      const isTitle = funcId === QXW_STOP_ID && hold === QXW_INFINITE_HOLD;
      // Resolve function name: prefer BASE_COLLECTIONS mapping, then funcNames
      const functionName = QXW_BASE_COLLECTIONS[funcId] || funcNames[funcId] || `ID ${funcId}`;
      steps.push({ note, functionId: funcId, functionName, holdMs: hold, isTitle, isManual: hold === QXW_INFINITE_HOLD });
    }
    if (steps.length > 0) chasers.set(name, steps);
  }
  return chasers;
}

/** Normalize a string for fuzzy matching */
function _qxwNormalize(text) {
  return text.toLowerCase().replace(/[\u2018\u2019\u201A\u201B`\u00B4]/g, "'").replace(/\s+/g, ' ').trim();
}

/** Find the chaser for a given song in the QXW data */
function findChaserForSong(chasers, songName) {
  if (!songName) return null;
  const norm = _qxwNormalize(songName);
  // Direct match
  for (const [name, steps] of chasers) {
    if (_qxwNormalize(name) === norm) return { chaserName: name, steps };
  }
  // Substring match
  let best = null, bestLen = 0;
  for (const [name, steps] of chasers) {
    const nName = _qxwNormalize(name);
    if (nName.includes(norm) || norm.includes(nName)) {
      if (nName.length > bestLen) { best = { chaserName: name, steps }; bestLen = nName.length; }
    }
  }
  return best;
}

/** Try to match a chaser step note to a part name */
function matchStepToPart(stepNote, parts) {
  if (!stepNote) return null;
  const normNote = _qxwNormalize(stepNote);
  // Exact match
  for (const p of parts) {
    if (_qxwNormalize(p.name) === normNote) return p;
  }
  // Base name match (strip trailing numbers and parenthetical)
  const noteBase = normNote.replace(/\s*(\(.*?\)\s*|\d+\s*)*$/, '').trim();
  if (!noteBase) return null;
  for (const p of parts) {
    const partBase = _qxwNormalize(p.name).replace(/\s*(\(.*?\)\s*|\d+\s*)*$/, '').trim();
    if (partBase === noteBase) return p;
  }
  return null;
}

/** Load QXW from GitHub and cache it */
async function loadQxwFile() {
  if (_qxwCache) return _qxwCache.chasers;
  const s = getSettings();
  if (!s.repo || !s.token) {
    toast('GitHub nicht konfiguriert', 'error');
    return null;
  }
  // Try both QXW files, prefer lightingAI.qxw
  for (const path of ['db/lightingAI.qxw', 'db/ThePact.qxw']) {
    try {
      const url = `https://api.github.com/repos/${s.repo}/contents/${path}`;
      const res = await fetch(url, { headers: { Authorization: `token ${s.token}`, Accept: 'application/vnd.github.v3+json' } });
      if (!res.ok) continue;
      const json = await res.json();
      let xmlStr;
      if (json.content) {
        // Small file: decode Base64 content with proper UTF-8 handling
        const binary = atob(json.content.replace(/\n/g, ''));
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        xmlStr = new TextDecoder('utf-8').decode(bytes);
      } else if (json.download_url) {
        // Large file (>1MB): GitHub returns content:null, use download_url instead
        const dlRes = await fetch(json.download_url);
        if (!dlRes.ok) { console.warn(`Download failed for ${path}: ${dlRes.status}`); continue; }
        xmlStr = await dlRes.text();
      } else {
        console.warn(`No content or download_url for ${path}`);
        continue;
      }
      const chasers = parseQxwChasers(xmlStr);
      _qxwCache = { xml: xmlStr, chasers };
      return chasers;
    } catch (e) {
      console.warn(`Failed to load ${path}:`, e);
      toast(`QXW Ladefehler (${path}): ${e.message}`, 'error', 5000);
    }
  }
  toast('Keine QXW-Datei gefunden im Repo (db/lightingAI.qxw)', 'error');
  return null;
}

/** Open the QLC+ Chaser Import modal for the current song */
async function openChaserModal(songId) {
  if (!songId || !db?.songs[songId]) return;
  const song = db.songs[songId];
  const parts = [];
  if (parts.length === 0) { toast('Keine Parts vorhanden', 'error'); return; }

  toast('QXW wird geladen...', 'info', 2000);
  const chasers = await loadQxwFile();
  if (!chasers) return;

  const match = findChaserForSong(chasers, song.name);
  if (!match) {
    const available = [...chasers.keys()].sort().join(', ');
    console.warn(`Kein Chaser fuer "${song.name}". Verfuegbare Chaser:`, available);
    toast(`Kein Chaser fuer "${song.name}" in der QXW gefunden (${chasers.size} Chaser geladen)`, 'error', 6000);
    // Debug: show available chasers in a second toast
    setTimeout(() => toast(`Verfuegbar: ${available.substring(0, 300)}`, 'info', 10000), 500);
    return;
  }

  // Filter out title/end steps and pure "11 Stop" transitions without a note
  const chaserSteps = match.steps.filter(s => !s.isTitle && !(s.functionId === QXW_STOP_ID && !s.note));

  // Save chaser steps as qlc_parts on the song (import suggestions)
  saveQlcParts(songId, chaserSteps);

  closeChaserModal();
  const overlay = document.createElement('div');
  overlay.className = 'tms-modal-overlay';
  overlay.id = 'chaser-modal-overlay';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeChaserModal(); });
  document.body.appendChild(overlay);

  const modal = document.createElement('div');
  modal.className = 'tms-modal chaser-modal';
  modal.id = 'chaser-modal';
  document.body.appendChild(modal);

  renderChaserModalContent(modal, songId, match.chaserName, chaserSteps, parts);
}

function closeChaserModal() {
  document.getElementById('chaser-modal')?.remove();
  document.getElementById('chaser-modal-overlay')?.remove();
  document.getElementById('chaser-assign-modal')?.remove();
  document.getElementById('chaser-assign-overlay')?.remove();
}

function renderChaserModalContent(modal, songId, chaserName, steps, parts) {
  // Pre-match each step
  const stepMatches = steps.map(s => {
    const matched = matchStepToPart(s.note, parts);
    return { ...s, matchedPart: matched, assigned: false };
  });

  const fmtHold = (ms) => {
    if (ms === QXW_INFINITE_HOLD) return 'MANUAL';
    if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`;
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms}ms`;
  };

  modal.innerHTML = `
    <div class="tms-header">
      <div class="tms-header-info" style="flex:1">
        <div class="tms-title">QLC+ Chaser: ${esc(chaserName)}</div>
        <div class="tms-next text-t2">${steps.length} Cues &mdash; Tippe auf einen Cue zum Uebernehmen</div>
      </div>
      <button class="btn btn-sm btn-primary" id="chaser-batch-btn" title="Alle matchenden Cues auf einmal uebernehmen">BATCH</button>
      <button class="btn btn-sm tms-close-btn" title="Schliessen">&times;</button>
    </div>
    <div class="tms-body">
      <div class="chaser-step-list">
        ${stepMatches.map((s, idx) => {
          const matchInfo = s.matchedPart
            ? `<span class="chaser-match text-green" title="Matched: ${esc(s.matchedPart.name)}">&#10003; ${esc(s.matchedPart.name)}</span>`
            : (s.note ? `<span class="chaser-match text-amber" title="Kein Part-Match">&#63; kein Match</span>` : `<span class="chaser-match text-t4">kein Part</span>`);
          return `
          <div class="chaser-step-item" data-chaser-idx="${idx}">
            <span class="chaser-step-num mono text-t3">${idx + 1}</span>
            <div class="chaser-step-info">
              <div class="chaser-step-note">${s.note ? esc(s.note) : '<span class="text-t4">(kein Name)</span>'}</div>
              <div class="chaser-step-func text-t2">${esc(s.functionName)}</div>
            </div>
            <span class="chaser-step-hold mono text-t3">${fmtHold(s.holdMs)}</span>
            ${matchInfo}
          </div>`;
        }).join('')}
      </div>
    </div>`;

  // Store step data on the modal for access
  modal._chaserData = { songId, steps: stepMatches, parts, chaserName };

  // Event handlers
  modal.addEventListener('click', (e) => {
    if (e.target.closest('.tms-close-btn')) { closeChaserModal(); return; }

    // Batch button
    if (e.target.closest('#chaser-batch-btn')) {
      handleChaserBatch(modal);
      return;
    }

    // Single step click
    const stepEl = e.target.closest('[data-chaser-idx]');
    if (stepEl) {
      const idx = parseInt(stepEl.dataset.chaserIdx);
      handleChaserStepClick(modal, idx);
    }
  });
}

function handleChaserStepClick(modal, idx) {
  const data = modal._chaserData;
  if (!data) return;
  const step = data.steps[idx];
  if (!step) return;

  if (step.matchedPart) {
    // Auto-assign
    applyChaserTemplate(data.songId, step.matchedPart.id, step.functionName);
    step.assigned = true;
    renderChaserModalContent(modal, data.songId, data.chaserName, data.steps, data.parts);
    toast(`"${step.functionName}" &#8594; ${step.matchedPart.name}`, 'success', 2000);
  } else if (step.note) {
    // Open part picker
    openPartAssignDialog(modal, idx);
  }
}

function handleChaserBatch(modal) {
  const data = modal._chaserData;
  if (!data) return;
  let assigned = 0;
  const unmatched = [];
  for (const step of data.steps) {
    if (step.matchedPart && !step.assigned) {
      applyChaserTemplate(data.songId, step.matchedPart.id, step.functionName);
      step.assigned = true;
      assigned++;
    } else if (step.note && !step.matchedPart) {
      unmatched.push(step);
    }
  }

  if (assigned > 0) {
    renderChaserModalContent(modal, data.songId, data.chaserName, data.steps, data.parts);
    toast(`${assigned} Templates uebernommen`, 'success', 2000);
  }

  if (unmatched.length > 0) {
    // Open assignment dialog for unmatched steps
    openBatchAssignDialog(modal, unmatched);
  } else if (assigned === 0) {
    toast('Keine neuen Zuordnungen moeglich', 'info', 2000);
  }
}

function applyChaserTemplate(songId, partId, templateName) {
  // Parts concept removed - this function is a no-op
  return;
}

/** Open a dialog to manually assign a chaser step to a part */
function openPartAssignDialog(chaserModal, stepIdx) {
  const data = chaserModal._chaserData;
  const step = data.steps[stepIdx];

  document.getElementById('chaser-assign-modal')?.remove();
  document.getElementById('chaser-assign-overlay')?.remove();

  const overlay = document.createElement('div');
  overlay.className = 'tms-modal-overlay';
  overlay.id = 'chaser-assign-overlay';
  overlay.style.zIndex = '9010';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); assignModal.remove(); } });
  document.body.appendChild(overlay);

  const assignModal = document.createElement('div');
  assignModal.className = 'tms-modal chaser-assign-modal';
  assignModal.id = 'chaser-assign-modal';
  assignModal.style.zIndex = '9011';
  assignModal.innerHTML = `
    <div class="tms-header">
      <div class="tms-header-info" style="flex:1">
        <div class="tms-title">Part zuordnen</div>
        <div class="tms-next text-t2">"${esc(step.note)}" &#8594; ${esc(step.functionName)}</div>
      </div>
      <button class="btn btn-sm tms-close-btn" title="Abbrechen">&times;</button>
    </div>
    <div class="tms-body">
      ${data.parts.map(p => `
        <div class="chaser-assign-part" data-assign-part="${p.id}">
          <span class="chaser-step-num mono text-t3">${p.pos}</span>
          <span>${esc(p.name)}</span>
          <span class="text-t3 mono" style="margin-left:auto">${p.light_template || '\u2014'}</span>
        </div>
      `).join('')}
    </div>`;
  document.body.appendChild(assignModal);

  assignModal.addEventListener('click', (e) => {
    if (e.target.closest('.tms-close-btn')) { overlay.remove(); assignModal.remove(); return; }
    const partEl = e.target.closest('[data-assign-part]');
    if (partEl) {
      const partId = partEl.dataset.assignPart;
      const part = data.parts.find(p => p.id === partId);
      if (part) {
        applyChaserTemplate(data.songId, partId, step.functionName);
        step.matchedPart = part;
        step.assigned = true;
        overlay.remove();
        assignModal.remove();
        renderChaserModalContent(chaserModal, data.songId, data.chaserName, data.steps, data.parts);
            toast(`"${step.functionName}" &#8594; ${part.name}`, 'success', 2000);
      }
    }
  });
}

/** Open a batch assignment dialog for all unmatched steps */
function openBatchAssignDialog(chaserModal, unmatchedSteps) {
  if (unmatchedSteps.length === 0) return;
  // Process one at a time — open dialog for first unmatched
  const step = unmatchedSteps[0];
  const idx = chaserModal._chaserData.steps.indexOf(step);
  if (idx >= 0) openPartAssignDialog(chaserModal, idx);
}

/* ══════════════════════════════════════════════════════
   QLC PARTS IMPORT (Drag & Drop)
   ══════════════════════════════════════════════════════ */

/**
 * Save QLC+ chaser steps as qlc_parts on the song.
 * These serve as import suggestions (name + light_template).
 */
function saveQlcParts(songId, chaserSteps) {
  const song = db.songs[songId];
  if (!song) return;
  const qlcParts = {};
  let pos = 0;
  for (const step of chaserSteps) {
    if (!step.note) continue; // skip unnamed steps
    pos++;
    const qpId = `${songId}_QP${String(pos).padStart(3, '0')}`;
    qlcParts[qpId] = {
      pos,
      name: step.note,
      light_template: step.functionName,
      notes: ''
    };
  }
  if (Object.keys(qlcParts).length > 0) {
    song.qlc_parts = qlcParts;
    markDirty();
  }
}

/** Get sorted qlc_parts for a song */
function getSortedQlcParts(songId) {
  const song = db.songs[songId];
  if (!song?.qlc_parts) return [];
  return Object.entries(song.qlc_parts)
    .map(([id, qp]) => ({ id, ...qp }))
    .sort((a, b) => a.pos - b.pos);
}

/** Open the QLC Parts Import modal (drag & drop assignment) */
function openQlcPartsImportModal(songId) {
  if (!songId || !db?.songs[songId]) return;
  const song = db.songs[songId];
  const qlcParts = getSortedQlcParts(songId);
  const realParts = [];

  if (qlcParts.length === 0) { toast('Keine QLC Parts vorhanden — erst QLC+ Import durchfuehren', 'error'); return; }
  if (realParts.length === 0) { toast('Keine Parts vorhanden', 'error'); return; }

  closeQlcPartsImportModal();

  const overlay = document.createElement('div');
  overlay.className = 'tms-modal-overlay';
  overlay.id = 'qlc-import-overlay';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeQlcPartsImportModal(); });
  document.body.appendChild(overlay);

  const modal = document.createElement('div');
  modal.className = 'tms-modal qlc-import-modal';
  modal.id = 'qlc-import-modal';
  document.body.appendChild(modal);

  renderQlcImportContent(modal, songId);
}

function closeQlcPartsImportModal() {
  document.getElementById('qlc-import-modal')?.remove();
  document.getElementById('qlc-import-overlay')?.remove();
}

function renderQlcImportContent(modal, songId) {
  const song = db.songs[songId];
  const qlcParts = getSortedQlcParts(songId);
  const realParts = [];

  // Track which qlc_parts are already assigned (matched by name+template to a real part)
  const assignedQpIds = new Set();
  for (const qp of qlcParts) {
    for (const rp of realParts) {
      if (rp.light_template === qp.light_template && rp.name === qp.name) {
        assignedQpIds.add(qp.id);
        break;
      }
    }
  }

  const hasBuf = !!audio.getBuffer();

  modal.innerHTML = `
    <div class="tms-header">
      <div class="tms-header-info" style="flex:1">
        <div class="tms-title">Parts importieren</div>
        <div class="tms-next text-t2">${esc(song.name)} — QLC-Vorlagen auf Parts ziehen</div>
      </div>
      <button class="btn btn-sm tms-close-btn" title="Schliessen">&times;</button>
    </div>
    <div class="tms-body qlc-import-body">
      <div class="qlc-import-section">
        <div class="qlc-import-label text-t3">QLC+ Vorlagen <span class="mono">(${qlcParts.length})</span></div>
        <div class="qlc-chip-pool" id="qlc-chip-pool">
          ${qlcParts.map(qp => `
            <span class="qlc-chip${assignedQpIds.has(qp.id) ? ' qlc-chip-used' : ''}" draggable="true" data-qp-id="${qp.id}" title="${esc(qp.light_template)}">
              <span class="qlc-chip-name">${esc(qp.name)}</span>
              <span class="qlc-chip-tmpl text-t3">${esc(qp.light_template)}</span>
              ${assignedQpIds.has(qp.id) ? '<span class="qlc-chip-check text-green">&#10003;</span>' : ''}
            </span>
          `).join('')}
        </div>
      </div>
      <div class="qlc-import-section">
        <div class="qlc-import-label text-t3">Parts <span class="mono">(${realParts.length})</span></div>
        <div class="qlc-parts-list" id="qlc-parts-list">
          ${realParts.map((rp, idx) => {
            const canPlay = hasBuf || false;
            const isPlaying = _partPlayActive && false;
            return `
            <div class="qlc-part-row" data-part-id="${rp.id}" data-song-id="${songId}">
              <span class="qlc-part-num mono text-t3">${rp.pos}</span>
              ${canPlay ? `<button class="btn-part-play${isPlaying ? ' playing' : ''}" data-action="play-part" data-part-id="${rp.id}" title="${isPlaying ? 'Stop' : 'Anhoeren'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>` : '<span class="qlc-part-no-play"></span>'}
              <span class="qlc-part-name">${esc(rp.name)}</span>
              <span class="qlc-part-bars mono text-t3">${rp.bars || 0} T</span>
              <span class="qlc-part-tmpl mono${rp.light_template ? ' text-green' : ' text-t4'}">${rp.light_template || '\u2014'}</span>
              <span class="qlc-drop-zone" data-drop-part="${rp.id}">&#8592; hierher ziehen</span>
            </div>`;
          }).join('')}
        </div>
      </div>
    </div>`;

  // Store data on modal
  modal._qlcData = { songId, qlcParts, realParts };

  // Wire events
  wireQlcImportEvents(modal);
}

function wireQlcImportEvents(modal) {
  const data = modal._qlcData;

  // Close button
  modal.addEventListener('click', (e) => {
    if (e.target.closest('.tms-close-btn')) { closeQlcPartsImportModal(); return; }

    // Play button
    const playBtn = e.target.closest('[data-action="play-part"]');
    if (playBtn) {
      // Update play buttons in modal
      setTimeout(() => updateQlcImportPlayState(), 50);
      return;
    }
  });

  // Desktop Drag & Drop (HTML5)
  const chipPool = modal.querySelector('#qlc-chip-pool');
  const partsList = modal.querySelector('#qlc-parts-list');

  let dragQpId = null;

  chipPool.addEventListener('dragstart', (e) => {
    const chip = e.target.closest('.qlc-chip');
    if (!chip || chip.classList.contains('qlc-chip-used')) { e.preventDefault(); return; }
    dragQpId = chip.dataset.qpId;
    chip.classList.add('qlc-chip-dragging');
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('text/plain', dragQpId);
  });

  chipPool.addEventListener('dragend', (e) => {
    modal.querySelectorAll('.qlc-chip-dragging').forEach(el => el.classList.remove('qlc-chip-dragging'));
    modal.querySelectorAll('.qlc-part-row.qlc-drop-hover').forEach(el => el.classList.remove('qlc-drop-hover'));
    dragQpId = null;
  });

  partsList.addEventListener('dragover', (e) => {
    if (!dragQpId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    const row = e.target.closest('.qlc-part-row');
    modal.querySelectorAll('.qlc-part-row.qlc-drop-hover').forEach(el => el.classList.remove('qlc-drop-hover'));
    if (row) row.classList.add('qlc-drop-hover');
  });

  partsList.addEventListener('dragleave', (e) => {
    if (!e.relatedTarget?.closest?.('.qlc-part-row')) {
      modal.querySelectorAll('.qlc-part-row.qlc-drop-hover').forEach(el => el.classList.remove('qlc-drop-hover'));
    }
  });

  partsList.addEventListener('drop', (e) => {
    e.preventDefault();
    modal.querySelectorAll('.qlc-part-row.qlc-drop-hover').forEach(el => el.classList.remove('qlc-drop-hover'));
    const qpId = e.dataTransfer.getData('text/plain') || dragQpId;
    if (!qpId) return;
    const row = e.target.closest('.qlc-part-row');
    if (!row) return;
  });

  // Touch Drag & Drop (iPad)
  let touchDrag = null;

  chipPool.addEventListener('touchstart', (e) => {
    const chip = e.target.closest('.qlc-chip');
    if (!chip || chip.classList.contains('qlc-chip-used')) return;
    const touch = e.touches[0];
    touchDrag = {
      qpId: chip.dataset.qpId,
      el: chip,
      startX: touch.clientX,
      startY: touch.clientY,
      moved: false,
      ghost: null
    };
  }, { passive: true });

  modal.addEventListener('touchmove', (e) => {
    if (!touchDrag) return;
    const touch = e.touches[0];
    const dx = Math.abs(touch.clientX - touchDrag.startX);
    const dy = Math.abs(touch.clientY - touchDrag.startY);
    if (dx > 10 || dy > 10) {
      touchDrag.moved = true;
      e.preventDefault();
      touchDrag.el.classList.add('qlc-chip-dragging');

      // Create/move ghost element
      if (!touchDrag.ghost) {
        const ghost = touchDrag.el.cloneNode(true);
        ghost.className = 'qlc-chip qlc-chip-ghost';
        document.body.appendChild(ghost);
        touchDrag.ghost = ghost;
      }
      touchDrag.ghost.style.left = (touch.clientX - 40) + 'px';
      touchDrag.ghost.style.top = (touch.clientY - 20) + 'px';

      // Highlight drop target
      const el = document.elementFromPoint(touch.clientX, touch.clientY);
      const row = el?.closest?.('.qlc-part-row');
      modal.querySelectorAll('.qlc-part-row.qlc-drop-hover').forEach(r => r.classList.remove('qlc-drop-hover'));
      if (row) row.classList.add('qlc-drop-hover');
    }
  }, { passive: false });

  modal.addEventListener('touchend', (e) => {
    if (!touchDrag) return;
    touchDrag.el.classList.remove('qlc-chip-dragging');
    modal.querySelectorAll('.qlc-part-row.qlc-drop-hover').forEach(r => r.classList.remove('qlc-drop-hover'));
    if (touchDrag.ghost) { touchDrag.ghost.remove(); touchDrag.ghost = null; }

    if (touchDrag.moved) {
      const touch = e.changedTouches[0];
      const el = document.elementFromPoint(touch.clientX, touch.clientY);
      const row = el?.closest?.('.qlc-part-row');
      if (row) {
          }
    }
    touchDrag = null;
  });
}

/**
 * Apply a qlc_part's name + light_template to a real part.
 */
function applyQlcPartToReal(modal, qpId, realPartId) {
  // Parts concept removed - this function is a no-op
  return;
}

/** Update play button states inside QLC import modal */
function updateQlcImportPlayState() {
  const modal = document.getElementById('qlc-import-modal');
  if (!modal) return;
  modal.querySelectorAll('[data-action="play-part"]').forEach(btn => {
    const isPlaying = false;
    btn.innerHTML = isPlaying ? '&#9632;' : '&#9654;';
    btn.title = isPlaying ? 'Stop' : 'Anhoeren';
    btn.classList.toggle('playing', isPlaying);
  });
}

/* ══════════════════════════════════════════════════════
   TAKTE TAB
   ══════════════════════════════════════════════════════ */

function getAllBarsFlat() {
  if (!db || !db.songs) return [];
  ensureCollections();
  const rows = [];

  for (const [songId, song] of Object.entries(db.songs)) {
    const totalBars = song.total_bars || 0;
    const songBars = getBarsForSong(songId);
    const bpm = song.bpm || 0;
    for (let n = 0; n < totalBars; n++) {
      const absBar = n + 1;
      const barEntry = songBars[n] || null;
      const barData = barEntry || {};
      const barId = barEntry ? barEntry.id : null;
      const accCount = barId ? getAccentsForBar(barId).length : 0;
      const barSec = bpm > 0 ? n * 4 * 60 / bpm : 0;
      rows.push({
        songId, songName: song.name, bpm,
        barNum: absBar, absBar, barSec,
        lyrics: barData.lyrics || '',
        audio: barData.audio || '',
        accCount, barId
      });
    }
  }
  return rows;
}

function renderTakteTab() {
  const filterSong = selectedSongId;
  ensureCollections();

  // Reconcile bar data before rendering
  if (filterSong) reconcileBars(filterSong);

  // Auto-load reference audio if available and not yet loaded (skip during bar playback)
  if (filterSong && !_partPlayActive) {
    const s = db.songs[filterSong];
    if (s && !audio.getBuffer() && s.audio_ref && _refLoadingFor !== filterSong) {
      _refLoadingFor = filterSong;
      _refLoadingPromise = loadReferenceAudio().finally(() => { _refLoadingFor = null; _refLoadingPromise = null; });
    }
  }

  let allBars;
  if (filterSong) {
    allBars = getAllBarsFlat().filter(b => b.songId === filterSong);
  } else {
    allBars = getAllBarsFlat();
    allBars.sort((a, b) => a.songName.localeCompare(b.songName, 'de') || a.absBar - b.absBar);
  }

  const sel = takteTabSelectedBar;
  const uniqueSongs = new Set(allBars.map(b => b.songId)).size;
  const withLyrics = allBars.filter(b => b.lyrics).length;
  const withAccents = allBars.filter(b => b.accCount > 0).length;

  const songLabel = filterSong ? esc(db.songs[filterSong]?.name || '') : 'alle Songs';

  els.content.innerHTML = `
    <div class="takte-tab-panel">
      <div class="takte-tab-scroll" id="takte-tab-scroll">
        ${allBars.length > 0 ? `<div class="takte-toolbar"><button class="btn btn-small btn-danger" id="btn-delete-all-bars" title="Alle Takte l\u00f6schen">Alle Takte l\u00f6schen</button></div>` : ''}
        ${allBars.length === 0
          ? '<div class="empty-state" style="padding:60px 0"><div class="icon">&#9881;</div><p>Keine Takte gefunden.</p></div>'
          : buildTakteTabTable(allBars, filterSong)}
        <div id="tt-editor-area"></div>
      </div>
      <div class="summary-bar">
        <span class="summary-item"><span class="summary-label">Songs</span><span class="mono">${uniqueSongs}</span></span>
        <span class="summary-item"><span class="summary-label">Takte</span><span class="mono">${allBars.length}</span></span>
        <span class="summary-item"><span class="summary-label">mit Lyrics</span><span class="mono">${withLyrics}</span></span>
        <span class="summary-item"><span class="summary-label">mit Accents</span><span class="mono">${withAccents}</span></span>
      </div>
    </div>`;

  renderTakteEditorSection();

  // Draw mini waveforms after DOM is ready
  requestAnimationFrame(() => renderMiniWaveforms());
}

/**
 * Get the time range of a bar from bar markers (for the selected song).
 * barNum is absolute (song-wide). Converts to local part index internally.
 * Returns { start, end } in seconds or null.
 */
function getBarTimeRange(songId, barNum) {
  if (!audioMeta || !selectedSongId) return null;

  // Get sorted markers
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  const idx = barNum - 1;

  if (idx < 0 || idx >= sorted.length) return null;
  const start = sorted[idx].time;
  const end = idx + 1 < sorted.length
    ? sorted[idx + 1].time
    : (audioMeta ? audioMeta.duration : null);
  return { start, end };
}

function buildTakteTabTable(bars, filterSong) {
  const showSongCol = !filterSong;
  const sel = takteTabSelectedBar;
  const hasBuf = !!audio.getBuffer();
  const showWave = hasBuf && filterSong === selectedSongId;

  return `
    <table class="takte-tab-table takte-tab-table">
      <thead><tr>
        <th class="ttt-nr">#</th>
        <th class="ttt-play"></th>
        ${showSongCol ? '<th class="ttt-song">Song</th>' : ''}
        <th class="ttt-bar">Takt</th>
        ${showWave ? '<th class="ttt-wave">Waveform</th>' : ''}
        <th class="ttt-time">Zeit</th>
        <th class="ttt-lyrics">Lyrics</th>
        <th class="ttt-acc">Acc.</th>
        <th class="ttt-audio">Audio</th>
      </tr></thead>
      <tbody>
        ${bars.map((b, idx) => {
          const isActive = sel && sel.songId === b.songId && sel.barNum === b.barNum;
          const isBarPlaying = _barPlayId === b.barId && _partPlayActive;

          let waveCanvas = '';
          if (showWave) {
            // Compute bar time range from sorted markers
            const sortedM = [...markers].sort((a, b) => a.time - b.time);
            const mIdx = b.absBar - 1;
            if (mIdx >= 0 && mIdx < sortedM.length) {
              const mStart = sortedM[mIdx].time;
              const mEnd = mIdx + 1 < sortedM.length ? sortedM[mIdx + 1].time : (audioMeta ? audioMeta.duration : mStart + 5);
              waveCanvas = `<canvas class="mini-waveform mini-waveform-sm" data-wave-start="${mStart}" data-wave-end="${mEnd}" data-wave-color="rgb(56, 189, 248)"></canvas>`;
            }
          }

          const canPlay = b.audio || (hasBuf && waveCanvas);
          return `<tr class="ttt-row${isActive ? ' active' : ''}" data-song-id="${b.songId}" data-bar-num="${b.barNum}">
            <td class="ttt-nr mono text-t3">${showSongCol ? idx + 1 : b.absBar}</td>
            <td class="ttt-play">${canPlay ? `<button class="btn-bar-play${isBarPlaying ? ' playing' : ''}" data-action="play-bar" data-play-song-id="${b.songId}" data-play-bar-num="${b.barNum}" title="${isBarPlaying ? 'Stop' : 'Takt abspielen'}">${isBarPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}</td>
            ${showSongCol ? `<td class="ttt-song"><span class="ttt-song-name">${esc(b.songName)}</span></td>` : ''}
            <td class="ttt-bar mono">${b.absBar}</td>
            ${showWave ? `<td class="ttt-wave">${waveCanvas}</td>` : ''}
            <td class="ttt-time mono text-t3">${fmtDur(Math.round(b.barSec))}</td>
            <td class="ttt-lyrics"><input type="text" value="${esc(b.lyrics)}" data-ttf="lyrics" class="takte-input" placeholder="\u2014"></td>
            <td class="ttt-acc mono text-t3">${b.accCount || '\u2014'}</td>
            <td class="ttt-audio">${b.audio ? '<span class="text-green">\u2713</span>' : '<span class="text-t4">\u2014</span>'}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

function renderTakteEditorSection() {
  const area = document.getElementById('tt-editor-area');
  if (!area) return;

  const sel = takteTabSelectedBar;
  if (!sel) { area.innerHTML = ''; return; }

  const song = db.songs[sel.songId];
  if (!song) { area.innerHTML = ''; return; }

  ensureCollections();
  const [barId, barData] = getOrCreateBar(sel.songId || selectedSongId, sel.barNum);
  const accents = getAccentsForBar(barId);

  const cells = Array.from({ length: 16 }, (_, i) => {
    const pos = i + 1;
    const accent = accents.find(a => a.pos_16th === pos);
    const isBeat = (pos - 1) % 4 === 0;
    const cls = ['accent-cell', isBeat ? 'beat' : '', accent ? accent.type : ''].filter(Boolean).join(' ');
    return `<div class="${cls}" data-pos16="${pos}" data-tt-accent="1">
      <span class="accent-num">${BEAT_LABELS[i]}</span>
      ${accent ? `<span class="accent-tag">${accent.type}</span>` : ''}
    </div>`;
  }).join('');


  area.innerHTML = `
    <div class="bar-editor">
      <div class="bar-editor-header">
        <h3>Takt ${sel.barNum} <span class="text-t3">(${esc(song.name)})</span></h3>
        <div class="accent-legend">
          ${Object.entries(ACCENT_INFO).map(([k, v]) => `<span class="legend-item ${k}">${v}</span>`).join('')}
        </div>
      </div>
      <div style="margin-bottom: 12px">
        <label>Lyrics</label>
        <input type="text" class="bar-lyrics-input" value="${esc(barData.lyrics || '')}" data-tt-bar-lyrics="1" placeholder="Textzeile...">
      </div>
      <div class="accent-grid">${cells}</div>
    </div>`;
}

/* ── Takte Tab Event Handlers ────────────────────── */

async function handleDeleteAllBars() {
  const filterSong = selectedSongId;
  const songLabel = filterSong ? (db.songs[filterSong]?.name || 'diesen Song') : 'alle Songs';
  const ok = await showConfirm(
    'Alle Takte l\u00f6schen?',
    `Alle Takte und Accents f\u00fcr <strong>${esc(songLabel)}</strong> werden unwiderruflich gel\u00f6scht.`,
    'L\u00f6schen'
  );
  if (!ok) return;

  ensureCollections();


  // Collect bar IDs to delete
  const barIdsToDelete = [];
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (!filterSong || bar.song_id === filterSong) {
      barIdsToDelete.push(barId);
    }
  }

  // Delete accents for those bars
  for (const [accId, acc] of Object.entries(db.accents)) {
    if (barIdsToDelete.includes(acc.bar_id)) {
      delete db.accents[accId];
    }
  }

  // Delete bars
  for (const barId of barIdsToDelete) {
    delete db.bars[barId];
  }

  // Sync: clear split_markers and total_bars
  if (filterSong) {
    const song = db.songs[filterSong];
    if (song) {
      if (song.split_markers) {
        song.split_markers.markers = [];
      }
      song.total_bars = 0;
      // If this song is currently loaded in the Audio tab, clear in-memory markers
      if (selectedSongId === filterSong) {
        markers = [];
      }
    }
  } else {
    // All songs: clear all markers
    for (const [, song] of Object.entries(db.songs)) {
      if (song.split_markers) {
        song.split_markers.markers = [];
      }
      song.total_bars = 0;
    }
    markers = [];
  }

  takteTabSelectedBar = null;
  markDirty();
  renderTakteTab();
  toast(`${barIdsToDelete.length} Takte gel\u00f6scht`, 'success');
}

function handleTakteTabClick(e) {
  const el = e.target;

  // Delete all bars button
  if (el.closest('#btn-delete-all-bars')) {
    handleDeleteAllBars();
    return;
  }

  // Play bar button
  const playBtn = el.closest('[data-action="play-bar"]');
  if (playBtn) {
    handleBarPlay(playBtn.dataset.playSongId || selectedSongId, parseInt(playBtn.dataset.playBarNum, 10));
    return;
  }

  // Accent cell
  const accentCell = el.closest('[data-tt-accent]');
  if (accentCell) {
    const pos = parseInt(accentCell.dataset.pos16, 10);
    handleTakteAccentToggle(pos);
    return;
  }

  // Song name click → select song in sidebar
  const songNameEl = el.closest('.ttt-song-name');
  if (songNameEl) {
    const row = songNameEl.closest('.ttt-row');
    if (row && row.dataset.songId !== selectedSongId) {
      selectedSongId = row.dataset.songId;
      
      selectedBarNum = null;
      takteTabSelectedBar = null;
      renderSongList(els.searchBox.value);
      renderTakteTab();
      return;
    }
  }

  // Row click (not on input)
  const row = el.closest('.ttt-row');
  if (row && !el.closest('input, select')) {
    const songId = row.dataset.songId;
    const barNum = parseInt(row.dataset.barNum, 10);
    const curSel = takteTabSelectedBar;
    const wasSame = curSel && curSel.songId === songId && curSel.barNum === barNum;
    if (wasSame) return;
    takteTabSelectedBar = { songId, barNum };
    document.querySelectorAll('.ttt-row').forEach(r => {
      r.classList.toggle('active',
        r.dataset.songId === songId && parseInt(r.dataset.barNum, 10) === barNum);
    });
    renderTakteEditorSection();
    return;
  }
}

function handleTakteTabChange(e) {
  const el = e.target;

  // Lyrics in table row
  if (el.dataset.ttf === 'lyrics') {
    const row = el.closest('.ttt-row');
    if (!row) return;
    const barNum = parseInt(row.dataset.barNum, 10);
    const [, barData] = getOrCreateBar(row.dataset.songId || selectedSongId, barNum);
    barData.lyrics = el.value;
    markDirty();
    return;
  }

  // Lyrics in editor
  if (el.hasAttribute('data-tt-bar-lyrics')) {
    const sel = takteTabSelectedBar;
    if (!sel) return;
    const [, barData] = getOrCreateBar(sel.songId || selectedSongId, sel.barNum);
    barData.lyrics = el.value;
    markDirty();
    // Sync table row
    const row = document.querySelector(`.ttt-row[data-bar-num="${sel.barNum}"]`);
    const inp = row?.querySelector('[data-ttf="lyrics"]');
    if (inp && inp !== el) inp.value = el.value;
    return;
  }
}

function handleTakteAccentToggle(pos) {
  const sel = takteTabSelectedBar;
  if (!sel) return;
  ensureCollections();
  const [barId, barData] = getOrCreateBar(sel.songId || selectedSongId, sel.barNum);

  const existing = Object.entries(db.accents).find(([, a]) => a.bar_id === barId && a.pos_16th === pos);

  if (existing) {
    const [accId, acc] = existing;
    const typeIdx = ACCENT_TYPES.indexOf(acc.type);
    if (typeIdx < ACCENT_TYPES.length - 1) {
      acc.type = ACCENT_TYPES[typeIdx + 1];
    } else {
      delete db.accents[accId];
    }
  } else {
    const newId = nextId('A', db.accents);
    db.accents[newId] = { bar_id: barId, pos_16th: pos, type: ACCENT_TYPES[0], notes: '' };
  }

  barData.has_accents = Object.values(db.accents).some(a => a.bar_id === barId);
  markDirty();
  renderTakteEditorSection();
}

/* ── Settings Modal ────────────────────────────────── */

function openSettings() {
  const s = getSettings();
  els.inputRepo.value  = s.repo  || 'christianprison/lighting.ai';
  els.inputToken.value = s.token || '';
  els.inputPath.value  = s.path  || 'db/lighting-ai-db.json';
  const debugCheckbox = document.getElementById('set-debug');
  if (debugCheckbox) debugCheckbox.checked = !!s.debugPanel;
  els.testResult.textContent = '';
  els.modalOverlay.classList.add('open');
}

function closeSettings() {
  els.modalOverlay.classList.remove('open');
}

/* ── Help Modal ───────────────────────────────────── */

function openHelp() {
  // Map program tab to help tab
  const helpTabMap = {
    setlist: 'setlist',
    editor: 'editor',
    takte: 'takte',
    lyrics: 'lyrics',
    audio: 'audio',
  };
  const helpTab = helpTabMap[activeTab] || 'general';
  switchHelpTab(helpTab);
  els.helpModal.classList.add('open');
}

function closeHelp() {
  els.helpModal.classList.remove('open');
}

/* ── Confirm Modal ─────────────────────────────────── */

/**
 * Show a modal confirm dialog. Returns a Promise<boolean>.
 * @param {string} title - dialog title
 * @param {string} message - HTML message body
 * @param {string} [okLabel='Ersetzen'] - label for the confirm button
 */
function showConfirm(title, message, okLabel = 'Ersetzen') {
  return new Promise((resolve) => {
    els.confirmTitle.textContent = title;
    els.confirmMsg.innerHTML = message;
    els.confirmOk.textContent = okLabel;
    els.confirmModal.classList.add('open');

    function cleanup() {
      els.confirmModal.classList.remove('open');
      els.confirmOk.removeEventListener('click', onOk);
      els.confirmCancel.removeEventListener('click', onCancel);
      els.confirmModal.removeEventListener('click', onBg);
    }
    function onOk() { cleanup(); resolve(true); }
    function onCancel() { cleanup(); resolve(false); }
    function onBg(e) { if (e.target === els.confirmModal) { cleanup(); resolve(false); } }

    els.confirmOk.addEventListener('click', onOk);
    els.confirmCancel.addEventListener('click', onCancel);
    els.confirmModal.addEventListener('click', onBg);
  });
}

function switchHelpTab(tabName) {
  els.helpModal.querySelectorAll('.help-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.help === tabName);
  });
  els.helpModal.querySelectorAll('.help-page').forEach(p => {
    p.classList.toggle('active', p.id === `help-${tabName}`);
  });
}

async function handleTestConnection() {
  const repo  = els.inputRepo.value.trim();
  const token = els.inputToken.value.trim();
  els.testResult.textContent = 'Testing...';
  els.testResult.style.color = 'var(--t3)';
  try {
    const ok = await testConnection(repo, token);
    els.testResult.textContent = ok ? 'Connection OK' : 'Failed';
    els.testResult.style.color = ok ? 'var(--green)' : 'var(--red)';
  } catch (e) {
    els.testResult.textContent = `Error: ${e.message}`;
    els.testResult.style.color = 'var(--red)';
  }
}

function handleSaveSettings() {
  const repo  = els.inputRepo.value.trim();
  const token = els.inputToken.value.trim();
  const path  = els.inputPath.value.trim();
  const debugPanel = document.getElementById('set-debug')?.checked || false;
  if (!path) { toast('DB-Pfad muss ausgef\u00fcllt sein.', 'error'); return; }
  saveSettings({ repo, token, path, debugPanel });
  applyDebugPanelVisibility();
  closeSettings();
  toast(token ? 'Settings gespeichert (read/write)' : 'Settings gespeichert (read-only)', 'success');
  initDB();
}

/* ── DB Init ───────────────────────────────────────── */

async function initDB() {
  const s = getSettings();
  setSyncStatus('loading');

  if (s.repo && s.token && s.path) {
    try {
      const result = await loadDB(s.repo, s.path, s.token);
      db = result.data;
      dbSha = result.sha;
      dirty = false;
      readOnly = false;
      setSyncStatus('saved');
      // Run integrity checks, auto-clean orphans, migrate split markers
      const check = integrity.checkOnLoad(db, true);
      if (!check.valid) dirty = true; // auto-cleaned orphans need saving
      toast(`DB geladen (read/write) \u2014 ${Object.keys(db.songs || {}).length} Songs`, 'success');
    } catch (e) {
      setSyncStatus('error');
      toast(`GitHub API fehlgeschlagen: ${e.message} \u2014 Fallback auf lokale DB (read-only)`, 'error', 5000);
      await loadLocal();
    }
  } else {
    await loadLocal();
  }

  renderSongList(els.searchBox.value);
  renderContent();
  updateSaveButton();
}

async function loadLocal() {
  const path = getSettings().path || 'db/lighting-ai-db.json';
  try {
    const result = await loadDBLocal(path);
    db = result.data;
    dbSha = null;
    dirty = false;
    readOnly = true;
    setSyncStatus('readonly');
    integrity.checkOnLoad(db, false); // validate + migrate markers, no auto-clean in read-only
    const hasToken = !!getSettings().token;
    const hint = hasToken ? ' \u2014 Token pr\u00fcfen!' : '';
    toast(`DB geladen (read-only${hint}) \u2014 ${Object.keys(db.songs || {}).length} Songs`, hasToken ? 'error' : 'info', hasToken ? 5000 : 3000);
  } catch (e) {
    db = null;
    setSyncStatus('error');
    toast(`DB laden fehlgeschlagen: ${e.message}`, 'error', 5000);
  }
}

function updateSaveButton() {
  if (readOnly) {
    const hasToken = !!getSettings().token;
    els.btnSave.title = hasToken
      ? 'Read-only \u2014 GitHub-Verbindung fehlgeschlagen. Token pr\u00fcfen!'
      : 'Read-only \u2014 Token in Settings eingeben';
    els.btnSave.style.opacity = '0.4';
  } else {
    els.btnSave.title = 'Save (Ctrl+S)';
    els.btnSave.style.opacity = '1';
  }
}

/* ── Save DB ───────────────────────────────────────── */

let _saveInProgress = false;
async function handleSave(showToast = true) {
  if (!db || !dirty) return true;
  if (_saveInProgress) return true; // prevent concurrent saves → 409
  // Ensure audio split markers are persisted to the song object before saving
  if (selectedSongId && markers.length > 0) {
    saveMarkersToSong();
  }
  if (readOnly) {
    const hasToken = !!getSettings().token;
    const msg = hasToken
      ? 'Read-only Modus \u2014 GitHub-Verbindung fehlgeschlagen. Token in Settings pr\u00fcfen!'
      : 'Read-only Modus \u2014 Token in Settings eingeben';
    toast(msg, 'error', 5000);
    return false;
  }
  const s = getSettings();
  setSyncStatus('saving');
  _saveInProgress = true;
  try {
    const newSha = await saveDB(s.repo, s.path, s.token, db, dbSha);
    dbSha = newSha;
    dirty = false;
    setSyncStatus('saved');
    updateDebugPanel();
    if (showToast) toast('Gespeichert', 'success');

    // Auto-export audio segments only from the audio tab


    return true;
  } catch (e) {
    setSyncStatus('error');
    toast(`Speichern fehlgeschlagen: ${e.message}`, 'error', 5000);
    return false;
  } finally {
    _saveInProgress = false;
  }
}

async function handleUndo() {
  if (readOnly) {
    toast('Read-only Modus \u2014 Undo nicht verf\u00fcgbar', 'error');
    return;
  }
  if (!dirty) {
    toast('Keine ungespeicherten \u00c4nderungen vorhanden', 'info');
    return;
  }
  // Bei unsaved Status: sofort ohne Rückfrage zurücksetzen.
  // Nur bei bereits gespeicherten Versionen (= nicht dirty) kommt eine Bestätigung —
  // aber da wir oben schon !dirty abfangen, greift die Confirm-Frage hier nie.
  // → Undo bei unsaved = immer sofort.
  const s = getSettings();
  setSyncStatus('loading');
  try {
    const result = await loadDB(s.repo, s.path, s.token);
    db = result.data;
    dbSha = result.sha;
    dirty = false;
    setSyncStatus('saved');
    integrity.checkOnLoad(db, true);
    renderSongList(els.searchBox.value);
    renderContent();
    toast('Letzte gespeicherte Version wiederhergestellt', 'success');
  } catch (e) {
    setSyncStatus('error');
    toast(`Undo fehlgeschlagen: ${e.message}`, 'error', 5000);
  }
}

function markDirty() {
  if (!dirty) {
    dirty = true;
    setSyncStatus('unsaved');
  }
  // Check if any progress step was newly completed → confetti
  if (selectedSongId) {
    checkProgressAndCelebrate(selectedSongId);
  }
  // Update debug panel
  updateDebugPanel();
}

/* ── Sidebar Toggle ────────────────────────────────── */

function toggleSidebar() {
  const collapsed = els.appEl.classList.toggle('sidebar-collapsed');
  els.sidebarToggle.innerHTML = collapsed ? '&#9654;' : '&#9664;';
  els.sidebarToggle.title = collapsed ? 'Sidebar aufklappen' : 'Sidebar einklappen';
  localStorage.setItem('lightingai_sidebar', collapsed ? 'collapsed' : 'open');
}

function restoreSidebar() {
  if (localStorage.getItem('lightingai_sidebar') === 'collapsed') {
    els.appEl.classList.add('sidebar-collapsed');
    els.sidebarToggle.innerHTML = '&#9654;';
    els.sidebarToggle.title = 'Sidebar aufklappen';
  }
}

/* ── Event Wiring ──────────────────────────────────── */

function wireEvents() {
  // Tabs
  els.tabEditor?.addEventListener('click', () => switchTab('editor'));
  els.tabTakte?.addEventListener('click',  () => switchTab('takte'));
  els.tabAudio?.addEventListener('click',  () => switchTab('audio'));
  els.tabLyrics?.addEventListener('click', () => switchTab('lyrics'));
  els.tabAccents?.addEventListener('click', () => switchTab('accents'));
  els.tabSetlist?.addEventListener('click', () => switchTab('setlist'));

  // Settings
  els.syncStatus.addEventListener('click', () => {
    const st = els.syncStatus.dataset.status;
    if (st === 'readonly' || st === 'error') openSettings();
  });
  els.btnSettings.addEventListener('click', openSettings);
  els.btnCancelSettings.addEventListener('click', closeSettings);
  els.btnSaveSettings.addEventListener('click', handleSaveSettings);
  els.btnTest.addEventListener('click', handleTestConnection);
  document.getElementById('btn-test-audio')?.addEventListener('click', async () => {
    try {
      const info = await audio.testBeep();
      toast(`Audio OK: ${info}`, 'success');
    } catch (err) {
      toast(`Audio FEHLER: ${err.message}`, 'error');
    }
  });
  els.modalOverlay.addEventListener('click', (e) => { if (e.target === els.modalOverlay) closeSettings(); });

  // Help
  els.btnHelp.addEventListener('click', openHelp);
  els.btnCloseHelp.addEventListener('click', closeHelp);
  els.helpModal.addEventListener('click', (e) => {
    if (e.target === els.helpModal) closeHelp();
    const tab = e.target.closest('.help-tab');
    if (tab) switchHelpTab(tab.dataset.help);
  });

  // Undo (revert to last saved GitHub version)
  els.btnUndo.addEventListener('click', handleUndo);

  // Save
  els.btnSave.addEventListener('click', handleSave);
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); handleSave(); }
    if (e.key === 'Escape') { closeSettings(); closeHelp(); els.confirmModal?.classList.remove('open'); }
    if (e.key === '?' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') openHelp();
  });

  // Sidebar toggle
  els.sidebarToggle.addEventListener('click', toggleSidebar);

  // Search
  els.searchBox.addEventListener('input', () => renderSongList(els.searchBox.value));

  // Song selection
  els.songList.addEventListener('click', (e) => {
    // TMS modal open via progress ring click
    const tmsOpen = e.target.closest('[data-tms-open]');
    if (tmsOpen) {
      e.stopPropagation();
      openTmsModal(tmsOpen.dataset.tmsOpen);
      return;
    }
    const item = e.target.closest('.song-item');
    if (!item) return;
    const rawId = item.dataset.id;
    const newId = rawId === '__all__' ? null : rawId;
    if (newId === selectedSongId) return;
    // Auto-save raw lyrics text before switching away
    saveLyricsRawText();
    // Persist markers for the OLD song before switching away
    if (selectedSongId && markers.length > 0) {
      saveMarkersToSong();
      markDirty();
    }
    // Remember current tab — must be preserved across song switch
    const currentTab = activeTab;
    // Stop audio and reset split state when switching songs
    audio.reset();
    audioMeta = null;
    audioFileName = null;
    resetAudioSplit();
    cancelAnimationFrame(animFrameId);
    selectedSongId = newId;
    
    selectedBarNum = null;
    
    
    takteTabSelectedBar = null;
    renderSongList(els.searchBox.value);
    // Auto-close sidebar on narrow screens (iPad, mobile)
    if (window.innerWidth < 900 && !els.appEl.classList.contains('sidebar-collapsed')) {
      toggleSidebar();
    }
    // Restore tab (defensive — ensure no code above changed it)
    if (activeTab !== currentTab) switchTab(currentTab);
    else renderContent();
  });

  // Editor event delegation
  els.content.addEventListener('change', handleEditorChange);
  els.content.addEventListener('click', (e) => {
    if (activeTab === 'editor') handleEditorClick(e);
    else if (activeTab === 'takte') handleTakteTabClick(e);
    else if (activeTab === 'audio') handleAudioClick(e);
    else if (activeTab === 'lyrics') handleLyricsClick(e);
    else if (activeTab === 'accents') handleAccentsTabClick(e);
    else if (activeTab === 'setlist') handleSetlistClick(e);
  });
  els.content.addEventListener('change', (e) => {
    if (activeTab === 'takte') handleTakteTabChange(e);
    else if (activeTab === 'lyrics') handleLyricsChange(e);
    else if (activeTab === 'setlist') handleSetlistChange(e);
  });
  // + scroll focused input into view after iOS keyboard opens
  els.content.addEventListener('focus', (e) => {
    // iOS keyboard scroll fix: after keyboard animates open, ensure field is visible
    if (e.target.matches('input, textarea, select')) {
      setTimeout(() => {
        e.target.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }, 350); // wait for iOS keyboard animation
    }
  }, true); // useCapture so focus (non-bubbling) is caught via delegation

  // Lyrics editor: no special input/focus handling needed (drag is wired in renderLyricsTab)

  // Audio drag & drop on content area
  els.content.addEventListener('dragover', (e) => {
    if (activeTab === 'audio') handleAudioDragOver(e);
  });
  els.content.addEventListener('dragleave', (e) => {
    if (activeTab === 'audio') handleAudioDragLeave(e);
  });
  els.content.addEventListener('drop', (e) => {
    if (activeTab === 'audio') handleAudioDrop(e);
  });

  // Keyboard shortcuts for audio & lyrics tabs
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    // Audio Split tab
    if (activeTab === 'audio' && audio.getBuffer()) {
      if (e.code === 'Space') { e.preventDefault(); handlePlayPause(); }
      if (e.key === '[') { handleSpeedChange(-1); }
      if (e.key === ']') { handleSpeedChange(1); }
      if (e.key === 'b' || e.key === 'B') { handleBarTap(); }
      if (e.key === 'z' || e.key === 'Z') { if (!e.ctrlKey && !e.metaKey) handleUndoTap(); }
    }

    // Lyrics tab: no keyboard shortcuts needed (per-part play via buttons)
  });
}

/* ══════════════════════════════════════════════════════
   TIP SYSTEM — Contextual tutorial bubbles per tab
   ══════════════════════════════════════════════════════ */

const TIP_STORAGE_KEY = 'lai_tips_seen';

/** Registry of tips per tab. Each tip: { id, tab, text, anchor(el), arrow } */
const TAB_TIPS = [
  {
    id: 'songlist-tms-progress',
    tab: '*',        // sidebar — always visible, show on any tab
    text: 'Tippe auf den Fortschrittskreis um offene Aufgaben zu sehen',
    anchor: () => document.querySelector('.song-progress-mini'),
    arrow: 'left'    // bubble right of circle, arrow points left
  }
];

function getTipsSeen() {
  try { return JSON.parse(localStorage.getItem(TIP_STORAGE_KEY) || '[]'); }
  catch { return []; }
}

function markTipSeen(tipId) {
  const seen = getTipsSeen();
  if (!seen.includes(tipId)) {
    seen.push(tipId);
    localStorage.setItem(TIP_STORAGE_KEY, JSON.stringify(seen));
  }
}

function dismissTip() {
  const el = document.querySelector('.tip-bubble');
  if (el) {
    const tipId = el.dataset.tipId;
    if (tipId) markTipSeen(tipId);
    el.remove();
  }
}

/**
 * Show the next unseen tip for the current tab (if any).
 * Called after each tab render with a short delay so DOM is ready.
 */
function showTabTip(tab) {
  // Remove any existing tip first
  document.querySelector('.tip-bubble')?.remove();

  const seen = getTipsSeen();
  const tip = TAB_TIPS.find(t => (t.tab === tab || t.tab === '*') && !seen.includes(t.id));
  if (!tip) return;

  // Small delay so the tab content is fully rendered & laid out
  setTimeout(() => {
    const anchorEl = tip.anchor();
    if (!anchorEl) return;  // anchor element not present (e.g. no waveform loaded)

    const bubble = document.createElement('div');
    bubble.className = `tip-bubble tip-arrow-${tip.arrow || 'down'}`;
    bubble.dataset.tipId = tip.id;
    bubble.innerHTML = `${esc(tip.text)}<button class="tip-close" aria-label="Schliessen">&times;</button>`;

    // Position relative to anchor
    const rect = anchorEl.getBoundingClientRect();
    const scrollParent = document.getElementById('content') || document.body;
    const scrollRect = scrollParent.getBoundingClientRect();

    bubble.style.position = 'fixed';
    if (tip.arrow === 'down') {
      bubble.style.top = (rect.top - 10) + 'px';  // will adjust after measuring
      bubble.style.left = Math.max(8, rect.left) + 'px';
    } else if (tip.arrow === 'up') {
      bubble.style.top = (rect.bottom + 10) + 'px';
      bubble.style.left = Math.max(8, rect.left) + 'px';
    } else if (tip.arrow === 'left') {
      bubble.style.top = rect.top + 'px';
      bubble.style.left = (rect.right + 10) + 'px';
    }

    document.body.appendChild(bubble);

    // Adjust: if arrow-down, move bubble up by its own height so it sits above anchor
    if (tip.arrow === 'down') {
      const bh = bubble.offsetHeight;
      bubble.style.top = (rect.top - bh - 10) + 'px';
    }

    // Close on button click or tap anywhere on bubble
    bubble.querySelector('.tip-close').addEventListener('click', (e) => { e.stopPropagation(); dismissTip(); });
    bubble.addEventListener('click', dismissTip);
  }, 400);
}

/* ── Debug Panel ───────────────────────────────────── */

function initDebugPanel() {
  const toggle = document.getElementById('debug-toggle');
  const panel = document.getElementById('debug-panel');
  if (!toggle || !panel) return;

  toggle.addEventListener('click', () => {
    panel.classList.toggle('collapsed');
    if (!panel.classList.contains('collapsed')) updateDebugPanel();
  });

  // Copy button
  document.getElementById('btn-debug-copy')?.addEventListener('click', () => {
    const out = document.getElementById('debug-output');
    if (!out) return;
    const text = out.innerText || out.textContent;
    copyToClipboard(text).then(
      () => toast('Debug-Daten kopiert', 'success'),
      () => toast('Kopieren fehlgeschlagen', 'error')
    );
  });

  applyDebugPanelVisibility();
}

/** Show/hide the debug panel toggle button based on settings */
function applyDebugPanelVisibility() {
  const panel = document.getElementById('debug-panel');
  if (!panel) return;
  const s = getSettings();
  if (s.debugPanel) {
    panel.classList.remove('hidden');
  } else {
    panel.classList.add('hidden');
    panel.classList.add('collapsed');
  }
}

function updateDebugPanel() {
  const panel = document.getElementById('debug-panel');
  const out = document.getElementById('debug-output');
  if (!panel || !out || panel.classList.contains('collapsed')) return;
  if (!db) { out.textContent = 'DB not loaded'; return; }

  const sid = selectedSongId;
  if (!sid || !db.songs[sid]) {
    out.innerHTML = '<span class="dbg-dim">Kein Song ausgewählt</span>';
    return;
  }

  const song = db.songs[sid];
  const sm = song.split_markers;
  const lines = [];

  lines.push(`<span class="dbg-section">── Song ──</span>`);
  lines.push(`ID: ${sid}`);
  lines.push(`Name: ${song.name}`);
  lines.push(`BPM: ${song.bpm || '—'}`);

  // In-memory markers[]
  lines.push(`<span class="dbg-section">── markers[] (In-Memory) ──</span>`);
  lines.push(`Gesamt: ${markers.length}`);
  const barMarkerCount = markers.filter(m => !false).length;
  lines.push(`  Bar-Marker: ${barMarkerCount}`);
  if (markers.length > 0) {
    for (const p of parts) {
      const pm = markers.filter(m => null === p.id);
      if (pm.length > 0) {
        lines.push(`  ${p.name}: ${pm.length} marker`);
      }
    }
  }

  // song.split_markers (DB-Objekt, noch nicht gespeichert)
  lines.push(`<span class="dbg-section">── song.split_markers (In-Memory DB) ──</span>`);
  if (!sm) {
    lines.push(`<span class="dbg-warn">NICHT VORHANDEN</span>`);
  } else if (!Array.isArray(sm.markers) || sm.markers.length === 0) {
    lines.push(`<span class="dbg-warn">Vorhanden aber LEER</span>`);
  } else {
    lines.push(`<span class="dbg-ok">Vorhanden: ${sm.markers.length} Einträge</span>`);
  }

  // Bars comparison: total_bars vs markers vs db.bars
  lines.push(`<span class="dbg-section">── Bars-Vergleich ──</span>`);
  const totalDeclared = song.total_bars || 0;
  const totalMarkers = markers.length;
  const totalDbBars = db.bars ? Object.values(db.bars).filter(b => b.song_id === selectedSongId).length : 0;
  const consistent = totalDeclared === totalMarkers && totalDeclared === totalDbBars;
  const cls = consistent ? 'dbg-ok' : 'dbg-err';
  lines.push(`<span class="${cls}">total_bars: ${totalDeclared}, markers: ${totalMarkers}, db.bars: ${totalDbBars}</span>`);
  if (!consistent) {
    lines.push(`<span class="dbg-err">⚠ INKONSISTENZ GEFUNDEN!</span>`);
  } else if (totalMarkers > 0) {
    lines.push(`<span class="dbg-ok">✓ Alles konsistent</span>`);
  }

  // Dirty / Save status
  lines.push(`<span class="dbg-section">── Status ──</span>`);
  lines.push(`dirty: ${dirty ? '<span class="dbg-warn">true</span>' : '<span class="dbg-ok">false</span>'}`);
  lines.push(`readOnly: ${readOnly}`);
  lines.push(`activeTab: ${activeTab}`);

  out.innerHTML = lines.join('\n');
}

/* ── Boot ──────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  wireEvents();
  initDebugPanel();
  restoreSidebar();
  audio.installGestureListener();
  // Set version from JS constant (avoids merge conflicts in index.html)
  const verEl = document.getElementById('app-version');
  if (verEl) verEl.textContent = APP_VERSION;
  switchTab('editor');
  initDB();
  initViewportFix();
});

/** Fix iPad Chrome/Safari: dynamic address bar changes visible viewport height.
 *  Uses visualViewport API to keep #app height in sync with actual visible area. */
function initViewportFix() {
  const app = document.getElementById('app');
  if (!app) return;

  function updateHeight() {
    const vh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    app.style.height = vh + 'px';
  }

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', updateHeight);
  } else {
    window.addEventListener('resize', updateHeight);
  }
  // Initial call to set correct height
  updateHeight();
}
