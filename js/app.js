/**
 * js/app.js — lighting.ai DB Editor
 *
 * Meilenstein 2: Vollstaendiger DB Editor mit Song-Detail, Parts-Tabelle,
 * Bar-Editor mit 16tel-Accent-Raster und Summary-Bar.
 */

import { loadDB, loadDBLocal, saveDB, testConnection, uploadFile, deleteFile, getSha } from './db.js';
import * as audio from './audio-engine.js';
import * as integrity from './integrity.js';

/* ── Version (single source of truth) ──────────────── */
const APP_VERSION = 'v0.15.6';

/* ── State ─────────────────────────────────────────── */
let db = null;
let dbSha = null;
let dirty = false;
let readOnly = true;
let activeTab = 'editor';
let selectedSongId = null;
let selectedPartId = null;
let selectedBarNum = null;

/* ── Parts Tab State ──────────────────────────────── */
let partsTabFilterSong = '';  // '' = alle Songs, or song_id
let partsTabSelectedPart = null;  // {songId, partId}
let partsTabSelectedBar = null;   // bar number or null

/* ── Takte Tab State ─────────────────────────────── */
let takteTabFilterSong = '';
let takteTabSelectedBar = null;  // {songId, partId, barNum}

/* ── Lyrics Editor State ────────────────────────── */
let _lePhase = 'empty';        // 'empty' | 'parts' | 'bars'
let _leWords = [];              // [{text, offset, newlineBefore, emptyLineBefore, isHeader}]
let _lePartMarkers = [];        // [{partId, charOffset, confirmed}] sorted by charOffset
let _leBarMarkers = [];         // [{partId, barNum, charOffset}] sorted by charOffset
let _leDrag = null;             // {type:'part'|'bar', idx, currentOffset, wordPositions}
let _leInitSongId = null;       // songId for which markers were initialized

/* ── Audio Split State ────────────────────────────── */
let audioMeta = null;          // {duration, sampleRate, channels}
let audioFileName = null;      // name of loaded file
let partMarkers = [];          // [{time, partIndex}] sorted
let barMarkers = [];           // [{time, partIndex}] sorted
let tapHistory = [];           // [{type:'part'|'bar', time, partIndex}] for undo
let currentPartIndex = 0;      // next part to be tapped
let currentBarInPart = 0;      // bar counter within current part
let animFrameId = null;        // requestAnimationFrame for playhead
let exportInProgress = false;
let playbackSpeed = 1.0;       // current playback speed multiplier
let waveformZoom = 1.0;        // waveform zoom level (linked to speed)
let _playingPartId = null;     // part ID currently being played in DB Editor
const _audioRefCache = {};     // songId → ArrayBuffer (cached reference audio)

/* ── Waveform Marker Drag State ──────────────────── */
let _dragMarker = null;        // { type: 'part'|'bar', index: number, originalTime: number }
let _isDragging = false;       // true while actively dragging (moved > threshold)
let _dragStartX = 0;           // mouse/touch start X for drag threshold
let _dragSuppressClick = false; // prevent seek after drag ends
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
  228: 'Spot auf Pete', 229: 'Spot auf Tim', 212: 'blind (accent)',
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
    tabParts:      document.getElementById('tab-parts'),
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
    pwModal:       document.getElementById('part-wave-modal'),
    pwCanvas:      document.getElementById('pw-canvas'),
    pwTitle:       document.getElementById('pw-title'),
    pwClose:       document.getElementById('pw-close'),
    pwPlay:        document.getElementById('pw-play'),
    pwSave:        document.getElementById('pw-save'),
    pwCancel:      document.getElementById('pw-cancel'),
    pwTimeStart:   document.getElementById('pw-time-start'),
    pwTimeEnd:     document.getElementById('pw-time-end'),
    pwTimeDur:     document.getElementById('pw-time-dur'),
    pwPlayhead:    document.getElementById('pw-playhead'),
    pwHandleStart: document.getElementById('pw-handle-start'),
    pwHandleEnd:   document.getElementById('pw-handle-end'),
    pwDimLeft:     document.getElementById('pw-dim-left'),
    pwDimRight:    document.getElementById('pw-dim-right'),
    pwWrap:        document.querySelector('.pw-waveform-wrap'),
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

function calcPartDuration(bars, bpm) {
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
 * Format: audio/{Song Title}/{NN Part Name}/{GlobalBarNum} {Song Title} {Part Name}.mp3
 * @param {object} song - the song object
 * @param {object} part - {id, pos, name, bars, ...}
 * @param {number} barNum - bar number within the part (1-based)
 * @param {number} globalBarNum - bar number within the song (1-based)
 */
function buildBarAudioPath(song, part, barNum, globalBarNum) {
  const songDir = sanitizePath(song.name);
  const partDir = `${String(part.pos).padStart(2, '0')} ${sanitizePath(part.name)}`;
  const barFile = `${String(globalBarNum).padStart(3, '0')} ${sanitizePath(song.name)} ${sanitizePath(part.name)}.mp3`;
  return `audio/${songDir}/${partDir}/${barFile}`;
}

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

/**
 * Migrate all audio paths in the DB from old ID-based format
 * (e.g. audio/5iZfKj/reference.mp3, audio/5iZfKj/5iZfKj_P001/bar_001.mp3)
 * to the new human-readable format
 * (e.g. audio/All The Small Things/reference.mp3,
 *       audio/All The Small Things/01 Thema 1/001 All The Small Things Thema 1.mp3).
 *
 * Runs once after DB load. Only touches in-memory data; changes persist on next save.
 */
function migrateAudioPaths() {
  if (!db || !db.songs) return;
  let changed = 0;

  for (const [songId, song] of Object.entries(db.songs)) {
    // Migrate song.audio_ref
    if (song.audio_ref) {
      const expected = buildRefAudioPath(song);
      if (song.audio_ref !== expected) {
        song.audio_ref = expected;
        changed++;
      }
    }

    // Build part lookup: partId → part object (with pos & name)
    const parts = getSortedParts(songId);
    const partById = {};
    for (const p of parts) partById[p.id] = p;

    // Compute global bar offsets per part
    let globalOffset = 0;
    const partGlobalOffset = {};
    for (const p of parts) {
      partGlobalOffset[p.id] = globalOffset;
      globalOffset += (p.bars || 0);
    }

    // Migrate bar.audio paths
    for (const [, bar] of Object.entries(db.bars || {})) {
      if (!bar.audio) continue;
      const part = partById[bar.part_id];
      if (!part) continue;
      const globalBarNum = partGlobalOffset[bar.part_id] + bar.bar_num;
      const expected = buildBarAudioPath(song, part, bar.bar_num, globalBarNum);
      if (bar.audio !== expected) {
        bar.audio = expected;
        changed++;
      }
    }
  }

  if (changed > 0) {
    markDirty();
    console.log(`migrateAudioPaths: updated ${changed} path(s)`);
  }
}

/**
 * Compute start_bar for each part in a song.
 * If a part has a manual start_bar override, use it; otherwise cumulate.
 * Returns Map<partId, {startBar, startSec}>
 */
function calcPartStarts(songId) {
  const song = db.songs[songId];
  if (!song) return new Map();
  const parts = getSortedParts(songId);
  const bpm = song.bpm || 0;
  const result = new Map();
  let cumulBars = 0;
  for (const p of parts) {
    const startBar = (typeof p.start_bar === 'number') ? p.start_bar : cumulBars;
    const startSec = bpm > 0 ? startBar * 4 * 60 / bpm : 0;
    result.set(p.id, { startBar, startSec });
    cumulBars = startBar + (p.bars || 0);
  }
  return result;
}

/* ── DB Helpers ────────────────────────────────────── */

function ensureCollections() {
  if (!db.bars) db.bars = {};
  if (!db.accents) db.accents = {};
}

function getSortedParts(songId) {
  const song = db.songs[songId];
  if (!song || !song.parts) return [];
  return Object.entries(song.parts)
    .map(([id, p]) => ({ id, ...p }))
    .sort((a, b) => a.pos - b.pos);
}

function findBar(partId, barNum) {
  ensureCollections();
  for (const [id, b] of Object.entries(db.bars)) {
    if (b.part_id === partId && b.bar_num === barNum) return [id, b];
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

/** Collect unique part names from all songs for datalist suggestions. */
function getPartNameSuggestions() {
  const names = new Set();
  if (!db.songs) return [];
  for (const song of Object.values(db.songs)) {
    if (!song.parts) continue;
    for (const part of Object.values(song.parts)) {
      if (part.name) names.add(part.name);
    }
  }
  return [...names].sort((a, b) => a.localeCompare(b, 'de'));
}

function getOrCreateBar(partId, barNum) {
  const existing = findBar(partId, barNum);
  if (existing) return existing;
  const barId = nextId('B', db.bars);
  db.bars[barId] = { part_id: partId, bar_num: barNum, lyrics: '', audio: '', has_accents: false };
  return [barId, db.bars[barId]];
}

function nextId(prefix, collection) {
  const nums = Object.keys(collection)
    .map(k => parseInt(k.replace(prefix, ''), 10))
    .filter(n => !isNaN(n));
  const max = nums.length ? Math.max(...nums) : 0;
  return `${prefix}${String(max + 1).padStart(4, '0')}`;
}

function nextPartId(songId) {
  const song = db.songs[songId];
  if (!song.parts) song.parts = {};
  const nums = Object.keys(song.parts).map(k => {
    const m = k.match(/_P(\d+)$/);
    return m ? parseInt(m[1], 10) : 0;
  });
  const max = nums.length ? Math.max(...nums) : 0;
  return `${songId}_P${String(max + 1).padStart(3, '0')}`;
}

function recalcSongDuration() {
  const song = db.songs[selectedSongId];
  if (!song) return;
  const totalSec = Object.values(song.parts || {})
    .reduce((sum, p) => sum + calcPartDuration(p.bars || 0, song.bpm || 0), 0);
  song.duration_sec = totalSec;
  song.duration = fmtDur(totalSec);
}

/* ── Song Progress Checklist ───────────────────────── */

/**
 * Detailed checklist grouped by category.
 * Each step has: id, label, category, tab, check(song, parts, barIds, db)
 */
const PROGRESS_CATEGORIES = [
  { id: 'stammdaten', label: 'Stammdaten', icon: '&#9998;' },
  { id: 'struktur',   label: 'Songstruktur', icon: '&#9881;' },
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

  // ── Songstruktur ──
  { id: 'has_parts',    label: 'Parts angelegt (min. 1)', cat: 'struktur', tab: 'parts',
    check: (s, parts) => parts.length > 0 },
  { id: 'bars_set',     label: 'Takte pro Part gesetzt', cat: 'struktur', tab: 'parts',
    check: (s, parts) => parts.length > 0 && parts.every(p => p.bars != null) },
  { id: 'parts_renamed', label: 'Parts benennen',        cat: 'struktur', tab: 'parts',
    check: (s, parts) => parts.length > 0 && parts.every(p => p.name && p.name !== 'New Part' && !p.name.match(/^Part \d+$/)) },
  { id: 'instr_set',    label: 'Instrumental-Parts identifiziert', cat: 'struktur', tab: 'parts',
    check: (s) => !!s.instr_done },

  // ── Audio ──
  { id: 'audio_ref',    label: 'Referenz-Audio geladen', cat: 'audio', tab: 'audio',
    check: (s) => !!s.audio_ref },
  { id: 'part_markers', label: 'Part-Marker gesetzt (alle Parts)', cat: 'audio', tab: 'audio',
    check: (s, parts) => {
      const pm = s.split_markers?.partMarkers;
      return pm && pm.length >= parts.length && parts.length > 0;
    }},
  { id: 'bar_markers',  label: 'Bar-Marker gesetzt (erwartet aus BPM/Bars)', cat: 'audio', tab: 'audio',
    check: (s, parts, barIds, theDb) => {
      if (parts.length === 0) return false;
      // First and last parts don't need bar markers
      if (parts.length <= 2) return true;
      const bm = s.split_markers?.barMarkers;
      const markersByPart = new Map();
      if (bm) for (const m of bm) markersByPart.set(m.partIndex, (markersByPart.get(m.partIndex) || 0) + 1);
      const dbBarsByPart = new Map();
      for (const bId of barIds) {
        const pid = theDb.bars[bId]?.part_id;
        if (pid) dbBarsByPart.set(pid, (dbBarsByPart.get(pid) || 0) + 1);
      }
      // Check inner parts (skip first and last)
      for (let i = 1; i < parts.length - 1; i++) {
        const p = parts[i];
        const expected = p.bars || 0;
        if (expected <= 0) continue;
        const fromMarkers = markersByPart.get(i) || 0;
        const fromDb = dbBarsByPart.get(p.id) || 0;
        if (fromMarkers < expected && fromDb < expected) return false;
      }
      return true;
    }},
  { id: 'audio_exported', label: 'Audio-Segmente exportiert', cat: 'audio', tab: 'audio',
    check: (s, parts, barIds, theDb) => {
      if (parts.length === 0) return false;
      // At least one bar has an audio path
      return barIds.some(bId => theDb.bars[bId]?.audio);
    }},

  // ── Lyrics ──
  { id: 'lyrics_raw',    label: 'Rohtext eingefuegt',     cat: 'lyrics', tab: 'lyrics',
    check: (s) => !!(s.lyrics_raw && s.lyrics_raw.trim()) },
  { id: 'lyrics_bars',   label: 'Lyrics auf Takte verteilt', cat: 'lyrics', tab: 'lyrics',
    check: (s, parts, barIds, theDb) => {
      // At least 30% of text-parts' bars should have lyrics
      const textParts = parts.filter(p => !p.instrumental && (p.bars || 0) > 0);
      if (textParts.length === 0) return true; // all instrumental = OK
      let withLyrics = 0, total = 0;
      for (const p of textParts) {
        for (const bId of barIds) {
          if (theDb.bars[bId]?.part_id === p.id) {
            total++;
            if (theDb.bars[bId].lyrics) withLyrics++;
          }
        }
      }
      return total > 0 && (withLyrics / total) >= 0.3;
    }},
  { id: 'lyrics_saved',  label: 'Lyrics in DB uebernommen', cat: 'lyrics', tab: 'lyrics',
    check: (s, parts, barIds, theDb) => {
      // Same as above but stricter: at least 1 bar has lyrics
      return barIds.some(bId => theDb.bars[bId]?.lyrics);
    }},

  // ── Licht ──
  { id: 'templates_all', label: 'Light-Template fuer alle Parts', cat: 'licht', tab: 'parts',
    check: (s, parts) => parts.length > 0 && parts.every(p => p.light_template && p.light_template !== '') },
  { id: 'accents_any',   label: 'Accents gesetzt (min. 1)', cat: 'licht', tab: 'accents',
    check: (s, parts, barIds, theDb) => {
      return barIds.some(bId => Object.values(theDb.accents).some(a => a.bar_id === bId));
    }},

  // ── Live-Ready ──
  { id: 'in_setlist',    label: 'fertig f\u00fcr Playlist', cat: 'live', tab: 'setlist',
    check: (s, parts, barIds, theDb) => {
      return theDb.setlist?.items?.some(i => i.type === 'song' && i.song_id === s._id);
    }},
];

/** Track previously completed steps per song to detect newly completed ones */
let _prevProgress = {}; // songId → Set of completed step ids

/**
 * Get or initialize the TMS data for a song.
 * Stored in db.songs[songId].tms = { manual_done: [], user_tasks: [] }
 * manual_done: array of default step IDs manually marked as done
 * user_tasks: array of { id, cat, label, done }
 */
function getSongTms(songId) {
  if (!songId || !db?.songs[songId]) return { manual_done: [], user_tasks: [] };
  const song = db.songs[songId];
  if (!song.tms) song.tms = { manual_done: [], user_tasks: [] };
  if (!song.tms.manual_done) song.tms.manual_done = [];
  if (!song.tms.user_tasks) song.tms.user_tasks = [];
  return song.tms;
}

function getSongProgress(songId) {
  if (!songId || !db?.songs[songId]) return { steps: [], pct: 0, next: null, categories: [], hasOpenUserTasks: false };
  const song = { ...db.songs[songId], _id: songId };
  const parts = getSortedParts(songId);
  ensureCollections();

  // Collect bar IDs for this song
  const barIds = [];
  for (const p of parts) {
    for (const [bId, b] of Object.entries(db.bars)) {
      if (b.part_id === p.id) barIds.push(bId);
    }
  }

  const tms = getSongTms(songId);

  const completed = new Set();
  const steps = SONG_CHECKLIST.map(s => {
    const autoCheck = s.check(song, parts, barIds, db);
    const manualDone = tms.manual_done.includes(s.id);
    const done = autoCheck || manualDone;
    if (done) completed.add(s.id);
    return { ...s, done, autoCheck, manualDone, isUser: false };
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

  const doneCount = steps.filter(s => s.done).length;
  const pct = Math.round((doneCount / steps.length) * 100);
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

  for (const stepId of completed) {
    if (!prev.has(stepId)) {
      const step = SONG_CHECKLIST.find(s => s.id === stepId);
      if (step) {
        toastConfetti(`${step.label} erledigt!`, pct);
      }
    }
  }
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

  // Event delegation for modal
  modal.addEventListener('click', (e) => {
    const el = e.target;

    // Close button
    if (el.closest('.tms-close-btn')) { closeTmsModal(); return; }

    // Toggle category collapse
    const catToggle = el.closest('[data-tms-cat-toggle]');
    if (catToggle) {
      const catEl = catToggle.closest('.tms-category');
      if (catEl) {
        catEl.classList.toggle('collapsed');
        const catId = catToggle.dataset.tmsCatToggle;
        if (catEl.classList.contains('collapsed')) _tmsCollapsed.add(catId);
        else _tmsCollapsed.delete(catId);
      }
      return;
    }

    // Toggle manual completion of default task
    const manualToggle = el.closest('[data-tms-toggle]');
    if (manualToggle) {
      const stepId = manualToggle.dataset.tmsToggle;
      const tms = getSongTms(songId);
      const idx = tms.manual_done.indexOf(stepId);
      if (idx >= 0) tms.manual_done.splice(idx, 1);
      else tms.manual_done.push(stepId);
      markDirty();
      renderTmsModalContent(songId);
      renderSongList(els.searchBox.value);
      return;
    }

    // Toggle user task
    const userToggle = el.closest('[data-tms-user-toggle]');
    if (userToggle) {
      const taskId = userToggle.dataset.tmsUserToggle;
      const tms = getSongTms(songId);
      const task = tms.user_tasks.find(t => t.id === taskId);
      if (task) { task.done = !task.done; markDirty(); }
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
                  title="${s.done ? (s.autoCheck && !s.isUser ? 'Automatisch erkannt' : 'Als offen markieren') : 'Als erledigt markieren'}">
                  ${s.done ? (s.autoCheck && !s.isUser ? '&#10003;' : '&#10004;') : '&#9675;'}
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

/* ── Confetti Toast ───────────────────────────────── */

function toastConfetti(msg, pct) {
  const el = document.createElement('div');
  el.className = 'toast success toast-confetti';
  el.innerHTML = `
    <div class="toast-confetti-content">
      <span class="toast-confetti-icon">&#127881;</span>
      <span>${esc(msg)}</span>
      ${pct !== undefined ? `<span class="toast-pct">${pct}%</span>` : ''}
    </div>
    <canvas class="toast-confetti-canvas" width="300" height="60"></canvas>`;
  els.toastContainer.appendChild(el);

  // Animate confetti particles
  const canvas = el.querySelector('.toast-confetti-canvas');
  if (canvas) animateConfetti(canvas);

  setTimeout(() => el.remove(), 4000);
}

function animateConfetti(canvas) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const colors = ['#00dc82', '#f0a030', '#38bdf8', '#ff3b5c', '#eef0f6', '#a855f7'];
  const particles = Array.from({ length: 40 }, () => ({
    x: w / 2 + (Math.random() - 0.5) * 60,
    y: h,
    vx: (Math.random() - 0.5) * 8,
    vy: -Math.random() * 5 - 3,
    size: Math.random() * 4 + 2,
    color: colors[Math.floor(Math.random() * colors.length)],
    rot: Math.random() * Math.PI * 2,
    rotV: (Math.random() - 0.5) * 0.3,
    life: 1,
  }));

  let frame = 0;
  function tick() {
    ctx.clearRect(0, 0, w, h);
    let alive = false;
    for (const p of particles) {
      if (p.life <= 0) continue;
      alive = true;
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.15; // gravity
      p.rot += p.rotV;
      p.life -= 0.02;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
      ctx.restore();
    }
    frame++;
    if (alive && frame < 120) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
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
        <span class="song-pct mono">${prog.pct}</span>
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
  }
  // Stop lyrics part playback when leaving lyrics tab
  if (activeTab === 'lyrics' && tab !== 'lyrics') {
    stopLyricsPartPlay();
  }
  // Pre-warm AudioContext for tabs with playback
  if (tab === 'lyrics' || tab === 'audio' || tab === 'parts' || tab === 'takte' || tab === 'accents') {
    audio.warmup();
  }
  activeTab = tab;
  els.tabEditor?.classList.toggle('active', tab === 'editor');
  els.tabParts?.classList.toggle('active', tab === 'parts');
  els.tabTakte?.classList.toggle('active', tab === 'takte');
  els.tabAudio?.classList.toggle('active', tab === 'audio');
  els.tabLyrics?.classList.toggle('active', tab === 'lyrics');
  els.tabAccents?.classList.toggle('active', tab === 'accents');
  els.tabSetlist?.classList.toggle('active', tab === 'setlist');
  renderContent();
}

function renderContent() {
  if (!db) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9881;</div><p>DB wird geladen...</p></div>`;
    return;
  }
  if (activeTab === 'editor') renderEditorTab();
  else if (activeTab === 'parts') renderPartsTab();
  else if (activeTab === 'takte') renderTakteTab();
  else if (activeTab === 'audio') renderAudioTab();
  else if (activeTab === 'lyrics') renderLyricsTab();
  else if (activeTab === 'accents') renderAccentsTab();
  else if (activeTab === 'setlist') renderSetlistTab();
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
        <div id="parts-area"></div>
        <div id="bar-area"></div>
      </div>
      <div id="summary-area"></div>
    </div>`;

  renderSongFields();
  renderPartsTable();
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
        <input type="text" value="${esc(song.gema_nr || '')}" data-song-field="gema_nr" class="mono">
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
 * Check if a part has audio bars stored in the DB.
 * Returns the sorted bar entries that have an audio path.
 */
function getAudioBarsForPart(partId) {
  ensureCollections();
  return Object.entries(db.bars)
    .filter(([, b]) => b.part_id === partId && b.audio)
    .map(([id, b]) => ({ id, ...b }))
    .sort((a, b) => a.bar_num - b.bar_num);
}

function renderPartsTable() {
  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  const area = document.getElementById('parts-area');
  if (!area) return;

  const hasSel = !!selectedPartId;

  const starts = calcPartStarts(selectedSongId);

  area.innerHTML = `
    <div class="parts-header">
      <h3>Parts <span class="text-t3">(${parts.length})</span></h3>
      <div class="parts-toolbar">
        <button class="btn btn-sm btn-primary" data-action="add-part">+ ADD</button>
        <button class="btn btn-sm" data-action="move-up" ${hasSel ? '' : 'disabled'}>&#9650;</button>
        <button class="btn btn-sm" data-action="move-down" ${hasSel ? '' : 'disabled'}>&#9660;</button>
        <button class="btn btn-sm" data-action="dup-part" ${hasSel ? '' : 'disabled'}>DUP</button>
        <button class="btn btn-sm btn-danger" data-action="del-part" ${hasSel ? '' : 'disabled'}>DEL</button>
      </div>
    </div>
    <table class="parts-table">
      <thead>
        <tr>
          <th class="pt-pos">#</th>
          <th class="pt-play"></th>
          <th class="pt-name">Name</th>
          <th class="pt-start">Start</th>
          <th class="pt-bars">Takte</th>
          <th class="pt-tmpl">Template</th>
          <th class="pt-grip"></th>
        </tr>
      </thead>
      <tbody>
        ${parts.map(p => {
          const audioBars = getAudioBarsForPart(p.id);
          const hasAudioBars = audioBars.length > 0;
          const isPlaying = _partPlayActive && _playingPartId === p.id;
          const st = starts.get(p.id) || { startBar: 0, startSec: 0 };
          const dur = calcPartDuration(p.bars, song.bpm);
          const partIdx = parts.indexOf(p);
          const hasRefSeg = !!audio.getBuffer() && getPartStartTime(partIdx) !== null && getPartEndTime(partIdx) !== null;
          const canPlay = hasAudioBars || hasRefSeg;
          return `
          <tr class="part-row${p.id === selectedPartId ? ' active' : ''}" data-part-id="${p.id}">
            <td class="pt-pos mono text-t3">${p.pos}</td>
            <td class="pt-play">${canPlay ? `<button class="btn-part-play${isPlaying ? ' playing' : ''}" data-action="play-part" data-part-id="${p.id}" title="${isPlaying ? 'Stop' : 'Part abspielen'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}</td>
            <td class="pt-name">${esc(p.name)}</td>
            <td class="pt-start mono text-t3">${st.startBar} <span class="text-t4">${fmtDur(Math.round(st.startSec))}</span></td>
            <td class="pt-bars mono">${p.bars || 0}</td>
            <td class="pt-tmpl text-t3">${p.light_template || '\u2014'}</td>
            <td class="pt-grip text-t4">\u2807</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

/* ── Bar Section ───────────────────────────────────── */

function renderBarSection() {
  const area = document.getElementById('bar-area');
  if (!area) return;

  if (!selectedPartId || !db.songs[selectedSongId]?.parts[selectedPartId]) {
    area.innerHTML = '';
    return;
  }

  const part = db.songs[selectedSongId].parts[selectedPartId];
  const barCount = part.bars || 0;

  if (barCount === 0) {
    area.innerHTML = `<div class="bar-section"><p class="text-t3">Keine Bars \u2014 setze die Bars-Anzahl in der Parts-Tabelle.</p></div>`;
    return;
  }

  ensureCollections();

  const blocks = Array.from({ length: barCount }, (_, i) => {
    const n = i + 1;
    const found = findBar(selectedPartId, n);
    const hasAcc = found ? getAccentsForBar(found[0]).length > 0 : false;
    const hasLyr = found && found[1].lyrics;
    return `<div class="bar-block${n === selectedBarNum ? ' active' : ''}${hasAcc ? ' has-accents' : ''}${hasLyr ? ' has-lyrics' : ''}" data-bar-num="${n}">${n}</div>`;
  }).join('');

  let editor = '';
  if (selectedBarNum && selectedBarNum <= barCount) {
    editor = buildBarEditor();
  }

  area.innerHTML = `
    <div class="bar-section">
      <h3>Bars \u2014 ${esc(part.name)} <span class="text-t3">(${barCount} Takte)</span></h3>
      <div class="bar-blocks">${blocks}</div>
      ${editor}
    </div>`;
}

function buildBarEditor() {
  const [barId, barData] = getOrCreateBar(selectedPartId, selectedBarNum);
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

  const parts = Object.values(song.parts || {});
  const totalBars = parts.reduce((sum, p) => sum + (p.bars || 0), 0);
  const totalSec = parts.reduce((sum, p) => sum + calcPartDuration(p.bars || 0, song.bpm || 0), 0);

  area.innerHTML = `
    <div class="summary-bar">
      <span class="summary-item"><span class="summary-label">Parts</span><span class="mono">${parts.length}</span></span>
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

    if (field === 'bpm') {
      song.bpm = parseInt(el.value, 10) || 0;
      // Recalc all part durations
      for (const p of Object.values(song.parts || {})) {
        p.duration_sec = calcPartDuration(p.bars || 0, song.bpm);
      }
      recalcSongDuration();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
      // Re-render parts table (durations + start times depend on BPM)
      renderPartsTable();
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

  /* ── Part field ── */
  if (el.dataset.partField) {
    const partId = el.closest('[data-part-id]')?.dataset.partId;
    if (!partId) return;
    const song = db.songs[selectedSongId];
    const part = song?.parts[partId];
    if (!part) return;

    const field = el.dataset.partField;
    if (field === 'bars') {
      part.bars = parseInt(el.value, 10) || 0;
      part.duration_sec = calcPartDuration(part.bars, song.bpm || 0);
      // Clean up excess bars when count is reduced
      integrity.syncBarCount(db, partId, part.bars);
      // Update duration cell
      const row = el.closest('[data-part-id]');
      const durCell = row?.querySelector('.part-duration');
      if (durCell) durCell.textContent = fmtDur(part.duration_sec);
      recalcSongDuration();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
      renderSummary();
      // Bars changed → re-render full parts table to update subsequent start values
      renderPartsTable();
      // Re-render bar section if this part is selected
      if (partId === selectedPartId) {
        if (selectedBarNum && selectedBarNum > part.bars) selectedBarNum = null;
        renderBarSection();
      }
    } else if (field === 'start_bar') {
      part.start_bar = parseInt(el.value, 10) || 0;
      renderPartsTable();
    } else if (field === 'duration_sec') {
      const newDur = parseInt(el.value, 10) || 0;
      const bpm = song.bpm || 0;
      if (bpm > 0) {
        part.bars = Math.round(newDur * bpm / 240);
      }
      part.duration_sec = calcPartDuration(part.bars, bpm);
      recalcSongDuration();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
      renderSummary();
      renderPartsTable();
      if (partId === selectedPartId) {
        if (selectedBarNum && selectedBarNum > part.bars) selectedBarNum = null;
        renderBarSection();
      }
    } else if (field === 'light_template') {
      part.light_template = el.value;
    } else if (field === 'name') {
      part.name = el.value;
      if (partId === selectedPartId) renderBarSection();
    } else {
      part[field] = el.value;
    }
    markDirty();
    return;
  }

  /* ── Bar lyrics ── */
  if (el.hasAttribute('data-bar-lyrics')) {
    if (!selectedPartId || !selectedBarNum) return;
    const [, barData] = getOrCreateBar(selectedPartId, selectedBarNum);
    barData.lyrics = el.value;
    markDirty();
    return;
  }
}

function handleEditorClick(e) {
  const el = e.target;

  /* ── Play part button ── */
  const playBtn = el.closest('[data-action="play-part"]');
  if (playBtn) {
    handlePartPlay(playBtn.dataset.partId);
    return;
  }

  /* ── Delete song ── */
  if (el.closest('[data-action="delete-song"]')) {
    handleDeleteSong();
    return;
  }

  /* ── Part toolbar actions ── */
  const actionBtn = el.closest('[data-action]');
  if (actionBtn && !actionBtn.disabled) {
    handlePartAction(actionBtn.dataset.action);
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

  /* ── Part row ── */
  const partRow = el.closest('.part-row');
  if (partRow && !el.closest('input, select, button')) {
    handlePartSelect(partRow.dataset.partId);
    return;
  }
}

function handlePartSelect(partId) {
  if (selectedPartId === partId) return;
  selectedPartId = partId;
  selectedBarNum = null;
  // Update active row visually
  document.querySelectorAll('.part-row').forEach(r => {
    r.classList.toggle('active', r.dataset.partId === partId);
  });
  // Enable/disable toolbar buttons
  document.querySelectorAll('.parts-toolbar .btn:not([data-action="add-part"])').forEach(btn => {
    btn.disabled = false;
  });
  renderBarSection();
}

function handleBarSelect(barNum) {
  selectedBarNum = (selectedBarNum === barNum) ? null : barNum;
  renderBarSection();
}

async function handleDeleteSong() {
  if (!selectedSongId || !db.songs[selectedSongId]) return;
  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  const barCount = Object.values(db.bars || {}).filter(b => parts.some(p => p.id === b.part_id)).length;
  const inSetlist = (db.setlist?.items || []).some(i => i.type === 'song' && i.song_id === selectedSongId);

  let details = `<strong>${esc(song.name)}</strong> (${esc(song.artist)})<br>`;
  details += `${parts.length} Parts, ${barCount} Takte`;
  if (inSetlist) details += ', in Setlist referenziert';
  details += ' — alles wird unwiderruflich gelöscht.';

  const ok = await showConfirm('Song löschen?', details, 'Löschen');
  if (!ok) return;

  integrity.deleteSong(db, selectedSongId);
  selectedSongId = null;
  selectedPartId = null;
  selectedBarNum = null;
  markDirty();
  renderSongList(els.searchBox.value);
  renderEditorTab();
  toast(`Song "${song.name}" gelöscht`, 'success');
}

function handlePartAction(action) {
  const song = db.songs[selectedSongId];
  if (!song) return;
  if (!song.parts) song.parts = {};

  switch (action) {
    case 'add-part': {
      const parts = getSortedParts(selectedSongId);
      const newPos = parts.length > 0 ? Math.max(...parts.map(p => p.pos)) + 1 : 1;
      const newId = nextPartId(selectedSongId);
      song.parts[newId] = {
        pos: newPos, name: 'New Part', bars: 0, duration_sec: 0,
        light_template: '', notes: ''
      };
      selectedPartId = newId;
      selectedBarNum = null;
      markDirty();
      renderPartsTable();
      renderBarSection();
      renderSummary();
      setTimeout(() => {
        const input = document.querySelector(`[data-part-id="${newId}"] [data-part-field="name"]`);
        if (input) { input.focus(); input.select(); }
      }, 50);
      break;
    }

    case 'del-part': {
      if (!selectedPartId || !song.parts[selectedPartId]) return;
      ensureCollections();
      // Delete bars and accents for this part
      for (const [barId, b] of Object.entries(db.bars)) {
        if (b.part_id === selectedPartId) {
          for (const [accId, a] of Object.entries(db.accents)) {
            if (a.bar_id === barId) delete db.accents[accId];
          }
          delete db.bars[barId];
        }
      }
      const deletedPartId = selectedPartId;
      delete song.parts[selectedPartId];
      // Renumber
      getSortedParts(selectedSongId).forEach((p, i) => { song.parts[p.id].pos = i + 1; });
      // Sync: remove split_markers for the deleted part
      removeSplitMarkersForPart(song, deletedPartId);
      selectedPartId = null;
      selectedBarNum = null;
      markDirty();
      recalcSongDuration();
      renderPartsTable();
      renderBarSection();
      renderSummary();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
      break;
    }

    case 'move-up': {
      if (!selectedPartId) return;
      const parts = getSortedParts(selectedSongId);
      const idx = parts.findIndex(p => p.id === selectedPartId);
      if (idx <= 0) return;
      const curr = song.parts[parts[idx].id];
      const prev = song.parts[parts[idx - 1].id];
      [curr.pos, prev.pos] = [prev.pos, curr.pos];
      updateSplitMarkersAfterReorder(song);
      markDirty();
      renderPartsTable();
      break;
    }

    case 'move-down': {
      if (!selectedPartId) return;
      const parts = getSortedParts(selectedSongId);
      const idx = parts.findIndex(p => p.id === selectedPartId);
      if (idx < 0 || idx >= parts.length - 1) return;
      const curr = song.parts[parts[idx].id];
      const next = song.parts[parts[idx + 1].id];
      [curr.pos, next.pos] = [next.pos, curr.pos];
      updateSplitMarkersAfterReorder(song);
      markDirty();
      renderPartsTable();
      break;
    }

    case 'dup-part': {
      if (!selectedPartId || !song.parts[selectedPartId]) return;
      // Use integrity module for cascade duplicate (copies bars + accents too)
      const newId = integrity.duplicatePart(db, selectedSongId, selectedPartId);
      if (!newId) return;
      selectedPartId = newId;
      selectedBarNum = null;
      markDirty();
      recalcSongDuration();
      renderPartsTable();
      renderBarSection();
      renderSummary();
      break;
    }
  }
}

/* ── Part Audio Playback ──────────────────────────── */

/** AudioContext for part playback (separate from audio-engine to avoid conflicts) */
let _partPlayCtx = null;
let _partPlaySources = [];
let _partPlayIndex = 0;
let _partPlayBuffers = [];
let _partPlayActive = false;
let _barPlayId = null;          // bar ID currently being played (single bar)

function refreshPartPlayUI() {
  // Update play buttons in-place instead of full re-render to preserve scroll position
  document.querySelectorAll('[data-action="play-part"]').forEach(btn => {
    const id = btn.dataset.partId;
    const isPlaying = _partPlayActive && _playingPartId === id;
    btn.innerHTML = isPlaying ? '&#9632;' : '&#9654;';
    btn.title = isPlaying ? 'Stop' : 'Part abspielen';
    btn.classList.toggle('playing', isPlaying);
  });
  // Takte tab: bar play buttons
  document.querySelectorAll('[data-action="play-bar"]').forEach(btn => {
    const partId = btn.dataset.playPartId;
    const barNum = parseInt(btn.dataset.playBarNum, 10);
    const isPlaying = _partPlayActive && _playingPartId === partId;
    // Bar-level play detection not needed here — just reset all
    btn.classList.toggle('playing', false);
  });
}

async function handlePartPlay(partId) {
  // If already playing this part → stop
  if (_playingPartId === partId && _partPlayActive) {
    stopPartPlay();
    return;
  }

  // Stop any current playback
  stopPartPlay();

  // Try reference audio segment first (if buffer loaded and part markers exist)
  if (audio.getBuffer() && selectedSongId) {
    const parts = getSortedParts(selectedSongId);
    const partIdx = parts.findIndex(p => p.id === partId);
    if (partIdx >= 0) {
      const startTime = getPartStartTime(partIdx);
      const endTime = getPartEndTime(partIdx);
      if (startTime !== null && endTime !== null) {
        _playingPartId = partId;
        _partPlayActive = true;
        refreshPartPlayUI();
        audio.playSegments([{ startTime, endTime }], () => {
          if (_playingPartId === partId) {
            _playingPartId = null;
            _partPlayActive = false;
            refreshPartPlayUI();
          }
        });
        return;
      }
    }
  }

  // Fallback: play exported bar MP3 files
  const audioBars = getAudioBarsForPart(partId);
  if (audioBars.length === 0) return;

  _playingPartId = partId;
  _partPlayActive = true;
  refreshPartPlayUI();

  try {
    if (!_partPlayCtx) {
      _partPlayCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (_partPlayCtx.state === 'suspended') await _partPlayCtx.resume();

    // Fetch and decode all bar audio files
    _partPlayBuffers = [];
    for (const bar of audioBars) {
      const arrBuf = await fetchAudioUrl(bar.audio);
      if (!arrBuf) throw new Error(`Audio nicht gefunden: ${bar.audio}`);
      const decoded = await _partPlayCtx.decodeAudioData(arrBuf);
      _partPlayBuffers.push(decoded);
    }

    // Schedule all buffers back-to-back for gapless playback
    let schedTime = _partPlayCtx.currentTime;
    _partPlaySources = [];
    for (let i = 0; i < _partPlayBuffers.length; i++) {
      const src = _partPlayCtx.createBufferSource();
      src.buffer = _partPlayBuffers[i];
      src.connect(_partPlayCtx.destination);
      src.start(schedTime);
      schedTime += _partPlayBuffers[i].duration;
      _partPlaySources.push(src);
    }

    // When last source ends, reset state
    const lastSrc = _partPlaySources[_partPlaySources.length - 1];
    lastSrc.onended = () => {
      if (_playingPartId === partId) {
        _playingPartId = null;
        _partPlayActive = false;
        refreshPartPlayUI();
      }
    };
  } catch (err) {
    console.error('Part playback error:', err);
    toast(`Wiedergabe-Fehler: ${err.message}`, 'error');
    stopPartPlay();
  }
}

function stopPartPlay() {
  // Stop reference audio segment playback
  audio.stopSegments();
  for (const src of _partPlaySources) {
    try { src.onended = null; src.stop(); } catch { /* ok */ }
    try { src.disconnect(); } catch { /* ok */ }
  }
  _partPlaySources = [];
  _partPlayBuffers = [];
  _partPlayActive = false;
  const wasPlaying = _playingPartId || _barPlayId;
  _playingPartId = null;
  _barPlayId = null;
  if (wasPlaying) refreshPartPlayUI();
}

async function handleBarPlay(partId, barNum) {
  ensureCollections();
  const found = findBar(partId, barNum);
  if (!found) return;
  const [barId, barData] = found;
  if (!barData.audio) return;

  // If already playing this bar → stop
  if (_barPlayId === barId && _partPlayActive) {
    stopPartPlay();
    _barPlayId = null;
    return;
  }

  stopPartPlay();
  _barPlayId = barId;
  _partPlayActive = true;

  try {
    if (!_partPlayCtx) {
      _partPlayCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (_partPlayCtx.state === 'suspended') await _partPlayCtx.resume();

    const arrBuf = await fetchAudioUrl(barData.audio);
    if (!arrBuf) throw new Error(`Audio nicht gefunden: ${barData.audio}`);
    const decoded = await _partPlayCtx.decodeAudioData(arrBuf);

    const src = _partPlayCtx.createBufferSource();
    src.buffer = decoded;
    src.connect(_partPlayCtx.destination);
    src.onended = () => {
      if (_barPlayId === barId) {
        _barPlayId = null;
        _partPlayActive = false;
        renderTakteTab();
      }
    };
    src.start(0);
    _partPlaySources = [src];
    _partPlayBuffers = [decoded];

    renderTakteTab();
  } catch (err) {
    console.error('Bar playback error:', err);
    toast(`Wiedergabe-Fehler: ${err.message}`, 'error');
    stopPartPlay();
    _barPlayId = null;
  }
}

function handleAccentToggle(pos16) {
  if (!selectedPartId || !selectedBarNum) return;
  ensureCollections();
  const [barId, barData] = getOrCreateBar(selectedPartId, selectedBarNum);

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

let _refLoadingFor = null; // songId currently loading reference for
let _refLoadingPromise = null; // pending loadReferenceAudio promise

function renderAudioTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9836;</div><p>Song aus der Liste links ausw\u00e4hlen, um Audio zu splitten.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
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
        ${hasBuf ? buildTapButtons(parts, isPlay) : ''}
        ${hasBuf ? buildBpmBanner(song) : ''}
        ${hasBuf ? buildSplitResult(parts) : ''}
      </div>
      ${hasBuf ? buildAudioSummary(parts) : ''}
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
      <div class="t-zoom" id="t-zoom">
        <button class="t-zoom-btn" id="t-zoom-out" title="Zoom Out">&minus;</button>
        <span class="t-zoom-label" id="t-zoom-label">&#128269; ${zoomLabel}</span>
        <button class="t-zoom-btn" id="t-zoom-in" title="Zoom In">+</button>
      </div>
    </div>`;
}

function buildTapButtons(parts, isPlay) {
  const nextPartName = currentPartIndex < parts.length
    ? parts[currentPartIndex].name
    : `Part ${currentPartIndex + 1}`;
  const allPartsDone = false; // Parts can always be added dynamically
  const nextAbsBar = barMarkers.length + 1;
  const barLabel = `Bar ${nextAbsBar}`;

  return `
    <div class="tap-row" id="tap-row">
      <button class="tap-btn tap-part" id="tap-part" ${!isPlay || allPartsDone ? 'disabled' : ''}>
        <span class="tap-label">PART TAP <kbd>P</kbd></span>
        <span class="tap-info">${esc(nextPartName)}</span>
      </button>
      <button class="tap-btn tap-bar" id="tap-bar" ${!isPlay || currentPartIndex === 0 ? 'disabled' : ''}>
        <span class="tap-label">BAR TAP <kbd>B</kbd></span>
        <span class="tap-info">${barLabel}</span>
      </button>
      <button class="tap-btn tap-undo" id="tap-undo" ${tapHistory.length === 0 ? 'disabled' : ''}>
        <span class="tap-label">UNDO <kbd>Z</kbd></span>
      </button>
      <button class="tap-btn tap-btn-dist" id="tap-distribute-parts" ${parts.length < 2 ? 'disabled' : ''} title="Part-Marker gleichmaessig ueber die Audiodauer verteilen">
        <span class="tap-label">PARTS</span>
        <span class="tap-info">verteilen</span>
      </button>
      <button class="tap-btn tap-btn-snap" id="tap-snap-peaks" ${(partMarkers.length + barMarkers.length) === 0 ? 'disabled' : ''} title="Alle Marker auf naechsten Audio-Peak verschieben">
        <span class="tap-label">SNAP</span>
        <span class="tap-info">&#8614; Peak</span>
      </button>
      <button class="tap-btn tap-btn-del" id="tap-delete-parts" ${partMarkers.length === 0 ? 'disabled' : ''}>
        <span class="tap-label">DEL PARTS</span>
        <span class="tap-info">${partMarkers.length}</span>
      </button>
      <button class="tap-btn tap-btn-del" id="tap-delete-bars" ${barMarkers.length === 0 ? 'disabled' : ''}>
        <span class="tap-label">DEL BARS</span>
        <span class="tap-info">${barMarkers.length}</span>
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

function buildSplitResult(parts) {
  if (parts.length === 0) return '';

  const rows = parts.map((p, i) => {
    const isDone = i < currentPartIndex;
    const isCurrent = i === currentPartIndex - 1 && currentPartIndex > 0;
    const start = getPartStartTime(i);
    const end = getPartEndTime(i);
    const dur = (start !== null && end !== null) ? end - start : null;
    const barCount = barMarkers.filter(m => m.partIndex === i).length;
    const cls = isCurrent ? 'current' : (isDone ? 'done' : '');
    const deleteBtn = isDone ? `<button class="marker-delete" data-type="part" data-time="${start}" data-part="${i}" title="Part-Marker loeschen">&#10005;</button>` : '';

    return `<tr class="${cls}" style="cursor:${isDone ? 'pointer' : 'default'}">
      <td class="st-nr mono text-t3">${p.pos}</td>
      <td class="st-name">${esc(p.name)}</td>
      <td class="st-bars mono">${barCount || '\u2014'}</td>
      <td class="st-start mono text-t3">${start !== null ? fmtTime(start) : '\u2014'}</td>
      <td class="st-dur mono text-t3">${dur !== null ? fmtTime(dur) : '\u2014'}</td>
      <td class="st-check">${isDone ? '\u2713' : ''}</td>
      <td class="st-actions">${deleteBtn}</td>
    </tr>`;
  }).join('');

  return `
    <div class="split-result">
      <h3>Split-Ergebnis</h3>
      <table class="split-table">
        <thead><tr>
          <th class="st-nr">#</th>
          <th class="st-name">Name</th>
          <th class="st-bars">Takte</th>
          <th class="st-start">Start</th>
          <th class="st-dur">Dauer</th>
          <th class="st-check"></th>
          <th class="st-actions"></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function buildExportSection(parts) {
  if (partMarkers.length === 0) return '';

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
        ${barMarkers.length > 0
          ? `${barMarkers.length} Bars als MP3-Segmente nach <span class="mono">audio/${sanitizePath(db.songs[selectedSongId]?.name || '')}/</span> hochladen.`
          : `Part-Zeiten in DB speichern (keine Bar-Segmente zum Exportieren).`}
      </div>
    </div>`;
}

function buildAudioSummary(parts) {
  const totalBars = barMarkers.length;
  const est = estimateBpm();
  return `
    <div class="summary-bar">
      <span class="summary-item"><span class="summary-label">Parts</span><span class="mono">${partMarkers.length}</span></span>
      <span class="summary-item"><span class="summary-label">Takte</span><span class="mono">${totalBars}</span></span>
      <span class="summary-item"><span class="summary-label">BPM (est.)</span><span class="mono">${est || '\u2014'}</span></span>
      <span class="summary-item"><span class="summary-label">Storage</span><span class="mono text-green">GitHub</span></span>
    </div>`;
}

/* ── Audio Helper Functions ────────────────────────── */

function fmtTime(sec) {
  if (sec == null || isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec % 1) * 10);
  return `${m}:${String(s).padStart(2, '0')}.${ms}`;
}

function getPartStartTime(partIndex) {
  const marker = partMarkers.find(m => m.partIndex === partIndex);
  return marker ? marker.time : null;
}

function getPartEndTime(partIndex) {
  const nextMarker = partMarkers.find(m => m.partIndex === partIndex + 1);
  if (nextMarker) return nextMarker.time;
  // If this part has a marker and no higher marker exists, it's the last part → use audio end
  const hasMarker = partMarkers.some(m => m.partIndex === partIndex);
  const hasHigher = partMarkers.some(m => m.partIndex > partIndex);
  if (hasMarker && !hasHigher && audioMeta) return audioMeta.duration;
  return null;
}

function estimateBpm() {
  if (barMarkers.length < 2) return null;
  const intervals = [];
  for (let i = 1; i < barMarkers.length; i++) {
    const dt = barMarkers[i].time - barMarkers[i - 1].time;
    if (dt >= 0.3 && dt <= 4.0) intervals.push(dt);
  }
  if (intervals.length === 0) return null;
  const avg = intervals.reduce((a, b) => a + b, 0) / intervals.length;
  return Math.round(240 / avg);
}

function resetAudioSplit() {
  partMarkers = [];
  barMarkers = [];
  tapHistory = [];
  currentPartIndex = 0;
  currentBarInPart = 0;
  exportInProgress = false;
  playbackSpeed = 1.0;
  waveformZoom = 1.0;
  audio.setPlaybackRate(1.0);
}

/**
 * Save current partMarkers + barMarkers into the song object in the DB.
 * Called after tapping is done (export) and can be restored on reload.
 */
function saveMarkersToSong() {
  if (!selectedSongId || !db.songs[selectedSongId]) return;
  const song = db.songs[selectedSongId];
  // Resolve partId from partIndex for each marker
  const parts = getSortedParts(selectedSongId);
  const indexToId = (idx) => parts[idx] ? parts[idx].id : undefined;
  song.split_markers = {
    partMarkers: partMarkers.map(m => ({ time: m.time, partIndex: m.partIndex, partId: m.partId || indexToId(m.partIndex) })),
    barMarkers: barMarkers.map(m => ({ time: m.time, partIndex: m.partIndex, partId: m.partId || indexToId(m.partIndex) })),
  };

  // Update bars count per part from bar markers
  for (let i = 0; i < parts.length; i++) {
    const count = barMarkers.filter(m => m.partIndex === i).length;
    if (song.parts[parts[i].id]) {
      song.parts[parts[i].id].bars = count;
    }
  }
}

/**
 * Remove split_markers (part + bar) for a specific partId from a song.
 * Also updates in-memory markers if the song is currently loaded in Audio tab.
 */
function removeSplitMarkersForPart(song, partId) {
  if (!song || !song.split_markers) return;
  const sm = song.split_markers;
  if (Array.isArray(sm.partMarkers)) {
    sm.partMarkers = sm.partMarkers.filter(m => m.partId !== partId);
  }
  if (Array.isArray(sm.barMarkers)) {
    sm.barMarkers = sm.barMarkers.filter(m => m.partId !== partId);
  }
  // Rebuild partIndex values after removal
  rebuildSplitMarkerIndices(song);
  // Sync in-memory markers if this song is active in Audio tab
  if (selectedSongId && db.songs[selectedSongId] === song) {
    restoreMarkersFromSong();
  }
}

/**
 * Rebuild partIndex values in split_markers based on current part order.
 * Called after parts are deleted, moved, or reordered.
 */
function rebuildSplitMarkerIndices(song) {
  if (!song || !song.split_markers) return;
  const sm = song.split_markers;
  const parts = Object.entries(song.parts || {})
    .map(([id, p]) => ({ id, pos: p.pos }))
    .sort((a, b) => a.pos - b.pos);
  const idToIndex = {};
  parts.forEach((p, i) => { idToIndex[p.id] = i; });

  for (const markers of [sm.partMarkers, sm.barMarkers]) {
    if (!Array.isArray(markers)) continue;
    for (const m of markers) {
      if (m.partId && idToIndex[m.partId] !== undefined) {
        m.partIndex = idToIndex[m.partId];
      }
    }
  }
}

/**
 * Restore partMarkers + barMarkers from the song object in the DB.
 * Called after loading reference audio.
 */
function restoreMarkersFromSong() {
  if (!selectedSongId || !db.songs[selectedSongId]) return;
  const song = db.songs[selectedSongId];
  if (!song.split_markers) return;

  const sm = song.split_markers;
  // Rebuild index from partId if available (survives part reorder)
  const parts = getSortedParts(selectedSongId);
  const idToIndex = {};
  parts.forEach((p, i) => { idToIndex[p.id] = i; });

  if (Array.isArray(sm.partMarkers) && sm.partMarkers.length > 0) {
    partMarkers = sm.partMarkers.map(m => {
      const idx = m.partId && idToIndex[m.partId] !== undefined ? idToIndex[m.partId] : m.partIndex;
      return { time: m.time, partIndex: idx, partId: m.partId };
    });
    currentPartIndex = partMarkers.length;
  }
  if (Array.isArray(sm.barMarkers) && sm.barMarkers.length > 0) {
    barMarkers = sm.barMarkers.map(m => {
      const idx = m.partId && idToIndex[m.partId] !== undefined ? idToIndex[m.partId] : m.partIndex;
      return { time: m.time, partIndex: idx, partId: m.partId };
    });
    const lastBar = barMarkers[barMarkers.length - 1];
    currentBarInPart = barMarkers.filter(b => b.partIndex === lastBar.partIndex).length;

    // Sync bars count from markers (split_markers is source of truth)
    for (let i = 0; i < parts.length; i++) {
      const count = barMarkers.filter(m => m.partIndex === i).length;
      if (count > 0 && song.parts[parts[i].id] && song.parts[parts[i].id].bars !== count) {
        song.parts[parts[i].id].bars = count;
      }
    }
  }
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
  const totalW = baseW * waveformZoom;  // virtual total width
  const h = 120;

  // Viewport-based rendering: canvas is always viewport-sized,
  // only the scroll container spans the full virtual width.
  // This avoids hitting browser canvas size limits at high zoom.
  const viewW = baseW;
  const scrollLeft = wrap.scrollLeft;

  scroll.style.width = totalW + 'px';
  canvas.width = viewW * dpr;
  canvas.height = h * dpr;
  canvas.style.width = viewW + 'px';
  canvas.style.height = h + 'px';
  // Pin canvas to viewport via CSS left offset inside scroll container
  canvas.style.position = 'sticky';
  canvas.style.left = '0px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, viewW, h);

  const buf = audio.getBuffer();
  if (!buf) return;
  const duration = buf.duration;

  // Map from virtual total coordinate to canvas coordinate
  const vToC = (vx) => vx - scrollLeft;
  // Visible time range
  const tStart = (scrollLeft / totalW) * duration;
  const tEnd = ((scrollLeft + viewW) / totalW) * duration;
  // Pixels per second at current zoom
  const pxPerSec = totalW / duration;

  // Draw waveform using getPeaksRange for the visible window only
  const buckets = Math.floor(viewW);
  const peaks = audio.getPeaksRange(tStart, tEnd, buckets);
  const mid = h / 2;

  // Midline
  ctx.strokeStyle = 'rgba(92, 96, 128, 0.2)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(viewW, mid);
  ctx.stroke();

  // Waveform bars
  for (let i = 0; i < buckets; i++) {
    const amp = peaks[i];
    const barH = amp * (h * 0.9);
    const opacity = 0.3 + amp * 0.7;
    ctx.fillStyle = `rgba(0, 220, 130, ${opacity})`;
    ctx.fillRect(i, mid - barH / 2, Math.max(0.5, 1), barH || 1);
  }

  // Helper: is a virtual x in the visible range (with margin for labels)?
  const margin = 80;
  const inView = (vx) => vx >= scrollLeft - margin && vx <= scrollLeft + viewW + margin;

  // Bar markers (cyan lines with flag labels as drag handles)
  for (let bi = 0; bi < barMarkers.length; bi++) {
    const m = barMarkers[bi];
    const vx = (m.time / duration) * totalW;
    if (!inView(vx)) continue;
    const x = vToC(vx);
    const absBarNum = bi + 1;
    const isDragTarget = _isDragging && _dragMarker && _dragMarker.type === 'bar' && _dragMarker.index === bi;
    ctx.strokeStyle = isDragTarget ? 'rgba(56, 189, 248, 0.9)' : 'rgba(56, 189, 248, 0.4)';
    ctx.lineWidth = isDragTarget ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    // Flag label (skip if a part marker sits at same position — part flag takes priority)
    const isPartStart = partMarkers.some(pm => Math.abs(pm.time - m.time) < 0.01);
    if (!isPartStart) {
      const label = String(absBarNum);
      ctx.font = '9px "DM Mono", monospace';
      const tw = ctx.measureText(label).width;
      const flagW = tw + 6;
      const flagH = 14;
      const flagX = x;
      const flagY = h - flagH;
      ctx.fillStyle = isDragTarget ? 'rgba(56, 189, 248, 1.0)' : 'rgba(56, 189, 248, 0.7)';
      ctx.fillRect(flagX, flagY, flagW, flagH);
      ctx.fillStyle = '#08090d';
      ctx.fillText(label, flagX + 3, flagY + 10);
    }
    if (isDragTarget) {
      ctx.font = '10px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(56, 189, 248, 0.95)';
      ctx.fillText(fmtTime(m.time), x + 4, h / 2);
    }
  }

  // Compute absolute bar offset per part from DB bar counts
  const parts = getSortedParts(selectedSongId);
  const partStartBar = {};
  let absCounter = 1;
  for (let pi = 0; pi < parts.length; pi++) {
    partStartBar[pi] = absCounter;
    absCounter += (parts[pi].bars || 0);
  }

  // Ghost markers: expected part positions from DB (dashed, dimmed)
  const song = db.songs[selectedSongId];
  if (song && song.bpm > 0 && parts.length > 0) {
    const starts = calcPartStarts(selectedSongId);
    ctx.setLineDash([4, 4]);
    for (let pi = 0; pi < parts.length; pi++) {
      const st = starts.get(parts[pi].id);
      if (!st || st.startSec <= 0) continue;
      const vx = (st.startSec / duration) * totalW;
      if (!inView(vx)) continue;
      const x = vToC(vx);
      ctx.strokeStyle = 'rgba(240, 160, 48, 0.25)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      const hasTapped = partMarkers.some(m => m.partIndex === pi);
      if (!hasTapped) {
        ctx.font = '9px Sora, sans-serif';
        ctx.fillStyle = 'rgba(240, 160, 48, 0.35)';
        const label = parts[pi].name;
        ctx.fillText(label, x + 3, 11);
      }
    }
    ctx.setLineDash([]);
  }

  // Part markers (amber) with flag labels as drag handles
  for (let pi2 = 0; pi2 < partMarkers.length; pi2++) {
    const m = partMarkers[pi2];
    const vx = (m.time / duration) * totalW;
    if (!inView(vx)) continue;
    const x = vToC(vx);
    const isDragTarget = _isDragging && _dragMarker && _dragMarker.type === 'part' && _dragMarker.index === pi2;
    ctx.strokeStyle = isDragTarget ? 'rgba(240, 160, 48, 1.0)' : 'rgba(240, 160, 48, 0.8)';
    ctx.lineWidth = isDragTarget ? 3 : 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();

    const partName = m.partIndex < parts.length ? parts[m.partIndex].name : '';
    if (partName) {
      ctx.font = 'bold 10px Sora, sans-serif';
      const tw = ctx.measureText(partName).width;
      const flagW = tw + 8;
      const flagH = 16;
      ctx.fillStyle = isDragTarget ? 'rgba(240, 160, 48, 1.0)' : 'rgba(240, 160, 48, 0.9)';
      ctx.fillRect(x, 0, flagW, flagH);
      ctx.fillStyle = '#08090d';
      ctx.fillText(partName, x + 4, 12);
    }

    const firstBarIdx = barMarkers.findIndex(b => b.partIndex === m.partIndex);
    const startBar = firstBarIdx >= 0 ? firstBarIdx + 1 : partStartBar[m.partIndex];
    if (isDragTarget) {
      ctx.font = '11px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(240, 160, 48, 1.0)';
      ctx.fillText(fmtTime(m.time), x + 4, h / 2);
    } else if (startBar !== undefined) {
      ctx.font = '9px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(240, 160, 48, 0.7)';
      ctx.fillText(String(startBar), x + 3, h - 4);
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

    // Auto-scroll to keep playhead visible when zoomed
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
 * If data-part-idx is set, Start/Ende flags and bar markers are drawn.
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
      // Draw markers overlay for Parts tab waveforms
      if (c.dataset.partIdx !== undefined && c.dataset.partIdx !== '') {
        drawMiniWaveformMarkers(c, start, end, parseInt(c.dataset.partIdx, 10));
      }
    }
  }
}

/**
 * Draw Start/Ende flags and bar markers on a mini waveform canvas.
 * Uses the same inverse label style as the Audio Split Tab markers.
 */
function drawMiniWaveformMarkers(canvas, startSec, endSec, partIndex) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w <= 0 || h <= 0) return;

  const ctx = canvas.getContext('2d');
  ctx.save();
  ctx.scale(dpr, dpr);

  const partDur = endSec - startSec;
  if (partDur <= 0) { ctx.restore(); return; }

  // Bar markers (cyan vertical lines — no flags in overview, flags only in finetuning)
  const bars = getBarMarkersForPart(partIndex);
  if (bars.length > 0) {
    for (let i = 0; i < bars.length; i++) {
      const x = ((bars[i].time - startSec) / partDur) * w;
      if (x < 1 || x > w - 1) continue;
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
  }

  // Start marker (amber, left edge — line only, no flag)
  ctx.strokeStyle = 'rgba(240, 160, 48, 0.8)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(0, h);
  ctx.stroke();

  // Ende marker (amber, right edge — line only, no flag)
  ctx.strokeStyle = 'rgba(240, 160, 48, 0.8)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(w, 0);
  ctx.lineTo(w, h);
  ctx.stroke();

  ctx.restore();
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
 * Returns { type: 'part'|'bar', index, marker, distPx } or null.
 */
function hitTestMarker(xPx, yPx) {
  if (!audioMeta) return null;
  const scroll = document.getElementById('waveform-scroll');
  if (!scroll) return null;
  const totalW = scroll.getBoundingClientRect().width;
  const duration = audioMeta.duration;
  const canvas = document.getElementById('waveform-scroll');
  const canvasH = canvas ? canvas.height : 100;
  if (duration <= 0 || totalW <= 0) return null;

  let best = null;
  let bestDist = DRAG_HIT_PX + 1;

  // Check part markers — flag area is wider hit target (top 16px)
  const parts = getSortedParts(selectedSongId);
  for (let i = 0; i < partMarkers.length; i++) {
    const mx = (partMarkers[i].time / duration) * totalW;
    const dist = Math.abs(xPx - mx);
    // If click is in flag area (top), use wider hit zone based on flag width
    let inFlag = false;
    if (yPx !== undefined && yPx <= 16) {
      const partName = partMarkers[i].partIndex < parts.length ? parts[partMarkers[i].partIndex].name : '';
      if (partName) {
        // Approximate flag width: measure roughly 7px per char + 8px padding
        const flagW = partName.length * 7 + 8;
        if (xPx >= mx && xPx <= mx + flagW) inFlag = true;
      }
    }
    if (inFlag) {
      // Flag hit always wins for part markers
      best = { type: 'part', index: i, marker: partMarkers[i], distPx: 0 };
      bestDist = 0;
    } else if (dist < bestDist) {
      bestDist = dist;
      best = { type: 'part', index: i, marker: partMarkers[i], distPx: dist };
    }
  }

  // Check bar markers — flag area at bottom (14px height)
  for (let i = 0; i < barMarkers.length; i++) {
    const mx = (barMarkers[i].time / duration) * totalW;
    const dist = Math.abs(xPx - mx);
    // If click is in flag area (bottom), use wider hit zone
    let inFlag = false;
    if (yPx !== undefined && yPx >= canvasH - 14) {
      const isPartStart = partMarkers.some(pm => Math.abs(pm.time - barMarkers[i].time) < 0.01);
      if (!isPartStart) {
        const label = String(i + 1);
        const flagW = label.length * 7 + 6;
        if (xPx >= mx && xPx <= mx + flagW) inFlag = true;
      }
    }
    if (inFlag && (!best || best.type !== 'part' || best.distPx > 0)) {
      best = { type: 'bar', index: i, marker: barMarkers[i], distPx: 0 };
      bestDist = 0;
    } else if (dist < bestDist) {
      bestDist = dist;
      best = { type: 'bar', index: i, marker: barMarkers[i], distPx: dist };
    }
  }

  return best && best.distPx <= DRAG_HIT_PX ? best : null;
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
    type: hit.type,
    index: hit.index,
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
function getDragBounds(type, index) {
  const duration = audioMeta ? audioMeta.duration : Infinity;
  const markers = type === 'part' ? partMarkers : barMarkers;
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  const sortedIdx = sorted.findIndex(m => m === markers[index]);
  const min = sortedIdx > 0 ? sorted[sortedIdx - 1].time + MIN_MARKER_GAP : 0;
  const max = sortedIdx < sorted.length - 1 ? sorted[sortedIdx + 1].time - MIN_MARKER_GAP : duration;

  // For bar markers, also constrain to stay within the part boundaries
  if (type === 'bar') {
    const bm = markers[index];
    const partStart = partMarkers.find(pm => pm.partIndex === bm.partIndex);
    const nextPart = partMarkers.find(pm => pm.partIndex === bm.partIndex + 1);
    return {
      min: Math.max(min, partStart ? partStart.time : 0),
      max: Math.min(max, nextPart ? nextPart.time - MIN_MARKER_GAP : duration),
    };
  }
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
      const bounds = getDragBounds(_dragMarker.type, _dragMarker.index);
      const newTime = Math.max(bounds.min, Math.min(bounds.max, rawTime));

      // Update marker time
      if (_dragMarker.type === 'part') {
        const oldTime = partMarkers[_dragMarker.index].time;
        partMarkers[_dragMarker.index].time = newTime;
        // Move the nearest bar marker along with the part marker (0.2s tolerance)
        // Search ALL bar markers regardless of partIndex — a bar just before
        // the part marker belongs to the previous part but should still follow
        let nearestBar = null;
        let nearestDist = Infinity;
        for (const bm of barMarkers) {
          const d = Math.abs(bm.time - oldTime);
          if (d < nearestDist) { nearestBar = bm; nearestDist = d; }
        }
        if (nearestBar && nearestDist < 0.2) {
          nearestBar.time = newTime;
        }
      } else {
        barMarkers[_dragMarker.index].time = newTime;
      }

      drawWaveform();

      // Show floating balloon above finger during touch drag
      if (_isTouchDrag) {
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        const parts = getSortedParts(selectedSongId);
        let label, color;
        if (_dragMarker.type === 'part') {
          const pi = partMarkers[_dragMarker.index].partIndex;
          label = pi < parts.length ? parts[pi].name : `Part ${pi + 1}`;
          color = '#f0a030';
        } else {
          label = `Bar ${_dragMarker.index + 1}`;
          color = '#38bdf8';
        }
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
      // Revert marker to original position
      const markers = _dragMarker.type === 'part' ? partMarkers : barMarkers;
      if (markers[_dragMarker.index]) {
        markers[_dragMarker.index].time = _dragMarker.originalTime;
      }
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

  if (_dragMarker && _isDragging) {
    // Finalize drag — snap first bar of each part to part marker
    snapFirstBarsToPartMarkers();

    // Sort markers by time to maintain order
    partMarkers.sort((a, b) => a.time - b.time);
    barMarkers.sort((a, b) => a.time - b.time);

    // Re-index part markers sequentially
    partMarkers.forEach((m, i) => { m.partIndex = i; });
    // Re-assign bar markers to correct parts based on time
    reassignBarMarkerParts();

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

/**
 * After dragging, re-assign each bar marker to the correct part based on time.
 */
function reassignBarMarkerParts() {
  for (const bm of barMarkers) {
    let assignedPart = 0;
    for (const pm of partMarkers) {
      if (pm.time <= bm.time) assignedPart = pm.partIndex;
    }
    bm.partIndex = assignedPart;
  }
  // Update currentBarInPart
  if (currentPartIndex > 0) {
    currentBarInPart = barMarkers.filter(m => m.partIndex === currentPartIndex - 1).length;
  }
}

/**
 * Ensure the first bar marker of each part is snapped to its part marker time.
 */
function snapFirstBarsToPartMarkers() {
  const SNAP_TOLERANCE = 0.2; // seconds
  for (const pm of partMarkers) {
    // Find the nearest bar marker across ALL bars (regardless of partIndex)
    let nearest = null;
    let nearestDist = Infinity;
    for (const bm of barMarkers) {
      const d = Math.abs(bm.time - pm.time);
      if (d < nearestDist) { nearest = bm; nearestDist = d; }
    }
    if (nearest && nearestDist <= SNAP_TOLERANCE) {
      nearest.time = pm.time;
    }
  }
}

/**
 * After Part-Reorder in the editor, update split_markers partIndex values
 * to match the new part order. Uses partIndex → partId mapping before reorder
 * and rebuilds the mapping after.
 */
function updateSplitMarkersAfterReorder(song) {
  if (!song || !song.split_markers) return;
  const parts = getSortedParts(song === db.songs[selectedSongId] ? selectedSongId : null);
  if (!parts.length) return;

  // Build new index map: pos (0-based) → partIndex should be sequential
  // Reassign partIndex on both part and bar markers based on the new part order
  const pm = song.split_markers.partMarkers || [];
  const bm = song.split_markers.barMarkers || [];

  // Sort part markers by time (their position doesn't change)
  pm.sort((a, b) => a.time - b.time);
  // Re-index sequentially
  pm.forEach((m, i) => { m.partIndex = i; });

  // Re-assign bar markers to parts by time
  for (const b of bm) {
    let assigned = 0;
    for (const p of pm) {
      if (p.time <= b.time) assigned = p.partIndex;
    }
    b.partIndex = assigned;
  }

  // Also update in-memory markers if this is the currently selected song
  if (song === db.songs[selectedSongId]) {
    partMarkers = pm.map(m => ({ ...m }));
    barMarkers = bm.map(m => ({ ...m }));
  }
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
        `Durch das Ersetzen k\u00f6nnen alle bestehenden Zeitinformationen (Part-Marker, Bar-Marker, Audio-Segmente) ung\u00fcltig werden.<br><br>` +
        `<strong>Trotzdem ersetzen?</strong>`,
        'Ersetzen'
      );
      if (!confirmed) {
        toast('Lade bestehende Referenz-Audio...', 'info');
        await loadReferenceAudio();
        return;
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

    // Re-render the active tab that uses audio
    if (selectedSongId === songId) {
      if (activeTab === 'audio') renderAudioTab();
      else if (activeTab === 'lyrics') renderLyricsTab();
      else if (activeTab === 'parts') renderPartsTab();
      else if (activeTab === 'takte') renderTakteTab();
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
  drawWaveform();
  updateTransportDisplay();
}

function handlePlayPause() {
  if (!audio.getBuffer()) return;
  if (audio.isPlaying()) {
    audio.pause();
    stopPlayheadAnimation();
    updateTapButtonStates();
  } else {
    // play() is synchronous — starts source immediately.
    // If AudioContext was suspended, audio + playhead sync via statechange listener.
    audio.play(() => {
      stopPlayheadAnimation();
      updateTapButtonStates();
      updatePlayButton();
    });
    startPlayheadAnimation();
    updateTapButtonStates();
  }
  updatePlayButton();
}

function handleSkipToStart() {
  audio.seek(0);
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
  const parts = getSortedParts(selectedSongId);
  const partBtn = document.getElementById('tap-part');
  const barBtn = document.getElementById('tap-bar');
  const undoBtn = document.getElementById('tap-undo');
  const delPartsBtn = document.getElementById('tap-delete-parts');
  const delBarsBtn = document.getElementById('tap-delete-bars');

  if (partBtn) partBtn.disabled = !isPlay;
  if (barBtn) barBtn.disabled = !isPlay || currentPartIndex === 0;
  if (undoBtn) undoBtn.disabled = tapHistory.length === 0;
  if (delPartsBtn) delPartsBtn.disabled = partMarkers.length === 0;
  if (delBarsBtn) delBarsBtn.disabled = barMarkers.length === 0;
}

function handlePartTap() {
  if (!audio.isPlaying()) return;
  let parts = getSortedParts(selectedSongId);

  // Auto-create a new part if no parts exist or all are already tapped
  let autoCreatedPartId = null;
  if (currentPartIndex >= parts.length) {
    const song = db.songs[selectedSongId];
    if (!song) return;
    const newPos = parts.length > 0 ? Math.max(...parts.map(p => p.pos)) + 1 : 1;
    const newId = nextPartId(selectedSongId);
    song.parts[newId] = {
      pos: newPos, name: `Part ${newPos}`, bars: 0, duration_sec: 0,
      light_template: '', notes: ''
    };
    autoCreatedPartId = newId;
    parts = getSortedParts(selectedSongId);
  }

  // Compensate for audio output latency: user taps when they hear the beat,
  // but getCurrentTime() is ahead by the output latency
  const time = Math.max(0, audio.getCurrentTime() - audio.getOutputLatency());

  // Add part marker
  partMarkers.push({ time, partIndex: currentPartIndex });

  // Automatically add first bar marker at the same position as the part marker
  barMarkers.push({ time, partIndex: currentPartIndex });

  // Record for undo (both part + auto-bar)
  tapHistory.push({ type: 'part', time, partIndex: currentPartIndex, autoBar: true, autoCreatedPartId });

  currentPartIndex++;
  currentBarInPart = 1; // first bar already added

  // Persist markers to song object
  saveMarkersToSong();
  markDirty();

  // Update UI elements without full re-render
  drawWaveform();
  updateTapInfo(parts);
  updateSplitResultLive(parts);
  updateAudioSummaryLive(parts);
}

function handleBarTap() {
  if (!audio.isPlaying()) return;
  if (currentPartIndex === 0) return; // No part started yet

  // Compensate for audio output latency
  const time = Math.max(0, audio.getCurrentTime() - audio.getOutputLatency());

  // Determine which part this bar belongs to based on playback time
  const activePartIdx = getPartIndexForTime(time);

  barMarkers.push({ time, partIndex: activePartIdx });
  tapHistory.push({ type: 'bar', time, partIndex: activePartIdx });
  currentBarInPart = barMarkers.filter(m => m.partIndex === activePartIdx).length;

  // Persist markers to song object
  saveMarkersToSong();
  markDirty();

  drawWaveform();
  updateTapInfo(getSortedParts(selectedSongId));
  updateSplitResultLive(getSortedParts(selectedSongId));
  updateAudioSummaryLive(getSortedParts(selectedSongId));
}

/**
 * Find the partIndex for a given time based on part markers.
 * Returns the index of the last part whose start time is <= the given time.
 */
function getPartIndexForTime(time) {
  let idx = 0;
  for (const m of partMarkers) {
    if (m.time <= time) idx = m.partIndex;
  }
  return idx;
}

function handleUndoTap() {
  if (tapHistory.length === 0) return;
  const last = tapHistory.pop();

  if (last.type === 'part') {
    // Remove the part marker
    partMarkers = partMarkers.filter(m => m.time !== last.time || m.partIndex !== last.partIndex);
    // Also remove the auto-bar if it was added with the part tap
    if (last.autoBar) {
      barMarkers = barMarkers.filter(m => !(Math.abs(m.time - last.time) < 0.001 && m.partIndex === last.partIndex));
    }
    currentPartIndex--;
    // Remove dynamically created part if it was auto-created during tapping
    if (last.autoCreatedPartId) {
      const song = db.songs[selectedSongId];
      if (song && song.parts[last.autoCreatedPartId]) {
        delete song.parts[last.autoCreatedPartId];
      }
    }
    // Recalculate currentBarInPart for previous part
    if (currentPartIndex > 0) {
      const prevPartIdx = currentPartIndex - 1;
      currentBarInPart = barMarkers.filter(m => m.partIndex === prevPartIdx).length;
    } else {
      currentBarInPart = 0;
    }
  } else {
    // Remove the bar marker
    barMarkers = barMarkers.filter(m => m.time !== last.time || m.partIndex !== last.partIndex);
    currentBarInPart = barMarkers.filter(m => m.partIndex === last.partIndex).length;
  }

  // Persist updated markers
  saveMarkersToSong();
  markDirty();

  drawWaveform();
  const parts = getSortedParts(selectedSongId);
  updateTapInfo(parts);
  updateSplitResultLive(parts);
  updateAudioSummaryLive(parts);
  updateTapButtonStates();
}

function handleDistributeParts() {
  if (!audioMeta) return;
  const parts = getSortedParts(selectedSongId);
  if (parts.length < 2) return;
  const duration = audioMeta.duration;

  // Create part markers if they don't exist yet
  if (partMarkers.length === 0) {
    for (let i = 0; i < parts.length; i++) {
      partMarkers.push({ time: 0, partIndex: i });
    }
    currentPartIndex = parts.length;
  }

  // Distribute evenly: first part at 0, rest equally spaced
  const count = partMarkers.length;
  const gap = duration / count;
  partMarkers.sort((a, b) => a.partIndex - b.partIndex);
  for (let i = 0; i < count; i++) {
    partMarkers[i].time = i * gap;
  }

  partMarkers.sort((a, b) => a.time - b.time);
  snapFirstBarsToPartMarkers();
  reassignBarMarkerParts();
  saveMarkersToSong();
  markDirty();
  renderAudioTab();
  toast(`${count} Parts gleichmäßig verteilt`);
}

async function handleDeleteAllParts() {
  if (partMarkers.length === 0) return;
  const ok = await showConfirm(
    'Alle Parts löschen?',
    `Alle <strong>${partMarkers.length} Part-Marker</strong> und <strong>${barMarkers.length} Bar-Marker</strong> werden entfernt.`,
    'Löschen'
  );
  if (!ok) return;
  // Remove dynamically created parts from DB
  const song = db.songs[selectedSongId];
  if (song) {
    for (const entry of tapHistory) {
      if (entry.autoCreatedPartId && song.parts[entry.autoCreatedPartId]) {
        delete song.parts[entry.autoCreatedPartId];
      }
    }
  }
  partMarkers = [];
  barMarkers = [];
  tapHistory = [];
  currentPartIndex = 0;
  currentBarInPart = 0;
  saveMarkersToSong();
  // Sync: also delete db.bars and db.accents for this song
  if (selectedSongId) {
    ensureCollections();
    const partsAfter = getSortedParts(selectedSongId);
    const partIds = new Set(partsAfter.map(p => p.id));
    for (const [barId, bar] of Object.entries(db.bars)) {
      if (partIds.has(bar.part_id)) {
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

function handleSnapToPeaks() {
  if (!audio.getBuffer()) return;
  const totalMarkers = partMarkers.length + barMarkers.length;
  if (totalMarkers === 0) return;

  let snapped = 0;
  // Snap part markers
  for (const m of partMarkers) {
    const newTime = audio.findPeakNear(m.time, 80);
    if (Math.abs(newTime - m.time) > 0.001) { m.time = newTime; snapped++; }
  }
  // Snap bar markers, skip first bar of each part (it should follow its part marker)
  for (const m of barMarkers) {
    // Check if this is a first bar (same time as its part marker)
    const isFirstBar = partMarkers.some(pm => pm.partIndex === m.partIndex && Math.abs(pm.time - m.time) < 0.01);
    if (isFirstBar) {
      // Sync first bar to its part marker
      const pm = partMarkers.find(p => p.partIndex === m.partIndex);
      if (pm && Math.abs(m.time - pm.time) > 0.001) { m.time = pm.time; snapped++; }
      continue;
    }
    const newTime = audio.findPeakNear(m.time, 80);
    if (Math.abs(newTime - m.time) > 0.001) { m.time = newTime; snapped++; }
  }

  // Re-sort
  partMarkers.sort((a, b) => a.time - b.time);
  barMarkers.sort((a, b) => a.time - b.time);
  saveMarkersToSong();
  markDirty();
  drawWaveform();
  const parts = getSortedParts(selectedSongId);
  updateSplitResultLive(parts);
  updateAudioSummaryLive(parts);
  toast(`${snapped} Marker auf Peaks verschoben`, 'success');
}

async function handleDeleteAllBarMarkers() {
  if (barMarkers.length === 0) return;
  const ok = await showConfirm(
    'Alle Takte löschen?',
    `Alle <strong>${barMarkers.length} Bar-Marker</strong> werden entfernt. Part-Marker bleiben erhalten.`,
    'Löschen'
  );
  if (!ok) return;
  barMarkers = [];
  tapHistory = tapHistory.filter(h => h.type !== 'bar');
  currentBarInPart = 0;
  saveMarkersToSong();
  // Sync: also delete db.bars and db.accents for this song
  if (selectedSongId) {
    ensureCollections();
    const parts = getSortedParts(selectedSongId);
    const partIds = new Set(parts.map(p => p.id));
    for (const [barId, bar] of Object.entries(db.bars)) {
      if (partIds.has(bar.part_id)) {
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

/* ── Speed / Zoom / Part-Seek / Marker Edit ─────── */

const SPEED_STEPS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5];
const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6, 8, 10, 14, 20];

function handleSpeedChange(dir) {
  const curIdx = SPEED_STEPS.indexOf(playbackSpeed);
  const idx = curIdx === -1 ? SPEED_STEPS.indexOf(1.0) : curIdx;
  const newIdx = Math.max(0, Math.min(SPEED_STEPS.length - 1, idx + dir));
  playbackSpeed = SPEED_STEPS[newIdx];
  audio.setPlaybackRate(playbackSpeed);
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

function handleSplitRowClick(row) {
  const rows = Array.from(row.parentElement.children);
  const idx = rows.indexOf(row);
  if (idx < 0) return;
  const startTime = getPartStartTime(idx);
  if (startTime === null) return;
  audio.seek(startTime);
  drawWaveform();
  updateTransportDisplay();
}

function handleMarkerDelete(btn) {
  const type = btn.dataset.type;    // 'part' or 'bar'
  const time = parseFloat(btn.dataset.time);
  const partIdx = parseInt(btn.dataset.part, 10);
  if (isNaN(time)) return;

  if (type === 'part') {
    // Remove part marker and all bars belonging to this part
    partMarkers = partMarkers.filter(m => m.partIndex !== partIdx);
    barMarkers = barMarkers.filter(m => m.partIndex !== partIdx);
    // Shift subsequent part indices down
    partMarkers.forEach(m => { if (m.partIndex > partIdx) m.partIndex--; });
    barMarkers.forEach(m => { if (m.partIndex > partIdx) m.partIndex--; });
    currentPartIndex = Math.max(0, currentPartIndex - 1);
    // Recalculate bar counter
    if (currentPartIndex > 0) {
      currentBarInPart = barMarkers.filter(m => m.partIndex === currentPartIndex - 1).length;
    } else {
      currentBarInPart = 0;
    }
  } else {
    // Remove single bar marker
    barMarkers = barMarkers.filter(m => !(Math.abs(m.time - time) < 0.001 && m.partIndex === partIdx));
    if (partIdx === currentPartIndex - 1) {
      currentBarInPart = barMarkers.filter(m => m.partIndex === partIdx).length;
    }
  }

  // Clear undo history (no longer reliable)
  tapHistory = [];
  saveMarkersToSong();
  markDirty();
  drawWaveform();
  renderAudioTab();
}

function updateTapInfo(parts) {
  const partBtn = document.getElementById('tap-part');
  const barBtn = document.getElementById('tap-bar');

  if (partBtn) {
    const info = partBtn.querySelector('.tap-info');
    const nextName = currentPartIndex < parts.length
      ? parts[currentPartIndex].name
      : `Part ${currentPartIndex + 1}`;
    if (info) info.textContent = nextName;
    partBtn.disabled = !audio.isPlaying();
  }
  if (barBtn) {
    const info = barBtn.querySelector('.tap-info');
    if (info) info.textContent = `Bar ${barMarkers.length + 1}`;
    barBtn.disabled = !audio.isPlaying() || currentPartIndex === 0;
  }

  const undoBtn = document.getElementById('tap-undo');
  if (undoBtn) undoBtn.disabled = tapHistory.length === 0;

  const delPartsBtn = document.getElementById('tap-delete-parts');
  if (delPartsBtn) {
    delPartsBtn.disabled = partMarkers.length === 0;
    const info = delPartsBtn.querySelector('.tap-info');
    if (info) info.textContent = `${partMarkers.length} Parts`;
  }
  const delBarsBtn = document.getElementById('tap-delete-bars');
  if (delBarsBtn) {
    delBarsBtn.disabled = barMarkers.length === 0;
    const info = delBarsBtn.querySelector('.tap-info');
    if (info) info.textContent = `${barMarkers.length} Takte`;
  }

}

function updateSplitResultLive(parts) {
  const tbody = document.querySelector('.split-table tbody');
  if (!tbody) return;

  const rows = tbody.querySelectorAll('tr');
  parts.forEach((p, i) => {
    if (!rows[i]) return;
    const isDone = i < currentPartIndex;
    const isCurrent = i === currentPartIndex - 1 && currentPartIndex > 0;
    const start = getPartStartTime(i);
    const end = getPartEndTime(i);
    const dur = (start !== null && end !== null) ? end - start : null;
    const barCount = barMarkers.filter(m => m.partIndex === i).length;

    rows[i].className = isCurrent ? 'current' : (isDone ? 'done' : '');
    const tds = rows[i].querySelectorAll('td');
    if (tds[2]) tds[2].textContent = barCount || '\u2014';
    if (tds[3]) tds[3].textContent = start !== null ? fmtTime(start) : '\u2014';
    if (tds[4]) tds[4].textContent = dur !== null ? fmtTime(dur) : '\u2014';
    if (tds[5]) tds[5].textContent = isDone ? '\u2713' : '';
  });
}

function updateAudioSummaryLive(parts) {
  const bar = document.querySelector('.audio-panel .summary-bar');
  if (!bar) return;
  const items = bar.querySelectorAll('.summary-item .mono');
  if (items[0]) items[0].textContent = partMarkers.length;
  if (items[1]) items[1].textContent = barMarkers.length;
  if (items[2]) items[2].textContent = estimateBpm() || '\u2014';
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

/**
 * Get sorted bar markers for a given partIndex.
 */
function getBarMarkersForPart(partIndex) {
  return barMarkers
    .filter(m => m.partIndex === partIndex)
    .sort((a, b) => a.time - b.time);
}

async function handleAudioExport() {
  if (!selectedSongId || !audioMeta || exportInProgress) return;
  const s = getSettings();
  if (!s.token || !s.repo) {
    toast('GitHub Token in Settings erforderlich', 'error');
    return;
  }

  const parts = getSortedParts(selectedSongId);
  if (partMarkers.length === 0) return;

  exportInProgress = true;

  // Count total bars across all parts
  const totalBars = barMarkers.length;
  let done = 0;
  toast(`Audio-Export: 0/${totalBars} Takte...`, 'info');

  ensureCollections();

  try {
    const song = db.songs[selectedSongId];
    const songName = song.name;
    let globalBarOffset = 0;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const partEnd = getPartEndTime(i);
      const bars = getBarMarkersForPart(i);

      // Update bars count in part (even if no bars were tapped)
      if (song.parts[part.id]) {
        song.parts[part.id].bars = bars.length;
      }

      if (bars.length === 0 || partEnd === null) continue;

      // Clean up old bars that exceed the new bar count
      const oldBars = Object.entries(db.bars)
        .filter(([, b]) => b.part_id === part.id)
        .sort((a, b) => a[1].bar_num - b[1].bar_num);

      for (const [oldBarId, oldBar] of oldBars) {
        if (oldBar.bar_num > bars.length) {
          // Delete orphaned audio file from GitHub
          if (oldBar.audio) {
            try {
              await deleteFile(s.repo, oldBar.audio, s.token,
                `Cleanup: ${part.name} Bar ${oldBar.bar_num} (${songName})`);
            } catch { /* ok if file doesn't exist */ }
          }
          // Remove accents for this bar
          for (const [accId, acc] of Object.entries(db.accents || {})) {
            if (acc.bar_id === oldBarId) delete db.accents[accId];
          }
          delete db.bars[oldBarId];
        }
      }

      for (let b = 0; b < bars.length; b++) {
        const barStart = bars[b].time;
        const barEnd = (b + 1 < bars.length) ? bars[b + 1].time : partEnd;
        const barNum = b + 1;
        const globalBarNum = globalBarOffset + barNum;

        const base64mp3 = await audio.exportSegmentMp3(barStart, barEnd);
        const path = buildBarAudioPath(song, part, barNum, globalBarNum);

        await uploadFile(s.repo, path, s.token, base64mp3, `Audio: ${part.name} Bar ${barNum} (${songName})`);

        // Update bar record in DB (preserves existing lyrics/accents)
        const [barId, barData] = getOrCreateBar(part.id, barNum);
        barData.audio = path;

        done++;
        if (done % 10 === 0 || done === totalBars) {
          toast(`Audio-Export: ${done}/${totalBars} Takte...`, 'info');
        }
      }

      globalBarOffset += bars.length;
    }

    saveMarkersToSong();
    markDirty();
    toast(done > 0 ? `${done} Bar-Segmente exportiert` : 'Part-Daten gespeichert', 'success');
  } catch (err) {
    toast(`Export-Fehler: ${err.message}`, 'error', 5000);
  } finally {
    exportInProgress = false;
    // Save DB again to persist audio paths
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

  // Speed control
  if (el.closest('#t-speed-down')) { handleSpeedChange(-1); return; }
  if (el.closest('#t-speed-up')) { handleSpeedChange(1); return; }

  // Zoom control
  if (el.closest('#t-zoom-out')) { handleZoomChange(-1); return; }
  if (el.closest('#t-zoom-in')) { handleZoomChange(1); return; }

  // Marker delete button (check BEFORE row click)
  if (el.closest('.marker-delete')) { handleMarkerDelete(el.closest('.marker-delete')); return; }

  // Split result row click → seek to part start
  const splitRow = el.closest('.split-table tbody tr');
  if (splitRow) { handleSplitRowClick(splitRow); return; }

  // Tap buttons
  if (el.closest('#tap-part') && !el.closest('#tap-part').disabled) { handlePartTap(); return; }
  if (el.closest('#tap-bar') && !el.closest('#tap-bar').disabled) { handleBarTap(); return; }
  if (el.closest('#tap-undo') && !el.closest('#tap-undo').disabled) { handleUndoTap(); return; }
  if (el.closest('#tap-distribute-parts') && !el.closest('#tap-distribute-parts').disabled) { handleDistributeParts(); return; }
  if (el.closest('#tap-snap-peaks') && !el.closest('#tap-snap-peaks').disabled) { handleSnapToPeaks(); return; }
  if (el.closest('#tap-delete-parts') && !el.closest('#tap-delete-parts').disabled) { handleDeleteAllParts(); return; }
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
   LYRICS EDITOR — Grafischer Marker-Editor
   Phasen: empty → parts (Part-Marker setzen) → bars (Takt-Marker setzen)
   ══════════════════════════════════════════════════════ */

/* ── Lyrics Editor: Parse raw text into word tokens ── */

/**
 * Parse raw lyrics text into word tokens.
 * Each token: {text, offset, newlineBefore, emptyLineBefore, isHeader}
 * Section headers like [Verse 1] are tagged as isHeader.
 */
function leParseRawText(rawText) {
  const words = [];
  if (!rawText) return words;
  const lines = rawText.split('\n');
  let absOffset = 0;
  let prevLineEmpty = false;

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    const trimmed = line.trim();

    if (trimmed === '') {
      prevLineEmpty = true;
      absOffset += line.length + 1;
      continue;
    }

    const isHeader = /^\[.*\]$/.test(trimmed);

    if (isHeader) {
      const headerOffset = absOffset + line.indexOf(trimmed);
      words.push({
        text: trimmed,
        offset: headerOffset,
        newlineBefore: li > 0 && !prevLineEmpty,
        emptyLineBefore: prevLineEmpty,
        isHeader: true
      });
    } else {
      const lineWords = trimmed.split(/\s+/);
      let localOffset = line.indexOf(trimmed);
      for (let wi = 0; wi < lineWords.length; wi++) {
        const w = lineWords[wi];
        const wOffset = line.indexOf(w, localOffset);
        words.push({
          text: w,
          offset: absOffset + wOffset,
          newlineBefore: wi === 0 && li > 0 && !prevLineEmpty,
          emptyLineBefore: wi === 0 && prevLineEmpty,
          isHeader: false
        });
        localOffset = wOffset + w.length;
      }
    }
    prevLineEmpty = false;
    absOffset += line.length + 1;
  }
  return words;
}

/**
 * Check if any bars for the given parts have lyrics.
 */
function leHasAnyBarLyrics(parts) {
  ensureCollections();
  for (const p of parts) {
    for (const [, b] of Object.entries(db.bars)) {
      if (b.part_id === p.id && b.lyrics) return true;
    }
  }
  return false;
}

/* ── Lyrics Editor: Marker Prediction ────────────── */

/** Synonyms for section header → part name matching */
const SECTION_SYNONYMS = {
  'verse': ['verse', 'strophe', 'stanza'],
  'chorus': ['chorus', 'refrain', 'hook'],
  'pre-chorus': ['pre-chorus', 'prechorus', 'pre chorus'],
  'bridge': ['bridge', 'bruecke', 'brücke', 'middle 8'],
  'outro': ['outro', 'ending', 'coda'],
  'intro': ['intro', 'opening'],
  'solo': ['solo', 'guitar solo', 'instrumental'],
  'breakdown': ['breakdown', 'break'],
  'interlude': ['interlude', 'zwischenspiel'],
  'post-chorus': ['post-chorus', 'postchorus', 'post chorus'],
};

function matchSectionToPartName(header) {
  const clean = header.replace(/[\[\]]/g, '').replace(/\s*\d+\s*$/, '').trim().toLowerCase();
  for (const [base, syns] of Object.entries(SECTION_SYNONYMS)) {
    if (syns.some(s => clean === s || clean.startsWith(s))) return base;
  }
  return clean;
}

function normalizePartName(name) {
  const clean = (name || '').replace(/\s*\d+\s*$/, '').trim().toLowerCase();
  for (const [base, syns] of Object.entries(SECTION_SYNONYMS)) {
    if (syns.some(s => clean === s || clean.startsWith(s))) return base;
  }
  return clean;
}

/**
 * Auto-predict part marker positions in the raw text.
 * Uses section headers [Verse 1] etc. to match parts.
 */
function leGuessPartMarkers(words, parts) {
  const markers = [];
  const textParts = parts.filter(p => !p.instrumental && (p.bars || 0) > 0);
  if (textParts.length === 0) return markers;

  // Find section headers in words
  const headers = []; // [{wordIdx, header, base, num}]
  for (let i = 0; i < words.length; i++) {
    if (words[i].isHeader) {
      const base = matchSectionToPartName(words[i].text);
      const numMatch = words[i].text.replace(/[\[\]]/g, '').match(/\s+(\d+)\s*$/);
      headers.push({ wordIdx: i, header: words[i].text, base, num: numMatch ? parseInt(numMatch[1], 10) : null });
    }
  }

  // Count part occurrences for matching numbered headers
  const partOccurrence = new Map();
  const baseCount = {};
  for (const part of textParts) {
    const base = normalizePartName(part.name);
    baseCount[base] = (baseCount[base] || 0) + 1;
    partOccurrence.set(part.id, baseCount[base]);
  }

  // Match headers to parts
  const usedHeaders = new Set();
  for (const part of textParts) {
    const partBase = normalizePartName(part.name);
    const partOcc = partOccurrence.get(part.id);

    for (const h of headers) {
      if (usedHeaders.has(h.wordIdx)) continue;
      if (h.base !== partBase) continue;
      if (h.num !== null && h.num !== partOcc) continue;

      // Found match: marker goes right after the header (next non-header word)
      let targetIdx = h.wordIdx + 1;
      while (targetIdx < words.length && words[targetIdx].isHeader) targetIdx++;
      if (targetIdx >= words.length) targetIdx = h.wordIdx;

      markers.push({
        partId: part.id,
        charOffset: words[targetIdx] ? words[targetIdx].offset : words[h.wordIdx].offset,
        confirmed: false
      });
      usedHeaders.add(h.wordIdx);
      break;
    }
  }

  // Parts without matched headers: distribute remaining text evenly
  const unmatchedParts = textParts.filter(p => !markers.some(m => m.partId === p.id));
  if (unmatchedParts.length > 0) {
    // Get the non-header words
    const lyricsWords = words.filter(w => !w.isHeader);
    const matchedOffsets = new Set(markers.map(m => m.charOffset));
    // Distribute unmatched parts across the remaining text
    const totalWords = lyricsWords.length;
    let usedWords = 0;
    // Count words already claimed by matched parts
    const sortedMarkers = [...markers].sort((a, b) => a.charOffset - b.charOffset);

    for (const part of unmatchedParts) {
      // Place marker at proportional position
      const proportion = textParts.indexOf(part) / textParts.length;
      const targetWordIdx = Math.floor(proportion * totalWords);
      const wordAtPos = lyricsWords[Math.min(targetWordIdx, lyricsWords.length - 1)];
      if (wordAtPos) {
        markers.push({
          partId: part.id,
          charOffset: wordAtPos.offset,
          confirmed: false
        });
      }
    }
  }

  // Sort by charOffset
  markers.sort((a, b) => a.charOffset - b.charOffset);
  return markers;
}

/**
 * Predict bar marker positions within parts.
 * Distributes bars evenly across the words of each part.
 */
function leGuessBarMarkers(words, parts, partMarkers) {
  const barMarkers = [];
  const lyricsWords = words.filter(w => !w.isHeader);
  if (lyricsWords.length === 0) return barMarkers;

  const sortedPM = [...partMarkers].sort((a, b) => a.charOffset - b.charOffset);

  for (let pi = 0; pi < sortedPM.length; pi++) {
    const pm = sortedPM[pi];
    const part = db.songs[selectedSongId]?.parts?.[pm.partId];
    if (!part) continue;
    const barCount = part.bars || 0;
    if (barCount === 0) continue;

    // Find the word range for this part
    const startOffset = pm.charOffset;
    const endOffset = (pi + 1 < sortedPM.length) ? sortedPM[pi + 1].charOffset : Infinity;

    const partWords = lyricsWords.filter(w => w.offset >= startOffset && w.offset < endOffset);
    if (partWords.length === 0) {
      // No words in this part segment, place all bar markers at part start
      for (let b = 1; b <= barCount; b++) {
        barMarkers.push({ partId: pm.partId, barNum: b, charOffset: startOffset });
      }
      continue;
    }

    // Distribute bars evenly across words
    for (let b = 0; b < barCount; b++) {
      const wordIdx = Math.round(b * partWords.length / barCount);
      const word = partWords[Math.min(wordIdx, partWords.length - 1)];
      barMarkers.push({
        partId: pm.partId,
        barNum: b + 1,
        charOffset: word.offset
      });
    }
  }

  barMarkers.sort((a, b) => a.charOffset - b.charOffset || a.barNum - b.barNum);
  return barMarkers;
}

/**
 * Reconstruct markers from existing per-bar lyrics stored in DB.
 */
function leReconstructMarkers(rawText, parts) {
  const partMarkers = [];
  const barMarkers = [];
  let searchOffset = 0;

  for (const part of parts) {
    if (part.instrumental) continue;
    const barCount = part.bars || 0;
    if (barCount === 0) continue;

    let partOffset = -1;

    for (let b = 1; b <= barCount; b++) {
      const found = findBar(part.id, b);
      const lyrics = found ? (found[1].lyrics || '').trim() : '';
      if (!lyrics) continue;

      // Find this lyrics text in the raw text (progressive search)
      const idx = rawText.indexOf(lyrics, searchOffset);
      if (idx >= 0) {
        if (partOffset < 0) {
          partOffset = idx;
          partMarkers.push({
            partId: part.id,
            charOffset: idx,
            confirmed: part.lyrics_confirmed || false
          });
        }
        barMarkers.push({
          partId: part.id,
          barNum: b,
          charOffset: idx
        });
        searchOffset = idx + lyrics.length;
      }
    }

    // If no bar lyrics found, still place a part marker
    if (partOffset < 0) {
      partMarkers.push({
        partId: part.id,
        charOffset: searchOffset,
        confirmed: part.lyrics_confirmed || false
      });
    }
  }

  return { partMarkers, barMarkers };
}

/**
 * Re-predict bar markers for a specific part after its part marker was moved.
 */
function leRepredictBarsForPart(partId) {
  // Remove old bar markers for this part
  _leBarMarkers = _leBarMarkers.filter(m => m.partId !== partId);
  // Re-predict using current part markers
  const parts = getSortedParts(selectedSongId);
  const lyricsWords = _leWords.filter(w => !w.isHeader);
  const sortedPM = [..._lePartMarkers].sort((a, b) => a.charOffset - b.charOffset);
  const pmIdx = sortedPM.findIndex(m => m.partId === partId);
  if (pmIdx < 0) return;

  const pm = sortedPM[pmIdx];
  const part = db.songs[selectedSongId]?.parts?.[partId];
  if (!part) return;
  const barCount = part.bars || 0;
  if (barCount === 0) return;

  const startOffset = pm.charOffset;
  const endOffset = (pmIdx + 1 < sortedPM.length) ? sortedPM[pmIdx + 1].charOffset : Infinity;
  const partWords = lyricsWords.filter(w => w.offset >= startOffset && w.offset < endOffset);

  for (let b = 0; b < barCount; b++) {
    const wordIdx = Math.round(b * partWords.length / barCount);
    const word = partWords[Math.min(wordIdx, Math.max(0, partWords.length - 1))];
    _leBarMarkers.push({
      partId: partId,
      barNum: b + 1,
      charOffset: word ? word.offset : startOffset
    });
  }

  _leBarMarkers.sort((a, b) => a.charOffset - b.charOffset || a.barNum - b.barNum);
}

/* ── Lyrics Editor: Init from song data ─────────── */

function leInitFromSong(song, parts) {
  const rawText = song.lyrics_raw || '';
  _leWords = leParseRawText(rawText);
  _leInitSongId = selectedSongId;

  // Try to reconstruct from existing bar lyrics
  const hasBarLyrics = leHasAnyBarLyrics(parts);
  if (hasBarLyrics && rawText) {
    const result = leReconstructMarkers(rawText, parts);
    _lePartMarkers = result.partMarkers;
    _leBarMarkers = result.barMarkers;
    // If we have bar markers, go straight to bars phase
    _lePhase = _leBarMarkers.length > 0 ? 'bars' : 'parts';
  } else if (rawText) {
    // Fresh text: predict part markers
    _lePartMarkers = leGuessPartMarkers(_leWords, parts);
    _leBarMarkers = [];
    _lePhase = 'parts';
  } else {
    _lePhase = 'empty';
    _lePartMarkers = [];
    _leBarMarkers = [];
  }
}

/* ── Lyrics Editor: Rendering ────────────────────── */

function renderLyricsTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Song aus der Liste links ausw&auml;hlen.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  const rawText = song.lyrics_raw || '';
  ensureCollections();

  // Auto-load reference audio
  if (!audio.getBuffer() && song.audio_ref && _refLoadingFor !== selectedSongId) {
    _refLoadingFor = selectedSongId;
    _refLoadingPromise = loadReferenceAudio().finally(() => { _refLoadingFor = null; _refLoadingPromise = null; });
  }

  // Initialize markers if needed (new song or first load)
  if (_leInitSongId !== selectedSongId) {
    if (rawText || leHasAnyBarLyrics(parts)) {
      leInitFromSong(song, parts);
    } else {
      _lePhase = 'empty';
      _lePartMarkers = [];
      _leBarMarkers = [];
      _leWords = [];
      _leInitSongId = selectedSongId;
    }
  }

  const geniusUrl = `https://genius.com/search?q=${encodeURIComponent(song.name + ' ' + song.artist)}`;

  let html = `<div class="lyrics-panel le-panel">
    ${buildSongHeader(song)}
    <div class="le-toolbar">
      <a href="${geniusUrl}" target="_blank" rel="noopener" class="btn btn-sm lyrics-genius-link" title="Auf Genius.com suchen">&#127925; Genius</a>
      <div style="flex:1"></div>`;

  if (_lePhase === 'empty') {
    html += `<button class="btn btn-sm" id="le-paste-btn" title="Text aus Zwischenablage einfügen">&#128203; Einfügen</button>`;
  } else {
    html += `<button class="btn btn-sm le-btn-danger" id="le-clear-btn" title="Text und Marker löschen">L&ouml;schen</button>`;
  }

  html += '</div>';

  if (_lePhase === 'empty') {
    html += `<div class="le-empty-wrap">
      <div id="le-paste-area" class="le-paste-area" contenteditable="true"
           data-placeholder="Songtext hier einf&uuml;gen...\nTipp: Text von Genius.com kopieren und hier einf&uuml;gen.\nOder den Knopf 'Einf&uuml;gen' oben dr&uuml;cken."></div>
    </div>`;
  } else {
    // Phase info bar
    if (_lePhase === 'parts') {
      html += `<div class="le-phase-bar le-phase-parts">
        <span class="le-phase-text">Part-Marker an die richtige Stelle ziehen</span>
        <button class="btn btn-sm le-btn-distribute" id="le-distribute-parts" title="Parts gleichm&auml;&szlig;ig im Text verteilen">&#8646; Verteilen</button>
        <button class="btn btn-sm le-btn-confirm" id="le-confirm-parts">Fertig</button>
      </div>`;
    } else if (_lePhase === 'bars') {
      html += `<div class="le-phase-bar le-phase-bars">
        <span class="le-phase-text">Takt-Marker pr&uuml;fen &amp; anpassen</span>
        <button class="btn btn-sm le-btn-save" id="le-save-lyrics">Fertig</button>
      </div>`;
    }

    // Graphical editor
    html += `<div class="le-editor" id="le-editor">
      <div class="le-text" id="le-text">${buildLyricsEditorContent(rawText)}</div>
    </div>`;

    // Legend
    html += `<div class="le-legend">
      <span class="le-legend-item"><span class="le-legend-swatch le-swatch-part"></span> Part-Marker</span>
      ${_lePhase === 'bars' ? '<span class="le-legend-item"><span class="le-legend-swatch le-swatch-bar"></span> Takt-Marker</span>' : ''}
    </div>`;
  }

  html += '</div>';
  els.content.innerHTML = html;

  // Wire paste area events
  const pasteArea = document.getElementById('le-paste-area');
  if (pasteArea) {
    pasteArea.addEventListener('paste', handleLePaste);
    pasteArea.addEventListener('input', () => {
      const text = pasteArea.innerText.trim();
      if (text.length > 10) leAcceptRawText(text);
    });
  }

  // Wire marker drag events
  leWireMarkerDrag();
}

/**
 * Build the inner HTML of the graphical text editor: words + markers.
 */
function buildLyricsEditorContent(rawText) {
  if (!rawText || _leWords.length === 0) return '';

  // Combine all markers, sorted by charOffset
  const allMarkers = [];
  for (let i = 0; i < _lePartMarkers.length; i++) {
    allMarkers.push({ ..._lePartMarkers[i], type: 'part', idx: i });
  }
  if (_lePhase === 'bars') {
    for (let i = 0; i < _leBarMarkers.length; i++) {
      allMarkers.push({ ..._leBarMarkers[i], type: 'bar', idx: i });
    }
  }
  allMarkers.sort((a, b) => {
    if (a.charOffset !== b.charOffset) return a.charOffset - b.charOffset;
    // Part markers come before bar markers at same position
    if (a.type !== b.type) return a.type === 'part' ? -1 : 1;
    return 0;
  });

  // Build HTML by iterating through words and inserting markers
  let html = '';
  let markerIdx = 0;
  let lastWasPartMarker = false;

  for (let wi = 0; wi < _leWords.length; wi++) {
    const word = _leWords[wi];

    // Insert any markers that belong before this word
    lastWasPartMarker = false;
    while (markerIdx < allMarkers.length && allMarkers[markerIdx].charOffset <= word.offset) {
      html += leRenderMarker(allMarkers[markerIdx]);
      if (allMarkers[markerIdx].type === 'part') lastWasPartMarker = true;
      markerIdx++;
    }

    // Line breaks (skip if part marker already added a <br>)
    if (lastWasPartMarker) { /* br already emitted after part marker */ }
    else if (word.emptyLineBefore) html += '<br><br>';
    else if (word.newlineBefore) html += '<br>';
    else if (wi > 0) html += ' ';

    // Render word
    if (word.isHeader) {
      html += `<span class="le-header" data-char-offset="${word.offset}">${esc(word.text)}</span>`;
    } else {
      html += `<span class="le-word" data-char-offset="${word.offset}">${esc(word.text)}</span>`;
    }
  }

  // Any remaining markers after all words
  while (markerIdx < allMarkers.length) {
    html += leRenderMarker(allMarkers[markerIdx]);
    markerIdx++;
  }

  return html;
}

/**
 * Render a single marker element (part or bar).
 */
function leRenderMarker(marker) {
  if (marker.type === 'part') {
    const part = db.songs[selectedSongId]?.parts?.[marker.partId];
    const name = part ? part.name : '?';
    const confirmedClass = marker.confirmed ? ' le-confirmed' : ' le-predicted';
    // Part markers: orange box with black part name, draggable inline in text, line break after
    return `<span class="le-marker le-part-marker${confirmedClass}"
                  data-le-type="part" data-le-idx="${marker.idx}"
                  data-char-offset="${marker.charOffset}"
                  title="${esc(name)}${marker.confirmed ? '' : ' (prognostiziert)'}">${esc(name)}</span><br>`;
  } else {
    // Bar markers: thin cyan vertical stripe with bar number
    return `<span class="le-marker le-bar-marker"
                  data-le-type="bar" data-le-idx="${marker.idx}"
                  data-char-offset="${marker.charOffset}"
                  title="Takt ${marker.barNum}"><span class="le-bar-num">${marker.barNum}</span></span>`;
  }
}

/* ── Lyrics Editor: Text Paste Handling ─────────── */

function handleLePaste(e) {
  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (text && text.trim()) {
    leAcceptRawText(text.trim());
  }
}

async function handleLePasteButton() {
  try {
    const text = await navigator.clipboard.readText();
    if (text && text.trim()) {
      leAcceptRawText(text.trim());
    } else {
      toast('Zwischenablage ist leer', 'error');
    }
  } catch {
    toast('Kein Zugriff auf Zwischenablage. Text manuell einf\u00fcgen.', 'error');
  }
}

function leAcceptRawText(text) {
  const song = db.songs[selectedSongId];
  if (!song) return;

  song.lyrics_raw = text;
  markDirty();

  const parts = getSortedParts(selectedSongId);
  _leWords = leParseRawText(text);
  _lePartMarkers = leGuessPartMarkers(_leWords, parts);
  _leBarMarkers = [];
  _lePhase = 'parts';
  _leInitSongId = selectedSongId;

  renderLyricsTab();
  toast('Text eingef\u00fcgt \u2013 Part-Marker pr\u00fcfen und best\u00e4tigen', 'success');
}

/* ── Lyrics Editor: Phase Transitions ────────────── */

/**
 * Distribute part markers evenly across the lyrics text.
 */
function leDistributeParts() {
  if (_lePartMarkers.length < 2 || _leWords.length === 0) return;
  const lyricsWords = _leWords.filter(w => !w.isHeader);
  if (lyricsWords.length === 0) return;
  const lastWord = lyricsWords[lyricsWords.length - 1];
  const totalChars = lastWord.offset + lastWord.text.length;
  const count = _lePartMarkers.length;
  const gap = totalChars / count;
  for (let i = 0; i < count; i++) {
    const targetOffset = Math.round(i * gap);
    // Snap to nearest word boundary
    let bestWord = lyricsWords[0];
    let bestDist = Math.abs(bestWord.offset - targetOffset);
    for (const w of lyricsWords) {
      const d = Math.abs(w.offset - targetOffset);
      if (d < bestDist) { bestDist = d; bestWord = w; }
    }
    _lePartMarkers[i].charOffset = bestWord.offset;
  }
  renderLyricsTab();
  toast('Parts gleichm\u00e4\u00dfig verteilt', 'success');
}

function leConfirmParts() {
  // Mark all part markers as confirmed
  for (const m of _lePartMarkers) m.confirmed = true;

  // Save confirmed status to song parts
  const song = db.songs[selectedSongId];
  if (song) {
    for (const m of _lePartMarkers) {
      if (song.parts[m.partId]) {
        song.parts[m.partId].lyrics_confirmed = true;
      }
    }
  }

  // Predict bar markers
  _leBarMarkers = leGuessBarMarkers(_leWords, getSortedParts(selectedSongId), _lePartMarkers);
  _lePhase = 'bars';
  markDirty();
  renderLyricsTab();
  toast('Parts best\u00e4tigt \u2013 Takt-Marker anpassen', 'success');
}

function leBackToParts() {
  _lePhase = 'parts';
  _leBarMarkers = [];
  renderLyricsTab();
}

function leClearLyrics() {
  const song = db.songs[selectedSongId];
  if (!song) return;

  song.lyrics_raw = '';
  _lePhase = 'empty';
  _lePartMarkers = [];
  _leBarMarkers = [];
  _leWords = [];
  _leInitSongId = selectedSongId;
  markDirty();
  renderLyricsTab();
  toast('Lyrics gel\u00f6scht', 'info');
}

/* ── Lyrics Editor: Save Logic ───────────────────── */

/**
 * Save lyrics by splitting text at marker positions.
 * Text between consecutive markers becomes the lyrics for each bar.
 */
function leSaveLyrics() {
  if (!selectedSongId) return;
  const song = db.songs[selectedSongId];
  if (!song) return;
  const rawText = song.lyrics_raw || '';
  if (!rawText) return;

  const parts = getSortedParts(selectedSongId);
  ensureCollections();

  // Sort bar markers by charOffset
  const sortedBars = [..._leBarMarkers].sort((a, b) => a.charOffset - b.charOffset || a.barNum - b.barNum);

  // Group bar markers by partId
  const barsByPart = new Map();
  for (const bm of sortedBars) {
    if (!barsByPart.has(bm.partId)) barsByPart.set(bm.partId, []);
    barsByPart.get(bm.partId).push(bm);
  }

  // Sort part markers
  const sortedParts = [..._lePartMarkers].sort((a, b) => a.charOffset - b.charOffset);

  let filledBars = 0;

  for (let pi = 0; pi < sortedParts.length; pi++) {
    const pm = sortedParts[pi];
    const partBars = barsByPart.get(pm.partId) || [];
    const part = song.parts[pm.partId];
    if (!part) continue;

    // Determine text range for this part
    const partEnd = (pi + 1 < sortedParts.length) ? sortedParts[pi + 1].charOffset : rawText.length;

    for (let bi = 0; bi < partBars.length; bi++) {
      const bm = partBars[bi];
      const barStart = bm.charOffset;
      const barEnd = (bi + 1 < partBars.length) ? partBars[bi + 1].charOffset : partEnd;

      // Extract text, strip section headers, clean up
      let barText = rawText.slice(barStart, barEnd).trim();
      barText = barText.replace(/\[.*?\]/g, '').trim();
      barText = barText.replace(/\n+/g, ' ').replace(/\s+/g, ' ').trim();

      // Save to DB
      const [, barData] = getOrCreateBar(pm.partId, bm.barNum);
      barData.lyrics = barText;
      filledBars++;
    }
  }

  markDirty();
  handleSave(false);
  toast(`Lyrics f\u00fcr ${filledBars} Takte gespeichert`, 'success');
}

/* ── Lyrics Editor: Drag Handling ────────────────── */

/**
 * Wire drag event listeners for markers in the editor.
 */
function leWireMarkerDrag() {
  const editor = document.getElementById('le-editor');
  if (!editor) return;

  editor.addEventListener('mousedown', leStartDrag);
  editor.addEventListener('touchstart', leStartDrag, { passive: false });
}

function leStartDrag(e) {
  const markerEl = e.target.closest('.le-marker');
  if (!markerEl) return;

  e.preventDefault();
  const type = markerEl.dataset.leType;
  const idx = parseInt(markerEl.dataset.leIdx, 10);

  // Build word positions for snap targets
  const wordEls = document.querySelectorAll('#le-text .le-word');
  const wordPositions = [];
  for (const w of wordEls) {
    const rect = w.getBoundingClientRect();
    wordPositions.push({
      charOffset: parseInt(w.dataset.charOffset, 10),
      left: rect.left,
      top: rect.top,
      centerY: rect.top + rect.height / 2,
      height: rect.height
    });
  }

  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const clientY = e.touches ? e.touches[0].clientY : e.clientY;

  _leDrag = {
    type,
    idx,
    startX: clientX,
    startY: clientY,
    currentOffset: parseInt(markerEl.dataset.charOffset, 10),
    wordPositions,
    moved: false
  };

  // Visual feedback: dragging cursor
  const editorEl = document.getElementById('le-editor');
  if (editorEl) editorEl.classList.add('le-dragging');

  // Add global move/end listeners
  document.addEventListener('mousemove', leMoveDrag);
  document.addEventListener('mouseup', leEndDrag);
  document.addEventListener('touchmove', leMoveDrag, { passive: false });
  document.addEventListener('touchend', leEndDrag);
}

function leMoveDrag(e) {
  if (!_leDrag) return;
  e.preventDefault();

  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const clientY = e.touches ? e.touches[0].clientY : e.clientY;

  // Check if we've moved enough to count as drag
  if (!_leDrag.moved) {
    const dx = clientX - _leDrag.startX;
    const dy = clientY - _leDrag.startY;
    if (Math.hypot(dx, dy) < 5) return;
    _leDrag.moved = true;
  }

  // Find nearest word boundary
  const positions = _leDrag.wordPositions;
  let bestDist = Infinity;
  let bestOffset = _leDrag.currentOffset;

  for (const p of positions) {
    const dist = Math.hypot(clientX - p.left, clientY - p.centerY);
    if (dist < bestDist) {
      bestDist = dist;
      bestOffset = p.charOffset;
    }
  }

  _leDrag.currentOffset = bestOffset;

  // Remove any previous drop-target highlight (no colored background needed)
  document.querySelectorAll('.le-word.le-drop-target').forEach(w => w.classList.remove('le-drop-target'));

  // Move the marker element visually (opacity change)
  const marker = document.querySelector(`.le-marker[data-le-type="${_leDrag.type}"][data-le-idx="${_leDrag.idx}"]`);
  if (marker) marker.classList.add('le-dragging');

  // Show short cursor-like guide line at drag position
  let guide = document.getElementById('le-drag-guide');
  if (!guide) {
    guide = document.createElement('div');
    guide.id = 'le-drag-guide';
    guide.className = 'le-drag-guide';
    document.body.appendChild(guide);
  }
  // Find the nearest word element to position the guide at text height
  const nearestWordEl = document.querySelector(`.le-word[data-char-offset="${bestOffset}"]`);
  if (nearestWordEl) {
    const wordRect = nearestWordEl.getBoundingClientRect();
    guide.style.left = (wordRect.left - 2) + 'px';
    guide.style.top = wordRect.top + 'px';
    guide.style.height = wordRect.height + 'px';
    guide.style.display = '';
  } else {
    guide.style.left = clientX + 'px';
    guide.style.top = (clientY - 8) + 'px';
    guide.style.height = '16px';
    guide.style.display = '';
  }

  // Floating balloon above finger/cursor
  let label = '';
  let color = '#f0a030';
  if (_leDrag.type === 'part' && _lePartMarkers[_leDrag.idx]) {
    const partId = _lePartMarkers[_leDrag.idx].partId;
    const song = db?.songs?.[selectedSongId];
    label = (song?.parts?.[partId]?.name) || 'Part';
    color = '#f0a030';
  } else if (_leDrag.type === 'bar' && _leBarMarkers[_leDrag.idx]) {
    label = 'Takt ' + _leBarMarkers[_leDrag.idx].barNum;
    color = '#38bdf8';
  }
  showDragBalloon(label, 0, color, clientX, clientY);
}

function leEndDrag() {
  if (!_leDrag) return;

  // Remove dragging cursor
  const editorEl = document.getElementById('le-editor');
  if (editorEl) editorEl.classList.remove('le-dragging');

  // Clean up global listeners
  document.removeEventListener('mousemove', leMoveDrag);
  document.removeEventListener('mouseup', leEndDrag);
  document.removeEventListener('touchmove', leMoveDrag);
  document.removeEventListener('touchend', leEndDrag);

  // Remove visual feedback
  hideDragBalloon();
  document.querySelectorAll('.le-word.le-drop-target').forEach(w => w.classList.remove('le-drop-target'));
  const guide = document.getElementById('le-drag-guide');
  if (guide) guide.remove();

  if (_leDrag.moved) {
    // Update marker position
    if (_leDrag.type === 'part') {
      if (_lePartMarkers[_leDrag.idx]) {
        _lePartMarkers[_leDrag.idx].charOffset = _leDrag.currentOffset;
        _lePartMarkers[_leDrag.idx].confirmed = true;
        // Re-sort
        _lePartMarkers.sort((a, b) => a.charOffset - b.charOffset);
        // If in bars phase, re-predict bar markers for this part
        if (_lePhase === 'bars') {
          const partId = _lePartMarkers[_leDrag.idx]?.partId;
          // Re-predict ALL bar markers since part order may have changed
          _leBarMarkers = leGuessBarMarkers(_leWords, getSortedParts(selectedSongId), _lePartMarkers);
        }
      }
    } else if (_leDrag.type === 'bar') {
      if (_leBarMarkers[_leDrag.idx]) {
        _leBarMarkers[_leDrag.idx].charOffset = _leDrag.currentOffset;
        _leBarMarkers.sort((a, b) => a.charOffset - b.charOffset || a.barNum - b.barNum);
      }
    }

    // Re-render the text with updated markers
    const textEl = document.getElementById('le-text');
    if (textEl) {
      const rawText = db.songs[selectedSongId]?.lyrics_raw || '';
      textEl.innerHTML = buildLyricsEditorContent(rawText);
      // Re-wire drag events for the new marker elements
      leWireMarkerDrag();
    }
  }

  _leDrag = null;
}

/* ── Lyrics Editor: Audio Playback ───────────────── */

let _leAudioTimeout = null;
let _lePlayingBarId = null;

async function lePlayBar(partId, barNum) {
  // Stop any current playback
  leStopPlayback();

  // Try bar audio snippet first
  const found = findBar(partId, barNum);
  if (found) {
    const [barId, barData] = found;
    if (barData.audio) {
      const buf = await fetchAudioUrl(barData.audio);
      if (buf) {
        await audio.loadBuffer(buf);
        audio.play();
        _lePlayingBarId = barId;
        // Auto-stop when bar finishes
        const duration = audio.getBuffer()?.duration || 5;
        _leAudioTimeout = setTimeout(() => leStopPlayback(), duration * 1000 + 200);
        return;
      }
    }
  }

  // Fallback: play reference audio from calculated bar position
  const hasBuf = !!audio.getBuffer();
  if (!hasBuf) {
    toast('Kein Audio verf\u00fcgbar', 'info');
    return;
  }

  const song = db.songs[selectedSongId];
  if (!song || !song.bpm) return;
  const parts = getSortedParts(selectedSongId);
  const part = parts.find(p => p.id === partId);
  if (!part) return;

  const starts = calcPartStarts(selectedSongId);
  const partStart = starts.get(partId);
  if (!partStart) return;

  const barDuration = 4 * 60 / song.bpm;
  const startTime = partStart.startSec + (barNum - 1) * barDuration;

  audio.play(startTime);
  _lePlayingBarId = `${partId}_${barNum}`;
  _leAudioTimeout = setTimeout(() => leStopPlayback(), barDuration * 1000 + 200);
}

function leStopPlayback() {
  audio.pause();
  if (_leAudioTimeout) clearTimeout(_leAudioTimeout);
  _leAudioTimeout = null;
  _lePlayingBarId = null;
}

/* ── Lyrics Editor: Event Handlers ───────────────── */

function handleLyricsClick(e) {
  const el = e.target;

  // Paste button
  if (el.closest('#le-paste-btn')) {
    handleLePasteButton();
    return;
  }

  // Clear button
  if (el.closest('#le-clear-btn')) {
    leClearLyrics();
    return;
  }

  // Distribute parts
  if (el.closest('#le-distribute-parts')) {
    leDistributeParts();
    return;
  }

  // Confirm parts
  if (el.closest('#le-confirm-parts')) {
    leConfirmParts();
    return;
  }

  // Back to parts
  if (el.closest('#le-back-to-parts')) {
    leBackToParts();
    return;
  }

  // Save lyrics
  if (el.closest('#le-save-lyrics')) {
    leSaveLyrics();
    return;
  }

  // Play bar audio (if clicking a bar marker with audio)
  const barMarker = el.closest('.le-bar-marker');
  if (barMarker && e.detail === 2) { // double-click to play
    const idx = parseInt(barMarker.dataset.leIdx, 10);
    const bm = _leBarMarkers[idx];
    if (bm) {
      lePlayBar(bm.partId, bm.barNum);
    }
    return;
  }
}

function handleLyricsChange(e) {
  // No special change handling needed in the new editor
}

/**
 * Save raw lyrics text. Called on song switch.
 */
function saveLyricsRawText() {
  // In the new editor, raw text is saved when accepted via paste
  // This function is kept for compatibility with song-switch logic
}

/**
 * Stop lyrics playback. Called on tab switch / song switch.
 */
function stopLyricsPartPlay() {
  leStopPlayback();
}


/* ══════════════════════════════════════════════════════
   ACCENTS TAB
   ══════════════════════════════════════════════════════ */

let _accentsSelectedPart = null;  // partId
let _accentsSelectedBar = null;   // barNum

function renderAccentsTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Song aus der Liste links ausw&auml;hlen.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  ensureCollections();

  // Count total accents for this song
  const allBarIds = new Set();
  for (const p of parts) {
    for (const [bId, b] of Object.entries(db.bars)) {
      if (b.part_id === p.id) allBarIds.add(bId);
    }
  }
  const totalAccents = Object.values(db.accents).filter(a => allBarIds.has(a.bar_id)).length;

  els.content.innerHTML = `
    <div class="accents-panel">
      <div class="accents-scroll" id="accents-scroll">
        ${buildSongHeader(song)}
        <div class="accents-legend">
          ${Object.entries(ACCENT_INFO).map(([k, v]) => `<span class="legend-item ${k}">${v}</span>`).join('')}
        </div>
        <div class="accents-parts-list" id="accents-parts-list">
          ${parts.length === 0 ? '<div class="empty-state"><p>Keine Parts vorhanden.</p></div>' : buildAccentsPartsList(parts, song)}
        </div>
      </div>
      <div class="summary-bar">
        <span class="summary-item"><span class="summary-label">Parts</span><span class="mono">${parts.length}</span></span>
        <span class="summary-item"><span class="summary-label">Accents</span><span class="mono">${totalAccents}</span></span>
      </div>
    </div>`;
}

function buildAccentsPartsList(parts, song) {
  let html = '';
  let absBarOffset = 0;
  for (const part of parts) {
    const barCount = part.bars || 0;
    const isSelected = _accentsSelectedPart === part.id;
    const partAccentCount = countPartAccents(part.id);

    html += `<div class="accents-part-card${isSelected ? ' expanded' : ''}" data-accent-part="${part.id}">
      <div class="accents-part-header" data-accent-toggle="${part.id}">
        <span class="accents-part-arrow">${isSelected ? '&#9660;' : '&#9654;'}</span>
        <span class="accents-part-name text-amber">${esc(part.name)}</span>
        <span class="accents-part-info text-t3 mono">${barCount} Takte</span>
        ${partAccentCount > 0 ? `<span class="accents-part-count text-cyan mono">${partAccentCount} Acc.</span>` : ''}
      </div>`;

    if (isSelected && barCount > 0) {
      html += '<div class="accents-bars-list">';
      for (let b = 1; b <= barCount; b++) {
        const absBar = absBarOffset + b;
        const isBarSel = _accentsSelectedBar === b;
        const found = findBar(part.id, b);
        const accCount = found ? getAccentsForBar(found[0]).length : 0;
        const barData = found ? db.bars[found[0]] : null;
        const lyrics = barData?.lyrics || '';
        const hasAudio = barData?.audio ? true : false;
        const isBarPlaying = barData && _barPlayId === found[0] && _partPlayActive;

        html += `<div class="accents-bar-row${isBarSel ? ' active' : ''}${accCount > 0 ? ' has-accents' : ''}" data-accent-bar="${b}">
          <span class="accents-bar-num mono">${absBar}</span>
          <span class="accents-bar-lyrics text-t2">${lyrics ? esc(lyrics) : '<span class="text-t4">—</span>'}</span>
          ${accCount > 0 ? `<span class="accents-bar-dots mono text-amber">${accCount}</span>` : ''}
          ${hasAudio ? `<button class="btn-bar-play${isBarPlaying ? ' playing' : ''}" data-action="accent-play-bar" data-play-part-id="${part.id}" data-play-bar-num="${b}" title="${isBarPlaying ? 'Stop' : 'Takt abspielen'}">${isBarPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}
        </div>`;
      }
      html += '</div>';

      // Show the 16th-note grid for the selected bar
      if (_accentsSelectedBar && _accentsSelectedBar <= barCount) {
        html += buildAccentsBarEditor(part.id, _accentsSelectedBar);
      }
    }

    html += '</div>';
    absBarOffset += barCount;
  }
  return html;
}

function countPartAccents(partId) {
  ensureCollections();
  let count = 0;
  for (const [bId, b] of Object.entries(db.bars)) {
    if (b.part_id !== partId) continue;
    count += Object.values(db.accents).filter(a => a.bar_id === bId).length;
  }
  return count;
}

function buildAccentsBarEditor(partId, barNum) {
  const [barId, barData] = getOrCreateBar(partId, barNum);
  const accents = getAccentsForBar(barId);

  const cells = Array.from({ length: 16 }, (_, i) => {
    const pos = i + 1;
    const accent = accents.find(a => a.pos_16th === pos);
    const isBeat = (pos - 1) % 4 === 0;
    const cls = ['accent-cell', isBeat ? 'beat' : '', accent ? accent.type : ''].filter(Boolean).join(' ');
    return `<div class="${cls}" data-accent-pos16="${pos}">
      <span class="accent-num">${BEAT_LABELS[i]}</span>
      ${accent ? `<span class="accent-tag">${accent.type}</span>` : ''}
    </div>`;
  }).join('');

  return `
    <div class="accents-bar-editor">
      <div class="accents-bar-editor-header">
        <h4>Takt ${barNum}</h4>
        ${barData.lyrics ? `<div class="accents-bar-editor-lyrics text-t2">${esc(barData.lyrics)}</div>` : ''}
      </div>
      <div class="accent-grid">${cells}</div>
    </div>`;
}

function handleAccentsTabClick(e) {
  const el = e.target;

  // Toggle part expand/collapse
  const toggle = el.closest('[data-accent-toggle]');
  if (toggle) {
    const partId = toggle.dataset.accentToggle;
    if (_accentsSelectedPart === partId) {
      _accentsSelectedPart = null;
      _accentsSelectedBar = null;
    } else {
      _accentsSelectedPart = partId;
      _accentsSelectedBar = null;
    }
    renderAccentsTab();
    return;
  }

  // Select bar
  const barBlock = el.closest('[data-accent-bar]');
  if (barBlock) {
    const barNum = parseInt(barBlock.dataset.accentBar, 10);
    _accentsSelectedBar = (_accentsSelectedBar === barNum) ? null : barNum;
    renderAccentsTab();
    return;
  }

  // Play bar button
  const playBtn = el.closest('[data-action="accent-play-bar"]');
  if (playBtn) {
    handleAccentBarPlay(playBtn.dataset.playPartId, parseInt(playBtn.dataset.playBarNum, 10));
    return;
  }

  // Accent cell click
  const accentCell = el.closest('[data-accent-pos16]');
  if (accentCell && _accentsSelectedPart && _accentsSelectedBar) {
    const pos = parseInt(accentCell.dataset.accentPos16, 10);
    handleAccentsTabToggle(_accentsSelectedPart, _accentsSelectedBar, pos);
    return;
  }
}

async function handleAccentBarPlay(partId, barNum) {
  ensureCollections();
  const found = findBar(partId, barNum);
  if (!found) return;
  const [barId, barData] = found;
  if (!barData.audio) return;

  // If already playing this bar → stop
  if (_barPlayId === barId && _partPlayActive) {
    stopPartPlay();
    _barPlayId = null;
    renderAccentsTab();
    return;
  }

  stopPartPlay();
  _barPlayId = barId;
  _partPlayActive = true;
  renderAccentsTab();

  try {
    if (!_partPlayCtx) {
      _partPlayCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (_partPlayCtx.state === 'suspended') await _partPlayCtx.resume();

    const arrBuf = await fetchAudioUrl(barData.audio);
    if (!arrBuf) throw new Error(`Audio nicht gefunden: ${barData.audio}`);
    const decoded = await _partPlayCtx.decodeAudioData(arrBuf);

    const src = _partPlayCtx.createBufferSource();
    src.buffer = decoded;
    src.connect(_partPlayCtx.destination);
    src.onended = () => {
      if (_barPlayId === barId) {
        _barPlayId = null;
        _partPlayActive = false;
        renderAccentsTab();
      }
    };
    src.start(0);
    _partPlaySources = [src];
    _partPlayBuffers = [decoded];
  } catch (err) {
    console.error('Bar playback error (accents):', err);
    toast(`Wiedergabe-Fehler: ${err.message}`, 'error');
    stopPartPlay();
    _barPlayId = null;
    renderAccentsTab();
  }
}

function handleAccentsTabToggle(partId, barNum, pos16) {
  const [barId] = getOrCreateBar(partId, barNum);
  ensureCollections();

  // Find existing accent
  const existingId = Object.keys(db.accents).find(
    id => db.accents[id].bar_id === barId && db.accents[id].pos_16th === pos16
  );

  if (existingId) {
    const current = db.accents[existingId];
    const typeIdx = ACCENT_TYPES.indexOf(current.type);
    if (typeIdx < ACCENT_TYPES.length - 1) {
      // Cycle to next type
      current.type = ACCENT_TYPES[typeIdx + 1];
    } else {
      // Remove accent
      delete db.accents[existingId];
    }
  } else {
    // Create new accent
    const newId = nextId('A', db.accents);
    db.accents[newId] = { bar_id: barId, pos_16th: pos16, type: ACCENT_TYPES[0], notes: '' };
  }

  // Update has_accents flag
  const [, barData] = getOrCreateBar(partId, barNum);
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
    const partsCount = Object.keys(song.parts || {}).length;
    const dur = song.duration || fmtDur(song.duration_sec || 0);
    parts.push(`<div class="setlist-card" data-idx="${idx}" data-song-id="${item.song_id}" draggable="true">
      <span class="sl-grip" title="Verschieben">&#8942;&#8942;</span>
      <span class="sl-pos">${songNum}</span>
      <span class="sl-name">${esc(song.name)}</span>
      <span class="sl-artist">${esc(song.artist || '')}</span>
      <div class="sl-meta">
        <span>${song.bpm || '\u2014'} bpm</span>
        <span>${partsCount} P</span>
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
      const xmlStr = atob(json.content.replace(/\n/g, ''));
      const chasers = parseQxwChasers(xmlStr);
      _qxwCache = { xml: xmlStr, chasers };
      return chasers;
    } catch (e) {
      console.warn(`Failed to load ${path}:`, e);
    }
  }
  toast('Keine QXW-Datei gefunden im Repo (db/lightingAI.qxw)', 'error');
  return null;
}

/** Open the QLC+ Chaser Import modal for the current song */
async function openChaserModal(songId) {
  if (!songId || !db?.songs[songId]) return;
  const song = db.songs[songId];
  const parts = getSortedParts(songId);
  if (parts.length === 0) { toast('Keine Parts vorhanden', 'error'); return; }

  toast('QXW wird geladen...', 'info', 2000);
  const chasers = await loadQxwFile();
  if (!chasers) return;

  const match = findChaserForSong(chasers, song.name);
  if (!match) {
    toast(`Kein Chaser fuer "${song.name}" in der QXW gefunden`, 'error', 4000);
    return;
  }

  // Filter out title/end steps and pure "11 Stop" transitions without a note
  const chaserSteps = match.steps.filter(s => !s.isTitle && !(s.functionId === QXW_STOP_ID && !s.note));

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
    renderPartsTab();
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
    renderPartsTab();
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
  const song = db.songs[songId];
  if (!song?.parts?.[partId]) return;
  song.parts[partId].light_template = templateName;
  markDirty();
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
        renderPartsTab();
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
   PARTS TAB
   ══════════════════════════════════════════════════════ */

function getAllPartsFlat() {
  if (!db || !db.songs) return [];
  const rows = [];
  for (const [songId, song] of Object.entries(db.songs)) {
    const sorted = getSortedParts(songId);
    for (const p of sorted) {
      rows.push({ songId, songName: song.name, songArtist: song.artist || '', bpm: song.bpm || 0, partId: p.id, ...p });
    }
  }
  return rows;
}

function renderPartsTab() {
  const filterSong = selectedSongId;

  // Auto-load reference audio if available and not yet loaded
  if (filterSong) {
    const s = db.songs[filterSong];
    if (s && !audio.getBuffer() && s.audio_ref && _refLoadingFor !== filterSong) {
      _refLoadingFor = filterSong;
      _refLoadingPromise = loadReferenceAudio().finally(() => { _refLoadingFor = null; _refLoadingPromise = null; });
    }
  }

  // Get parts based on selected song
  let allParts;
  if (filterSong) {
    const song = db.songs[filterSong];
    if (!song) { allParts = []; }
    else {
      allParts = getSortedParts(filterSong).map(p => ({
        songId: filterSong, songName: song.name, songArtist: song.artist || '',
        bpm: song.bpm || 0, partId: p.id, ...p
      }));
    }
  } else {
    allParts = getAllPartsFlat();
    allParts.sort((a, b) => a.songName.localeCompare(b.songName, 'de') || a.pos - b.pos);
  }

  const sel = partsTabSelectedPart;
  const hasSel = !!(sel && sel.partId);

  // Summary stats
  const totalBars = allParts.reduce((s, p) => s + (p.bars || 0), 0);
  const totalSec = allParts.reduce((s, p) => s + calcPartDuration(p.bars || 0, p.bpm), 0);
  const uniqueSongs = new Set(allParts.map(p => p.songId)).size;

  els.content.innerHTML = `
    <div class="parts-tab-panel">
      <div class="parts-tab-scroll" id="parts-tab-scroll">
        <div class="parts-tab-header">
          <div class="parts-toolbar">
            ${filterSong ? `<button class="btn btn-sm btn-primary" data-pt-action="add">+ ADD</button>` : ''}
            <button class="btn btn-sm" data-pt-action="move-up" ${hasSel ? '' : 'disabled'}>&#9650;</button>
            <button class="btn btn-sm" data-pt-action="move-down" ${hasSel ? '' : 'disabled'}>&#9660;</button>
            <button class="btn btn-sm" data-pt-action="dup" ${hasSel ? '' : 'disabled'}>DUP</button>
            <button class="btn btn-sm btn-danger" data-pt-action="del" ${hasSel ? '' : 'disabled'}>DEL</button>
            ${filterSong ? `<button class="btn btn-sm${db.songs[filterSong]?.instr_done ? ' btn-success' : ''}" data-pt-action="instr-done" title="Alle Instrumental-Parts identifiziert">${db.songs[filterSong]?.instr_done ? '&#9835; &#10003;' : '&#9835; Instr. gepr\u00fcft'}</button>` : ''}
            ${filterSong ? `<button class="btn btn-sm" data-pt-action="qlc-import" title="Light Templates aus QLC+ QXW importieren">&#9728; QLC+</button>` : ''}
          </div>
        </div>
        ${allParts.length === 0
          ? '<div class="empty-state" style="padding:60px 0"><div class="icon">&#9881;</div><p>Keine Parts gefunden.</p></div>'
          : buildPartsTabTable(allParts, filterSong)}
        <div id="pt-bar-area"></div>
      </div>
      <div class="summary-bar">
        <span class="summary-item"><span class="summary-label">Songs</span><span class="mono">${uniqueSongs}</span></span>
        <span class="summary-item"><span class="summary-label">Parts</span><span class="mono">${allParts.length}</span></span>
        <span class="summary-item"><span class="summary-label">Takte</span><span class="mono">${totalBars}</span></span>
        <span class="summary-item"><span class="summary-label">Dauer</span><span class="mono">${fmtDur(totalSec)}</span></span>
      </div>
    </div>`;

  renderPartsTabBarSection();

  // Draw mini waveforms after DOM is ready
  requestAnimationFrame(() => renderMiniWaveforms());
}

function buildPartsTabTable(parts, filterSong) {
  const showSongCol = !filterSong;
  const sel = partsTabSelectedPart;
  const hasBuf = !!audio.getBuffer();

  // Pre-compute starts for all involved songs
  const songIds = [...new Set(parts.map(p => p.songId))];
  const allStarts = {};
  for (const sid of songIds) allStarts[sid] = calcPartStarts(sid);

  return `
    <table class="parts-tab-table">
      <thead><tr>
        <th class="ptt-pos">#</th>
        <th class="ptt-play"></th>
        ${showSongCol ? '<th class="ptt-song">Song</th>' : ''}
        <th class="ptt-name">Part Name</th>
        ${hasBuf ? '<th class="ptt-wave">Waveform</th>' : ''}
        <th class="ptt-start">Start</th>
        <th class="ptt-bars">Takte</th>
        <th class="ptt-tmpl">Light Template</th>
        <th class="ptt-dur">Sek</th>
        <th class="ptt-instr" title="Instrumental">instr.</th>
        <th class="ptt-notes">Notizen</th>
      </tr></thead>
      <tbody>
        ${parts.map((p, idx) => {
          const isActive = sel && sel.songId === p.songId && sel.partId === p.partId;
          const dur = calcPartDuration(p.bars || 0, p.bpm);
          const st = allStarts[p.songId]?.get(p.partId) || { startBar: 0, startSec: 0 };
          const audioBars = getAudioBarsForPart(p.partId);
          const hasAudioBars = audioBars.length > 0;
          const isPlaying = _partPlayActive && _playingPartId === p.partId;

          // Compute waveform time range from part markers (if available for this song)
          let waveCanvas = '';
          let hasRefSegment = false;
          if (hasBuf && p.songId === selectedSongId) {
            const partIdx = getSortedParts(p.songId).findIndex(sp => sp.id === p.partId);
            const wStart = getPartStartTime(partIdx);
            const wEnd = getPartEndTime(partIdx);
            if (wStart !== null && wEnd !== null) {
              waveCanvas = `<canvas class="mini-waveform" data-wave-start="${wStart}" data-wave-end="${wEnd}" data-wave-color="rgb(0, 220, 130)" data-part-idx="${partIdx}"></canvas>`;
              hasRefSegment = true;
            }
          }
          const canPlay = hasAudioBars || hasRefSegment;

          return `<tr class="ptt-row${isActive ? ' active' : ''}" data-song-id="${p.songId}" data-part-id="${p.partId}">
            <td class="ptt-pos mono text-t3">${showSongCol ? idx + 1 : p.pos}</td>
            <td class="ptt-play">${canPlay ? `<button class="btn-part-play${isPlaying ? ' playing' : ''}" data-action="play-part" data-part-id="${p.partId}" title="${isPlaying ? 'Stop' : 'Part abspielen'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}</td>
            ${showSongCol ? `<td class="ptt-song"><span class="ptt-song-name">${esc(p.songName)}</span></td>` : ''}
            <td class="ptt-name"><input type="text" value="${esc(p.name)}" data-ptf="name" class="part-input" list="dl-part-names" autocomplete="off"></td>
            ${hasBuf ? `<td class="ptt-wave">${waveCanvas}</td>` : ''}
            <td class="ptt-start">
              <div class="start-cell">
                <input type="number" value="${st.startBar}" data-ptf="start_bar" class="part-input-num mono" min="0" step="1" inputmode="numeric" title="Takt-Offset ab Songstart">
                <span class="start-time mono text-t3">${fmtDur(Math.round(st.startSec))}</span>
              </div>
            </td>
            <td class="ptt-bars"><input type="number" value="${p.bars || 0}" data-ptf="bars" class="part-input-num mono" min="0" step="1" inputmode="numeric"></td>
            <td class="ptt-tmpl">
              <select data-ptf="light_template" class="part-select">
                <option value="">\u2014</option>
                ${buildTemplateOptions(p.light_template)}
              </select>
            </td>
            <td class="ptt-dur"><input type="number" value="${dur}" data-ptf="duration_sec" class="part-input-num mono" min="0" step="1" inputmode="numeric" title="Dauer in Sekunden"></td>
            <td class="ptt-instr"><input type="checkbox" data-ptf="instrumental" class="instr-check" ${p.instrumental ? 'checked' : ''}></td>
            <td class="ptt-notes"><input type="text" value="${esc(p.notes || '')}" data-ptf="notes" class="part-input ptt-notes-input" placeholder="\u2014"></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    <datalist id="dl-part-names">
      ${getPartNameSuggestions().map(n => `<option value="${esc(n)}">`).join('')}
    </datalist>`;
}

function renderPartsTabBarSection() {
  const area = document.getElementById('pt-bar-area');
  if (!area) return;

  const sel = partsTabSelectedPart;
  if (!sel || !sel.songId || !sel.partId) { area.innerHTML = ''; return; }

  const song = db.songs[sel.songId];
  if (!song || !song.parts[sel.partId]) { area.innerHTML = ''; return; }

  const part = song.parts[sel.partId];
  const barCount = part.bars || 0;

  if (barCount === 0) {
    area.innerHTML = `<div class="bar-section"><p class="text-t3">Keine Bars \u2014 setze die Bars-Anzahl oben.</p></div>`;
    return;
  }

  ensureCollections();
  const blocks = Array.from({ length: barCount }, (_, i) => {
    const n = i + 1;
    const found = findBar(sel.partId, n);
    const hasAcc = found ? getAccentsForBar(found[0]).length > 0 : false;
    const hasLyr = found && found[1].lyrics;
    return `<div class="bar-block${n === partsTabSelectedBar ? ' active' : ''}${hasAcc ? ' has-accents' : ''}${hasLyr ? ' has-lyrics' : ''}" data-bar-num="${n}">${n}</div>`;
  }).join('');

  let editor = '';
  if (partsTabSelectedBar && partsTabSelectedBar <= barCount) {
    editor = buildPartsTabBarEditor();
  }

  area.innerHTML = `
    <div class="bar-section">
      <h3>Bars \u2014 ${esc(part.name)} <span class="text-t3">(${barCount} Takte, ${esc(song.name)})</span></h3>
      <div class="bar-blocks">${blocks}</div>
      ${editor}
    </div>`;
}

function buildPartsTabBarEditor() {
  const sel = partsTabSelectedPart;
  if (!sel) return '';
  const [barId, barData] = getOrCreateBar(sel.partId, partsTabSelectedBar);
  const accents = getAccentsForBar(barId);

  const cells = Array.from({ length: 16 }, (_, i) => {
    const pos = i + 1;
    const accent = accents.find(a => a.pos_16th === pos);
    const isBeat = (pos - 1) % 4 === 0;
    const cls = ['accent-cell', isBeat ? 'beat' : '', accent ? accent.type : ''].filter(Boolean).join(' ');
    return `<div class="${cls}" data-pos16="${pos}" data-pt-accent="1">
      <span class="accent-num">${BEAT_LABELS[i]}</span>
      ${accent ? `<span class="accent-tag">${accent.type}</span>` : ''}
    </div>`;
  }).join('');

  return `
    <div class="bar-editor">
      <div class="bar-editor-header">
        <h3>Bar ${partsTabSelectedBar}</h3>
        <div class="accent-legend">
          ${Object.entries(ACCENT_INFO).map(([k, v]) => `<span class="legend-item ${k}">${v}</span>`).join('')}
        </div>
      </div>
      <div style="margin-bottom: 12px">
        <label>Lyrics</label>
        <input type="text" class="bar-lyrics-input" value="${esc(barData.lyrics || '')}" data-pt-bar-lyrics="1" placeholder="Textzeile...">
      </div>
      <div class="accent-grid">${cells}</div>
    </div>`;
}

/* ── Parts Tab Event Handlers ─────────────────────── */

function handlePartsTabClick(e) {
  const el = e.target;

  // Play part button
  const playBtn = el.closest('[data-action="play-part"]');
  if (playBtn) {
    handlePartPlay(playBtn.dataset.partId);
    return;
  }

  // Mini-waveform click → open Part Wave Editor (Finetuning)
  const waveCanvas = el.closest('.mini-waveform');
  if (waveCanvas) {
    const row = waveCanvas.closest('.ptt-row');
    if (row) {
      openPartWaveEditor(row.dataset.songId, row.dataset.partId);
      return;
    }
  }

  // Toolbar actions
  const actionBtn = el.closest('[data-pt-action]');
  if (actionBtn && !actionBtn.disabled) {
    handlePartsTabAction(actionBtn.dataset.ptAction);
    return;
  }

  // Accent cell
  const accentCell = el.closest('[data-pt-accent]');
  if (accentCell) {
    const pos = parseInt(accentCell.dataset.pos16, 10);
    handlePartsTabAccentToggle(pos);
    return;
  }

  // Bar block
  const barBlock = el.closest('[data-bar-num]');
  if (barBlock && !barBlock.closest('.bar-editor')) {
    const barNum = parseInt(barBlock.dataset.barNum, 10);
    partsTabSelectedBar = (partsTabSelectedBar === barNum) ? null : barNum;
    renderPartsTabBarSection();
    return;
  }

  // Song name click → select song in sidebar
  const songNameEl = el.closest('.ptt-song-name');
  if (songNameEl) {
    const row = songNameEl.closest('.ptt-row');
    if (row && row.dataset.songId !== selectedSongId) {
      selectedSongId = row.dataset.songId;
      selectedPartId = null;
      selectedBarNum = null;
      partsTabSelectedPart = null;
      partsTabSelectedBar = null;
      renderSongList(els.searchBox.value);
      renderPartsTab();
      return;
    }
  }

  // Row click (not on input/select)
  const row = el.closest('.ptt-row');
  if (row && !el.closest('input, select')) {
    const songId = row.dataset.songId;
    const partId = row.dataset.partId;
    const wasSame = partsTabSelectedPart && partsTabSelectedPart.songId === songId && partsTabSelectedPart.partId === partId;
    if (wasSame) return;
    partsTabSelectedPart = { songId, partId };
    partsTabSelectedBar = null;
    // Update active row visually
    document.querySelectorAll('.ptt-row').forEach(r => {
      r.classList.toggle('active', r.dataset.songId === songId && r.dataset.partId === partId);
    });
    // Enable toolbar buttons
    document.querySelectorAll('.parts-toolbar .btn:not([data-pt-action="add"])').forEach(btn => {
      btn.disabled = false;
    });
    renderPartsTabBarSection();
    return;
  }
}

function handlePartsTabChange(e) {
  const el = e.target;

  // Part field edit
  if (el.dataset.ptf) {
    const row = el.closest('.ptt-row');
    if (!row) return;
    const songId = row.dataset.songId;
    const partId = row.dataset.partId;
    const song = db.songs[songId];
    const part = song?.parts[partId];
    if (!part) return;

    const field = el.dataset.ptf;
    if (field === 'bars') {
      part.bars = parseInt(el.value, 10) || 0;
      part.duration_sec = calcPartDuration(part.bars, song.bpm || 0);
      recalcSongDurationFor(songId);
      // Bars changed → re-render to update subsequent start values
      renderPartsTab();
      if (partsTabSelectedPart && partsTabSelectedPart.partId === partId) {
        if (partsTabSelectedBar && partsTabSelectedBar > part.bars) partsTabSelectedBar = null;
        renderPartsTabBarSection();
      }
    } else if (field === 'start_bar') {
      part.start_bar = parseInt(el.value, 10) || 0;
      renderPartsTab();
    } else if (field === 'duration_sec') {
      const newDur = parseInt(el.value, 10) || 0;
      const bpm = song.bpm || 0;
      if (bpm > 0) {
        part.bars = Math.round(newDur * bpm / 240);
      }
      part.duration_sec = calcPartDuration(part.bars, bpm);
      recalcSongDurationFor(songId);
      renderPartsTab();
      if (partsTabSelectedPart && partsTabSelectedPart.partId === partId) {
        if (partsTabSelectedBar && partsTabSelectedBar > part.bars) partsTabSelectedBar = null;
        renderPartsTabBarSection();
      }
    } else if (field === 'light_template') {
      part.light_template = el.value;
    } else if (field === 'instrumental') {
      part.instrumental = el.checked;
    } else if (field === 'notes') {
      part.notes = el.value;
    } else if (field === 'name') {
      // If user cleared the field (or left it empty), restore old name
      if (!el.value.trim()) {
        el.value = part.name;
        return;
      }
      part.name = el.value.trim();
      if (partsTabSelectedPart && partsTabSelectedPart.partId === partId) {
        renderPartsTabBarSection();
      }
    } else {
      part[field] = el.value;
    }
    markDirty();
    return;
  }

  // Bar lyrics
  if (el.hasAttribute('data-pt-bar-lyrics')) {
    const sel = partsTabSelectedPart;
    if (!sel || !partsTabSelectedBar) return;
    const [, barData] = getOrCreateBar(sel.partId, partsTabSelectedBar);
    barData.lyrics = el.value;
    markDirty();
    return;
  }
}

function recalcSongDurationFor(songId) {
  const song = db.songs[songId];
  if (!song) return;
  const totalSec = Object.values(song.parts || {})
    .reduce((sum, p) => sum + calcPartDuration(p.bars || 0, song.bpm || 0), 0);
  song.duration_sec = totalSec;
  song.duration = fmtDur(totalSec);
}

function handlePartsTabAction(action) {
  const sel = partsTabSelectedPart;
  const filterSong = selectedSongId;

  switch (action) {
    case 'add': {
      if (!filterSong) return;
      const song = db.songs[filterSong];
      if (!song) return;
      if (!song.parts) song.parts = {};
      const parts = getSortedParts(filterSong);
      const newPos = parts.length > 0 ? Math.max(...parts.map(p => p.pos)) + 1 : 1;
      const newId = nextPartId(filterSong);
      song.parts[newId] = { pos: newPos, name: 'New Part', bars: 0, duration_sec: 0, light_template: '', notes: '' };
      partsTabSelectedPart = { songId: filterSong, partId: newId };
      partsTabSelectedBar = null;
      markDirty();
      renderPartsTab();
      setTimeout(() => {
        const input = document.querySelector(`[data-part-id="${newId}"] [data-ptf="name"]`);
        if (input) { input.focus(); input.select(); }
      }, 50);
      break;
    }

    case 'del': {
      if (!sel) return;
      const song = db.songs[sel.songId];
      if (!song || !song.parts[sel.partId]) return;
      ensureCollections();
      for (const [barId, b] of Object.entries(db.bars)) {
        if (b.part_id === sel.partId) {
          for (const [accId, a] of Object.entries(db.accents)) {
            if (a.bar_id === barId) delete db.accents[accId];
          }
          delete db.bars[barId];
        }
      }
      delete song.parts[sel.partId];
      getSortedParts(sel.songId).forEach((p, i) => { song.parts[p.id].pos = i + 1; });
      // Sync: remove split_markers for the deleted part
      removeSplitMarkersForPart(song, sel.partId);
      recalcSongDurationFor(sel.songId);
      partsTabSelectedPart = null;
      partsTabSelectedBar = null;
      markDirty();
      renderPartsTab();
      break;
    }

    case 'move-up':
    case 'move-down': {
      if (!sel) return;
      const song = db.songs[sel.songId];
      if (!song) return;
      const parts = getSortedParts(sel.songId);
      const idx = parts.findIndex(p => p.id === sel.partId);
      if (action === 'move-up' && idx <= 0) return;
      if (action === 'move-down' && (idx < 0 || idx >= parts.length - 1)) return;
      const swapIdx = action === 'move-up' ? idx - 1 : idx + 1;
      const curr = song.parts[parts[idx].id];
      const other = song.parts[parts[swapIdx].id];
      [curr.pos, other.pos] = [other.pos, curr.pos];
      // Sync: update partIndex in split_markers after reorder
      rebuildSplitMarkerIndices(song);
      if (selectedSongId === sel.songId) restoreMarkersFromSong();
      recalcSongDurationFor(sel.songId);
      markDirty();
      renderPartsTab();
      break;
    }

    case 'dup': {
      if (!sel) return;
      const song = db.songs[sel.songId];
      if (!song || !song.parts[sel.partId]) return;
      const src = song.parts[sel.partId];
      for (const p of Object.values(song.parts)) {
        if (p.pos > src.pos) p.pos += 1;
      }
      const newId = nextPartId(sel.songId);
      song.parts[newId] = {
        pos: src.pos + 1, name: src.name + ' (Copy)', bars: src.bars,
        duration_sec: src.duration_sec, light_template: src.light_template, notes: src.notes || ''
      };
      partsTabSelectedPart = { songId: sel.songId, partId: newId };
      partsTabSelectedBar = null;
      markDirty();
      recalcSongDurationFor(sel.songId);
      renderPartsTab();
      break;
    }

    case 'instr-done': {
      if (!filterSong) return;
      const song = db.songs[filterSong];
      if (!song) return;
      song.instr_done = !song.instr_done;
      markDirty();
      renderPartsTab();
      checkProgressAndCelebrate(filterSong);
      break;
    }

    case 'qlc-import': {
      if (!filterSong) return;
      openChaserModal(filterSong);
      break;
    }
  }
}

function handlePartsTabAccentToggle(pos) {
  const sel = partsTabSelectedPart;
  if (!sel || !partsTabSelectedBar) return;
  ensureCollections();
  const [barId, barData] = getOrCreateBar(sel.partId, partsTabSelectedBar);

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
  renderPartsTabBarSection();
}

/* ══════════════════════════════════════════════════════
   PART WAVEFORM EDITOR MODAL
   ══════════════════════════════════════════════════════ */

/** State for the Part Waveform Editor modal */
let _pw = {
  open: false,
  songId: null,
  partId: null,
  partIndex: -1,
  /** Full audio range visible in the modal (with context padding) */
  viewStart: 0,
  viewEnd: 0,
  /** Current trim positions (editable) */
  trimStart: 0,
  trimEnd: 0,
  /** Original trim positions (for cancel) */
  origStart: 0,
  origEnd: 0,
  /** Playback animation frame id */
  animFrame: null,
  /** Is playing */
  playing: false,
};

/**
 * Open the Part Waveform Editor for a given part.
 * @param {string} songId
 * @param {string} partId
 */
function openPartWaveEditor(songId, partId) {
  if (!audio.getBuffer()) return;
  const parts = getSortedParts(songId);
  const partIdx = parts.findIndex(p => p.id === partId);
  if (partIdx < 0) return;

  const startTime = getPartStartTime(partIdx);
  const endTime = getPartEndTime(partIdx);
  if (startTime === null || endTime === null) return;

  const part = parts[partIdx];
  const duration = audioMeta ? audioMeta.duration : audio.getBuffer().duration;

  // Show ~2 seconds of context on each side, clamped to audio bounds
  const pad = Math.min(2, (endTime - startTime) * 0.3);
  _pw.songId = songId;
  _pw.partId = partId;
  _pw.partIndex = partIdx;
  _pw.viewStart = Math.max(0, startTime - pad);
  _pw.viewEnd = Math.min(duration, endTime + pad);
  _pw.trimStart = startTime;
  _pw.trimEnd = endTime;
  _pw.origStart = startTime;
  _pw.origEnd = endTime;
  _pw.open = true;
  _pw.playing = false;

  els.pwTitle.textContent = `${part.name} — ${db.songs[songId]?.name || ''}`;
  els.pwModal.classList.add('open');

  // Draw after modal is visible (needs layout for canvas size)
  requestAnimationFrame(() => {
    _pwDrawWaveform();
    _pwUpdateUI();
  });
}

function closePartWaveEditor(save) {
  _pwStopPlay();
  _pw.open = false;
  els.pwModal.classList.remove('open');

  if (save && (_pw.trimStart !== _pw.origStart || _pw.trimEnd !== _pw.origEnd)) {
    // Update the part marker
    const marker = partMarkers.find(m => m.partIndex === _pw.partIndex);
    if (marker) {
      marker.time = _pw.trimStart;
    }
    // Update next part marker (= end of this part) if it exists
    const nextMarker = partMarkers.find(m => m.partIndex === _pw.partIndex + 1);
    if (nextMarker) {
      nextMarker.time = _pw.trimEnd;
    }
    // Persist and re-render
    saveMarkersToSong();
    markDirty();
    if (activeTab === 'parts') renderPartsTab();
    else if (activeTab === 'audio') { drawWaveform(); }
    toast('Part-Grenzen aktualisiert', 'success');
  }
}

/** Draw the waveform on the modal canvas */
function _pwDrawWaveform() {
  const canvas = els.pwCanvas;
  if (!canvas) return;
  const wrap = els.pwWrap;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  if (w <= 0 || h <= 0) return;

  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const buckets = Math.floor(w);
  const peaks = audio.getPeaksRange(_pw.viewStart, _pw.viewEnd, buckets);
  const mid = h / 2;

  // Midline
  ctx.strokeStyle = 'rgba(92, 96, 128, 0.2)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(w, mid);
  ctx.stroke();

  // Waveform bars
  for (let i = 0; i < buckets; i++) {
    const amp = peaks[i];
    const barH = amp * (h * 0.85);
    const opacity = 0.3 + amp * 0.7;
    ctx.fillStyle = `rgba(0, 220, 130, ${opacity})`;
    ctx.fillRect(i, mid - barH / 2, 1, barH || 1);
  }

  // Draw bar markers with flags
  const bars = getBarMarkersForPart(_pw.partIndex);
  if (bars.length > 0) {
    const viewRange = _pw.viewEnd - _pw.viewStart;
    for (let i = 0; i < bars.length; i++) {
      const x = ((bars[i].time - _pw.viewStart) / viewRange) * w;
      if (x < 0 || x > w) continue;
      // Cyan vertical line
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.6)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      // Flag label (bottom, like Audio-Split-Tab)
      const label = `${bars[i].barNum || i + 1}`;
      ctx.font = '9px DM Mono, monospace';
      const tw = ctx.measureText(label).width + 4;
      ctx.fillStyle = 'rgba(56, 189, 248, 0.85)';
      ctx.fillRect(x, h - 13, tw, 13);
      ctx.fillStyle = '#08090d';
      ctx.fillText(label, x + 2, h - 3);
    }
  }

  // Draw Start flag (amber)
  {
    const x = ((_pw.trimStart - _pw.viewStart) / (_pw.viewEnd - _pw.viewStart)) * w;
    ctx.strokeStyle = 'rgba(240, 160, 48, 0.9)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    const label = 'Start';
    ctx.font = '9px Sora, sans-serif';
    const tw = ctx.measureText(label).width + 4;
    ctx.fillStyle = 'rgba(240, 160, 48, 0.9)';
    ctx.fillRect(x, 0, tw, 13);
    ctx.fillStyle = '#08090d';
    ctx.fillText(label, x + 2, 10);
  }

  // Draw Ende flag (amber)
  {
    const x = ((_pw.trimEnd - _pw.viewStart) / (_pw.viewEnd - _pw.viewStart)) * w;
    ctx.strokeStyle = 'rgba(240, 160, 48, 0.9)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    const label = 'Ende';
    ctx.font = '9px Sora, sans-serif';
    const tw = ctx.measureText(label).width + 4;
    ctx.fillStyle = 'rgba(240, 160, 48, 0.9)';
    ctx.fillRect(x - tw, 0, tw, 13);
    ctx.fillStyle = '#08090d';
    ctx.fillText(label, x - tw + 2, 10);
  }
}

/** Convert time in seconds to X pixel position in the modal waveform */
function _pwTimeToX(timeSec) {
  const w = els.pwWrap.clientWidth;
  const range = _pw.viewEnd - _pw.viewStart;
  if (range <= 0) return 0;
  return ((timeSec - _pw.viewStart) / range) * w;
}

/** Convert X pixel position to time in seconds */
function _pwXToTime(x) {
  const w = els.pwWrap.clientWidth;
  const range = _pw.viewEnd - _pw.viewStart;
  return _pw.viewStart + (x / w) * range;
}

/** Update handle positions, dimmed regions, and time labels */
function _pwUpdateUI() {
  const w = els.pwWrap.clientWidth;
  const startX = _pwTimeToX(_pw.trimStart);
  const endX = _pwTimeToX(_pw.trimEnd);

  els.pwHandleStart.style.left = `${startX}px`;
  els.pwHandleEnd.style.left = `${endX - 6}px`; // handle width offset

  els.pwDimLeft.style.width = `${startX}px`;
  els.pwDimRight.style.width = `${w - endX}px`;

  els.pwTimeStart.textContent = fmtTime(_pw.trimStart);
  els.pwTimeEnd.textContent = fmtTime(_pw.trimEnd);
  els.pwTimeDur.textContent = fmtTime(_pw.trimEnd - _pw.trimStart);
}

/* fmtTime — siehe Zeile 1835 (einzige Definition) */

/* ── Part Wave Editor: Handle Drag ── */

let _pwDrag = null; // { which: 'start'|'end', startX }

function _pwStartDrag(which, e) {
  e.preventDefault();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  _pwDrag = { which, startX: clientX };

  const onMove = (ev) => {
    if (!_pwDrag) return;
    const cx = ev.touches ? ev.touches[0].clientX : ev.clientX;
    const rect = els.pwWrap.getBoundingClientRect();
    const x = Math.max(0, Math.min(cx - rect.left, rect.width));
    const time = _pwXToTime(x);

    if (_pwDrag.which === 'start') {
      _pw.trimStart = Math.max(_pw.viewStart, Math.min(time, _pw.trimEnd - 0.1));
    } else {
      _pw.trimEnd = Math.min(_pw.viewEnd, Math.max(time, _pw.trimStart + 0.1));
    }
    _pwUpdateUI();
  };
  const onEnd = () => {
    _pwDrag = null;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onEnd);
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onEnd);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onEnd);
  document.addEventListener('touchmove', onMove, { passive: false });
  document.addEventListener('touchend', onEnd);
}

/* ── Part Wave Editor: Playback ── */

function _pwTogglePlay() {
  if (_pw.playing) {
    _pwStopPlay();
  } else {
    _pw.playing = true;
    els.pwPlay.innerHTML = '&#9632; Stop';
    els.pwPlayhead.style.display = 'block';
    audio.playSegments([{ startTime: _pw.trimStart, endTime: _pw.trimEnd }], () => {
      _pwStopPlay();
    });
    _pwAnimatePlayhead();
  }
}

function _pwStopPlay() {
  _pw.playing = false;
  audio.stopSegments();
  if (_pw.animFrame) {
    cancelAnimationFrame(_pw.animFrame);
    _pw.animFrame = null;
  }
  els.pwPlay.innerHTML = '&#9654; Play';
  els.pwPlayhead.style.display = 'none';
}

function _pwAnimatePlayhead() {
  if (!_pw.playing) return;
  const t = audio.getSegmentCurrentTime();
  if (t > 0) {
    const x = _pwTimeToX(t);
    els.pwPlayhead.style.left = `${x}px`;
  }
  _pw.animFrame = requestAnimationFrame(_pwAnimatePlayhead);
}

/* ── Part Wave Editor: Nudge ── */

const PW_NUDGE_MS = 50;

function _pwNudge(which, dir) {
  const delta = (dir * PW_NUDGE_MS) / 1000;
  if (which === 'start') {
    _pw.trimStart = Math.max(_pw.viewStart, Math.min(_pw.trimStart + delta, _pw.trimEnd - 0.05));
  } else {
    _pw.trimEnd = Math.min(_pw.viewEnd, Math.max(_pw.trimEnd + delta, _pw.trimStart + 0.05));
  }
  _pwUpdateUI();
}

/* ── Part Wave Editor: Click on waveform to seek ── */

function _pwWaveformClick(e) {
  if (_pwDrag) return; // was a drag, not a click
  const rect = els.pwWrap.getBoundingClientRect();
  const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
  const time = _pwXToTime(x);

  // Seek to clicked position and start playback (works whether playing or stopped)
  if (_pw.playing) _pwStopPlay();
  _pw.playing = true;
  els.pwPlay.innerHTML = '&#9632; Stop';
  els.pwPlayhead.style.display = 'block';
  const seekTime = Math.max(_pw.trimStart, Math.min(time, _pw.trimEnd));
  audio.playSegments([{ startTime: seekTime, endTime: _pw.trimEnd }], () => {
    _pwStopPlay();
  });
  _pwAnimatePlayhead();
}

/* ── Part Wave Editor: Init Event Listeners ── */

function initPartWaveEditor() {
  // Handle drag
  els.pwHandleStart.addEventListener('mousedown', (e) => _pwStartDrag('start', e));
  els.pwHandleStart.addEventListener('touchstart', (e) => _pwStartDrag('start', e), { passive: false });
  els.pwHandleEnd.addEventListener('mousedown', (e) => _pwStartDrag('end', e));
  els.pwHandleEnd.addEventListener('touchstart', (e) => _pwStartDrag('end', e), { passive: false });

  // Waveform click to seek
  els.pwWrap.addEventListener('click', _pwWaveformClick);

  // Play button
  els.pwPlay.addEventListener('click', _pwTogglePlay);

  // Nudge buttons
  els.pwModal.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-pw]');
    if (!btn) return;
    const action = btn.dataset.pw;
    if (action === 'nudge-start-left')  _pwNudge('start', -1);
    if (action === 'nudge-start-right') _pwNudge('start', 1);
    if (action === 'nudge-end-left')    _pwNudge('end', -1);
    if (action === 'nudge-end-right')   _pwNudge('end', 1);
  });

  // Save / Cancel / Close
  els.pwSave.addEventListener('click', () => closePartWaveEditor(true));
  els.pwCancel.addEventListener('click', () => closePartWaveEditor(false));
  els.pwClose.addEventListener('click', () => closePartWaveEditor(false));

  // Background click closes
  els.pwModal.addEventListener('click', (e) => {
    if (e.target === els.pwModal) closePartWaveEditor(false);
  });
}

/* ══════════════════════════════════════════════════════
   TAKTE TAB
   ══════════════════════════════════════════════════════ */

function getAllBarsFlat() {
  if (!db || !db.songs) return [];
  const rows = [];
  for (const [songId, song] of Object.entries(db.songs)) {
    const parts = getSortedParts(songId);
    const starts = calcPartStarts(songId);
    for (const p of parts) {
      const st = starts.get(p.id) || { startBar: 0, startSec: 0 };
      const barCount = p.bars || 0;
      for (let n = 1; n <= barCount; n++) {
        const found = findBar(p.id, n);
        const barData = found ? found[1] : {};
        const barId = found ? found[0] : null;
        const accCount = barId ? getAccentsForBar(barId).length : 0;
        const absBar = st.startBar + n;
        const bpm = song.bpm || 0;
        const barSec = bpm > 0 ? (st.startBar + n - 1) * 4 * 60 / bpm : 0;
        rows.push({
          songId, songName: song.name, bpm,
          partId: p.id, partName: p.name,
          barNum: n, absBar, barSec,
          lyrics: barData.lyrics || '',
          audio: barData.audio || '',
          accCount, barId
        });
      }
    }
  }
  return rows;
}

function renderTakteTab() {
  const filterSong = selectedSongId;
  ensureCollections();

  // Auto-load reference audio if available and not yet loaded
  if (filterSong) {
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
    <div class="parts-tab-panel">
      <div class="parts-tab-scroll" id="takte-tab-scroll">
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
 * Returns { start, end } in seconds or null.
 */
function getBarTimeRange(partId, barNum) {
  if (!audioMeta || !selectedSongId) return null;
  const parts = getSortedParts(selectedSongId);
  const partIdx = parts.findIndex(p => p.id === partId);
  if (partIdx < 0) return null;

  // Get sorted bar markers for this part
  const barsInPart = barMarkers
    .filter(m => m.partIndex === partIdx)
    .sort((a, b) => a.time - b.time);

  if (barNum < 1 || barNum > barsInPart.length) return null;
  const start = barsInPart[barNum - 1].time;
  const end = barNum < barsInPart.length
    ? barsInPart[barNum].time
    : (getPartEndTime(partIdx) || audioMeta.duration);
  return { start, end };
}

function buildTakteTabTable(bars, filterSong) {
  const showSongCol = !filterSong;
  const sel = takteTabSelectedBar;
  const hasBuf = !!audio.getBuffer();
  const showWave = hasBuf && filterSong === selectedSongId;

  return `
    <table class="parts-tab-table takte-tab-table">
      <thead><tr>
        <th class="ttt-nr">#</th>
        <th class="ttt-play"></th>
        ${showSongCol ? '<th class="ttt-song">Song</th>' : ''}
        <th class="ttt-part">Part</th>
        <th class="ttt-bar">Takt</th>
        ${showWave ? '<th class="ttt-wave">Waveform</th>' : ''}
        <th class="ttt-time">Zeit</th>
        <th class="ttt-lyrics">Lyrics</th>
        <th class="ttt-acc">Acc.</th>
        <th class="ttt-audio">Audio</th>
      </tr></thead>
      <tbody>
        ${bars.map((b, idx) => {
          const isActive = sel && sel.songId === b.songId && sel.partId === b.partId && sel.barNum === b.barNum;
          const isBarPlaying = _barPlayId === b.barId && _partPlayActive;

          let waveCanvas = '';
          if (showWave) {
            const range = getBarTimeRange(b.partId, b.barNum);
            if (range) {
              waveCanvas = `<canvas class="mini-waveform mini-waveform-sm" data-wave-start="${range.start}" data-wave-end="${range.end}" data-wave-color="rgb(56, 189, 248)"></canvas>`;
            }
          }

          return `<tr class="ttt-row${isActive ? ' active' : ''}" data-song-id="${b.songId}" data-part-id="${b.partId}" data-bar-num="${b.barNum}">
            <td class="ttt-nr mono text-t3">${showSongCol ? idx + 1 : b.absBar}</td>
            <td class="ttt-play">${b.audio ? `<button class="btn-bar-play${isBarPlaying ? ' playing' : ''}" data-action="play-bar" data-play-part-id="${b.partId}" data-play-bar-num="${b.barNum}" title="${isBarPlaying ? 'Stop' : 'Takt abspielen'}">${isBarPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}</td>
            ${showSongCol ? `<td class="ttt-song"><span class="ttt-song-name">${esc(b.songName)}</span></td>` : ''}
            <td class="ttt-part text-t2">${esc(b.partName)}</td>
            <td class="ttt-bar mono">${b.barNum}</td>
            ${showWave ? `<td class="ttt-wave">${waveCanvas}</td>` : ''}
            <td class="ttt-time mono text-t3">${fmtDur(Math.round(b.barSec))}</td>
            <td class="ttt-lyrics"><input type="text" value="${esc(b.lyrics)}" data-ttf="lyrics" class="part-input" placeholder="\u2014"></td>
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
  const [barId, barData] = getOrCreateBar(sel.partId, sel.barNum);
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

  const part = song.parts[sel.partId];
  area.innerHTML = `
    <div class="bar-editor">
      <div class="bar-editor-header">
        <h3>Takt ${sel.barNum} \u2014 ${esc(part?.name || '')} <span class="text-t3">(${esc(song.name)})</span></h3>
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
  const parts = filterSong ? getSortedParts(filterSong) : null;
  const partIds = parts ? new Set(parts.map(p => p.id)) : null;

  // Collect bar IDs to delete
  const barIdsToDelete = [];
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (!partIds || partIds.has(bar.part_id)) {
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

  // Sync: clear split_markers.barMarkers and reset part.bars count
  if (filterSong) {
    const song = db.songs[filterSong];
    if (song) {
      // Clear bar markers from split_markers
      if (song.split_markers && Array.isArray(song.split_markers.barMarkers)) {
        song.split_markers.barMarkers = [];
      }
      // Reset bars count on all parts
      if (parts) {
        for (const p of parts) {
          if (song.parts[p.id]) song.parts[p.id].bars = 0;
        }
      }
      // If this song is currently loaded in the Audio tab, clear in-memory barMarkers
      if (selectedSongId === filterSong) {
        barMarkers = [];
        currentBarInPart = 0;
      }
    }
  } else {
    // All songs: clear all bar markers
    for (const [, song] of Object.entries(db.songs)) {
      if (song.split_markers) song.split_markers.barMarkers = [];
      if (song.parts) {
        for (const p of Object.values(song.parts)) p.bars = 0;
      }
    }
    barMarkers = [];
    currentBarInPart = 0;
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
    handleBarPlay(playBtn.dataset.playPartId, parseInt(playBtn.dataset.playBarNum, 10));
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
      selectedPartId = null;
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
    const partId = row.dataset.partId;
    const barNum = parseInt(row.dataset.barNum, 10);
    const curSel = takteTabSelectedBar;
    const wasSame = curSel && curSel.songId === songId && curSel.partId === partId && curSel.barNum === barNum;
    if (wasSame) return;
    takteTabSelectedBar = { songId, partId, barNum };
    document.querySelectorAll('.ttt-row').forEach(r => {
      r.classList.toggle('active',
        r.dataset.songId === songId && r.dataset.partId === partId && parseInt(r.dataset.barNum, 10) === barNum);
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
    const partId = row.dataset.partId;
    const barNum = parseInt(row.dataset.barNum, 10);
    const [, barData] = getOrCreateBar(partId, barNum);
    barData.lyrics = el.value;
    markDirty();
    return;
  }

  // Lyrics in editor
  if (el.hasAttribute('data-tt-bar-lyrics')) {
    const sel = takteTabSelectedBar;
    if (!sel) return;
    const [, barData] = getOrCreateBar(sel.partId, sel.barNum);
    barData.lyrics = el.value;
    markDirty();
    // Sync table row
    const row = document.querySelector(`.ttt-row[data-part-id="${sel.partId}"][data-bar-num="${sel.barNum}"]`);
    const inp = row?.querySelector('[data-ttf="lyrics"]');
    if (inp && inp !== el) inp.value = el.value;
    return;
  }
}

function handleTakteAccentToggle(pos) {
  const sel = takteTabSelectedBar;
  if (!sel) return;
  ensureCollections();
  const [barId, barData] = getOrCreateBar(sel.partId, sel.barNum);

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
    parts: 'parts',
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
  if (!path) { toast('DB-Pfad muss ausgef\u00fcllt sein.', 'error'); return; }
  saveSettings({ repo, token, path });
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
      migrateAudioPaths();
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
    migrateAudioPaths();
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
    if (showToast) toast('Gespeichert', 'success');

    // Auto-export audio segments only from the audio tab (not during lyrics/parts editing)
    if (activeTab === 'audio' && selectedSongId && audioMeta && !exportInProgress
        && partMarkers.length > 0 && barMarkers.length > 0) {
      handleAudioExport();
    }

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
  if (!confirm('\u00c4nderungen verwerfen und letzte gespeicherte Version von GitHub laden?')) return;
  const s = getSettings();
  setSyncStatus('loading');
  try {
    const result = await loadDB(s.repo, s.path, s.token);
    db = result.data;
    dbSha = result.sha;
    dirty = false;
    setSyncStatus('saved');
    migrateAudioPaths();
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
  els.tabParts?.addEventListener('click',  () => switchTab('parts'));
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
    // Remember current tab — must be preserved across song switch
    const currentTab = activeTab;
    // Stop audio and reset split state when switching songs
    audio.reset();
    audioMeta = null;
    audioFileName = null;
    resetAudioSplit();
    cancelAnimationFrame(animFrameId);
    selectedSongId = newId;
    selectedPartId = null;
    selectedBarNum = null;
    partsTabSelectedPart = null;
    partsTabSelectedBar = null;
    takteTabSelectedBar = null;
    stopLyricsPartPlay();
    renderSongList(els.searchBox.value);
    // Restore tab (defensive — ensure no code above changed it)
    if (activeTab !== currentTab) switchTab(currentTab);
    else renderContent();
  });

  // Editor event delegation
  els.content.addEventListener('change', handleEditorChange);
  els.content.addEventListener('click', (e) => {
    if (activeTab === 'editor') handleEditorClick(e);
    else if (activeTab === 'parts') handlePartsTabClick(e);
    else if (activeTab === 'takte') handleTakteTabClick(e);
    else if (activeTab === 'audio') handleAudioClick(e);
    else if (activeTab === 'lyrics') handleLyricsClick(e);
    else if (activeTab === 'accents') handleAccentsTabClick(e);
    else if (activeTab === 'setlist') handleSetlistClick(e);
  });
  // (Finetuning modal is now triggered by single click on mini-waveform in handlePartsTabClick)
  els.content.addEventListener('change', (e) => {
    if (activeTab === 'parts') handlePartsTabChange(e);
    else if (activeTab === 'takte') handleTakteTabChange(e);
    else if (activeTab === 'lyrics') handleLyricsChange(e);
    else if (activeTab === 'setlist') handleSetlistChange(e);
  });
  // Parts tab: clear placeholder names ("Part 1", "New Part") on focus
  // + scroll focused input into view after iOS keyboard opens
  els.content.addEventListener('focus', (e) => {
    if (activeTab === 'parts' && e.target.matches('[data-ptf="name"]')) {
      if (/^(Part \d+|New Part)$/i.test(e.target.value.trim())) {
        e.target.value = '';
      }
    }
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
      if (e.key === 'p' || e.key === 'P') { handlePartTap(); }
      if (e.key === 'b' || e.key === 'B') { handleBarTap(); }
      if (e.key === 'z' || e.key === 'Z') { if (!e.ctrlKey && !e.metaKey) handleUndoTap(); }
    }

    // Lyrics tab: no keyboard shortcuts needed (per-part play via buttons)
  });
}

/* ── Boot ──────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  wireEvents();
  initPartWaveEditor();
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
