// Styled portrait puppet: one portrait image animated in WebGL2 over its MediaPipe face landmarks.
//
//   const p = await Puppet.create(canvas, { base: 'chars/film_w/', tess, mouth: 'drawn' | 'sprites' });
//   p.render({ pose, blink: [l, r], gaze: [x, y], head: {yaw, pitch, roll, tx, ty}, brow, smile, breath, sprites });
//
// Mesh: MediaPipe's 852 face triangles (mouth and eyes are holes there), a fan filling each eye around the iris
// centre, and 6 rings scaled from the face oval out past the image edge (hair, neck, shoulders, backdrop).
// Motion: per-vertex bases built once from the landmarks (jaw, lip part, upper-lip lift, width, round, press, tuck,
// smile, brows, a blink per eye), then a small 3D head rotation using the landmark depth for parallax, then breathing.
// Gaze moves the iris with a fragment-level warp inside each eye. The mouth hole shows one of two inner mouths:
//   'drawn'    a procedural layer under the lips: dark cavity, upper and lower teeth, tongue, tinted from the portrait
//   'sprites'  images made once per character by image-to-image (gen.py mouths) from this puppet's own render of
//              each shape, mapped through the same mesh, and blended over the lips and the hole by viseme distance.

import { SHAPES } from '../lipsync/lib/visemes.js';

export const OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148,
  176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
const UPPER_CHAIN = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308];
const LOWER_CHAIN = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308];
const UPPER_INNER = UPPER_CHAIN.slice(1, -1), LOWER_INNER = LOWER_CHAIN.slice(1, -1);
const UPPER_OUTER = [185, 40, 39, 37, 0, 267, 269, 270, 409], LOWER_OUTER = [146, 91, 181, 84, 17, 314, 405, 321, 375];
const EYES = [
  { upper: [246, 161, 160, 159, 158, 157, 173], lower: [7, 163, 144, 145, 153, 154, 155], crease: [247, 30, 29, 27, 28, 56, 190],
    loop: [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7] },
  { upper: [466, 388, 387, 386, 385, 384, 398], lower: [249, 390, 373, 374, 380, 381, 382], crease: [467, 260, 259, 257, 258, 286, 414],
    loop: [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249] },
];
const BROWS = [70, 63, 105, 66, 107, 46, 53, 52, 65, 55, 300, 293, 334, 296, 336, 276, 283, 282, 295, 285];
const RINGS = [1.15, 1.35, 1.65, 2.1, 3.0, 6.0];
const RING_HEAD = [0.92, 0.72, 0.42, 0.15, 0, 0];
// Mouth images made per character, and the viseme pose each one was rendered at.
export const SPRITE_POSES = { mid: SHAPES.DD, aa: SHAPES.aa, E: SHAPES.E, O: SHAPES.O, FF: SHAPES.FF };
const BASES = ['open', 'part', 'teeth', 'width', 'round', 'press', 'tuck', 'smile', 'brow', 'blinkL', 'blinkR'];

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

const VS_FACE = `#version 300 es
in vec2 aPos; in vec2 aUv; in float aAlpha;
uniform vec4 uView; out vec2 vUv; out float vAlpha;
void main(){ vUv = aUv; vAlpha = aAlpha; gl_Position = vec4((aPos.x - uView.x) * uView.z, -(aPos.y - uView.y) * uView.w, 0., 1.); }`;
const FS_FACE = `#version 300 es
precision highp float;
in vec2 vUv; in float vAlpha; uniform sampler2D uTex; uniform vec2 uSize; uniform vec4 uEye[2]; uniform vec2 uGaze[2];
uniform float uOpacity; out vec4 o;
void main(){
  vec2 p = vUv;   // source pixels
  for (int i = 0; i < 2; i++) {     // gaze: push the iris inside the eye, the eye outline stays
    vec2 d = (p - uEye[i].xy) / uEye[i].zw; float r = dot(d, d);
    if (r < 1.) p -= uGaze[i] * pow(1. - r, 1.6);
  }
  vec4 c = texture(uTex, p / uSize);
  o = vec4(c.rgb, 1.) * (vAlpha * uOpacity);
}`;
const FS_MOUTH = `#version 300 es
precision highp float;
in vec2 vUv; in float vAlpha; out vec4 o;
uniform vec2 uL, uR, uUp, uLo; uniform float uOpen, uTeeth, uTongue, uTuck; uniform vec3 uLip, uTooth;
float band(float x, float a, float w){ return smoothstep(a - w, a + w, x); }
void main(){
  vec2 p = vUv;  // deformed pixels here (aUv carries the position)
  vec2 mid = (uL + uR) * .5, ax = uR - uL; float len = length(ax); vec2 a = ax / len, n = vec2(-a.y, a.x);
  if (dot(n, uLo - mid) < 0.) n = -n;
  float x = dot(p - mid, a) / (len * .5), y = dot(p - mid, n), aa = len * .006 + .6;
  float yU = dot(uUp - mid, n) * (1. - x * x), yL = dot(uLo - mid, n) * (1. - x * x);
  float gap = max(yL - yU, .001);
  // cavity: dark, a little lighter at the centre top, darker at the corners
  vec3 cav = uLip * (.16 + .1 * (1. - abs(x))) * (.75 + .25 * band(y, yU, gap * .5));
  // upper teeth hang from the upper lip; F/V lays them on the lower lip
  float tH = len * (.085 + .04 * uTeeth) + uTuck * gap;
  float upT = (1. - band(y, yU + tH, aa)) * (1. - smoothstep(.62, .85, abs(x)));
  float gaps = 1. - .35 * (exp(-pow(x / .018, 2.)) + exp(-pow((abs(x) - .2) / .016, 2.)) + .7 * exp(-pow((abs(x) - .38) / .016, 2.)));
  vec3 teeth = uTooth * gaps * (1. - .45 * x * x) * (.78 + .22 * band(y, yU + tH * .25, tH * .4));
  // lower teeth only when the jaw is well open
  float loT = band(y, yL - len * .05, aa) * (1. - smoothstep(.5, .7, abs(x))) * smoothstep(.45, .8, uOpen);
  vec3 lteeth = uTooth * .8 * gaps;
  // tongue: low and wide, lifts toward the teeth for T, D, N, L
  vec2 tc = vec2(0., yL - len * (.06 + .1 * uTongue));
  vec2 td = vec2(x / .62, (y - tc.y) / (len * .13));
  float tg = 1. - smoothstep(.85, 1., length(td));
  vec3 tongue = mix(uLip * .55, vec3(.72, .38, .38), .4) * (.7 + .3 * (1. - td.y * .5));
  vec3 c = cav;
  c = mix(c, tongue, tg * smoothstep(.15, .4, uOpen + uTongue));
  c = mix(c, lteeth, loT);
  c = mix(c, teeth, upT);
  // soft shadow just inside both lips
  c *= .55 + .45 * band(y, yU + gap * .05, gap * .12) * (1. - band(y, yL - gap * .08, gap * .12) * .5);
  o = vec4(c, 1.);
}`;

function program(gl, vs, fs) {
  const p = gl.createProgram();
  for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    gl.attachShader(p, s);
  }
  gl.bindAttribLocation(p, 0, 'aPos'); gl.bindAttribLocation(p, 1, 'aUv'); gl.bindAttribLocation(p, 2, 'aAlpha');
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {};
  for (let i = 0; i < gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i++) {
    const n = gl.getActiveUniform(p, i).name.replace(/\[0\]$/, '');
    u[n] = gl.getUniformLocation(p, n);
  }
  return { p, u };
}

async function loadImage(url) {
  const img = new Image();
  img.src = url;
  await img.decode();
  return img;
}

export class Puppet {
  static async create(canvas, opts) {
    const [lm, img] = await Promise.all([fetch(opts.base + 'landmarks.json').then((r) => r.json()), loadImage(opts.base + 'portrait.png')]);
    const p = new Puppet(canvas, lm, img, opts);
    if (opts.sprites?.length) await p.loadSprites(opts.base, opts.sprites);
    return p;
  }

  constructor(canvas, lm, img, { tess, mouth = 'drawn' }) {
    this.canvas = canvas;
    this.mouth = mouth;
    this.W = lm.w; this.H = lm.h;
    const gl = this.gl = canvas.getContext('webgl2', { antialias: true, premultipliedAlpha: true, preserveDrawingBuffer: true });
    if (!gl) throw new Error('WebGL2 not available');
    this.buildMesh(lm.points, tess);
    this.buildBases();
    this.sampleColours(img);
    this.face = program(gl, VS_FACE, FS_FACE);
    this.mouthProg = program(gl, VS_FACE, FS_MOUTH);
    this.tex = this.texture(img);
    this.sprites = [];
    const V = this.V;
    this.pos = new Float32Array(V * 2);
    this.cur = new Float32Array(V * 2);
    this.posBuf = gl.createBuffer();
    this.uvBuf = this.staticBuf(this.rest2);
    this.oneBuf = this.staticBuf(new Float32Array(V).fill(1));
    this.alphaBuf = this.staticBuf(this.patchAlpha);
    this.idx = (a) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, b); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(a), gl.STATIC_DRAW); return { b, n: a.length }; };
    this.faceIdx = this.idx(this.faceTris);
    this.mouthIdx = this.idx(this.mouthTris);
    this.patchIdx = this.idx(this.patchTris);
    this.vao = gl.createVertexArray();
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

  staticBuf(arr) {
    const gl = this.gl, b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
    return b;
  }

  buildMesh(points, tess) {
    const NL = points.length, NR = RINGS.length, NO = OVAL.length;
    this.V = NL + NR * NO;
    const rest = this.rest = new Float32Array(this.V * 3);
    points.forEach((p, i) => rest.set(p, i * 3));
    const P = (i) => [rest[i * 3], rest[i * 3 + 1], rest[i * 3 + 2]];
    this.P = P;
    let cx = 0, cy = 0, cz = 0;
    for (const i of OVAL) { cx += P(i)[0]; cy += P(i)[1]; cz += P(i)[2]; }
    cx /= NO; cy /= NO; cz /= NO;
    this.ovalZ = cz;
    RINGS.forEach((s, k) => OVAL.forEach((o, j) => {
      const [x, y] = P(o);
      rest.set([cx + (x - cx) * s, cy + (y - cy) * s, cz + 40 * k], (NL + k * NO + j) * 3);
    }));
    this.rest2 = new Float32Array(this.V * 2);  // texture coordinates: the portrait's own pixels
    for (let i = 0; i < this.V; i++) { this.rest2[i * 2] = rest[i * 3]; this.rest2[i * 2 + 1] = rest[i * 3 + 1]; }
    // positions: the inner lips meet on their midline at rest, so a portrait with a slight gap shows no seam
    UPPER_INNER.forEach((u, j) => {
      const l = LOWER_INNER[j];
      for (const k of [0, 1]) { const m = (rest[u * 3 + k] + rest[l * 3 + k]) / 2; rest[u * 3 + k] = m; rest[l * 3 + k] = m; }
    });
    const tris = [...tess];
    // eye fans around the nearer iris centre (468 / 473)
    this.eyeCentre = EYES.map((e) => {
      const c = e.loop.reduce((a, i) => [a[0] + P(i)[0] / e.loop.length, a[1] + P(i)[1] / e.loop.length], [0, 0]);
      const iris = [468, 473].sort((a, b) => Math.hypot(P(a)[0] - c[0], P(a)[1] - c[1]) - Math.hypot(P(b)[0] - c[0], P(b)[1] - c[1]))[0];
      e.loop.forEach((v, j) => tris.push(iris, v, e.loop[(j + 1) % e.loop.length]));
      return iris;
    });
    // rings: oval -> ring 0 -> ... -> ring 5
    const ringIdx = (k, j) => (k < 0 ? OVAL[j % NO] : NL + k * NO + (j % NO));
    for (let k = -1; k < NR - 1; k++) for (let j = 0; j < NO; j++) {
      const a = ringIdx(k, j), b = ringIdx(k, j + 1), c = ringIdx(k + 1, j), d = ringIdx(k + 1, j + 1);
      tris.push(a, c, b, b, c, d);
    }
    this.faceTris = tris;
    const mouth = [];
    for (let i = 0; i < UPPER_CHAIN.length - 1; i++) mouth.push(UPPER_CHAIN[i], UPPER_CHAIN[i + 1], LOWER_CHAIN[i + 1], UPPER_CHAIN[i], LOWER_CHAIN[i + 1], LOWER_CHAIN[i]);
    this.mouthTris = mouth;
    // the face frame: down = nose bridge -> chin
    const b = P(168), ch = P(152);
    const dl = Math.hypot(ch[0] - b[0], ch[1] - b[1]);
    this.down = [(ch[0] - b[0]) / dl, (ch[1] - b[1]) / dl];
    this.right = [this.down[1], -this.down[0]];
    if (this.right[0] < 0) this.right = this.right.map((v) => -v);
    this.fh = Math.hypot(P(10)[0] - ch[0], P(10)[1] - ch[1]);
    this.mw = Math.hypot(P(291)[0] - P(61)[0], P(291)[1] - P(61)[1]);
    this.mc = [(P(61)[0] + P(291)[0]) / 2, (P(61)[1] + P(291)[1]) / 2];
    // sprite patch: face triangles around the mouth plus the hole, feathered at the edge
    const R = 0.95 * this.mw;
    this.patchAlpha = new Float32Array(this.V);
    for (let i = 0; i < this.V; i++) {
      const d = Math.hypot((rest[i * 3] - this.mc[0]) / 1.0, (rest[i * 3 + 1] - this.mc[1] - 0.15 * this.mw) / 1.15);
      this.patchAlpha[i] = 1 - smooth(0.55 * R, R, d);
    }
    const pt = [];
    for (let t = 0; t < tess.length; t += 3) if ([0, 1, 2].some((k) => this.patchAlpha[tess[t + k]] > 0)) pt.push(tess[t], tess[t + 1], tess[t + 2]);
    this.patchTris = pt;
    this.eyes = EYES.map((e, k) => {
      const xs = e.loop.map((i) => P(i)[0]), ys = e.loop.map((i) => P(i)[1]);
      const c = P(this.eyeCentre[k]);
      return { c: [c[0], c[1]], r: [(Math.max(...xs) - Math.min(...xs)) / 2 * 1.05, (Math.max(...ys) - Math.min(...ys)) / 2 * 1.25] };
    });
  }

  local(i) {
    const x = this.rest[i * 3] - this.mc[0], y = this.rest[i * 3 + 1] - this.mc[1];
    return [(x * this.right[0] + y * this.right[1]) / this.mw, (x * this.down[0] + y * this.down[1]) / this.mw];
  }

  buildBases() {
    const V = this.V, NL = 478, P = this.P, fh = this.fh, mw = this.mw, dn = this.down, rt = this.right;
    const B = this.bases = Object.fromEntries(BASES.map((k) => [k, new Float32Array(V * 2)]));
    const add = (k, i, dx, dy) => { B[k][i * 2] += dx; B[k][i * 2 + 1] += dy; };
    const set = (k, i, dx, dy) => { B[k][i * 2] = dx; B[k][i * 2 + 1] = dy; };
    const cornerX = Math.abs(this.local(308)[0]) || 0.4;
    const lens = (i) => { const x = this.local(i)[0]; return Math.max(0, 1 - (x / (cornerX * 1.05)) ** 2); };
    const lipT = (a, b) => Math.hypot(P(a)[0] - P(b)[0], P(a)[1] - P(b)[1]);
    const upT = lipT(0, 13), loT = lipT(14, 17);
    const chin = P(152);
    const jaw = 0.12 * fh;
    // the closed-lip seam as a curve ly(lx), so "below the mouth" follows the real lip line (smiles bend it)
    const seam = UPPER_CHAIN.map((i) => this.local(i)).sort((a, b) => a[0] - b[0]);
    const seamAt = (x) => {
      if (x <= seam[0][0]) return seam[0][1];
      for (let j = 1; j < seam.length; j++) if (x <= seam[j][0]) { const [a, b] = [seam[j - 1], seam[j]]; return a[1] + ((b[1] - a[1]) * (x - a[0])) / (b[0] - a[0]); }
      return seam[seam.length - 1][1];
    };
    for (let i = 0; i < V; i++) {
      const [lx, ly0] = this.local(i);
      const ly = ly0 - seamAt(lx);
      if (i < NL) {
        // jaw: everything under the mouth line, fading toward the ears
        let w = smooth(-0.02, 0.24, ly) * (1 - smooth(0.75, 1.6, Math.abs(lx)));
        if (ly > 0.004 && Math.abs(lx) < cornerX * 1.05) w = Math.max(w, 0.35 + 0.65 * lens(i));  // lower lip moves as one
        set('open', i, dn[0] * jaw * w, dn[1] * jaw * w);
        // brows and forehead skin
        let bw = 0;
        for (const j of BROWS) bw = Math.max(bw, Math.exp(-((Math.hypot(P(j)[0] - P(i)[0], P(j)[1] - P(i)[1]) / (0.09 * fh)) ** 2)));
        bw *= smooth(-0.02, 0.06, (P(105)[1] + P(334)[1]) / 2 / fh + 0.06 - P(i)[1] / fh);
        set('brow', i, -dn[0] * 0.024 * fh * bw, -dn[1] * 0.024 * fh * bw);
      } else {
        const k = Math.floor((i - NL) / OVAL.length);
        const below = (this.rest[i * 3] - chin[0]) * dn[0] + (this.rest[i * 3 + 1] - chin[1]) * dn[1];
        const w = below > -0.05 * fh ? [0.6, 0.25, 0.08, 0, 0, 0][k] * (1 - smooth(0.6, 1.4, Math.abs(lx))) : 0;
        set('open', i, dn[0] * jaw * w, dn[1] * jaw * w);
      }
      // corners: width, round and smile
      let g = 0, side = Math.sign(lx) || 1;
      for (const c of [61, 291, 78, 308]) g = Math.max(g, Math.exp(-((Math.hypot(P(c)[0] - this.rest[i * 3], P(c)[1] - this.rest[i * 3 + 1]) / (0.3 * mw)) ** 2)));
      const gw = i < NL ? g : 0;
      add('width', i, side * rt[0] * 0.6 * mw * gw, side * rt[1] * 0.6 * mw * gw);
      add('round', i, -side * rt[0] * 0.22 * mw * gw, -side * rt[1] * 0.22 * mw * gw);
      add('smile', i, side * rt[0] * 0.05 * mw * gw - dn[0] * 0.035 * fh * gw, side * rt[1] * 0.05 * mw * gw - dn[1] * 0.035 * fh * gw);
    }
    // the lips themselves: overrides
    for (const i of LOWER_INNER) { const l = 0.35 + 0.65 * lens(i); set('open', i, dn[0] * jaw * l, dn[1] * jaw * l); }
    for (const i of LOWER_OUTER) { const l = 0.45 + 0.55 * lens(i); set('open', i, dn[0] * jaw * l, dn[1] * jaw * l); }
    for (const i of [78, 308]) set('open', i, dn[0] * jaw * 0.3, dn[1] * jaw * 0.3);
    for (const i of [61, 291]) set('open', i, dn[0] * jaw * 0.28, dn[1] * jaw * 0.28);
    for (const i of [...UPPER_INNER, ...UPPER_OUTER]) set('open', i, 0, 0);
    const lip = (k, list, amt) => { for (const i of list) { const l = lens(i); add(k, i, dn[0] * amt * l, dn[1] * amt * l); } };
    lip('part', UPPER_INNER, -0.02 * fh); lip('part', LOWER_INNER, 0.02 * fh);
    lip('teeth', UPPER_INNER, -0.02 * fh); lip('teeth', UPPER_OUTER, -0.011 * fh);
    lip('round', UPPER_INNER, -0.012 * fh); lip('round', LOWER_INNER, 0.012 * fh);
    lip('round', UPPER_OUTER, -0.006 * fh); lip('round', LOWER_OUTER, 0.006 * fh);
    lip('press', UPPER_OUTER, 0.3 * upT); lip('press', LOWER_OUTER, -0.3 * loT);
    lip('tuck', LOWER_INNER, -0.016 * fh); lip('tuck', LOWER_OUTER, -0.3 * loT);
    // blinks: upper lid onto the lower lid, crease follows halfway, iris centre in between
    EYES.forEach((e, k) => {
      const key = k ? 'blinkR' : 'blinkL';
      e.upper.forEach((u, j) => {
        const l = e.lower[j], d = [P(l)[0] - P(u)[0], P(l)[1] - P(u)[1]];
        set(key, u, d[0] * 0.9, d[1] * 0.9);
        set(key, l, -d[0] * 0.1, -d[1] * 0.1);
        set(key, e.crease[j], d[0] * 0.42, d[1] * 0.42);
      });
      const mid = e.upper[3], low = e.lower[3];
      set(key, this.eyeCentre[k], (P(low)[0] - P(mid)[0]) * 0.55, (P(low)[1] - P(mid)[1]) * 0.55);
    });
    // head-motion weight per vertex
    this.headW = new Float32Array(V).fill(1);
    for (let i = NL; i < V; i++) {
      const k = Math.floor((i - NL) / OVAL.length);
      const below = (this.rest[i * 3] - chin[0]) * dn[0] + (this.rest[i * 3 + 1] - chin[1]) * dn[1];
      this.headW[i] = RING_HEAD[k] * (below > 0 ? 1 - smooth(0, 0.35 * fh, below) * 0.85 : 1);
    }
    this.breathW = new Float32Array(V);
    for (let i = NL; i < V; i++) {
      const below = (this.rest[i * 3] - chin[0]) * dn[0] + (this.rest[i * 3 + 1] - chin[1]) * dn[1];
      this.breathW[i] = smooth(0.05 * fh, 0.5 * fh, below);
    }
    this.pivot = [chin[0] + dn[0] * 0.15 * fh, chin[1] + dn[1] * 0.15 * fh, this.ovalZ + 0.35 * fh];
  }

  sampleColours(img) {
    const c = document.createElement('canvas');
    c.width = this.W; c.height = this.H;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    const at = (ids) => {
      const s = [0, 0, 0];
      for (const i of ids) { const d = g.getImageData(Math.round(this.P(i)[0]), Math.round(this.P(i)[1]), 1, 1).data; s[0] += d[0]; s[1] += d[1]; s[2] += d[2]; }
      return s.map((v) => v / ids.length / 255);
    };
    this.lip = at([0, 17, 37, 267, 84, 314]);
    this.skin = at([205, 425, 101, 330]);
    const lum = 0.3 * this.skin[0] + 0.59 * this.skin[1] + 0.11 * this.skin[2];
    const k = Math.min(1, 0.55 + lum * 0.6);
    this.tooth = [0.95 * k, 0.92 * k, 0.86 * k];
  }

  async loadSprites(base, names) {
    for (const name of names) {
      if (!SPRITE_POSES[name]) continue;
      const img = await loadImage(`${base}mouth/${name}.png`);
      const uv = this.deform({ pose: SPRITE_POSES[name] }, new Float32Array(this.V * 2));
      this.sprites.push({ name, pose: SPRITE_POSES[name], tex: this.texture(img), uvBuf: this.staticBuf(uv) });
    }
  }

  /** Blend weights of the sprites for a mouth pose, and of the plain portrait ('base'). */
  spriteWeights(pose) {
    const d2 = (a, b) => (a.open - b.open) ** 2 + 1.5 * (a.width - b.width) ** 2 + (a.round - b.round) ** 2
      + (a.tuck - b.tuck) ** 2 + 0.3 * (a.teeth - b.teeth) ** 2 + 0.5 * (a.press - b.press) ** 2;
    const raw = this.sprites.map((s) => Math.exp(-d2(pose, s.pose) / 0.025));
    const base = Math.exp(-d2(pose, SHAPES.sil) / 0.025);
    const sum = raw.reduce((a, b) => a + b, base) || 1;
    return { base: base / sum, w: raw.map((r) => r / sum) };
  }

  /** Deformed vertex positions for a state; returns `out` (Float32Array V*2). */
  deform(st, out = this.pos) {
    const pose = st.pose || SHAPES.sil, V = this.V, B = this.bases, R = this.rest;
    const a = {
      open: pose.open, part: Math.min(1, pose.open * 1.6), teeth: pose.teeth * (0.35 + 0.65 * Math.min(1, pose.open * 4 + pose.tuck)),
      width: pose.width - 0.5, round: pose.round, press: pose.press, tuck: pose.tuck, smile: st.smile || 0, brow: st.brow || 0,
      blinkL: st.blink?.[0] || 0, blinkR: st.blink?.[1] || 0,
    };
    const ks = BASES.filter((k) => a[k]);
    for (let i = 0; i < V; i++) {
      let x = R[i * 3], y = R[i * 3 + 1];
      for (const k of ks) { x += B[k][i * 2] * a[k]; y += B[k][i * 2 + 1] * a[k]; }
      out[i * 2] = x; out[i * 2 + 1] = y;
    }
    const h = st.head;
    if (h) {
      const [px, py, pz] = this.pivot;
      const cy = Math.cos(h.yaw), sy = Math.sin(h.yaw), cp = Math.cos(h.pitch), sp = Math.sin(h.pitch), cr = Math.cos(h.roll), sr = Math.sin(h.roll);
      for (let i = 0; i < V; i++) {
        const w = this.headW[i];
        if (!w) continue;
        const x0 = out[i * 2] - px, y0 = out[i * 2 + 1] - py, z0 = R[i * 3 + 2] - pz;
        const x1 = x0 * cy + z0 * sy, z1 = -x0 * sy + z0 * cy;
        const y1 = y0 * cp - z1 * sp;
        const x2 = x1 * cr - y1 * sr, y2 = x1 * sr + y1 * cr;
        out[i * 2] += (x2 - x0 + (h.tx || 0)) * w;
        out[i * 2 + 1] += (y2 - y0 + (h.ty || 0)) * w;
      }
    }
    if (st.breath) for (let i = 0; i < V; i++) {
      out[i * 2 + 1] -= st.breath * (this.breathW[i] * 2.2 + this.headW[i] * 1.0);
    }
    return out;
  }

  /** Crop of the image shown in the canvas: centred on the face, cover-fit to the canvas aspect. */
  setView(zoom = 1) {
    const c = this.canvas, aspect = c.width / c.height;
    let h = this.H / zoom, w = h * aspect;
    if (w > this.W / zoom) { w = this.W / zoom; h = w / aspect; }
    const cx = Math.min(this.W - w / 2, Math.max(w / 2, this.mc[0]));
    const cy = Math.min(this.H - h / 2, Math.max(h / 2, this.P(168)[1] + h * 0.08));
    this.view = [cx, cy, 2 / w, 2 / h];
  }

  bind(posBuf, uvBuf, alphaBuf) {
    const gl = this.gl;
    for (const [loc, buf, n] of [[0, posBuf, 2], [1, uvBuf, 2], [2, alphaBuf, 1]]) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, n, gl.FLOAT, false, 0, 0);
    }
  }

  /** One frame. Returns the rendered inner-lip gap in portrait pixels (for the lag metric). */
  render(st) {
    const gl = this.gl;
    this.deform(st);
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, this.pos, gl.DYNAMIC_DRAW);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    const pos = (i) => [this.pos[i * 2], this.pos[i * 2 + 1]];
    const pose = st.pose || SHAPES.sil;
    const useSprites = this.mouth === 'sprites' && this.sprites.length;
    const sw = useSprites ? this.spriteWeights(pose) : null;
    // 1. inner mouth under everything
    if (useSprites && 1 - sw.base > 0.02) {
      this.drawSpriteBlend(sw.w, this.mouthIdx, this.oneBuf, true);
    } else {
      const m = this.mouthProg;
      gl.useProgram(m.p);
      this.bind(this.posBuf, this.posBuf, this.oneBuf);
      gl.uniform4fv(m.u.uView, this.view);
      gl.uniform2fv(m.u.uL, pos(78)); gl.uniform2fv(m.u.uR, pos(308)); gl.uniform2fv(m.u.uUp, pos(13)); gl.uniform2fv(m.u.uLo, pos(14));
      gl.uniform1f(m.u.uOpen, pose.open); gl.uniform1f(m.u.uTeeth, pose.teeth); gl.uniform1f(m.u.uTongue, pose.tongue); gl.uniform1f(m.u.uTuck, pose.tuck);
      gl.uniform3fv(m.u.uLip, this.lip); gl.uniform3fv(m.u.uTooth, this.tooth);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.mouthIdx.b);
      gl.drawElements(gl.TRIANGLES, this.mouthIdx.n, gl.UNSIGNED_SHORT, 0);
    }
    // 2. the portrait
    const f = this.face;
    gl.useProgram(f.p);
    this.bind(this.posBuf, this.uvBuf, this.oneBuf);
    gl.uniform4fv(f.u.uView, this.view);
    gl.uniform2f(f.u.uSize, this.W, this.H);
    gl.uniform1f(f.u.uOpacity, 1);
    const g = st.gaze || [0, 0];
    gl.uniform4fv(f.u.uEye, this.eyes.flatMap((e) => [...e.c, ...e.r]));
    gl.uniform2fv(f.u.uGaze, this.eyes.flatMap((e) => [g[0] * e.r[0] * 0.3, g[1] * e.r[1] * 0.25]));
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tex); gl.uniform1i(f.u.uTex, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.faceIdx.b);
    gl.drawElements(gl.TRIANGLES, this.faceIdx.n, gl.UNSIGNED_SHORT, 0);
    // 3. sprite lips over the portrait, feathered
    if (useSprites && 1 - sw.base > 0.02) this.drawSpriteBlend(sw.w, this.patchIdx, this.alphaBuf, false, sw.base);
    const up = pos(13), lo = pos(14);
    return Math.hypot(lo[0] - up[0], lo[1] - up[1]);
  }

  // Exact linear blend by sequential "over": layer i gets alpha w_i / (base + w_1 + ... + w_i).
  drawSpriteBlend(w, idx, alphaBuf, normalise, base = 0) {
    const gl = this.gl, f = this.face;
    gl.useProgram(f.p);
    gl.uniform4fv(f.u.uView, this.view);
    gl.uniform2f(f.u.uSize, this.W, this.H);
    gl.uniform4fv(f.u.uEye, new Float32Array(8));
    gl.uniform2fv(f.u.uGaze, new Float32Array(4));
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idx.b);
    const tot = w.reduce((a, b) => a + b, 0) || 1;
    let acc = normalise ? 0 : base;
    this.sprites.forEach((s, i) => {
      const wi = normalise ? w[i] / tot : w[i];
      if (wi < 0.005) return;
      acc += wi;
      this.bind(this.posBuf, s.uvBuf, alphaBuf);
      gl.uniform1f(f.u.uOpacity, acc > 0 ? wi / acc : 0);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, s.tex); gl.uniform1i(f.u.uTex, 0);
      gl.drawElements(gl.TRIANGLES, idx.n, gl.UNSIGNED_SHORT, 0);
    });
  }
}
