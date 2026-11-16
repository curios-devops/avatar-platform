// How each method's raw output becomes viseme weights. Shared by mouth-driver.js (browser) and offline.mjs (Node)
// so both measure the same thing.

// lipsync-engine defaults (vendor/lipsync-engine/core/LipSyncEngine.js), passed explicitly.
export const ENGINE_OPTIONS = { fftSize: 256, silenceThreshold: 0.015, smoothingFactor: 0.35, holdFrames: 2, intensitySmoothing: 0.2, energySmoothing: 0.5 };

/**
 * B: the engine reports one viseme per frame plus an intensity (3 x smoothed RMS). We show that viseme, scaled by
 * the intensity so a quiet "aa" does not open the jaw fully (its own SVG renderer scales by the shape instead).
 */
export function engineWeights(frame) {
  if (!frame || frame.viseme === 'sil') return { sil: 1 };
  return { [frame.viseme]: Math.min(1, 0.4 + frame.intensity) };
}

// H: HeadAudio (met4citizen, MIT, vendor/headaudio/). The worklet classifies MFCC frames into 15 visemes; the node's
// main-thread half holds each viseme >= visemeMinMs and ramps blend values over visemeRampMs with a sigmoid, capped
// at visemeMaxs. We divide by the cap so a fully active viseme is weight 1, like the other methods.
export const HA_NAMES = ['aa', 'E', 'I', 'O', 'U', 'PP', 'SS', 'TH', 'DD', 'FF', 'kk', 'nn', 'RR', 'CH', 'sil'];
export const HA_MAXS = [0.65, 0.65, 0.65, 0.65, 0.65, 0.75, 0.65, 0.65, 0.65, 0.75, 0.65, 0.65, 0.65, 0.65, 0.65];

/** From the node's onvalue('viseme_xx', v) values to weights. */
export function headAudioWeights(values) {
  const w = {};
  HA_NAMES.forEach((n, i) => { const v = values[`viseme_${n}`]; if (v > 0 && n !== 'sil') w[n] = Math.min(1, v / HA_MAXS[i]); });
  return Object.keys(w).length ? w : { sil: 1 };
}

/** The node's hold + ramp logic (vendor/headaudio/dist/headaudio.min.mjs, update()), reproduced to run in Node. */
export class HeadAudioRamp {
  constructor({ minMs = 120, rampMs = 100, k = 5 } = {}) {
    this.minMs = minMs; this.rampMs = rampMs;
    const base = (t) => 1 / (1 + Math.exp(-k * t)) - 0.5, corr = 0.5 / base(1);
    this.ease = (t) => corr * base(2 * Math.max(Math.min(t, 1), 0) - 1) + 0.5;
    this.alphas = new Array(15).fill(0); this.active = -1; this.since = -1e9;
  }
  viseme(idx, nowMs) { // a 'viseme' message from the worklet
    const next = idx === 14 ? -1 : idx;
    if (next !== this.active && nowMs - this.since >= this.minMs) { this.active = next; this.since = nowMs; }
  }
  ended() { this.active = -1; this.since = 0; }
  update(dtMs) {
    const da = dtMs / this.rampMs, values = {};
    for (let i = 0; i < 15; i++) {
      let a = this.alphas[i];
      if (i === this.active) { if (a < 1) { a += da; if (a > 0.99) a = 1; } } else if (a > 0) { a -= da; if (a < 0.01) a = 0; }
      this.alphas[i] = a;
      values[`viseme_${HA_NAMES[i]}`] = HA_MAXS[i] * this.ease(a);
    }
    return values;
  }
}
