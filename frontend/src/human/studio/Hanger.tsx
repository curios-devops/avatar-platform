// The closet view: garments hang from a chrome rail beside the model, the one in front grows and gets
// its name tag. Same handle as the arc, so the page drives both the same way.
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import type { ArcHandle, ArcItem } from './Arc';

const REDUCED = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

export const Hanger = forwardRef<ArcHandle, { items: ArcItem[]; selected: number; onSettle: (i: number) => void }>(
  function Hanger({ items, selected, onSettle }, ref) {
    const host = useRef<HTMLDivElement>(null);
    const n = items.length;
    const st = useRef({ pos: Math.max(0, selected), target: Math.max(0, selected), dragging: false, p0: 0, lastX: 0, lastT: 0, vel: 0, settled: selected });
    const settleRef = useRef(onSettle);
    settleRef.current = onSettle;
    const gap = () => (host.current?.clientWidth || innerWidth) * 0.15;
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
        s.pos = s.p0 - dx / gap();
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
        const w = host.current?.clientWidth || innerWidth, g = gap();
        Array.from(host.current?.querySelectorAll<HTMLElement>('.item') ?? []).forEach((el, i) => {
          const u = i - s.pos, a = Math.abs(u);
          const sc = 1 + 0.2 * Math.max(0, 1 - a);
          // garments swing a little as the rail moves, like real hangers
          const swing = REDUCED ? 0 : Math.max(-8, Math.min(8, (s.target - s.pos) * 6)) + Math.sin(t * 1.3 + i) * 0.6;
          el.style.transform = `translateX(${w / 2 + u * g}px) rotate(${swing}deg) scale(${sc})`;
          el.style.zIndex = String(100 - Math.round(a * 10));
          el.style.opacity = String(a > 3.2 ? Math.max(0, 1 - (a - 3.2) / 0.8) : 1);
          el.classList.toggle('on', a < 0.5);
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
          <div key={it.key} className="item" data-slot={i} style={{ left: 0 }}>
            <span className="hook" />
            <div className="img" style={{ backgroundImage: it.img ? `url(${it.img})` : undefined }}>
              {it.none && <div style={{ position: 'absolute', inset: '20% 20% 40%', display: 'grid', placeItems: 'center', fontSize: '8vh', fontWeight: 200, opacity: 0.7 }}>∅</div>}
              {it.swatch && !it.img && <div style={{ position: 'absolute', left: '25%', right: '25%', top: '10%', aspectRatio: '1', borderRadius: 999, background: it.swatch }} />}
            </div>
            <span className="label">{it.title}</span>
          </div>
        ))}
      </div>
    );
  });
