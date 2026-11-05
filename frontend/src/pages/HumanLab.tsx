// exp/three-human: MetaHuman-style creator on three.js (?human=1).
// Body = Anny (NAVER, Apache-2.0), clothes/hair/skins = MakeHuman (CC0), baked by human/server.py.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { HumanEngine, type Framing } from '../human/engine';
import { Speech, type SpeechStats } from '../human/speech';
import { LANG } from '../i18n';

const HUMAN_URL = (import.meta.env.VITE_HUMAN_URL || 'http://localhost:8010').replace(/\/$/, '');

type Item = { id: string; label: string; thumb?: string; proxy?: string; material?: { diffuseTexture?: string } };
type Catalog = {
  skins: Item[]; hair: Item[]; clothes: Item[]; eyebrows: Item[]; eyelashes: Item[];
  eyeColors: { id: string; material: { diffuseTexture?: string } }[];
  faceChanges: string[]; fixed: Record<string, string>;
};
type Tab = 'body' | 'face' | 'skin' | 'hair' | 'clothes' | 'studio' | 'voice' | 'twin';
type TwinFit = { phenotype: Record<string, number>; local: Record<string, number>; texture: string; error_iod: number; fit_s: number };

const es = LANG === 'es';
const L = (en: string, sp: string) => (es ? sp : en);

const STAGES = [
  { id: 'child', label: L('Child', 'Niño'), sub: L('About 8', 'Unos 8'), age: 0.12 },
  { id: 'teen', label: L('Teen', 'Adolescente'), sub: L('About 15', 'Unos 15'), age: 0.3 },
  { id: 'adult', label: L('Adult', 'Adulto'), sub: L('About 30', 'Unos 30'), age: 0.5 },
  { id: 'elder', label: L('Elder', 'Mayor'), sub: L('About 75', 'Unos 75'), age: 0.95 },
];
const BUILDS = [
  { id: 'slim', label: L('Slim', 'Delgado'), weight: 0.2, muscle: 0.35 },
  { id: 'average', label: L('Average', 'Medio'), weight: 0.5, muscle: 0.5 },
  { id: 'athletic', label: L('Athletic', 'Atlético'), weight: 0.42, muscle: 0.85 },
  { id: 'heavy', label: L('Heavy', 'Robusto'), weight: 0.92, muscle: 0.4 },
];
const SLIDERS: [string, string][] = [
  ['gender', L('Feminine ↔ masculine', 'Femenino ↔ masculino')], ['age', L('Age', 'Edad')], ['muscle', L('Muscle', 'Músculo')],
  ['weight', L('Weight', 'Peso')], ['height', L('Height', 'Altura')], ['proportions', L('Proportions', 'Proporciones')],
  ['african', L('African traits', 'Rasgos africanos')], ['asian', L('Asian traits', 'Rasgos asiáticos')], ['caucasian', L('European traits', 'Rasgos europeos')],
];
// one slider per pair: l-/r- prefixed changes move together
const FACE = [
  'head-scale-vert', 'head-scale-horiz', 'head-fat', 'forehead-scale-vert', 'eyebrows-trans-up', 'eye-scale', 'eye-trans-up',
  'eye-epicanthus-out', 'eye-bag', 'nose-scale-horiz', 'nose-scale-vert', 'nose-scale-depth', 'nose-hump', 'nose-point-up',
  'mouth-scale-horiz', 'mouth-upperlip-volume', 'mouth-lowerlip-volume', 'mouth-angles-up', 'chin-prominent', 'chin-width',
  'chin-height', 'cheek-bones', 'cheek-volume', 'ear-scale', 'neck-scale-horiz',
];
const EXPRESSIONS = ['neutral', 'smile', 'happy', 'surprised', 'sad', 'angry', 'thinking'];
const EXPR_LABEL: Record<string, string> = es
  ? { neutral: 'Neutra', smile: 'Sonrisa', happy: 'Alegre', surprised: 'Sorpresa', sad: 'Triste', angry: 'Enfado', thinking: 'Pensando' }
  : { neutral: 'Neutral', smile: 'Smile', happy: 'Happy', surprised: 'Surprised', sad: 'Sad', angry: 'Angry', thinking: 'Thinking' };
const HAIR_COLORS = ['#ffffff', '#2b1d14', '#5a3a22', '#a5743f', '#d8b278', '#8a3b22', '#9aa0a6', '#1a1a1a'];
const CLOTH_COLORS = ['#ffffff', '#c8102e', '#1f2a44', '#2f5d3a', '#e0c068', '#222222', '#b9b9b9', '#7a4a2a'];
const SAY = es
  ? ['Hola, soy tu humano digital hecho con three.js.', '¿Qué tal tu día? Cuéntame algo que te haya hecho reír.', 'Explícame en una frase qué es MEYA.']
  : ['Hi, I am your digital human built with three.js.', 'How was your day? Tell me something that made you laugh.', 'Explain MEYA in one sentence.'];

function faceKeys(name: string, changes: string[]) {
  return changes.filter((c) => c === `${name}-incr` || c === `${name}` || c === `l-${name}-incr` || c === `r-${name}-incr`
    || c === `l-${name}` || c === `r-${name}` || c === `${name}-out` || c === `l-${name}-out` || c === `r-${name}-out` || c === `${name}-up`);
}

export function HumanLab({ serverUrl, onBack }: { serverUrl: string; onBack: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<HumanEngine | null>(null);
  const speech = useRef<Speech | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('body');
  const [pheno, setPheno] = useState<Record<string, number>>({ gender: 0, age: 0.5, muscle: 0.5, weight: 0.45, height: 0.5, proportions: 0.5, african: 1 / 3, asian: 1 / 3, caucasian: 1 / 3 });
  const [local, setLocal] = useState<Record<string, number>>({});
  const [hair, setHair] = useState('ponytail01');
  const [brows, setBrows] = useState('eyebrow001');
  const [lashes, setLashes] = useState('eyelashes01');
  const [clothes, setClothes] = useState<string[]>(['female_casualsuit01', 'shoes01']);
  const [skin, setSkin] = useState('young_caucasian_female');
  const [eye, setEye] = useState('brown');
  const [hairColor, setHairColor] = useState('#ffffff');
  const [clothColor, setClothColor] = useState('#ffffff');
  const [expr, setExpr] = useState('neutral');
  const [walking, setWalking] = useState(false);
  const [bake, setBake] = useState({ busy: false, ms: 0, loadMs: 0, kb: 0 });
  const [fps, setFps] = useState(0);
  const [voice, setVoice] = useState<{ state: string; text?: string; stats?: SpeechStats }>({ state: 'offline' });
  const [say, setSay] = useState('');
  const [twin, setTwin] = useState<{ busy: boolean; fit?: TwinFit; error?: string; ms?: number }>({ busy: false });

  useEffect(() => {
    fetch(`${HUMAN_URL}/catalog`).then((r) => r.json()).then(setCatalog)
      .catch(() => setError(L(`Start the human service: cd human && .venv/bin/uvicorn server:app --port 8010`, `Arranca el servicio: cd human && .venv/bin/uvicorn server:app --port 8010`)));
    const e = new HumanEngine(host.current!, HUMAN_URL);
    engine.current = e;
    const s = new Speech(serverUrl);
    s.onState = (state, text) => setVoice((v) => ({ ...v, state, text: text ?? v.text }));
    s.onStats = (stats) => setVoice((v) => ({ ...v, stats }));
    s.connect();
    speech.current = s;
    e.mouth = () => s.mouth();
    const fpsTimer = setInterval(() => setFps(Math.round(e.fps)), 1000);
    return () => { clearInterval(fpsTimer); s.close(); e.dispose(); };
  }, [serverUrl]);

  const find = (list: Item[] | undefined, id: string) => list?.find((i) => i.id === id);
  const look = useMemo(() => ({
    skin: find(catalog?.skins, skin)?.material?.diffuseTexture,
    eyes: catalog?.eyeColors.find((c) => c.id === eye)?.material.diffuseTexture,
    hairColor, clothesColor: clothColor,
    faceTexture: twin.fit ? `${HUMAN_URL}${twin.fit.texture}` : undefined,
  }), [catalog, skin, eye, hairColor, clothColor, twin.fit]);
  const proxies = useMemo(() => {
    if (!catalog) return [];
    const pick = (list: Item[], id: string) => find(list, id)?.proxy;
    return [catalog.fixed.eyes, catalog.fixed.teeth, catalog.fixed.tongue, pick(catalog.eyebrows, brows), pick(catalog.eyelashes, lashes),
      pick(catalog.hair, hair), ...clothes.map((c) => pick(catalog.clothes, c))].filter(Boolean) as string[];
  }, [catalog, hair, brows, lashes, clothes]);

  // re-bake when the shape or the proxies change (debounced: sliders fire on every pixel)
  const lookRef = useRef(look);
  lookRef.current = look;
  useEffect(() => {
    if (!catalog) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setBake((b) => ({ ...b, busy: true }));
      try {
        const t0 = performance.now();
        const res = await fetch(`${HUMAN_URL}/bake`, {
          method: 'POST', headers: { 'content-type': 'application/json' }, signal: ctrl.signal,
          body: JSON.stringify({ phenotype: pheno, local, proxies }),
        });
        const glb = await res.arrayBuffer();
        const t1 = performance.now();
        await engine.current!.load(glb, lookRef.current);
        setBake({ busy: false, ms: Math.round(t1 - t0), loadMs: Math.round(performance.now() - t1), kb: Math.round(glb.byteLength / 1024) });
      } catch (err) {
        if ((err as Error).name !== 'AbortError') { setError(String(err)); setBake((b) => ({ ...b, busy: false })); }
      }
    }, 180);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [catalog, pheno, local, proxies]);

  useEffect(() => { void engine.current?.setLook(look); }, [look]);
  useEffect(() => { engine.current?.setExpression(expr); }, [expr]);
  useEffect(() => { if (engine.current) engine.current.walking = walking; if (walking) engine.current?.frame('full'); }, [walking]);

  const setFace = (name: string, v: number) => {
    const keys = faceKeys(name, catalog?.faceChanges ?? []);
    setLocal((l) => { const n = { ...l }; for (const k of keys) n[k] = v; return n; });
  };
  const faceValue = (name: string) => local[faceKeys(name, catalog?.faceChanges ?? [])[0]] ?? 0;
  const speak = (text: string) => { if (speech.current?.say(text)) setSay(''); };
  const fitTwin = async (photo: Blob) => {
    setTwin({ busy: true });
    const t0 = performance.now();
    try {
      const res = await fetch(`${HUMAN_URL}/twin/fit`, { method: 'POST', body: photo, headers: { 'content-type': 'application/octet-stream' } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
      const fit = (await res.json()) as TwinFit;
      setPheno((p) => ({ ...p, ...fit.phenotype }));
      setLocal(fit.local);
      setBrows(''); // the photo already carries the brows
      setTwin({ busy: false, fit, ms: Math.round(performance.now() - t0) });
    } catch (err) {
      setTwin({ busy: false, error: String((err as Error).message ?? err) });
    }
  };
  const shot = () => {
    const a = document.createElement('a');
    a.href = engine.current!.screenshot();
    a.download = 'human.png';
    a.click();
  };

  return (
    <div style={{ position: 'fixed', inset: 0, display: 'flex', background: '#2b2e34', color: '#e8e8e8', fontFamily: 'Inter, system-ui, sans-serif' }}>
      <div ref={host} data-testid="human-canvas" style={{ flex: 1, position: 'relative', minWidth: 0 }}>
        <button onClick={onBack} style={pill({ position: 'absolute', top: 16, left: 16 })}>← {L('Back', 'Volver')}</button>
        <div style={{ position: 'absolute', left: 16, bottom: 16, fontSize: 12, opacity: 0.75, lineHeight: 1.6 }}>
          <div>{bake.busy ? L('Baking…', 'Horneando…') : L(`Bake ${bake.ms} ms · load ${bake.loadMs} ms · ${bake.kb} KB`, `Horneado ${bake.ms} ms · carga ${bake.loadMs} ms · ${bake.kb} KB`)} · {fps} fps</div>
          <div>{L('Anny body (NAVER, Apache-2.0) · MakeHuman assets (CC0) · three.js', 'Cuerpo Anny (NAVER, Apache-2.0) · assets MakeHuman (CC0) · three.js')}</div>
        </div>
        {voice.text && voice.state === 'speaking' && (
          <div style={{ position: 'absolute', bottom: 64, left: '50%', transform: 'translateX(-50%)', background: 'rgba(0,0,0,0.55)', padding: '8px 14px', borderRadius: 10, maxWidth: '70%', fontSize: 15 }}>{voice.text}</div>
        )}
        {error && <div style={{ position: 'absolute', top: 64, left: 16, right: 16, background: '#5a1d1d', padding: 12, borderRadius: 8, fontSize: 13 }}>{error}</div>}
      </div>

      <aside style={{ width: 340, background: 'rgba(22,24,28,0.96)', borderLeft: '1px solid #333', overflowY: 'auto', padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <strong style={{ fontSize: 18 }}>{L('Human creator', 'Creador humano')}</strong>
          <span style={{ fontSize: 11, opacity: 0.6 }}>exp/three-human</span>
        </div>
        <nav style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 16 }}>
          {([['body', L('Body', 'Cuerpo')], ['face', L('Face', 'Cara')], ['skin', L('Skin', 'Piel')], ['hair', L('Hair', 'Pelo')],
            ['clothes', L('Clothes', 'Ropa')], ['studio', L('Studio', 'Estudio')], ['voice', L('Voice', 'Voz')], ['twin', 'Twin']] as [Tab, string][]).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={chip(tab === id)}>{label}</button>
          ))}
        </nav>

        {tab === 'body' && (
          <>
            <Row>{[[0, L('Female', 'Mujer')], [1, L('Male', 'Hombre')]].map(([g, label]) => (
              <button key={label} onClick={() => setPheno((p) => ({ ...p, gender: g as number }))} style={chip(Math.round(pheno.gender) === g)}>{label}</button>))}</Row>
            <H>{L('Life stage', 'Etapa de vida')}</H>
            <Row>{STAGES.map((s) => (
              <button key={s.id} onClick={() => setPheno((p) => ({ ...p, age: s.age }))} style={chip(Math.abs(pheno.age - s.age) < 0.06)}>
                {s.label}<br /><small style={{ opacity: 0.6 }}>{s.sub}</small></button>))}</Row>
            <H>{L('Build', 'Complexión')}</H>
            <Row>{BUILDS.map((b) => (
              <button key={b.id} onClick={() => setPheno((p) => ({ ...p, weight: b.weight, muscle: b.muscle }))}
                style={chip(Math.abs(pheno.weight - b.weight) < 0.05 && Math.abs(pheno.muscle - b.muscle) < 0.05)}>{b.label}</button>))}</Row>
            <H>{L('Fine tune', 'Ajuste fino')}</H>
            {SLIDERS.map(([k, label]) => (
              <Slider key={k} label={label} value={pheno[k] ?? 0.5} min={0} max={1} onChange={(v) => setPheno((p) => ({ ...p, [k]: v }))} />
            ))}
          </>
        )}

        {tab === 'face' && (
          <>
            <button onClick={() => setLocal({})} style={chip(false)}>{L('Reset face', 'Restablecer cara')}</button>
            {FACE.filter((f) => faceKeys(f, catalog?.faceChanges ?? []).length).map((f) => (
              <Slider key={f} label={f.replace(/-/g, ' ')} value={faceValue(f)} min={-1} max={1} onChange={(v) => setFace(f, v)} />
            ))}
          </>
        )}

        {tab === 'skin' && (
          <>
            <Grid items={catalog?.skins ?? []} selected={skin} onPick={setSkin} />
            <H>{L('Eyes', 'Ojos')}</H>
            <Row>{catalog?.eyeColors.map((c) => <button key={c.id} onClick={() => setEye(c.id)} style={chip(eye === c.id)}>{c.id}</button>)}</Row>
          </>
        )}

        {tab === 'hair' && (
          <>
            <H>{L('Colour', 'Color')}</H>
            <Swatches colors={HAIR_COLORS} value={hairColor} onPick={setHairColor} />
            <H>{L('Hairstyle', 'Peinado')}</H>
            <Grid items={[{ id: '', label: L('Bald', 'Sin pelo') }, ...(catalog?.hair ?? [])]} selected={hair} onPick={setHair} />
            <H>{L('Eyebrows', 'Cejas')}</H>
            <Grid items={[{ id: '', label: L('None', 'Ninguna') }, ...(catalog?.eyebrows ?? [])]} selected={brows} onPick={setBrows} small />
            <H>{L('Eyelashes', 'Pestañas')}</H>
            <Grid items={catalog?.eyelashes ?? []} selected={lashes} onPick={setLashes} small />
          </>
        )}

        {tab === 'clothes' && (
          <>
            <H>{L('Colour tint', 'Tono')}</H>
            <Swatches colors={CLOTH_COLORS} value={clothColor} onPick={setClothColor} />
            <H>{L('Outfits and shoes (pick several)', 'Conjuntos y zapatos (puedes elegir varios)')}</H>
            <Grid items={catalog?.clothes ?? []} selected={clothes} onPick={(id) => setClothes((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]))} />
          </>
        )}

        {tab === 'studio' && (
          <>
            <H>{L('Camera', 'Cámara')}</H>
            <Row>{(['face', 'bust', 'full'] as Framing[]).map((f) => (
              <button key={f} onClick={() => engine.current?.frame(f)} style={chip(false)}>{{ face: L('Face', 'Cara'), bust: L('Bust', 'Busto'), full: L('Full body', 'Cuerpo entero') }[f]}</button>))}</Row>
            <H>{L('Motion', 'Movimiento')}</H>
            <Row><button onClick={() => setWalking((w) => !w)} style={chip(walking)}>{walking ? L('Stop walking', 'Parar') : L('Walk', 'Caminar')}</button>
              <button onClick={shot} style={chip(false)}>{L('Screenshot', 'Captura')}</button></Row>
            <H>{L('Expression', 'Expresión')}</H>
            <Row>{EXPRESSIONS.map((x) => <button key={x} onClick={() => setExpr(x)} style={chip(expr === x)}>{EXPR_LABEL[x]}</button>)}</Row>
          </>
        )}

        {tab === 'twin' && (
          <>
            <p style={{ fontSize: 13, opacity: 0.75, marginTop: 0 }}>
              {L('Only of yourself. Fits the face shape to your photo and projects it onto the skin, on CPU in about 12 s.',
                'Solo de ti mismo. Ajusta la forma de la cara a tu foto y la proyecta sobre la piel, en CPU en unos 12 s.')}
            </p>
            <input type="file" accept="image/*" disabled={twin.busy} onChange={(e) => e.target.files?.[0] && fitTwin(e.target.files[0])} />
            <Row><button disabled={twin.busy} onClick={async () => fitTwin(await (await fetch(`${HUMAN_URL}/twin/tex/test_portrait.jpg`)).blob())} style={chip(false)}>
              {L('Use the test portrait', 'Usar el retrato de prueba')}</button>
              {twin.fit && <button onClick={() => { setTwin({ busy: false }); setLocal({}); setBrows('eyebrow001'); }} style={chip(false)}>{L('Remove Twin', 'Quitar Twin')}</button>}</Row>
            <div style={{ fontSize: 12, marginTop: 10, opacity: 0.85 }}>
              {twin.busy && L('Fitting…', 'Ajustando…')}
              {twin.error && <span style={{ color: '#ff8a8a' }}>{twin.error}</span>}
              {twin.fit && L(`Landmark error ${(twin.fit.error_iod * 100).toFixed(1)}% of eye distance · ${twin.ms} ms`,
                `Error de puntos ${(twin.fit.error_iod * 100).toFixed(1)}% de la distancia entre ojos · ${twin.ms} ms`)}
            </div>
          </>
        )}

        {tab === 'voice' && (
          <>
            <p style={{ fontSize: 13, opacity: 0.75, marginTop: 0 }}>
              {L('Talks through the same orchestrator as the Feed (LLM + ElevenLabs). Lips move from its visemes, no GPU.',
                'Habla con el mismo orquestador que el Feed (LLM + ElevenLabs). Los labios se mueven con sus visemas, sin GPU.')}
            </p>
            <div style={{ fontSize: 12, marginBottom: 8 }}>
              {L('State', 'Estado')}: <b>{voice.state}</b>
              {voice.stats?.firstAudioMs != null && <> · {L('first audio', 'primer audio')} <b>{voice.stats.firstAudioMs} ms</b></>}
              {voice.stats?.firstChunkMs != null && <> · {L('first chunk', 'primer trozo')} {voice.stats.firstChunkMs} ms</>}
              {voice.stats?.firstChunkServerMs != null && <> · {L('server', 'servidor')} {voice.stats.firstChunkServerMs} ms</>}
            </div>
            {SAY.map((s) => <button key={s} onClick={() => speak(s)} style={{ ...chip(false), display: 'block', width: '100%', textAlign: 'left', marginBottom: 6 }}>{s}</button>)}
            <textarea value={say} onChange={(e) => setSay(e.target.value)} rows={3} placeholder={L('Ask something…', 'Pregunta algo…')}
              style={{ width: '100%', boxSizing: 'border-box', background: '#111', color: '#eee', border: '1px solid #444', borderRadius: 8, padding: 8 }} />
            <Row><button onClick={() => speak(say)} style={chip(true)}>{L('Send', 'Enviar')}</button>
              <button onClick={() => speech.current?.stop()} style={chip(false)}>{L('Stop', 'Parar')}</button></Row>
          </>
        )}
      </aside>
    </div>
  );
}

const pill = (extra: React.CSSProperties = {}): React.CSSProperties => ({
  padding: '8px 14px', borderRadius: 999, background: 'rgba(255,255,255,0.08)', color: '#e5e5e5', fontSize: 14,
  border: '1px solid rgba(255,255,255,0.15)', cursor: 'pointer', zIndex: 2, ...extra,
});
const chip = (on: boolean): React.CSSProperties => ({
  padding: '7px 8px', borderRadius: 10, fontSize: 12, cursor: 'pointer', color: '#eee', lineHeight: 1.25,
  background: on ? 'rgba(200,16,46,0.18)' : 'rgba(255,255,255,0.05)', border: `1px solid ${on ? '#c8102e' : '#3a3a3a'}`,
});
const H = ({ children }: { children: React.ReactNode }) => <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 8px' }}>{children}</div>;
const Row = ({ children }: { children: React.ReactNode }) => <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>{children}</div>;

function Slider({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <label style={{ display: 'block', fontSize: 12, margin: '10px 0' }}>
      <span style={{ display: 'flex', justifyContent: 'space-between', opacity: 0.85 }}><span>{label}</span><span>{value.toFixed(2)}</span></span>
      <input type="range" min={min} max={max} step={0.01} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ width: '100%', accentColor: '#c8102e' }} />
    </label>
  );
}

function Swatches({ colors, value, onPick }: { colors: string[]; value: string; onPick: (c: string) => void }) {
  return (
    <Row>{colors.map((c) => (
      <button key={c} onClick={() => onPick(c)} title={c}
        style={{ width: 28, height: 28, borderRadius: 999, background: c === '#ffffff' ? 'conic-gradient(#d33,#3d3,#33d,#d33)' : c, border: value === c ? '2px solid #fff' : '1px solid #555', cursor: 'pointer' }} />
    ))}</Row>
  );
}

function Grid({ items, selected, onPick, small }: { items: Item[]; selected: string | string[]; onPick: (id: string) => void; small?: boolean }) {
  const on = (id: string) => (Array.isArray(selected) ? selected.includes(id) : selected === id);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${small ? 4 : 3}, 1fr)`, gap: 8 }}>
      {items.map((i) => (
        <button key={i.id || 'none'} onClick={() => onPick(i.id)} title={i.label}
          style={{ ...chip(on(i.id)), padding: 4, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          {i.thumb ? <img src={`${HUMAN_URL}/asset/${i.thumb}`} alt="" loading="lazy" style={{ width: '100%', aspectRatio: '1', objectFit: 'cover', borderRadius: 8, background: '#222' }} />
            : <div style={{ width: '100%', aspectRatio: '1', borderRadius: 8, background: '#222' }} />}
          <span style={{ fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', width: '100%' }}>{i.label}</span>
        </button>
      ))}
    </div>
  );
}
