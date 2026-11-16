// The 15 Oculus visemes, a mouth pose for each, and the blending every method shares.
// Pure ES module: runs in the browser and in Node. Renderer-agnostic: a pose is a few numbers, not a drawing.
//
//   open    gap between the lips, 0..1        width   mouth width, 0.5 = rest
//   round   pucker / lips forward, 0..1       press   lips pressed together (P, B, M)
//   tuck    lower lip under the upper teeth   tongue  tongue tip visible
//   teeth   upper teeth visible
//
// The three.js human (avatar-platform-human, frontend/src/human/visemes.ts) uses the same set with lower-case
// ih / oh / ou for I / O / U; TO_HUMAN maps ours to its names so the driver can move it unchanged.

export const VISEMES = ['sil', 'PP', 'FF', 'TH', 'DD', 'kk', 'CH', 'SS', 'nn', 'RR', 'aa', 'E', 'I', 'O', 'U'];

const P = (open, width, round = 0, extra = {}) => ({ open, width, round, press: 0, tuck: 0, tongue: 0, teeth: 0, ...extra });

export const SHAPES = {
  sil: P(0.0, 0.5),
  PP: P(0.0, 0.46, 0.05, { press: 1 }),
  FF: P(0.07, 0.52, 0, { tuck: 1, teeth: 1 }),
  TH: P(0.18, 0.52, 0, { tongue: 1, teeth: 0.8 }),
  DD: P(0.26, 0.53, 0, { teeth: 0.6, tongue: 0.35 }),
  kk: P(0.32, 0.5, 0, { teeth: 0.5 }),
  CH: P(0.18, 0.36, 0.65, { teeth: 0.7 }),
  SS: P(0.08, 0.62, 0, { teeth: 1 }),
  nn: P(0.16, 0.5, 0, { teeth: 0.3, tongue: 0.25 }),
  RR: P(0.22, 0.42, 0.45, { teeth: 0.3 }),
  aa: P(0.95, 0.6, 0, { teeth: 0.5 }),
  E: P(0.55, 0.68, 0, { teeth: 0.7 }),
  I: P(0.3, 0.76, 0, { teeth: 0.85 }),
  O: P(0.66, 0.4, 0.8, { teeth: 0.2 }),
  U: P(0.22, 0.3, 1),
};

export const PARAMS = ['open', 'width', 'round', 'press', 'tuck', 'tongue', 'teeth'];

export const TO_HUMAN = { I: 'ih', O: 'oh', U: 'ou' };

/** Visual class used by the agreement metric: lips meeting, open, or rounded forward. */
export function visemeClass(id) {
  const s = SHAPES[id] || SHAPES.sil;
  if (s.round >= 0.4) return 'rounded';
  if (s.open <= 0.1) return 'closed';
  return 'open';
}

/** Weighted mix of poses. weights: {viseme: w}; missing weight goes to sil. */
export function blendPose(weights) {
  const out = Object.fromEntries(PARAMS.map((k) => [k, 0]));
  let sum = 0;
  for (const [id, w] of Object.entries(weights)) {
    if (!(w > 0) || !SHAPES[id]) continue;
    sum += w;
    for (const k of PARAMS) out[k] += SHAPES[id][k] * w;
  }
  if (sum < 1) for (const k of PARAMS) out[k] += SHAPES.sil[k] * (1 - sum);
  else if (sum > 1) for (const k of PARAMS) out[k] /= sum;
  return out;
}

/** The viseme with the highest weight (sil when nothing is active). */
export function dominant(weights) {
  let best = 'sil', bw = 0.15;
  for (const [id, w] of Object.entries(weights)) if (w > bw) { best = id; bw = w; }
  return best;
}

/**
 * Per-parameter attack/release smoothing, the same in every method so only the input differs.
 * attack: time constant (s) when a value grows, release when it falls. Lips close a little slower than they open.
 */
export class PoseSmoother {
  constructor({ attack = 0.035, release = 0.06 } = {}) {
    this.attack = attack;
    this.release = release;
    this.pose = blendPose({ sil: 1 });
  }
  step(target, dt) {
    for (const k of PARAMS) {
      const tau = target[k] > this.pose[k] ? this.attack : this.release;
      this.pose[k] += (target[k] - this.pose[k]) * (1 - Math.exp(-dt / tau));
    }
    return this.pose;
  }
  reset() { this.pose = blendPose({ sil: 1 }); }
}
