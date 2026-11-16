// The test page: one clip, three mouth drivers on the same audio, three identical faces, live numbers.
// Everything measured here is also exposed on window.__lipsync for scripted runs (run(clipId, mode) -> rows).
import { createMouthDriver } from './mouth-driver.js';
import { createFace } from './face2d.js';
import { cuesFromAlignment } from './lib/g2v.js';
import { VISEMES, blendPose } from './lib/visemes.js';
import { envelope, syncLag, poseClass, agreement, speakingMask, round } from './lib/metrics.js';

const CLIPS = [
  { id: 'nova_es_t', label: 'Nova, es, timed', lang: 'es', timed: true },
  { id: 'hana_es_t', label: 'Hana, es, timed', lang: 'es', timed: true },
  { id: 'imani_en_t', label: 'Imani, en, timed', lang: 'en', timed: true },
  ...['nova-es', 'hana-es', 'imani-es', 'kai-es', 'nova-en', 'hana-en'].map((g) => ({ id: g, label: `${g} greeting (no timing file)`, lang: g.slice(-2), src: `clips/greet/${g}.mp3` })),
].map((c) => ({ src: `clips/${c.id}.mp3`, timing: c.timed ? `clips/${c.id}.json` : null, ...c }));

const METHODS = [
  { key: 'A', method: 'amplitude', title: 'A. Amplitude (RMS)', color: 'var(--a)', worklet: 'yes: RMS meter worklet' },
  { key: 'B', method: 'engine', title: 'B. lipsync-engine', color: 'var(--b)', worklet: 'no: AnalyserNode read on the main thread' },
  { key: 'H', method: 'headaudio', title: 'H. HeadAudio (MFCC model)', color: 'var(--h)', worklet: 'yes: MFCC + classifier worklet' },
  { key: 'C', method: 'text', title: 'C. Text-timed visemes', color: 'var(--c)', worklet: 'no audio analysis (timeline lookup)' },
];

const $ = (id) => document.getElementById(id);
const FPS = 60;
for (const c of CLIPS) $('clip').append(new Option(c.label, c.id));

const ui = {};
for (const m of METHODS) {
  const p = document.createElement('section');
  p.className = 'panel';
  p.style.setProperty('--accent', m.color);
  p.innerHTML = `<h2>${m.title}</h2><div class="facebox"></div><div class="na" hidden>No timing file for this clip: C needs the TTS character timestamps.</div>
    <div class="vis">sil</div><canvas width="600" height="96"></canvas><dl>
    <dt>viseme events/s</dt><dd data-k="ev">-</dd><dt>lag vs heard audio</dt><dd data-k="lag">after the clip</dd>
    <dt>analysis ms/frame</dt><dd data-k="cost">-</dd><dt>draw ms/frame</dt><dd data-k="draw">-</dd>
    <dt>AudioWorklet</dt><dd data-k="wk">${m.worklet}</dd><dt>fps</dt><dd data-k="fps">-</dd></dl>`;
  $('panels').append(p);
  ui[m.key] = { p, face: createFace(p.querySelector('.facebox')), vis: p.querySelector('.vis'), cv: p.querySelector('canvas'),
    dd: (k) => p.querySelector(`[data-k=${k}]`), na: p.querySelector('.na'), box: p.querySelector('.facebox') };
}
for (const v of VISEMES) {
  const f = document.createElement('figure');
  $('sheet').append(f);
  createFace(f).render(blendPose({ [v]: 1 }));
  f.append(Object.assign(document.createElement('figcaption'), { textContent: v }));
}

let ctx = null, run = null, mic = null;
const status = (s) => { $('status').textContent = s; };

async function ensureCtx() {
  if (!ctx) {
    ctx = new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' });
    await ctx.audioWorklet.addModule('lib/pcm-queue-worklet.js');
  }
  if (ctx.state !== 'running') await ctx.resume();
}

// Context time at the speaker right now (what the listener hears), not the time the graph is processing.
function audibleCtxTime() {
  const ts = ctx.getOutputTimestamp ? ctx.getOutputTimestamp() : null;
  if (ts && ts.contextTime > 0) return ts.contextTime + (performance.now() - ts.performanceTime) / 1000;
  return ctx.currentTime - (ctx.outputLatency || ctx.baseLatency || 0);
}

const cache = new Map();
async function load(clip) {
  if (cache.has(clip.id)) return cache.get(clip.id);
  const bytes = await (await fetch(clip.src)).arrayBuffer();
  const buffer = await ctx.decodeAudioData(bytes.slice(0));
  const meta = clip.timing ? await (await fetch(clip.timing)).json() : null;
  const v = { buffer, meta };
  cache.set(clip.id, v);
  return v;
}

function partial(al, n) {
  return { characters: al.characters.slice(0, n), character_start_times_seconds: al.character_start_times_seconds.slice(0, n),
    character_end_times_seconds: al.character_end_times_seconds.slice(0, n) };
}

// Live mode: when each piece of PCM "arrives" and how many alignment characters arrive with it.
function schedule(mode, pcm, sr, meta) {
  const out = [];
  if (mode === 'recorded' && meta?.stream?.length) {
    const total = meta.stream.reduce((a, s) => a + s.bytes, 0), first = meta.stream[0].arrival_ms;
    let bytes = 0, chars = 0;
    for (const s of meta.stream) {
      const from = Math.round((bytes / total) * pcm.length);
      bytes += s.bytes; chars += s.n_chars;
      out.push({ at: (s.arrival_ms - first) / 1000, from, to: Math.round((bytes / total) * pcm.length), chars });
    }
  } else {
    // just in time: 100 ms chunks produced 1.05x faster than real time, +-40 ms jitter, 150 ms prebuffer in the worklet
    const step = Math.round(0.1 * sr);
    let at = 0;
    for (let from = 0, k = 0; from < pcm.length; from += step, k++) {
      at = Math.max(at, 0.03 + (k * 0.1) / 1.05 + (Math.random() - 0.5) * 0.08);
      const to = Math.min(pcm.length, from + step);
      const chars = meta ? meta.alignment.character_start_times_seconds.filter((t) => t < to / sr).length : 0;
      out.push({ at, from, to, chars });
    }
  }
  out[out.length - 1].last = true;
  return out;
}

async function play(clipId = $('clip').value, mode = $('mode').value) {
  await ensureCtx();
  stopAll();
  const clip = CLIPS.find((c) => c.id === clipId);
  const { buffer, meta } = await load(clip);
  const pcm = buffer.getChannelData(0), sr = buffer.sampleRate;
  const r = run = { clip, mode: mode === 'recorded' && !meta ? 'jit' : mode, sr, dur: buffer.duration, env: envelope(pcm, sr, FPS),
    rec: { A: [], B: [], H: [], C: [] }, draw: { A: [], B: [], H: [], C: [] }, frames: { A: 0, B: 0, H: 0, C: 0 }, drivers: {}, timers: [], underruns: 0, buffered: 0 };
  r.envMax = Math.max(...r.env) || 1;
  let source, clock, T0 = Infinity;
  if (r.mode === 'file') {
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    src.onended = () => finishSoon(r);
    source = r.src = src;
    clock = () => audibleCtxTime() - T0;
  } else {
    const q = new AudioWorkletNode(ctx, 'pcm-queue', { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1], processorOptions: { prebufferMs: 150 } });
    q.connect(ctx.destination);
    const hist = [];
    q.port.onmessage = (e) => {
      const d = e.data;
      if (d.type === 'pos') { hist.push(d); if (hist.length > 800) hist.shift(); r.buffered = d.buffered / sr; r.underruns = d.underruns; }
      else if (d.type === 'done') finishSoon(r);
    };
    clock = () => {
      if (!hist.length) return -1;
      const ta = audibleCtxTime();
      let i = hist.length - 1;
      while (i > 0 && hist[i].t > ta) i--;
      const h = hist[i], n = hist[i + 1];
      if (h.t > ta || (h.played === 0 && (!n || n.played === 0))) return -1;
      if (!n) return h.played / sr;
      return (h.played + ((n.played - h.played) * (ta - h.t)) / (n.t - h.t)) / sr;
    };
    source = r.q = q;
  }
  r.clock = clock;
  const lead = +$('lead').value, gain = +$('bgain').value;
  for (const m of METHODS) {
    const none = m.key === 'C' && !meta;
    ui[m.key].na.hidden = !none; ui[m.key].box.hidden = none; ui[m.key].p.classList.toggle('off', none);
    ui[m.key].dd('lag').textContent = 'after the clip';
    if (none) continue;
    const cues = m.key === 'C' && r.mode === 'file' ? cuesFromAlignment(meta.alignment, clip.lang) : [];
    const d = createMouthDriver({ method: m.method, context: ctx, clock, cues, leadMs: m.key === 'C' ? lead : 0, inputGainDb: m.key === 'B' ? gain : 0 });
    d.onViseme((f) => onFrame(r, m.key, f));
    await d.start(source);
    r.drivers[m.key] = d;
  }
  r.lead = lead; r.gain = gain;
  r.t0 = performance.now();
  if (r.mode === 'file') { T0 = ctx.currentTime + 0.1; r.src.start(T0); }
  else {
    for (const c of schedule(r.mode, pcm, sr, meta)) {
      r.timers.push(setTimeout(() => {
        r.q.port.postMessage({ type: 'push', samples: pcm.slice(c.from, c.to) });
        if (meta && r.drivers.C) r.drivers.C.setCues(cuesFromAlignment(partial(meta.alignment, c.chars), clip.lang));
        if (c.last) r.q.port.postMessage({ type: 'end' });
      }, c.at * 1000));
    }
  }
  $('play').disabled = true; $('stop').disabled = false;
  r.done = new Promise((res) => { r.resolve = res; });
  return r.done;
}

function onFrame(r, key, f) {
  const c0 = performance.now();
  ui[key].face.render(f.pose, f.pose.open);
  r.draw[key].push(performance.now() - c0);
  r.frames[key]++;
  ui[key].vis.textContent = f.viseme;
  if (f.t >= 0 && f.t <= r.dur + 0.3) r.rec[key].push([f.t, f.pose.open, poseClass(f.pose), f.viseme]);
  drawTrace(r, key, f.t);
}

function drawTrace(r, key, t) {
  const cv = ui[key].cv, g = cv.getContext('2d'), W = cv.width, H = cv.height, span = 4;
  const css = getComputedStyle(document.documentElement);
  g.clearRect(0, 0, W, H);
  const t1 = Math.max(span, t), t0 = t1 - span;
  g.fillStyle = css.getPropertyValue('--env');
  for (let x = 0; x < W; x += 3) {
    const i = Math.floor((t0 + (x / W) * span) * FPS);
    const v = i >= 0 && i < r.env.length ? r.env[i] / r.envMax : 0;
    g.fillRect(x, H - v * H, 2, v * H);
  }
  g.strokeStyle = css.getPropertyValue(`--${key.toLowerCase()}`);
  g.lineWidth = 2;
  g.beginPath();
  const rec = r.rec[key];
  for (let i = Math.max(0, rec.length - 300); i < rec.length; i++) {
    const x = ((rec[i][0] - t0) / span) * W, y = H - rec[i][1] * H;
    if (x < 0) continue;
    g.lineTo(x, y);
  }
  g.stroke();
}

setInterval(() => {
  const r = run;
  if (!r || r.finished) return;
  for (const [k, d] of Object.entries(r.drivers)) {
    const s = d.stats(), dr = r.draw[k].slice(-120);
    ui[k].dd('ev').textContent = s.eventsPerS.toFixed(1);
    ui[k].dd('cost').textContent = `${s.costMeanMs.toFixed(3)} / ${s.costP95Ms.toFixed(3)}`;
    ui[k].dd('draw').textContent = (dr.reduce((a, b) => a + b, 0) / Math.max(1, dr.length)).toFixed(3);
    ui[k].dd('fps').textContent = s.fps;
  }
  if (ctx) status(`${r.clip.label}, ${r.mode}. Context ${ctx.sampleRate} Hz, base latency ${(ctx.baseLatency * 1000).toFixed(0)} ms, output latency ${((ctx.outputLatency || 0) * 1000).toFixed(0)} ms. `
    + `Heard: ${Math.max(0, r.clock()).toFixed(2)} s of ${r.dur.toFixed(2)} s.` + (r.q ? ` Buffered ${(r.buffered * 1000).toFixed(0)} ms, underruns ${r.underruns}.` : ''));
}, 300);

function finishSoon(r) { setTimeout(() => finish(r), 400); }

function series(rec, n) {
  const s = [...rec].sort((a, b) => a[0] - b[0]), open = new Float64Array(n), cls = new Array(n).fill('closed');
  let j = 0;
  for (let i = 0; i < n; i++) {
    const t = i / FPS;
    while (j < s.length - 1 && s[j + 1][0] <= t) j++;
    if (!s.length || t < s[0][0]) continue;
    const a = s[j], b = s[j + 1];
    open[i] = b ? a[1] + ((b[1] - a[1]) * (t - a[0])) / Math.max(1e-6, b[0] - a[0]) : a[1];
    cls[i] = a[2];
  }
  return { open, cls };
}

function finish(r) {
  if (r !== run || r.finished) return;
  r.finished = true;
  const secs = (performance.now() - r.t0) / 1000, n = r.env.length, mask = speakingMask(r.env);
  const S = {}, rows = [];
  for (const [k, d] of Object.entries(r.drivers)) { S[k] = { stats: d.stats(), ...series(r.rec[k], n) }; d.stop(); }
  for (const [k, d] of Object.entries(S)) {
    const lag = syncLag(d.open, r.env, FPS);
    let ch = 0;
    for (let i = 1; i < r.rec[k].length; i++) if (r.rec[k][i][3] !== r.rec[k][i - 1][3]) ch++;
    const dr = r.draw[k], ag = S.C && k !== 'C' ? agreement(d.cls, S.C.cls, mask) : null;
    const row = { clip: r.clip.id, mode: r.mode, method: k, r: lag.r, lagMs: lag.lagMs, eventsPerS: round(ch / r.dur, 1),
      costMeanMs: round(d.stats.costMeanMs, 4), costP95Ms: round(d.stats.costP95Ms, 4),
      drawMs: round(dr.reduce((a, b) => a + b, 0) / Math.max(1, dr.length), 4), fps: round(r.frames[k] / secs, 0),
      worklet: d.stats.inWorklet, agreeC: ag && ag.agree, chanceC: ag && ag.chance, underruns: r.q ? r.underruns : null,
      leadMs: k === 'C' ? r.lead : null, bGainDb: k === 'B' ? r.gain : null,
      outputLatencyMs: round(((ctx.outputLatency || 0) + ctx.baseLatency) * 1000, 0) };
    rows.push(row);
    ui[k].dd('lag').textContent = `${lag.lagMs} ms (r ${lag.r})`;
    ui[k].dd('ev').textContent = `${row.eventsPerS} (whole clip)`;
    const tr = document.createElement('tr');
    tr.innerHTML = [row.clip, row.mode, k + (k === 'C' ? ` lead ${r.lead}` : k === 'B' ? ` ${r.gain} dB` : ''), row.r, row.lagMs, row.eventsPerS,
      `${row.costMeanMs} / ${row.costP95Ms}`, row.drawMs, row.fps, row.worklet ? 'yes' : 'no', ag ? `${ag.agree} (${ag.chance})` : '-', row.underruns ?? '-']
      .map((v) => `<td>${v}</td>`).join('');
    $('runs').tBodies[0].append(tr);
  }
  window.__lipsync.runs.push(...rows);
  stopAll();
  r.resolve(rows);
}

function stopAll() {
  if (run) {
    for (const t of run.timers) clearTimeout(t);
    for (const d of Object.values(run.drivers)) d.stop();
    try { run.src?.stop(); } catch {}
    try { run.q?.disconnect(); } catch {}
    if (!run.finished) { run.finished = true; run.resolve?.([]); }
  }
  if (mic) { mic.drivers.forEach((d) => d.stop()); mic.stream.getTracks().forEach((t) => t.stop()); mic = null; }
  $('play').disabled = false; $('stop').disabled = true;
}

async function startMic() {
  await ensureCtx();
  stopAll();
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } });
  const drivers = [];
  for (const m of METHODS.filter((x) => x.key !== 'C')) {
    const d = createMouthDriver({ method: m.method, context: ctx, inputGainDb: m.key === 'B' ? +$('bgain').value : 0 });
    d.onViseme((f) => { ui[m.key].face.render(f.pose, f.pose.open); ui[m.key].vis.textContent = f.viseme; });
    await d.start(stream);
    drivers.push(d);
  }
  ui.C.na.hidden = false; ui.C.box.hidden = true; ui.C.p.classList.add('off');
  mic = { stream, drivers };
  status('Microphone: A, B and H follow your voice. C needs text with timestamps, so it is off.');
  $('play').disabled = true; $('stop').disabled = false;
}

$('play').onclick = () => play();
$('stop').onclick = () => stopAll();
$('mic').onclick = () => startMic().catch((e) => status(`Microphone failed: ${e.message}`));
window.__lipsync = { runs: [], run: play, clips: CLIPS.map((c) => c.id), stop: stopAll, context: () => ctx, heard: () => (run && !run.finished ? run.clock() : -1) };
