// Life on top of the mouth: blinks, gaze with saccades, head motion, nods, brows, breathing, a soft smile.
// Two modes: 'speaking' (more head motion, follows the mouth's energy, looks away at phrase starts) and
// 'listening' (mostly eye contact, micro-saccades, slow nods, a slight tilt and smile). Deterministic per seed.

const DEG = Math.PI / 180;

function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

// smooth noise in [-1, 1] from incommensurate sines
const noise = (t, a) => (Math.sin(t * 1.0 + a) * 0.5 + Math.sin(t * 2.37 + a * 1.7) * 0.3 + Math.sin(t * 4.13 + a * 2.9) * 0.2);
const ease = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u));

export class Idle {
  constructor(seed = 7) {
    this.r = rng(seed);
    this.mode = 'listening';
    this.t = 0;
    this.nextBlink = 1.2;
    this.blinkAt = -10;
    this.double = false;
    this.gaze = [0, 0]; this.gazeFrom = [0, 0]; this.gazeTo = [0, 0]; this.gazeAt = -1; this.nextGaze = 0.6;
    this.nextNod = 2.5; this.nodAt = -10; this.nodAmp = 0;
    this.energy = 0; this.lastSpeech = -10; this.browAt = -10;
    this.smile = 0.25;
  }

  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    if (mode === 'speaking') this.lookAway(0.45, 0.8);
  }

  lookAway(amp, hold) {
    const r = this.r;
    this.saccade([(r() * 2 - 1) * amp, -(0.15 + r() * 0.35) * amp]);
    this.nextGaze = this.t + hold;
  }

  saccade(to) {
    this.gazeFrom = [...this.gaze];
    this.gazeTo = to;
    this.gazeAt = this.t;
  }

  /** dt in s, open = current mouth opening (0..1). Returns the non-mouth part of the puppet state. */
  step(dt, open = 0) {
    const r = this.r, t = (this.t += dt), speaking = this.mode === 'speaking';
    // blink: 70 ms close, 40 ms hold, 110 ms open; sometimes twice
    if (t >= this.nextBlink) {
      this.blinkAt = t;
      this.double = r() < 0.15;
      this.nextBlink = t + (speaking ? 1.8 + r() * 3.2 : 2.4 + r() * 3.6) + (this.double ? 0.3 : 0);
    }
    const bt = (x) => (x < 0 ? 0 : x < 0.07 ? ease(x / 0.07) : x < 0.11 ? 1 : x < 0.22 ? 1 - ease((x - 0.11) / 0.11) : 0);
    let blink = bt(t - this.blinkAt);
    if (this.double) blink = Math.max(blink, bt(t - this.blinkAt - 0.28));
    // gaze: saccades of ~50 ms; listening holds eye contact with micro-saccades, speaking looks away at phrase starts
    if (t >= this.nextGaze) {
      if (speaking) {
        if (r() < 0.35) this.lookAway(0.5, 0.5 + r() * 0.7);
        else { this.saccade([(r() * 2 - 1) * 0.12, (r() * 2 - 1) * 0.08]); this.nextGaze = t + 0.8 + r() * 1.8; }
      } else if (r() < 0.12) this.lookAway(0.55, 0.6 + r() * 0.5);
      else { this.saccade([(r() * 2 - 1) * 0.1, (r() * 2 - 1) * 0.07]); this.nextGaze = t + 0.7 + r() * 2.2; }
    }
    const gu = ease((t - this.gazeAt) / 0.05);
    this.gaze = [this.gazeFrom[0] + (this.gazeTo[0] - this.gazeFrom[0]) * gu, this.gazeFrom[1] + (this.gazeTo[1] - this.gazeFrom[1]) * gu];
    // speech energy (smoothed opening) drives emphasis: small nods and brow lifts on phrase onsets
    const e0 = this.energy;
    this.energy += (open - this.energy) * (1 - Math.exp(-dt / 0.18));
    if (open > 0.25) {
      if (t - this.lastSpeech > 0.35 && speaking) this.browAt = t;
      this.lastSpeech = t;
    }
    // listening nods
    if (!speaking && t >= this.nextNod) {
      this.nodAt = t; this.nodAmp = 2 + r() * 2;
      this.nextNod = t + 3.5 + r() * 4;
    } else if (speaking && t >= this.nextNod) this.nextNod = t + 1;
    const nu = (t - this.nodAt) / 0.75;
    const nod = nu > 0 && nu < 1 ? Math.sin(nu * Math.PI) * (1 - 0.35 * nu) * this.nodAmp : 0;
    const amp = speaking ? 1.6 : 1;
    const head = {
      yaw: (noise(t * 0.23, 1.3) * 2.0 * amp + this.gaze[0] * 2.5) * DEG,
      pitch: (noise(t * 0.31, 4.1) * 1.2 * amp + nod + (speaking ? this.energy * 2.2 + (this.energy - e0) * 20 : 0) - this.gaze[1] * 1.5) * DEG,
      roll: (noise(t * 0.19, 2.7) * 1.3 * amp + (speaking ? 0 : 1.6)) * DEG,
      tx: noise(t * 0.17, 5.5) * 2.0, ty: 0,
    };
    const bu = (t - this.browAt) / 0.7;
    const brow = (bu > 0 && bu < 1 ? Math.sin(bu * Math.PI) * 0.7 : 0) + (speaking ? 0 : 0.1 + 0.1 * noise(t * 0.11, 8));
    this.smile += ((speaking ? 0.12 : 0.32 + 0.12 * noise(t * 0.07, 3)) - this.smile) * (1 - Math.exp(-dt / 0.8));
    return { blink: [blink, blink], gaze: this.gaze, head, brow, smile: this.smile, breath: Math.sin(t * 2 * Math.PI / 4.2) };
  }
}
