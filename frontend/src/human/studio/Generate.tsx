// ?human=gen — renders the studio cut-outs with the creator itself (transparent PNG → human/studio/*.webp):
// one per character, one ghost-mannequin per garment and one per hairstyle. Run once after changing presets.
import { useEffect, useRef, useState } from 'react';
import { HumanEngine } from '../engine';
import { CHARACTERS, categoryOf } from './presets';
import { HUMAN_URL, bake, fromCharacter, lookOf, type Avatar, type Catalog } from './avatar';

import { ANGLES } from './Hanger';

const THREE_DEG = Math.PI / 180;
const BASE_F = fromCharacter(CHARACTERS[0]);
const BASE_M = fromCharacter(CHARACTERS[13]);

export function Generate() {
  const host = useRef<HTMLDivElement>(null);
  const [log, setLog] = useState<string[]>([]);
  useEffect(() => {
    const engine = new HumanEngine(host.current!, HUMAN_URL, true);
    let stop = false;
    const say = (s: string) => setLog((l) => [...l.slice(-30), s]);
    (async () => {
      const cat = (await (await fetch(`${HUMAN_URL}/catalog`)).json()) as Catalog;
      const only = new URLSearchParams(location.search).get('only'); // e.g. only=char or only=hair_elvs,char_mei
      type Job = { name: string; avatar: Avatar; isolate: string[] | null; yaw?: number; frame: () => void };
      const jobs: Job[] = [];
      for (const c of CHARACTERS) {
        jobs.push({ name: `char_${c.id}`, avatar: fromCharacter(c), isolate: null, frame: () => engine.frame('full') });
      }
      // everything that hangs in the closet turns from profile (on the rail) to front: one frame every 30°
      const turning = (name: string, avatar: Avatar, isolate: string[] | null, frame: () => void) => {
        for (const deg of ANGLES) jobs.push({ name: deg ? `${name}_a${deg}` : name, avatar, isolate, yaw: THREE_DEG * deg, frame });
      };
      for (const g of cat.clothes) {
        const kind = categoryOf(g.id);
        const base = g.id.startsWith('male_') ? BASE_M : BASE_F;
        const avatar: Avatar = { ...base, clothes: [g.id], tints: {}, accessories: [], hair: kind === 'hats' ? '' : base.hair };
        turning(`garment_${g.id}`, avatar, [g.id], kind === 'shoes' ? () => engine.frameBones('foot.L', 'foot.R', 2.4)
          : kind === 'hats' ? () => engine.frame('bust') : () => engine.frame('full'));
      }
      for (const h of cat.hair) {
        turning(`hair_${h.id}`, { ...BASE_F, hair: h.id, hairColor: '#ffffff', accessories: [] }, [h.id], () => engine.frame('bust'));
      }
      for (const id of ['hoops', 'studs', 'glasses', 'sunglasses'] as const) {
        // shown worn, on a face with the ears clear: a lone hoop is a speck on a card
        turning(`acc_${id}`, { ...BASE_F, hair: 'ponytail01', accessories: [{ id }] }, null, () => engine.frame('face'));
      }
      for (const job of jobs) {
        if (stop) return;
        if (only && !only.split(',').some((p) => job.name.startsWith(p))) continue;
        try {
          await engine.load(await bake(cat, job.avatar), lookOf(cat, job.avatar));
          engine.setYaw(job.yaw ?? 0);
          engine.isolate(job.isolate, job.isolate === null);
          job.frame();
          const png = await (await fetch(await engine.cutout())).blob();
          const res = await fetch(`${HUMAN_URL}/studio/${job.name}`, { method: 'POST', body: png });
          say(`${job.name}: ${res.ok ? 'ok' : res.status}`);
        } catch (e) {
          say(`${job.name}: ${(e as Error).message}`);
        }
      }
      say('done');
    })();
    return () => { stop = true; engine.dispose(); };
  }, []);
  return (
    <div style={{ position: 'fixed', inset: 0, display: 'flex', background: '#777', color: '#fff', font: '12px Inter, system-ui' }}>
      <div ref={host} style={{ width: 640, height: 1000, position: 'relative' }} />
      <pre data-testid="gen-log" style={{ padding: 16 }}>{log.join('\n')}</pre>
    </div>
  );
}
