// ?human=embed: the 3D look inside MEYA's Create flow. The parent page sends what the person wrote, a photo of them,
// and (after the first result) the chips they changed; this page answers with a living half body (Anny + MakeHuman,
// three.js) and a still of it.
//   parent -> { type: 'meya:3d:make', prompt?: string, intro?: string, photo?: dataURL, look?: Partial<Spec> }
//             prompt = the look description; intro = other text about the being (only its sex and age are read);
//             look = chip overrides (sex, hair, hairColor, tone, build, outfit, outfitColor), winning over the words
//   embed  -> { type: 'meya:3d:ready' } on load, { type: 'meya:3d:busy' },
//             { type: 'meya:3d:done', still: dataURL, summary, look: Resolved, photo: boolean } or { type: 'meya:3d:error', message }
// Words are read deterministically in ./studio/words.ts. The full wardrobe studio (every slider and garment) is ?human=1.
import { useEffect, useRef, useState } from 'react';
import { HumanEngine } from './engine';
import { HUMAN_URL, bake, lookOf, type Catalog } from './studio/avatar';
import { buildAvatar, merge, parseWords, type Spec } from './studio/words';

type Fit = { phenotype: Record<string, number>; local: Record<string, number>; texture: string };

export function Embed() {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<HumanEngine | null>(null);
  const cat = useRef<Catalog | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Inside MEYA's preview card: the card's colour shows through.
    document.documentElement.style.background = document.body.style.background = 'transparent';
    const e = new HumanEngine(host.current!, HUMAN_URL, true);
    e.controls.enabled = false;
    engine.current = e;
    let dead = false;
    const post = (msg: unknown) => window.parent.postMessage(msg, '*');
    fetch(`${HUMAN_URL}/catalog`).then((r) => r.json()).then((c: Catalog) => { cat.current = c; if (!dead) post({ type: 'meya:3d:ready' }); });

    let lastFit: { photo: string; fit: Fit } | null = null; // a chip change after a photo reuses its ~13 s fit
    const make = async (data: { prompt?: string; intro?: string; photo?: string; look?: Partial<Spec> }) => {
      if (!cat.current) return;
      setBusy(true);
      post({ type: 'meya:3d:busy' });
      try {
        const intro = parseWords(data.intro ?? '');
        const spec = merge(merge({ sex: intro.sex, age: intro.age }, parseWords(data.prompt ?? '')), data.look);
        let fit: Fit | null = null;
        if (data.photo) {
          if (lastFit?.photo === data.photo) fit = lastFit.fit;
          else {
            const photo = await (await fetch(data.photo)).blob();
            const res = await fetch(`${HUMAN_URL}/twin/fit`, { method: 'POST', body: photo, headers: { 'content-type': 'application/octet-stream' } });
            if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
            fit = await res.json() as Fit;
            lastFit = { photo: data.photo, fit };
          }
        }
        // the photo decides sex and age unless the words or chips say otherwise
        const { avatar, summary, look } = buildAvatar(spec, fit ? { gender: fit.phenotype.gender, age: fit.phenotype.age } : {});
        if (fit) {
          const forced = { ...(spec.sex ? { gender: avatar.pheno.gender } : {}), ...(spec.build ? { weight: avatar.pheno.weight } : {}) };
          Object.assign(avatar, { pheno: { ...avatar.pheno, ...fit.phenotype, ...forced }, local: fit.local, brows: '', faceTexture: `${HUMAN_URL}${fit.texture}` });
        }
        const glb = await bake(cat.current, avatar);
        if (dead) return;
        await e.load(glb, lookOf(cat.current, avatar));
        e.frame('bust');
        await new Promise((r) => setTimeout(r, 600)); // a few frames of idle before the still
        post({ type: 'meya:3d:done', still: e.renderer.domElement.toDataURL('image/png'), summary, look, photo: !!fit });
      } catch (err) {
        post({ type: 'meya:3d:error', message: String((err as Error).message ?? err) });
      } finally {
        setBusy(false);
      }
    };
    const onMessage = (ev: MessageEvent) => { if (ev.data?.type === 'meya:3d:make') void make(ev.data); };
    window.addEventListener('message', onMessage);
    return () => { dead = true; window.removeEventListener('message', onMessage); e.dispose(); };
  }, []);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'transparent' }}>
      <div ref={host} style={{ position: 'absolute', inset: 0 }} />
      {busy && <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', font: '500 13px system-ui', color: '#8a8a84' }}>…</div>}
    </div>
  );
}
