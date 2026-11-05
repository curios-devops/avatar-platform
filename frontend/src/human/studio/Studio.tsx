// MEYA studio (?human=1): the live three.js person stands in the middle of a soft backdrop.
// Two worlds share the stage: Character (who they are: body, face, skin, hair, eyes, or a photo Twin)
// and Fitting (what they wear). Pick from the arc or the closet rail, click straight on the body
// (the jacket opens the outfits, the hair opens hairstyles…) or just say it: "add gold hoops".
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './studio.css';
import { HumanEngine, type Accessory, type Pick } from '../engine';
import { Speech } from '../speech';
import { Arc, type ArcHandle, type ArcItem } from './Arc';
import { ANGLES, Hanger, type HangItem } from './Hanger';
import { liquidGlass } from './liquid';
import {
  ACCESSORIES, BACKDROPS, CHARACTERS, FACE_GROUPS, FIT_TABS, GARMENT_NAMES, HAIR_TINTS, L, PROMPTS, TINTS, categoryOf, es,
  type Category,
} from './presets';
import { HUMAN_URL, bake, bakeBody, cut, faceKeys, fromCharacter, lookOf, type Avatar, type Catalog } from './avatar';

type Mode = 'character' | 'fitting';
type CharTab = 'body' | 'face' | 'skin' | 'hair' | 'eyes';
type Op = { op: string; key?: string; value?: number; id?: string; target?: string; color?: string; on?: boolean };

const CHAR_TABS: [CharTab, string][] = [
  ['body', L('Body', 'Cuerpo')], ['face', L('Face', 'Cara')], ['skin', L('Skin', 'Piel')], ['hair', L('Hair', 'Pelo')], ['eyes', L('Eyes', 'Ojos')],
];
const EYE_HEX: Record<string, string> = {
  blue: '#4a78b5', bluegreen: '#4f8a8b', brown: '#5a3a22', brownlight: '#8a5a32', deepblue: '#23407a',
  green: '#4f7f45', grey: '#8a9096', ice: '#b9d4e6', lightblue: '#8ab4dc',
};
const STAGES: [string, number][] = [[L('Child', 'Niño'), 0.12], [L('Teen', 'Adolescente'), 0.3], [L('Adult', 'Adulto'), 0.5], [L('Middle age', 'Mediana edad'), 0.7], [L('Elder', 'Mayor'), 0.95]];
const BUILDS: [string, number, number][] = [[L('Slim', 'Delgado'), 0.2, 0.35], [L('Average', 'Medio'), 0.5, 0.5], [L('Athletic', 'Atlético'), 0.42, 0.85], [L('Heavy', 'Robusto'), 0.92, 0.4]];
const TONE: Record<string, 'light' | 'dark'> = { atelier: 'light', showroom: 'dark', dusk: 'light', night: 'dark', gallery: 'light' };
const EXPRS = ['neutral', 'smile', 'happy', 'surprised', 'thinking'];
const PART_LABEL: Record<string, string> = {
  clothes: L('OUTFIT', 'ROPA'), shoes: L('SHOES', 'ZAPATOS'), hat: L('HAT', 'SOMBRERO'), hair: L('HAIR', 'PELO'),
  accessory: L('EXTRAS', 'ACCESORIOS'), body: L('FACE · BODY', 'CARA · CUERPO'), eyes: L('EYES', 'OJOS'), eyebrows: L('FACE', 'CARA'),
};
/** "cortu shaggy green hair" → "Shaggy green", "long01" → "Long 01": the CC0 packs name hair by file. */
const hairName = (label: string) => {
  const t = label.replace(/^(cortu|culturalibre|elvs|toigo|sonntag78|o4saken|faydaen|littleright|rehmanpolanski)[ _]/, '')
    .replace(/[_-]+/g, ' ').replace(/\bhair\b/gi, '').replace(/([a-z])(\d+)$/i, '$1 $2').replace(/\s+/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};
/** The closet's frames for one cut-out: front, 30°, 60°, profile (see Generate). */
const turns = (name: string) => ANGLES.map((d) => cut(d ? `${name}_a${d}` : name));
const STARTER = ['male_casualsuit06', 'shoes05']; // white tee + jeans, white sneakers (fits any body)
const family = (id: Accessory['id']) => (id === 'hoops' || id === 'studs' ? 'ears' : 'eyes');

export function Studio({ serverUrl, onBack }: { serverUrl: string; onBack: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const bgRef = useRef<HTMLDivElement>(null);
  const ghostRef = useRef<HTMLDivElement>(null);
  const scanRef = useRef<HTMLDivElement>(null);
  const curRef = useRef<HTMLDivElement>(null);
  const arc = useRef<ArcHandle>(null);
  const engine = useRef<HumanEngine | null>(null);
  const speech = useRef<Speech | null>(null);

  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [mode, setMode] = useState<Mode>('fitting');
  const [fitTab, setFitTab] = useState<Category>('outfits');
  const [charTab, setCharTab] = useState<CharTab>('body');
  const [view, setView] = useState<'arc' | 'hanger'>('arc');
  const [backdrop, setBackdrop] = useState('atelier');
  // everyone starts in the classic white tee and jeans; the character's own outfit is one click away
  const [avatar, setAvatar] = useState<Avatar>(() => ({ ...fromCharacter(CHARACTERS[0]), clothes: [...STARTER], tints: {}, accessories: [] }));
  const [charId, setCharId] = useState<string | null>(CHARACTERS[0].id);
  const [lastChar, setLastChar] = useState(0);
  const [history, setHistory] = useState<Avatar[]>([]);
  const [expr, setExpr] = useState('neutral');
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null);
  const [twinBusy, setTwinBusy] = useState(false);
  const scanNext = useRef(true); // the first person appears with the scan

  const flash = useCallback((text: string, err = false) => {
    setToast({ text, err });
    window.clearTimeout((flash as any).t);
    (flash as any).t = window.setTimeout(() => setToast(null), 3200);
  }, []);

  useEffect(() => liquidGlass(root.current!), []);

  // ------------------------------------------------------------------ engine, voice, catalog
  useEffect(() => {
    const e = new HumanEngine(host.current!, HUMAN_URL, true);
    e.controls.enabled = false; // the page owns the pointer: drag on the body turns it, elsewhere moves the arc
    e.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    e.fullDistance = 5.6;
    e.setShift(0, 0.06); // the person stands a little high: the prompt bar lives at their feet
    engine.current = e;
    const s = new Speech(serverUrl);
    s.connect();
    speech.current = s;
    e.mouth = () => s.mouth();
    fetch(`${HUMAN_URL}/catalog`).then((r) => r.json()).then(setCatalog)
      .catch(() => flash(L('Start the human service on port 8010', 'Arranca el servicio humano en el puerto 8010'), true));
    return () => { s.close(); e.dispose(); };
  }, [serverUrl, flash]);

  // ------------------------------------------------------------------ bake + scan reveal
  const bakeKey = catalog ? JSON.stringify(bakeBody(catalog, avatar)) : '';
  const avatarRef = useRef(avatar);
  avatarRef.current = avatar;
  useEffect(() => {
    if (!catalog) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const glb = await bake(catalog, avatarRef.current, ctrl.signal);
        const e = engine.current!;
        const scan = scanNext.current;
        scanNext.current = false;
        const old = scan ? e.screenshot() : '';
        await e.load(glb, lookOf(catalog, avatarRef.current));
        e.frame(framingFor(), false);
        if (scan) reveal(old);
      } catch (err) {
        if ((err as Error).name !== 'AbortError') flash(String((err as Error).message), true);
      }
    }, 140);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [catalog, bakeKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // look-only changes (tints, skin, eyes, accessories, Twin texture) repaint without a bake
  const lookKey = catalog ? JSON.stringify(lookOf(catalog, avatar)) : '';
  useEffect(() => { if (catalog) void engine.current?.setLook(lookOf(catalog, avatar)); }, [lookKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { engine.current?.setExpression(expr); }, [expr]);

  /** The new look sweeps down behind a glowing line; the old one stays below it until the line passes. */
  function reveal(oldPng: string) {
    const box = scanRef.current, canvas = host.current;
    if (!box || !canvas) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    box.innerHTML = '';
    const img = document.createElement('img');
    img.src = oldPng;
    const grid = document.createElement('div');
    grid.className = 'grid';
    const line = document.createElement('div');
    line.className = 'line';
    box.append(img, grid, line);
    const ease = 'cubic-bezier(.65,0,.35,1)';
    const T = 1100;
    canvas.animate([{ clipPath: 'inset(0 0 100% 0)' }, { clipPath: 'inset(0 0 0% 0)' }], { duration: T, easing: ease });
    img.animate([{ clipPath: 'inset(0% 0 0 0)' }, { clipPath: 'inset(100% 0 0 0)' }], { duration: T, easing: ease, fill: 'forwards' });
    grid.animate([{ clipPath: 'inset(0 0 100% 0)', opacity: 1 }, { clipPath: 'inset(0 0 0 0)', opacity: 1, offset: 0.5 }, { clipPath: 'inset(100% 0 0 0)', opacity: 0 }], { duration: T * 1.15, easing: ease });
    line.animate([
      { top: '0%', transform: 'scaleX(.2)', opacity: 0 }, { top: '6%', transform: 'scaleX(1)', opacity: 1, offset: 0.08 },
      { top: '94%', transform: 'scaleX(1)', opacity: 1, offset: 0.92 }, { top: '100%', transform: 'scaleX(.2)', opacity: 0 },
    ], { duration: T, easing: ease, fill: 'forwards' }).finished.then(() => { if (box.contains(line)) box.innerHTML = ''; });
  }

  // ------------------------------------------------------------------ camera follows the task
  const framingFor = () => (mode === 'character' && (charTab === 'face' || charTab === 'eyes') ? 'face'
    : mode === 'character' && charTab === 'hair' ? 'bust' : 'full');
  useEffect(() => { engine.current?.frame(framingFor(), true); }, [mode, charTab]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { engine.current?.setShift(mode === 'fitting' && view === 'hanger' ? 0.27 : 0, 0.06); }, [mode, view]);

  // ------------------------------------------------------------------ edits
  const commit = useCallback((next: Avatar | ((a: Avatar) => Avatar), opts: { scan?: boolean; keepChar?: boolean } = {}) => {
    setAvatar((cur) => {
      const n = typeof next === 'function' ? next(cur) : next;
      if (n === cur) return cur;
      setHistory((h) => [...h.slice(-30), cur]);
      return n;
    });
    if (opts.scan) scanNext.current = true;
    if (!opts.keepChar) setCharId(null);
  }, []);
  const undo = () => {
    setHistory((h) => {
      if (!h.length) return h;
      scanNext.current = true;
      setAvatar(h[h.length - 1]);
      return h.slice(0, -1);
    });
  };
  const useCharacter = (i: number) => {
    const c = CHARACTERS[i];
    if (!c) return;
    commit(fromCharacter(c), { scan: true, keepChar: true });
    setCharId(c.id);
    setLastChar(i);
  };

  const wear = (id: string) => commit((a) => {
    const cat = categoryOf(id);
    if (a.clothes.includes(id)) return a;
    return { ...a, clothes: [...a.clothes.filter((c) => categoryOf(c) !== cat), id] };
  }, { scan: true });
  const unwear = (cat: Category) => commit((a) => ({ ...a, clothes: a.clothes.filter((c) => categoryOf(c) !== cat) }), { scan: true });
  const setAccessory = (id: Accessory['id'] | null, color?: string) => commit((a) => {
    if (!id) return { ...a, accessories: [] };
    const rest = a.accessories.filter((x) => family(x.id) !== family(id));
    return { ...a, accessories: [...rest, { id, color }] };
  });
  const tint = (target: string, color: string) => commit((a) => (target === 'hair' ? { ...a, hairColor: color }
    : { ...a, tints: { ...a.tints, [target]: color } }));

  function applyOps(ops: Op[]) {
    let scan = false, preset = -1;
    const next = ops.reduce<Avatar>((a, o) => {
      switch (o.op) {
        case 'pheno': return { ...a, pheno: { ...a.pheno, [o.key!]: o.value! } };
        case 'face': {
          const local = { ...a.local };
          for (const k of faceKeys(o.key!, catalog?.faceChanges ?? [])) local[k] = o.value!;
          return { ...a, local };
        }
        case 'wear': scan = true; return { ...a, clothes: [...a.clothes.filter((c) => categoryOf(c) !== categoryOf(o.id!)), o.id!] };
        case 'remove': scan = true; return { ...a, clothes: a.clothes.filter((c) => c !== o.id) };
        case 'tint': {
          if (o.target === 'hair') return { ...a, hairColor: o.color! };
          const targets = o.target && a.clothes.includes(o.target) ? [o.target]
            : a.clothes.filter((c) => categoryOf(c) === 'outfits').concat(a.clothes.some((c) => categoryOf(c) === 'outfits') ? [] : a.clothes);
          return { ...a, tints: { ...a.tints, ...Object.fromEntries(targets.map((t) => [t, o.color!])) } };
        }
        case 'hair': scan = true; return { ...a, hair: o.id! };
        case 'skin': return { ...a, skin: o.id!, faceTexture: undefined };
        case 'eyes': return { ...a, eyes: o.id! };
        case 'accessory': {
          const id = o.id as Accessory['id'];
          const rest = a.accessories.filter((x) => (o.on ? family(x.id) !== family(id) : x.id !== id));
          return { ...a, accessories: o.on ? [...rest, { id, color: o.color }] : rest };
        }
        case 'expression': setExpr(o.id!); return a;
        case 'background': setBackdrop(o.id!); return a;
        case 'preset': preset = CHARACTERS.findIndex((c) => c.id === o.id); return a;
        default: return a;
      }
    }, avatarRef.current);
    if (preset >= 0) return useCharacter(preset);
    if (next !== avatarRef.current) commit(next, { scan });
    // show where the change happened
    const first = ops.find((o) => ['wear', 'remove', 'accessory', 'hair'].includes(o.op));
    if (first) {
      setMode('fitting');
      setFitTab(first.op === 'accessory' ? 'accessories' : first.op === 'hair' ? 'hair' : categoryOf(first.id!));
    }
  }

  // ------------------------------------------------------------------ carousel contents
  const fitItems = useMemo<{ items: HangItem[]; ids: (string | null)[] }>(() => {
    if (!catalog) return { items: [], ids: [] };
    const none = (cat: string): ArcItem => ({ key: `none-${cat}`, title: L('None', 'Ninguno'), none: true });
    if (fitTab === 'accessories') {
      return { items: [none('acc'), ...ACCESSORIES.map((a) => ({ key: a.id, title: a.name, img: cut(`acc_${a.id}`), turns: turns(`acc_${a.id}`) }))], ids: [null, ...ACCESSORIES.map((a) => a.id)] };
    }
    if (fitTab === 'hair') {
      return { items: [{ key: 'bald', title: L('No hair', 'Sin pelo'), none: true }, ...catalog.hair.map((h) => ({ key: h.id, title: hairName(h.label), img: cut(`hair_${h.id}`), turns: turns(`hair_${h.id}`) }))], ids: ['', ...catalog.hair.map((h) => h.id)] };
    }
    const list = catalog.clothes.filter((c) => categoryOf(c.id) === fitTab);
    const sub = { outfits: L('Outfit', 'Conjunto'), shoes: L('Shoes', 'Zapatos'), hats: L('Hat', 'Sombrero') }[fitTab as 'outfits'];
    const items: HangItem[] = list.map((c) => ({
      key: c.id, title: GARMENT_NAMES[c.id] ?? c.label, sub, img: cut(`garment_${c.id}`),
      turns: turns(`garment_${c.id}`),
    }));
    return fitTab === 'outfits' ? { items, ids: list.map((c) => c.id) } : { items: [none(fitTab), ...items], ids: [null, ...list.map((c) => c.id)] };
  }, [catalog, fitTab]);

  const fitSelected = (() => {
    if (fitTab === 'accessories') return Math.max(0, fitItems.ids.findIndex((id) => id && avatar.accessories.some((a) => a.id === id)));
    if (fitTab === 'hair') return Math.max(0, fitItems.ids.indexOf(avatar.hair));
    const worn = avatar.clothes.find((c) => categoryOf(c) === fitTab);
    return worn ? fitItems.ids.indexOf(worn) : fitTab === 'outfits' ? -1 : 0;
  })();

  const onFitSettle = (i: number) => {
    const id = fitItems.ids[i];
    if (fitTab === 'accessories') return setAccessory((id as Accessory['id']) ?? null);
    if (fitTab === 'hair') return commit((a) => (a.hair === id ? a : { ...a, hair: id ?? '' }), { scan: true });
    if (id) wear(id); else unwear(fitTab);
  };

  const charItems = useMemo<ArcItem[]>(() => CHARACTERS.map((c) => ({ key: c.id, title: c.name, sub: `${c.age} · ${c.note}`, img: cut(`char_${c.id}`) })), []);
  const charSelected = charId ? CHARACTERS.findIndex((c) => c.id === charId) : lastChar;

  // ------------------------------------------------------------------ pointer: cards, body, arc
  const ptr = useRef({ down: false, x: 0, y: 0, moved: 0, kind: '' as '' | 'card' | 'body' | 'arc', slot: -1, pick: null as Pick | null, lastPick: 0 });
  const cursor = useRef({ x: innerWidth / 2, y: innerHeight / 2, tx: innerWidth / 2, ty: innerHeight / 2, sx: 0, sy: 0 });
  const setCursor = (modeName: string, text = '') => {
    const el = curRef.current;
    if (!el) return;
    el.dataset.mode = modeName;
    const t = el.querySelector('.txt');
    if (t && t.textContent !== text) t.textContent = text;
  };
  const isUI = (t: EventTarget | null) => !!(t as HTMLElement)?.closest?.('button, input, .glass:not(.card), .panel, .ask');

  const onPointerDown = (e: React.PointerEvent) => {
    if (isUI(e.target) || e.button !== 0) return;
    const p = ptr.current;
    p.down = true; p.x = e.clientX; p.y = e.clientY; p.moved = 0;
    const slotEl = (e.target as HTMLElement).closest('[data-slot]') as HTMLElement | null;
    p.pick = slotEl ? null : engine.current?.pick(e.clientX, e.clientY) ?? null;
    p.kind = slotEl ? 'card' : p.pick ? 'body' : 'arc';
    p.slot = slotEl ? Number(slotEl.dataset.slot) : -1;
    curRef.current?.classList.add('down');
    root.current?.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const c = cursor.current;
    c.tx = e.clientX; c.ty = e.clientY;
    const p = ptr.current;
    if (p.down) {
      const dx = e.clientX - p.x;
      p.moved = Math.max(p.moved, Math.hypot(dx, e.clientY - p.y));
      if (p.moved < 6) return;
      if (p.kind === 'body') { engine.current?.turn((e.movementX || 0) * 0.012); setCursor('drag', L('TURN', 'GIRAR')); }
      else if (showArc) { arc.current?.drag(dx); setCursor('drag', L('DRAG', 'ARRASTRA')); }
      return;
    }
    if (isUI(e.target)) return setCursor('btn');
    if ((e.target as HTMLElement).closest('[data-slot]')) return setCursor('try', mode === 'character' ? L('BE ME', 'ELEGIR') : L('TRY ON', 'PROBAR'));
    const now = performance.now();
    if (now - p.lastPick < 70) return; // skinned raycasts are not free
    p.lastPick = now;
    const hit = engine.current?.pick(e.clientX, e.clientY);
    if (hit) setCursor('try', PART_LABEL[hit.kind] ?? '');
    else setCursor(showArc ? 'drag' : '', showArc ? L('DRAG', 'ARRASTRA') : '');
  };
  const onPointerUp = () => {
    const p = ptr.current;
    if (!p.down) return;
    p.down = false;
    curRef.current?.classList.remove('down');
    if (p.moved >= 6) { if (p.kind !== 'body') arc.current?.release(); return; }
    if (p.kind === 'card') arc.current?.goSlot(p.slot);
    else if (p.kind === 'body' && p.pick) openPart(p.pick);
  };

  /** A click on the body opens the right drawer: jacket → outfits, hair → hairstyles, face → face sliders… */
  function openPart(hit: Pick) {
    const k = hit.kind;
    if (k === 'clothes' || k === 'shoes' || k === 'hat' || k === 'accessory') {
      setMode('fitting');
      setFitTab(k === 'clothes' ? 'outfits' : k === 'shoes' ? 'shoes' : k === 'hat' ? 'hats' : 'accessories');
    } else if (k === 'hair') {
      if (mode === 'character') setCharTab('hair'); else setFitTab('hair');
    } else {
      setMode('character');
      setCharTab(k === 'eyes' ? 'eyes' : 'face');
    }
  }

  const showArc = mode === 'character' || view === 'arc';
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
      if (e.key === 'ArrowRight') arc.current?.step(1);
      if (e.key === 'ArrowLeft') arc.current?.step(-1);
    };
    let acc = 0, last = 0;
    const onWheel = (e: WheelEvent) => {
      if ((e.target as HTMLElement)?.closest?.('.panel')) return;
      acc += Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const now = performance.now();
      if (Math.abs(acc) > 60 && now - last > 260) { arc.current?.step(Math.sign(acc)); acc = 0; last = now; }
    };
    addEventListener('keydown', onKey);
    addEventListener('wheel', onWheel, { passive: true });
    return () => { removeEventListener('keydown', onKey); removeEventListener('wheel', onWheel); };
  }, []);

  // cursor + parallax
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const c = cursor.current;
      c.x += (c.tx - c.x) * 0.22; c.y += (c.ty - c.y) * 0.22;
      c.sx += ((c.tx / innerWidth - 0.5) - c.sx) * 0.06; c.sy += ((c.ty / innerHeight - 0.5) - c.sy) * 0.06;
      if (curRef.current) curRef.current.style.transform = `translate(${c.x}px, ${c.y}px)`;
      if (bgRef.current) bgRef.current.style.transform = `translate3d(${-c.sx * 22}px, ${-c.sy * 14}px, 0) scale(1.05)`;
      if (ghostRef.current) ghostRef.current.style.transform = `translate(calc(-50% - ${c.sx * 40}px), ${-c.sy * 16}px)`;
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, []);

  // ------------------------------------------------------------------ Twin from a photo
  const fileRef = useRef<HTMLInputElement>(null);
  async function fitTwin(photo: Blob) {
    setTwinBusy(true);
    setMode('character');
    setCharTab('face');
    try {
      const res = await fetch(`${HUMAN_URL}/twin/fit`, { method: 'POST', body: photo, headers: { 'content-type': 'application/octet-stream' } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
      const fit = await res.json() as { phenotype: Record<string, number>; local: Record<string, number>; texture: string };
      commit((a) => ({ ...a, pheno: { ...a.pheno, ...fit.phenotype }, local: fit.local, brows: '', faceTexture: `${HUMAN_URL}${fit.texture}` }), { scan: true });
      flash(L('Your Twin is ready', 'Tu Twin está listo'));
    } catch (err) {
      flash(String((err as Error).message ?? err), true);
    } finally {
      setTwinBusy(false);
    }
  }

  // ------------------------------------------------------------------ what the look card shows
  const card = (() => {
    if (mode === 'character') {
      const c = charId ? CHARACTERS.find((x) => x.id === charId) : null;
      return {
        thumb: c ? cut(`char_${c.id}`) : cut(`char_${CHARACTERS[lastChar].id}`),
        name: avatar.faceTexture ? L('Your Twin', 'Tu Twin') : c ? c.name : L('Your character', 'Tu personaje'),
        sub: c ? `${c.age} ${L('years', 'años')} · ${c.note}` : L('Customised', 'Personalizado'),
        dots: null as null | { list: [string, string][]; value: string; pick: (c: string) => void },
      };
    }
    if (fitTab === 'hair') {
      return { thumb: avatar.hair ? cut(`hair_${avatar.hair}`) : '', name: fitItems.items[fitSelected]?.title ?? '', sub: L('Hairstyle · colour', 'Peinado · color'),
        dots: { list: HAIR_TINTS, value: avatar.hairColor, pick: (c: string) => tint('hair', c) } };
    }
    if (fitTab === 'accessories') {
      const a = avatar.accessories[avatar.accessories.length - 1];
      const meta = ACCESSORIES.find((x) => x.id === a?.id);
      return { thumb: meta ? cut(`acc_${meta.id}`) : '', name: meta?.name ?? L('No accessories', 'Sin accesorios'), sub: L('Accessories', 'Accesorios'),
        dots: meta ? { list: meta.colors.map((c) => [c, c] as [string, string]), value: a.color ?? meta.colors[0], pick: (c: string) => setAccessory(meta.id, c) } : null };
    }
    const worn = avatar.clothes.find((c) => categoryOf(c) === fitTab);
    return { thumb: worn ? cut(`garment_${worn}`) : '', name: worn ? GARMENT_NAMES[worn] ?? worn : L('Nothing', 'Nada'),
      sub: FIT_TABS.find((t) => t[0] === fitTab)?.[1] ?? '',
      dots: worn ? { list: TINTS, value: avatar.tints[worn] ?? '#ffffff', pick: (c: string) => tint(worn, c) } : null };
  })();

  const bd = BACKDROPS.find((b) => b.id === backdrop) ?? BACKDROPS[0];
  const word = mode === 'character'
    ? (avatar.faceTexture ? 'TWIN' : (CHARACTERS.find((c) => c.id === charId)?.name ?? L('YOU', 'TÚ')).toUpperCase())
    : bd.word;

  return (
    <div ref={root} className="st" data-tone={TONE[backdrop]} data-mode={mode}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
      onPointerLeave={() => setCursor('')}>
      <div ref={bgRef} className="st-bg" data-bg={backdrop} />
      {showArc ? (
        <div ref={ghostRef} className="st-ghost" key={word}>
          {[...word].map((ch, i) => <span key={i} style={{ animation: `rise 1.1s cubic-bezier(.2,.8,.2,1) ${i * 0.05}s backwards` }}>{ch}</span>)}
        </div>
      ) : (
        <div className="st-wall" key={`wall-${fitTab}`}>
          {(avatar.pheno.gender ?? 0) > 0.6 ? L('men', 'hombre') : (avatar.pheno.gender ?? 0) < 0.4 ? L('women', 'mujer') : L('everyone', 'todos')} /<br />
          {(FIT_TABS.find((t) => t[0] === fitTab)?.[1] ?? '').toLowerCase()}
        </div>
      )}

      {showArc && catalog && (mode === 'character'
        ? <Arc key="chars" ref={arc} items={charItems} selected={charSelected} variant="figure" onSettle={useCharacter} />
        : <Arc key={`fit-${fitTab}`} ref={arc} items={fitItems.items} selected={fitSelected} variant="card" onSettle={onFitSettle} />)}
      {!showArc && catalog && <Hanger key={`hang-${fitTab}`} ref={arc} fit={fitTab === 'hair' || fitTab === 'accessories' ? 'box' : 'height'} items={fitItems.items} selected={Math.max(0, fitSelected)} onSettle={onFitSettle} />}

      <div ref={scanRef} className="st-scan" />
      <div ref={host} className="st-canvas" style={{ pointerEvents: 'none' }} data-testid="human-canvas" />
      {twinBusy && <TwinScan />}

      {/* top: back + brand, the two worlds, their drawers, backdrop and photo */}
      <div className="st-corner l">
        <button className="chip glass" onClick={onBack}>←</button>
        <span className="brand">MEYA<small>Studio</small></span>
      </div>
      <div className="st-top">
        <Tabs className="main" value={mode} onChange={(m) => setMode(m as Mode)}
          options={[['character', L('Character', 'Personaje')], ['fitting', L('Fitting', 'Ropa')]]} />
        {mode === 'fitting'
          ? <Tabs className="sub" value={fitTab} onChange={(t) => setFitTab(t as Category)} options={FIT_TABS} />
          : <Tabs className="sub" value={charTab} onChange={(t) => setCharTab(t as CharTab)} options={CHAR_TABS} />}
      </div>
      <div className="st-corner r">
        {mode === 'fitting' && (
          <button className="chip glass" onClick={() => {
            // the closet borrows the shop look: cool grey wall, chrome rail
            if (view === 'arc' && backdrop === 'atelier') setBackdrop('showroom');
            setView((v) => (v === 'arc' ? 'hanger' : 'arc'));
          }} title={L('Switch view', 'Cambiar vista')}>
            {view === 'arc' ? <IconHanger /> : <IconArc />}<span>{view === 'arc' ? L('Closet', 'Percha') : L('Arc', 'Arco')}</span>
          </button>
        )}
        <button className="chip glass" onClick={() => setBackdrop(BACKDROPS[(BACKDROPS.indexOf(bd) + 1) % BACKDROPS.length].id)}>
          <IconScene /><span>{bd.name}</span>
        </button>
        <button className="chip solid" onClick={() => fileRef.current?.click()} disabled={twinBusy}>
          <IconCamera /><span>{twinBusy ? L('Fitting your face…', 'Ajustando tu cara…') : L('From your photo', 'Desde tu foto')}</span>
        </button>
        <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void fitTwin(f); e.target.value = ''; }} />
      </div>

      <nav className="rail glass">
        <button title={L('Face', 'Cara')} onClick={() => engine.current?.frame('face', true)}><IconFace /></button>
        <button title={L('Bust', 'Busto')} onClick={() => engine.current?.frame('bust', true)}><IconBust /></button>
        <button title={L('Full body', 'Cuerpo entero')} onClick={() => engine.current?.frame('full', true)}><IconBody /></button>
        <span className="sep" />
        <button title={L('Expression', 'Expresión')} aria-pressed={expr !== 'neutral'} onClick={() => setExpr((x) => EXPRS[(EXPRS.indexOf(x) + 1) % EXPRS.length])}><IconSmile /></button>
        <button title={L('Say hello', 'Saludar')} onClick={() => speech.current?.say(L('Hi! This is me. Do you like the look?', '¡Hola! Esta soy yo. ¿Te gusta cómo quedé?'))}><IconVoice /></button>
        <button title={L('Snapshot', 'Captura')} onClick={() => { const a = document.createElement('a'); a.href = engine.current!.screenshot(); a.download = 'meya-avatar.png'; a.click(); }}><IconShot /></button>
      </nav>

      {mode === 'character' && catalog && (
        <CharacterPanel tab={charTab} avatar={avatar} catalog={catalog} commit={commit} />
      )}

      <div className="look glass">
        <div className="thumb" style={{ backgroundImage: card.thumb ? `url(${card.thumb})` : undefined }} />
        <div className="info">
          <Roll className="name" text={card.name} />
          <Roll className="sub" text={card.sub} />
          {card.dots && (
            <div className="dots">
              {card.dots.list.map(([name, hex]) => (
                <button key={hex} title={name} aria-pressed={card.dots!.value === hex} className={hex === '#ffffff' ? 'orig' : ''}
                  style={hex === '#ffffff' ? undefined : { background: hex }} onClick={() => card.dots!.pick(hex)} />
              ))}
            </div>
          )}
        </div>
      </div>

      <Ask serverUrl={serverUrl} mode={mode} catalog={catalog} avatar={avatar} expr={expr} backdrop={backdrop}
        onOps={applyOps} canUndo={history.length > 0} onUndo={undo} />

      {toast && <div className={`toast glass ${toast.err ? 'err' : ''}`}>{toast.text}</div>}
      <div ref={curRef} className="cur"><span className="ring" /><span className="dot" /><span className="txt" /></div>
    </div>
  );
}

// ==================================================================== pieces

function Tabs({ options, value, onChange, className }: { options: [string, string][]; value: string; onChange: (v: string) => void; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState({ x: 0, w: 0 });
  useEffect(() => {
    const btn = ref.current?.querySelector<HTMLElement>(`[data-v="${value}"]`);
    if (btn) setPill({ x: btn.offsetLeft, w: btn.offsetWidth });
  }, [value, options]);
  return (
    <div ref={ref} className={`tabs glass ${className ?? ''}`}>
      <span className="pill" style={{ transform: `translateX(${pill.x}px)`, width: pill.w }} />
      {options.map(([v, label]) => <button key={v} data-v={v} aria-pressed={v === value} onClick={() => onChange(v)}>{label}</button>)}
    </div>
  );
}

/** Text that rolls up when it changes. */
function Roll({ text, className }: { text: string; className?: string }) {
  const [pair, setPair] = useState<{ cur: string; old: string | null; k: number }>({ cur: text, old: null, k: 0 });
  useEffect(() => { setPair((p) => (p.cur === text ? p : { cur: text, old: p.cur, k: p.k + 1 })); }, [text]);
  const anim = (from: string, to: string) => ({ animation: `roll-${from}-${to} .62s cubic-bezier(.2,.8,.2,1) both` });
  return (
    <div className={`ln ${className ?? ''}`}>
      {pair.old !== null && <span key={`o${pair.k}`} style={anim('0', 'up')}>{pair.old}</span>}
      <span key={`n${pair.k}`} style={pair.k ? anim('down', '0') : undefined}>{pair.cur}</span>
    </div>
  );
}

function TwinScan() {
  return (
    <div className="st-scan" style={{ zIndex: 13 }}>
      <div className="grid" style={{ animation: 'twin-grid 2.4s ease-in-out infinite' }} />
      <div className="line" style={{ animation: 'twin-line 2.4s cubic-bezier(.65,0,.35,1) infinite alternate' }} />
    </div>
  );
}

function Slide({ label, value, min = 0, max = 1, onChange }: { label: string; value: number; min?: number; max?: number; onChange: (v: number) => void }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <label className="slide">
      <span><span>{label}</span><span>{Math.round(pct)}</span></span>
      <input type="range" min={min} max={max} step={0.01} value={value} style={{ ['--v' as any]: `${pct}%` }}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function CharacterPanel({ tab, avatar, catalog, commit }: {
  tab: CharTab; avatar: Avatar; catalog: Catalog; commit: (n: Avatar | ((a: Avatar) => Avatar), o?: { scan?: boolean }) => void;
}) {
  const ph = avatar.pheno;
  const setPh = (patch: Record<string, number>) => commit((a) => ({ ...a, pheno: { ...a.pheno, ...patch } }));
  const near = (a: number, b: number, eps = 0.06) => Math.abs(a - b) < eps;
  const faceVal = (k: string) => avatar.local[faceKeys(k, catalog.faceChanges)[0]] ?? 0;
  const setFace = (k: string, v: number) => commit((a) => {
    const local = { ...a.local };
    for (const key of faceKeys(k, catalog.faceChanges)) local[key] = v;
    return { ...a, local };
  });
  // the three origin sliders are a mix: moving one rebalances the other two
  const setOrigin = (key: 'african' | 'asian' | 'caucasian', v: number) => {
    const others = (['african', 'asian', 'caucasian'] as const).filter((k) => k !== key);
    const rest = others.reduce((s, k) => s + (ph[k] ?? 0), 0) || 1;
    setPh({ [key]: v, ...Object.fromEntries(others.map((k) => [k, ((ph[k] ?? 0) / rest) * (1 - v)])) });
  };
  return (
    <aside className="panel glass" onPointerDown={(e) => e.stopPropagation()}>
      {tab === 'body' && <>
        <h4>{L('Gender', 'Género')}</h4>
        <div className="seg">
          {[[0, L('Woman', 'Mujer')], [0.5, L('Neutral', 'Neutro')], [1, L('Man', 'Hombre')]].map(([g, label]) => (
            <button key={label} aria-pressed={near(ph.gender, g as number, 0.2)} onClick={() => setPh({ gender: g as number })}>{label}</button>))}
        </div>
        <h4>{L('Life stage', 'Etapa de vida')}</h4>
        <div className="seg">{STAGES.map(([label, age]) => <button key={label} aria-pressed={near(ph.age, age)} onClick={() => setPh({ age })}>{label}</button>)}</div>
        <h4>{L('Build', 'Complexión')}</h4>
        <div className="seg">{BUILDS.map(([label, weight, muscle]) => (
          <button key={label} aria-pressed={near(ph.weight, weight) && near(ph.muscle, muscle)} onClick={() => setPh({ weight, muscle })}>{label}</button>))}</div>
        <h4>{L('Fine tune', 'Ajuste fino')}</h4>
        <Slide label={L('Height', 'Altura')} value={ph.height ?? 0.5} onChange={(v) => setPh({ height: v })} />
        <Slide label={L('Weight', 'Peso')} value={ph.weight ?? 0.5} onChange={(v) => setPh({ weight: v })} />
        <Slide label={L('Muscle', 'Músculo')} value={ph.muscle ?? 0.5} onChange={(v) => setPh({ muscle: v })} />
        <Slide label={L('Age', 'Edad')} value={ph.age ?? 0.5} onChange={(v) => setPh({ age: v })} />
        <h4>{L('Features', 'Rasgos')}</h4>
        <Slide label={L('African', 'Africanos')} value={ph.african ?? 0.33} onChange={(v) => setOrigin('african', v)} />
        <Slide label={L('Asian', 'Asiáticos')} value={ph.asian ?? 0.33} onChange={(v) => setOrigin('asian', v)} />
        <Slide label={L('European', 'Europeos')} value={ph.caucasian ?? 0.33} onChange={(v) => setOrigin('caucasian', v)} />
      </>}
      {tab === 'face' && <>
        {FACE_GROUPS.map((g) => (
          <React.Fragment key={g.name}>
            <h4>{g.name}</h4>
            {g.keys.filter(([k]) => faceKeys(k, catalog.faceChanges).length).map(([k, label]) => (
              <Slide key={k} label={label} value={faceVal(k)} min={-1} max={1} onChange={(v) => setFace(k, v)} />
            ))}
          </React.Fragment>
        ))}
        <div className="seg" style={{ marginTop: 14 }}><button onClick={() => commit((a) => ({ ...a, local: {} }))}>{L('Reset face', 'Restablecer cara')}</button></div>
        <p className="mini">{L('Tip: click the face, hair or clothes on the model to jump to them.', 'Truco: haz clic en la cara, el pelo o la ropa del modelo para ir directo.')}</p>
      </>}
      {tab === 'skin' && <>
        <h4>{L('Skin', 'Piel')}</h4>
        <div className="tiles">
          {catalog.skins.filter((s) => !/genitals/.test(s.id)).map((s) => (
            <button key={s.id} title={s.label} aria-pressed={avatar.skin === s.id && !avatar.faceTexture}
              style={{ backgroundImage: s.thumb ? `url(${HUMAN_URL}/asset/${s.thumb}?size=128)` : undefined }}
              onClick={() => commit((a) => ({ ...a, skin: s.id, faceTexture: undefined }))} />
          ))}
        </div>
      </>}
      {tab === 'hair' && <>
        <h4>{L('Colour', 'Color')}</h4>
        <div className="dots">
          {HAIR_TINTS.map(([name, hex]) => (
            <button key={hex} title={name} aria-pressed={avatar.hairColor === hex} className={hex === '#ffffff' ? 'orig' : ''}
              style={hex === '#ffffff' ? undefined : { background: hex }} onClick={() => commit((a) => ({ ...a, hairColor: hex }))} />
          ))}
        </div>
        <h4>{L('Hairstyle', 'Peinado')}</h4>
        <div className="tiles hair">
          {catalog.hair.map((h) => (
            <button key={h.id} title={h.label} aria-pressed={avatar.hair === h.id} style={{ backgroundImage: `url(${cut(`hair_${h.id}`)})` }}
              onClick={() => commit((a) => ({ ...a, hair: h.id }), { scan: true })} />
          ))}
        </div>
      </>}
      {tab === 'eyes' && <>
        <h4>{L('Eye colour', 'Color de ojos')}</h4>
        <div className="dots" style={{ gap: 10 }}>
          {catalog.eyeColors.map((c) => (
            <button key={c.id} title={c.id} aria-pressed={avatar.eyes === c.id} style={{ width: 28, height: 28, background: `radial-gradient(circle, #111 22%, ${EYE_HEX[c.id] ?? '#777'} 26%, ${EYE_HEX[c.id] ?? '#777'} 70%, #222 74%)` }}
              onClick={() => commit((a) => ({ ...a, eyes: c.id }))} />
          ))}
        </div>
        {FACE_GROUPS.filter((g) => g.keys[0][0].startsWith('eye')).map((g) => g.keys.filter(([k]) => faceKeys(k, catalog.faceChanges).length).map(([k, label]) => (
          <Slide key={k} label={label} value={faceVal(k)} min={-1} max={1} onChange={(v) => setFace(k, v)} />
        )))}
      </>}
    </aside>
  );
}

/** Say it or type it: the phrase becomes small edits (LLM on the backend, catalog-checked). */
function Ask({ serverUrl, mode, catalog, avatar, expr, backdrop, onOps, canUndo, onUndo }: {
  serverUrl: string; mode: Mode; catalog: Catalog | null; avatar: Avatar; expr: string; backdrop: string;
  onOps: (ops: Op[]) => void; canUndo: boolean; onUndo: () => void;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [rec, setRec] = useState<MediaRecorder | null>(null);

  async function send(body: { text?: string; audio_b64?: string; mime?: string }) {
    if (!catalog) return;
    setBusy(true);
    setStatus(body.audio_b64 ? L('Listening…', 'Escuchando…') : '');
    try {
      const res = await fetch(`${serverUrl}/api/v1/human/edit`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          ...body,
          state: { mode, wearing: avatar.clothes, hair: avatar.hair, hairColor: avatar.hairColor, skin: avatar.skin, eyes: avatar.eyes,
            accessories: avatar.accessories.map((a) => a.id), pheno: avatar.pheno, expression: expr, background: backdrop, language: es ? 'es' : 'en' },
          options: {
            clothes: catalog.clothes.map((c) => c.id), hair: catalog.hair.map((h) => h.id), skins: catalog.skins.map((s) => s.id),
            eyes: catalog.eyeColors.map((e) => e.id), face: FACE_GROUPS.flatMap((g) => g.keys.map(([k]) => k)),
            accessories: ACCESSORIES.map((a) => a.id), expressions: EXPRS, backgrounds: BACKDROPS.map((b) => b.id), presets: CHARACTERS.map((c) => c.id),
            garment_names: GARMENT_NAMES,
          },
        }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail ?? res.statusText);
      if (out.transcript && body.audio_b64) setText(out.transcript);
      onOps(out.ops ?? []);
      setStatus(out.say || (out.ops?.length ? L('Done', 'Hecho') : L('I could not do that one', 'No pude hacer eso')));
      if (!body.audio_b64) setText('');
    } catch (err) {
      setStatus(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleMic() {
    if (rec) { rec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRec(null);
        const blob = new Blob(chunks, { type: r.mimeType });
        const b64 = btoa(Array.from(new Uint8Array(await blob.arrayBuffer()), (b) => String.fromCharCode(b)).join(''));
        void send({ audio_b64: b64, mime: r.mimeType });
      };
      r.start();
      setRec(r);
      setStatus(L('Recording — tap again to send', 'Grabando — toca otra vez para enviar'));
    } catch {
      setStatus(L('No microphone access', 'Sin acceso al micrófono'));
    }
  }

  return (
    <div className="ask">
      <div className="examples">
        {PROMPTS[mode].map((p) => <button key={p} className="glass" onClick={() => void send({ text: p })} disabled={busy}>{p}</button>)}
      </div>
      <form className={`glass ${busy ? 'busy' : ''}`} onSubmit={(e) => { e.preventDefault(); if (text.trim()) void send({ text }); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} disabled={busy}
          placeholder={mode === 'fitting' ? L('Describe the change: "white top and gold hoops"…', 'Describe el cambio: "top blanco y aros dorados"…')
            : L('Describe them: "taller, curly red hair, green eyes"…', 'Descríbelo: "más alta, pelo rizado pelirrojo, ojos verdes"…')} />
        <button type="button" className={`icon ${rec ? 'rec' : ''}`} onClick={toggleMic} title={L('Say it', 'Dilo')}><IconMic /></button>
        <button type="submit" className="icon go" disabled={busy || !text.trim()} title={L('Apply', 'Aplicar')}><IconArrow /></button>
      </form>
      <div className="status">{status}{canUndo && status && <button onClick={onUndo}>{L('Undo', 'Deshacer')}</button>}</div>
    </div>
  );
}

// ==================================================================== icons (24px, stroke)
const I = ({ d, fill }: { d: string; fill?: boolean }) => (
  <svg viewBox="0 0 24 24" fill={fill ? 'currentColor' : 'none'} stroke={fill ? 'none' : 'currentColor'} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);
const IconFace = () => <I d="M12 3a6 6 0 0 1 6 6v2a6 6 0 0 1-12 0V9a6 6 0 0 1 6-6zM9.5 10h.01M14.5 10h.01M10 14.5c1.2.8 2.8.8 4 0" />;
const IconBust = () => <I d="M12 4a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM4.5 20c.8-4 3.8-6.5 7.5-6.5s6.7 2.5 7.5 6.5" />;
const IconBody = () => <I d="M12 2.5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM8 8.5h8l-1.2 6H13l-.6 7h-.8l-.6-7H9.2z" />;
const IconSmile = () => <I d="M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM8.5 14c.9 1.4 2.1 2 3.5 2s2.6-.6 3.5-2M9 9.5h.01M15 9.5h.01" />;
const IconVoice = () => <I d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />;
const IconShot = () => <I d="M4 8h3l1.5-2h7L17 8h3v11H4zM12 11a3 3 0 1 1 0 6 3 3 0 0 1 0-6z" />;
const IconMic = () => <I d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />;
const IconArrow = () => <I d="M5 12h14M13 6l6 6-6 6" />;
const IconCamera = () => <I d="M4 8h3l1.5-2h7L17 8h3v11H4zM12 11a3 3 0 1 1 0 6 3 3 0 0 1 0-6z" />;
const IconScene = () => <I d="M3 5h18v14H3zM3 15l5-5 4 4 3-3 6 6" />;
const IconHanger = () => <I d="M12 7a2 2 0 1 1 2-2M12 7v2l9 6v2H3v-2l9-6" />;
const IconArc = () => <I d="M3 16c3-6 15-6 18 0M6 12.5v4M12 11v5M18 12.5v4" />;
