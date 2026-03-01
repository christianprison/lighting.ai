/**
 * js/app.js — lighting.ai DB Editor
 *
 * Meilenstein 2: Vollstaendiger DB Editor mit Song-Detail, Parts-Tabelle,
 * Bar-Editor mit 16tel-Accent-Raster und Summary-Bar.
 */

import { loadDB, loadDBLocal, saveDB, testConnection, uploadFile } from './db.js';
import * as audio from './audio-engine.js';

/* ── State ─────────────────────────────────────────── */
let db = null;
let dbSha = null;
let dirty = false;
let readOnly = true;
let activeTab = 'editor';
let selectedSongId = null;
let selectedPartId = null;
let selectedBarNum = null;

/* ── Audio Split State ────────────────────────────── */
let audioMeta = null;          // {duration, sampleRate, channels}
let partMarkers = [];          // [{time, partIndex}] sorted
let barMarkers = [];           // [{time, partIndex}] sorted
let tapHistory = [];           // [{type:'part'|'bar', time, partIndex}] for undo
let currentPartIndex = 0;      // next part to be tapped
let currentBarInPart = 0;      // bar counter within current part
let animFrameId = null;        // requestAnimationFrame for playhead
let exportInProgress = false;

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
    tabAudio:      document.getElementById('tab-audio'),
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
  };
}

/* ── Sync Status ───────────────────────────────────── */

function setSyncStatus(status) {
  const labels = {
    saved: 'SAVED', unsaved: 'UNSAVED', saving: 'SAVING...',
    error: 'ERROR', loading: 'LOADING...',
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
  els.songList.innerHTML = filtered.map(s => `
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
  activeTab = tab;
  els.tabEditor.classList.toggle('active', tab === 'editor');
  els.tabAudio.classList.toggle('active', tab === 'audio');
  renderContent();
}

function renderContent() {
  if (!db) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9881;</div><p>DB wird geladen...</p></div>`;
    return;
  }
  if (activeTab === 'editor') renderEditorTab();
  else renderAudioTab();
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
    </div>`;
}

/* ── Parts Table ───────────────────────────────────── */

function renderPartsTable() {
  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  const area = document.getElementById('parts-area');
  if (!area) return;

  const hasSel = !!selectedPartId;

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
          <th class="pt-name">Name</th>
          <th class="pt-bars">Bars</th>
          <th class="pt-dur">Dauer</th>
          <th class="pt-tmpl">Light Template</th>
          <th class="pt-grip"></th>
        </tr>
      </thead>
      <tbody>
        ${parts.map(p => `
          <tr class="part-row${p.id === selectedPartId ? ' active' : ''}" data-part-id="${p.id}">
            <td class="pt-pos mono text-t3">${p.pos}</td>
            <td class="pt-name"><input type="text" value="${esc(p.name)}" data-part-field="name" class="part-input"></td>
            <td class="pt-bars"><input type="number" value="${p.bars || 0}" data-part-field="bars" class="part-input-num mono" min="0" step="1"></td>
            <td class="pt-dur mono text-t3 part-duration">${fmtDur(calcPartDuration(p.bars, song.bpm))}</td>
            <td class="pt-tmpl">
              <select data-part-field="light_template" class="part-select">
                <option value="">\u2014</option>
                ${LIGHT_TEMPLATES.map(t => `<option value="${t}"${t === p.light_template ? ' selected' : ''}>${t}</option>`).join('')}
              </select>
            </td>
            <td class="pt-grip text-t4">\u2807</td>
          </tr>
        `).join('')}
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
      <span class="summary-item"><span class="summary-label">Total Bars</span><span class="mono">${totalBars}</span></span>
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
      // Update duration cells in DOM without full re-render
      document.querySelectorAll('.part-duration').forEach(cell => {
        const pid = cell.closest('[data-part-id]')?.dataset.partId;
        if (pid && song.parts[pid]) {
          cell.textContent = fmtDur(calcPartDuration(song.parts[pid].bars || 0, song.bpm));
        }
      });
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
      // Update duration cell
      const row = el.closest('[data-part-id]');
      const durCell = row?.querySelector('.part-duration');
      if (durCell) durCell.textContent = fmtDur(part.duration_sec);
      recalcSongDuration();
      const durField = document.getElementById('song-duration-field');
      if (durField) durField.value = song.duration || '';
      renderSummary();
      // Re-render bar section if this part is selected
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
      markDirty();
      renderPartsTable();
      break;
    }

    case 'dup-part': {
      if (!selectedPartId || !song.parts[selectedPartId]) return;
      const src = song.parts[selectedPartId];
      // Shift positions of parts after current
      for (const p of Object.values(song.parts)) {
        if (p.pos > src.pos) p.pos += 1;
      }
      const newId = nextPartId(selectedSongId);
      song.parts[newId] = {
        pos: src.pos + 1, name: src.name + ' (Copy)', bars: src.bars,
        duration_sec: src.duration_sec, light_template: src.light_template, notes: src.notes || ''
      };
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

function renderAudioTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9836;</div><p>Song aus der Liste links ausw\u00e4hlen, um Audio zu splitten.</p></div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const parts = getSortedParts(selectedSongId);
  const hasBuf = !!audio.getBuffer();
  const isPlay = audio.isPlaying();

  els.content.innerHTML = `
    <div class="audio-panel">
      <div class="audio-scroll" id="audio-scroll">
        ${buildSongHeader(song)}
        ${buildDropZone()}
        ${hasBuf ? buildWaveform() : ''}
        ${hasBuf ? buildTransport() : ''}
        ${hasBuf ? buildTapButtons(parts, isPlay) : ''}
        ${hasBuf ? buildBpmBanner(song) : ''}
        ${hasBuf ? buildSplitResult(parts) : ''}
        ${hasBuf ? buildExportSection(parts) : ''}
      </div>
      ${hasBuf ? buildAudioSummary(parts) : ''}
    </div>`;

  if (hasBuf) {
    requestAnimationFrame(() => drawWaveform());
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

function buildDropZone() {
  if (audioMeta) {
    const durStr = fmtTime(audioMeta.duration);
    const sr = (audioMeta.sampleRate / 1000).toFixed(1);
    return `
      <div class="audio-dropzone has-file" id="audio-dropzone">
        <div class="dz-info">
          <span>${durStr}</span>
          <span>${sr} kHz</span>
          <span>${audioMeta.channels}ch</span>
        </div>
        <span class="dz-change">Klick zum Wechseln</span>
      </div>`;
  }
  return `
    <div class="audio-dropzone" id="audio-dropzone">
      <div class="dz-icon">&#127925;</div>
      <div class="dz-text">Audio-Datei hier ablegen oder klicken</div>
      <div class="dz-formats">.wav .mp3 .m4a .ogg</div>
    </div>`;
}

function buildWaveform() {
  return `<div class="waveform-wrap" id="waveform-wrap"><canvas id="waveform-canvas"></canvas></div>`;
}

function buildTransport() {
  const isPlay = audio.isPlaying();
  const cur = audio.getCurrentTime();
  const dur = audioMeta ? audioMeta.duration : 0;
  const pct = dur > 0 ? (cur / dur * 100) : 0;
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
    </div>`;
}

function buildTapButtons(parts, isPlay) {
  const nextPartName = currentPartIndex < parts.length ? parts[currentPartIndex].name : '\u2014';
  const allPartsDone = currentPartIndex >= parts.length;
  const barLabel = currentBarInPart > 0 ? `Bar ${currentBarInPart + 1}` : 'Bar 1';

  return `
    <div class="tap-row" id="tap-row">
      <button class="tap-btn tap-part" id="tap-part" ${!isPlay || allPartsDone ? 'disabled' : ''}>
        <span class="tap-label">PART TAP</span>
        <span class="tap-info">${esc(nextPartName)}</span>
      </button>
      <button class="tap-btn tap-bar" id="tap-bar" ${!isPlay || currentPartIndex === 0 ? 'disabled' : ''}>
        <span class="tap-label">BAR TAP</span>
        <span class="tap-info">${barLabel}</span>
      </button>
      <button class="tap-btn tap-undo" id="tap-undo" ${tapHistory.length === 0 ? 'disabled' : ''}>
        <span class="tap-label">UNDO</span>
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

    return `<tr class="${cls}">
      <td class="st-nr mono text-t3">${p.pos}</td>
      <td class="st-name">${esc(p.name)}</td>
      <td class="st-bars mono">${barCount || '\u2014'}</td>
      <td class="st-start mono text-t3">${start !== null ? fmtTime(start) : '\u2014'}</td>
      <td class="st-dur mono text-t3">${dur !== null ? fmtTime(dur) : '\u2014'}</td>
      <td class="st-check">${isDone ? '\u2713' : ''}</td>
    </tr>`;
  }).join('');

  return `
    <div class="split-result">
      <h3>Split-Ergebnis</h3>
      <table class="split-table">
        <thead><tr>
          <th class="st-nr">#</th>
          <th class="st-name">Name</th>
          <th class="st-bars">Bars</th>
          <th class="st-start">Start</th>
          <th class="st-dur">Dauer</th>
          <th class="st-check"></th>
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
        ${parts.length} Parts als WAV-Segmente nach <span class="mono">audio/${selectedSongId}/</span> hochladen.
      </div>
    </div>`;
}

function buildAudioSummary(parts) {
  const totalBars = barMarkers.length;
  const est = estimateBpm();
  return `
    <div class="summary-bar">
      <span class="summary-item"><span class="summary-label">Parts</span><span class="mono">${partMarkers.length}</span></span>
      <span class="summary-item"><span class="summary-label">Bars</span><span class="mono">${totalBars}</span></span>
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
  // If this is the last tapped part
  if (partIndex === currentPartIndex - 1 && audioMeta) return audioMeta.duration;
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
}

/* ── Waveform Drawing ──────────────────────────────── */

function drawWaveform() {
  const canvas = document.getElementById('waveform-canvas');
  if (!canvas) return;
  const wrap = document.getElementById('waveform-wrap');
  if (!wrap) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = wrap.getBoundingClientRect();
  const w = rect.width;
  const h = 120;

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

  // Draw waveform bars
  const buckets = Math.floor(w / 2); // 2px per bar
  const peaks = audio.getPeaks(buckets);
  const barW = w / buckets;
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

  // Bar markers (cyan)
  for (const m of barMarkers) {
    // Skip if also a part marker (to avoid double-draw)
    if (partMarkers.some(pm => pm.time === m.time)) continue;
    const x = (m.time / duration) * w;
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }

  // Part markers (amber)
  for (const m of partMarkers) {
    const x = (m.time / duration) * w;
    ctx.strokeStyle = 'rgba(240, 160, 48, 0.8)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();

    // Label
    const parts = getSortedParts(selectedSongId);
    const partName = m.partIndex < parts.length ? parts[m.partIndex].name : '';
    if (partName) {
      ctx.font = '10px Sora, sans-serif';
      ctx.fillStyle = 'rgba(240, 160, 48, 0.9)';
      const labelX = Math.min(x + 4, w - ctx.measureText(partName).width - 4);
      ctx.fillText(partName, labelX, 12);
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

/* ── Audio Split Event Handlers ────────────────────── */

function handleAudioFileLoad(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const meta = await audio.decodeAudio(e.target.result);
      audioMeta = meta;
      resetAudioSplit();
      renderAudioTab();
      toast(`Audio geladen: ${fmtTime(meta.duration)}`, 'success');
    } catch (err) {
      toast(`Audio-Fehler: ${err.message}`, 'error');
    }
  };
  reader.readAsArrayBuffer(file);
}

function handleWaveformClick(e) {
  if (!audioMeta) return;
  const wrap = document.getElementById('waveform-wrap');
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const pct = x / rect.width;
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

  // Also add a bar marker at the same position
  barMarkers.push({ time, partIndex: currentPartIndex });

  // Record for undo
  tapHistory.push({ type: 'part', time, partIndex: currentPartIndex });

  currentPartIndex++;
  currentBarInPart = 1; // First bar of new part already placed

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
  const activePartIdx = currentPartIndex - 1;

  barMarkers.push({ time, partIndex: activePartIdx });
  tapHistory.push({ type: 'bar', time, partIndex: activePartIdx });
  currentBarInPart++;

  drawWaveform();
  updateTapInfo(getSortedParts(selectedSongId));
  updateSplitResultLive(getSortedParts(selectedSongId));
  updateAudioSummaryLive(getSortedParts(selectedSongId));
}

function handleUndoTap() {
  if (tapHistory.length === 0) return;
  const last = tapHistory.pop();

  if (last.type === 'part') {
    // Remove the part marker
    partMarkers = partMarkers.filter(m => m.time !== last.time || m.partIndex !== last.partIndex);
    // Remove the bar marker placed with this part
    barMarkers = barMarkers.filter(m => m.time !== last.time || m.partIndex !== last.partIndex);
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
    currentBarInPart = Math.max(0, currentBarInPart - 1);
  }

  drawWaveform();
  const parts = getSortedParts(selectedSongId);
  updateTapInfo(parts);
  updateSplitResultLive(parts);
  updateAudioSummaryLive(parts);
  updateTapButtonStates();
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
    if (info) info.textContent = `Bar ${currentBarInPart + 1}`;
    barBtn.disabled = !audio.isPlaying() || currentPartIndex === 0;
  }

  const undoBtn = document.getElementById('tap-undo');
  if (undoBtn) undoBtn.disabled = tapHistory.length === 0;

  // Check if all parts done and show export
  if (currentPartIndex >= parts.length && !document.getElementById('export-section')) {
    renderAudioTab();
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
  const totalSegments = parts.length;
  let done = 0;

  try {
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const startTime = getPartStartTime(i);
      const endTime = getPartEndTime(i);

      if (startTime === null || endTime === null) continue;

      if (textEl()) textEl().textContent = `Exportiere ${part.name}... (${done + 1}/${totalSegments})`;

      const base64wav = await audio.exportSegmentWav(startTime, endTime);
      const path = `audio/${selectedSongId}/${part.id}/full.wav`;

      await uploadFile(s.repo, path, s.token, base64wav, `Audio: ${part.name} (${db.songs[selectedSongId].name})`);

      done++;
      const pct = (done / totalSegments * 100).toFixed(0);
      if (fillEl()) fillEl().style.width = pct + '%';
      if (textEl()) textEl().textContent = `${done}/${totalSegments} hochgeladen`;
    }

    toast(`${done} Audio-Segmente exportiert`, 'success');
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

  // Tap buttons
  if (el.closest('#tap-part') && !el.closest('#tap-part').disabled) { handlePartTap(); return; }
  if (el.closest('#tap-bar') && !el.closest('#tap-bar').disabled) { handleBarTap(); return; }
  if (el.closest('#tap-undo') && !el.closest('#tap-undo').disabled) { handleUndoTap(); return; }

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
  els.helpModal.classList.add('open');
}

function closeHelp() {
  els.helpModal.classList.remove('open');
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
      toast(`DB geladen (read/write) \u2014 ${Object.keys(db.songs || {}).length} Songs`, 'success');
    } catch (e) {
      setSyncStatus('error');
      toast(`GitHub API fehlgeschlagen: ${e.message}`, 'error', 3000);
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
    setSyncStatus('saved');
    toast(`DB geladen (read-only) \u2014 ${Object.keys(db.songs || {}).length} Songs`, 'info');
  } catch (e) {
    db = null;
    setSyncStatus('error');
    toast(`DB laden fehlgeschlagen: ${e.message}`, 'error', 5000);
  }
}

function updateSaveButton() {
  if (readOnly) {
    els.btnSave.title = 'Read-only \u2014 Token in Settings eingeben';
    els.btnSave.style.opacity = '0.4';
  } else {
    els.btnSave.title = 'Save (Ctrl+S)';
    els.btnSave.style.opacity = '1';
  }
}

/* ── Save DB ───────────────────────────────────────── */

async function handleSave() {
  if (!db || !dirty) return;
  if (readOnly) {
    toast('Read-only Modus \u2014 Token in Settings eingeben', 'error');
    return;
  }
  const s = getSettings();
  setSyncStatus('saving');
  try {
    const newSha = await saveDB(s.repo, s.path, s.token, db, dbSha);
    dbSha = newSha;
    dirty = false;
    setSyncStatus('saved');
    toast('Gespeichert', 'success');
  } catch (e) {
    setSyncStatus('error');
    toast(`Speichern fehlgeschlagen: ${e.message}`, 'error', 5000);
  }
}

function markDirty() {
  if (!dirty) {
    dirty = true;
    setSyncStatus('unsaved');
  }
}

/* ── Event Wiring ──────────────────────────────────── */

function wireEvents() {
  // Tabs
  els.tabEditor.addEventListener('click', () => switchTab('editor'));
  els.tabAudio.addEventListener('click',  () => switchTab('audio'));

  // Settings
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
    if (e.key === 'Escape') { closeSettings(); closeHelp(); }
    if (e.key === '?' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') openHelp();
  });

  // Search
  els.searchBox.addEventListener('input', () => renderSongList(els.searchBox.value));

  // Song selection
  els.songList.addEventListener('click', (e) => {
    const item = e.target.closest('.song-item');
    if (!item) return;
    const newId = item.dataset.id;
    if (newId === selectedSongId) return;
    // Stop audio and reset split state when switching songs
    audio.reset();
    audioMeta = null;
    resetAudioSplit();
    cancelAnimationFrame(animFrameId);
    selectedSongId = newId;
    selectedPartId = null;
    selectedBarNum = null;
    renderSongList(els.searchBox.value);
    renderContent();
  });

  // Editor event delegation
  els.content.addEventListener('change', handleEditorChange);
  els.content.addEventListener('click', (e) => {
    if (activeTab === 'editor') handleEditorClick(e);
    else if (activeTab === 'audio') handleAudioClick(e);
  });

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

  // Keyboard shortcuts for audio
  document.addEventListener('keydown', (e) => {
    if (activeTab !== 'audio' || !audio.getBuffer()) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.code === 'Space') {
      e.preventDefault();
      handlePlayPause();
    }
  });
}

/* ── Boot ──────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  wireEvents();
  switchTab('editor');
  initDB();
});
