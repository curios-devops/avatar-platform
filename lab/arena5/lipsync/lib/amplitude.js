// Method A: amplitude only. RMS of the last ~20 ms -> jaw opening. No shape information at all: the floor.
// Auto-gain (a slowly decaying peak) so a quiet voice and a loud one both use the full range.

export class AmplitudeMouth {
  constructor({ gate = 0.01, peakDecayS = 2.5, curve = 0.8 } = {}) {
    this.gate = gate;
    this.peakDecayS = peakDecayS;
    this.curve = curve;
    this.peak = 0.08;
  }
  /** rms: 0..1, dt: seconds since the last call. Returns weights for blendPose (only the jaw: aa). */
  update(rms, dt) {
    this.peak = Math.max(rms, this.peak * Math.exp(-dt / this.peakDecayS), 0.03);
    const x = (rms - this.gate) / (this.peak * 0.85 - this.gate);
    const open = Math.pow(Math.min(1, Math.max(0, x)), this.curve);
    return { aa: open };
  }
  reset() { this.peak = 0.08; }
}

export function rms(samples, from = 0, to = samples.length) {
  let s = 0;
  const a = Math.max(0, from), b = Math.min(samples.length, to);
  for (let i = a; i < b; i++) s += samples[i] * samples[i];
  return b > a ? Math.sqrt(s / (b - a)) : 0;
}
