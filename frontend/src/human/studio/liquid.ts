// Liquid glass, after Kubai's six-layer recipe (Lumno): projection, blur + brightening, edge refraction
// with dispersion, tint, edge light and text colouring. This file does the refraction; the rest is CSS
// (.glass in studio.css). An SVG displacement map pushes the backdrop inward near the edges (the closer to
// the edge the stronger, the centre stays flat); red bends 15 % more than green and blue 15 % less.
// Chromium only: other browsers do not take url() in backdrop-filter, so they keep the plain frosted glass.

const SUPPORTED = typeof window !== 'undefined' && 'chrome' in window && CSS.supports('backdrop-filter', 'blur(1px)');
const EDGE = 44; // px of refracting rim (recommended)
const OFFSET = 1.1; // displacement = 1.1 × the rim width
const DISPERSION = 0.15;

let svg: SVGSVGElement | null = null;
const made = new Set<string>();

function rim(w: number, h: number) {
  return Math.max(6, Math.min(EDGE, Math.min(w, h) * 0.45));
}

/** Displacement map: R/G = x/y push towards the centre, strongest at the rim, 0.5 (no push) inside. */
function map(w: number, h: number, r: number, e: number): string {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const ctx = c.getContext('2d')!;
  const img = ctx.createImageData(w, h);
  r = Math.min(r, w / 2, h / 2);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      // signed distance to the rounded rectangle, and the inward normal
      const qx = Math.abs(x + 0.5 - w / 2) - (w / 2 - r), qy = Math.abs(y + 0.5 - h / 2) - (h / 2 - r);
      const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
      const d = r - (Math.hypot(ox, oy) + Math.min(Math.max(qx, qy), 0)); // distance inside the edge
      let nx = 0, ny = 0;
      if (ox > 0 || oy > 0) { const l = Math.hypot(ox, oy) || 1; nx = ox / l; ny = oy / l; }
      else if (qx > qy) nx = 1; else ny = 1;
      nx *= x + 0.5 < w / 2 ? 1 : -1; // point inward
      ny *= y + 0.5 < h / 2 ? 1 : -1;
      const m = d >= e ? 0 : (1 - Math.max(0, d) / e) ** 2;
      const i = (y * w + x) * 4;
      img.data[i] = 128 + 127 * nx * m;
      img.data[i + 1] = 128 + 127 * ny * m;
      img.data[i + 2] = 128;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL();
}

function filter(w: number, h: number, r: number): string {
  const id = `lg-${w}x${h}r${r}`;
  if (made.has(id)) return id;
  if (!svg) {
    svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('aria-hidden', 'true');
    Object.assign(svg.style, { position: 'absolute', width: '0', height: '0', overflow: 'hidden' });
    document.body.appendChild(svg);
  }
  const e = rim(w, h), s = e * OFFSET;
  const ch = (k: number) => {
    const m = ['0 0 0 0 0', '0 0 0 0 0', '0 0 0 0 0'];
    m[k] = ['1 0 0 0 0', '0 1 0 0 0', '0 0 1 0 0'][k];
    return `${m.join(' ')} 0 0 0 1 0`;
  };
  svg.insertAdjacentHTML('beforeend', `
    <filter id="${id}" x="0" y="0" width="${w}" height="${h}" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feImage href="${map(w, h, r, e)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="map"/>
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${(s * (1 + DISPERSION)).toFixed(1)}" xChannelSelector="R" yChannelSelector="G" result="dr"/>
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${s.toFixed(1)}" xChannelSelector="R" yChannelSelector="G" result="dg"/>
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${(s * (1 - DISPERSION)).toFixed(1)}" xChannelSelector="R" yChannelSelector="G" result="db"/>
      <feColorMatrix in="dr" type="matrix" values="${ch(0)}" result="r"/>
      <feColorMatrix in="dg" type="matrix" values="${ch(1)}" result="g"/>
      <feColorMatrix in="db" type="matrix" values="${ch(2)}" result="b"/>
      <feBlend in="r" in2="g" mode="screen" result="rg"/>
      <feBlend in="rg" in2="b" mode="screen"/>
    </filter>`);
  made.add(id);
  return id;
}

const sized = new WeakMap<HTMLElement, string>();
const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver((entries) => entries.forEach((en) => apply(en.target as HTMLElement))) : null;

function apply(el: HTMLElement) {
  const w = Math.round(el.offsetWidth), h = Math.round(el.offsetHeight);
  if (w < 8 || h < 8) return;
  const r = Math.round(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0);
  const key = `${w}x${h}r${r}`;
  if (sized.get(el) === key) return;
  sized.set(el, key);
  el.style.setProperty('--refract', `url(#${filter(w, h, r)})`);
  el.classList.add('liquid');
}

/** Watch a subtree: every .glass element that appears gets its refraction filter, re-made on resize. */
export function liquidGlass(root: HTMLElement): () => void {
  if (!SUPPORTED || !ro) return () => {};
  const scan = () => root.querySelectorAll<HTMLElement>('.glass').forEach((el) => {
    if (!sized.has(el)) { sized.set(el, ''); ro.observe(el); apply(el); }
  });
  scan();
  const mo = new MutationObserver(scan);
  mo.observe(root, { childList: true, subtree: true });
  return () => mo.disconnect();
}
