/**
 * LipSyncEngine — Main orchestrator for streaming lip-sync.
 *
 * Manages the full audio pipeline:
 *   AudioSource → AudioWorklet → AnalyserNode → FrequencyAnalyzer → Events
 *
 * Supports three input modes:
 *   1. Streaming PCM chunks (from TTS APIs like OpenAI Realtime, ElevenLabs)
 *   2. MediaStream (microphone, WebRTC)
 *   3. HTMLMediaElement (audio/video element)
 *
 * @module LipSyncEngine
 *
 * @example
 *   import { LipSyncEngine } from '@beer-digital/lipsync-engine';
 *
 *   const engine = new LipSyncEngine({ sampleRate: 24000 });
 *   await engine.init();
 *
 *   engine.on('viseme', (frame) => {
 *     updateAvatar(frame.viseme, frame.intensity, frame.shape);
 *   });
 *
 *   // Feed PCM chunks from TTS
 *   ws.onmessage = (e) => {
 *     const data = JSON.parse(e.data);
 *     if (data.type === 'audio') {
 *       engine.feedAudio(base64ToInt16(data.audio));
 *     }
 *   };
 */

import { EventEmitter } from '../utils/EventEmitter.js';
import { FrequencyAnalyzer } from '../analyzers/FrequencyAnalyzer.js';
import { int16ToFloat32, resample } from '../utils/audio-utils.js';

/** @type {Object} Default engine options. */
const DEFAULTS = {
  // Audio pipeline
  sampleRate: 24000,           // Expected input sample rate
  fftSize: 256,                // FFT window size (power of 2)
  analyserSmoothing: 0.5,      // AnalyserNode smoothingTimeConstant

  // Viseme detection
  silenceThreshold: 0.015,     // RMS below this = silence
  smoothingFactor: 0.35,       // Viseme transition smoothing (0-1)
  holdFrames: 2,               // Min frames before viseme switch
  intensitySmoothing: 0.2,     // Intensity EMA factor

  // Playback
  volume: 1.0,
  startThresholdMs: 50,        // Buffer ms before auto-play
  bufferSeconds: 5,            // Ring buffer capacity

  // Analysis timing
  analysisMode: 'raf',         // 'raf' (requestAnimationFrame) or 'interval'
  analysisIntervalMs: 16,      // Only used when analysisMode = 'interval'

  // Worklet
  workletUrl: null,            // Custom worklet URL (auto-detected if null)
  disablePlayback: false,      // If true, analyze only (no audio output)
};

export class LipSyncEngine extends EventEmitter {
  /**
   * @param {Partial<typeof DEFAULTS>} options
   */
  constructor(options = {}) {
    super();
    this.opts = { ...DEFAULTS, ...options };

    /** @type {AudioContext|null} */
    this.audioContext = null;

    /** @type {AudioWorkletNode|null} */
    this.workletNode = null;

    /** @type {AnalyserNode|null} */
    this.analyserNode = null;

    /** @type {GainNode|null} */
    this.gainNode = null;

    /** @type {FrequencyAnalyzer|null} */
    this.analyzer = null;

    /** @type {MediaStreamAudioSourceNode|null} */
    this._mediaSource = null;

    /** @type {MediaElementAudioSourceNode|null} */
    this._elementSource = null;

    // State
    this._initialized = false;
    this._analyzing = false;
    this._animFrameId = null;
    this._intervalId = null;
    this._inputMode = null; // 'stream' | 'media' | 'element'
    this._playbackTimeMs = 0;
    this._bufferLevel = 0;
    this._destroyed = false;
  }

  // ════════════════════════════════════════════════════════════════
  //  INITIALIZATION
  // ════════════════════════════════════════════════════════════════

  /**
   * Initialize the audio pipeline. Must be called after a user gesture (browser policy).
   * @param {AudioContext} [existingContext] - Optionally reuse an existing AudioContext.
   * @returns {Promise<void>}
   */
  async init(existingContext) {
    if (this._initialized) return;
    if (this._destroyed) throw new Error('Engine has been destroyed');

    // Create or reuse AudioContext
    this.audioContext = existingContext || new AudioContext({
      sampleRate: this.opts.sampleRate,
    });

    // Resume if suspended (browser autoplay policy)
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    // Load AudioWorklet
    const workletUrl = this.opts.workletUrl || this._resolveWorkletUrl();
    await this.audioContext.audioWorklet.addModule(workletUrl);

    // Create worklet node
    this.workletNode = new AudioWorkletNode(
      this.audioContext,
      'streaming-processor',
      {
        processorOptions: {
          sampleRate: this.opts.sampleRate,
          bufferSeconds: this.opts.bufferSeconds,
          startThresholdMs: this.opts.startThresholdMs,
        },
      }
    );

    // Create analyser
    this.analyserNode = this.audioContext.createAnalyser();
    this.analyserNode.fftSize = this.opts.fftSize;
    this.analyserNode.smoothingTimeConstant = this.opts.analyserSmoothing;

    // Create gain node
    this.gainNode = this.audioContext.createGain();
    this.gainNode.gain.value = this.opts.volume;

    // Connect pipeline: Worklet → Analyser → Gain → Destination
    this.workletNode.connect(this.analyserNode);
    if (!this.opts.disablePlayback) {
      this.analyserNode.connect(this.gainNode);
      this.gainNode.connect(this.audioContext.destination);
    }

    // Create frequency analyzer
    this.analyzer = new FrequencyAnalyzer(
      this.analyserNode,
      this.audioContext.sampleRate,
      {
        fftSize: this.opts.fftSize,
        silenceThreshold: this.opts.silenceThreshold,
        smoothingFactor: this.opts.smoothingFactor,
        holdFrames: this.opts.holdFrames,
        intensitySmoothing: this.opts.intensitySmoothing,
      }
    );

    // Listen for worklet messages
    this.workletNode.port.onmessage = (e) => this._onWorkletMessage(e.data);

    this._initialized = true;
    this._inputMode = 'stream';
    this.emit('initialized');
  }

  /**
   * Try to resolve the worklet URL automatically.
   * @private
   */
  _resolveWorkletUrl() {
    // Try common locations
    const candidates = [
      './streaming-processor.js',
      './worklet/streaming-processor.js',
      './dist/worklet/streaming-processor.js',
      '/streaming-processor.js',
    ];

    // If running from npm package, try node_modules path
    // The consumer should ideally provide workletUrl explicitly
    return candidates[0];
  }

  // ════════════════════════════════════════════════════════════════
  //  INPUT SOURCES
  // ════════════════════════════════════════════════════════════════

  /**
   * Feed PCM audio chunks for streaming playback + analysis.
   * This is the primary method for TTS API integration.
   *
   * @param {Int16Array|Float32Array|ArrayBuffer} samples - Audio samples.
   * @param {number} [inputSampleRate] - Override sample rate for this chunk.
   */
  feedAudio(samples, inputSampleRate) {
    this._ensureInitialized();

    let float32;

    if (samples instanceof Int16Array) {
      float32 = int16ToFloat32(samples);
    } else if (samples instanceof Float32Array) {
      float32 = samples;
    } else if (samples instanceof ArrayBuffer) {
      // Assume Int16 PCM
      float32 = int16ToFloat32(new Int16Array(samples));
    } else if (ArrayBuffer.isView(samples)) {
      float32 = int16ToFloat32(new Int16Array(samples.buffer));
    } else {
      throw new TypeError('feedAudio expects Int16Array, Float32Array, or ArrayBuffer');
    }

    // Resample if needed
    const srcRate = inputSampleRate || this.opts.sampleRate;
    if (srcRate !== this.audioContext.sampleRate) {
      float32 = resample(float32, srcRate, this.audioContext.sampleRate);
    }

    // Send to worklet
    this.workletNode.port.postMessage(
      { type: 'audio', samples: float32 },
      [float32.buffer] // Transfer ownership for zero-copy
    );
  }

  /**
   * Attach a MediaStream (e.g., microphone) for analysis.
   * Audio is analyzed but NOT played back (to avoid feedback).
   *
   * @param {MediaStream} stream
   */
  attachStream(stream) {
    this._ensureInitialized();
    this._disconnectSources();

    this._mediaSource = this.audioContext.createMediaStreamSource(stream);
    this._mediaSource.connect(this.analyserNode);
    // Don't connect to destination (feedback prevention)

    this._inputMode = 'media';
    this.emit('sourceAttached', { type: 'stream' });
  }

  /**
   * Attach an HTML audio/video element for analysis.
   *
   * @param {HTMLMediaElement} element
   */
  attachElement(element) {
    this._ensureInitialized();
    this._disconnectSources();

    this._elementSource = this.audioContext.createMediaElementSource(element);
    this._elementSource.connect(this.analyserNode);
    this.analyserNode.connect(this.audioContext.destination);

    this._inputMode = 'element';
    this.emit('sourceAttached', { type: 'element' });
  }

  /**
   * Disconnect any attached media sources.
   * @private
   */
  _disconnectSources() {
    if (this._mediaSource) {
      try { this._mediaSource.disconnect(); } catch {}
      this._mediaSource = null;
    }
    if (this._elementSource) {
      try { this._elementSource.disconnect(); } catch {}
      this._elementSource = null;
    }
  }

  // ════════════════════════════════════════════════════════════════
  //  ANALYSIS LOOP
  // ════════════════════════════════════════════════════════════════

  /**
   * Start the viseme analysis loop.
   * Emits 'viseme' events at the configured rate.
   */
  startAnalysis() {
    if (this._analyzing) return;
    this._ensureInitialized();
    this._analyzing = true;

    if (this.opts.analysisMode === 'raf') {
      this._startRAFLoop();
    } else {
      this._startIntervalLoop();
    }

    this.emit('analysisStarted');
  }

  /** Stop the viseme analysis loop. */
  stopAnalysis() {
    this._analyzing = false;

    if (this._animFrameId !== null) {
      cancelAnimationFrame(this._animFrameId);
      this._animFrameId = null;
    }
    if (this._intervalId !== null) {
      clearInterval(this._intervalId);
      this._intervalId = null;
    }

    this.emit('analysisStopped');
  }

  /** @private */
  _startRAFLoop() {
    const tick = () => {
      if (!this._analyzing) return;
      this._analyzeFrame();
      this._animFrameId = requestAnimationFrame(tick);
    };
    this._animFrameId = requestAnimationFrame(tick);
  }

  /** @private */
  _startIntervalLoop() {
    this._intervalId = setInterval(() => {
      if (!this._analyzing) return;
      this._analyzeFrame();
    }, this.opts.analysisIntervalMs);
  }

  /** @private */
  _analyzeFrame() {
    const frame = this.analyzer.analyze();
    frame.timeMs = this._playbackTimeMs;
    frame.bufferLevel = this._bufferLevel;
    this.emit('viseme', frame);
  }

  // ════════════════════════════════════════════════════════════════
  //  WORKLET COMMUNICATION
  // ════════════════════════════════════════════════════════════════

  /** @private */
  _onWorkletMessage(data) {
    switch (data.type) {
      case 'position':
        this._playbackTimeMs = data.timeMs;
        this._bufferLevel = data.bufferLevel;
        this.emit('position', {
          timeMs: data.timeMs,
          bufferLevel: data.bufferLevel,
          bufferMs: data.bufferMs,
          isPlaying: data.isPlaying,
        });
        break;

      case 'playbackStarted':
        this.emit('playbackStarted');
        break;

      case 'playbackEnded':
        this.emit('playbackEnded');
        break;

      case 'bufferUnderrun':
        this.emit('bufferUnderrun', { timeMs: data.timeMs });
        break;

      case 'bufferOverflow':
        this.emit('bufferOverflow', { dropped: data.dropped });
        break;

      case 'ready':
        this.emit('workletReady');
        break;
    }
  }

  // ════════════════════════════════════════════════════════════════
  //  CONTROLS
  // ════════════════════════════════════════════════════════════════

  /**
   * Set playback volume.
   * @param {number} value - Volume [0, 1].
   */
  setVolume(value) {
    const v = Math.max(0, Math.min(1, value));
    if (this.gainNode) {
      this.gainNode.gain.setTargetAtTime(v, this.audioContext.currentTime, 0.02);
    }
    this.workletNode?.port.postMessage({ type: 'setVolume', value: v });
  }

  /** Clear the audio buffer (stops playback of buffered audio). */
  clearBuffer() {
    this.workletNode?.port.postMessage({ type: 'clear' });
  }

  /** Start playback (if paused). */
  play() {
    this.workletNode?.port.postMessage({ type: 'start' });
  }

  /** Pause playback. */
  pause() {
    this.workletNode?.port.postMessage({ type: 'stop' });
  }

  /** Reset all state (buffer, position, analyzer). */
  reset() {
    this.workletNode?.port.postMessage({ type: 'reset' });
    this.analyzer?.reset();
    this._playbackTimeMs = 0;
    this._bufferLevel = 0;
    this.emit('reset');
  }

  // ════════════════════════════════════════════════════════════════
  //  STATE QUERIES
  // ════════════════════════════════════════════════════════════════

  /** Whether the engine has been initialized. */
  get initialized() { return this._initialized; }

  /** Whether analysis is currently running. */
  get analyzing() { return this._analyzing; }

  /** Current playback position in milliseconds. */
  get playbackTimeMs() { return this._playbackTimeMs; }

  /** Current buffer fill level (0..1). */
  get bufferLevel() { return this._bufferLevel; }

  /** Current input mode: 'stream', 'media', or 'element'. */
  get inputMode() { return this._inputMode; }

  /**
   * Get a snapshot of current engine state.
   * @returns {Object}
   */
  getState() {
    return {
      initialized: this._initialized,
      analyzing: this._analyzing,
      inputMode: this._inputMode,
      playbackTimeMs: this._playbackTimeMs,
      bufferLevel: this._bufferLevel,
      sampleRate: this.audioContext?.sampleRate,
      volume: this.gainNode?.gain.value,
    };
  }

  // ════════════════════════════════════════════════════════════════
  //  LIFECYCLE
  // ════════════════════════════════════════════════════════════════

  /**
   * Destroy the engine and release all resources.
   */
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;

    this.stopAnalysis();
    this._disconnectSources();

    try { this.workletNode?.disconnect(); } catch {}
    try { this.analyserNode?.disconnect(); } catch {}
    try { this.gainNode?.disconnect(); } catch {}

    // Only close context if we created it
    if (this.audioContext?.state !== 'closed') {
      this.audioContext?.close().catch(() => {});
    }

    this.workletNode = null;
    this.analyserNode = null;
    this.gainNode = null;
    this.analyzer = null;
    this.audioContext = null;
    this._initialized = false;

    this.removeAllListeners();
    this.emit('destroyed');
  }

  /** @private */
  _ensureInitialized() {
    if (!this._initialized) {
      throw new Error('LipSyncEngine not initialized. Call init() first.');
    }
  }
}
