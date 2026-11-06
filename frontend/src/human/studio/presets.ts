// Studio data: the character line-up, garment categories, backgrounds and prompt examples.
// Every character is built from the same parametric body (Anny) and CC0 assets, so a card in the
// carousel is exactly what loads when it is picked. Names are invented.
import type { Accessory } from '../engine';
import { LANG } from '../../i18n';

export const es = LANG === 'es';
export const L = (en: string, sp: string) => (es ? sp : en);

export type Pheno = Record<string, number>;
export type Character = {
  id: string; name: string; age: number; note: string;
  pheno: Pheno; skin: string; hair: string; hairColor: string; eyes: string;
  clothes: string[]; tints?: Record<string, string>; accessories?: Accessory[];
};

const mix = (african: number, asian: number, caucasian: number) => ({ african, asian, caucasian });

// A spread meant to let most people find someone close to them: ages 8 to 75, every build and height,
// and African, East Asian, South Asian, Latin American and European looks.
export const CHARACTERS: Character[] = [
  { id: 'lucia', name: 'Lucía', age: 26, note: L('Latina, Bogotá', 'Latina, Bogotá'),
    pheno: { gender: 0, age: 0.45, muscle: 0.45, weight: 0.45, height: 0.45, proportions: 0.6, ...mix(0.2, 0.25, 0.55) },
    skin: 'toigo_light_skin_female_bronze', hair: 'elvs_hazel_hair', hairColor: '#3a2618', eyes: 'brown',
    clothes: ['female_casualsuit02', 'shoes02'], accessories: [{ id: 'hoops' }] },
  { id: 'kwame', name: 'Kwame', age: 31, note: L('Tall, athletic', 'Alto, atlético'),
    pheno: { gender: 1, age: 0.5, muscle: 0.82, weight: 0.45, height: 0.82, proportions: 0.6, ...mix(0.95, 0, 0.05) },
    skin: 'young_african_male', hair: 'short01', hairColor: '#1a1a1a', eyes: 'brown',
    clothes: ['male_casualsuit03', 'shoes03'] },
  { id: 'mei', name: 'Mei', age: 24, note: L('Petite, Shanghai', 'Menuda, Shanghái'),
    pheno: { gender: 0, age: 0.42, muscle: 0.4, weight: 0.3, height: 0.3, proportions: 0.55, ...mix(0, 0.95, 0.05) },
    skin: 'young_asian_female', hair: 'elvs_short_side_do', hairColor: '#141414', eyes: 'brown',
    clothes: ['female_casualsuit01', 'shoes01'] },
  { id: 'erik', name: 'Erik', age: 35, note: L('Nordic, very tall', 'Nórdico, muy alto'),
    pheno: { gender: 1, age: 0.55, muscle: 0.6, weight: 0.5, height: 0.95, proportions: 0.6, ...mix(0, 0, 1) },
    skin: 'young_caucasian_male', hair: 'short02', hairColor: '#d8b278', eyes: 'lightblue',
    clothes: ['male_casualsuit01', 'shoes04'] },
  { id: 'rosa', name: 'Rosa', age: 75, note: L('Grandmother, Seville', 'Abuela, Sevilla'),
    pheno: { gender: 0, age: 0.95, muscle: 0.3, weight: 0.62, height: 0.3, proportions: 0.45, ...mix(0.05, 0.1, 0.85) },
    skin: 'old_caucasian_female', hair: 'elvs_50s_updo', hairColor: '#b8b8b4', eyes: 'brownlight',
    clothes: ['female_elegantsuit01', 'shoes01'], tints: { female_elegantsuit01: '#4a3b5c' }, accessories: [{ id: 'glasses' }] },
  { id: 'hiroshi', name: 'Hiroshi', age: 70, note: L('Retired, Osaka', 'Jubilado, Osaka'),
    pheno: { gender: 1, age: 0.9, muscle: 0.35, weight: 0.4, height: 0.38, proportions: 0.5, ...mix(0, 1, 0) },
    skin: 'old_asian_male', hair: 'short03', hairColor: '#a9aaa8', eyes: 'brown',
    clothes: ['male_elegantsuit01', 'shoes04'] },
  { id: 'amara', name: 'Amara', age: 40, note: L('Curvy, Lagos', 'Con curvas, Lagos'),
    pheno: { gender: 0, age: 0.6, muscle: 0.4, weight: 0.88, height: 0.5, proportions: 0.5, ...mix(0.9, 0, 0.1) },
    skin: 'middleage_african_female', hair: 'punkduck_alpha7_curly2', hairColor: '#161210', eyes: 'brown',
    clothes: ['female_casualsuit02', 'shoes02'], tints: { female_casualsuit02: '#c2462e' }, accessories: [{ id: 'hoops' }] },
  { id: 'diego', name: 'Diego', age: 8, note: L('Kid, Lima', 'Niño, Lima'),
    pheno: { gender: 1, age: 0.12, muscle: 0.45, weight: 0.5, height: 0.5, proportions: 0.5, ...mix(0.15, 0.35, 0.5) },
    skin: 'young_caucasian_male2', hair: 'short04', hairColor: '#2b1d14', eyes: 'brown',
    clothes: ['male_casualsuit02', 'shoes06'] },
  { id: 'priya', name: 'Priya', age: 32, note: L('Engineer, Pune', 'Ingeniera, Pune'),
    pheno: { gender: 0, age: 0.52, muscle: 0.45, weight: 0.45, height: 0.45, proportions: 0.55, ...mix(0.15, 0.25, 0.6) },
    skin: 'cutoff3d_indian_female_skin', hair: 'braid01', hairColor: '#141010', eyes: 'brown',
    clothes: ['female_elegantsuit01', 'shoes01'], tints: { female_elegantsuit01: '#1f5f5b' }, accessories: [{ id: 'studs' }] },
  { id: 'tom', name: 'Tom', age: 52, note: L('Big build, Manchester', 'Corpulento, Mánchester'),
    pheno: { gender: 1, age: 0.72, muscle: 0.35, weight: 0.96, height: 0.32, proportions: 0.45, ...mix(0, 0, 1) },
    skin: 'middleage_caucasian_male', hair: 'short01', hairColor: '#5a3a22', eyes: 'grey',
    clothes: ['male_worksuit01', 'shoes02'] },
  { id: 'sofia', name: 'Sofía', age: 15, note: L('Teen, Mexico City', 'Adolescente, CDMX'),
    pheno: { gender: 0, age: 0.3, muscle: 0.45, weight: 0.4, height: 0.45, proportions: 0.55, ...mix(0.1, 0.4, 0.5) },
    skin: 'young_caucasian_female2', hair: 'elvs_keylth_hair', hairColor: '#4a2e1c', eyes: 'brown',
    clothes: ['female_sportsuit01', 'shoes06'] },
  { id: 'jamal', name: 'Jamal', age: 20, note: L('Slim, Atlanta', 'Delgado, Atlanta'),
    pheno: { gender: 1, age: 0.38, muscle: 0.5, weight: 0.22, height: 0.62, proportions: 0.6, ...mix(0.9, 0, 0.1) },
    skin: 'young_african_male', hair: 'cortu_short_messy_hair', hairColor: '#141414', eyes: 'brown',
    clothes: ['male_casualsuit05', 'shoes06'], accessories: [{ id: 'sunglasses' }] },
  { id: 'ana', name: 'Ana', age: 46, note: L('Petite, Santiago', 'Bajita, Santiago'),
    pheno: { gender: 0, age: 0.66, muscle: 0.4, weight: 0.58, height: 0.12, proportions: 0.45, ...mix(0.1, 0.3, 0.6) },
    skin: 'middleage_caucasian_female', hair: 'toigo_inverted_bob', hairColor: '#2b1d14', eyes: 'brown',
    clothes: ['female_casualsuit01', 'shoes02'], tints: { female_casualsuit01: '#d9ccb4' } },
  { id: 'liam', name: 'Liam', age: 22, note: L('Average build, Dublin', 'Complexión media, Dublín'),
    pheno: { gender: 1, age: 0.4, muscle: 0.5, weight: 0.5, height: 0.55, proportions: 0.5, ...mix(0, 0, 1) },
    skin: 'young_caucasian_male2', hair: 'short03', hairColor: '#a5743f', eyes: 'bluegreen',
    clothes: ['male_casualsuit04', 'shoes04'] },
];

export type Category = 'outfits' | 'shoes' | 'hats' | 'accessories' | 'hair';
export const categoryOf = (id: string): Category =>
  /^shoes/.test(id) ? 'shoes' : /fedora|hat/.test(id) ? 'hats' : 'outfits';

export const FIT_TABS: [Category, string][] = [
  ['outfits', L('Outfits', 'Conjuntos')], ['shoes', L('Shoes', 'Zapatos')], ['hats', L('Hats', 'Sombreros')],
  ['accessories', L('Accessories', 'Accesorios')], ['hair', L('Hair', 'Pelo')],
];

// Readable names for the MakeHuman proxies (their own labels are file names).
export const GARMENT_NAMES: Record<string, string> = {
  female_casualsuit01: L('Tee and jeans', 'Camiseta y vaqueros'), female_casualsuit02: L('Tee and denim shorts', 'Camiseta y short vaquero'),
  female_elegantsuit01: L('Striped blouse and skirt', 'Blusa de rayas y falda'), female_sportsuit01: L('Crop top and leggings', 'Top corto y mallas'),
  male_casualsuit01: L('Denim shirt and jeans', 'Camisa vaquera'), male_casualsuit02: L('Long-sleeve tee and jeans', 'Manga larga y vaqueros'),
  male_casualsuit03: L('Striped shirt and jeans', 'Camisa de rayas'), male_casualsuit04: L('Logo tee and jeans', 'Camiseta con logo'),
  male_casualsuit05: L('Field jacket', 'Chaqueta militar'), male_casualsuit06: L('White tee and jeans', 'Camiseta blanca'),
  male_elegantsuit01: L('Suit and tie', 'Traje y corbata'), male_worksuit01: L('Denim overalls', 'Peto vaquero'),
  shoes01: L('Brown leather shoes', 'Zapatos de piel'), shoes02: L('Worn sneakers', 'Zapatillas gastadas'),
  shoes03: L('Black loafers', 'Mocasines negros'), shoes04: L('Black dress shoes', 'Zapatos de vestir'),
  shoes05: L('White sneakers', 'Zapatillas blancas'), shoes06: L('Blue sneakers', 'Zapatillas azules'),
  fedora01: 'Fedora', fedora_cocked: L('Tilted fedora', 'Fedora ladeado'),
};

export const ACCESSORIES: { id: Accessory['id']; name: string; colors: string[] }[] = [
  { id: 'hoops', name: L('Hoop earrings', 'Aros'), colors: ['#d9b56a', '#d8d8d8', '#b87a5a'] },
  { id: 'studs', name: L('Stud earrings', 'Pendientes'), colors: ['#f2f2f2', '#d9b56a', '#1c1c1e'] },
  { id: 'glasses', name: L('Glasses', 'Gafas'), colors: ['#2a2320', '#8a5a3c', '#c9c9c9'] },
  { id: 'sunglasses', name: L('Sunglasses', 'Gafas de sol'), colors: ['#1a1a1a', '#5a3d22', '#d9b56a'] },
];

// Colour dots offered for every garment: neutrals first, then a few tones that read well on screen.
export const TINTS: [string, string][] = [
  [L('Original', 'Original'), '#ffffff'], [L('Bone', 'Hueso'), '#ece6da'], [L('Sand', 'Arena'), '#d9ccb4'],
  [L('Sage', 'Salvia'), '#a9b59c'], [L('Sky', 'Cielo'), '#b9cde0'], [L('Navy', 'Marino'), '#2a3550'],
  [L('Brick', 'Teja'), '#b5523b'], [L('Charcoal', 'Carbón'), '#3a3b3f'],
];
// Strand-textured hair cards (hair02/hair03, CC-BY) read far more like real hair than the system
// shells, so they lead the list; the rest follow in catalog order.
const HAIR_FIRST = [
  'elvs_hazel_hair', 'elvs_daisy_hair', 'elvs_adrienne_hair', 'elvs_ashley_may_hair', 'elvs_lady_hippy_hair',
  'elvs_keylth_hair', 'elvs_katherine_hair', 'elvs_short_daisy_hair', 'elvs_island_princess_hair', 'elvs_that_80s_babe_hair',
  'punkduck_alpha7_curly2', 'punkduck_alpha7_curly', 'punkduck_alpha7_long2', 'elvs_inverted_curly_bob', 'elvs_witchy_lil_bob',
  'elvs_short_side_do', 'elvs_wavy_bob', 'elvs_50s_updo', 'elvs_braid_bun', 'elvs_lara_hair', 'elvs_micky_afro',
  'elvs_braided_rows', 'elvs_grump_hair', 'elvs_maxwell_hair',
];
export const sortHair = <T extends { id: string }>(hair: T[]) => {
  const rank = (id: string) => { const i = HAIR_FIRST.indexOf(id); return i < 0 ? HAIR_FIRST.length : i; };
  return [...hair].sort((a, b) => rank(a.id) - rank(b.id));
};

export const HAIR_TINTS: [string, string][] = [
  [L('Natural', 'Natural'), '#ffffff'], [L('Black', 'Negro'), '#141414'], [L('Dark brown', 'Castaño oscuro'), '#3a2618'],
  [L('Brown', 'Castaño'), '#6b4428'], [L('Blonde', 'Rubio'), '#d8b278'], [L('Copper', 'Cobrizo'), '#9a4a26'],
  [L('Grey', 'Gris'), '#b8b8b4'], [L('Pastel pink', 'Rosa pastel'), '#e8b4c0'],
];

export type Backdrop = { id: string; name: string; word: string };
export const BACKDROPS: Backdrop[] = [
  { id: 'atelier', name: L('Atelier', 'Atelier'), word: 'FIT' },
  { id: 'showroom', name: L('Showroom', 'Showroom'), word: 'LOOK' },
  { id: 'dusk', name: L('Dusk', 'Atardecer'), word: 'GLOW' },
  { id: 'night', name: L('Night', 'Noche'), word: 'NIGHT' },
  { id: 'gallery', name: L('Gallery', 'Galería'), word: 'MUSE' },
];

export const PROMPTS = {
  fitting: es
    ? ['Ponle aros dorados', 'Cambia la ropa a blanco', 'Ropa deportiva y zapatillas', 'Gafas de sol', 'Algo elegante para una cena']
    : ['Add gold hoop earrings', 'Make the outfit white', 'Sportswear and sneakers', 'Sunglasses', 'Something smart for dinner'],
  character: es
    ? ['Más alta y atlética', 'Que tenga unos 60 años', 'Pelo largo y castaño', 'Ojos verdes', 'Que sonría']
    : ['Taller and athletic', 'Make them about 60', 'Long brown hair', 'Green eyes', 'Make them smile'],
};

export const FACE_GROUPS: { name: string; keys: [string, string][] }[] = [
  { name: L('Head', 'Cabeza'), keys: [['head-scale-vert', L('Length', 'Largo')], ['head-scale-horiz', L('Width', 'Ancho')], ['head-fat', L('Fullness', 'Volumen')]] },
  { name: L('Eyes', 'Ojos'), keys: [['eye-scale', L('Size', 'Tamaño')], ['eye-trans-up', L('Height', 'Altura')], ['eye-epicanthus-out', L('Fold', 'Pliegue')]] },
  { name: L('Nose', 'Nariz'), keys: [['nose-scale-horiz', L('Width', 'Ancho')], ['nose-scale-vert', L('Length', 'Largo')], ['nose-hump', L('Bridge', 'Caballete')]] },
  { name: L('Mouth', 'Boca'), keys: [['mouth-scale-horiz', L('Width', 'Ancho')], ['mouth-upperlip-volume', L('Upper lip', 'Labio superior')], ['mouth-lowerlip-volume', L('Lower lip', 'Labio inferior')]] },
  { name: L('Jaw', 'Mandíbula'), keys: [['chin-prominent', L('Chin', 'Mentón')], ['chin-width', L('Jaw width', 'Ancho')], ['cheek-bones', L('Cheekbones', 'Pómulos')]] },
];
