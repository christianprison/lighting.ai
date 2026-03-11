/**
 * js/integrity.js — Data Integrity Module for lighting.ai
 *
 * Provides validation, orphan cleanup, cascade delete,
 * and bar-count synchronisation for the song database.
 *
 * All functions operate on the db object passed as first argument
 * and return mutation info so callers can decide on dirty-state.
 *
 * NOTE: Parts concept has been removed. Bars reference songs directly
 * via song_id. Markers are simple {time} objects.
 */

/* ── Helpers ──────────────────────────────────────── */

function ensureCollections(db) {
  if (!db.bars) db.bars = {};
  if (!db.accents) db.accents = {};
}

function nextId(prefix, collection) {
  const nums = Object.keys(collection)
    .map(k => parseInt(k.replace(prefix, ''), 10))
    .filter(n => !isNaN(n));
  const max = nums.length ? Math.max(...nums) : 0;
  return `${prefix}${String(max + 1).padStart(4, '0')}`;
}

/* ── Validation ───────────────────────────────────── */

/**
 * Validate all references in the database.
 * Returns { valid: boolean, errors: string[], orphanBars: string[], orphanAccents: string[] }
 */
export function validateDB(db) {
  const errors = [];
  const orphanBars = [];
  const orphanAccents = [];
  ensureCollections(db);

  // Collect all valid song IDs
  const allSongIds = new Set(Object.keys(db.songs || {}));

  // Check bars → songs
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (!bar.song_id || !allSongIds.has(bar.song_id)) {
      errors.push(`Bar ${barId} references non-existent song ${bar.song_id}`);
      orphanBars.push(barId);
    }
  }

  // Check accents → bars
  for (const [accId, acc] of Object.entries(db.accents)) {
    if (!acc.bar_id || !db.bars[acc.bar_id]) {
      errors.push(`Accent ${accId} references non-existent bar ${acc.bar_id}`);
      orphanAccents.push(accId);
    }
  }

  // Check setlist → songs
  if (db.setlist && Array.isArray(db.setlist.items)) {
    for (const item of db.setlist.items) {
      if (item.type === 'song' && item.song_id && !(db.songs || {})[item.song_id]) {
        errors.push(`Setlist references non-existent song ${item.song_id}`);
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    orphanBars,
    orphanAccents,
  };
}

/* ── Orphan Cleanup ───────────────────────────────── */

/**
 * Remove orphaned bars and accents from the database.
 * Returns { removedBars: string[], removedAccents: string[] }
 */
export function cleanupOrphans(db) {
  const result = validateDB(db);
  for (const barId of result.orphanBars) {
    delete db.bars[barId];
  }
  for (const accId of result.orphanAccents) {
    delete db.accents[accId];
  }
  return { removedBars: result.orphanBars, removedAccents: result.orphanAccents };
}

/* ── Cascade Delete ───────────────────────────────── */

/**
 * Delete a song and all its bars, accents, and setlist references.
 */
export function deleteSong(db, songId) {
  ensureCollections(db);
  const song = (db.songs || {})[songId];
  if (!song) return { deleted: false };

  const deletedBars = [];
  const deletedAccents = [];

  // Delete all bars and their accents for this song
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (bar.song_id === songId) {
      // Delete accents for this bar
      for (const [accId, acc] of Object.entries(db.accents)) {
        if (acc.bar_id === barId) {
          delete db.accents[accId];
          deletedAccents.push(accId);
        }
      }
      delete db.bars[barId];
      deletedBars.push(barId);
    }
  }

  // Remove from setlist
  if (db.setlist && Array.isArray(db.setlist.items)) {
    db.setlist.items = db.setlist.items.filter(
      item => !(item.type === 'song' && item.song_id === songId)
    );
  }

  delete db.songs[songId];
  return { deleted: true, deletedBars, deletedAccents };
}

/**
 * Delete a bar and all its accents.
 */
export function deleteBar(db, barId) {
  ensureCollections(db);
  const deletedAccents = [];
  for (const [accId, acc] of Object.entries(db.accents)) {
    if (acc.bar_id === barId) {
      delete db.accents[accId];
      deletedAccents.push(accId);
    }
  }
  delete db.bars[barId];
  return { deletedAccents };
}

/* ── Bar-Count Sync ───────────────────────────────── */

/**
 * Synchronise bars in db.bars with the declared song.total_bars count.
 * Removes excess bars (and their accents) when total_bars is reduced.
 * Returns { removed: string[] } — list of removed bar IDs.
 */
export function syncBarCount(db, songId, declaredCount) {
  ensureCollections(db);
  const removed = [];

  // Get all bars for this song, sorted by bar_num
  const barsForSong = Object.entries(db.bars)
    .filter(([, b]) => b.song_id === songId)
    .map(([id, b]) => ({ id, ...b }))
    .sort((a, b) => a.bar_num - b.bar_num);

  // Keep first declaredCount bars, remove the rest
  for (let i = declaredCount; i < barsForSong.length; i++) {
    deleteBar(db, barsForSong[i].id);
    removed.push(barsForSong[i].id);
  }

  return { removed };
}

/* ── Split-Marker Migration: Legacy → Unified ───── */

/**
 * Migrate split_markers from any old format to simple {time} markers.
 * Old formats had partId, partStart fields — these are stripped.
 */
export function migrateToUnifiedMarkers(db) {
  let migrated = 0;
  for (const [songId, song] of Object.entries(db.songs || {})) {
    if (!song.split_markers) continue;
    const sm = song.split_markers;

    // Already in new format (array of {time} only)?
    if (Array.isArray(sm.markers) && sm.markers.length > 0) {
      // Strip any legacy partId/partStart fields
      let hadLegacy = false;
      for (const m of sm.markers) {
        if (m.partId !== undefined || m.partStart !== undefined) {
          delete m.partId;
          delete m.partStart;
          hadLegacy = true;
        }
      }
      if (hadLegacy) migrated++;
      continue;
    }

    // Old two-array format
    if (Array.isArray(sm.partMarkers) || Array.isArray(sm.barMarkers)) {
      const unified = [];
      if (Array.isArray(sm.partMarkers)) {
        for (const m of sm.partMarkers) {
          unified.push({ time: m.time });
        }
      }
      if (Array.isArray(sm.barMarkers)) {
        for (const m of sm.barMarkers) {
          // Skip if a marker sits at the same time (within tolerance)
          const isDup = unified.some(u => Math.abs(u.time - m.time) < 0.01);
          if (!isDup) {
            unified.push({ time: m.time });
          }
        }
      }
      unified.sort((a, b) => a.time - b.time);
      song.split_markers = { markers: unified };
      migrated++;
    }
  }
  return { migrated };
}

/* ── Sync bars count from split_markers ───────────── */

/**
 * Ensure song.total_bars matches the number of markers.
 * split_markers.markers is the source of truth when present.
 * Returns the number of songs that were fixed.
 */
export function syncBarsFromMarkers(db) {
  let fixed = 0;
  for (const [, song] of Object.entries(db.songs || {})) {
    const sm = song.split_markers;
    if (!sm || !Array.isArray(sm.markers) || sm.markers.length === 0) continue;

    const count = sm.markers.length;
    if (song.total_bars !== count) {
      console.log(`[integrity] Fixed total_bars: ${song.name}: ${song.total_bars} → ${count}`);
      song.total_bars = count;
      fixed++;
    }
  }
  return fixed;
}

/* ── Run All Checks on Load ───────────────────────── */

/**
 * Run validation and optional cleanup when loading the database.
 * Logs issues to console and optionally cleans up orphans.
 * Returns the validation result.
 */
export function checkOnLoad(db, autoClean = false) {
  const result = validateDB(db);
  if (!result.valid) {
    console.warn('[integrity] DB validation issues found:', result.errors);
    if (autoClean) {
      const cleaned = cleanupOrphans(db);
      console.log('[integrity] Cleaned up:', cleaned);
    }
  }

  // Migrate split markers to unified format
  const migration = migrateToUnifiedMarkers(db);
  if (migration.migrated > 0) {
    console.log(`[integrity] Migrated ${migration.migrated} song(s) to unified markers`);
  }

  // Sync bars count from split_markers (source of truth)
  const barsFixed = syncBarsFromMarkers(db);
  if (barsFixed > 0) {
    console.log(`[integrity] Fixed bars count for ${barsFixed} song(s) from split_markers`);
    result.valid = false; // trigger dirty flag so changes get saved
  }

  return result;
}
