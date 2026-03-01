/**
 * js/app.js — lighting.ai DB Editor
 *
 * Meilenstein 2: Vollstaendiger DB Editor mit Song-Detail, Parts-Tabelle,
 * Bar-Editor mit 16tel-Accent-Raster und Summary-Bar.
 */

import { loadDB, loadDBLocal, saveDB, testConnection } from './db.js';

/* ── State ─────────────────────────────────────────── */
let db = null;
let dbSha = null;
let dirty = false;
let readOnly = true;
let activeTab = 'editor';
let selectedSongId = null;
let selectedPartId = null;
let selectedBarNum = null;

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

/* ── Audio Tab (placeholder) ───────────────────────── */

function renderAudioTab() {
  els.content.innerHTML = `<div class="empty-state"><div class="icon">&#9836;</div><p>Audio Split wird in Meilenstein 3 implementiert.</p></div>`;
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

  // Save
  els.btnSave.addEventListener('click', handleSave);
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); handleSave(); }
    if (e.key === 'Escape') closeSettings();
  });

  // Search
  els.searchBox.addEventListener('input', () => renderSongList(els.searchBox.value));

  // Song selection
  els.songList.addEventListener('click', (e) => {
    const item = e.target.closest('.song-item');
    if (!item) return;
    const newId = item.dataset.id;
    if (newId === selectedSongId) return;
    selectedSongId = newId;
    selectedPartId = null;
    selectedBarNum = null;
    renderSongList(els.searchBox.value);
    renderContent();
  });

  // Editor event delegation
  els.content.addEventListener('change', handleEditorChange);
  els.content.addEventListener('click', handleEditorClick);
}

/* ── Boot ──────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  wireEvents();
  switchTab('editor');
  initDB();
});
