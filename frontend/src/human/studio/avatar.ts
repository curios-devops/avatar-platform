// One avatar = what the baker needs (shape + proxies) and what the engine paints on top (look).
import type { Accessory, Look } from '../engine';
import type { Character } from './presets';

export const HUMAN_URL = (import.meta.env.VITE_HUMAN_URL || 'http://localhost:8010').replace(/\/$/, '');

export type Item = { id: string; label: string; thumb?: string; proxy?: string; material?: { diffuseTexture?: string } };
export type Catalog = {
  skins: Item[]; hair: Item[]; clothes: Item[]; eyebrows: Item[]; eyelashes: Item[];
  eyeColors: { id: string; material: { diffuseTexture?: string } }[];
  faceChanges: string[]; fixed: Record<string, string>;
};

export type Avatar = {
  pheno: Record<string, number>; local: Record<string, number>;
  skin: string; hair: string; hairColor: string; eyes: string; brows: string; lashes: string;
  clothes: string[]; tints: Record<string, string>; accessories: Accessory[];
  faceTexture?: string; // Twin: projected photo texture URL
};

export const fromCharacter = (c: Character): Avatar => ({
  pheno: { ...c.pheno }, local: {}, skin: c.skin, hair: c.hair, hairColor: c.hairColor, eyes: c.eyes,
  brows: 'eyebrow001', lashes: 'eyelashes01', clothes: [...c.clothes], tints: { ...(c.tints ?? {}) },
  accessories: [...(c.accessories ?? [])],
});

const find = (list: Item[] | undefined, id: string) => list?.find((i) => i.id === id);

export function bakeBody(cat: Catalog, a: Avatar) {
  const pick = (list: Item[], id: string) => find(list, id)?.proxy;
  const proxies = [cat.fixed.eyes, cat.fixed.teeth, cat.fixed.tongue, pick(cat.eyebrows, a.brows), pick(cat.eyelashes, a.lashes),
    pick(cat.hair, a.hair), ...a.clothes.map((c) => pick(cat.clothes, c))].filter(Boolean) as string[];
  return { phenotype: a.pheno, local: a.local, proxies };
}

export function lookOf(cat: Catalog, a: Avatar): Look {
  return {
    skin: find(cat.skins, a.skin)?.material?.diffuseTexture,
    eyes: cat.eyeColors.find((c) => c.id === a.eyes)?.material.diffuseTexture,
    hairColor: a.hairColor, clothesColor: '#ffffff', tints: a.tints, accessories: a.accessories,
    faceTexture: a.faceTexture,
  };
}

export async function bake(cat: Catalog, a: Avatar, signal?: AbortSignal): Promise<ArrayBuffer> {
  const res = await fetch(`${HUMAN_URL}/bake`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, signal, body: JSON.stringify(bakeBody(cat, a)),
  });
  if (!res.ok) throw new Error(`bake ${res.status}`);
  return res.arrayBuffer();
}

/** Studio cut-out URL (rendered by ?human=gen). */
export const cut = (name: string) => `${HUMAN_URL}/studio/${name}.webp`;

/** The face sliders move l-/r- pairs together. */
export function faceKeys(name: string, changes: string[]) {
  return changes.filter((c) => c === `${name}-incr` || c === name || c === `l-${name}-incr` || c === `r-${name}-incr`
    || c === `l-${name}` || c === `r-${name}` || c === `${name}-out` || c === `l-${name}-out` || c === `r-${name}-out` || c === `${name}-up`);
}
