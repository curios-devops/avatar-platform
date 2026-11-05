// A looping 3D arc: glass cards (garments) or standing figures (characters) curve around the live model,
// recede, tilt and blur toward the edges. The page owns the pointer (the canvas sits on top) and drives
// this through the handle; the arc reports the item it settles on.
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';

export type ArcItem = { key: string; img?: string; title: string; sub?: string; swatch?: string; none?: boolean };
export type ArcHandle = { drag(dx: number): void; release(): void; step(d: number): void; goSlot(slot: number): void };
type Props = {
  items: ArcItem[]; selected: number; variant: 'card' | 'figure';
  onSettle: (index: number) => void;
};

const REDUCED = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const mod = (a: number, n: number) => ((a % n) + n) % n;

export const Arc = forwardRef<ArcHandle, Props>(function Arc({ items, selected, variant, onSettle }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const n = Math.max(1, items.length);
  const slots = n * Math.max(1, Math.ceil(10 / n)); // at least 10 slots so the loop never shows its seam
  const st = useRef({ pos: 0, target: 0, dragging: false, p0: 0, lastX: 0, lastT: 0, vel: 0, settled: -1, intro: REDUCED ? 1 : 0, dx: 0 });
  const settleRef = useRef(onSettle);
  settleRef.current = onSettle;
  const W = () => host.current?.clientWidth || innerWidth;
  const H = () => host.current?.clientHeight || innerHeight;
  const xs = () => {
    const phone = innerWidth < 768;
    if (variant === 'figure') return (phone ? [0, .34, .5, .58, .62, .64] : [0, .16, .27, .355, .42, .46]).map((v) => v * W());
    return (phone ? [0, .36, .5, .56, .6, .62] : [0, .215, .345, .432, .49, .52]).map((v) => v * W());
  };

  // an outside change (prompt, click on the body) moves the arc the short way round to that item
  useEffect(() => {
    const s = st.current;
    if (selected < 0) return;
    const cur = mod(Math.round(s.target), n);
    if (cur === selected) { s.settled = selected; return; }
    let d = mod(selected - cur, n);
    if (d > n / 2) d -= n;
    s.target = Math.round(s.target) + d;
    s.settled = selected;
  }, [selected, n]);

  useImperativeHandle(ref, () => ({
    drag(dx) {
      const s = st.current;
      const now = performance.now();
      if (!s.dragging) { s.dragging = true; s.p0 = s.pos; s.lastX = 0; s.lastT = now; s.vel = 0; }
      s.vel = (dx - s.lastX) / Math.max(1, now - s.lastT);
      s.lastX = dx; s.lastT = now;
      s.pos = s.p0 - dx / xs()[1];
    },
    release() {
      const s = st.current;
      if (!s.dragging) return;
      s.dragging = false;
      s.target = Math.round(s.pos - s.vel * 3.2);
    },
    step(d) { st.current.target = Math.round(st.current.target) + d; },
    goSlot(slot) {
      // a click is a decision: try it on now, while the arc is still turning
      const s = st.current;
      let d = mod(slot - Math.round(s.target), slots);
      if (d > slots / 2) d -= slots;
      s.target = Math.round(s.target) + d;
      const idx = mod(slot, n);
      if (idx !== s.settled) { s.settled = idx; settleRef.current(idx); }
    },
  }), [slots, variant, n]);

  useEffect(() => {
    let raf = 0;
    const els = () => Array.from(host.current?.children ?? []) as HTMLElement[];
    const loop = (tms: number) => {
      raf = requestAnimationFrame(loop);
      const s = st.current, t = tms / 1000;
      if (!s.dragging) s.pos = REDUCED ? s.target : s.pos + (s.target - s.pos) * 0.11;
      s.intro = Math.min(1, s.intro + 0.012);
      const ie = 1 - (1 - s.intro) ** 3;
      const XS = xs(), h = H();
      const xAt = (a: number) => {
        const i = Math.min(Math.floor(a), XS.length - 2);
        return XS[i] + (XS[i + 1] - XS[i]) * Math.min(1, a - i);
      };
      els().forEach((el, i) => {
        const u = mod(i - s.pos + slots / 2, slots) - slots / 2;
        const a = Math.abs(u), sg = Math.sign(u);
        let sc: number, z: number, op: number, ry: number, blur = 0;
        if (variant === 'figure') {
          // the live model stands in the centre slot, so its card steps aside
          sc = 1 / (1 + 0.38 * a ** 1.05);
          z = 0; ry = 0;
          op = a < 0.5 ? 0 : Math.min(1, (a - 0.5) * 2);
          blur = Math.max(0, a - 1.4) * 2.2;
        } else if (a < 1) {
          sc = 0.55 + 0.45 * a; z = -260 * (1 - a); op = a; ry = -sg * 16 * a;
        } else {
          sc = 1 / (1 + 0.3 * (a - 1) ** 1.15); z = -110 * (a - 1);
          ry = -sg * (16 + 9 * Math.min(2, a - 1)); op = 1; blur = Math.max(0, a - 1.6) * 2.4;
        }
        if (a > 3.4) op *= Math.max(0, 1 - (a - 3.4) / 0.8);
        const bob = REDUCED || variant === 'figure' ? 0 : Math.sin(t * 1.1 + i * 1.7) * h * 0.006 * Math.min(1, a);
        // figures further back stand a little higher on the floor, towards the horizon
        const y = variant === 'figure' ? -(1 - sc) * h * 0.07 : bob - (1 - sc) * h * 0.04;
        const x = sg * xAt(a) * ie;
        el.style.transform = `translate(${x}px, ${y}px) perspective(1300px) translateZ(${z}px) rotateY(${ry}deg) scale(${sc * (0.6 + 0.4 * ie)})`;
        el.style.opacity = String(op * ie);
        el.style.filter = blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : '';
        el.style.zIndex = String(a < 1 && variant === 'card' ? 1 : Math.round(100 - 10 * a));
        el.style.visibility = op * ie < 0.01 ? 'hidden' : 'visible';
      });
      if (items.length && !s.dragging && Math.abs(s.target - s.pos) < 0.02) {
        const idx = mod(Math.round(s.target), n);
        if (idx !== s.settled) { s.settled = idx; settleRef.current(idx); }
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [slots, n, variant, items.length]);

  return (
    <div ref={host} className="arc">
      {Array.from({ length: slots }, (_, i) => {
        const it = items[i % n];
        if (!it) return null;
        return variant === 'figure' ? (
          <div key={`${it.key}-${i}`} className="fig" data-slot={i}>
            {it.img && <img src={it.img} alt={it.title} draggable={false} />}
            <span className="tag">{it.title}{it.sub ? ` · ${it.sub}` : ''}</span>
          </div>
        ) : (
          <div key={`${it.key}-${i}`} className="card glass" data-slot={i}>
            {it.none ? <div className="none">∅</div>
              : it.swatch ? <div className="swatch" style={{ background: it.swatch }} />
              : <div className="g" style={{ backgroundImage: it.img ? `url(${it.img})` : undefined }} />}
            <div className="n">{it.title}</div>
            {it.sub && <div className="p">{it.sub}</div>}
            <span className="sheen" />
          </div>
        );
      })}
    </div>
  );
});
