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
 * bar_num is absolute (song-wide), so we keep the first declaredCount bars
 * sorted by bar_num and remove the rest.
 * Returns { removed: string[] } — list of removed bar IDs.
 */
export function syncBarCount(db, partId, declaredCount) {
  ensureCollections(db);
  const removed = [];

  // Get all bars for this part, sorted by bar_num (absolute)
  const barsForPart = Object.entries(db.bars)
    .filter(([, b]) => b.part_id === partId)
    .map(([id, b]) => ({ id, ...b }))
    .sort((a, b) => a.bar_num - b.bar_num);

  // Keep first declaredCount bars, remove the rest
  for (let i = declaredCount; i < barsForPart.length; i++) {
    deleteBar(db, barsForPart[i].id);
    removed.push(barsForPart[i].id);
  }

  return { removed };
}

/* ── Split-Marker Migration: Legacy → Unified ───── */

/**
 * Migrate split_markers from the old two-array format (partMarkers + barMarkers)
 * to the new unified single-array format (markers[]).
 *
 * Old: { partMarkers: [{time, partIndex, partId}], barMarkers: [{time, partIndex, partId}] }
 * New: { markers: [{time, partId, partStart: true/false}] }
 *
 * Also handles the even older format without partId by resolving from partIndex.
 * The partIndex field is dropped — partId is the sole reference.
 */
export function migrateToUnifiedMarkers(db) {
  let migrated = 0;
  for (const [songId, song] of Object.entries(db.songs || {})) {
    if (!song.split_markers) continue;
    const sm = song.split_markers;

    // Already migrated?
    if (Array.isArray(sm.markers)) continue;

    const parts = sortedParts(song);
    const indexToId = (idx) => parts[idx] ? parts[idx].id : undefined;

    const unified = [];

    // Convert part markers → partStart: true
    if (Array.isArray(sm.partMarkers)) {
      for (const m of sm.partMarkers) {
        const partId = m.partId || indexToId(m.partIndex);
        if (partId) {
          unified.push({ time: m.time, partId, partStart: true });
        }
      }
    }

    // Convert bar markers → partStart: false (skip those co-located with a part marker)
    if (Array.isArray(sm.barMarkers)) {
      for (const m of sm.barMarkers) {
        const partId = m.partId || indexToId(m.partIndex);
        if (!partId) continue;
        // Skip if a part marker sits at the same time (within tolerance)
        const isPartStart = unified.some(u => u.partStart && Math.abs(u.time - m.time) < 0.01);
        if (!isPartStart) {
          unified.push({ time: m.time, partId, partStart: false });
        }
      }
    }

    // Sort by time
    unified.sort((a, b) => a.time - b.time);

    // Replace old format with unified
    song.split_markers = { markers: unified };
    migrated++;
  }
  return { migrated };
}

/* ── Sync bars count from split_markers ───────────── */

/**
 * Ensure part.bars matches the number of markers for that part.
 * split_markers.markers is the source of truth when present.
 * Returns the number of parts that were fixed.
 */
export function syncBarsFromMarkers(db) {
  let fixed = 0;
  for (const [, song] of Object.entries(db.songs || {})) {
    const sm = song.split_markers;
    if (!sm || !Array.isArray(sm.markers) || sm.markers.length === 0) continue;

    // Count all markers (part starts count as bar 1) per partId
    const barsByPartId = {};
    for (const m of sm.markers) {
      if (!m.partId) continue;
      barsByPartId[m.partId] = (barsByPartId[m.partId] || 0) + 1;
    }

    for (const [partId, count] of Object.entries(barsByPartId)) {
      if (count > 0 && song.parts && song.parts[partId]) {
        const part = song.parts[partId];
        if (part.bars !== count) {
          console.log(`[integrity] Fixed bars: ${song.name} / ${part.name}: ${part.bars} → ${count}`);
          part.bars = count;
          fixed++;
        }
      }
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

  // Migrate split markers to unified single-array format
  const migration = migrateToUnifiedMarkers(db);
  if (migration.migrated > 0) {
    console.log(`[integrity] Migrated ${migration.migrated} song(s) to unified markers`);
  }

  // Sync bars count from split_markers (source of truth)
  const barsFixed = syncBarsFromMarkers(db);
  if (barsFixed > 0) {
    console.log(`[integrity] Fixed bars count for ${barsFixed} part(s) from split_markers`);
    result.valid = false; // trigger dirty flag so changes get saved
  }

  return result;
}
