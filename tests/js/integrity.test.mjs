/**
 * Characterization tests for js/integrity.js
 *
 * These pin down the CURRENT behaviour of the data-integrity layer of the
 * DB-Pflege-App. The central-DB port will replace the *persistence* (GitHub
 * JSON -> Supabase) but MUST keep the data-model semantics identical. If a
 * port changes how songs/bars/accents relate, one of these tests goes red.
 *
 * Runner: Node's built-in test runner (no npm install).
 *   node --test tests/js/
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  validateDB,
  cleanupOrphans,
  deleteSong,
  deleteBar,
  syncBarCount,
  migrateToUnifiedMarkers,
  syncBarsFromMarkers,
  checkOnLoad,
} from '../../js/integrity.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, '..', '..');

/** A small, fully-controlled fixture with two real refs and three orphans. */
function makeDb() {
  return {
    songs: { S1: { name: 'Alpha' }, S2: { name: 'Bravo' } },
    bars: {
      B0001: { song_id: 'S1', bar_num: 1 },
      B0002: { song_id: 'S1', bar_num: 2 },
      B0003: { song_id: 'S2', bar_num: 1 },
      B0099: { song_id: 'GONE', bar_num: 1 }, // orphan: song missing
    },
    accents: {
      A0001: { bar_id: 'B0001', type: 'bl' },
      A0002: { bar_id: 'B0002', type: 'st' },
      A0099: { bar_id: 'GONE', type: 'bo' }, // orphan: bar missing
    },
    setlist: {
      items: [
        { type: 'song', song_id: 'S1' },
        { type: 'pause' },
        { type: 'song', song_id: 'GONE' }, // dangling setlist ref
      ],
    },
  };
}

/* ── validateDB ─────────────────────────────────────── */

test('validateDB flags orphan bars, orphan accents and dangling setlist refs', () => {
  const db = makeDb();
  const r = validateDB(db);
  assert.equal(r.valid, false);
  assert.deepEqual(r.orphanBars, ['B0099']);
  assert.deepEqual(r.orphanAccents, ['A0099']);
  // 1 bar orphan + 1 accent orphan + 1 setlist dangling = 3 errors
  assert.equal(r.errors.length, 3);
});

test('validateDB on a clean db reports valid', () => {
  const db = makeDb();
  delete db.bars.B0099;
  delete db.accents.A0099;
  db.setlist.items = db.setlist.items.filter(
    (i) => i.type !== 'song' || i.song_id !== 'GONE',
  );
  const r = validateDB(db);
  assert.equal(r.valid, true);
  assert.equal(r.errors.length, 0);
});

/* ── cleanupOrphans ─────────────────────────────────── */

test('cleanupOrphans removes exactly the orphaned bars and accents', () => {
  const db = makeDb();
  const res = cleanupOrphans(db);
  assert.deepEqual(res.removedBars, ['B0099']);
  assert.deepEqual(res.removedAccents, ['A0099']);
  assert.deepEqual(Object.keys(db.bars).sort(), ['B0001', 'B0002', 'B0003']);
  assert.deepEqual(Object.keys(db.accents).sort(), ['A0001', 'A0002']);
  // setlist dangling ref is NOT touched by cleanupOrphans (only bars/accents)
  assert.equal(db.setlist.items.some((i) => i.song_id === 'GONE'), true);
});

/* ── deleteSong (cascade) ───────────────────────────── */

test('deleteSong cascades to its bars, their accents, and the setlist', () => {
  const db = makeDb();
  const res = deleteSong(db, 'S1');
  assert.equal(res.deleted, true);
  assert.deepEqual(res.deletedBars.sort(), ['B0001', 'B0002']);
  assert.deepEqual(res.deletedAccents.sort(), ['A0001', 'A0002']);
  assert.equal('S1' in db.songs, false);
  assert.deepEqual(Object.keys(db.bars).sort(), ['B0003', 'B0099']);
  assert.deepEqual(Object.keys(db.accents).sort(), ['A0099']);
  assert.equal(db.setlist.items.some((i) => i.song_id === 'S1'), false);
});

test('deleteSong on a missing song is a no-op', () => {
  const db = makeDb();
  const res = deleteSong(db, 'NOPE');
  assert.deepEqual(res, { deleted: false });
  assert.equal(Object.keys(db.bars).length, 4);
});

/* ── deleteBar ──────────────────────────────────────── */

test('deleteBar removes the bar and its accents only', () => {
  const db = makeDb();
  const res = deleteBar(db, 'B0002');
  assert.deepEqual(res.deletedAccents, ['A0002']);
  assert.equal('B0002' in db.bars, false);
  assert.equal('A0002' in db.accents, false);
  assert.equal('B0001' in db.bars, true);
});

/* ── syncBarCount ───────────────────────────────────── */

test('syncBarCount trims excess bars beyond declaredCount (lowest bar_num kept)', () => {
  const db = makeDb();
  const res = syncBarCount(db, 'S1', 1);
  assert.deepEqual(res.removed, ['B0002']); // B0001 (bar_num 1) kept, B0002 removed
  assert.equal('B0001' in db.bars, true);
  assert.equal('B0002' in db.bars, false);
  assert.equal('A0002' in db.accents, false); // accent cascaded
});

test('syncBarCount with a count >= existing bars removes nothing', () => {
  const db = makeDb();
  const res = syncBarCount(db, 'S1', 5);
  assert.deepEqual(res.removed, []);
});

/* ── migrateToUnifiedMarkers ────────────────────────── */

test('migrateToUnifiedMarkers folds legacy part/bar arrays into sorted {time} markers', () => {
  const db = {
    songs: {
      S1: {
        name: 'Legacy',
        split_markers: {
          partMarkers: [{ time: 0.0 }, { time: 8.0 }],
          barMarkers: [{ time: 8.0 }, { time: 4.0 }], // 8.0 is a near-dup of partMarker
        },
      },
    },
  };
  const res = migrateToUnifiedMarkers(db);
  assert.equal(res.migrated, 1);
  assert.deepEqual(db.songs.S1.split_markers, {
    markers: [{ time: 0.0 }, { time: 4.0 }, { time: 8.0 }],
  });
});

test('migrateToUnifiedMarkers strips legacy partId/partStart from new-format markers', () => {
  const db = {
    songs: {
      S1: {
        split_markers: {
          markers: [{ time: 0.0, partId: 'P1', partStart: true }, { time: 2.0 }],
        },
      },
    },
  };
  const res = migrateToUnifiedMarkers(db);
  assert.equal(res.migrated, 1);
  assert.equal('partId' in db.songs.S1.split_markers.markers[0], false);
  assert.equal('partStart' in db.songs.S1.split_markers.markers[0], false);
  assert.equal(db.songs.S1.split_markers.markers[0].time, 0.0);
});

/* ── syncBarsFromMarkers ────────────────────────────── */

test('syncBarsFromMarkers makes total_bars match the marker count', () => {
  const db = {
    songs: {
      S1: { name: 'X', total_bars: 5, split_markers: { markers: [{ time: 0 }, { time: 1 }, { time: 2 }] } },
      S2: { name: 'Y', total_bars: 2, split_markers: { markers: [{ time: 0 }, { time: 1 }] } }, // already correct
    },
  };
  const fixed = syncBarsFromMarkers(db);
  assert.equal(fixed, 1);
  assert.equal(db.songs.S1.total_bars, 3);
  assert.equal(db.songs.S2.total_bars, 2);
});

/* ── checkOnLoad (integration) ──────────────────────── */

test('checkOnLoad returns a validation result and applies migrations', () => {
  const db = makeDb();
  const r = checkOnLoad(db, /* autoClean */ true);
  assert.equal(typeof r.valid, 'boolean');
  // autoClean removed the orphans
  assert.equal('B0099' in db.bars, false);
  assert.equal('A0099' in db.accents, false);
});

/* ── Invariant on the REAL production database ──────── */

test('the real lighting-ai-db.json passes referential integrity (current baseline)', () => {
  const db = JSON.parse(
    readFileSync(join(REPO_ROOT, 'db', 'lighting-ai-db.json'), 'utf8'),
  );
  const r = validateDB(db);
  // Baseline today: no orphans, no dangling setlist refs. If real data drifts,
  // this surfaces it BEFORE the port touches the persistence layer.
  assert.deepEqual(r.orphanBars, [], `unexpected orphan bars: ${r.orphanBars}`);
  assert.deepEqual(r.orphanAccents, [], `unexpected orphan accents: ${r.orphanAccents}`);
  assert.equal(r.valid, true, `validation errors: ${r.errors.join(' | ')}`);
});
