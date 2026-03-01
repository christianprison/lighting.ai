/**
 * js/app.js — Main application logic for lighting.ai
 *
 * Responsibilities:
 * - Settings management (localStorage)
 * - DB loading from GitHub on startup
 * - Tab routing (DB Editor / Audio Split)
 * - Sync status display
 * - Ctrl+S / Cmd+S save shortcut
 * - Song list rendering & filtering
 */

import { loadDB, loadDBLocal, saveDB, getSha, testConnection } from './db.js';

/* ── State ─────────────────────────────────────────── */
let db = null;          // the full DB object
let dbSha = null;       // current SHA from GitHub
let dirty = false;      // unsaved local changes?
let readOnly = true;    // no token → read-only mode
let activeTab = 'editor';
let selectedSongId = null;

const SETTINGS_KEY = 'lightingai_settings';

/* ── Settings ──────────────────────────────────────── */

function getSettings() {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {};
  } catch {
    return {};
  }
}

function saveSettings(s) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

function hasSettings() {
  const s = getSettings();
  return !!(s.repo && s.token && s.path);
}

/* ── DOM refs (set after DOMContentLoaded) ─────────── */
let els = {};

function cacheDom() {
  els = {
    // Header
    syncStatus:    document.getElementById('sync-status'),
    tabEditor:     document.getElementById('tab-editor'),
    tabAudio:      document.getElementById('tab-audio'),
    btnSettings:   document.getElementById('btn-settings'),
    btnSave:       document.getElementById('btn-save'),

    // Sidebar
    searchBox:     document.getElementById('search-box'),
    songCount:     document.getElementById('song-count'),
    songList:      document.getElementById('song-list'),

    // Content
    content:       document.getElementById('content'),

    // Settings modal
    modalOverlay:  document.getElementById('settings-modal'),
    inputRepo:     document.getElementById('set-repo'),
    inputToken:    document.getElementById('set-token'),
    inputPath:     document.getElementById('set-path'),
    btnTest:       document.getElementById('btn-test-conn'),
    testResult:    document.getElementById('test-result'),
    btnSaveSettings: document.getElementById('btn-save-settings'),
    btnCancelSettings: document.getElementById('btn-cancel-settings'),

    // Toast container
    toastContainer: document.getElementById('toast-container'),
  };
}

/* ── Sync Status ───────────────────────────────────── */

/** @param {'saved'|'unsaved'|'saving'|'error'|'loading'} status */
function setSyncStatus(status) {
  const labels = {
    saved: 'SAVED', unsaved: 'UNSAVED', saving: 'SAVING...',
    error: 'ERROR', loading: 'LOADING...',
  };
  els.syncStatus.dataset.status = status;
  els.syncStatus.textContent = labels[status] || status;
}

/* ── Toast Notifications ───────────────────────────── */

function toast(msg, type = 'info', duration = 3000) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  els.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
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
    ? songs.filter(s =>
        s.name.toLowerCase().includes(q) ||
        s.artist.toLowerCase().includes(q))
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

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
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
    els.content.innerHTML = `
      <div class="empty-state">
        <div class="icon">&#9881;</div>
        <p>DB wird geladen...</p>
      </div>`;
    return;
  }

  if (activeTab === 'editor') {
    renderEditorTab();
  } else {
    renderAudioTab();
  }
}

function renderEditorTab() {
  if (!selectedSongId || !db.songs[selectedSongId]) {
    els.content.innerHTML = `
      <div class="empty-state">
        <div class="icon">&#9835;</div>
        <p>Song aus der Liste links auswaehlen, um Details zu sehen.</p>
      </div>`;
    return;
  }

  const song = db.songs[selectedSongId];
  const parts = song.parts ? Object.entries(song.parts)
    .map(([id, p]) => ({ id, ...p }))
    .sort((a, b) => a.pos - b.pos) : [];

  els.content.innerHTML = `
    <div style="max-width: 800px">
      <h2 style="margin-bottom: 16px">${esc(song.name)} <span class="text-t3" style="font-weight:400;font-size:0.9rem">— ${esc(song.artist)}</span></h2>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px">
        <div class="form-group"><label>BPM</label><input type="number" value="${song.bpm || ''}" class="mono" style="width:100%" data-field="bpm"></div>
        <div class="form-group"><label>Key</label><input type="text" value="${esc(song.key || '')}" style="width:100%" data-field="key"></div>
        <div class="form-group"><label>Year</label><input type="text" value="${esc(song.year || '')}" style="width:100%" data-field="year"></div>
        <div class="form-group"><label>Duration</label><input type="text" value="${esc(song.duration || '')}" style="width:100%" data-field="duration" readonly class="mono text-t3"></div>
        <div class="form-group"><label>GEMA Nr.</label><input type="text" value="${esc(song.gema_nr || '')}" style="width:100%" data-field="gema_nr" class="mono"></div>
        <div class="form-group"><label>Pick</label><input type="text" value="${esc(song.pick || '')}" style="width:100%" data-field="pick"></div>
      </div>

      <h3 style="margin-bottom: 8px">Parts <span class="text-t3" style="font-weight:400">(${parts.length})</span></h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
        <thead>
          <tr style="text-align:left;color:var(--t3);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em">
            <th style="padding:6px 8px;border-bottom:1px solid var(--border)">#</th>
            <th style="padding:6px 8px;border-bottom:1px solid var(--border)">Name</th>
            <th style="padding:6px 8px;border-bottom:1px solid var(--border)">Bars</th>
            <th style="padding:6px 8px;border-bottom:1px solid var(--border)">Template</th>
          </tr>
        </thead>
        <tbody>
          ${parts.map(p => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:8px;font-family:var(--font-mono);color:var(--t3);font-size:0.8rem">${p.pos}</td>
              <td style="padding:8px;font-weight:500">${esc(p.name)}</td>
              <td style="padding:8px;font-family:var(--font-mono)">${p.bars || '—'}</td>
              <td style="padding:8px;font-family:var(--font-mono);color:var(--cyan);font-size:0.8rem">${esc(p.light_template || '')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>

      ${song.notes ? `<div style="margin-top:12px"><label>Notes</label><div style="color:var(--t2);font-size:0.85rem;white-space:pre-wrap">${esc(song.notes)}</div></div>` : ''}
    </div>`;
}

function renderAudioTab() {
  els.content.innerHTML = `
    <div class="empty-state">
      <div class="icon">&#9836;</div>
      <p>Audio Split wird in Meilenstein 3 implementiert.</p>
    </div>`;
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
    if (ok) {
      els.testResult.textContent = 'Connection OK';
      els.testResult.style.color = 'var(--green)';
    } else {
      els.testResult.textContent = 'Failed — check token/repo';
      els.testResult.style.color = 'var(--red)';
    }
  } catch (e) {
    els.testResult.textContent = `Error: ${e.message}`;
    els.testResult.style.color = 'var(--red)';
  }
}

function handleSaveSettings() {
  const repo  = els.inputRepo.value.trim();
  const token = els.inputToken.value.trim();
  const path  = els.inputPath.value.trim();

  if (!path) {
    toast('DB-Pfad muss ausgefuellt sein.', 'error');
    return;
  }

  saveSettings({ repo, token, path });
  closeSettings();
  toast(token ? 'Settings gespeichert (read/write)' : 'Settings gespeichert (read-only)', 'success');
  initDB();
}

/* ── DB Init ───────────────────────────────────────── */

async function initDB() {
  const s = getSettings();
  setSyncStatus('loading');

  // Strategy: If token is set, load via GitHub API (read+write).
  // Otherwise, load the local file directly (read-only, works on GitHub Pages).
  if (s.repo && s.token && s.path) {
    try {
      const result = await loadDB(s.repo, s.path, s.token);
      db = result.data;
      dbSha = result.sha;
      dirty = false;
      readOnly = false;
      setSyncStatus('saved');
      toast(`DB geladen (read/write) — ${Object.keys(db.songs || {}).length} Songs`, 'success');
    } catch (e) {
      setSyncStatus('error');
      toast(`GitHub API fehlgeschlagen: ${e.message}. Lade lokal...`, 'error', 3000);
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
    toast(`DB geladen (read-only) — ${Object.keys(db.songs || {}).length} Songs`, 'info');
  } catch (e) {
    db = null;
    setSyncStatus('error');
    toast(`DB laden fehlgeschlagen: ${e.message}`, 'error', 5000);
  }
}

function updateSaveButton() {
  if (readOnly) {
    els.btnSave.title = 'Read-only — Token in Settings eingeben zum Speichern';
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
    toast('Read-only Modus — Token in Settings eingeben zum Speichern', 'error');
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

  // Close modal on overlay click
  els.modalOverlay.addEventListener('click', (e) => {
    if (e.target === els.modalOverlay) closeSettings();
  });

  // Save button
  els.btnSave.addEventListener('click', handleSave);

  // Ctrl+S / Cmd+S
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      handleSave();
    }
    // Escape closes modal
    if (e.key === 'Escape') closeSettings();
  });

  // Search
  els.searchBox.addEventListener('input', () => {
    renderSongList(els.searchBox.value);
  });

  // Song selection (event delegation)
  els.songList.addEventListener('click', (e) => {
    const item = e.target.closest('.song-item');
    if (!item) return;
    selectedSongId = item.dataset.id;
    renderSongList(els.searchBox.value);
    renderContent();
  });
}

/* ── Boot ──────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  wireEvents();
  switchTab('editor');
  // Always load DB on start — works without token (read-only via local fetch)
  initDB();
});

/* Expose for inline onclick in rendered HTML */
window.markDirty = markDirty;
