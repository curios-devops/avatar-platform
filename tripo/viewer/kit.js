// Creature kit: turns a creature spec (JSON, written by an LLM from a text prompt) into a skinned
// three.js character, entirely on the CPU and in the browser.
//
//   shapes  → a signed distance field: primitives joined with a smooth union, so the body is one
//             continuous surface (no visible joints between parts), optionally carved
//   field   → mesh by surface nets on a grid whose cell size is picked to hit a triangle target
//   bones   → a Skeleton; each vertex mixes the bones of the shapes nearest to it (soft weights)
//   paint   → per-vertex colour from the shapes plus "paint" volumes (belly, snout, paws…)
//   fur     → a strand texture drawn on a canvas, applied triplanar with bump (0 bytes to download)
//   parts   → small rigid meshes (eyes, nostrils, teeth, claws) parented to bones
//   clips   → each channel of a bone is an oscillator; baked to AnimationClips for playback/export
//
// The spec format is documented in tripo/creature_llm.py (it is the LLM's system prompt).
import * as THREE from 'three';

const DEG = Math.PI / 180;

// ── signed distance primitives (plain numbers, no allocation in the hot loop) ──
function rotInv(rot = [0, 0, 0]) {
  const m = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG));
  return m.transpose().elements; // inverse of a rotation = transpose; column-major
}
function compile(s, palette) {
  const c = s.center ?? [0, 0, 0], R = rotInv(s.rot), out = { ...s };
  const local = (x, y, z) => {
    const dx = x - c[0], dy = y - c[1], dz = z - c[2];
    return [R[0] * dx + R[4] * dy + R[8] * dz, R[1] * dx + R[5] * dy + R[9] * dz, R[2] * dx + R[6] * dy + R[10] * dz];
  };
  if (s.type === 'ellipsoid') {
    const [rx, ry, rz] = s.radii;
    out.f = (x, y, z) => {
      const [lx, ly, lz] = local(x, y, z);
      const k0 = Math.hypot(lx / rx, ly / ry, lz / rz), k1 = Math.hypot(lx / (rx * rx), ly / (ry * ry), lz / (rz * rz));
      return k1 === 0 ? -Math.min(rx, ry, rz) : (k0 * (k0 - 1)) / k1;
    };
    out.bc = c; out.br = Math.max(rx, ry, rz);
  } else if (s.type === 'capsule') { // a round cone from a (radius r) to b (radius r2 ?? r)
    const a = s.a, b = s.b, r1 = s.r, r2 = s.r2 ?? s.r;
    const bax = b[0] - a[0], bay = b[1] - a[1], baz = b[2] - a[2];
    const l2 = bax * bax + bay * bay + baz * baz, rr = r1 - r2, a2 = l2 - rr * rr, il2 = 1 / l2;
    out.f = (x, y, z) => {
      const pax = x - a[0], pay = y - a[1], paz = z - a[2];
      const yy = pax * bax + pay * bay + paz * baz, zz = yy - l2;
      const xvx = pax * l2 - bax * yy, xvy = pay * l2 - bay * yy, xvz = paz * l2 - baz * yy;
      const x2 = xvx * xvx + xvy * xvy + xvz * xvz, y2 = yy * yy * l2, z2 = zz * zz * l2;
      const k = Math.sign(rr) * rr * rr * x2;
      if (Math.sign(zz) * a2 * z2 > k) return Math.sqrt(x2 + z2) * il2 - r2;
      if (Math.sign(yy) * a2 * y2 < k) return Math.sqrt(x2 + y2) * il2 - r1;
      return (Math.sqrt(x2 * a2 * il2) + yy * rr) * il2 - r1;
    };
    out.bc = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
    out.br = Math.sqrt(l2) / 2 + Math.max(r1, r2);
  } else if (s.type === 'box') { // rounded box, size = full extents
    const hx = s.size[0] / 2, hy = s.size[1] / 2, hz = s.size[2] / 2, rd = Math.min(s.round ?? 0.01, hx, hy, hz);
    out.f = (x, y, z) => {
      const [lx, ly, lz] = local(x, y, z);
      const qx = Math.abs(lx) - hx + rd, qy = Math.abs(ly) - hy + rd, qz = Math.abs(lz) - hz + rd;
      return Math.hypot(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - rd;
    };
    out.bc = c; out.br = Math.hypot(hx, hy, hz);
  } else throw new Error(`unknown shape type ${s.type}`);
  out.k = s.blend ?? 0.04;
  out.col = new THREE.Color(palette[s.color] ?? s.color ?? '#888').convertSRGBToLinear();
  return out;
}
const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; };

// mirror anything marked mirror:true across x (the creature's left is +X), swapping _L/_R names
const swapLR = (n) => n?.split('_').map((t) => (t === 'L' ? 'R' : t === 'R' ? 'L' : t)).join('_');
const flipX = (p) => p && [-p[0], p[1], p[2]];
function mirrorAll(list) {
  const out = [];
  for (const s of list ?? []) {
    out.push(s);
    if (!s.mirror) continue;
    const m = { ...s, mirror: false, name: swapLR(s.name), bone: swapLR(s.bone), parent: swapLR(s.parent) };
    for (const key of ['center', 'a', 'b', 'pos']) if (s[key]) m[key] = flipX(s[key]);
    if (s.rot) m.rot = [s.rot[0], -s.rot[1], -s.rot[2]];
    out.push(m);
  }
  return out;
}

// ── surface nets ──
const CORNERS = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
const EDGES = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
function surfaceNets(field, lo, h, n) {
  const [nx, ny, nz] = n, P = (i, j, k) => i + nx * (j + ny * k);
  const val = new Float32Array(nx * ny * nz);
  for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    val[P(i, j, k)] = field(lo[0] + i * h, lo[1] + j * h, lo[2] + k * h);
  const C = (i, j, k) => i + (nx - 1) * (j + (ny - 1) * k);
  const cellV = new Int32Array((nx - 1) * (ny - 1) * (nz - 1)).fill(-1);
  const pos = [], cv = new Float32Array(8);
  for (let k = 0; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    let mask = 0;
    for (let c = 0; c < 8; c++) { cv[c] = val[P(i + CORNERS[c][0], j + CORNERS[c][1], k + CORNERS[c][2])]; if (cv[c] < 0) mask |= 1 << c; }
    if (mask === 0 || mask === 255) continue;
    let sx = 0, sy = 0, sz = 0, m = 0;
    for (const [a, b] of EDGES) {
      if ((cv[a] < 0) === (cv[b] < 0)) continue;
      const t = cv[a] / (cv[a] - cv[b]);
      sx += CORNERS[a][0] + t * (CORNERS[b][0] - CORNERS[a][0]);
      sy += CORNERS[a][1] + t * (CORNERS[b][1] - CORNERS[a][1]);
      sz += CORNERS[a][2] + t * (CORNERS[b][2] - CORNERS[a][2]);
      m++;
    }
    cellV[C(i, j, k)] = pos.length / 3;
    pos.push(lo[0] + (i + sx / m) * h, lo[1] + (j + sy / m) * h, lo[2] + (k + sz / m) * h);
  }
  const idx = [];
  const quad = (a, b, c, d) => { if (a < 0 || b < 0 || c < 0 || d < 0) return; idx.push(a, b, c, a, c, d); };
  for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++)       // x edges
    if ((val[P(i, j, k)] < 0) !== (val[P(i + 1, j, k)] < 0)) quad(cellV[C(i, j - 1, k - 1)], cellV[C(i, j, k - 1)], cellV[C(i, j, k)], cellV[C(i, j - 1, k)]);
  for (let k = 1; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++)       // y edges
    if ((val[P(i, j, k)] < 0) !== (val[P(i, j + 1, k)] < 0)) quad(cellV[C(i - 1, j, k - 1)], cellV[C(i, j, k - 1)], cellV[C(i, j, k)], cellV[C(i - 1, j, k)]);
  for (let k = 0; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++)       // z edges
    if ((val[P(i, j, k)] < 0) !== (val[P(i, j, k + 1)] < 0)) quad(cellV[C(i - 1, j - 1, k)], cellV[C(i, j - 1, k)], cellV[C(i, j, k)], cellV[C(i - 1, j, k)]);
  return { pos, idx };
}

// ── fur: a tileable canvas of short strokes, used as albedo variation and as a bump height ──
function furTexture(seed = 1, size = 512) {
  const cv = document.createElement('canvas'); cv.width = cv.height = size;
  const g = cv.getContext('2d');
  g.fillStyle = '#808080'; g.fillRect(0, 0, size, size);
  let s = seed * 9301 + 49297; const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  const tiled = (draw) => { for (const ox of [-size, 0, size]) for (const oy of [-size, 0, size]) draw(ox, oy); };
  // soft patches (low frequency), then clumps of strands that share a direction (high frequency)
  for (let i = 0; i < 60; i++) {
    const x = rnd() * size, y = rnd() * size, r = 30 + rnd() * 90, v = rnd() < 0.5 ? 0 : 255;
    tiled((ox, oy) => {
      const gr = g.createRadialGradient(x + ox, y + oy, 0, x + ox, y + oy, r);
      gr.addColorStop(0, `rgba(${v},${v},${v},0.10)`); gr.addColorStop(1, `rgba(${v},${v},${v},0)`);
      g.fillStyle = gr; g.fillRect(x + ox - r, y + oy - r, 2 * r, 2 * r);
    });
  }
  g.lineCap = 'round';
  for (let c = 0; c < 700; c++) {
    const cx = rnd() * size, cy = rnd() * size, a = -1.3 + (rnd() - 0.5) * 0.5, v0 = 70 + rnd() * 120;
    for (let i = 0; i < 7; i++) {
      const x = cx + (rnd() - 0.5) * 14, y = cy + (rnd() - 0.5) * 14, l = 14 + rnd() * 20, v = Math.min(255, v0 + (rnd() - 0.5) * 50) | 0;
      g.strokeStyle = `rgba(${v},${v},${v},0.5)`; g.lineWidth = 1.5 + rnd() * 2;
      tiled((ox, oy) => { g.beginPath(); g.moveTo(x + ox, y + oy); g.quadraticCurveTo(x + ox + Math.cos(a) * l * 0.5 + 3, y + oy + Math.sin(a) * l * 0.5, x + ox + Math.cos(a) * l, y + oy + Math.sin(a) * l); g.stroke(); });
    }
  }
  const t = new THREE.CanvasTexture(cv);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8;
  t.colorSpace = THREE.NoColorSpace;
  return t;
}
function furMaterial(tex, { scale = 3, contrast = 0.35, bump = 0.03, roughness = 0.88 } = {}) {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness });
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, { furMap: { value: tex }, furScale: { value: scale }, furContrast: { value: contrast }, furBump: { value: bump } });
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vFurPos; varying vec3 vFurN;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvFurPos = position; vFurN = normal;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vFurPos; varying vec3 vFurN;\nuniform sampler2D furMap; uniform float furScale, furContrast, furBump;')
      .replace('#include <map_fragment>', `#include <map_fragment>
        vec3 fw = pow(abs(normalize(vFurN)), vec3(4.0)); fw /= fw.x + fw.y + fw.z;
        float fh = texture2D(furMap, vFurPos.zy * furScale).r * fw.x + texture2D(furMap, vFurPos.xz * furScale).r * fw.y
                 + texture2D(furMap, vFurPos.xy * furScale).r * fw.z;
        diffuseColor.rgb *= mix(1.0 - furContrast, 1.0 + furContrast, fh);`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        { vec2 dH = vec2(dFdx(fh), dFdy(fh)) * furBump; vec3 sp = -vViewPosition;
          vec3 sx = dFdx(sp), sy = dFdy(sp), r1 = cross(sy, normal), r2 = cross(normal, sx);
          float det = dot(sx, r1) * faceDirection;
          normal = normalize(abs(det) * normal - sign(det) * (dH.x * r1 + dH.y * r2)); }`);
  };
  return m;
}
const PART_MATS = {
  eye: () => new THREE.MeshStandardMaterial({ color: 0x0d0b0a, roughness: 0.12 }),
  gloss: (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.25 }),
  matte: (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.8 }),
};

// ── build ──
export function buildCreature(spec, { targetTris } = {}) {
  const t0 = performance.now();
  const palette = spec.palette ?? {};
  const target = targetTris ?? spec.detail ?? 12000;
  const shapes = mirrorAll(spec.shapes).map((s) => compile(s, palette));
  const solids = shapes.filter((s) => (s.op ?? 'union') === 'union');
  const carves = shapes.filter((s) => s.op === 'carve');
  const paints = shapes.filter((s) => s.op === 'paint');
  if (!solids.length) throw new Error('spec has no union shapes');

  const field = (x, y, z) => {
    let d = 1e9;
    for (const s of solids) {
      const lb = Math.hypot(x - s.bc[0], y - s.bc[1], z - s.bc[2]) - s.br;
      if (lb > d + s.k) continue; // cannot change the smooth union
      d = smin(d, s.f(x, y, z), s.k);
    }
    for (const s of carves) {
      const lb = Math.hypot(x - s.bc[0], y - s.bc[1], z - s.bc[2]) - s.br;
      if (lb > -d + s.k) continue;
      d = -smin(-d, s.f(x, y, z), s.k);
    }
    return d;
  };

  // bounds, then a coarse pass to measure the surface area and pick the cell size for the target
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  for (const s of solids) for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], s.bc[a] - s.br - s.k); hi[a] = Math.max(hi[a], s.bc[a] + s.br + s.k); }
  const grid = (h) => {
    const l = lo.map((v) => v - 2 * h), n = [0, 1, 2].map((a) => Math.ceil((hi[a] - lo[a]) / h) + 5);
    return surfaceNets(field, l, h, n);
  };
  const span = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
  const h0 = span / 40, coarse = grid(h0);
  const h = h0 * Math.sqrt(coarse.idx.length / 3 / target);
  const { pos, idx } = grid(h);
  const tField = performance.now() - t0;

  // project vertices onto the surface (2 Newton steps), normals from the field gradient
  const nv = pos.length / 3, nrm = new Float32Array(pos.length), e = h * 0.25;
  const grad = (x, y, z) => {
    const gx = field(x + e, y, z) - field(x - e, y, z), gy = field(x, y + e, z) - field(x, y - e, z), gz = field(x, y, z + e) - field(x, y, z - e);
    const l = Math.hypot(gx, gy, gz) || 1; return [gx / l, gy / l, gz / l];
  };
  for (let v = 0; v < nv; v++) {
    let x = pos[3 * v], y = pos[3 * v + 1], z = pos[3 * v + 2];
    for (let it = 0; it < 2; it++) {
      const d = field(x, y, z), g = grad(x, y, z), step = Math.max(-h, Math.min(h, d));
      x -= g[0] * step; y -= g[1] * step; z -= g[2] * step;
    }
    pos[3 * v] = x; pos[3 * v + 1] = y; pos[3 * v + 2] = z;
    nrm.set(grad(x, y, z), 3 * v);
  }
  // orient every triangle with the field gradient
  for (let t = 0; t < idx.length; t += 3) {
    const [a, b, c] = [idx[t], idx[t + 1], idx[t + 2]];
    const ux = pos[3 * b] - pos[3 * a], uy = pos[3 * b + 1] - pos[3 * a + 1], uz = pos[3 * b + 2] - pos[3 * a + 2];
    const wx = pos[3 * c] - pos[3 * a], wy = pos[3 * c + 1] - pos[3 * a + 1], wz = pos[3 * c + 2] - pos[3 * a + 2];
    const fx = uy * wz - uz * wy, fy = uz * wx - ux * wz, fz = ux * wy - uy * wx;
    if (fx * (nrm[3 * a] + nrm[3 * b] + nrm[3 * c]) + fy * (nrm[3 * a + 1] + nrm[3 * b + 1] + nrm[3 * c + 1]) + fz * (nrm[3 * a + 2] + nrm[3 * b + 2] + nrm[3 * c + 2]) < 0) { idx[t + 1] = c; idx[t + 2] = b; }
  }

  // stand it on the ground
  let minY = 1e9;
  for (let v = 0; v < nv; v++) minY = Math.min(minY, pos[3 * v + 1]);
  const lift = -minY;
  for (let v = 0; v < nv; v++) pos[3 * v + 1] += lift;

  // bones
  const boneSpecs = mirrorAll(spec.bones);
  const bones = [], byName = new Map();
  for (const b of boneSpecs) {
    const bone = new THREE.Bone(); bone.name = b.name;
    bone.userData.world = [b.pos[0], b.pos[1] + lift, b.pos[2]];
    bones.push(bone); byName.set(b.name, bone);
  }
  let root = null;
  for (const [i, b] of boneSpecs.entries()) {
    const bone = bones[i], parent = b.parent ? byName.get(b.parent) : null;
    if (b.parent && !parent) throw new Error(`bone ${b.name}: unknown parent ${b.parent}`);
    const w = bone.userData.world, pw = parent ? parent.userData.world : [0, 0, 0];
    bone.position.set(w[0] - pw[0], w[1] - pw[1], w[2] - pw[2]);
    if (parent) parent.add(bone); else if (!root) root = bone; else throw new Error(`two root bones: ${root.name}, ${b.name}`);
  }
  const boneIndex = new Map(bones.map((b, i) => [b.name, i]));
  for (const s of [...solids, ...shapes.filter((s) => s.op === 'paint')]) if (s.bone && !boneIndex.has(s.bone)) throw new Error(`shape on unknown bone ${s.bone}`);

  // per-vertex skin weights and colour from the nearest shapes
  const col = new Uint8Array(nv * 4), sIdx = new Uint8Array(nv * 4), sW = new Uint8Array(nv * 4);
  const lin = new THREE.Color(), dist = new Float32Array(solids.length);
  for (let v = 0; v < nv; v++) {
    const x = pos[3 * v], y = pos[3 * v + 1] - lift, z = pos[3 * v + 2];
    let dmin = 1e9;
    for (let i = 0; i < solids.length; i++) { dist[i] = solids[i].f(x, y, z); dmin = Math.min(dmin, dist[i]); }
    const perBone = new Map(); let r = 0, g = 0, b = 0, wc = 0;
    for (let i = 0; i < solids.length; i++) {
      const s = solids[i], sig = Math.max(s.k, 0.015);
      const w = Math.exp(-(dist[i] - dmin) / sig);
      if (w < 1e-4) continue;
      const bi = boneIndex.get(s.bone) ?? 0;
      perBone.set(bi, (perBone.get(bi) ?? 0) + w);
      const wcol = Math.exp(-(dist[i] - dmin) / (0.4 * sig));
      r += s.col.r * wcol; g += s.col.g * wcol; b += s.col.b * wcol; wc += wcol;
    }
    lin.setRGB(r / wc, g / wc, b / wc);
    for (const p of paints) { // paint volumes recolour what they touch, with a soft edge
      const d = p.f(x, y, z), soft = p.soft ?? 0.02;
      const t = Math.min(1, Math.max(0, 1 - d / soft)) * (p.opacity ?? 1);
      if (t > 0) lin.lerp(p.col, t * t * (3 - 2 * t));
    }
    lin.convertLinearToSRGB();
    col.set([lin.r * 255, lin.g * 255, lin.b * 255, 255].map(Math.round), 4 * v);
    const top = [...perBone].sort((p, q) => q[1] - p[1]).slice(0, 4), tot = top.reduce((a, p) => a + p[1], 0);
    // 8-bit weights that sum to exactly 255: floor each, give the remainder to the heaviest bone
    let acc = 0;
    top.forEach(([bi, w], j) => { sIdx[4 * v + j] = bi; const q = Math.floor((w / tot) * 255); sW[4 * v + j] = q; acc += q; });
    sW[4 * v] += 255 - acc;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 4, true));
  geo.setAttribute('skinIndex', new THREE.BufferAttribute(sIdx, 4));
  geo.setAttribute('skinWeight', new THREE.BufferAttribute(sW, 4, true));
  geo.setIndex(nv < 65536 ? new THREE.BufferAttribute(new Uint16Array(idx), 1) : new THREE.BufferAttribute(new Uint32Array(idx), 1));
  const fur = spec.fur ?? {};
  const body = new THREE.SkinnedMesh(geo, furMaterial(furTexture(fur.seed ?? 1), fur));
  body.name = 'body';
  body.add(root);
  body.updateMatrixWorld(true);
  body.bind(new THREE.Skeleton(bones));

  // rigid parts
  const group = new THREE.Group(); group.name = spec.name ?? 'creature';
  group.add(body);
  group.updateMatrixWorld(true);
  let partTris = 0;
  for (const p of mirrorAll(spec.parts)) {
    const colour = palette[p.color] ?? p.color ?? '#222';
    const mat = (PART_MATS[p.material] ?? PART_MATS.matte)(new THREE.Color(colour));
    let g;
    if (p.type === 'box') g = new THREE.BoxGeometry(...p.size);
    else if (p.type === 'cone') g = new THREE.ConeGeometry(p.r, p.length, 10);
    else { g = new THREE.SphereGeometry(1, 20, 14); g.scale(...p.radii); }
    const mesh = new THREE.Mesh(g, mat); mesh.name = p.name ?? p.material ?? 'part';
    const c = p.center ?? [0, 0, 0];
    mesh.position.set(c[0], c[1] + lift, c[2]);
    if (p.rot) mesh.rotation.set(p.rot[0] * DEG, p.rot[1] * DEG, p.rot[2] * DEG);
    group.add(mesh); mesh.updateMatrixWorld(true);
    const bone = byName.get(p.bone) ?? root;
    bone.attach(mesh);
    partTris += g.index ? g.index.count / 3 : g.attributes.position.count / 3;
  }

  // clips
  const rest = new Map(bones.map((b) => [b, b.position.clone()]));
  const clips = {};
  for (const [name, c] of Object.entries(spec.clips ?? {})) {
    const period = c.period ?? 1, tracks = (c.tracks ?? []).filter((t) => byName.has(t.bone));
    clips[name] = { period, tracks: tracks.map((t) => ({ ...t, bone: byName.get(t.bone) })) };
  }
  const wave = (kind, a) => { const s = Math.sin(a); return kind === 'abs' ? Math.abs(s) : kind === 'pos' ? Math.max(0, s) : kind === 'neg' ? Math.min(0, s) : s; };
  const pose = (clipName, t) => {
    for (const b of bones) { b.position.copy(rest.get(b)); b.rotation.set(0, 0, 0); }
    const c = clips[clipName]; if (!c) return;
    for (const tr of c.tracks) {
      const v = (tr.bias ?? 0) + (tr.amp ?? 0) * wave(tr.wave, 2 * Math.PI * Math.round(tr.harmonic ?? 1) * t / c.period + (tr.phase ?? 0) * DEG);
      const ch = tr.ch ?? 'rx';
      if (ch[0] === 'r') tr.bone.rotation[ch[1]] += v; else tr.bone.position[ch[1]] += v;
    }
  };
  const bake = (clipName, fps = 30) => {
    const c = clips[clipName], frames = Math.max(2, Math.round(c.period * fps)), times = [], buf = new Map(bones.map((b) => [b, { p: [], q: [] }]));
    for (let i = 0; i <= frames; i++) {
      const t = (i / frames) * c.period; pose(clipName, t); times.push(t);
      for (const b of bones) { buf.get(b).p.push(...b.position.toArray()); buf.get(b).q.push(...b.quaternion.toArray()); }
    }
    const moved = new Set(c.tracks.map((t) => t.bone)), tracks = [];
    for (const b of moved) {
      tracks.push(new THREE.QuaternionKeyframeTrack(`${b.name}.quaternion`, times, buf.get(b).q));
      if (c.tracks.some((t) => t.bone === b && t.ch?.[0] === 'p')) tracks.push(new THREE.VectorKeyframeTrack(`${b.name}.position`, times, buf.get(b).p));
    }
    pose(null, 0);
    return new THREE.AnimationClip(clipName, c.period, tracks);
  };

  // pieces that do not touch the rest of the body (floating blobs are an error in the spec)
  const parentOf = new Int32Array(nv).map((_, i) => i);
  const find = (i) => { while (parentOf[i] !== i) { parentOf[i] = parentOf[parentOf[i]]; i = parentOf[i]; } return i; };
  for (let t = 0; t < idx.length; t += 3) { const a = find(idx[t]), b = find(idx[t + 1]), c = find(idx[t + 2]); parentOf[b] = a; parentOf[find(c)] = a; }
  const comps = new Map(); for (let v = 0; v < nv; v++) { const r = find(v); comps.set(r, (comps.get(r) ?? 0) + 1); }
  const box = new THREE.Box3().setFromBufferAttribute(geo.attributes.position);

  const stats = {
    bodyTris: idx.length / 3, partTris, tris: idx.length / 3 + partTris, verts: nv, bones: bones.length,
    cell: +h.toFixed(4), pieces: comps.size, smallPieces: [...comps.values()].filter((n) => n < nv * 0.9).sort((a, b) => b - a),
    lift: +lift.toFixed(3), size: box.getSize(new THREE.Vector3()).toArray().map((v) => +v.toFixed(3)),
    fieldMs: +tField.toFixed(0), buildMs: +(performance.now() - t0).toFixed(0), clips: Object.keys(clips),
  };
  return { group, body, bones, byName, pose, bake, clips, stats };
}
