// Offline half of the lip-sync test, no browser: decode each clip with ffmpeg, run the three methods frame by frame
// at 60 fps and score them.
//   A  amplitude (lib/amplitude.js)
//   B  lipsync-engine's FrequencyAnalyzer, the vendored file unchanged, on an AnalyserNode emulated to the spec
//   C  visemes from ElevenLabs character timestamps (lib/g2v.js), for clips that have clips/<id>.json
//   H  HeadAudio (met4citizen): MFCC + Gaussian prototypes, English model, vendored processor unchanged
//   Hw H after it has already heard the clip once (silence calibration done), as mid-conversation
//   Bq B on the same clip 6 dB quieter (its thresholds are absolute)
//   Cl C shown 50 ms early (animator's lead)
//   C0 the same rules with the text spread evenly over the voiced span (what you get with no timestamps)
// Against C (the TTS's own timing) it reports class agreement (closed / open / rounded) and onset timing in ms.
//
//   node lab/arena5/lipsync/offline.mjs            -> results/offline.json + a table
//   node lab/arena5/lipsync/offline.mjs --series   -> also results/series/<clip>.json (per-frame curves)

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FrequencyAnalyzer } from './vendor/lipsync-engine/analyzers/FrequencyAnalyzer.js';
import { OfflineAnalyser } from './lib/analyser-shim.js';
import { AmplitudeMouth, rms } from './lib/amplitude.js';
import { cuesFromAlignment, estimateAlignment, sampleCues } from './lib/g2v.js';
import { blendPose, dominant, PoseSmoother } from './lib/visemes.js';
import { engineWeights, ENGINE_OPTIONS, headAudioWeights, HeadAudioRamp } from './lib/methods.js';
import { Processor } from './vendor/headaudio/modules/processor.mjs';
import { Training } from './vendor/headaudio/modules/training.mjs';
import * as HA from './vendor/headaudio/modules/parameters.mjs';
import { envelope, speakingMask, syncLag, poseClass, agreement, onsetTiming, eventsPerSecond, round } from './lib/metrics.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VOICE = `${HERE}/clips/greet`; // copies of ManyMe/apps/web/public/media/voice/*.mp3
const SR = 24000, FPS = 60, DT = 1 / FPS;
const LEAD = 0.05;
const SERIES = process.argv.includes('--series');

const CLIPS = [
  { id: 'nova_es_t', file: `${HERE}/clips/nova_es_t.mp3`, lang: 'es' },
  { id: 'hana_es_t', file: `${HERE}/clips/hana_es_t.mp3`, lang: 'es' },
  { id: 'imani_en_t', file: `${HERE}/clips/imani_en_t.mp3`, lang: 'en' },
  ...['nova-es', 'hana-es', 'imani-es', 'kai-es', 'nova-en', 'hana-en'].map((g) => ({ id: g, file: `${VOICE}/${g}.mp3`, lang: g.slice(-2) })),
];

function decode(file) {
  const r = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-ac', '1', '-ar', String(SR), '-f', 'f32le', '-'], { maxBuffer: 64 << 20 });
  if (r.status !== 0) throw new Error(`ffmpeg failed on ${file}: ${r.stderr}`);
  const b = r.stdout;
  return new Float32Array(b.buffer, b.byteOffset, b.byteLength / 4).slice();
}

function run(weightsAt, n) {
  const sm = new PoseSmoother(), open = [], cls = [], dom = [];
  for (let i = 0; i < n; i++) {
    const w = weightsAt(i);
    const p = sm.step(blendPose(w), DT);
    open.push(p.open); cls.push(poseClass(p)); dom.push(dominant(w));
  }
  return { open, cls, dom };
}

function describe(m, env, mask) {
  const sp = m.open.filter((_, i) => mask[i]), si = m.open.filter((_, i) => !mask[i]);
  const hist = {};
  for (const d of m.dom) hist[d] = (hist[d] || 0) + 1;
  return {
    ...syncLag(m.open, env, FPS),
    eventsPerS: eventsPerSecond(m.dom, FPS),
    openSpeaking: round(sp.reduce((a, b) => a + b, 0) / Math.max(1, sp.length), 3),
    openSilent: round(si.reduce((a, b) => a + b, 0) / Math.max(1, si.length), 3),
    visemes: Object.fromEntries(Object.entries(hist).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, round(v / m.dom.length, 3)])),
  };
}

// HeadAudio's pre-trained model (English), decoded the way its own tests do
const haModel = (() => {
  const bin = fs.readFileSync(`${HERE}/vendor/headaudio/dist/model-en-mixed.bin`);
  const buf = bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.byteLength), tr = new Training(), m = [];
  for (let pos = 0; pos + HA.RECORD_OFFSET <= buf.byteLength; pos += HA.RECORD_OFFSET) m.push(tr.decodeBinaryRecord(new Float32Array(buf, pos, HA.RECORD_LEN)));
  return m;
})();

const results = { sampleRate: SR, fps: FPS, engine: ENGINE_OPTIONS, clips: {} };
for (const clip of CLIPS) {
  const x = decode(clip.file), n = Math.floor((x.length / SR) * FPS);
  const env = envelope(x, SR, FPS), mask = speakingMask(env);
  const pos = (i) => Math.floor(((i + 1) * SR) / FPS);

  const amp = new AmplitudeMouth();
  const A = run((i) => amp.update(rms(x, pos(i) - 512, pos(i)), DT), n);

  const an = new OfflineAnalyser(x, SR);
  const fa = new FrequencyAnalyzer(an, SR, ENGINE_OPTIONS);
  let us = 0;
  const B = run((i) => { an.pos = pos(i); const t = performance.now(); const f = fa.analyze(); us += performance.now() - t; return engineWeights(f); }, n);

  // the same engine on the same clip 6 dB quieter: the classifier has absolute thresholds
  const xq = x.map((v) => v * 0.5), anq = new OfflineAnalyser(xq, SR), faq = new FrequencyAnalyzer(anq, SR, ENGINE_OPTIONS);
  const Bq = run((i) => { anq.pos = pos(i); return engineWeights(faq.analyze()); }, n);
  // how often B shows closed lips on the loudest quarter of the voiced frames (should be ~0: loud = open vowel)
  const voiced = [...env].filter((_, i) => mask[i]).sort((a, b) => a - b), loud = voiced[Math.floor(voiced.length * 0.75)];
  const loudClosed = (m) => { let c = 0, t = 0; for (let i = 0; i < n; i++) if (env[i] >= loud) { t++; if (m.cls[i] === 'closed') c++; } return round(c / Math.max(1, t), 3); };

  // H: HeadAudio worklet processor (vendored, unchanged) fed 128-sample blocks, then its node's hold + ramp
  const msgs = [], proc = new Processor({ sampleRate: SR }, { port: { postMessage: (m) => msgs.push(m), onmessage: null } });
  proc._onmessage({ data: { event: 'model', reset: true, model: haModel } });
  const ramp = new HeadAudioRamp();
  let fed = 0, hus = 0;
  const H = run((i) => {
    const t = performance.now();
    for (; fed + 128 <= pos(i); fed += 128) proc.process(x.subarray(fed, fed + 128));
    hus += performance.now() - t;
    for (const m of msgs.splice(0)) { if (m.event === 'viseme') ramp.viseme(m.viseme, (i * 1000) / FPS); else if (m.event === 'ended') ramp.ended(); }
    return headAudioWeights(ramp.update(1000 / FPS));
  }, n);

  // Hw: the same, after the processor has already heard the clip once (its silence prototype calibrates over ~3 s),
  // which is how it would be mid-conversation
  const msgs2 = [], proc2 = new Processor({ sampleRate: SR }, { port: { postMessage: (m) => msgs2.push(m), onmessage: null } });
  proc2._onmessage({ data: { event: 'model', reset: true, model: haModel } });
  for (let k = 0; k + 128 <= x.length; k += 128) proc2.process(x.subarray(k, k + 128));
  for (let k = 0; k < 4800; k += 128) proc2.process(new Float32Array(128)); // 0.2 s pause between turns
  msgs2.length = 0;
  const ramp2 = new HeadAudioRamp();
  let fed2 = 0;
  const Hw = run((i) => {
    for (; fed2 + 128 <= pos(i); fed2 += 128) proc2.process(x.subarray(fed2, fed2 + 128));
    for (const m of msgs2.splice(0)) { if (m.event === 'viseme') ramp2.viseme(m.viseme, (i * 1000) / FPS); else if (m.event === 'ended') ramp2.ended(); }
    return headAudioWeights(ramp2.update(1000 / FPS));
  }, n);

  const out = { lang: clip.lang, seconds: round(x.length / SR, 2), speakingS: round(mask.filter(Boolean).length / FPS, 2),
    A: { ...describe(A, env, mask), loudClosed: loudClosed(A) },
    B: { ...describe(B, env, mask), loudClosed: loudClosed(B), nodeUsPerFrame: round((us * 1000) / n, 1) },
    Bq: { ...describe(Bq, env, mask), loudClosed: loudClosed(Bq) },
    H: { ...describe(H, env, mask), loudClosed: loudClosed(H), nodeUsPerFrame: round((hus * 1000) / n, 1) },
    Hw: { ...describe(Hw, env, mask), loudClosed: loudClosed(Hw) } };

  const tj = clip.file.replace(/\.mp3$/, '.json');
  let C = null, C0 = null, Cl = null;
  if (fs.existsSync(tj)) {
    const meta = JSON.parse(fs.readFileSync(tj, 'utf8'));
    const cues = cuesFromAlignment(meta.alignment, clip.lang);
    C = run((i) => sampleCues(cues, i / FPS), n);
    Cl = run((i) => sampleCues(cues, i / FPS + LEAD), n); // shown LEAD seconds early, like an animator's lead
    const first = mask.indexOf(true), last = mask.lastIndexOf(true);
    const cues0 = cuesFromAlignment(estimateAlignment(meta.text, first / FPS, (last + 1) / FPS), clip.lang);
    C0 = run((i) => sampleCues(cues0, i / FPS), n);
    out.text = meta.text;
    out.C = { ...describe(C, env, mask), cues: cues.length };
    out.C0 = describe(C0, env, mask);
    out.Cl = { ...describe(Cl, env, mask), leadMs: LEAD * 1000 };
    out.C.loudClosed = loudClosed(C);
    out.vsC = {};
    for (const [k, m] of Object.entries({ A, B, Bq, H, Hw, C0, Cl })) {
      out.vsC[k] = {
        classes: agreement(m.cls, C.cls, mask),
        openingLag: syncLag(m.open, C.open, FPS),
      };
      // closed and rounded onsets are scored separately: each sequence keeps only that class
      out.vsC[k].closedOnsets = onsetTiming(C.cls, m.cls, mask, 'closed', FPS);
      out.vsC[k].roundedOnsets = onsetTiming(C.cls, m.cls, mask, 'rounded', FPS);
    }
  }
  results.clips[clip.id] = out;
  if (SERIES) {
    fs.mkdirSync(`${HERE}/results/series`, { recursive: true });
    const r3 = (a) => a.map((v) => round(v, 3));
    fs.writeFileSync(`${HERE}/results/series/${clip.id}.json`, JSON.stringify({ fps: FPS, env: r3([...env]), A: r3(A.open), B: r3(B.open),
      Bdom: B.dom, H: r3(H.open), Hdom: H.dom, C: C && r3(C.open), Cdom: C && C.dom, C0: C0 && r3(C0.open) }));
  }
}

fs.mkdirSync(`${HERE}/results`, { recursive: true });
fs.writeFileSync(`${HERE}/results/offline.json`, JSON.stringify(results, null, 1));

const pad = (s, w) => String(s ?? '-').padEnd(w);
console.log(pad('clip', 12) + pad('method', 7) + pad('r', 7) + pad('lag ms', 8) + pad('ev/s', 7) + pad('open sp', 9) + pad('open sil', 9)
  + pad('loudCl', 8) + pad('agree C', 9) + pad('chance', 8) + pad('kappa', 7) + pad('closed hit/prec', 15) + pad('|dt| ms', 8) + pad('round hit/prec', 15) + 'C-lag ms');
for (const [id, c] of Object.entries(results.clips)) {
  for (const k of ['A', 'B', 'Bq', 'H', 'Hw', 'C', 'Cl', 'C0']) {
    const m = c[k];
    if (!m) continue;
    const v = c.vsC?.[k];
    console.log(pad(id, 12) + pad(k, 7) + pad(m.r, 7) + pad(m.lagMs, 8) + pad(m.eventsPerS, 7) + pad(m.openSpeaking, 9) + pad(m.openSilent, 9)
      + pad(m.loudClosed, 8) + pad(v?.classes.agree, 9) + pad(v?.classes.chance, 8) + pad(v?.classes.kappa, 7)
      + pad(v ? `${v.closedOnsets.matched}/${v.closedOnsets.onsets} p${v.closedOnsets.precision}` : '', 15) + pad(v?.closedOnsets.medianAbsMs, 8)
      + pad(v ? `${v.roundedOnsets.matched}/${v.roundedOnsets.onsets} p${v.roundedOnsets.precision}` : '', 15) + (v?.openingLag.lagMs ?? ''));
  }
}
