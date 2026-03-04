/**
 * js/integrity.js — Data Integrity Module for lighting.ai
 *
 * Provides validation, orphan cleanup, cascade delete/duplicate,
 * and bar-count synchronisation for the song database.
 *
 * All functions operate on the db object passed as first argument
 * and return mutation info so callers can decide on dirty-state.
 */

/* ── Helpers ──────────────────────────────────────── */

function ensureCollections(db) {
  if (!db.bars) db.bars = {};
  if (!db.accents) db.accents = {};
}

function sortedParts(song) {
  if (!song || !song.parts) return [];
  return Object.entries(song.parts)
    .map(([id, p]) => ({ id, ...p }))
    .sort((a, b) => a.pos - b.pos);
}

function nextId(prefix, collection) {
  const nums = Object.keys(collection)
    .map(k => parseInt(k.replace(prefix, ''), 10))
    .filter(n => !isNaN(n));
  const max = nums.length ? Math.max(...nums) : 0;
  return `${prefix}${String(max + 1).padStart(4, '0')}`;
}

function nextPartId(songId, song) {
  if (!song.parts) song.parts = {};
  const nums = Object.keys(song.parts).map(k => {
    const m = k.match(/_P(\d+)$/);
    return m ? parseInt(m[1], 10) : 0;
  });
  const max = nums.length ? Math.max(...nums) : 0;
  return `${songId}_P${String(max + 1).padStart(3, '0')}`;
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

  // Collect all valid part IDs
  const allPartIds = new Set();
  for (const [songId, song] of Object.entries(db.songs || {})) {
    if (song.parts) {
      for (const partId of Object.keys(song.parts)) {
        allPartIds.add(partId);
      }
    }
  }

  // Check bars → parts
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (!bar.part_id || !allPartIds.has(bar.part_id)) {
      errors.push(`Bar ${barId} references non-existent part ${bar.part_id}`);
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
 * Delete a song and all its parts, bars, accents, and setlist references.
 */
export function deleteSong(db, songId) {
  ensureCollections(db);
  const song = (db.songs || {})[songId];
  if (!song) return { deleted: false };

  const deletedParts = [];
  const deletedBars = [];
  const deletedAccents = [];

  // Delete all parts (and their bars/accents)
  if (song.parts) {
    for (const partId of Object.keys(song.parts)) {
      const r = deletePart(db, songId, partId);
      deletedParts.push(partId);
      deletedBars.push(...r.deletedBars);
      deletedAccents.push(...r.deletedAccents);
    }
  }

  // Remove from setlist
  if (db.setlist && Array.isArray(db.setlist.items)) {
    db.setlist.items = db.setlist.items.filter(
      item => !(item.type === 'song' && item.song_id === songId)
    );
  }

  delete db.songs[songId];
  return { deleted: true, deletedParts, deletedBars, deletedAccents };
}

/**
 * Delete a part and all its bars and accents.
 */
export function deletePart(db, songId, partId) {
  ensureCollections(db);
  const song = (db.songs || {})[songId];
  const deletedBars = [];
  const deletedAccents = [];

  // Delete bars and their accents
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (bar.part_id === partId) {
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

  if (song && song.parts) {
    delete song.parts[partId];
    // Renumber remaining parts
    sortedParts(song).forEach((p, i) => { song.parts[p.id].pos = i + 1; });
  }

  return { deletedBars, deletedAccents };
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

/* ── Cascade Duplicate ────────────────────────────── */

/**
 * Duplicate a part including all its bars and accents.
 * Returns the new partId.
 */
export function duplicatePart(db, songId, partId) {
  ensureCollections(db);
  const song = (db.songs || {})[songId];
  if (!song || !song.parts || !song.parts[partId]) return null;

  const src = song.parts[partId];

  // Shift positions of parts after current
  for (const p of Object.values(song.parts)) {
    if (p.pos > src.pos) p.pos += 1;
  }

  const newPartId = nextPartId(songId, song);
  song.parts[newPartId] = {
    pos: src.pos + 1,
    name: src.name + ' (Copy)',
    bars: src.bars,
    duration_sec: src.duration_sec,
    light_template: src.light_template,
    notes: src.notes || '',
  };

  // Duplicate bars and accents
  const barIdMap = {}; // oldBarId → newBarId
  for (const [barId, bar] of Object.entries(db.bars)) {
    if (bar.part_id === partId) {
      const newBarId = nextId('B', db.bars);
      barIdMap[barId] = newBarId;
      db.bars[newBarId] = {
        ...bar,
        part_id: newPartId,
        audio: '', // Audio paths need re-export
      };
    }
  }

  // Duplicate accents, mapping to new bar IDs
  for (const [accId, acc] of Object.entries(db.accents)) {
    if (barIdMap[acc.bar_id]) {
      const newAccId = nextId('A', db.accents);
      db.accents[newAccId] = {
        ...acc,
        bar_id: barIdMap[acc.bar_id],
      };
    }
  }

  return newPartId;
}

/* ── Bar-Count Sync ───────────────────────────────── */

/**
 * Synchronise bars in db.bars with the declared part.bars count.
 * Removes excess bars (and their accents) when part.bars is reduced.
 * Returns { removed: string[] } — list of removed bar IDs.
 */
export function syncBarCount(db, partId, declaredCount) {
  ensureCollections(db);
  const removed = [];

  // Get all bars for this part, sorted by bar_num
  const barsForPart = Object.entries(db.bars)
    .filter(([, b]) => b.part_id === partId)
    .map(([id, b]) => ({ id, ...b }))
    .sort((a, b) => a.bar_num - b.bar_num);

  // Remove bars whose bar_num > declaredCount
  for (const bar of barsForPart) {
    if (bar.bar_num > declaredCount) {
      deleteBar(db, bar.id);
      removed.push(bar.id);
    }
  }

  return { removed };
}

/* ── Split-Marker Migration: partIndex → partId ───── */

/**
 * Migrate split_markers from partIndex-based to partId-based references.
 * This makes markers independent of part order.
 *
 * Before: { time: 5.2, partIndex: 0 }
 * After:  { time: 5.2, partIndex: 0, partId: "5Ij0Ns_P001" }
 *
 * The partIndex field is kept for backward compatibility but partId
 * becomes the authoritative reference.
 */
export function migrateSplitMarkers(db) {
  let migrated = 0;
  for (const [songId, song] of Object.entries(db.songs || {})) {
    if (!song.split_markers) continue;
    const parts = sortedParts(song);
    if (!parts.length) continue;

    for (const markers of [song.split_markers.partMarkers, song.split_markers.barMarkers]) {
      if (!Array.isArray(markers)) continue;
      for (const m of markers) {
        // Only migrate if partId is not yet set
        if (!m.partId && typeof m.partIndex === 'number') {
          const part = parts[m.partIndex];
          if (part) {
            m.partId = part.id;
            migrated++;
          }
        }
      }
    }
  }
  return { migrated };
}

/**
 * Rebuild partIndex values from partId references.
 * Call this after part reorder to keep partIndex in sync.
 */
export function rebuildPartIndexFromId(song) {
  if (!song || !song.split_markers) return;
  const parts = sortedParts(song);
  const idToIndex = {};
  parts.forEach((p, i) => { idToIndex[p.id] = i; });

  for (const markers of [song.split_markers.partMarkers, song.split_markers.barMarkers]) {
    if (!Array.isArray(markers)) continue;
    for (const m of markers) {
      if (m.partId && idToIndex[m.partId] !== undefined) {
        m.partIndex = idToIndex[m.partId];
      }
    }
  }
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

  // Migrate split markers to partId-based
  const migration = migrateSplitMarkers(db);
  if (migration.migrated > 0) {
    console.log(`[integrity] Migrated ${migration.migrated} split markers to partId-based`);
  }

  return result;
}
