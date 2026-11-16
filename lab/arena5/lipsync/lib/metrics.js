// Numbers shared by the Node script and the page. All series are sampled at `fps` frames per second.
// Sync is measured the way round 4 measured it (lab/a2f/arena4_metrics.py): Pearson r between mouth opening and the
// voice's RMS envelope at the best lag within +-250 ms; a positive lag means the mouth is late.

export function envelope(x, sr, fps = 60) {
  const n = Math.floor((x.length / sr) * fps), env = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor((i * sr) / fps), b = Math.floor(((i + 1) * sr) / fps);
    let s = 0;
    for (let j = a; j < b; j++) s += x[j] * x[j];
    env[i] = Math.sqrt(s / Math.max(1, b - a));
  }
  const sm = new Float64Array(n);
  for (let i = 0; i < n; i++) sm[i] = (env[Math.max(0, i - 1)] + env[i] + env[Math.min(n - 1, i + 1)]) / 3;
  return sm;
}

export function percentile(a, p) {
  const s = [...a].sort((x, y) => x - y);
  return s.length ? s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))] : 0;
}

/** Frames where the voice is audible: envelope above 12 % of its 95th percentile. */
export function speakingMask(env) {
  const th = 0.12 * percentile(env, 95);
  return Array.from(env, (v) => v > th);
}

export function pearson(a, b) {
  const n = Math.min(a.length, b.length);
  if (n < 3) return NaN;
  let ma = 0, mb = 0;
  for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; }
  ma /= n; mb /= n;
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < n; i++) { const da = a[i] - ma, db = b[i] - mb; sab += da * db; saa += da * da; sbb += db * db; }
  return saa > 0 && sbb > 0 ? sab / Math.sqrt(saa * sbb) : NaN;
}

/** Best lag (ms, mouth late > 0) and r there, plus r at lag 0. Only overlapping frames are compared. */
export function syncLag(mouth, env, fps = 60, maxMs = 250) {
  const maxL = Math.round((maxMs / 1000) * fps);
  let best = { r: -2, lagMs: 0 };
  for (let L = -maxL; L <= maxL; L++) {
    const a = [], b = [];
    for (let i = 0; i < env.length; i++) { const j = i + L; if (j >= 0 && j < mouth.length) { a.push(mouth[j]); b.push(env[i]); } }
    const r = pearson(a, b);
    if (r > best.r) best = { r, lagMs: Math.round((L * 1000) / fps) };
  }
  return { r: round(best.r, 3), lagMs: best.lagMs, r0: round(pearson(mouth, env), 3) };
}

/** What the viewer sees, in three classes: lips meeting / open / rounded forward. */
export function poseClass(p) {
  if (p.round >= 0.35 && p.open > 0.04) return 'rounded';
  if (p.open < 0.1) return 'closed';
  return 'open';
}

/** Agreement of two class sequences on the masked frames, with chance level and Cohen's kappa. */
export function agreement(ca, cb, mask) {
  let n = 0, same = 0;
  const fa = {}, fb = {};
  for (let i = 0; i < Math.min(ca.length, cb.length); i++) {
    if (mask && !mask[i]) continue;
    n++;
    if (ca[i] === cb[i]) same++;
    fa[ca[i]] = (fa[ca[i]] || 0) + 1;
    fb[cb[i]] = (fb[cb[i]] || 0) + 1;
  }
  const po = n ? same / n : NaN;
  let pe = 0;
  for (const k of Object.keys(fa)) pe += (fa[k] / n) * ((fb[k] || 0) / n);
  return { agree: round(po, 3), chance: round(pe, 3), kappa: round((po - pe) / (1 - pe), 3), frames: n };
}

/**
 * Timing of visible events into class `cls`: every time the reference enters it (and stays 2+ frames) while the
 * voice is on or within 100 ms, find the nearest entry of the test into the same class within +-maxMs.
 * hitRate = matched / reference onsets; precision = share of the test's own onsets that match one.
 */
export function onsetTiming(ref, test, mask, cls, fps = 60, maxMs = 200) {
  const onsets = (c) => {
    const out = [];
    for (let i = 1; i < c.length - 1; i++) if (c[i] === cls && c[i - 1] !== cls && c[i + 1] === cls) out.push(i);
    return out;
  };
  const near = (k) => [-6, 0, 6].some((d) => mask[Math.max(0, Math.min(mask.length - 1, k + d))]);
  const ro = onsets(ref).filter(near), to = onsets(test).filter(near), maxF = (maxMs / 1000) * fps, errs = [];
  for (const i of ro) {
    let best = null;
    for (const j of to) if (Math.abs(j - i) <= maxF && (best === null || Math.abs(j - i) < Math.abs(best - i))) best = j;
    if (best !== null) errs.push(((best - i) * 1000) / fps);
  }
  const good = to.filter((j) => ro.some((i) => Math.abs(i - j) <= maxF)).length;
  return {
    onsets: ro.length, matched: errs.length, hitRate: round(ro.length ? errs.length / ro.length : NaN, 3),
    testOnsets: to.length, precision: round(to.length ? good / to.length : NaN, 3),
    medianMs: round(percentile(errs, 50), 0), medianAbsMs: round(percentile(errs.map(Math.abs), 50), 0),
  };
}

/** Changes of the shown viseme per second of clip. */
export function eventsPerSecond(dom, fps = 60) {
  let c = 0;
  for (let i = 1; i < dom.length; i++) if (dom[i] !== dom[i - 1]) c++;
  return round(dom.length ? c / (dom.length / fps) : 0, 1);
}

export function round(v, d) { return Number.isFinite(v) ? Math.round(v * 10 ** d) / 10 ** d : null; }
