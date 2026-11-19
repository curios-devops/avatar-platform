// Keyframe morph: the whole face changes, not a mouth patch (arena 5 puppet, pilot 2, 2026-11-19).
//
//   const m = await Morph.create(canvas, { base: 'chars/film_w/', tess, mode: 'morph' | 'replace' });
//   m.render({ vis: {aa: .7, E: .3}, pose, laugh, laughPulse, smile, blink: [l, r], gaze, head, breath, dt });
//
// Each character has 8 full-face key poses made once by an image-edit model (kf.py) from its portrait: rest (the
// portrait itself), talk_mid, aa, OU, E, MBP, laugh, blink, each with its own MediaPipe mesh (kfprep.py).
// Every frame:
//   1. keyframe weights from the viseme weights plus a smile, a laugh and a blink channel, separately for the upper
//      face (eyes, brows, cheeks) and the lower face (mouth, jaw), smoothed with attack/release;
//   2. one interpolated mesh: rest + sum of weight x (keyframe mesh aligned to rest on the stable points - rest),
//      per vertex with the upper/lower weights mixed by the vertex's region; then the head rotation and breathing;
//   3. the portrait warped to that mesh as the base layer (hair, neck, clothes, backdrop through 6 outer rings);
//   4. the face oval is cut out with a feathered mask (alpha 0 on the oval, 1 from 12 % of the face width inside)
//      and refilled with the 2 to 4 nearest keyframes, each warped from its own mesh to the interpolated one and
//      added with a sharpened weight (so teeth do not ghost at half weight): no patch edge, no seam.
// 'replace' mode (clay, crochet): stop-motion replacement faces instead of a morph: the strongest keyframe per
// region is swapped in hard, decided on twos (12 Hz, each face held 2 frames of 24), head motion stepped the same.

import { OVAL } from './puppet.js';

const KEYS = ['rest', 'talk_mid', 'aa', 'OU', 'E', 'MBP', 'laugh', 'blink', 'smirk'];  // smirk: closed listening smile (nico)
const INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95];
const EYE_LOOPS = [[33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7],
  [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249]];
const STABLE = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 109, 338, 67, 297, 103, 332, 54, 284, 21, 251, 162, 389, 127, 356, 234, 454];
const RINGS = [1.15, 1.35, 1.65, 2.1, 3.0, 6.0];
const RING_HEAD = [0.92, 0.72, 0.42, 0.15, 0, 0];
const RING_FOLLOW = [0.7, 0.4, 0.15, 0.05, 0, 0];  // how much a ring follows the jaw / cheek of its oval point
// viseme -> lower-face keyframes
const VIS = {
  sil: { rest: 1 }, PP: { MBP: 1 }, FF: { MBP: 0.5, talk_mid: 0.5 }, TH: { talk_mid: 1 }, DD: { talk_mid: 1 },
  kk: { talk_mid: 0.6, aa: 0.4 }, CH: { OU: 0.5, talk_mid: 0.5 }, SS: { talk_mid: 1 }, nn: { talk_mid: 1 },
  RR: { OU: 0.4, talk_mid: 0.6 }, aa: { aa: 1 }, E: { E: 1 }, I: { E: 0.6, talk_mid: 0.4 }, O: { OU: 0.6, aa: 0.4 }, U: { OU: 1 },
};
// colour-weight sharpening: half-weight cross-fades ghost (two sets of eyes, faint teeth on closed lips), so the colour
// switches faster than the shape: the eyes (upper face) as a cut at the half-way point (the shape stays a morph,
// so the lids still travel), the mouth a little softer
// a pose a character lacks (a keyframe rejected at the gate) borrows its nearest neighbour
const FALLBACK = { aa: 'talk_mid', OU: 'talk_mid', E: 'talk_mid', talk_mid: 'rest', laugh: 'E', MBP: 'rest', blink: 'rest', smirk: 'rest' };
const GAMMA_U = 40, GAMMA_L = 10;

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

const VS = `#version 300 es
in vec2 aPos; in vec2 aUv; in float aR; in float aA;
uniform vec4 uView; uniform float uWu, uWl; out vec2 vUv; out float vW;
void main(){ vUv = aUv; vW = mix(uWu, uWl, aR) * aA; gl_Position = vec4((aPos.x - uView.x) * uView.z, -(aPos.y - uView.y) * uView.w, 0., 1.); }`;
const FS = `#version 300 es
precision highp float;
in vec2 vUv; in float vW; uniform sampler2D uTex; uniform vec2 uSize; uniform vec4 uEye[2]; uniform vec2 uGaze[2];
uniform int uMode; out vec4 o;   // 0 opaque, 1 cut (multiply destination by 1 - w), 2 add w x colour
void main(){
  if (uMode == 1) { o = vec4(0., 0., 0., vW); return; }
  vec2 p = vUv;
  for (int i = 0; i < 2; i++) { vec2 d = (p - uEye[i].xy) / uEye[i].zw; float r = dot(d, d); if (r < 1.) p -= uGaze[i] * pow(1. - r, 1.6); }
  vec3 c = texture(uTex, p / uSize).rgb;
  o = uMode == 0 ? vec4(c, 1.) : vec4(c * vW, vW);
}`;

function program(gl) {
  const p = gl.createProgram();
  for (const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS]]) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    gl.attachShader(p, s);
  }
  ['aPos', 'aUv', 'aR', 'aA'].forEach((n, i) => gl.bindAttribLocation(p, i, n));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {};
  for (let i = 0; i < gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i++) {
    const n = gl.getActiveUniform(p, i).name.replace(/\[0\]$/, '');
    u[n] = gl.getUniformLocation(p, n);
  }
  return { p, u };
}

async function loadImage(url) { const img = new Image(); img.src = url; await img.decode(); return img; }

/** Similarity transform (scale, rotation, shift) taking points a onto b, least squares. Returns f(x, y) -> [x, y]. */
function similarity(a, b) {
  const n = a.length;
  let ax = 0, ay = 0, bx = 0, by = 0;
  for (let i = 0; i < n; i++) { ax += a[i][0]; ay += a[i][1]; bx += b[i][0]; by += b[i][1]; }
  ax /= n; ay /= n; bx /= n; by /= n;
  let sxx = 0, sxy = 0, na = 0;
  for (let i = 0; i < n; i++) {
    const x = a[i][0] - ax, y = a[i][1] - ay, u = b[i][0] - bx, v = b[i][1] - by;
    sxx += x * u + y * v; sxy += x * v - y * u; na += x * x + y * y;
  }
  const c = sxx / na, s = sxy / na;
  return (x, y) => [bx + c * (x - ax) - s * (y - ay), by + s * (x - ax) + c * (y - ay)];
}

export class Morph {
  static async create(canvas, { base, tess, mode = 'morph' }) {
    const idx = await fetch(base + 'kf/index.json').then((r) => r.json());
    const keys = KEYS.filter((k) => idx.poses[k]);
    const imgs = await Promise.all(keys.map((k) => loadImage(base + (k === 'rest' ? 'portrait.png' : `kf/${k}.png`))));
    return new Morph(canvas, idx, keys, imgs, tess, mode);
  }

  constructor(canvas, idx, keys, imgs, tess, mode) {
    this.canvas = canvas; this.mode = mode; this.mouth = mode; this.sprites = [];
    this.W = idx.w; this.H = idx.h; this.keys = keys;
    this.vis = { ...VIS, ...(idx.vis || {}) };  // per-character viseme map override (kf/index.json `vis`; nico: O = OU only)
    const gl = this.gl = canvas.getContext('webgl2', { antialias: true, premultipliedAlpha: true, preserveDrawingBuffer: true });
    if (!gl) throw new Error('WebGL2 not available');
    const NL = 478, NF = NL + 1, NO = OVAL.length, V = this.V = NF + RINGS.length * NO;
    this.NF = NF;
    const pts = (k) => {  // keyframe landmarks + mouth centre (vertex 478)
      const p = idx.poses[k].points.map((q) => [q[0], q[1], q[2]]);
      const c = INNER.reduce((a, i) => [a[0] + p[i][0] / INNER.length, a[1] + p[i][1] / INNER.length, a[2] + p[i][2] / INNER.length], [0, 0, 0]);
      p.push(c);
      return p;
    };
    const R = pts('rest');
    this.rest = R;
    const centre = OVAL.reduce((a, i) => [a[0] + R[i][0] / NO, a[1] + R[i][1] / NO, a[2] + R[i][2] / NO], [0, 0, 0]);
    // ring vertices: scaled copies of the oval
    this.ringOf = [];
    for (let k = 0; k < RINGS.length; k++) OVAL.forEach((o, j) => {
      R.push([centre[0] + (R[o][0] - centre[0]) * RINGS[k], centre[1] + (R[o][1] - centre[1]) * RINGS[k], centre[2] + 40 * k]);
      this.ringOf.push([o, k]);
    });
    const fw = Math.hypot(R[454][0] - R[234][0], R[454][1] - R[234][1]);
    this.fh = Math.hypot(R[10][0] - R[152][0], R[10][1] - R[152][1]);
    // per keyframe: texture coordinates (its own pixels) and its geometry offset, aligned to rest on stable points
    this.kf = keys.map((k, n) => {
      const P = k === 'rest' ? R.slice(0, NF) : pts(k);
      const f = similarity(STABLE.map((i) => P[i]), STABLE.map((i) => R[i]));
      const uv = new Float32Array(V * 2), off = new Float32Array(NF * 2);
      for (let i = 0; i < V; i++) { const q = i < NF ? P[i] : R[i]; uv[i * 2] = q[0]; uv[i * 2 + 1] = q[1]; }
      for (let i = 0; i < NF; i++) { const [x, y] = f(P[i][0], P[i][1]); off[i * 2] = x - R[i][0]; off[i * 2 + 1] = y - R[i][1]; }
      const eyes = [468, 473].map((i) => [P[i][0], P[i][1]]);
      return { name: k, uv, off, eyes, tex: this.texture(imgs[n]), uvBuf: this.staticBuf(uv) };
    });
    // triangles: tessellation + eye fans + mouth fan (overlay); + rings (base)
    const tris = [...tess];
    EYE_LOOPS.forEach((loop, e) => {
      const c = loop.reduce((a, i) => [a[0] + R[i][0], a[1] + R[i][1]], [0, 0]).map((v) => v / loop.length);
      const iris = [468, 473].sort((a, b) => Math.hypot(R[a][0] - c[0], R[a][1] - c[1]) - Math.hypot(R[b][0] - c[0], R[b][1] - c[1]))[0];
      loop.forEach((v, j) => tris.push(iris, v, loop[(j + 1) % loop.length]));
    });
    INNER.forEach((v, j) => tris.push(NL, v, INNER[(j + 1) % INNER.length]));
    const over = [...tris];
    const ringIdx = (k, j) => (k < 0 ? OVAL[j % NO] : NF + k * NO + (j % NO));
    for (let k = -1; k < RINGS.length - 1; k++) for (let j = 0; j < NO; j++) {
      const a = ringIdx(k, j), b = ringIdx(k, j + 1), c = ringIdx(k + 1, j), d = ringIdx(k + 1, j + 1);
      tris.push(a, c, b, b, c, d);
    }
    const ib = (a) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, b); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(a), gl.STATIC_DRAW); return { b, n: a.length }; };
    this.baseIdx = ib(tris); this.overIdx = ib(over);
    // feather: distance inside the rest oval; region: 0 upper face .. 1 lower face (eye line -> below the nose)
    const poly = OVAL.map((i) => R[i]);
    const segDist = (p, a, b) => {
      const dx = b[0] - a[0], dy = b[1] - a[1], t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)));
      return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
    };
    const alpha = new Float32Array(V), region = new Float32Array(V);
    const eyeY = (R[159][1] + R[386][1]) / 2, noseY = R[2][1];
    for (let i = 0; i < NF; i++) {
      let d = Infinity;
      for (let j = 0; j < NO; j++) d = Math.min(d, segDist(R[i], poly[j], poly[(j + 1) % NO]));
      alpha[i] = OVAL.includes(i) ? 0 : smooth(0, 0.12 * fw, d);
      region[i] = smooth(eyeY + 0.3 * (noseY - eyeY), noseY + 0.15 * (noseY - eyeY), R[i][1]);
    }
    this.alphaBuf = this.staticBuf(alpha);
    this.regionBuf = this.staticBuf(region);
    this.region = region;
    this.oneBuf = this.staticBuf(new Float32Array(V).fill(1));
    // head motion weight and pivot, breathing (as in puppet.js)
    const chin = R[152], dn = [(chin[0] - R[168][0]), (chin[1] - R[168][1])];
    const dl = Math.hypot(dn[0], dn[1]); dn[0] /= dl; dn[1] /= dl;
    this.headW = new Float32Array(V).fill(1); this.breathW = new Float32Array(V);
    for (let i = NF; i < V; i++) {
      const k = this.ringOf[i - NF][1];
      const below = (R[i][0] - chin[0]) * dn[0] + (R[i][1] - chin[1]) * dn[1];
      this.headW[i] = RING_HEAD[k] * (below > 0 ? 1 - smooth(0, 0.35 * this.fh, below) * 0.85 : 1);
      this.breathW[i] = smooth(0.05 * this.fh, 0.5 * this.fh, below);
    }
    this.pivot = [chin[0] + dn[0] * 0.15 * this.fh, chin[1] + dn[1] * 0.15 * this.fh, centre[2] + 0.35 * this.fh];
    this.eyeR = EYE_LOOPS.map((loop) => {
      const xs = loop.map((i) => R[i][0]), ys = loop.map((i) => R[i][1]);
      return [(Math.max(...xs) - Math.min(...xs)) / 2 * 1.05, (Math.max(...ys) - Math.min(...ys)) / 2 * 1.25];
    });
    this.mc = [(R[61][0] + R[291][0]) / 2, (R[61][1] + R[291][1]) / 2];
    this.pos = new Float32Array(V * 2);
    this.posBuf = gl.createBuffer();
    this.prog = program(gl);
    this.vao = gl.createVertexArray();
    this.wU = Object.fromEntries(keys.map((k) => [k, k === 'rest' ? 1 : 0]));
    this.wL = { ...this.wU };
    this.tick = -1; this.held = null;
    this.setView();
  }

  texture(img) {
    const gl = this.gl, t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    for (const w of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D, w, gl.CLAMP_TO_EDGE);
    return t;
  }

  staticBuf(arr) { const gl = this.gl, b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW); return b; }

  setView(zoom = 1) {
    const c = this.canvas, aspect = c.width / c.height;
    let h = this.H / zoom, w = h * aspect;
    if (w > this.W / zoom) { w = this.W / zoom; h = w / aspect; }
    const cx = Math.min(this.W - w / 2, Math.max(w / 2, this.mc[0]));
    const cy = Math.min(this.H - h / 2, Math.max(h / 2, this.rest[168][1] + h * 0.08));
    this.view = [cx, cy, 2 / w, 2 / h];
  }

  /** Target keyframe weights per region from the channels. */
  targets(st) {
    const has = (k) => this.keys.includes(k);
    const add = (o, k, w) => {
      if (!(w > 0)) return;
      while (!has(k)) k = FALLBACK[k] || 'rest';
      o[k] = (o[k] || 0) + w;
    };
    const vis = {};
    let sum = 0;
    for (const [id, w] of Object.entries(st.vis || { sil: 1 })) { if (!(w > 0)) continue; sum += w; for (const [k, f] of Object.entries(this.vis[id] || VIS.sil)) add(vis, k, w * f); }
    if (sum < 1) add(vis, 'rest', 1 - sum);
    const s = Math.min(1, st.expressSmile || 0), l = Math.min(1, st.laugh || 0), p = st.laughPulse ?? 1;
    const b = Math.max(st.blink?.[0] || 0, st.blink?.[1] || 0);
    const lo = {}, up = {};
    // smirk (listening): the rest share of the lower face, and a little of the upper face, becomes the closed smile
    const sm = this.keys.includes('smirk') ? Math.min(1, st.smirk || 0) : 0;
    if (sm > 0 && vis.rest) { add(vis, 'smirk', vis.rest * sm); vis.rest *= 1 - sm; }
    for (const [k, w] of Object.entries(vis)) add(lo, k, w * (1 - l) * (1 - s));
    add(lo, 'E', (1 - l) * s);
    add(lo, 'laugh', l * p); add(lo, 'E', l * (1 - p));
    add(up, 'laugh', l);
    add(up, 'blink', (1 - l) * b);
    add(up, 'E', (1 - l) * (1 - b) * s * 0.7);
    add(up, 'smirk', (1 - l) * (1 - b) * (1 - s * 0.7) * sm * 0.6);
    add(up, 'rest', (1 - l) * (1 - b) * (1 - s * 0.7) * (1 - sm * 0.6));
    return { up, lo };
  }

  weights(st) {
    const { up, lo } = this.targets(st), dt = st.dt ?? 1 / 60;
    if (this.mode === 'replace') {
      // stop motion: decide on twos (12 Hz); each region shows its strongest face, hard swap
      const tick = Math.floor((st.t ?? 0) * 12);
      if (tick !== this.tick || !this.held) {
        this.tick = tick;
        const best = (o) => Object.entries(o).sort((a, b) => b[1] - a[1])[0][0];
        const bu = best(up), bl = best(lo);
        this.held = { up: Object.fromEntries(this.keys.map((k) => [k, k === bu ? 1 : 0])), lo: Object.fromEntries(this.keys.map((k) => [k, k === bl ? 1 : 0])), head: st.head, breath: st.breath };
      }
      return { gu: this.held.up, gl: this.held.lo, cu: this.held.up, cl: this.held.lo };
    }
    const step = (cur, tgt) => {
      let s = 0;
      for (const k of this.keys) {
        const t = tgt[k] || 0, tau = t > cur[k] ? 0.035 : 0.06;
        cur[k] += (t - cur[k]) * (1 - Math.exp(-dt / tau)); s += cur[k];
      }
      for (const k of this.keys) cur[k] /= s || 1;
      return cur;
    };
    step(this.wU, up); step(this.wL, lo);
    const sharp = (w, g) => {
      const o = {}; let s = 0;
      for (const k of this.keys) { o[k] = w[k] ** g; s += o[k]; }
      for (const k of this.keys) o[k] /= s || 1;
      return o;
    };
    return { gu: this.wU, gl: this.wL, cu: sharp(this.wU, GAMMA_U), cl: sharp(this.wL, GAMMA_L) };
  }

  deform(w, st) {
    const out = this.pos, R = this.rest, NF = this.NF, V = this.V, reg = this.region;
    for (let i = 0; i < NF; i++) { out[i * 2] = R[i][0]; out[i * 2 + 1] = R[i][1]; }
    for (const kf of this.kf) {
      const u = w.gu[kf.name], l = w.gl[kf.name];
      if (u < 1e-4 && l < 1e-4) continue;
      for (let i = 0; i < NF; i++) { const f = u + (l - u) * reg[i]; out[i * 2] += kf.off[i * 2] * f; out[i * 2 + 1] += kf.off[i * 2 + 1] * f; }
    }
    for (let i = NF; i < V; i++) {
      const [o, k] = this.ringOf[i - NF], f = RING_FOLLOW[k];
      out[i * 2] = R[i][0] + (out[o * 2] - R[o][0]) * f;
      out[i * 2 + 1] = R[i][1] + (out[o * 2 + 1] - R[o][1]) * f;
    }
    const h = this.mode === 'replace' && this.held ? this.held.head : st.head;
    if (h) {
      const [px, py, pz] = this.pivot;
      const cy = Math.cos(h.yaw), sy = Math.sin(h.yaw), cp = Math.cos(h.pitch), sp = Math.sin(h.pitch), cr = Math.cos(h.roll), sr = Math.sin(h.roll);
      for (let i = 0; i < V; i++) {
        const hw = this.headW[i];
        if (!hw) continue;
        const x0 = out[i * 2] - px, y0 = out[i * 2 + 1] - py, z0 = R[i][2] - pz;
        const x1 = x0 * cy + z0 * sy, z1 = -x0 * sy + z0 * cy;
        const y1 = y0 * cp - z1 * sp;
        const x2 = x1 * cr - y1 * sr, y2 = x1 * sr + y1 * cr;
        out[i * 2] += (x2 - x0 + (h.tx || 0)) * hw;
        out[i * 2 + 1] += (y2 - y0 + (h.ty || 0)) * hw;
      }
    }
    const br = this.mode === 'replace' && this.held ? this.held.breath : st.breath;
    if (br) for (let i = 0; i < V; i++) out[i * 2 + 1] -= br * (this.breathW[i] * 2.2 + this.headW[i] * 1.0);
  }

  bind(uvBuf, alphaBuf) {
    const gl = this.gl;
    for (const [loc, buf, n] of [[0, this.posBuf, 2], [1, uvBuf, 2], [2, this.regionBuf, 1], [3, alphaBuf, 1]]) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, n, gl.FLOAT, false, 0, 0);
    }
  }

  /** One frame. Returns the rendered inner-lip gap in portrait pixels (for the lag metric). */
  render(st) {
    const gl = this.gl, { p, u } = this.prog;
    const w = this.weights(st);
    this.last = w;
    this.deform(w, st);
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, this.pos, gl.DYNAMIC_DRAW);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(p);
    gl.uniform4fv(u.uView, this.view);
    gl.uniform2f(u.uSize, this.W, this.H);
    const g = this.mode === 'replace' ? [0, 0] : (st.gaze || [0, 0]);
    gl.uniform2fv(u.uGaze, this.eyeR.flatMap((r) => [g[0] * r[0] * 0.3, g[1] * r[1] * 0.25]));
    const eyes = (kf) => gl.uniform4fv(u.uEye, kf.eyes.flatMap((c, i) => [...c, ...this.eyeR[i]]));
    gl.activeTexture(gl.TEXTURE0); gl.uniform1i(u.uTex, 0);
    // 1. base: the portrait over the whole mesh
    const rest = this.kf[0];
    gl.disable(gl.BLEND);
    this.bind(rest.uvBuf, this.oneBuf);
    eyes(rest);
    gl.uniform1i(u.uMode, 0); gl.uniform1f(u.uWu, 1); gl.uniform1f(u.uWl, 1);
    gl.bindTexture(gl.TEXTURE_2D, rest.tex);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.baseIdx.b);
    gl.drawElements(gl.TRIANGLES, this.baseIdx.n, gl.UNSIGNED_SHORT, 0);
    // 2. cut the face oval, feathered. Depth test per pass: where interpolated triangles fold over each other (mouth
    //    corners in a laugh) a pixel is still counted once, otherwise the additive passes brighten it
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS);
    gl.clear(gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ZERO, gl.ONE_MINUS_SRC_ALPHA);
    this.bind(rest.uvBuf, this.alphaBuf);
    gl.uniform1i(u.uMode, 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.overIdx.b);
    gl.drawElements(gl.TRIANGLES, this.overIdx.n, gl.UNSIGNED_SHORT, 0);
    // 3. refill it with the weighted keyframes
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.uniform1i(u.uMode, 2);
    for (const kf of this.kf) {
      const cu = w.cu[kf.name], cl = w.cl[kf.name];
      if (cu < 0.003 && cl < 0.003) continue;
      this.bind(kf.uvBuf, this.alphaBuf);
      eyes(kf);
      gl.uniform1f(u.uWu, cu); gl.uniform1f(u.uWl, cl);
      gl.clear(gl.DEPTH_BUFFER_BIT);
      gl.bindTexture(gl.TEXTURE_2D, kf.tex);
      gl.drawElements(gl.TRIANGLES, this.overIdx.n, gl.UNSIGNED_SHORT, 0);
    }
    gl.disable(gl.DEPTH_TEST);
    const o = this.pos;
    return Math.hypot(o[14 * 2] - o[13 * 2], o[14 * 2 + 1] - o[13 * 2 + 1]);
  }
}
