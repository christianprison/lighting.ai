/**
 * js/audio-engine.js — Web Audio API wrapper for lighting.ai
 *
 * Handles: decoding audio files, playback with pause/resume,
 * waveform peak extraction, and audio segment export.
 */

/* ── AudioContext (shared, lazy-init) ──────────────── */
let ctx = null;

function getContext() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  return ctx;
}

/* ── State ─────────────────────────────────────────── */
let audioBuffer = null;
let sourceNode = null;
let startedAt = 0;   // context.currentTime when playback last started
let pausedAt = 0;     // offset in seconds where we paused
let playing = false;
let onEndCallback = null;
let _playbackRate = 1.0;

/* ── Public API ────────────────────────────────────── */

/**
 * Decode an ArrayBuffer (from File/Blob) into an AudioBuffer.
 * Stores the buffer internally and returns metadata.
 * @param {ArrayBuffer} arrayBuffer
 * @returns {Promise<{duration: number, sampleRate: number, channels: number}>}
 */
export async function decodeAudio(arrayBuffer) {
  const ac = getContext();
  audioBuffer = await ac.decodeAudioData(arrayBuffer);
  pausedAt = 0;
  playing = false;
  return {
    duration: audioBuffer.duration,
    sampleRate: audioBuffer.sampleRate,
    channels: audioBuffer.numberOfChannels,
  };
}

/**
 * Get the decoded AudioBuffer (or null).
 * @returns {AudioBuffer|null}
 */
export function getBuffer() {
  return audioBuffer;
}

/**
 * Start or resume playback from the current position.
 * @param {Function} [onEnd] - called when playback reaches end
 */
export async function play(onEnd) {
  if (!audioBuffer) return;
  const ac = getContext();
  if (ac.state === 'suspended') await ac.resume();

  stop(true); // stop previous source without resetting position

  sourceNode = ac.createBufferSource();
  sourceNode.buffer = audioBuffer;
  sourceNode.playbackRate.value = _playbackRate;
  sourceNode.connect(ac.destination);
  sourceNode.onended = () => {
    if (playing) {
      playing = false;
      pausedAt = 0;
      if (onEndCallback) onEndCallback();
    }
  };
  onEndCallback = onEnd || null;

  const offset = pausedAt;
  sourceNode.start(0, offset);
  startedAt = ac.currentTime - offset / _playbackRate;
  playing = true;
}

/**
 * Pause playback (remembers position for resume).
 */
export function pause() {
  if (!playing) return;
  const ac = getContext();
  pausedAt = (ac.currentTime - startedAt) * _playbackRate;
  stop(true);
  playing = false;
}

/**
 * Stop playback.
 * @param {boolean} [keepPos=false] - if true, keeps pausedAt for resume
 */
export function stop(keepPos = false) {
  if (sourceNode) {
    try {
      sourceNode.onended = null;
      sourceNode.stop();
    } catch { /* already stopped */ }
    sourceNode.disconnect();
    sourceNode = null;
  }
  if (!keepPos) {
    pausedAt = 0;
    playing = false;
  }
}

/**
 * Seek to a specific time (seconds).
 * If currently playing, restarts from new position.
 * @param {number} time
 */
export function seek(time) {
  if (!audioBuffer) return;
  const wasPlaying = playing;
  stop(true);
  pausedAt = Math.max(0, Math.min(time, audioBuffer.duration));
  playing = false;
  if (wasPlaying) play(onEndCallback);
}

/**
 * Get current playback position in seconds.
 * @returns {number}
 */
export function getCurrentTime() {
  if (!audioBuffer) return 0;
  if (playing) {
    const ac = getContext();
    const t = (ac.currentTime - startedAt) * _playbackRate;
    return Math.min(t, audioBuffer.duration);
  }
  return pausedAt;
}

/**
 * Is audio currently playing?
 * @returns {boolean}
 */
export function isPlaying() {
  return playing;
}

/**
 * Extract waveform peaks for rendering.
 * Returns an array of peak amplitudes (0-1) for the given number of buckets.
 * @param {number} buckets - number of bars to draw
 * @returns {Float32Array}
 */
export function getPeaks(buckets) {
  if (!audioBuffer) return new Float32Array(buckets);
  const chan = audioBuffer.getChannelData(0);
  const len = chan.length;
  const step = len / buckets;
  const peaks = new Float32Array(buckets);

  for (let i = 0; i < buckets; i++) {
    const start = Math.floor(i * step);
    const end = Math.floor((i + 1) * step);
    let max = 0;
    for (let j = start; j < end; j++) {
      const abs = Math.abs(chan[j]);
      if (abs > max) max = abs;
    }
    peaks[i] = max;
  }
  return peaks;
}

/**
 * Extract waveform peaks for a specific time range.
 * @param {number} startSec - start time in seconds
 * @param {number} endSec - end time in seconds
 * @param {number} buckets - number of output peaks
 * @returns {Float32Array}
 */
export function getPeaksRange(startSec, endSec, buckets) {
  if (!audioBuffer || buckets <= 0) return new Float32Array(buckets);
  const sr = audioBuffer.sampleRate;
  const chan = audioBuffer.getChannelData(0);
  const sStart = Math.max(0, Math.floor(startSec * sr));
  const sEnd = Math.min(chan.length, Math.floor(endSec * sr));
  const rangeLen = sEnd - sStart;
  if (rangeLen <= 0) return new Float32Array(buckets);

  const step = rangeLen / buckets;
  const peaks = new Float32Array(buckets);

  for (let i = 0; i < buckets; i++) {
    const from = sStart + Math.floor(i * step);
    const to = sStart + Math.floor((i + 1) * step);
    let max = 0;
    for (let j = from; j < to; j++) {
      const abs = Math.abs(chan[j]);
      if (abs > max) max = abs;
    }
    peaks[i] = max;
  }
  return peaks;
}

/**
 * Export a segment of the audio buffer as MP3 (Base64 string).
 * Uses lamejs for client-side MP3 encoding.
 * @param {number} startTime - start in seconds
 * @param {number} endTime - end in seconds
 * @param {number} [kbps=128] - MP3 bitrate
 * @returns {Promise<string>} base64-encoded MP3
 */
export async function exportSegmentMp3(startTime, endTime, kbps = 128) {
  if (!audioBuffer) throw new Error('No audio loaded');
  const lame = window.lamejs;
  if (!lame) throw new Error('lamejs not loaded — CDN script missing?');

  const sr = audioBuffer.sampleRate;
  const channels = audioBuffer.numberOfChannels;
  const startSample = Math.floor(startTime * sr);
  const endSample = Math.min(Math.floor(endTime * sr), audioBuffer.length);
  const length = endSample - startSample;

  if (length <= 0) throw new Error('Invalid segment range');

  // Convert Float32 → Int16
  function floatTo16(float32) {
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16;
  }

  const left = floatTo16(audioBuffer.getChannelData(0).slice(startSample, endSample));
  const right = channels > 1
    ? floatTo16(audioBuffer.getChannelData(1).slice(startSample, endSample))
    : left;

  const numCh = channels > 1 ? 2 : 1;
  const mp3enc = new lame.Mp3Encoder(numCh, sr, kbps);
  const mp3Chunks = [];
  const blockSize = 1152;

  for (let i = 0; i < length; i += blockSize) {
    const leftChunk = left.subarray(i, i + blockSize);
    const mp3buf = numCh === 2
      ? mp3enc.encodeBuffer(leftChunk, right.subarray(i, i + blockSize))
      : mp3enc.encodeBuffer(leftChunk);
    if (mp3buf.length > 0) mp3Chunks.push(mp3buf);
  }
  const tail = mp3enc.flush();
  if (tail.length > 0) mp3Chunks.push(tail);

  // Merge chunks into single Uint8Array
  const totalLen = mp3Chunks.reduce((s, c) => s + c.length, 0);
  const mp3Data = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of mp3Chunks) {
    mp3Data.set(chunk, offset);
    offset += chunk.length;
  }

  // Convert to base64 (chunk-safe for large arrays)
  const chunkSize = 8192;
  let binary = '';
  for (let i = 0; i < mp3Data.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, mp3Data.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

/* ── Segment Playback (for playing bars of a part) ── */

let segmentSource = null;
let segmentQueue = [];
let segmentIndex = 0;
let segmentPlaying = false;
let onSegmentDone = null;

/**
 * Play a list of audio segments sequentially without gaps.
 * Each segment is {startTime, endTime} in seconds referring to the loaded AudioBuffer.
 * @param {{startTime: number, endTime: number}[]} segments
 * @param {Function} [onDone] - called when all segments finished
 */
export function playSegments(segments, onDone) {
  stopSegments();
  if (!audioBuffer || segments.length === 0) return;

  segmentQueue = segments;
  segmentIndex = 0;
  segmentPlaying = true;
  onSegmentDone = onDone || null;
  _playNextSegment();
}

function _playNextSegment() {
  if (segmentIndex >= segmentQueue.length) {
    segmentPlaying = false;
    if (onSegmentDone) onSegmentDone();
    return;
  }

  const ac = getContext();
  if (ac.state === 'suspended') ac.resume();

  const seg = segmentQueue[segmentIndex];
  const duration = seg.endTime - seg.startTime;
  if (duration <= 0) { segmentIndex++; _playNextSegment(); return; }

  segmentSource = ac.createBufferSource();
  segmentSource.buffer = audioBuffer;
  segmentSource.connect(ac.destination);
  segmentSource.onended = () => {
    segmentIndex++;
    _playNextSegment();
  };
  segmentSource.start(0, seg.startTime, duration);
}

/**
 * Stop segment playback.
 */
export function stopSegments() {
  segmentPlaying = false;
  segmentQueue = [];
  segmentIndex = 0;
  if (segmentSource) {
    try { segmentSource.onended = null; segmentSource.stop(); } catch { /* ok */ }
    segmentSource.disconnect();
    segmentSource = null;
  }
}

/**
 * Is segment playback in progress?
 * @returns {boolean}
 */
export function isSegmentPlaying() {
  return segmentPlaying;
}

/**
 * Set playback speed (0.25 - 2.0).
 * If currently playing, applies immediately.
 * @param {number} rate
 */
export function setPlaybackRate(rate) {
  const newRate = Math.max(0.25, Math.min(2.0, rate));
  if (playing) {
    // Capture position BEFORE changing rate (getCurrentTime uses _playbackRate)
    const pos = getCurrentTime();
    _playbackRate = newRate;
    stop(true);
    pausedAt = pos;
    playing = false;
    play(onEndCallback);
  } else {
    _playbackRate = newRate;
  }
}

/**
 * Get current playback rate.
 * @returns {number}
 */
export function getPlaybackRate() {
  return _playbackRate;
}

/**
 * Reset the engine state (clear buffer etc.)
 */
export function reset() {
  stop();
  audioBuffer = null;
  pausedAt = 0;
  playing = false;
  onEndCallback = null;
}
