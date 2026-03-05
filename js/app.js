/**
 * js/app.js — lighting.ai DB Editor
 *
 * Meilenstein 2: Vollstaendiger DB Editor mit Song-Detail, Parts-Tabelle,
 * Bar-Editor mit 16tel-Accent-Raster und Summary-Bar.
 */

import { loadDB, loadDBLocal, saveDB, testConnection, uploadFile, deleteFile, getSha } from './db.js';
import * as audio from './audio-engine.js';
import * as integrity from './integrity.js';

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

/* ── Lyrics Tab State ───────────────────────────── */
let _lyricsPlayingPart = null;    // partId currently playing in lyrics tab
let _lyricsPausedPart = null;     // partId currently paused in lyrics tab
let _lyricsCollapsed = new Set(); // Set of partIds that are collapsed

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

const SETTINGS_KEY = 'lightingai_settings';

/* ── Constants ─────────────────────────────────────── */

const LIGHT_TEMPLATES = [
  'intro_buildup', 'intro_hit',
  'verse_minimal', 'verse_driving', 'verse_dark',
  'prechorus_rise',
  'chorus_half', 'chorus_full', 'chorus_anthem',
  'bridge_atmospheric', 'bridge_breakdown',
  'solo_spotlight', 'solo_intense',
  'breakdown_minimal', 'buildup_8bars', 'drop_impact',
  'outro_fadeout', 'outro_cut',
  'ballad_warm', 'generic_bpm'
];

const ACCENT_TYPES = ['bl', 'bo', 'hl', 'st', 'fg'];

const ACCENT_INFO = {
  bl: 'Blinder', bo: 'Blackout', hl: 'Highlight', st: 'Strobe', fg: 'Fog'
};

const BEAT_LABELS = ['1','e','+','e','2','e','+','e','3','e','+','e','4','e','+','e'];

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
    tabSetlist:    document.getElementById('tab-setlist'),
    btnSettings:   document.getElementById('btn-settings'),
    btnSave:       document.getElementById('btn-save'),
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
    const res = await fetch(url);
    if (res.ok) {
      const ct = res.headers.get('content-type') || '';
      if (!ct.includes('text/html')) return await res.arrayBuffer();
    }
  } catch { /* fall through */ }

  // 2. GitHub API fetch
  if (s.token && s.repo) {
    try {
      const apiUrl = `https://api.github.com/repos/${s.repo}/contents/${url}`;
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
    filtered.map(s => `
    <div class="song-item${s.id === selectedSongId ? ' active' : ''}" data-id="${s.id}">
      <div style="flex:1;min-width:0">
        <div class="song-name">${esc(s.name)}</div>
        <div class="song-artist">${esc(s.artist)}</div>
      </div>
      <div class="song-bpm">${s.bpm || ''}</div>
    </div>
  `).join('');
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
  if (tab === 'lyrics' || tab === 'audio' || tab === 'parts' || tab === 'takte') {
    audio.warmup();
  }
  activeTab = tab;
  els.tabEditor?.classList.toggle('active', tab === 'editor');
  els.tabParts?.classList.toggle('active', tab === 'parts');
  els.tabTakte?.classList.toggle('active', tab === 'takte');
  els.tabAudio?.classList.toggle('active', tab === 'audio');
  els.tabLyrics?.classList.toggle('active', tab === 'lyrics');
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
}

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
        <input type="number" value="${song.bpm || ''}" data-song-field="bpm" class="mono" min="0">
      </div>
      <div>
        <label>Key</label>
        <input type="text" value="${esc(song.key || '')}" data-song-field="key">
      </div>
      <div>
        <label>Jahr</label>
        <input type="text" value="${esc(song.year || '')}" data-song-field="year">
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
          <th class="pt-dur">Dauer</th>
          <th class="pt-tmpl">Template</th>
          <th class="pt-grip"></th>
        </tr>
      </thead>
      <tbody>
        ${parts.map(p => {
          const audioBars = getAudioBarsForPart(p.id);
          const hasAudio = audioBars.length > 0;
          const isPlaying = _partPlayActive && _playingPartId === p.id;
          const st = starts.get(p.id) || { startBar: 0, startSec: 0 };
          const dur = calcPartDuration(p.bars, song.bpm);
          return `
          <tr class="part-row${p.id === selectedPartId ? ' active' : ''}" data-part-id="${p.id}">
            <td class="pt-pos mono text-t3">${p.pos}</td>
            <td class="pt-play">${hasAudio ? `<button class="btn-part-play${isPlaying ? ' playing' : ''}" data-action="play-part" data-part-id="${p.id}" title="${isPlaying ? 'Stop' : 'Part abspielen'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}</td>
            <td class="pt-name">${esc(p.name)}</td>
            <td class="pt-start mono text-t3">${st.startBar} <span class="text-t4">${fmtDur(Math.round(st.startSec))}</span></td>
            <td class="pt-bars mono">${p.bars || 0}</td>
            <td class="pt-dur mono text-t3">${fmtDur(dur)}</td>
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
        light_template: 'generic_bpm', notes: ''
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
      delete song.parts[selectedPartId];
      // Renumber
      getSortedParts(selectedSongId).forEach((p, i) => { song.parts[p.id].pos = i + 1; });
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
  if (activeTab === 'editor') renderPartsTable();
  else if (activeTab === 'parts') renderPartsTab();
  else if (activeTab === 'takte') renderTakteTab();
}

async function handlePartPlay(partId) {
  // If already playing this part → stop
  if (_playingPartId === partId && _partPlayActive) {
    stopPartPlay();
    return;
  }

  // Stop any current playback
  stopPartPlay();

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
    loadReferenceAudio().finally(() => { _refLoadingFor = null; });
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
  const nextPartName = currentPartIndex < parts.length ? parts[currentPartIndex].name : '\u2014';
  const allPartsDone = currentPartIndex >= parts.length;
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
  if (currentPartIndex < parts.length) return '';
  if (parts.length === 0) return '';

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
  const w = baseW * waveformZoom;
  const h = 120;

  // Size the scrollable inner container
  scroll.style.width = w + 'px';
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  // Clear
  ctx.clearRect(0, 0, w, h);

  const buf = audio.getBuffer();
  if (!buf) return;
  const duration = buf.duration;

  // Draw waveform bars (1px per bar for high resolution at all zoom levels)
  const buckets = Math.floor(w);
  const peaks = audio.getPeaks(buckets);
  const barW = 1;
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
    const barH = amp * (h * 0.9);
    const opacity = 0.3 + amp * 0.7;
    ctx.fillStyle = `rgba(0, 220, 130, ${opacity})`;
    ctx.fillRect(i * barW, mid - barH / 2, Math.max(barW - 0.5, 1), barH || 1);
  }

  // Bar markers (cyan lines — highlight when dragging, with absolute bar number)
  for (let bi = 0; bi < barMarkers.length; bi++) {
    const m = barMarkers[bi];
    const x = (m.time / duration) * w;
    const absBarNum = bi + 1; // absolute bar number from song start
    const isDragTarget = _isDragging && _dragMarker && _dragMarker.type === 'bar' && _dragMarker.index === bi;
    ctx.strokeStyle = isDragTarget ? 'rgba(56, 189, 248, 0.9)' : 'rgba(56, 189, 248, 0.4)';
    ctx.lineWidth = isDragTarget ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    // Bar number label (skip if a part marker sits at same position — part label takes priority)
    const isPartStart = partMarkers.some(pm => Math.abs(pm.time - m.time) < 0.01);
    if (!isPartStart) {
      ctx.font = '9px "DM Mono", monospace';
      ctx.fillStyle = isDragTarget ? 'rgba(56, 189, 248, 0.95)' : 'rgba(56, 189, 248, 0.6)';
      ctx.fillText(String(absBarNum), x + 3, 10);
    }
    if (isDragTarget) {
      ctx.font = '10px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(56, 189, 248, 0.95)';
      ctx.fillText(fmtTime(m.time), x + 4, h / 2);
    }
  }

  // Compute absolute bar offset per part from DB bar counts
  const parts = getSortedParts(selectedSongId);
  const partStartBar = {}; // partIndex → first absolute bar number
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
      const x = (st.startSec / duration) * w;
      // Ghost line
      ctx.strokeStyle = 'rgba(240, 160, 48, 0.25)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      // Ghost label (only if no tapped marker near this position)
      const hasTapped = partMarkers.some(m => m.partIndex === pi);
      if (!hasTapped) {
        ctx.font = '9px Sora, sans-serif';
        ctx.fillStyle = 'rgba(240, 160, 48, 0.35)';
        const label = parts[pi].name;
        const labelX = Math.min(x + 3, w - ctx.measureText(label).width - 3);
        ctx.fillText(label, labelX, 11);
      }
    }
    ctx.setLineDash([]);
  }

  // Part markers (amber) with part name + absolute bar number
  for (let pi2 = 0; pi2 < partMarkers.length; pi2++) {
    const m = partMarkers[pi2];
    const x = (m.time / duration) * w;
    const isDragTarget = _isDragging && _dragMarker && _dragMarker.type === 'part' && _dragMarker.index === pi2;
    ctx.strokeStyle = isDragTarget ? 'rgba(240, 160, 48, 1.0)' : 'rgba(240, 160, 48, 0.8)';
    ctx.lineWidth = isDragTarget ? 3 : 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();

    // Part name label (top)
    const partName = m.partIndex < parts.length ? parts[m.partIndex].name : '';
    if (partName) {
      ctx.font = '10px Sora, sans-serif';
      ctx.fillStyle = 'rgba(240, 160, 48, 0.9)';
      const labelX = Math.min(x + 4, w - ctx.measureText(partName).width - 4);
      ctx.fillText(partName, labelX, 12);
    }

    // Absolute bar number above bottom (or time during drag)
    // Use barMarkers (tapped) if available, fallback to DB-based count
    const firstBarIdx = barMarkers.findIndex(b => b.partIndex === m.partIndex);
    const startBar = firstBarIdx >= 0 ? firstBarIdx + 1 : partStartBar[m.partIndex];
    if (isDragTarget) {
      ctx.font = '11px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(240, 160, 48, 1.0)';
      ctx.fillText(fmtTime(m.time), x + 4, h - 14);
    } else if (startBar !== undefined) {
      ctx.font = '11px "DM Mono", monospace';
      ctx.fillStyle = 'rgba(240, 160, 48, 0.85)';
      ctx.fillText(String(startBar), x + 4, h - 14);
    }
  }

  // Playhead (green with glow)
  const cur = audio.getCurrentTime();
  if (cur > 0 || audio.isPlaying()) {
    const px = (cur / duration) * w;
    ctx.shadowColor = '#00dc82';
    ctx.shadowBlur = 6;
    ctx.strokeStyle = '#00dc82';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(px, 0);
    ctx.lineTo(px, h);
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Auto-scroll to keep playhead visible when zoomed
    if (waveformZoom > 1 && !_suppressAutoScroll) {
      const scrollLeft = wrap.scrollLeft;
      const viewW = wrapRect.width;
      if (px < scrollLeft + 40 || px > scrollLeft + viewW - 40) {
        wrap.scrollLeft = px - viewW * 0.3;
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

/**
 * Find the nearest marker to a given x pixel position on the waveform.
 * Returns { type: 'part'|'bar', index, marker, distPx } or null.
 */
function hitTestMarker(xPx) {
  if (!audioMeta) return null;
  const scroll = document.getElementById('waveform-scroll');
  if (!scroll) return null;
  const totalW = scroll.getBoundingClientRect().width;
  const duration = audioMeta.duration;
  if (duration <= 0 || totalW <= 0) return null;

  let best = null;
  let bestDist = DRAG_HIT_PX + 1;

  // Check part markers
  for (let i = 0; i < partMarkers.length; i++) {
    const mx = (partMarkers[i].time / duration) * totalW;
    const dist = Math.abs(xPx - mx);
    if (dist < bestDist) {
      bestDist = dist;
      best = { type: 'part', index: i, marker: partMarkers[i], distPx: dist };
    }
  }

  // Check bar markers
  for (let i = 0; i < barMarkers.length; i++) {
    const mx = (barMarkers[i].time / duration) * totalW;
    const dist = Math.abs(xPx - mx);
    if (dist < bestDist) {
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

function onWaveformPointerDown(e) {
  if (!audioMeta) return;
  // Only handle primary button (left click) or single touch
  if (e.type === 'mousedown' && e.button !== 0) return;
  if (e.touches && e.touches.length > 1) return; // Ignore multi-touch

  const x = waveformEventX(e);
  const hit = hitTestMarker(x);
  if (!hit) return; // No marker hit → let click handler do seek

  // Start potential drag
  _dragMarker = {
    type: hit.type,
    index: hit.index,
    originalTime: hit.marker.time,
  };
  _isDragging = false;
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
    }
  } else {
    // Hover cursor: show col-resize when near a marker
    const x = waveformEventX(e);
    const hit = hitTestMarker(x);
    wrap.style.cursor = hit ? 'col-resize' : 'crosshair';
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
  const wrap = document.getElementById('waveform-wrap');
  if (wrap) {
    wrap.classList.remove('dragging');
    wrap.style.cursor = 'crosshair';
  }
  _dragMarker = null;
  _isDragging = false;
}

function onWaveformPointerUp(e) {
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

  // Touch events (iPad support)
  wrap.addEventListener('touchstart', onWaveformPointerDown, { passive: false });
  document.addEventListener('touchmove', onWaveformPointerMove, { passive: false });
  document.addEventListener('touchend', onWaveformPointerUp);
  document.addEventListener('touchcancel', cancelDrag);
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

  // Don't seek if clicking on a marker — drag handles that
  const hit = hitTestMarker(x);
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
  const allPartsDone = currentPartIndex >= parts.length;

  const partBtn = document.getElementById('tap-part');
  const barBtn = document.getElementById('tap-bar');
  const undoBtn = document.getElementById('tap-undo');

  if (partBtn) partBtn.disabled = !isPlay || allPartsDone;
  if (barBtn) barBtn.disabled = !isPlay || currentPartIndex === 0;
  if (undoBtn) undoBtn.disabled = tapHistory.length === 0;
}

function handlePartTap() {
  if (!audio.isPlaying()) return;
  const parts = getSortedParts(selectedSongId);
  if (currentPartIndex >= parts.length) return;

  const time = audio.getCurrentTime();

  // Add part marker
  partMarkers.push({ time, partIndex: currentPartIndex });

  // Automatically add first bar marker at the same position as the part marker
  barMarkers.push({ time, partIndex: currentPartIndex });

  // Record for undo (both part + auto-bar)
  tapHistory.push({ type: 'part', time, partIndex: currentPartIndex, autoBar: true });

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

  const time = audio.getCurrentTime();

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

async function handleDeleteAllParts() {
  if (partMarkers.length === 0) return;
  const ok = await showConfirm(
    'Alle Parts löschen?',
    `Alle <strong>${partMarkers.length} Part-Marker</strong> und <strong>${barMarkers.length} Bar-Marker</strong> werden entfernt.`,
    'Löschen'
  );
  if (!ok) return;
  partMarkers = [];
  barMarkers = [];
  tapHistory = [];
  currentPartIndex = 0;
  currentBarInPart = 0;
  saveMarkersToSong();
  markDirty();
  drawWaveform();
  const parts = getSortedParts(selectedSongId);
  updateTapInfo(parts);
  updateSplitResultLive(parts);
  updateAudioSummaryLive(parts);
  updateTapButtonStates();
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
  markDirty();
  drawWaveform();
  const parts = getSortedParts(selectedSongId);
  updateTapInfo(parts);
  updateSplitResultLive(parts);
  updateAudioSummaryLive(parts);
  updateTapButtonStates();
}

/* ── Speed / Zoom / Part-Seek / Marker Edit ─────── */

const SPEED_STEPS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5];
const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6, 8, 10];

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
  drawWaveform();
  renderAudioTab();
}

function updateTapInfo(parts) {
  const partBtn = document.getElementById('tap-part');
  const barBtn = document.getElementById('tap-bar');

  if (partBtn) {
    const info = partBtn.querySelector('.tap-info');
    const nextName = currentPartIndex < parts.length ? parts[currentPartIndex].name : '\u2014';
    if (info) info.textContent = nextName;
    partBtn.disabled = !audio.isPlaying() || currentPartIndex >= parts.length;
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
  if (currentPartIndex < parts.length) return;

  exportInProgress = true;
  renderAudioTab();

  const fillEl = () => document.getElementById('export-fill');
  const textEl = () => document.getElementById('export-text');

  // Count total bars across all parts
  const totalBars = barMarkers.length;
  let done = 0;

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
              if (textEl()) textEl().textContent = `L\u00f6sche alten Bar ${oldBar.bar_num}...`;
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

        if (textEl()) textEl().textContent = `Exportiere ${part.name} Bar ${barNum}... (${done + 1}/${totalBars})`;

        const base64mp3 = await audio.exportSegmentMp3(barStart, barEnd);
        const path = buildBarAudioPath(song, part, barNum, globalBarNum);

        await uploadFile(s.repo, path, s.token, base64mp3, `Audio: ${part.name} Bar ${barNum} (${songName})`);

        // Update bar record in DB (preserves existing lyrics/accents)
        const [barId, barData] = getOrCreateBar(part.id, barNum);
        barData.audio = path;

        done++;
        const pct = (done / totalBars * 100).toFixed(0);
        if (fillEl()) fillEl().style.width = pct + '%';
        if (textEl()) textEl().textContent = `${done}/${totalBars} hochgeladen`;
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
    renderAudioTab();
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
   LYRICS TAB — Part-basierter Songtext-Editor
   ══════════════════════════════════════════════════════ */

function renderLyricsTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9835;</div><p>Song aus der Liste links ausw&auml;hlen.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  const hasBuf = !!audio.getBuffer();

  // Auto-load reference audio
  if (!hasBuf && song.audio_ref && _refLoadingFor !== selectedSongId) {
    _refLoadingFor = selectedSongId;
    loadReferenceAudio().finally(() => { _refLoadingFor = null; });
  }

  const geniusUrl = `https://genius.com/search?q=${encodeURIComponent(song.name + ' ' + song.artist)}`;

  // Check if any part has lyrics in DB bars
  ensureCollections();

  els.content.innerHTML = `
    <div class="lyrics-panel">
      <div class="lyrics-scroll" id="lyrics-scroll">
        ${buildSongHeader(song)}
        ${buildLyricsRawImport(song, geniusUrl)}
        ${parts.length > 0 ? buildLyricsPartsList(parts, song, hasBuf) : '<div class="empty-state"><p>Keine Parts vorhanden. Erst Parts im Parts-Tab anlegen.</p></div>'}
      </div>
    </div>`;

  // Draw lyrics waveforms after DOM is ready
  requestAnimationFrame(() => {
    drawLyricsPartWaveforms();
    // Attach drag listeners to lyrics wave canvases
    const canvases = document.querySelectorAll('canvas[data-lyrics-wave-idx]');
    for (const c of canvases) {
      c.addEventListener('mousedown', initLyricsWaveDrag);
      c.addEventListener('touchstart', initLyricsWaveDrag, { passive: false });
    }
  });
}

function buildLyricsRawImport(song, geniusUrl) {
  const raw = song.lyrics_raw || '';
  return `
    <div class="lyrics-raw-section" id="lyrics-raw-section">
      <div class="lyrics-raw-header">
        <h3>Rohtext</h3>
        <a href="${geniusUrl}" target="_blank" rel="noopener" class="btn btn-sm lyrics-genius-link" title="Auf Genius.com suchen">&#127925; Genius.com</a>
      </div>
      <textarea id="lyrics-raw-text" class="lyrics-paste" rows="8" placeholder="Songtext hier einfuegen...&#10;Tipp: Auf Genius.com den Songtext kopieren und hier einfuegen.&#10;Dann auf VERTEILEN klicken, um den Text auf die Parts aufzuteilen.">${esc(raw)}</textarea>
      <div class="lyrics-import-actions">
        <button class="btn btn-sm" id="lyrics-distribute-btn" title="Rohtext automatisch auf Parts verteilen">VERTEILEN</button>
      </div>
    </div>`;
}

/**
 * Extract base function name from a part name (e.g. "Chorus 2" → "Chorus", "Bridge" → "Bridge").
 * Returns null for Verse/Strophe parts (those are excluded from lyrics copying).
 */
function getLyricsPartBaseName(name) {
  if (!name) return null;
  const n = name.trim();
  // Exclude Verse / Strophe
  if (/^(verse|strophe)\b/i.test(n)) return null;
  // Strip trailing number: "Chorus 2" → "Chorus", "Bridge" → "Bridge"
  return n.replace(/\s*\d+\s*$/, '').trim() || null;
}

function buildLyricsPartsList(parts, song, hasBuf) {
  // Count non-instrumental parts for the toggle-all button
  const nonInstrParts = parts.filter(p => !p.instrumental);
  const allCollapsed = nonInstrParts.length > 0 && nonInstrParts.every(p => _lyricsCollapsed.has(p.id));

  let html = '<div class="lyrics-parts-toolbar">';
  if (nonInstrParts.length > 1) {
    html += `<button class="btn btn-sm" id="lyrics-toggle-all" title="${allCollapsed ? 'Alle aufklappen' : 'Alle zuklappen'}">${allCollapsed ? '&#9660; Alle aufklappen' : '&#9650; Alle zuklappen'}</button>`;
  }
  html += '</div>';
  html += '<div class="lyrics-parts-list" id="lyrics-parts-list">';

  let absBarOffset = 0; // cumulative bar count for absolute numbering
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    const barCount = part.bars || 0;
    const dur = calcPartDuration(barCount, song.bpm || 0);
    const isInstr = !!part.instrumental;
    const isCollapsed = !isInstr && _lyricsCollapsed.has(part.id);

    // Collect existing lyrics from DB bars
    const barLyrics = [];
    for (let b = 1; b <= barCount; b++) {
      const found = findBar(part.id, b);
      barLyrics.push(found ? (found[1].lyrics || '') : '');
    }
    const lyricsText = barLyrics.join('\n');
    const lyricsPreview = barLyrics.filter(l => l).slice(0, 2).join(' / ');

    // Can we play this part?
    const canPlayRef = hasBuf && partMarkers.some(m => m.partIndex === i);
    const canPlayBars = getAudioBarsForPart(part.id).length > 0;
    const canPlay = canPlayRef || canPlayBars;
    const isPlaying = _lyricsPlayingPart === part.id;
    const isPaused = _lyricsPausedPart === part.id;

    // Find previous part with same base name (for "copy lyrics" button)
    const baseName = getLyricsPartBaseName(part.name);
    let prevSamePartId = null;
    let prevSamePartName = null;
    if (baseName && !isInstr) {
      for (let j = i - 1; j >= 0; j--) {
        if (getLyricsPartBaseName(parts[j].name) === baseName && !parts[j].instrumental) {
          prevSamePartId = parts[j].id;
          prevSamePartName = parts[j].name;
          break;
        }
      }
    }

    html += `
      <div class="lyrics-part-card${isInstr ? ' instrumental' : ''}${isCollapsed ? ' collapsed' : ''}" data-part-id="${part.id}" data-part-index="${i}">
        <div class="lyrics-part-header">
          ${!isInstr ? `<button class="lyrics-collapse-btn" data-lyrics-collapse="${part.id}" title="${isCollapsed ? 'Aufklappen' : 'Zuklappen'}">${isCollapsed ? '&#9654;' : '&#9660;'}</button>` : ''}
          <span class="lyrics-part-name text-amber">${esc(part.name)}</span>
          <span class="lyrics-part-info text-t3 mono">${barCount} Takte${dur ? ' \u00b7 ' + fmtTime(dur) : ''}</span>
          ${isCollapsed && lyricsPreview ? `<span class="lyrics-preview text-t3">${esc(lyricsPreview)}</span>` : ''}
          <label class="lyrics-instr-label" title="Instrumental (kein Text)">
            <input type="checkbox" class="lyrics-instr-check" data-instr-part="${part.id}" ${isInstr ? 'checked' : ''}>
            <span>Instrumental</span>
          </label>
          <div style="flex:1"></div>
          ${prevSamePartId ? `<button class="btn btn-sm btn-lyrics-copy" data-lyrics-copy-from="${prevSamePartId}" data-lyrics-copy-to="${part.id}" title="Text aus ${esc(prevSamePartName)} übernehmen">Text aus ${esc(prevSamePartName)} &#x2192;</button>` : ''}
          ${canPlay ? `<button class="btn btn-sm btn-part-play${isPlaying ? ' playing' : ''}${isPaused ? ' paused' : ''}" data-lyrics-play="${part.id}" data-part-index="${i}" title="${isPlaying ? 'Pause' : isPaused ? 'Fortsetzen' : 'Part abspielen'}">
            ${isPlaying ? '&#9646;&#9646;' : '&#9654;'}
          </button>` : ''}
        </div>
        ${!isInstr && !isCollapsed ? buildLyricsPartBody(part, i, barCount, barLyrics, hasBuf, absBarOffset) : ''}
      </div>`;
    absBarOffset += barCount;
  }

  html += '</div>';
  return html;
}

/**
 * Build the body of a lyrics part card: waveform + horizontal bar inputs.
 */
function buildLyricsPartBody(part, partIndex, barCount, barLyrics, hasBuf, absBarOffset) {
  if (barCount === 0) {
    return '<div class="lyrics-part-bar-hint text-t3">Keine Takte definiert</div>';
  }

  // Waveform canvas for this part (if audio is loaded and part markers exist)
  const partMarker = partMarkers.find(m => m.partIndex === partIndex);
  const partEnd = getPartEndTime(partIndex);
  const showWave = hasBuf && partMarker && partEnd;

  // Uniform cell width: determined by the longest text in any bar of this part
  const PX_PER_CHAR = 7;
  const CELL_PAD = 10;
  const MIN_CELL_W = 32;
  const maxTextLen = barLyrics.reduce((mx, t) => Math.max(mx, (t || '').length), 0);
  const cellW = Math.max(MIN_CELL_W, maxTextLen * PX_PER_CHAR + CELL_PAD);
  const totalMinWidth = cellW * barCount;

  // Build scrollable container for waveform + bars (scroll together)
  const minWStyle = totalMinWidth > 0 ? `min-width:${totalMinWidth}px` : '';
  let html = `<div class="lyrics-part-scroll">`;
  html += `<div class="lyrics-part-scroll-inner" ${minWStyle ? `style="${minWStyle}"` : ''}>`;

  if (showWave) {
    html += `<div class="lyrics-wave-wrap" data-lyrics-wave-part="${partIndex}">
      <canvas class="lyrics-wave-canvas" data-lyrics-wave-idx="${partIndex}" data-wave-start="${partMarker.time}" data-wave-end="${partEnd}"></canvas>
    </div>`;
  }

  // Horizontal bar inputs — all equal width, waveform stretches to match
  html += '<div class="lyrics-bars-row">';
  for (let b = 0; b < barCount; b++) {
    const text = barLyrics[b] || '';
    const absBarNum = absBarOffset + b + 1;
    html += `<div class="lyrics-bar-cell" style="flex:1 1 0;min-width:${cellW}px">
      <div class="lyrics-bar-num mono text-t3">${absBarNum}</div>
      <input type="text" class="lyrics-bar-input" data-lyrics-bar-part="${part.id}" data-lyrics-bar-num="${b + 1}" value="${esc(text)}" placeholder="\u2014">
    </div>`;
  }
  html += '</div>';
  html += '</div></div>';

  return html;
}

/**
 * Draw waveform with bar markers for a lyrics part canvas.
 * Called after renderLyricsTab to populate canvases.
 */
function drawLyricsPartWaveforms() {
  if (!audio.getBuffer() || !audioMeta) return;
  const canvases = document.querySelectorAll('canvas[data-lyrics-wave-idx]');
  for (const canvas of canvases) {
    drawLyricsPartWaveform(canvas);
  }
}

function drawLyricsPartWaveform(canvas) {
  if (!audio.getBuffer() || !audioMeta) return;
  const partIndex = parseInt(canvas.dataset.lyricsWaveIdx, 10);
  const startSec = parseFloat(canvas.dataset.waveStart);
  const endSec = parseFloat(canvas.dataset.waveEnd);
  if (isNaN(startSec) || isNaN(endSec) || endSec <= startSec) return;

  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w <= 0 || h <= 0) return;

  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  // Draw waveform
  const buckets = Math.floor(w);
  const peaks = audio.getPeaksRange(startSec, endSec, buckets);
  const mid = h / 2;
  for (let i = 0; i < buckets; i++) {
    const amp = peaks[i];
    const barH = amp * (h * 0.85);
    const opacity = 0.3 + amp * 0.7;
    ctx.fillStyle = `rgba(0, 220, 130, ${opacity})`;
    ctx.fillRect(i, mid - barH / 2, 1, barH || 1);
  }

  // Draw bar markers
  const partDur = endSec - startSec;
  const bars = getBarMarkersForPart(partIndex);
  for (let bi = 0; bi < bars.length; bi++) {
    const relTime = bars[bi].time - startSec;
    const x = (relTime / partDur) * w;
    const isDrag = _lyricsWaveDrag && _lyricsWaveDrag.partIndex === partIndex && _lyricsWaveDrag.barIdx === bi;
    ctx.strokeStyle = isDrag ? 'rgba(56, 189, 248, 0.95)' : 'rgba(56, 189, 248, 0.5)';
    ctx.lineWidth = isDrag ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();

    // Bar number label
    ctx.font = '9px "DM Mono", monospace';
    ctx.fillStyle = isDrag ? 'rgba(56, 189, 248, 0.95)' : 'rgba(56, 189, 248, 0.6)';
    ctx.fillText(String(bi + 1), x + 2, 10);

    if (isDrag) {
      ctx.fillStyle = 'rgba(56, 189, 248, 0.95)';
      ctx.fillText(fmtTime(bars[bi].time), x + 2, h - 3);
    }
  }
}

/* ── Lyrics Waveform Bar Marker Drag ─────────────── */

let _lyricsWaveDrag = null; // { canvas, partIndex, barIdx, startX, startTime, bars }

function initLyricsWaveDrag(e) {
  const canvas = e.target.closest('canvas[data-lyrics-wave-idx]');
  if (!canvas || !audioMeta) return;
  const partIndex = parseInt(canvas.dataset.lyricsWaveIdx, 10);
  const startSec = parseFloat(canvas.dataset.waveStart);
  const endSec = parseFloat(canvas.dataset.waveEnd);
  if (isNaN(startSec) || isNaN(endSec)) return;

  const rect = canvas.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const xPx = clientX - rect.left;
  const w = rect.width;
  const partDur = endSec - startSec;
  const clickTime = startSec + (xPx / w) * partDur;

  // Hit test: find nearest bar marker
  const bars = getBarMarkersForPart(partIndex);
  let bestIdx = -1, bestDist = Infinity;
  for (let i = 0; i < bars.length; i++) {
    const mX = ((bars[i].time - startSec) / partDur) * w;
    const dist = Math.abs(mX - xPx);
    if (dist < bestDist) { bestDist = dist; bestIdx = i; }
  }
  if (bestIdx < 0 || bestDist > 12) return; // 12px threshold

  e.preventDefault();
  _lyricsWaveDrag = {
    canvas, partIndex, barIdx: bestIdx, startSec, endSec,
    origTime: bars[bestIdx].time
  };
  drawLyricsPartWaveform(canvas);
}

function moveLyricsWaveDrag(e) {
  if (!_lyricsWaveDrag) return;
  e.preventDefault();
  const { canvas, partIndex, barIdx, startSec, endSec } = _lyricsWaveDrag;
  const rect = canvas.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const xPx = clientX - rect.left;
  const w = rect.width;
  const partDur = endSec - startSec;

  let newTime = startSec + (xPx / w) * partDur;
  newTime = Math.max(startSec + 0.01, Math.min(endSec - 0.01, newTime));

  // Update the actual barMarkers array
  const bars = getBarMarkersForPart(partIndex);
  if (bars[barIdx]) {
    // Find in global barMarkers
    const globalIdx = barMarkers.findIndex(m =>
      m.partIndex === partIndex && Math.abs(m.time - bars[barIdx].time) < 0.0001);
    if (globalIdx >= 0) {
      barMarkers[globalIdx].time = newTime;
    }
  }

  drawLyricsPartWaveform(canvas);
}

function endLyricsWaveDrag() {
  if (!_lyricsWaveDrag) return;
  const moved = _lyricsWaveDrag;
  _lyricsWaveDrag = null;

  // Re-sort global bar markers and save
  barMarkers.sort((a, b) => a.time - b.time);
  saveMarkersToSong();
  drawLyricsPartWaveform(moved.canvas);
}

/**
 * Distribute raw text across parts based on blank-line separation.
 * Section headers like [Verse 1] are matched to part names if possible.
 */
function distributeLyricsToparts() {
  if (!selectedSongId) return;
  const song = db.songs[selectedSongId];
  const rawEl = document.getElementById('lyrics-raw-text');
  if (!rawEl) return;

  const rawText = rawEl.value.trim();
  if (!rawText) { toast('Kein Rohtext vorhanden', 'error'); return; }

  // Save raw text
  song.lyrics_raw = rawEl.value;

  const parts = getSortedParts(selectedSongId);
  if (parts.length === 0) { toast('Keine Parts vorhanden', 'error'); return; }

  // Split into sections by blank lines
  const sections = [];
  let currentSection = [];
  for (const line of rawText.split('\n')) {
    if (line.trim() === '' && currentSection.length > 0) {
      sections.push(currentSection);
      currentSection = [];
    } else if (line.trim() !== '') {
      // Skip section headers like [Verse 1]
      if (/^\[.*\]$/.test(line.trim())) continue;
      currentSection.push(line);
    }
  }
  if (currentSection.length > 0) sections.push(currentSection);

  if (sections.length === 0) { toast('Kein verteilbarer Text gefunden', 'error'); return; }

  // Distribute sections to parts (skip instrumental parts)
  let sIdx = 0;
  for (let i = 0; i < parts.length && sIdx < sections.length; i++) {
    const part = parts[i];
    const barCount = part.bars || 0;
    if (barCount === 0 || part.instrumental) continue;

    const section = sections[sIdx];
    sIdx++;

    // Fill individual bar inputs
    for (let b = 0; b < barCount; b++) {
      const inp = document.querySelector(`.lyrics-bar-input[data-lyrics-bar-part="${part.id}"][data-lyrics-bar-num="${b + 1}"]`);
      if (inp) inp.value = b < section.length ? section[b] : '';
    }
  }

  markDirty();
  toast(`Text auf ${Math.min(sIdx, parts.length)} Parts verteilt`, 'success');
}

/* ── Lyrics Part Playback ─────────────────────────── */

let _lyricsAnimFrame = null;        // animation frame for lyrics playhead
let _lyricsPlayPartIndex = null;    // partIndex currently playing

function handleLyricsPartPlay(partId, partIndex) {
  // Pause if currently playing this part
  if (_lyricsPlayingPart === partId) {
    pauseLyricsPartPlay();
    return;
  }

  // Resume if this part is paused
  if (_lyricsPausedPart === partId) {
    resumeLyricsPartPlay();
    return;
  }

  // Stop any previous playback or paused state
  if (_lyricsPlayingPart) stopLyricsPartPlay();
  if (_lyricsPausedPart) clearLyricsPausedState();

  _lyricsPlayingPart = partId;
  _lyricsPlayPartIndex = partIndex;
  updateLyricsPlayButtons();

  // Try reference audio segment first
  const hasBuf = !!audio.getBuffer();
  const startTime = getPartStartTime(partIndex);
  const endTime = getPartEndTime(partIndex);

  if (hasBuf && startTime !== null && endTime !== null) {
    audio.playSegments([{ startTime, endTime }], () => {
      _lyricsPlayingPart = null;
      _lyricsPausedPart = null;
      _lyricsPlayPartIndex = null;
      stopLyricsPlayheadAnimation();
      updateLyricsPlayButtons();
    });
    startLyricsPlayheadAnimation();
    return;
  }

  // Fallback: play bar MP3 files (no pause support for bar-by-bar playback)
  handlePartPlay(partId);

  const origInterval = setInterval(() => {
    if (!_partPlayActive) {
      clearInterval(origInterval);
      _lyricsPlayingPart = null;
      _lyricsPlayPartIndex = null;
      updateLyricsPlayButtons();
    }
  }, 200);
}

function pauseLyricsPartPlay() {
  if (!_lyricsPlayingPart) return;
  audio.pauseSegments();
  stopLyricsPlayheadAnimation();
  _lyricsPausedPart = _lyricsPlayingPart;
  _lyricsPlayingPart = null;
  updateLyricsPlayButtons();
}

function resumeLyricsPartPlay() {
  if (!_lyricsPausedPart) return;
  _lyricsPlayingPart = _lyricsPausedPart;
  _lyricsPausedPart = null;
  audio.resumeSegments();
  startLyricsPlayheadAnimation();
  updateLyricsPlayButtons();
}

function clearLyricsPausedState() {
  if (_lyricsPausedPart) {
    audio.stopSegments();
    _lyricsPausedPart = null;
    _lyricsPlayPartIndex = null;
  }
}

function stopLyricsPartPlay() {
  if (_lyricsPlayingPart || _lyricsPausedPart) {
    audio.stopSegments();
    stopPartPlay();
    stopLyricsPlayheadAnimation();
    _lyricsPlayingPart = null;
    _lyricsPausedPart = null;
    _lyricsPlayPartIndex = null;
    updateLyricsPlayButtons();
  }
}

function startLyricsPlayheadAnimation() {
  cancelAnimationFrame(_lyricsAnimFrame);
  function tick() {
    drawLyricsPlayhead();
    if (audio.isSegmentPlaying()) {
      _lyricsAnimFrame = requestAnimationFrame(tick);
    }
  }
  _lyricsAnimFrame = requestAnimationFrame(tick);
}

function stopLyricsPlayheadAnimation() {
  cancelAnimationFrame(_lyricsAnimFrame);
  _lyricsAnimFrame = null;
  // Redraw without playhead
  drawLyricsPartWaveforms();
}

function drawLyricsPlayhead() {
  if (_lyricsPlayPartIndex === null) return;
  const canvas = document.querySelector(`canvas[data-lyrics-wave-idx="${_lyricsPlayPartIndex}"]`);
  if (!canvas) return;

  // Redraw base waveform first
  drawLyricsPartWaveform(canvas);

  // Draw playhead
  const curTime = audio.getSegmentCurrentTime();
  if (curTime <= 0) return;

  const startSec = parseFloat(canvas.dataset.waveStart);
  const endSec = parseFloat(canvas.dataset.waveEnd);
  if (isNaN(startSec) || isNaN(endSec) || endSec <= startSec) return;

  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  const relPos = (curTime - startSec) / (endSec - startSec);
  if (relPos < 0 || relPos > 1) return;

  const px = relPos * w;
  const ctx = canvas.getContext('2d');
  // dpr scale is already applied by drawLyricsPartWaveform
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

function updateLyricsPlayButtons() {
  document.querySelectorAll('[data-lyrics-play]').forEach(btn => {
    const partId = btn.dataset.lyricsPlay;
    const isPlaying = _lyricsPlayingPart === partId;
    const isPaused = _lyricsPausedPart === partId;
    btn.innerHTML = isPlaying ? '&#9646;&#9646;' : '&#9654;';
    btn.classList.toggle('playing', isPlaying);
    btn.classList.toggle('paused', isPaused);
    btn.title = isPlaying ? 'Pause' : isPaused ? 'Fortsetzen' : 'Part abspielen';
  });
}

/**
 * Copy lyrics bar-by-bar from one part to another.
 */
function copyLyricsFromPart(fromPartId, toPartId) {
  const db = getDB();
  if (!db || !db.songs || !selectedSongId) return;
  const song = db.songs[selectedSongId];
  if (!song || !song.parts) return;

  const fromPart = song.parts[fromPartId];
  const toPart = song.parts[toPartId];
  if (!fromPart || !toPart) return;

  const fromBars = fromPart.bars || 0;
  const toBars = toPart.bars || 0;
  const count = Math.min(fromBars, toBars);

  // Copy lyrics bar by bar
  for (let b = 1; b <= count; b++) {
    const srcBar = findBar(fromPartId, b);
    const srcLyrics = srcBar ? (srcBar[1].lyrics || '') : '';

    // Find or create target bar
    let tgtBar = findBar(toPartId, b);
    if (tgtBar) {
      tgtBar[1].lyrics = srcLyrics;
    } else {
      // Create bar entry in DB
      const barId = 'B' + Date.now().toString(36) + '_' + b;
      if (!db.bars) db.bars = {};
      db.bars[barId] = {
        part_id: toPartId,
        bar_num: b,
        lyrics: srcLyrics,
        audio: '',
        has_accents: false
      };
    }
  }

  // Update UI inputs directly
  document.querySelectorAll(`input[data-lyrics-bar-part="${toPartId}"]`).forEach(inp => {
    const barNum = parseInt(inp.dataset.lyricsBarNum, 10);
    if (barNum <= count) {
      const srcBar = findBar(fromPartId, barNum);
      inp.value = srcBar ? (srcBar[1].lyrics || '') : '';
    }
  });

  markDirty();
}

/* ── Lyrics Tab Event Handlers ────────────────────── */

function handleLyricsClick(e) {
  const el = e.target;

  // Distribute raw text to parts
  if (el.closest('#lyrics-distribute-btn')) {
    distributeLyricsToparts();
    return;
  }

  // Toggle-all collapse/expand
  if (el.closest('#lyrics-toggle-all')) {
    const parts = getSortedParts(selectedSongId);
    const nonInstr = parts.filter(p => !p.instrumental);
    const allCollapsed = nonInstr.every(p => _lyricsCollapsed.has(p.id));
    if (allCollapsed) {
      nonInstr.forEach(p => _lyricsCollapsed.delete(p.id));
    } else {
      nonInstr.forEach(p => _lyricsCollapsed.add(p.id));
    }
    const scrollEl = document.getElementById('lyrics-scroll');
    const savedScroll = scrollEl ? scrollEl.scrollTop : 0;
    renderLyricsTab();
    const scrollEl2 = document.getElementById('lyrics-scroll');
    if (scrollEl2) scrollEl2.scrollTop = savedScroll;
    return;
  }

  // Collapse/expand single part
  const collapseBtn = el.closest('[data-lyrics-collapse]');
  if (collapseBtn) {
    const partId = collapseBtn.dataset.lyricsCollapse;
    const card = collapseBtn.closest('.lyrics-part-card');
    const scrollEl = document.getElementById('lyrics-scroll');
    const cardTop = card ? card.getBoundingClientRect().top : 0;

    if (_lyricsCollapsed.has(partId)) {
      _lyricsCollapsed.delete(partId);
    } else {
      _lyricsCollapsed.add(partId);
    }

    const savedScroll = scrollEl ? scrollEl.scrollTop : 0;
    renderLyricsTab();
    const scrollEl2 = document.getElementById('lyrics-scroll');
    if (scrollEl2) {
      // Keep the clicked card at the same screen position
      const newCard = scrollEl2.querySelector(`.lyrics-part-card[data-part-id="${partId}"]`);
      if (newCard) {
        const newCardTop = newCard.getBoundingClientRect().top;
        scrollEl2.scrollTop += newCardTop - cardTop;
      } else {
        scrollEl2.scrollTop = savedScroll;
      }
    }
    return;
  }

  // Copy lyrics from previous same-name part
  const copyBtn = el.closest('[data-lyrics-copy-from]');
  if (copyBtn) {
    const fromPartId = copyBtn.dataset.lyricsCopyFrom;
    const toPartId = copyBtn.dataset.lyricsCopyTo;
    copyLyricsFromPart(fromPartId, toPartId);
    return;
  }

  // Part play button
  const playBtn = el.closest('[data-lyrics-play]');
  if (playBtn) {
    const partId = playBtn.dataset.lyricsPlay;
    const partIndex = parseInt(playBtn.dataset.partIndex, 10);
    handleLyricsPartPlay(partId, partIndex);
    return;
  }
}

/**
 * Save the raw lyrics textarea value into the current song object.
 * Called on song switch, tab switch, and periodically via change events.
 */
function saveLyricsRawText() {
  if (!selectedSongId) return;
  const song = db.songs[selectedSongId];
  if (!song) return;
  const rawEl = document.getElementById('lyrics-raw-text');
  if (!rawEl) return;
  const val = rawEl.value;
  if (val !== (song.lyrics_raw || '')) {
    song.lyrics_raw = val;
    markDirty();
  }
}

function handleLyricsChange(e) {
  const el = e.target;

  // Instrumental checkbox
  if (el.classList.contains('lyrics-instr-check')) {
    const partId = el.dataset.instrPart;
    if (!partId || !selectedSongId) return;
    const song = db.songs[selectedSongId];
    if (!song || !song.parts[partId]) return;
    song.parts[partId].instrumental = el.checked;
    markDirty();
    const card = el.closest('.lyrics-part-card');
    const scrollEl = document.getElementById('lyrics-scroll');
    const cardTop = card ? card.getBoundingClientRect().top : 0;
    renderLyricsTab();
    const scrollEl2 = document.getElementById('lyrics-scroll');
    if (scrollEl2 && card) {
      const newCard = scrollEl2.querySelector(`.lyrics-part-card[data-part-id="${partId}"]`);
      if (newCard) {
        scrollEl2.scrollTop += newCard.getBoundingClientRect().top - cardTop;
      }
    }
    return;
  }

  // Auto-save raw lyrics text on any change in the raw textarea
  if (el.id === 'lyrics-raw-text') {
    saveLyricsRawText();
    return;
  }
}

/* ── Lyrics Input Focus (iPad compact + auto-save) ── */

const _isIPad = /iPad|Macintosh/i.test(navigator.userAgent) && 'ontouchend' in document;

// Track visual viewport height via CSS custom property (iPad keyboard fix).
// When the keyboard opens, visualViewport.height shrinks. The panel uses
// height: var(--vv-h) so it never extends behind the keyboard → no black band.
let _vvCleanup = null;
function _startVisualViewportTracking() {
  if (_vvCleanup || !window.visualViewport) return;
  const update = () => {
    document.documentElement.style.setProperty('--vv-h', `${window.visualViewport.height}px`);
  };
  update();
  window.visualViewport.addEventListener('resize', update);
  window.visualViewport.addEventListener('scroll', update);
  _vvCleanup = () => {
    window.visualViewport.removeEventListener('resize', update);
    window.visualViewport.removeEventListener('scroll', update);
    document.documentElement.style.removeProperty('--vv-h');
    _vvCleanup = null;
  };
}

// Remember scroll position so we can restore it when leaving kbd mode
let _savedScrollY = 0;

function lyricsInputFocusIn(input) {
  if (_isIPad) {
    _savedScrollY = window.scrollY;
    _startVisualViewportTracking();
    const panel = document.querySelector('.lyrics-panel');
    if (panel) panel.classList.add('lyrics-kbd-mode');
    // Scroll the focused input into view inside the now-fixed panel
    const card = input.closest('.lyrics-part-card');
    if (card) {
      requestAnimationFrame(() => {
        card.scrollIntoView({ block: 'start', behavior: 'smooth' });
      });
    }
  }
}

function lyricsInputFocusOut(input) {
  // Save this bar's lyrics into DB immediately
  const partId = input.dataset.lyricsBarPart;
  const barNum = parseInt(input.dataset.lyricsBarNum, 10);
  if (partId && !isNaN(barNum)) {
    const [, barData] = getOrCreateBar(partId, barNum);
    const newText = input.value.trim();
    if (barData.lyrics !== newText) {
      barData.lyrics = newText;
      markDirty();
      handleSave(false); // silent save to GitHub
    }
  }

  // iPad: restore full layout (small delay to handle tab between inputs)
  if (_isIPad) {
    setTimeout(() => {
      const active = document.activeElement;
      if (!active || !active.classList.contains('lyrics-bar-input')) {
        const panel = document.querySelector('.lyrics-panel');
        if (panel) panel.classList.remove('lyrics-kbd-mode');
        if (_vvCleanup) _vvCleanup();
        // Restore original scroll position
        window.scrollTo(0, _savedScrollY);
      }
    }, 150);
  }
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
        <th class="ptt-dur">Dauer</th>
        <th class="ptt-tmpl">Light Template</th>
        <th class="ptt-notes">Notizen</th>
      </tr></thead>
      <tbody>
        ${parts.map((p, idx) => {
          const isActive = sel && sel.songId === p.songId && sel.partId === p.partId;
          const dur = calcPartDuration(p.bars || 0, p.bpm);
          const st = allStarts[p.songId]?.get(p.partId) || { startBar: 0, startSec: 0 };
          const audioBars = getAudioBarsForPart(p.partId);
          const hasAudio = audioBars.length > 0;
          const isPlaying = _partPlayActive && _playingPartId === p.partId;

          // Compute waveform time range from part markers (if available for this song)
          let waveCanvas = '';
          if (hasBuf && p.songId === selectedSongId) {
            const partIdx = getSortedParts(p.songId).findIndex(sp => sp.id === p.partId);
            const wStart = getPartStartTime(partIdx);
            const wEnd = getPartEndTime(partIdx);
            if (wStart !== null && wEnd !== null) {
              waveCanvas = `<canvas class="mini-waveform" data-wave-start="${wStart}" data-wave-end="${wEnd}" data-wave-color="rgb(0, 220, 130)"></canvas>`;
            }
          }

          return `<tr class="ptt-row${isActive ? ' active' : ''}" data-song-id="${p.songId}" data-part-id="${p.partId}">
            <td class="ptt-pos mono text-t3">${showSongCol ? idx + 1 : p.pos}</td>
            <td class="ptt-play">${hasAudio ? `<button class="btn-part-play${isPlaying ? ' playing' : ''}" data-action="play-part" data-part-id="${p.partId}" title="${isPlaying ? 'Stop' : 'Part abspielen'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>` : ''}</td>
            ${showSongCol ? `<td class="ptt-song"><span class="ptt-song-name">${esc(p.songName)}</span></td>` : ''}
            <td class="ptt-name"><input type="text" value="${esc(p.name)}" data-ptf="name" class="part-input"></td>
            ${hasBuf ? `<td class="ptt-wave">${waveCanvas}</td>` : ''}
            <td class="ptt-start">
              <div class="start-cell">
                <input type="number" value="${st.startBar}" data-ptf="start_bar" class="part-input-num mono" min="0" step="1" title="Takt-Offset ab Songstart">
                <span class="start-time mono text-t3">${fmtDur(Math.round(st.startSec))}</span>
              </div>
            </td>
            <td class="ptt-bars"><input type="number" value="${p.bars || 0}" data-ptf="bars" class="part-input-num mono" min="0" step="1"></td>
            <td class="ptt-dur"><input type="number" value="${dur}" data-ptf="duration_sec" class="part-input-num mono" min="0" step="1" title="Dauer in Sekunden"></td>
            <td class="ptt-tmpl">
              <select data-ptf="light_template" class="part-select">
                <option value="">\u2014</option>
                ${LIGHT_TEMPLATES.map(t => `<option value="${t}"${t === p.light_template ? ' selected' : ''}>${t}</option>`).join('')}
              </select>
            </td>
            <td class="ptt-notes"><input type="text" value="${esc(p.notes || '')}" data-ptf="notes" class="part-input ptt-notes-input" placeholder="\u2014"></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
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
    } else if (field === 'notes') {
      part.notes = el.value;
    } else if (field === 'name') {
      part.name = el.value;
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
      song.parts[newId] = { pos: newPos, name: 'New Part', bars: 0, duration_sec: 0, light_template: 'generic_bpm', notes: '' };
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

async function handleSave(showToast = true) {
  if (!db || !dirty) return true;
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
  try {
    const newSha = await saveDB(s.repo, s.path, s.token, db, dbSha);
    dbSha = newSha;
    dirty = false;
    setSyncStatus('saved');
    if (showToast) toast('Gespeichert', 'success');
    return true;
  } catch (e) {
    setSyncStatus('error');
    toast(`Speichern fehlgeschlagen: ${e.message}`, 'error', 5000);
    return false;
  }
}

function markDirty() {
  if (!dirty) {
    dirty = true;
    setSyncStatus('unsaved');
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
    else if (activeTab === 'setlist') handleSetlistClick(e);
  });
  els.content.addEventListener('change', (e) => {
    if (activeTab === 'parts') handlePartsTabChange(e);
    else if (activeTab === 'takte') handleTakteTabChange(e);
    else if (activeTab === 'lyrics') handleLyricsChange(e);
    else if (activeTab === 'setlist') handleSetlistChange(e);
  });
  // input events for lyrics raw textarea (change fires only on blur)
  els.content.addEventListener('input', (e) => {
    if (activeTab === 'lyrics' && e.target.id === 'lyrics-raw-text') {
      saveLyricsRawText();
    }
  });

  // Lyrics bar input: save individual bar on blur + iPad compact layout
  els.content.addEventListener('focusin', (e) => {
    if (activeTab === 'lyrics' && e.target.classList.contains('lyrics-bar-input')) {
      lyricsInputFocusIn(e.target);
    }
  });
  els.content.addEventListener('focusout', (e) => {
    if (activeTab === 'lyrics' && e.target.classList.contains('lyrics-bar-input')) {
      lyricsInputFocusOut(e.target);
    }
    if (activeTab === 'lyrics' && e.target.id === 'lyrics-raw-text') {
      saveLyricsRawText();
      handleSave(false);
    }
  });

  // Lyrics waveform bar marker drag (global move/end handlers)
  document.addEventListener('mousemove', moveLyricsWaveDrag);
  document.addEventListener('mouseup', endLyricsWaveDrag);
  document.addEventListener('touchmove', moveLyricsWaveDrag, { passive: false });
  document.addEventListener('touchend', endLyricsWaveDrag);

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
  restoreSidebar();
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
