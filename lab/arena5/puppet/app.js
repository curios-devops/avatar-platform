// The puppet page: pick a character and a mouth technique, play a real voice line with its text-timed visemes
// (../lipsync/mouth-driver.js, method 'text', unchanged) or let it listen. Live numbers: fps, main-thread ms per frame,
// audio-to-mouth lag (rendered inner-lip gap vs the voice envelope on the heard-audio clock, like the lip-sync test).
// window.__puppet drives scripted runs: speak, listen, freeze, capture, sheet, exportPre, detect.

import { Puppet, SPRITE_POSES } from './puppet.js';
import { Idle } from './idle.js';
import { createMouthDriver } from '../lipsync/mouth-driver.js';
import { cuesFromAlignment } from '../lipsync/lib/g2v.js';
import { SHAPES } from '../lipsync/lib/visemes.js';
import { envelope, syncLag } from '../lipsync/lib/metrics.js';

const $ = (id) => document.getElementById(id);
const CLIPS = { nova_es_t: 'es', hana_es_t: 'es', imani_en_t: 'en' };
const LEAD_MS = 50, FPS = 60;
const q = new URLSearchParams(location.search);

let chars = [], ch = null, puppet = null, tess = null, ctx = null, run = null, freeze = null, still = false, last = performance.now();
const idle = new Idle(11);
const costs = [], frames = [];
let lastResult = null, hook = null;

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
  puppet = await Puppet.create(c, { base: `chars/${ch.id}/`, tess, mouth, sprites: mouth === 'sprites' ? ch.sprites : [] });
  $('loadms').textContent = `${(performance.now() - t0).toFixed(0)} ms`;
  sizeCanvas();
  $('style').textContent = `${ch.styleName} · ${ch.name}` + (mouth === 'sprites' && !puppet.sprites.length ? ' · no sprites yet, drawn mouth shown' : '');
  return { id: ch.id, mouth, sprites: puppet.sprites.map((s) => s.name) };
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
  let pose = SHAPES.sil, vis = 'sil';
  if (run) { const f = run.driver.update(now); pose = f.pose; vis = f.viseme; }
  if (freeze) { pose = freeze.pose; vis = freeze.name; }
  idle.setMode(run || freeze ? 'speaking' : 'listening');
  const st = still ? { blink: [0, 0], gaze: [0, 0], head: null, brow: 0, smile: 0, breath: 0 } : idle.step(dt, pose.open);
  st.pose = pose;
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
  addEventListener('resize', sizeCanvas);
  await load(q.get('char') || chars[0].id, q.get('mouth') || 'drawn');
  requestAnimationFrame(frame);
  window.__puppet = { load, speak, stop, sheet, exportPre, detect, capture, freeze: setFreeze, result: () => lastResult,
    stats: () => ({ fps: frames.length, msMean: costs.reduce((a, b) => a + b, 0) / costs.length, canvas: [puppet.canvas.width, puppet.canvas.height] }) };
  document.body.dataset.ready = '1';
}

main().catch((e) => { $('style').textContent = `error: ${e.message}`; console.error(e); });
