// Round 4 arena (?human=arena4&mode=threejs|a2f): Jasom, the same three.js half body, the same 16.9 s
// conversation, two face drivers (a2fcal = Audio2Face through our rig's calibration profile). threejs = our lip sync (visemes from word timings, the coarticulation of
// engine.ts). a2f = NVIDIA Audio2Face-3D v3.0 ARKit weights, solved offline on a GPU. Body, gaze, blinks and
// breathing are the engine's own in both, so only the face driver differs. ?rec=1 records canvas + audio as webm
// and posts it to the lab file server (lab/a2f/lab_files.py, port 8099).
import { useEffect, useRef, useState } from 'react';
import { HumanEngine } from './engine';
import { HUMAN_URL, bake, lookOf, type Avatar, type Catalog } from './studio/avatar';
import { VISEME_TO_ARKIT, type Weights } from './visemes';

const LAB = 'http://127.0.0.1:8099';
const q = new URLSearchParams(location.search);
const MODE = (['a2f', 'a2fcal'] as const).find((m) => m === q.get('mode')) ?? 'threejs';
const LABEL = { threejs: 'three.js (visemas)', a2f: 'NVIDIA Audio2Face-3D', a2fcal: 'Audio2Face-3D calibrado' }[MODE];
type Calib = Record<string, { rest: number; gain: number }>;
type Cue = { t: number; id: string; w: number };

function visemeMouth(cues: Cue[], now: number): Weights {
  let i = cues.length - 1;
  while (i > 0 && cues[i].t > now) i--;
  const a = cues[i];
  if (!a || a.t > now) return {};
  const b = cues[i + 1], fade = 0.07;
  const k = b && b.t - now < fade ? 1 - (b.t - now) / fade : 0;
  const out: Weights = {};
  const add = (c: Cue, w: number) => { for (const [n, v] of Object.entries(VISEME_TO_ARKIT[c.id] ?? {})) out[n] = (out[n] ?? 0) + v * c.w * w; };
  add(a, 1 - k);
  if (b && k > 0) add(b, k);
  return out;
}

function a2fMouth(frames: number[][], names: string[], now: number, cal?: Calib): Weights {
  if (!frames.length || now < frames[0][0]) return {};
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (frames[m][0] <= now) lo = m; else hi = m - 1; }
  const a = frames[lo], b = frames[Math.min(lo + 1, frames.length - 1)];
  const k = b[0] > a[0] ? Math.min(1, (now - a[0]) / (b[0] - a[0])) : 0;
  const out: Weights = {};
  names.forEach((n, i) => {
    if (n.startsWith('eyeLook')) return; // gaze stays the engine's, as in the other driver
    let v = a[i + 1] * (1 - k) + b[i + 1] * k;
    // calibration profile for our rig (lab/a2f/a2f_calibrate.py): drop the shape's rest bias, then scale
    if (cal?.[n]) v = Math.min(1, cal[n].gain * Math.max(0, v - cal[n].rest));
    if (v > 0.002) out[n] = v;
  });
  return out;
}

export function Arena4() {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState('cargando');

  useEffect(() => {
    const e = new HumanEngine(host.current!, HUMAN_URL, true);
    e.controls.enabled = false;
    const audio = new Audio(`${LAB}/f/conv_mix_16k.wav`);
    audio.crossOrigin = 'anonymous';
    let raf = 0, dead = false;
    let out: HTMLCanvasElement | null = null;
    (async () => {
      const [cat, fit] = await Promise.all([
        fetch(`${HUMAN_URL}/catalog`).then((r) => r.json()) as Promise<Catalog>,
        fetch(`${LAB}/f/twin_fit.json`).then((r) => r.json()),
      ]);
      const avatar: Avatar = {
        pheno: { ...fit.phenotype, gender: 1, age: 0.5, muscle: 0.85, weight: 0.45, height: 0.75, proportions: 0.6 },
        local: fit.local, skin: 'young_caucasian_male2', hair: q.get('hair') ?? 'short04', hairColor: '#2a1d14', eyes: 'brown',
        brows: '', lashes: 'eyelashes01', clothes: ['male_casualsuit04', 'shoes04'],
        tints: { male_casualsuit04: '#f2f2ee' }, accessories: [], faceTexture: `${HUMAN_URL}${fit.texture}`,
      };
      const glb = await bake(cat, avatar);
      if (dead) return;
      await e.load(glb, lookOf(cat, avatar));
      e.frame('bust');
      if (MODE === 'threejs') {
        const v = await fetch(`${LAB}/f/visemes_threejs.json`).then((r) => r.json());
        const cues: Cue[] = v.cues;
        e.mouth = () => visemeMouth(cues, audio.currentTime);
      } else {
        const [csv, names, calib] = await Promise.all([
          fetch(`${LAB}/f/a2f_weights.csv`).then((r) => r.text()),
          fetch(`${LAB}/f/a2f_pose_names.json`).then((r) => r.json()) as Promise<string[]>,
          MODE === 'a2fcal' ? fetch(`${LAB}/f/a2f_calib.json`).then((r) => r.json()) : Promise.resolve(null),
        ]);
        const cal: Calib | undefined = calib?.shapes;
        const frames = csv.trim().split('\n').map((l) => l.split(',').map(Number));
        e.mouth = () => a2fMouth(frames, names, audio.currentTime, cal);
      }
      // composite: sunset plate + the transparent WebGL canvas, so the recording carries the backdrop
      const bg = new Image();
      bg.crossOrigin = 'anonymous';
      bg.src = `${LAB}/f/plate.png`;
      await bg.decode().catch(() => undefined);
      if (dead) return;
      const gl = e.renderer.domElement;
      out = document.createElement('canvas');
      out.width = 720; out.height = 1080;
      out.style.cssText = 'position:fixed;inset:0;margin:auto;height:100vh;z-index:2';
      document.body.appendChild(out);
      const ctx = out.getContext('2d')!;
      const cv = out;
      const draw = () => {
        if (dead) return;
        const out = cv;
        if (bg.naturalWidth) {
          const s = Math.max(out.width / bg.naturalWidth, out.height / bg.naturalHeight);
          const w = bg.naturalWidth * s, h = bg.naturalHeight * s;
          ctx.filter = 'blur(3px)';
          ctx.drawImage(bg, (out.width - w) / 2, (out.height - h) / 2, w, h);
          ctx.filter = 'none';
        } else { ctx.fillStyle = '#6b4a7a'; ctx.fillRect(0, 0, out.width, out.height); }
        const s = Math.max(out.width / gl.width, out.height / gl.height);
        ctx.drawImage(gl, (out.width - gl.width * s) / 2, (out.height - gl.height * s) / 2, gl.width * s, gl.height * s);
        ctx.fillStyle = 'rgba(0,0,0,.45)'; ctx.fillRect(0, out.height - 64, out.width, 64);
        ctx.fillStyle = '#fff'; ctx.font = '600 26px system-ui';
        ctx.fillText(`Jasom · ${LABEL}`, 24, out.height - 22);
        raf = requestAnimationFrame(draw);
      };
      draw();
      setStatus('listo');
      (window as any).arenaPlay = async (rec: boolean) => {
        let mr: MediaRecorder | null = null;
        const chunks: Blob[] = [];
        if (rec) {
          const ac = new AudioContext();
          const src = ac.createMediaElementSource(audio);
          const dst = ac.createMediaStreamDestination();
          src.connect(dst); src.connect(ac.destination);
          const stream = new MediaStream([...cv.captureStream(30).getVideoTracks(), ...dst.stream.getAudioTracks()]);
          mr = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9,opus', videoBitsPerSecond: 6_000_000 });
          mr.ondataavailable = (ev) => chunks.push(ev.data);
          mr.start();
        }
        audio.currentTime = 0;
        await audio.play();
        await new Promise((r) => (audio.onended = r));
        await new Promise((r) => setTimeout(r, 400));
        if (!mr) return 'played';
        await new Promise((r) => { mr!.onstop = r; mr!.stop(); });
        const blob = new Blob(chunks, { type: 'video/webm' });
        const res = await fetch(`${LAB}/save/arena4_${MODE}.webm`, { method: 'POST', body: blob });
        return `saved ${await res.text()} bytes`;
      };
    })().catch((err) => { console.error('arena4', err?.stack ?? err); setStatus(String(err)); });
    return () => { dead = true; cancelAnimationFrame(raf); out?.remove(); audio.pause(); e.dispose(); };
  }, []);

  return (
    <div style={{ position: 'fixed', inset: 0, background: '#111' }}>
      <div ref={host} style={{ position: 'absolute', inset: 0, opacity: 0 }} />
      <div id="arena-status" style={{ position: 'fixed', top: 8, left: 8, zIndex: 3, color: '#fff', font: '12px system-ui' }}>{MODE} · {status}</div>
    </div>
  );
}
