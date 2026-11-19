// The puppet page: pick a character and a mouth technique, play a real voice line with its text-timed visemes
// (../lipsync/mouth-driver.js, method 'text', unchanged) or let it listen. Live numbers: fps, main-thread ms per frame,
// audio-to-mouth lag (rendered inner-lip gap vs the voice envelope on the heard-audio clock, like the lip-sync test).
// window.__puppet drives scripted runs: speak, listen, freeze, capture, sheet, exportPre, detect.

import { Puppet, SPRITE_POSES } from './puppet.js';
import { Morph } from './morph.js';
import { Idle } from './idle.js';
import { createMouthDriver } from '../lipsync/mouth-driver.js';
import { cuesFromAlignment, sampleCues } from '../lipsync/lib/g2v.js';
import { SHAPES, blendPose, PoseSmoother } from '../lipsync/lib/visemes.js';
import { envelope, syncLag } from '../lipsync/lib/metrics.js';

const $ = (id) => document.getElementById(id);
const CLIPS = { nova_es_t: 'es', hana_es_t: 'es', imani_en_t: 'en' };
const LEAD_MS = 50, FPS = 60;
const q = new URLSearchParams(location.search);

let chars = [], ch = null, puppet = null, tess = null, ctx = null, run = null, freeze = null, still = false, last = performance.now();
const idle = new Idle(11);
const costs = [], frames = [];
let lastResult = null, hook = null, laughAt = -10, laughDur = 1.4;

async function ensureCtx() {
  if (!ctx) ctx = new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' });
  if (ctx.state !== 'running') await ctx.resume();
}

function audibleCtxTime() {
  const ts = ctx.getOutputTimestamp ? ctx.getOutputTimestamp() : null;
  if (ts && ts.contextTime > 0) return ts.contextTime + (performance.now() - ts.performanceTime) / 1000;
  return ctx.currentTime - (ctx.outputLatency || ctx.baseLatency || 0);
}

function sizeCanvas() {
  const c = $('stage'), r = c.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
  c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr);
  puppet?.setView(+(q.get('zoom') || 1.25));
}

async function load(id, mouth = $('mouth').value) {
  stop();
  ch = chars.find((c) => c.id === id) || chars[0];
  $('char').value = ch.id; $('mouth').value = mouth;
  $('clip').value = ch.voice;
  const old = $('stage'), c = old.cloneNode(false);  // a fresh canvas: one WebGL context per character
  old.replaceWith(c);
  const t0 = performance.now();
  if ((mouth === 'morph' || mouth === 'replace') && !ch.kf?.length) mouth = 'drawn';
  $('mouth').value = mouth;
  puppet = await makeEngine(c, ch, mouth);
  $('loadms').textContent = `${(performance.now() - t0).toFixed(0)} ms`;
  sizeCanvas();
  $('style').textContent = `${ch.styleName} · ${ch.name}` + (mouth === 'sprites' && !puppet.sprites.length ? ' · no sprites yet, drawn mouth shown' : '');
  return { id: ch.id, mouth, sprites: puppet.sprites.map((s) => s.name) };
}

async function makeEngine(c, chr, mouth) {
  if (mouth === 'morph' || mouth === 'replace') return Morph.create(c, { base: `chars/${chr.id}/`, tess, mode: mouth });
  return Puppet.create(c, { base: `chars/${chr.id}/`, tess, mouth, sprites: mouth === 'sprites' ? chr.sprites : [] });
}

/** Laugh channel: 0.25 s rise, hold, 0.4 s fall; the pulse is the "ha-ha" (mouth between laugh and smile, ~4.5 Hz). */
function laughState(t) {
  const u = t - laughAt;
  if (u < 0 || u > laughDur) return { laugh: 0, laughPulse: 1 };
  const env = Math.min(1, u / 0.25) * Math.min(1, (laughDur - u) / 0.4);
  return { laugh: env * env * (3 - 2 * env), laughPulse: 0.72 + 0.28 * Math.abs(Math.cos(u * Math.PI * 4.5)) };
}

/** The old puppet has no laugh: the closest it can do is its smile basis with an open, wide mouth. */
function oldLaugh(st) {
  const L = st.laugh;
  if (!L) return st;
  const open = 0.55 * st.laughPulse;
  st.smile = Math.max(st.smile || 0, L);
  st.pose = { ...st.pose, open: st.pose.open + (open - st.pose.open) * L, width: st.pose.width + (0.7 - st.pose.width) * L, teeth: st.pose.teeth + (1 - st.pose.teeth) * L };
  return st;
}

const cache = new Map();
async function clipData(id) {
  if (cache.has(id)) return cache.get(id);
  const [bytes, meta] = await Promise.all([fetch(`../lipsync/clips/${id}.mp3`).then((r) => r.arrayBuffer()), fetch(`../lipsync/clips/${id}.json`).then((r) => r.json())]);
  const buffer = await ctx.decodeAudioData(bytes);
  const v = { buffer, meta, env: envelope(buffer.getChannelData(0), buffer.sampleRate, FPS) };
  cache.set(id, v);
  return v;
}

async function speak(id = $('clip').value) {
  await ensureCtx();
  stop();
  const { buffer, meta, env } = await clipData(id);
  const src = ctx.createBufferSource();
  src.buffer = buffer; src.connect(ctx.destination);
  const T0 = ctx.currentTime + 0.08;
  const clock = () => audibleCtxTime() - T0;
  const driver = createMouthDriver({ method: 'text', context: ctx, clock, cues: cuesFromAlignment(meta.alignment, CLIPS[id]), leadMs: LEAD_MS, loop: false });
  await driver.start();
  src.start(T0);
  const r = run = { id, src, driver, clock, env, dur: buffer.duration, rec: [], costs: [], frameTimes: [] };
  return new Promise((resolve) => {
    src.onended = () => setTimeout(() => {
      if (run !== r) return resolve(null);
      run = null; driver.stop();
      resolve(lastResult = finish(r));
    }, 300);
  });
}

function finish(r) {
  // rendered inner-lip gap, resampled on the heard-audio clock at 60 fps, against the voice envelope
  const n = r.env.length, mouth = new Float64Array(n);
  let j = 0;
  for (let i = 0; i < n; i++) {
    const t = i / FPS;
    while (j < r.rec.length - 2 && r.rec[j + 1][0] < t) j++;
    const [ta, ga] = r.rec[j] || [0, 0], [tb, gb] = r.rec[j + 1] || [ta, ga];
    mouth[i] = tb > ta ? ga + ((gb - ga) * Math.min(1, Math.max(0, (t - ta) / (tb - ta)))) : ga;
  }
  const lag = syncLag(mouth, r.env, FPS);
  const c = [...r.costs].sort((a, b) => a - b), dts = [];
  for (let i = 1; i < r.frameTimes.length; i++) dts.push(r.frameTimes[i] - r.frameTimes[i - 1]);
  dts.sort((a, b) => a - b);
  const res = {
    clip: r.id, char: ch.id, mouth: puppet.mouth, canvas: [puppet.canvas.width, puppet.canvas.height], css: Math.round(puppet.canvas.getBoundingClientRect().width),
    lagMs: lag.lagMs, r: lag.r, leadMs: LEAD_MS,
    fpsMedian: Math.round(1000 / dts[Math.floor(dts.length / 2)]), fpsP5: Math.round(1000 / dts[Math.floor(dts.length * 0.95)]),
    msMean: +(c.reduce((a, b) => a + b, 0) / c.length).toFixed(3), msP95: +c[Math.floor(c.length * 0.95)].toFixed(3), frames: c.length,
  };
  $('lag').textContent = `${res.lagMs} ms (r ${res.r})`;
  return res;
}

function stop() {
  if (run) { try { run.src.onended = null; run.src.stop(); } catch {} run.driver.stop(); run = null; }
}

function frame(now) {
  const t0 = performance.now();
  const dt = Math.min(0.1, Math.max(0.001, (now - last) / 1000));
  last = now;
  let pose = SHAPES.sil, vis = 'sil', weights = { sil: 1 };
  if (run) { const f = run.driver.update(now); pose = f.pose; vis = f.viseme; weights = f.weights; }
  if (freeze) { pose = freeze.pose; vis = freeze.name; weights = { [freeze.name]: 1 }; }
  idle.setMode(run || freeze ? 'speaking' : 'listening');
  const st = still ? { blink: [0, 0], gaze: [0, 0], head: null, brow: 0, smile: 0, breath: 0 } : idle.step(dt, pose.open);
  st.pose = pose; st.vis = weights; st.dt = dt; st.t = now / 1000;
  Object.assign(st, laughState(now / 1000));
  if (puppet instanceof Puppet) oldLaugh(st);
  const gap = puppet ? puppet.render(st) : 0;
  const cost = performance.now() - t0;
  costs.push(cost); if (costs.length > 240) costs.shift();
  frames.push(now); while (frames.length && now - frames[0] > 1000) frames.shift();
  if (run) { const h = run.clock(); if (h >= 0) run.rec.push([h, gap]); run.costs.push(cost); run.frameTimes.push(now); }
  if (hook) hook({ now, pose, vis, heard: run ? run.clock() : -1 });
  if (frames.length % 10 === 0) {
    const s = [...costs].sort((a, b) => a - b);
    $('fps').textContent = frames.length;
    $('ms').textContent = `${(s.reduce((a, b) => a + b, 0) / s.length).toFixed(2)} / ${s[Math.floor(s.length * 0.95)].toFixed(2)}`;
    $('vis').textContent = `${vis} · ${run ? 'speaking' : freeze ? 'frozen' : 'listening'}`;
  }
  requestAnimationFrame(frame);
}

async function post(path, blob) {
  const r = await fetch(`/save?path=${encodeURIComponent(path)}`, { method: 'POST', body: blob });
  if (!r.ok) throw new Error(`save ${path}: ${r.status}`);
  return path;
}
const pngOf = (canvas) => new Promise((res) => canvas.toBlob(res, 'image/png'));

/** Plays a clip and grabs `n` frames between `from` and `from + dur` s of heard audio into one sheet; also saves the
 *  first frame where the mouth is clearly on "aa" and on "O". */
async function sheet({ clip, from = 0.3, dur = 2, n = 12, cols = 6, name = 'sheet', tile = 300 } = {}) {
  const rows = Math.ceil(n / cols), c = puppet.canvas, ar = c.height / c.width;
  const s = document.createElement('canvas');
  s.width = cols * tile; s.height = Math.round(rows * tile * ar) + 24;
  const g = s.getContext('2d');
  g.fillStyle = '#111'; g.fillRect(0, 0, s.width, s.height);
  let k = 0;
  const grabs = { aa: null, O: null };
  const saves = [];
  hook = ({ pose, vis, heard }) => {
    if (heard < 0) return;
    if (!grabs.aa && vis === 'aa' && pose.open > 0.7) { grabs.aa = heard; saves.push(pngOf(c).then((b) => post(`chars/${ch.id}/shots/${puppet.mouth}_aa.png`, b))); }
    if (!grabs.O && (vis === 'O' || vis === 'U') && pose.round > 0.6) { grabs.O = heard; saves.push(pngOf(c).then((b) => post(`chars/${ch.id}/shots/${puppet.mouth}_O.png`, b))); }
    while (k < n && heard >= from + (k * dur) / n) {
      const x = (k % cols) * tile, y = Math.floor(k / cols) * tile * ar;
      g.drawImage(c, x, y, tile, tile * ar);
      g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(x, y, 92, 20);
      g.fillStyle = '#fff'; g.font = '13px system-ui'; g.fillText(`${heard.toFixed(2)} s ${vis}`, x + 4, y + 14);
      k++;
    }
  };
  const res = await speak(clip);
  hook = null;
  g.fillStyle = '#ccc'; g.font = '14px system-ui';
  g.fillText(`${ch.styleName} · ${ch.name} · mouth: ${puppet.mouth} · ${res?.clip} ${from}-${from + dur} s · lag ${res?.lagMs} ms`, 8, s.height - 7);
  saves.push(pngOf(s).then((b) => post(`chars/${ch.id}/shots/${name}_${puppet.mouth}.png`, b)));
  return { ...res, grabs, saved: await Promise.all(saves) };
}

/** Renders each sprite pose at the portrait's full size with the drawn mouth, no head motion, for gen.py mouths. */
async function exportPre(id = ch.id) {
  const c = document.createElement('canvas');
  const lm = await fetch(`chars/${id}/landmarks.json`).then((r) => r.json());
  c.width = lm.w; c.height = lm.h;
  const p = await Puppet.create(c, { base: `chars/${id}/`, tess, mouth: 'drawn' });
  p.setView(1);
  const out = [];
  for (const [name, pose] of Object.entries({ sil: SHAPES.sil, ...SPRITE_POSES })) {
    p.render({ pose });
    out.push(await post(`chars/${id}/pre/${name}.png`, await pngOf(c)));
  }
  p.gl.getExtension('WEBGL_lose_context')?.loseContext();
  return out;
}

/** The same Face Landmarker in the browser (tasks-vision 0.10.14 from jsDelivr): mean distance to the saved JSON. */
async function detect(id = ch.id) {
  const V = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';
  const { FilesetResolver, FaceLandmarker } = await import(`${V}/vision_bundle.mjs`);
  const t0 = performance.now();
  const fs = await FilesetResolver.forVisionTasks(`${V}/wasm`);
  const fl = await FaceLandmarker.createFromOptions(fs, { baseOptions: { modelAssetPath: 'vendor/face_landmarker.task' }, runningMode: 'IMAGE', numFaces: 1 });
  const t1 = performance.now();
  const img = new Image(); img.src = `chars/${id}/portrait.png`; await img.decode();
  const res = fl.detect(img);
  const t2 = performance.now();
  const lm = await fetch(`chars/${id}/landmarks.json`).then((r) => r.json());
  const pts = res.faceLandmarks[0];
  let d = 0, mx = 0;
  pts.forEach((p, i) => { const e = Math.hypot(p.x * lm.w - lm.points[i][0], p.y * lm.h - lm.points[i][1]); d += e; mx = Math.max(mx, e); });
  fl.close();
  return { points: pts.length, meanPx: +(d / pts.length).toFixed(2), maxPx: +mx.toFixed(2), loadMs: Math.round(t1 - t0), detectMs: Math.round(t2 - t1) };
}

/**
 * Deterministic comparison sheet: the same timeline (a voice line's text-timed visemes at 60 fps, idle seed 11, then a
 * laugh) rendered offline by each engine, one row per engine, the same instants in every row. No audio is played.
 */
async function compare({ id = ch.id, clip = ch.voice, engines = null, times = null, laughFor = 1.4, tile = 260, zoom = 1.25, name = 'compare' } = {}) {
  const chr = chars.find((c) => c.id === id);
  engines = engines || [...(chr.sprites.length ? ['sprites'] : ['drawn']), ...(chr.kf?.length ? [chr.kfMode] : [])];
  const meta = await fetch(`../lipsync/clips/${clip}.json`).then((r) => r.json());
  const cues = cuesFromAlignment(meta.alignment, CLIPS[clip]);
  const end = Math.min(cues[cues.length - 1].t, 3.2);
  const la = end + 0.15;
  times = times || [0.45, 0.7, 0.95, 1.2, 1.45, 1.7, 1.95, 2.2, la + 0.15, la + 0.35, la + 0.6, la + 0.95];
  const W = 600, H = 750, ar = H / W;
  const s = document.createElement('canvas');
  s.width = times.length * tile; s.height = engines.length * Math.round(tile * ar) + 22;
  const g = s.getContext('2d');
  g.fillStyle = '#111'; g.fillRect(0, 0, s.width, s.height);
  const info = [];
  for (const [row, mode] of engines.entries()) {
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const eng = await makeEngine(c, chr, mode);
    eng.setView(zoom);
    const id2 = new Idle(11), sm = new PoseSmoother();
    const N = Math.ceil((Math.max(...times) + 0.01) * 60);
    let k = 0, cost = 0;
    for (let f = 0; f <= N && k < times.length; f++) {
      const t = f / 60, dt = 1 / 60;
      const speaking = t < end + 0.1;
      const w = speaking ? sampleCues(cues, t + LEAD_MS / 1000) : { sil: 1 };
      const pose = { ...sm.step(blendPose(w), dt) };
      id2.setMode(speaking ? 'speaking' : 'listening');
      const st = id2.step(dt, pose.open);
      Object.assign(st, { pose, vis: w, dt, t }, (laughAt = la, laughDur = laughFor, laughState(t)));
      if (eng instanceof Puppet) oldLaugh(st);
      const c0 = performance.now();
      eng.render(st);
      cost += performance.now() - c0;
      while (k < times.length && t + 1e-6 >= times[k]) {
        const x = k * tile, y = row * Math.round(tile * ar);
        g.drawImage(c, x, y, tile, tile * ar);
        g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(x, y, tile, 18);
        g.fillStyle = '#fff'; g.font = '12px system-ui';
        const lab = st.laugh > 0.05 ? `laugh ${st.laugh.toFixed(1)}` : Object.entries(w).sort((a, b) => b[1] - a[1])[0][0];
        g.fillText(`${mode} ${t.toFixed(2)} s ${lab}`, x + 4, y + 13);
        if (eng.last) info.push({ t: +t.toFixed(2), cu: Object.fromEntries(Object.entries(eng.last.cu).filter(([, v]) => v > 0.01).map(([kk, v]) => [kk, +v.toFixed(2)])), cl: Object.fromEntries(Object.entries(eng.last.cl).filter(([, v]) => v > 0.01).map(([kk, v]) => [kk, +v.toFixed(2)])) });
        k++;
      }
    }
    info.push({ mode, msPerRender: +(cost / (N + 1)).toFixed(3) });
    eng.gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
  laughAt = -10; laughDur = 1.4;
  g.fillStyle = '#ccc'; g.font = '13px system-ui';
  g.fillText(`${chr.styleName} · ${chr.name} · rows: ${engines.join(' / ')} · ${clip}, laugh at ${la.toFixed(2)} s · same idle seed`, 8, s.height - 6);
  const saved = await post(`chars/${id}/shots/${name}.png`, await pngOf(s));
  return { saved, info, times };
}

function laugh(dur = 1.4) { laughAt = performance.now() / 1000; laughDur = dur; }

async function capture(name) { return post(`chars/${ch.id}/shots/${name}.png`, await pngOf(puppet.canvas)); }

function setFreeze(name, opts = {}) {
  freeze = name ? { name, pose: SHAPES[name] || SPRITE_POSES[name] } : null;
  still = !!opts.still;
}

async function main() {
  [chars, tess] = await Promise.all([fetch('chars/index.json').then((r) => r.json()), fetch('mesh/tess.json').then((r) => r.json())]);
  for (const style of [...new Set(chars.map((c) => c.styleName))]) {
    const g = document.createElement('optgroup'); g.label = style;
    for (const c of chars.filter((x) => x.styleName === style)) g.append(new Option(`${c.name} (${c.id})`, c.id));
    $('char').append(g);
  }
  for (const id of Object.keys(CLIPS)) $('clip').append(new Option(id, id));
  $('char').onchange = () => load($('char').value);
  $('mouth').onchange = () => load(ch.id, $('mouth').value);
  $('speak').onclick = () => speak();
  $('listen').onclick = () => { stop(); setFreeze(null); };
  $('laugh').onclick = () => laugh();
  addEventListener('resize', sizeCanvas);
  await load(q.get('char') || chars[0].id, q.get('mouth') || 'drawn');
  requestAnimationFrame(frame);
  window.__puppet = { load, speak, stop, sheet, compare, laugh, exportPre, detect, capture, freeze: setFreeze, result: () => lastResult,
    stats: () => ({ fps: frames.length, msMean: costs.reduce((a, b) => a + b, 0) / costs.length, canvas: [puppet.canvas.width, puppet.canvas.height] }) };
  document.body.dataset.ready = '1';
}

main().catch((e) => { $('style').textContent = `error: ${e.message}`; console.error(e); });
