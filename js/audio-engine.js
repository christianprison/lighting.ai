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
export function play(onEnd) {
  if (!audioBuffer) return;
  const ac = getContext();
  if (ac.state === 'suspended') ac.resume();

  stop(true); // stop previous source without resetting position

  sourceNode = ac.createBufferSource();
  sourceNode.buffer = audioBuffer;
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
  startedAt = ac.currentTime - offset;
  playing = true;
}

/**
 * Pause playback (remembers position for resume).
 */
export function pause() {
  if (!playing) return;
  const ac = getContext();
  pausedAt = ac.currentTime - startedAt;
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
    const t = ac.currentTime - startedAt;
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
 * Export a segment of the audio buffer as WAV (Base64 string).
 * Uses OfflineAudioContext for precision.
 * @param {number} startTime - start in seconds
 * @param {number} endTime - end in seconds
 * @returns {Promise<string>} base64-encoded WAV
 */
export async function exportSegmentWav(startTime, endTime) {
  if (!audioBuffer) throw new Error('No audio loaded');

  const sr = audioBuffer.sampleRate;
  const channels = audioBuffer.numberOfChannels;
  const startSample = Math.floor(startTime * sr);
  const endSample = Math.min(Math.floor(endTime * sr), audioBuffer.length);
  const length = endSample - startSample;

  if (length <= 0) throw new Error('Invalid segment range');

  // Extract samples
  const channelData = [];
  for (let ch = 0; ch < channels; ch++) {
    const full = audioBuffer.getChannelData(ch);
    channelData.push(full.slice(startSample, endSample));
  }

  // Encode as WAV
  const wavBuffer = encodeWav(channelData, sr, channels);

  // Convert to base64
  const bytes = new Uint8Array(wavBuffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Encode raw PCM channel data as a WAV ArrayBuffer.
 * @param {Float32Array[]} channelData
 * @param {number} sampleRate
 * @param {number} numChannels
 * @returns {ArrayBuffer}
 */
function encodeWav(channelData, sampleRate, numChannels) {
  const length = channelData[0].length;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = length * blockAlign;
  const bufferSize = 44 + dataSize;
  const buffer = new ArrayBuffer(bufferSize);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, 'RIFF');
  view.setUint32(4, bufferSize - 8, true);
  writeString(view, 8, 'WAVE');

  // fmt chunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // chunk size
  view.setUint16(20, 1, true);  // PCM format
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);

  // data chunk
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  // Interleave and write samples
  let offset = 44;
  for (let i = 0; i < length; i++) {
    for (let ch = 0; ch < numChannels; ch++) {
      const sample = Math.max(-1, Math.min(1, channelData[ch][i]));
      const val = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
      view.setInt16(offset, val, true);
      offset += 2;
    }
  }

  return buffer;
}

function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
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
