/**
 * js/db.js — Persistence for lighting.ai
 *
 * DB (songs/bars/accents/setlist/meta): Supabase Postgres via PostgREST,
 * using the public anon/publishable key (Supabase-Cutover Option B — kein
 * Login, RLS erlaubt der anon-Rolle insert/update/delete auf genau den 5
 * Tabellen, die diese App besitzt; siehe docs/cutover-uebergabe.md und
 * supabase/migrations/0010_anon_write_access.sql). Der Key ist bewusst
 * öffentlich im Client-Bundle — das ist der akzeptierte Trade-off für ein
 * Hobbyprojekt ohne Login-UI.
 *
 * Audio-Binärdateien (MP3-Snippets, Referenz-Audio) bleiben unverändert auf
 * GitHub (Contents API) — das ist nicht Teil des Cutovers.
 */

const SUPABASE_URL = 'https://ivkcvvjtwwfommsnxerv.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_bS0KjYSEGa_CVEplXPC_ZA_gloEimqh';

const GITHUB_API = 'https://api.github.com';

/** SHA cache: path → sha (kept in sync after every read/write, GitHub audio only) */
const shaCache = {};

/** Snapshot of row-ids present in Supabase at last loadDB(), used to compute
 *  deletions on the next saveDB() (rows we knew about that vanished from the
 *  in-memory `db` are pruned; everything else is left alone). */
let _loadedIds = { songs: new Set(), bars: new Set(), accents: new Set() };

/* ═══════════════════ JSON ⇄ Zeilen-Mapping ═══════════════════════════════
 * Exakter JS-Port von scripts/central_db/transform.py — muss inhaltlich
 * identisch bleiben, sonst driften WebApp und Python-Skripte (Export/Verify)
 * auseinander. */

const CORE_FIELDS = [
  ['name', 'name'],
  ['artist', 'artist'],
  ['bpm', 'bpm'],
  ['key', 'music_key'],
  ['year', 'year'],
  ['pick', 'pick'],
  ['gema_nr', 'gema_nr'],
  ['duration', 'duration'],
  ['duration_sec', 'duration_sec'],
  ['notes', 'notes'],
];
const CORE_JSON_FIELDS = new Set(CORE_FIELDS.map(([jf]) => jf));

const BAR_PLAIN_FIELDS = ['song_id', 'bar_num', 'lyrics', 'audio', 'has_accents'];
const ACCENT_FIELDS = ['bar_id', 'pos_16th', 'type', 'notes'];

/**
 * Split the monolithic db object into Supabase table rows.
 * @param {object} db
 */
function dbJsonToRows(db) {
  const songsRows = [];
  const detailRows = [];
  for (const [sid, s] of Object.entries(db.songs || {})) {
    const row = { id: sid };
    for (const [jf, col] of CORE_FIELDS) row[col] = s[jf] ?? null;
    songsRows.push(row);
    const detail = {};
    for (const k of Object.keys(s)) {
      if (!CORE_JSON_FIELDS.has(k)) detail[k] = s[k];
    }
    detailRows.push({ song_id: sid, detail });
  }

  const barsRows = [];
  for (const [bid, b] of Object.entries(db.bars || {})) {
    const row = { bar_id: bid };
    for (const f of BAR_PLAIN_FIELDS) row[f] = b[f];
    row.lyrics = row.lyrics ?? '';
    row.audio = row.audio ?? '';
    row.has_accents = !!row.has_accents;
    row.instrumental = !!b.instrumental;
    barsRows.push(row);
  }

  const accentsRows = [];
  for (const [aid, a] of Object.entries(db.accents || {})) {
    const row = { accent_id: aid };
    for (const f of ACCENT_FIELDS) row[f] = a[f];
    row.notes = row.notes ?? '';
    accentsRows.push(row);
  }

  const appState = {
    id: 1,
    version: db.version ?? null,
    band: db.band ?? null,
    setlist: db.setlist ?? null,
    meta: db.meta ?? null,
  };

  return { songs: songsRows, song_detail_lighting: detailRows, bars: barsRows, accents: accentsRows, app_state: appState };
}

/**
 * Reassemble the monolithic db object from Supabase table rows.
 * @param {object} rows - {songs, song_detail_lighting, bars, accents, app_state}
 */
function rowsToDbJson(rows) {
  const app = rows.app_state;
  const db = {
    version: app.version,
    band: app.band,
    setlist: app.setlist,
    songs: {},
    bars: {},
    accents: {},
    meta: app.meta,
  };

  const detailById = {};
  for (const r of rows.song_detail_lighting) detailById[r.song_id] = r.detail || {};

  for (const srow of rows.songs) {
    const sid = srow.id;
    const s = {};
    for (const [jf, col] of CORE_FIELDS) s[jf] = srow[col];
    Object.assign(s, detailById[sid] || {});
    db.songs[sid] = s;
  }

  for (const brow of rows.bars) {
    const b = {};
    for (const f of BAR_PLAIN_FIELDS) b[f] = brow[f];
    if (brow.instrumental) b.instrumental = true;
    db.bars[brow.bar_id] = b;
  }

  for (const arow of rows.accents) {
    const a = {};
    for (const f of ACCENT_FIELDS) a[f] = arow[f];
    db.accents[arow.accent_id] = a;
  }

  return db;
}

/* ═══════════════════ Supabase REST (PostgREST) ═══════════════════════════ */

function sbHeaders(extra = {}) {
  return {
    apikey: SUPABASE_ANON_KEY,
    Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
    'Content-Type': 'application/json',
    ...extra,
  };
}

async function sbFetch(path, { method = 'GET', headers = {}, body } = {}) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method,
    headers: sbHeaders(headers),
    body,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(`Supabase ${method} ${path} ${res.status}: ${errBody.message || res.statusText}`);
  }
  return res;
}

const PAGE_SIZE = 1000; // PostgREST caps a single select() at 1000 rows

/** Fetch every row of a table, paginated, ordered by its PK for stable pages. */
async function fetchAllRows(table, orderCol) {
  let out = [];
  let offset = 0;
  for (;;) {
    const res = await sbFetch(`${table}?select=*&order=${orderCol}.asc&limit=${PAGE_SIZE}&offset=${offset}`);
    const chunk = await res.json();
    out = out.concat(chunk);
    if (chunk.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }
  return out;
}

const UPSERT_BATCH = 500;

/** Upsert rows into a table (insert-or-update on the table's primary key). */
async function upsertRows(table, rows) {
  if (!rows.length) return;
  for (let i = 0; i < rows.length; i += UPSERT_BATCH) {
    const chunk = rows.slice(i, i + UPSERT_BATCH);
    await sbFetch(table, {
      method: 'POST',
      headers: { Prefer: 'resolution=merge-duplicates,return=minimal' },
      body: JSON.stringify(chunk),
    });
  }
}

const DELETE_BATCH = 200; // keep the `in.(...)` filter URL a sane length

/** Delete rows by primary key from a table, batched. */
async function deleteRows(table, pkCol, ids) {
  for (let i = 0; i < ids.length; i += DELETE_BATCH) {
    const chunk = ids.slice(i, i + DELETE_BATCH);
    const list = chunk.map((id) => encodeURIComponent(id)).join(',');
    await sbFetch(`${table}?${pkCol}=in.(${list})`, { method: 'DELETE', headers: { Prefer: 'return=minimal' } });
  }
}

async function fetchAppState() {
  const rows = await sbFetch('app_state?select=*&id=eq.1').then((r) => r.json());
  if (!rows[0]) throw new Error('app_state Zeile (id=1) fehlt in Supabase');
  return rows[0];
}

/**
 * Load the full DB from Supabase and reassemble it into the same in-memory
 * shape the app has always used (the monolithic db object).
 * @returns {Promise<{data: object, sha: string}>} sha = app_state.updated_at,
 *   reused as the optimistic-lock token (replaces the old GitHub SHA).
 */
export async function loadDB() {
  const [songs, songDetail, bars, accents, appState] = await Promise.all([
    fetchAllRows('songs', 'id'),
    fetchAllRows('song_detail_lighting', 'song_id'),
    fetchAllRows('bars', 'bar_id'),
    fetchAllRows('accents', 'accent_id'),
    fetchAppState(),
  ]);

  const data = rowsToDbJson({ songs, song_detail_lighting: songDetail, bars, accents, app_state: appState });

  _loadedIds = {
    songs: new Set(songs.map((r) => r.id)),
    bars: new Set(bars.map((r) => r.bar_id)),
    accents: new Set(accents.map((r) => r.accent_id)),
  };

  return { data, sha: appState.updated_at };
}

/**
 * Save the full in-memory db object to Supabase: upsert everything (FK-safe
 * order), then prune rows that vanished since the last loadDB()/saveDB()
 * (only rows this tab actually knew about — never a blind "delete anything
 * not in the current set").
 *
 * Optimistic locking: before writing, re-check app_state.updated_at against
 * the `sha` token captured at load time. A mismatch means another tab/device
 * saved in the meantime — throws the same `isConflict` error shape the old
 * GitHub-SHA flow used, so the existing conflict-dialog UI keeps working.
 *
 * @param {object} data
 * @param {string} sha - updated_at token from the last loadDB()/saveDB()
 * @param {string} [_message] - unused (no commit messages in Supabase); kept
 *   for call-site compatibility with the old GitHub-based signature
 * @param {boolean} [force] - skip the conflict check and overwrite anyway
 * @returns {Promise<string>} new sha (updated_at) after the save
 */
export async function saveDB(data, sha, _message, force = false) {
  if (!force && sha) {
    const current = await fetchAppState();
    if (current.updated_at !== sha) {
      const latest = await loadDB();
      const err = new Error('Die Datenbank wurde zwischenzeitlich woanders gespeichert (anderer Tab/Gerät).');
      err.isConflict = true;
      err.latestSha = latest.sha;
      err.latestData = latest.data;
      throw err;
    }
  }

  const rows = dbJsonToRows(data);

  await upsertRows('songs', rows.songs);
  await upsertRows('song_detail_lighting', rows.song_detail_lighting);
  await upsertRows('bars', rows.bars);
  await upsertRows('accents', rows.accents);
  await upsertRows('app_state', [rows.app_state]);

  const currentSongIds = new Set(rows.songs.map((r) => r.id));
  const currentBarIds = new Set(rows.bars.map((r) => r.bar_id));
  const currentAccentIds = new Set(rows.accents.map((r) => r.accent_id));

  // Child tables first (accents → bars → songs) so FK cascades never race us.
  const deletedAccents = [..._loadedIds.accents].filter((id) => !currentAccentIds.has(id));
  const deletedBars = [..._loadedIds.bars].filter((id) => !currentBarIds.has(id));
  const deletedSongs = [..._loadedIds.songs].filter((id) => !currentSongIds.has(id));

  if (deletedAccents.length) await deleteRows('accents', 'accent_id', deletedAccents);
  if (deletedBars.length) await deleteRows('bars', 'bar_id', deletedBars);
  if (deletedSongs.length) await deleteRows('songs', 'id', deletedSongs); // song_detail_lighting cascades

  _loadedIds = { songs: currentSongIds, bars: currentBarIds, accents: currentAccentIds };

  const fresh = await fetchAppState();
  return fresh.updated_at;
}

/**
 * Quick reachability check for Supabase (used e.g. by a status indicator).
 * @returns {Promise<boolean>}
 */
export async function testSupabaseConnection() {
  try {
    await sbFetch('app_state?select=id&limit=1');
    return true;
  } catch {
    return false;
  }
}

/* ═══════════════════ GitHub (Audio-Blobs only) ═══════════════════════════
 * Unverändert — Audio-Snippets/Referenz-Audio bleiben auf GitHub, das ist
 * nicht Teil des Supabase-Cutovers. */

function headers(token) {
  return {
    'Authorization': `token ${token}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };
}

function utf8ToBase64(str) {
  return btoa(unescape(encodeURIComponent(str)));
}

/**
 * Upload a binary file (e.g. MP3) to GitHub as Base64.
 * Creates the file if it doesn't exist, updates if it does.
 *
 * @param {string} repo
 * @param {string} path   - e.g. "audio/5Ij0Ns/5Ij0Ns_P003/bar_001.mp3"
 * @param {string} token
 * @param {string} base64content - the file content already Base64-encoded
 * @param {string} [message]
 * @returns {Promise<string>} SHA of the committed file
 */
export async function uploadFile(repo, path, token, base64content, message) {
  const commitMsg = message || `Upload ${path} via lighting.ai`;

  // Check if file exists to get its SHA
  let existingSha = shaCache[path] || null;
  if (!existingSha) {
    try {
      const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
      const res = await fetch(url, { headers: headers(token) });
      if (res.ok) {
        const json = await res.json();
        existingSha = json.sha;
      }
    } catch {
      // file doesn't exist yet — that's fine
    }
  }

  const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
  const body = {
    message: commitMsg,
    content: base64content,
  };
  if (existingSha) {
    body.sha = existingSha;
  }

  const res = await fetch(url, {
    method: 'PUT',
    headers: headers(token),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(`GitHub PUT ${res.status}: ${errBody.message || res.statusText}`);
  }

  const json = await res.json();
  const newSha = json.content.sha;
  shaCache[path] = newSha;
  return newSha;
}

/**
 * Delete a file from a GitHub repo.
 *
 * @param {string} repo
 * @param {string} path
 * @param {string} token
 * @param {string} [message]
 * @returns {Promise<void>}
 */
export async function deleteFile(repo, path, token, message) {
  const commitMsg = message || `Delete ${path} via lighting.ai`;

  // Get SHA of existing file
  let sha = shaCache[path] || null;
  if (!sha) {
    const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
    const res = await fetch(url, { headers: headers(token) });
    if (!res.ok) return; // file doesn't exist — nothing to delete
    const json = await res.json();
    sha = json.sha;
  }

  const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
  const res = await fetch(url, {
    method: 'DELETE',
    headers: headers(token),
    body: JSON.stringify({ message: commitMsg, sha }),
  });

  if (!res.ok && res.status !== 404) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(`GitHub DELETE ${res.status}: ${errBody.message || res.statusText}`);
  }

  delete shaCache[path];
}

/**
 * Load DB via direct fetch (no token needed) — fallback for when Supabase is
 * unreachable. Works on GitHub Pages (same-origin) and local dev servers.
 * Returns data only — no sha (read-only mode).
 *
 * @param {string} path - relative path, e.g. "db/lighting-ai-db.json"
 * @returns {Promise<{data: object, sha: null}>}
 */
export async function loadDBLocal(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`Fetch ${res.status}: ${res.statusText}`);
  }
  const data = await res.json();
  return { data, sha: null };
}

/**
 * Test the GitHub connection by reading the repo root (used for the Audio
 * repo/token settings — has nothing to do with the DB, which lives in
 * Supabase now).
 *
 * @param {string} repo
 * @param {string} token
 * @returns {Promise<boolean>}
 */
export async function testConnection(repo, token) {
  const url = `${GITHUB_API}/repos/${repo}`;
  const res = await fetch(url, { headers: headers(token) });
  return res.ok;
}

/**
 * Get cached SHA for a GitHub path.
 * @param {string} path
 * @returns {string|null}
 */
export function getSha(path) {
  return shaCache[path] || null;
}
