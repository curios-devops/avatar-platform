// One interface for every way of moving a mouth, so the same driver can move the 2D face here, the three.js human
// (avatar-platform-human) or any other arena candidate. It knows nothing about drawing: it emits viseme weights and
// a pose (open, width, round, press, tuck, tongue, teeth; see lib/visemes.js).
//
//   const d = createMouthDriver({ method: 'text', context, cues, clock });   // or 'amplitude' | 'engine'
//   d.onViseme((f) => face.render(f.pose));       // f = {viseme, weights, pose, t, costMs}
//   await d.start(audioNode | mediaStream);        // 'text' only needs the clock; a node is optional
//   d.setCues(cues)                                // text: replace the timeline (live mode: it grows per chunk)
//   d.stop();
//
// method 'amplitude'  RMS in an AudioWorklet (lib/rms-worklet.js) -> jaw only
// method 'engine'     lipsync-engine's FrequencyAnalyzer (vendor/, unchanged) on an AnalyserNode, main thread
// method 'headaudio' HeadAudio (met4citizen, vendor/headaudio/): MFCC + trained prototypes in an AudioWorklet
// method 'text'       viseme cues from TTS character timestamps (lib/g2v.js), looked up on `clock()`
//
// clock(): seconds of the clip that are AUDIBLE now. Analyser methods read the audio graph, which runs ahead of the
// speaker by the output latency; the text method follows whatever clock it is given, so give it the audible one.
// For the three.js human, map ids with TO_HUMAN (I/O/U -> ih/oh/ou) and feed weights into VISEME_TO_ARKIT.

import { FrequencyAnalyzer } from './vendor/lipsync-engine/analyzers/FrequencyAnalyzer.js';
import { AmplitudeMouth } from './lib/amplitude.js';
import { sampleCues } from './lib/g2v.js';
import { blendPose, dominant, PoseSmoother, TO_HUMAN } from './lib/visemes.js';
import { engineWeights, ENGINE_OPTIONS, headAudioWeights } from './lib/methods.js';

export { TO_HUMAN };

const loaded = new WeakMap();
async function addWorklet(ctx, file) {
  const set = loaded.get(ctx) || new Set();
  loaded.set(ctx, set);
  if (!set.has(file)) { await ctx.audioWorklet.addModule(new URL(file, import.meta.url)); set.add(file); }
}

export class MouthDriver {
  constructor({ method, context, cues = [], clock = null, leadMs = 0, inputGainDb = 0, loop = true, smoothing } = {}) {
    if (!['amplitude', 'engine', 'headaudio', 'text'].includes(method)) throw new Error(`unknown method ${method}`);
    this.method = method;
    this.ctx = context;
    this.cues = cues;
    this.clock = clock;
    this.leadMs = leadMs;
    this.inputGainDb = inputGainDb;
    this.loop = loop;
    this.smoother = new PoseSmoother(smoothing);
    this.listeners = new Set();
    this.nodes = [];
    this.running = false;
    this.inWorklet = method === 'amplitude' || method === 'headaudio';
    this._stats = { costs: [], changes: [], frames: [], last: 'sil' };
  }

  onViseme(cb) { this.listeners.add(cb); return () => this.listeners.delete(cb); }
  setCues(cues) { this.cues = cues; }

  async start(source) {
    const ctx = this.ctx;
    if (source instanceof MediaStream) { source = ctx.createMediaStreamSource(source); this.nodes.push(source); }
    const sink = ctx.createGain();
    sink.gain.value = 0;
    sink.connect(ctx.destination); // keeps analysis nodes pulled without making them audible
    this.nodes.push(sink);
    if (this.method === 'amplitude') {
      await addWorklet(ctx, './lib/rms-worklet.js');
      const meter = new AudioWorkletNode(ctx, 'rms-meter', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      this.amp = new AmplitudeMouth();
      this._rms = 0;
      meter.port.onmessage = (e) => { this._rms = e.data.rms; };
      source.connect(meter);
      this._tap = [source, meter];
      meter.connect(sink);
      this.nodes.push(meter);
    } else if (this.method === 'engine') {
      const gain = ctx.createGain();
      gain.gain.value = Math.pow(10, this.inputGainDb / 20);
      const analyser = ctx.createAnalyser();
      source.connect(gain);
      this._tap = [source, gain];
      gain.connect(analyser);
      analyser.connect(sink);
      this.nodes.push(gain, analyser);
      this.analyzer = new FrequencyAnalyzer(analyser, ctx.sampleRate, ENGINE_OPTIONS);
    } else if (this.method === 'headaudio') {
      await addWorklet(ctx, './vendor/headaudio/dist/headworklet.min.mjs');
      const { HeadAudio } = await import('./vendor/headaudio/dist/headaudio.min.mjs');
      const node = new HeadAudio(ctx, {});
      await node.loadModel(new URL('./vendor/headaudio/dist/model-en-mixed.bin', import.meta.url).href);
      this._ha = {};
      node.onvalue = (k, v) => { this._ha[k] = v; };
      source.connect(node);
      this._tap = [source, node];
      this.nodes.push(node);
      this.ha = node;
    }
    if (!this.clock) { const t0 = ctx.currentTime; this.clock = () => ctx.currentTime - t0; }
    this.running = true;
    this._prev = performance.now();
    if (this.loop) {
      const tick = () => { if (!this.running) return; this.update(); this._raf = requestAnimationFrame(tick); };
      this._raf = requestAnimationFrame(tick);
    }
  }

  /** One frame: read the method's input, blend, smooth, emit. Call it yourself when created with loop: false. */
  update(now = performance.now()) {
    const dt = Math.min(0.1, Math.max(0.001, (now - this._prev) / 1000));
    this._prev = now;
    const c0 = performance.now();
    let weights;
    if (this.method === 'amplitude') weights = this.amp.update(this._rms, dt);
    else if (this.method === 'engine') weights = engineWeights(this.analyzer.analyze());
    else if (this.method === 'headaudio') { this.ha.update(dt * 1000); weights = headAudioWeights(this._ha); }
    else weights = sampleCues(this.cues, this.clock() + this.leadMs / 1000);
    const pose = { ...this.smoother.step(blendPose(weights), dt) };
    const viseme = dominant(weights);
    const costMs = performance.now() - c0;
    const s = this._stats;
    s.costs.push(costMs); if (s.costs.length > 600) s.costs.shift();
    s.frames.push(now); while (s.frames.length && now - s.frames[0] > 1000) s.frames.shift();
    if (viseme !== s.last) { s.changes.push(now); s.last = viseme; }
    while (s.changes.length && now - s.changes[0] > 2000) s.changes.shift();
    const frame = { method: this.method, t: this.clock(), viseme, weights, pose, costMs };
    for (const cb of this.listeners) cb(frame);
    return frame;
  }

  /** Live numbers: viseme changes per second (last 2 s), main-thread cost per frame (ms), frames per second. */
  stats() {
    const c = [...this._stats.costs].sort((a, b) => a - b);
    return {
      eventsPerS: this._stats.changes.length / 2,
      costMeanMs: c.reduce((a, b) => a + b, 0) / Math.max(1, c.length),
      costP95Ms: c[Math.floor(c.length * 0.95)] ?? 0,
      fps: this._stats.frames.length,
      inWorklet: this.inWorklet,
    };
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this._raf);
    if (this._tap) { try { this._tap[0].disconnect(this._tap[1]); } catch {} this._tap = null; }
    for (const n of this.nodes) { try { n.disconnect(); } catch {} }
    this.nodes = [];
    this.smoother.reset();
    this.analyzer?.reset();
  }
}

export function createMouthDriver(opts) { return new MouthDriver(opts); }
