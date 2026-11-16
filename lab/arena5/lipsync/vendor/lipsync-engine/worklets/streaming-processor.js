/**
 * StreamingProcessor — AudioWorkletProcessor for gapless streaming playback.
 *
 * This file runs in the AudioWorklet thread and MUST be self-contained
 * (no imports, no external dependencies).
 *
 * Features:
 *   - Lock-free ring buffer (configurable capacity, default 5s at 24 kHz)
 *   - Gapless playback from chunked PCM streams
 *   - Auto-start when initial buffer threshold is met
 *   - Precise sample-accurate playback position reporting
 *   - Buffer underrun detection + recovery
 *   - Fade-in/out to prevent clicks
 *   - Configurable via messages from main thread
 *
 * Message protocol (main → worklet):
 *   { type: 'audio',     samples: Float32Array }
 *   { type: 'config',    sampleRate?: number, bufferSeconds?: number, startThresholdMs?: number }
 *   { type: 'start' }
 *   { type: 'stop' }
 *   { type: 'clear' }
 *   { type: 'reset' }
 *   { type: 'setVolume', value: number }
 *
 * Message protocol (worklet → main):
 *   { type: 'ready' }
 *   { type: 'position',        timeMs, bufferLevel, isPlaying, bufferMs }
 *   { type: 'playbackStarted' }
 *   { type: 'playbackEnded' }
 *   { type: 'bufferUnderrun',  timeMs }
 *   { type: 'bufferOverflow',  dropped }
 *   { type: 'stats',           totalSamplesPlayed, totalSamplesReceived }
 */
class StreamingProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();

    // ── Configuration ────────────────────────────────────────────
    const opts = options?.processorOptions || {};
    this._sampleRate = opts.sampleRate || 24000;
    this._bufferSeconds = opts.bufferSeconds || 5;
    this._startThresholdMs = opts.startThresholdMs || 50;
    this._fadeFrames = opts.fadeFrames || 64; // click-free fade in/out

    // ── Ring buffer ──────────────────────────────────────────────
    this._capacity = Math.ceil(this._sampleRate * this._bufferSeconds);
    this._buffer = new Float32Array(this._capacity);
    this._readPtr = 0;
    this._writePtr = 0;
    this._available = 0;

    // ── Playback state ───────────────────────────────────────────
    this._isPlaying = false;
    this._autoStartPending = true; // wait for threshold before first play
    this._totalPlayed = 0;
    this._totalReceived = 0;
    this._volume = 1.0;
    this._fadeCounter = 0;
    this._fadingIn = false;
    this._fadingOut = false;

    // ── Reporting ────────────────────────────────────────────────
    this._reportInterval = 128; // samples between position reports
    this._samplesSinceReport = 0;

    // ── Message handling ─────────────────────────────────────────
    this.port.onmessage = (e) => this._handleMessage(e.data);
    this.port.postMessage({ type: 'ready' });
  }

  // ════════════════════════════════════════════════════════════════
  //  MESSAGE HANDLING
  // ════════════════════════════════════════════════════════════════

  _handleMessage(data) {
    switch (data.type) {
      case 'audio':
        this._enqueue(data.samples);
        break;

      case 'start':
        this._isPlaying = true;
        this._autoStartPending = false;
        this._startFadeIn();
        break;

      case 'stop':
        this._startFadeOut();
        break;

      case 'clear':
        this._clearBuffer();
        break;

      case 'reset':
        this._clearBuffer();
        this._totalPlayed = 0;
        this._totalReceived = 0;
        this._autoStartPending = true;
        this._isPlaying = false;
        break;

      case 'setVolume':
        this._volume = Math.max(0, Math.min(1, data.value));
        break;

      case 'config':
        if (data.sampleRate) this._sampleRate = data.sampleRate;
        if (data.startThresholdMs) this._startThresholdMs = data.startThresholdMs;
        break;
    }
  }

  // ════════════════════════════════════════════════════════════════
  //  BUFFER MANAGEMENT
  // ════════════════════════════════════════════════════════════════

  _enqueue(samples) {
    let dropped = 0;
    for (let i = 0; i < samples.length; i++) {
      if (this._available >= this._capacity) {
        // Overflow: drop oldest
        this._readPtr = (this._readPtr + 1) % this._capacity;
        dropped++;
      } else {
        this._available++;
      }
      this._buffer[this._writePtr] = samples[i];
      this._writePtr = (this._writePtr + 1) % this._capacity;
    }

    this._totalReceived += samples.length;

    if (dropped > 0) {
      this.port.postMessage({ type: 'bufferOverflow', dropped });
    }

    // Auto-start on first fill
    if (this._autoStartPending) {
      const bufferedMs = (this._available / this._sampleRate) * 1000;
      if (bufferedMs >= this._startThresholdMs) {
        this._autoStartPending = false;
        this._isPlaying = true;
        this._startFadeIn();
        this.port.postMessage({ type: 'playbackStarted' });
      }
    }
  }

  _clearBuffer() {
    this._readPtr = 0;
    this._writePtr = 0;
    this._available = 0;
  }

  // ════════════════════════════════════════════════════════════════
  //  FADE IN / OUT
  // ════════════════════════════════════════════════════════════════

  _startFadeIn() {
    this._fadingIn = true;
    this._fadingOut = false;
    this._fadeCounter = 0;
  }

  _startFadeOut() {
    this._fadingOut = true;
    this._fadingIn = false;
    this._fadeCounter = 0;
  }

  _getFadeGain() {
    if (this._fadingIn) {
      const t = Math.min(this._fadeCounter / this._fadeFrames, 1);
      if (t >= 1) this._fadingIn = false;
      this._fadeCounter++;
      return t * t; // ease-in (quadratic)
    }
    if (this._fadingOut) {
      const t = Math.min(this._fadeCounter / this._fadeFrames, 1);
      if (t >= 1) {
        this._fadingOut = false;
        this._isPlaying = false;
        this.port.postMessage({ type: 'playbackEnded' });
      }
      this._fadeCounter++;
      return (1 - t) * (1 - t); // ease-out
    }
    return 1;
  }

  // ════════════════════════════════════════════════════════════════
  //  AUDIO PROCESSING (called ~every 2.67ms for 128 samples)
  // ════════════════════════════════════════════════════════════════

  process(inputs, outputs) {
    const output = outputs[0];
    if (!output || output.length === 0) return true;

    const channel = output[0]; // mono output
    const blockSize = channel.length;

    if (!this._isPlaying) {
      // Output silence
      channel.fill(0);
      return true;
    }

    let underrun = false;

    for (let i = 0; i < blockSize; i++) {
      if (this._available > 0) {
        const sample = this._buffer[this._readPtr];
        this._readPtr = (this._readPtr + 1) % this._capacity;
        this._available--;
        this._totalPlayed++;

        const fadeGain = this._getFadeGain();
        channel[i] = sample * this._volume * fadeGain;
      } else {
        // Buffer underrun
        channel[i] = 0;
        if (!underrun) {
          underrun = true;
          this.port.postMessage({
            type: 'bufferUnderrun',
            timeMs: (this._totalPlayed / this._sampleRate) * 1000
          });
        }
      }
    }

    // Copy mono to other channels if present
    for (let ch = 1; ch < output.length; ch++) {
      output[ch].set(channel);
    }

    // Report position periodically
    this._samplesSinceReport += blockSize;
    if (this._samplesSinceReport >= this._reportInterval) {
      this._samplesSinceReport = 0;
      this.port.postMessage({
        type: 'position',
        timeMs: (this._totalPlayed / this._sampleRate) * 1000,
        bufferLevel: this._available / this._capacity,
        bufferMs: (this._available / this._sampleRate) * 1000,
        isPlaying: this._isPlaying,
      });
    }

    return true; // keep processor alive
  }
}

registerProcessor('streaming-processor', StreamingProcessor);
