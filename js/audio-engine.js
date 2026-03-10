/**
 * js/audio-engine.js — Web Audio API wrapper for lighting.ai
 *
 * Handles: decoding audio files, playback with pause/resume,
 * waveform peak extraction, and audio segment export.
 */

/* ── AudioContext (shared, eager-init on first gesture) ── */
let ctx = null;

function getContext() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  return ctx;
}

/** Expose the shared AudioContext for use outside the engine */
export { getContext };

/**
 * Play a short test beep to verify audio output works.
 * Must be called from a user gesture (click/touch) on iOS.
 * @returns {Promise<string>} diagnostic info
 */
export async function testBeep() {
  const ac = getContext();
  const info = [`state: ${ac.state}`, `sampleRate: ${ac.sampleRate}`];
  if (ac.state === 'suspended') {
    await ac.resume();
    info.push(`after resume: ${ac.state}`);
  }
  // Generate a 440Hz sine wave for 200ms
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = 'sine';
  osc.frequency.value = 440;
  gain.gain.value = 0.3;
  osc.connect(gain);
  gain.connect(ac.destination);
  osc.start();
  osc.stop(ac.currentTime + 0.2);
  info.push('beep started');
  return info.join(', ');
}

/**
 * Pre-warm the AudioContext so playback starts instantly.
 * Call on user interaction (tab switch, click, touch) before actual play.
 * Also installs a global gesture listener to keep the context alive.
 */
export function warmup() {
  const ac = getContext();
  if (ac.state === 'suspended') ac.resume();
}

// Auto-resume on any user gesture (critical for iOS/iPad).
// Creates the AudioContext eagerly on first gesture so it's already
// running when play() is called later.
let _gestureListenerInstalled = false;
export function installGestureListener() {
  if (_gestureListenerInstalled) return;
  _gestureListenerInstalled = true;
  const ensureRunning = () => {
    const ac = getContext(); // creates ctx if null
    if (ac.state === 'suspended') ac.resume();
  };
  document.addEventListener('touchstart', ensureRunning, { passive: true });
  document.addEventListener('mousedown', ensureRunning, { passive: true });
  document.addEventListener('keydown', ensureRunning, { passive: true, once: true });
}

/**
 * Get the estimated output latency in seconds.
 * Used for tap compensation: subtract this from tap timestamps.
 */
export function getOutputLatency() {
  if (!ctx) return 0;
  // outputLatency: time from audio render to speaker (Safari/Chrome)
  // baseLatency: time from buffer submit to audio render
  return (ctx.outputLatency || 0) + (ctx.baseLatency || 0);
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
 * Safari silently discards sourceNode.start() on a suspended context,
 * so we MUST wait for resume before creating the source node.
 * Uses .then() instead of await to avoid breaking the gesture chain.
 * @param {Function} [onEnd] - called when playback reaches end
 */
export function play(onEnd) {
  if (!audioBuffer) return;
  const ac = getContext();
  const offset = pausedAt;
  onEndCallback = onEnd || null;
  playing = true;

  if (ac.state === 'running') {
    _startSource(ac, offset);
  } else {
    // Resume called synchronously in gesture handler — Safari requires this.
    // Then start source once context is actually running.
    ac.resume().then(() => {
      if (playing) _startSource(ac, offset);
    });
  }
}

/** @private Create and start the buffer source node. Context MUST be running. */
function _startSource(ac, offset) {
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

  sourceNode.start(0, offset);
  startedAt = ac.currentTime - offset / _playbackRate;
}

/**
 * Pause playback (remembers position for resume).
 */
export function pause() {
  if (!playing) return;
  if (sourceNode) {
    const ac = getContext();
    pausedAt = (ac.currentTime - startedAt) * _playbackRate;
  }
  // If sourceNode is null, context was still resuming — pausedAt is already correct
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
    // If source hasn't started yet (context still resuming), show paused position
    if (!sourceNode) return pausedAt;
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
 * Find the nearest energy peak (transient onset) near a given time.
 * Searches within a window of ±windowMs milliseconds.
 * Uses an onset detection approach: finds the sample position with
 * the highest energy increase (derivative of RMS).
 * @param {number} timeSec - center time in seconds
 * @param {number} [windowMs=100] - search window in ms
 * @returns {number} snapped time in seconds
 */
export function findPeakNear(timeSec, windowMs = 100) {
  if (!audioBuffer) return timeSec;
  const sr = audioBuffer.sampleRate;
  const chan = audioBuffer.getChannelData(0);
  const windowSamples = Math.floor((windowMs / 1000) * sr);
  const center = Math.floor(timeSec * sr);
  const start = Math.max(0, center - windowSamples);
  const end = Math.min(chan.length, center + windowSamples);

  // Compute short-term energy in small frames (2ms ~= 88 samples at 44100)
  const frameSize = Math.max(1, Math.floor(sr * 0.002));
  let bestEnergy = -Infinity;
  let bestSample = center;

  for (let i = start; i < end - frameSize; i += Math.floor(frameSize / 2)) {
    // Current frame energy
    let energy = 0;
    for (let j = 0; j < frameSize; j++) {
      const s = chan[i + j];
      energy += s * s;
    }
    // Previous frame energy (for onset detection)
    let prevEnergy = 0;
    if (i >= frameSize) {
      for (let j = 0; j < frameSize; j++) {
        const s = chan[i - frameSize + j];
        prevEnergy += s * s;
      }
    }
    // Onset strength = energy increase
    const onset = energy - prevEnergy;
    if (onset > bestEnergy) {
      bestEnergy = onset;
      bestSample = i;
    }
  }

  return bestSample / sr;
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
let segmentPaused = false;
let segmentPausedAt = 0;     // absolute buffer position where we paused
let onSegmentDone = null;
let segmentStartedCtx = 0;  // context.currentTime when current segment started
let segmentStartOffset = 0; // buffer offset of current segment
let segmentCurrentEnd = 0;  // end time of the current segment

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
  segmentPaused = false;
  segmentPausedAt = 0;
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
  if (ac.state === 'suspended') {
    ac.resume().then(() => _playNextSegment());
    return;
  }

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
  segmentStartOffset = seg.startTime;
  segmentStartedCtx = ac.currentTime;
  segmentCurrentEnd = seg.endTime;
  segmentSource.start(0, seg.startTime, duration);
}

/**
 * Stop segment playback.
 */
export function stopSegments() {
  segmentPlaying = false;
  segmentPaused = false;
  segmentPausedAt = 0;
  segmentCurrentEnd = 0;
  segmentQueue = [];
  segmentIndex = 0;
  segmentStartedCtx = 0;
  segmentStartOffset = 0;
  if (segmentSource) {
    try { segmentSource.onended = null; segmentSource.stop(); } catch { /* ok */ }
    segmentSource.disconnect();
    segmentSource = null;
  }
}

/**
 * Pause segment playback (remembers position for resume).
 */
export function pauseSegments() {
  if (!segmentPlaying || segmentPaused) return;
  const ac = getContext();
  segmentPausedAt = segmentStartOffset + (ac.currentTime - segmentStartedCtx);
  segmentPaused = true;
  segmentPlaying = false;
  if (segmentSource) {
    try { segmentSource.onended = null; segmentSource.stop(); } catch { /* ok */ }
    segmentSource.disconnect();
    segmentSource = null;
  }
}

/**
 * Resume segment playback from paused position.
 */
export function resumeSegments() {
  if (!segmentPaused || !audioBuffer) return;
  const ac = getContext();
  if (ac.state === 'suspended') {
    ac.resume().then(() => resumeSegments());
    return;
  }

  const resumeFrom = segmentPausedAt;
  const resumeEnd = segmentCurrentEnd;
  const duration = resumeEnd - resumeFrom;

  if (duration <= 0) {
    // Current segment finished, move to next
    segmentPaused = false;
    segmentPlaying = true;
    segmentIndex++;
    _playNextSegment();
    return;
  }

  segmentSource = ac.createBufferSource();
  segmentSource.buffer = audioBuffer;
  segmentSource.connect(ac.destination);
  segmentSource.onended = () => {
    segmentIndex++;
    _playNextSegment();
  };
  segmentStartOffset = resumeFrom;
  segmentStartedCtx = ac.currentTime;
  segmentSource.start(0, resumeFrom, duration);

  segmentPaused = false;
  segmentPlaying = true;
}

/**
 * Is segment playback in progress (playing or paused)?
 * @returns {boolean}
 */
export function isSegmentPlaying() {
  return segmentPlaying;
}

/**
 * Is segment playback paused?
 * @returns {boolean}
 */
export function isSegmentPaused() {
  return segmentPaused;
}

/**
 * Get current absolute time (in the audio buffer) during segment playback.
 * @returns {number} seconds into the buffer, or 0 if not playing
 */
export function getSegmentCurrentTime() {
  if (!segmentPlaying) return 0;
  const ac = getContext();
  const elapsed = ac.currentTime - segmentStartedCtx;
  return segmentStartOffset + elapsed;
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
  stopClick();
  audioBuffer = null;
  pausedAt = 0;
  playing = false;
  onEndCallback = null;
}

/* ── Click Track (Metronome) ─────────────────────── */

let _clickEnabled = false;
let _clickBpm = 0;
let _clickGain = null;       // GainNode for click volume
let _clickTimerId = null;    // setTimeout handle for scheduler
let _clickNextBeat = 0;      // next beat time in AudioContext time
let _clickLookahead = 0.1;   // schedule 100ms ahead
let _clickInterval = 25;     // scheduler runs every 25ms
let _clickVolume = 0.35;     // default click volume

/**
 * Create a short click sound (high-pitched tick).
 * @param {number} when - AudioContext time to play
 * @param {boolean} [accent=false] - louder accent on beat 1
 */
function _scheduleClick(when, accent = false) {
  const ac = getContext();
  if (!_clickGain) {
    _clickGain = ac.createGain();
    _clickGain.connect(ac.destination);
  }
  _clickGain.gain.value = _clickVolume;

  const osc = ac.createOscillator();
  const env = ac.createGain();
  osc.type = 'sine';
  osc.frequency.value = accent ? 1200 : 880;
  env.gain.setValueAtTime(accent ? 0.6 : 0.4, when);
  env.gain.exponentialRampToValueAtTime(0.001, when + 0.04);
  osc.connect(env);
  env.connect(_clickGain);
  osc.start(when);
  osc.stop(when + 0.05);
}

/**
 * Start the click track scheduler.
 * Schedules clicks ahead using the Web Audio API clock for sample-accurate timing.
 */
function _clickScheduler() {
  if (!_clickEnabled || _clickBpm <= 0 || !playing) return;
  const ac = getContext();
  const beatInterval = 60.0 / _clickBpm;

  while (_clickNextBeat < ac.currentTime + _clickLookahead) {
    if (_clickNextBeat >= ac.currentTime - 0.01) {
      _scheduleClick(_clickNextBeat);
    }
    _clickNextBeat += beatInterval;
  }
  _clickTimerId = setTimeout(_clickScheduler, _clickInterval);
}

/**
 * Start click track from a given audio position.
 * @param {number} audioOffset - current position in audio (seconds)
 */
export function startClick(audioOffset) {
  if (!_clickEnabled || _clickBpm <= 0) return;
  const ac = getContext();
  const beatInterval = 60.0 / _clickBpm;

  // Calculate time of the next beat relative to audio position
  const beatsElapsed = audioOffset / beatInterval;
  const nextBeatNum = Math.ceil(beatsElapsed);
  const nextBeatAudioTime = nextBeatNum * beatInterval;
  const deltaFromNow = (nextBeatAudioTime - audioOffset) / _playbackRate;

  _clickNextBeat = ac.currentTime + deltaFromNow;
  if (_clickTimerId) clearTimeout(_clickTimerId);
  _clickScheduler();
}

/**
 * Stop the click track scheduler.
 */
export function stopClick() {
  if (_clickTimerId) {
    clearTimeout(_clickTimerId);
    _clickTimerId = null;
  }
}

/**
 * Enable or disable click track.
 * @param {boolean} enabled
 */
export function setClickEnabled(enabled) {
  _clickEnabled = enabled;
  if (!enabled) stopClick();
}

/**
 * Is click track enabled?
 * @returns {boolean}
 */
export function isClickEnabled() {
  return _clickEnabled;
}

/**
 * Set the BPM for the click track.
 * @param {number} bpm
 */
export function setClickBpm(bpm) {
  _clickBpm = bpm > 0 ? bpm : 0;
}

/**
 * Set click volume (0.0 - 1.0).
 * @param {number} vol
 */
export function setClickVolume(vol) {
  _clickVolume = Math.max(0, Math.min(1, vol));
  if (_clickGain) _clickGain.gain.value = _clickVolume;
}
