// A simple original 2D face in SVG, drawn here (no third-party art). It renders a pose from lib/visemes.js
// (open, width, round, press, tuck, tongue, teeth) and adds blinks and a little head motion of its own.
//   const face = createFace(container); face.render(pose, level)   // level: 0..1 voice level for the nod

const NS = 'http://www.w3.org/2000/svg';
let uid = 0;

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

export function createFace(container, { skin = '#f2c9a5', hair = '#2d2433', lips = '#c4566a' } = {}) {
  const id = `f${++uid}`;
  const svg = el('svg', { viewBox: '-100 -125 200 250', class: 'face', role: 'img', 'aria-label': 'talking face' }, container);
  const defs = el('defs', {}, svg);
  const hole = el('clipPath', { id: `${id}-hole` }, defs);
  const holePathClip = el('path', {}, hole);
  for (const s of [-1, 1]) el('ellipse', { cx: 26 * s, cy: -12, rx: 13, ry: 9 }, el('clipPath', { id: `${id}-eye${s}` }, defs));

  const head = el('g', {}, svg);
  el('path', { d: 'M-70,-30 C-78,-95 78,-95 70,-30 L70,-10 C60,-60 -60,-60 -70,-10 Z', fill: hair }, head); // back hair
  for (const s of [-1, 1]) el('ellipse', { cx: 70 * s, cy: 5, rx: 10, ry: 16, fill: skin }, head);
  el('path', { d: 'M-68,-20 C-70,-80 70,-80 68,-20 C68,40 40,92 0,94 C-40,92 -68,40 -68,-20 Z', fill: skin }, head);
  el('path', { d: 'M-70,-22 C-66,-92 66,-92 70,-22 C52,-58 18,-64 -6,-50 C-24,-62 -54,-56 -70,-22 Z', fill: hair }, head); // fringe
  for (const s of [-1, 1]) el('ellipse', { cx: 40 * s, cy: 28, rx: 12, ry: 7, fill: '#f08f8f', opacity: 0.35 }, head);
  el('path', { d: 'M-3,4 C-6,18 -8,22 0,24 C4,24 6,22 5,20', fill: 'none', stroke: '#c9967a', 'stroke-width': 2, 'stroke-linecap': 'round' }, head);

  const brows = [], lids = [];
  for (const s of [-1, 1]) {
    el('ellipse', { cx: 26 * s, cy: -12, rx: 13, ry: 9, fill: '#fff' }, head);
    const eye = el('g', { 'clip-path': `url(#${id}-eye${s})` }, head);
    el('circle', { cx: 26 * s + 1, cy: -11, r: 6.5, fill: '#4b3a2a' }, eye);
    el('circle', { cx: 26 * s + 1, cy: -11, r: 3, fill: '#140f0c' }, eye);
    el('circle', { cx: 26 * s + 3, cy: -13.5, r: 1.6, fill: '#fff' }, eye);
    lids.push(el('rect', { x: 26 * s - 15, y: -40, width: 30, height: 20, fill: skin }, eye));
    brows.push(el('path', { d: `M${26 * s - 13},-28 Q${26 * s},${-34} ${26 * s + 13},-28`, fill: 'none', stroke: hair, 'stroke-width': 4, 'stroke-linecap': 'round' }, head));
  }

  const mouth = el('g', {}, head);
  const outer = el('path', { fill: lips }, mouth);
  const inner = el('path', { fill: '#3b1220' }, mouth);
  const inside = el('g', { 'clip-path': `url(#${id}-hole)` }, mouth);
  const teeth = el('rect', { x: -40, width: 80, fill: '#fbf8f2' }, inside);
  const tongue = el('ellipse', { fill: '#e07a8a' }, inside);
  const seam = el('path', { fill: 'none', stroke: '#8d3346', 'stroke-width': 1.6, 'stroke-linecap': 'round' }, mouth);

  let blinkAt = performance.now() + 1500 + Math.random() * 2500, t0 = performance.now(), nod = 0;

  function lipPath(w, yTop, yBot, cy, k) {
    return `M${-w},${cy} C${-w * k},${yTop} ${w * k},${yTop} ${w},${cy} C${w * k},${yBot} ${-w * k},${yBot} ${-w},${cy} Z`;
  }

  function render(p, level = 0) {
    const now = performance.now(), t = (now - t0) / 1000;
    // blink: 60 ms down, 90 ms up, every 2-5 s
    let lid = 0;
    const since = now - blinkAt;
    if (since > 0 && since < 150) lid = since < 60 ? since / 60 : 1 - (since - 60) / 90;
    else if (since >= 150) blinkAt = now + 2000 + Math.random() * 3000;
    for (const l of lids) l.setAttribute('y', -40 + 21 * lid);
    nod += (level - nod) * 0.08;
    const brow = -2.5 * nod;
    brows.forEach((b, i) => b.setAttribute('transform', `translate(0,${brow + (i ? 0 : 0.5)})`));
    const ang = 1.6 * Math.sin(t * 0.55) + 0.8 * Math.sin(t * 1.43 + 1), dy = 1.4 * Math.sin(t * 0.9) + 2.5 * nod;
    head.setAttribute('transform', `translate(${0.8 * Math.sin(t * 0.37)},${dy}) rotate(${ang},0,40)`);

    // mouth
    const cy = 50, W = 19 + 24 * p.width - 9 * p.round, k = 0.55 + 0.35 * p.round;
    const H = 1 + 30 * p.open;
    let yTop = cy - H * 0.32, yBot = cy + H * 0.68;
    if (p.tuck > 0) yBot -= p.tuck * Math.max(0, yBot - (cy - 1)); // lower lip up under the teeth
    const tu = 5.5 * (1 - 0.45 * p.press) + 3 * p.round, tl = 7 * (1 - 0.35 * p.press) + 3.5 * p.round - 2 * p.tuck;
    const w = W * (0.9 - 0.2 * p.round);
    outer.setAttribute('d', lipPath(W, yTop - tu, yBot + tl, cy, k));
    const hd = lipPath(w, yTop, yBot, cy, k);
    const gap = yBot - yTop;
    inner.setAttribute('d', hd);
    holePathClip.setAttribute('d', hd);
    inner.setAttribute('opacity', Math.min(1, gap / 3));
    teeth.setAttribute('y', yTop - 1);
    teeth.setAttribute('height', Math.max(0, 3 + 6 * p.teeth + 4 * p.tuck));
    teeth.setAttribute('opacity', Math.min(1, p.teeth * 1.2 + p.tuck));
    tongue.setAttribute('cx', 0);
    tongue.setAttribute('rx', w * 0.55);
    tongue.setAttribute('ry', 4 + 3 * p.tongue);
    tongue.setAttribute('cy', yBot - 1 - p.tongue * Math.max(0, gap * 0.45));
    tongue.setAttribute('opacity', 0.55 + 0.45 * p.tongue);
    seam.setAttribute('d', `M${-W * 0.95},${cy} Q0,${cy + 1.5 - 2.5 * p.round} ${W * 0.95},${cy}`);
    seam.setAttribute('opacity', Math.max(0, 1 - gap / 2.5));
  }

  render({ open: 0, width: 0.5, round: 0, press: 0, tuck: 0, tongue: 0, teeth: 0 });
  return { svg, render };
}
