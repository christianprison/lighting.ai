/**
 * js/db.js — Persistence for lighting.ai
 *
 * DB (songs/bars/accents/setlist/meta) UND Audio (Snippets, Referenz-Audio):
 * beides Supabase, über PostgREST bzw. die Storage-API, mit dem öffentlichen
 * anon/publishable Key (Supabase-Cutover Option B — kein Login, RLS erlaubt
 * der anon-Rolle insert/update/delete auf den 5 Katalog-Tabellen UND auf den
 * Storage-Bucket `snippets` + `audio_assets`; siehe docs/cutover-uebergabe.md,
 * supabase/migrations/0010_anon_write_access.sql und
 * supabase/migrations/0011_anon_storage_write.sql). Der Key ist bewusst
 * öffentlich im Client-Bundle — akzeptierter Trade-off für ein Hobbyprojekt
 * ohne Login-UI.
 *
 * Audio lief bis 2026-08-02 noch über GitHub — umgestellt, nachdem ein
 * typografischer Apostroph in einem Dateipfad zeigte, dass zwei verschiedene
 * Zustellwege für dieselbe Datei (GitHub Pages vs. Supabase Storage) sich
 * unterschiedlich verhalten können (GitHub tolerant, Storage lehnt ungültige
 * Object-Keys ab). Seitdem ein einziger Weg für Lesen UND Schreiben.
 * Der bestehende Git-`audio/`-Ordner bleibt vorerst als Backup/Fallback
 * bestehen (siehe `fetchAudioUrl` in js/app.js), wird aber nicht mehr aktiv
 * beschrieben.
 *
 * Nur die QXW-Datei (Lichtshow-Konfiguration) und Ad-hoc-GitHub-Zugriffe
 * (Test Connection in den Settings) nutzen noch die GitHub Contents API.
 */

const SUPABASE_URL = 'https://ivkcvvjtwwfommsnxerv.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_bS0KjYSEGa_CVEplXPC_ZA_gloEimqh';
const STORAGE_BUCKET = 'snippets';

const GITHUB_API = 'https://api.github.com';

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
  ['band_id', 'band_id'],
];
const CORE_JSON_FIELDS = new Set(CORE_FIELDS.map(([jf]) => jf));

const BAR_PLAIN_FIELDS = ['song_id', 'bar_num', 'lyrics', 'audio', 'has_accents'];
const ACCENT_FIELDS = ['bar_id', 'pos_16th', 'type', 'notes'];

/**
 * Split the monolithic db object into Supabase table rows.
 * @param {object} db
 * @param {string} bandId - app_state ist seit der Multi-Band-Migration
 *   (0012) eine Zeile PRO Band statt eines globalen Singletons.
 */
function dbJsonToRows(db, bandId) {
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
    band_id: bandId,
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
    band_id: app.band_id,
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

/**
 * Fetch every row of a table (optionally filtered), paginated, ordered by
 * its PK for stable pages.
 * @param {string} table
 * @param {string} orderCol
 * @param {string} [filter] - extra PostgREST query filter, e.g. "band_id=eq.the_pact"
 */
async function fetchAllRows(table, orderCol, filter = '') {
  let out = [];
  let offset = 0;
  const extra = filter ? `&${filter}` : '';
  for (;;) {
    const res = await sbFetch(`${table}?select=*${extra}&order=${orderCol}.asc&limit=${PAGE_SIZE}&offset=${offset}`);
    const chunk = await res.json();
    out = out.concat(chunk);
    if (chunk.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }
  return out;
}

const IN_BATCH = 200; // keep `in.(...)` filter URLs a sane length

/** Fetch rows of a table whose `idCol` is one of `ids`, batched for URL-length safety. */
async function fetchRowsByIds(table, idCol, ids) {
  if (!ids.length) return [];
  let out = [];
  for (let i = 0; i < ids.length; i += IN_BATCH) {
    const chunk = ids.slice(i, i + IN_BATCH);
    const list = chunk.map((id) => encodeURIComponent(id)).join(',');
    const res = await sbFetch(`${table}?select=*&${idCol}=in.(${list})`);
    out = out.concat(await res.json());
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

async function fetchAppState(bandId) {
  const rows = await sbFetch(`app_state?select=*&band_id=eq.${encodeURIComponent(bandId)}`).then((r) => r.json());
  if (!rows[0]) throw new Error(`app_state Zeile für Band "${bandId}" fehlt in Supabase`);
  return rows[0];
}

/**
 * List all bands (id + name), for the band switcher UI.
 * @returns {Promise<Array<{id: string, name: string}>>}
 */
export async function loadBands() {
  const res = await sbFetch('bands?select=id,name&order=name.asc');
  return res.json();
}

/**
 * Load one band's DB from Supabase and reassemble it into the same in-memory
 * shape the app has always used (the monolithic db object).
 *
 * `songs` is filtered server-side by band_id (the table that matters —
 * multiple bands' catalogs could grow large). `bars` is filtered server-side
 * via the resulting song-id list (also potentially large, thousands of rows
 * per band). `song_detail_lighting`/`accents` stay small in absolute terms
 * regardless of band count (song_detail_lighting = 1 row/song, accents are
 * far fewer than bars) — fetched in full and filtered client-side, which
 * avoids a second-hop `in.(...)` filter (accents don't carry song_id
 * directly, only bar_id) blowing past sane URL lengths.
 *
 * @param {string} bandId
 * @returns {Promise<{data: object, sha: string}>} sha = app_state.updated_at,
 *   reused as the optimistic-lock token (replaces the old GitHub SHA).
 */
export async function loadDB(bandId) {
  const [songs, songDetailAll, appState] = await Promise.all([
    fetchAllRows('songs', 'id', `band_id=eq.${encodeURIComponent(bandId)}`),
    fetchAllRows('song_detail_lighting', 'song_id'),
    fetchAppState(bandId),
  ]);

  const songIds = new Set(songs.map((r) => r.id));
  const songDetail = songDetailAll.filter((r) => songIds.has(r.song_id));

  const bars = await fetchRowsByIds('bars', 'song_id', [...songIds]);
  const barIds = new Set(bars.map((r) => r.bar_id));

  const accentsAll = await fetchAllRows('accents', 'accent_id');
  const accents = accentsAll.filter((r) => barIds.has(r.bar_id));

  const data = rowsToDbJson({ songs, song_detail_lighting: songDetail, bars, accents, app_state: appState });

  _loadedIds = {
    songs: songIds,
    bars: barIds,
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
 * @param {string} bandId - welche app_state-Zeile (Band) gespeichert wird
 * @param {boolean} [force] - skip the conflict check and overwrite anyway
 * @returns {Promise<string>} new sha (updated_at) after the save
 */
export async function saveDB(data, sha, bandId, force = false) {
  if (!force && sha) {
    const current = await fetchAppState(bandId);
    if (current.updated_at !== sha) {
      const latest = await loadDB(bandId);
      const err = new Error('Die Datenbank wurde zwischenzeitlich woanders gespeichert (anderer Tab/Gerät).');
      err.isConflict = true;
      err.latestSha = latest.sha;
      err.latestData = latest.data;
      throw err;
    }
  }

  const rows = dbJsonToRows(data, bandId);

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

  const fresh = await fetchAppState(bandId);
  return fresh.updated_at;
}

/**
 * Quick reachability check for Supabase (used e.g. by a status indicator).
 * @returns {Promise<boolean>}
 */
export async function testSupabaseConnection() {
  try {
    await sbFetch('app_state?select=band_id&limit=1');
    return true;
  } catch {
    return false;
  }
}

/* ═══════════════════ Supabase Storage (Audio) ═════════════════════════════
 * Bucket `snippets` ist public (Lesen ohne Auth über die /object/public/-URL).
 * Schreiben (Upload/Overwrite) erfordert trotzdem den anon-Key + RLS-Policy
 * auf storage.objects (supabase/migrations/0011_anon_storage_write.sql). */

/**
 * Build the public URL for a file in the Storage bucket (no auth needed to read).
 * @param {string} path - key inside the bucket, e.g. "audio/Foo/Foo - Full Song.mp3"
 * @returns {string}
 */
export function storagePublicUrl(path) {
  const encodedPath = path.split('/').map(encodeURIComponent).join('/');
  return `${SUPABASE_URL}/storage/v1/object/public/${STORAGE_BUCKET}/${encodedPath}`;
}

/**
 * Upload a file (base64-encoded) to the Storage bucket, overwriting any
 * existing object at the same key (upsert).
 *
 * @param {string} path - key inside the bucket
 * @param {string} base64 - file content, base64-encoded
 * @param {string} [contentType]
 * @returns {Promise<void>}
 */
export async function uploadToStorage(path, base64, contentType = 'audio/mpeg') {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  const encodedPath = path.split('/').map(encodeURIComponent).join('/');
  const res = await fetch(`${SUPABASE_URL}/storage/v1/object/${STORAGE_BUCKET}/${encodedPath}`, {
    method: 'POST',
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      'Content-Type': contentType,
      'x-upsert': 'true',
    },
    body: bytes,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(`Supabase Storage Upload ${res.status}: ${errBody.message || res.statusText}`);
  }
}

/**
 * Upsert an audio_assets row (registers/updates metadata for an uploaded file).
 * Conflict target matches the table's unique(bucket, storage_path) constraint.
 *
 * @param {{song_id: string, kind: 'playalong'|'snippet', storage_path: string,
 *          bar_num: number|null, part_id: string|null}} asset
 * @returns {Promise<void>}
 */
export async function registerAudioAsset(asset) {
  await sbFetch('audio_assets?on_conflict=bucket,storage_path', {
    method: 'POST',
    headers: { Prefer: 'resolution=merge-duplicates,return=minimal' },
    body: JSON.stringify([{ bucket: STORAGE_BUCKET, ...asset }]),
  });
}

/* ═══════════════════ GitHub (QXW-Datei, Ad-hoc-Zugriffe) ══════════════════
 * Nur noch für die QXW-Lichtshow-Datei und "Test Connection" in den
 * Settings — Audio läuft seit 2026-08-02 über Supabase Storage (s.o.). */

function headers(token) {
  return {
    'Authorization': `token ${token}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };
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
 * Test the GitHub connection by reading the repo root (used for the QXW-Datei
 * repo/token settings — has nothing to do with DB or Audio, die beide über
 * Supabase laufen).
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
