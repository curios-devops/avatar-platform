// The closet view, after a real clothes rail: garments hang in profile along a chrome bar, and the one
// in front turns to face you as it slides into place (pre-rendered frames every 30°, cross-faded), grows,
// and gets its yellow name tag. Same handle as the arc, so the page drives both the same way.
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import type { ArcHandle, ArcItem } from './Arc';

export const ANGLES = [0, 30, 60, 90];
const REDUCED = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

export type HangItem = ArcItem & { turns?: string[] }; // image per angle in ANGLES order (front … profile)

export const Hanger = forwardRef<ArcHandle, { items: HangItem[]; selected: number; onSettle: (i: number) => void }>(
  function Hanger({ items, selected, onSettle }, ref) {
    const host = useRef<HTMLDivElement>(null);
    const n = items.length;
    const st = useRef({ pos: Math.max(0, selected), target: Math.max(0, selected), dragging: false, p0: 0, lastX: 0, lastT: 0, vel: 0, settled: selected });
    const settleRef = useRef(onSettle);
    settleRef.current = onSettle;
    const W = () => host.current?.clientWidth || innerWidth;
    const side = () => W() * 0.075; // spacing between garments in profile
    const front = () => W() * 0.15; // the one in front needs room to open up
    const clamp = (v: number) => Math.max(0, Math.min(n - 1, v));

    useEffect(() => {
      if (selected < 0) return;
      st.current.target = selected;
      st.current.settled = selected;
    }, [selected]);

    useImperativeHandle(ref, () => ({
      drag(dx) {
        const s = st.current, now = performance.now();
        if (!s.dragging) { s.dragging = true; s.p0 = s.pos; s.lastX = 0; s.lastT = now; }
        s.vel = (dx - s.lastX) / Math.max(1, now - s.lastT);
        s.lastX = dx; s.lastT = now;
        s.pos = s.p0 - dx / side();
      },
      release() {
        const s = st.current;
        if (!s.dragging) return;
        s.dragging = false;
        s.target = clamp(Math.round(s.pos - s.vel * 2.4));
      },
      step(d) { st.current.target = clamp(Math.round(st.current.target) + d); },
      goSlot(slot) {
        const s = st.current;
        s.target = clamp(slot);
        if (s.target !== s.settled) { s.settled = s.target; settleRef.current(s.target); }
      },
    }), [n]);

    useEffect(() => {
      let raf = 0;
      const loop = (tms: number) => {
        raf = requestAnimationFrame(loop);
        const s = st.current, t = tms / 1000;
        if (!s.dragging) s.pos = REDUCED ? s.target : s.pos + (s.target - s.pos) * 0.12;
        const cx = W() * 0.4, fg = front(), sg = side();
        const speed = s.target - s.pos;
        Array.from(host.current?.querySelectorAll<HTMLElement>('.item') ?? []).forEach((el, i) => {
          const u = i - s.pos, a = Math.abs(u), k = Math.min(1, a);
          // neighbours step aside by the front garment's half width, the rest are packed like a real rail
          const x = cx + Math.sign(u) * (k * fg + Math.max(0, a - 1) * sg);
          const sc = 1 + 0.12 * (1 - k);
          const swing = REDUCED ? 0 : Math.max(-7, Math.min(7, speed * 5)) * (0.4 + 0.6 * k) + Math.sin(t * 1.2 + i * 1.9) * 0.5 * k;
          el.style.transform = `translateX(${x}px) rotate(${swing.toFixed(2)}deg) scale(${sc})`;
          el.style.zIndex = String(100 - Math.round(a * 10));
          el.style.opacity = String(x > W() + 200 || x < -200 ? 0 : 1);
          el.classList.toggle('on', a < 0.5);
          // turn: 0° in front, 90° (profile) from one slot away; cross-fade the two nearest frames
          const deg = 90 * k;
          const frames = el.querySelectorAll<HTMLElement>('.turn');
          if (frames.length > 1) {
            const f = deg / 30, lo = Math.floor(f), mix = f - lo;
            frames.forEach((fr, j) => { fr.style.opacity = String(j === lo ? 1 - mix : j === lo + 1 ? mix : 0); });
          } else if (frames.length === 1) {
            frames[0].style.transform = `scaleX(${1 - 0.55 * k})`; // no side render (hair, extras): squeeze
          }
        });
        if (!s.dragging && Math.abs(s.target - s.pos) < 0.02 && Math.round(s.target) !== s.settled) {
          s.settled = Math.round(s.target);
          settleRef.current(s.settled);
        }
      };
      raf = requestAnimationFrame(loop);
      return () => cancelAnimationFrame(raf);
    }, [n]);

    return (
      <div ref={host} className="hanger">
        <div className="bar" />
        {items.map((it, i) => (
          <div key={it.key} className="item">
            <span className="hit" data-slot={i} />
            <span className="hook" />
            <div className="img">
              {(it.turns ?? (it.img ? [it.img] : [])).map((src, j) => (
                <div key={j} className="turn" style={{ backgroundImage: `url(${src})` }} />
              ))}
              {it.none && <div className="nil">∅</div>}
              {it.swatch && !it.img && <div className="sw" style={{ background: it.swatch }} />}
            </div>
            <span className="label">{it.title}</span>
          </div>
        ))}
      </div>
    );
  });
