// An AnalyserNode for Node, following the Web Audio spec (section "AnalyserNode: FFT windowing and smoothing"):
// Blackman window, |FFT| / N, temporal smoothing per call, dB, then bytes between minDecibels and maxDecibels.
// It lets lipsync-engine's FrequencyAnalyzer (vendor/, unchanged) run offline on decoded PCM: set `pos` to the
// sample the browser's audio thread would have reached, then call analyze().

export class OfflineAnalyser {
  constructor(samples, sampleRate) {
    this.x = samples;
    this.sampleRate = sampleRate;
    this.pos = 0;
    this.minDecibels = -100;
    this.maxDecibels = -30;
    this.smoothingTimeConstant = 0.8;
    this.fftSize = 2048;
  }
  set fftSize(n) {
    this._n = n;
    this._prev = new Float64Array(n / 2);
    this._win = new Float64Array(n);
    for (let i = 0; i < n; i++) this._win[i] = 0.42 - 0.5 * Math.cos((2 * Math.PI * i) / n) + 0.08 * Math.cos((4 * Math.PI * i) / n);
  }
  get fftSize() { return this._n; }
  get frequencyBinCount() { return this._n / 2; }

  _frame() {
    const n = this._n, out = new Float64Array(n), start = this.pos - n;
    for (let i = 0; i < n; i++) { const j = start + i; out[i] = j >= 0 && j < this.x.length ? this.x[j] : 0; }
    return out;
  }
  getByteTimeDomainData(arr) {
    const f = this._frame();
    for (let i = 0; i < arr.length && i < f.length; i++) arr[i] = Math.max(0, Math.min(255, Math.floor(128 * (1 + f[i]))));
  }
  getByteFrequencyData(arr) {
    const n = this._n, f = this._frame(), re = new Float64Array(n), im = new Float64Array(n);
    for (let i = 0; i < n; i++) re[i] = f[i] * this._win[i];
    fft(re, im);
    const tau = this.smoothingTimeConstant, range = this.maxDecibels - this.minDecibels;
    for (let k = 0; k < n / 2; k++) {
      const mag = Math.hypot(re[k], im[k]) / n;
      this._prev[k] = tau * this._prev[k] + (1 - tau) * mag;
      const db = 20 * Math.log10(this._prev[k] || 1e-20);
      if (k < arr.length) arr[k] = Math.max(0, Math.min(255, Math.floor((255 / range) * (db - this.minDecibels))));
    }
  }
}

// In-place radix-2 FFT.
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len, wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = a + len / 2;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}
