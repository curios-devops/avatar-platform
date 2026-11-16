// Words to a 3D character for MEYA's Create flow (?human=embed). Deterministic, no model: the text is read into a
// small semantic spec (sex, age, build, skin tone, hair, eyes, outfit and colours), MEYA's chips can override any of
// it, and the spec is resolved against the studio's catalog (the same CC0 presets, hair, skins and garments).
// Colour words go to the nearest thing they describe: "chaqueta azul y pelo negro", "black hair, blue jacket".
import { fromCharacter, type Avatar } from './avatar';
import { CHARACTERS, type Character } from './presets';

export type Sex = 'female' | 'male';
export type Tone = 'light' | 'medium' | 'dark';
export type Build = 'slim' | 'average' | 'athletic' | 'heavy';
export type HairStyle = 'long' | 'short' | 'bob' | 'wavy' | 'curly' | 'afro' | 'braid' | 'ponytail' | 'bun' | 'bald';
export type HairColor = 'black' | 'darkbrown' | 'brown' | 'blonde' | 'red' | 'grey';
export type Outfit = 'tee' | 'shirt' | 'jacket' | 'sweater' | 'sport' | 'suit' | 'dress' | 'shorts' | 'overalls';
export type Cloth = 'original' | 'black' | 'white' | 'grey' | 'navy' | 'blue' | 'red' | 'green' | 'yellow' | 'pink' | 'brown' | 'beige' | 'orange' | 'purple';
type Origin = 'african' | 'asian' | 'indian' | 'latin';

/** What a description asks for. Everything is optional: what is missing comes from the closest preset. */
export type Spec = {
  sex?: Sex; age?: number; origin?: Origin; tone?: Tone; build?: Build; height?: 'tall' | 'short';
  hair?: HairStyle; hairColor?: HairColor; eyes?: string; outfit?: Outfit; outfitColor?: Cloth;
  glasses?: 'glasses' | 'sunglasses'; earrings?: boolean;
};

export const HAIR_HEX: Record<HairColor, string> = {
  black: '#141414', darkbrown: '#3a2618', brown: '#6b4428', blonde: '#d8b278', red: '#8a3a1c', grey: '#b8b8b4',
};
export const CLOTH_HEX: Record<Exclude<Cloth, 'original'>, string> = {
  black: '#1c1c1c', white: '#f2f2ee', grey: '#6e6e6e', navy: '#24406e', blue: '#2f5d9e', red: '#b8322a', green: '#3f5a3a',
  yellow: '#d0a43a', pink: '#d58aa0', brown: '#7a5232', beige: '#d9ccb4', orange: '#d0702a', purple: '#4a3b5c',
};

/** Hairstyles in the catalog for each word, by sex (any style fits any head; only the default look differs). */
const HAIR: Record<HairStyle, { female: string; male: string }> = {
  long: { female: 'elvs_hazel_hair', male: 'o4saken_long01' },
  short: { female: 'elvs_short_side_do', male: 'short02' },
  bob: { female: 'toigo_inverted_bob', male: 'toigo_inverted_bob' },
  wavy: { female: 'elvs_daisy_hair', male: 'short03' },
  curly: { female: 'punkduck_alpha7_curly2', male: 'afro01' }, // o4saken_curly01 renders as a long blonde wig
  afro: { female: 'afro01', male: 'afro01' },
  braid: { female: 'braid01', male: 'braid01' },
  ponytail: { female: 'ponytail01', male: 'ponytail01' },
  bun: { female: 'rehmanpolanski_hair_bun_brown', male: 'rehmanpolanski_hair_bun_brown' },
  bald: { female: '', male: '' },
};

/** Garments per outfit word. MakeHuman garments fit any body, so a woman can wear the field jacket. */
const OUTFIT: Record<Outfit, { female: string; male: string }> = {
  tee: { female: 'female_casualsuit01', male: 'male_casualsuit04' },
  shirt: { female: 'male_casualsuit01', male: 'male_casualsuit01' },
  jacket: { female: 'male_casualsuit05', male: 'male_casualsuit05' },
  sweater: { female: 'male_casualsuit02', male: 'male_casualsuit02' },
  sport: { female: 'female_sportsuit01', male: 'male_casualsuit02' },
  suit: { female: 'female_elegantsuit01', male: 'male_elegantsuit01' },
  dress: { female: 'female_elegantsuit01', male: 'female_elegantsuit01' },
  shorts: { female: 'female_casualsuit02', male: 'female_casualsuit02' },
  overalls: { female: 'male_worksuit01', male: 'male_worksuit01' },
};
const DEFAULT_OUTFIT = { female: 'female_casualsuit02', male: 'male_casualsuit04' };

// ---------------------------------------------------------------------------------------------------- reading

/** Whole-word match that also works for accented words (\b does not): `w('alt[oa]')` matches "alta", not "salta". */
const w = (src: string) => new RegExp(`(?<![\\p{L}\\d])(?:${src})(?![\\p{L}])`, 'iu');
/** Word-start match for stems: `stem('castañ')` matches "castaño", "castaña". */
const stem = (src: string) => new RegExp(`(?<![\\p{L}\\d])(?:${src})`, 'iu');

const FEMALE = w('mujer(?:es)?|chica|señora|señorita|abuela|niña|madre|mamá|hija|woman|women|girl|female|lady|she|her|ella|mother|mom|daughter|actriz|abuelita|wife|esposa|novia|girlfriend');
const MALE = w('hombre|chico|señor|abuelo|niño|padre|papá|hijo|man|men|boy|male|guy|he|his|él|father|dad|caballero|abuelito|husband|esposo|novio|boyfriend');
// Spanish adjectives carry the sex in their ending: "rubia, alta" is a woman, "moreno, delgado" a man.
const ADJ_F = w('(?:rubi|moren|alt|baj|delgad|pelirroj|canos|atlétic|guap)a|bajita|flaca|gordita');
const ADJ_M = w('(?:rubi|moren|alt|baj|delgad|pelirroj|canos|atlétic|guap)o|bajito|flaco|gordito');

type Kind = 'hair' | 'eyes' | 'skin' | 'person' | 'clothes' | 'bottom' | Outfit;
const NOUNS: [RegExp, Kind][] = [
  [stem('pelo|cabell|melena|hair|peinad'), 'hair'],
  [w('ojos?|eyes?'), 'eyes'],
  [w('piel|skin|tez|skinned'), 'skin'],
  [w('mujer(?:es)?|hombre|chic[oa]|señor[a]?|persona|person|man|woman|guy|girl|boy|lady'), 'person'],
  [stem('camiset|polera|playera|remera|tee\\b|tshirt'), 'tee'],
  [stem('camisa|blus|shirt'), 'shirt'],
  [stem('chaquet|cazador|chamarr|campera|abrig|jacket|coat|parka|anorak|bomber|cortavient'), 'jacket'],
  [stem('jersey|su[eé]ter|sweater|sudader|hoodie|poler[oó]n|buzo|cardigan|pullover|chompa'), 'sweater'],
  [stem('traje|terno|blazer|suit|tuxedo|esmoquin|smoking'), 'suit'],
  [stem('ch[aá]ndal|legging|mallas|tracksuit|sportswear|deportiv'), 'sport'],
  [stem('vestid|dress|falda|skirt'), 'dress'],
  [stem('shorts|bermuda'), 'shorts'],
  [stem('peto|overol|overall|dungaree|mono de trabajo'), 'overalls'],
  [stem('pantal|jeans|vaquer|tejan|trousers|pants|denim'), 'bottom'],
  [stem('ropa|outfit|clothes|clothing|vestimenta|atuendo|look'), 'clothes'],
];

type Hue = { cloth?: Cloth; hair?: HairColor; tone?: Tone; eyes?: string; only?: 'hair' };
const COLORS: [RegExp, Hue][] = [
  [stem('rubi|blond|platin'), { hair: 'blonde', only: 'hair' }],
  [stem('pelirroj|ginger|cobriz|copper|redhead|auburn'), { hair: 'red', only: 'hair' }],
  [stem('castañ|brunette'), { hair: 'darkbrown', eyes: 'brown', only: 'hair' }],
  [stem('can[oa]s|canas'), { hair: 'grey', only: 'hair' }],
  [stem('moren'), { hair: 'darkbrown', tone: 'medium' }],
  [w('azul marino|marino|navy'), { cloth: 'navy' }],
  [stem('negr|black'), { cloth: 'black', hair: 'black', tone: 'dark' }],
  [stem('blanc|white'), { cloth: 'white', hair: 'grey', tone: 'light' }],
  [stem('gris|gr[ae]y'), { cloth: 'grey', hair: 'grey', eyes: 'grey' }],
  [stem('azul|blue|celeste'), { cloth: 'blue', eyes: 'blue' }],
  [w('roj[oa]s?|red|granate|burdeos|maroon|burgundy|vino'), { cloth: 'red', hair: 'red' }],
  [stem('verde|green|oliva|olive|caqui|khaki'), { cloth: 'green', eyes: 'green' }],
  [stem('amarill|yellow|mostaza|mustard'), { cloth: 'yellow' }],
  [w('ros[ao]s?|rosad[oa]s?|pink|fucsia'), { cloth: 'pink' }],
  [stem('marr[oó]n|caf[eé]|brown|camel|chocolate'), { cloth: 'brown', hair: 'darkbrown', eyes: 'brown' }],
  [stem('miel|hazel|avellana'), { eyes: 'brownlight' }],
  [stem('beige|crema|cream|arena|sand|hueso|ivory'), { cloth: 'beige' }],
  [stem('naranja|orange'), { cloth: 'orange' }],
  [stem('morad|purple|violet|lila'), { cloth: 'purple' }],
  [stem('clar[oa]|pale|fair|light'), { tone: 'light' }],
  [stem('oscur|dark'), { tone: 'dark', hair: 'black' }],
  [stem('trigueñ|aceitunad|tan\\b|tanned|canela'), { tone: 'medium' }],
];
const SEPARATOR = /^(?:[,.;:!?]|y|e|and|con|with|pero|but|que|who|which)$/;

/** Each colour word goes to the nearest noun it can describe (a clause break counts as two words). */
function colours(t: string, spanish: boolean) {
  const tokens = t.replace(/t[- ]?shirt/g, 'tshirt').match(/[\p{L}\d]+|[,.;:!?]/gu) ?? [];
  const nouns = tokens.map((tok) => NOUNS.find(([re]) => re.test(tok))?.[1]);
  const out: { kind: Kind; hue: Hue }[] = [];
  tokens.forEach((tok, i) => {
    const hue = COLORS.find(([re]) => re.test(tok))?.[1];
    if (!hue) return;
    if (hue.cloth && /^(?:de|in)$/.test(tokens[i - 1] ?? '') && !nouns[i + 1]) { out.push({ kind: 'clothes', hue }); return; }
    let best: { kind: Kind; d: number; after: boolean } | null = null;
    for (let j = 0; j < tokens.length; j++) {
      const kind = nouns[j];
      if (!kind || j === i) continue;
      const [a, b] = j < i ? [j, i] : [i, j];
      let d = b - a;
      for (let k = a + 1; k < b; k++) if (SEPARATOR.test(tokens[k])) d += 2;
      if (d > 3) continue;
      const after = j > i;
      // ties: Spanish puts the colour after the noun ("pelo negro"), English before ("black hair")
      if (!best || d < best.d || (d === best.d && after !== spanish)) best = { kind, d, after };
    }
    if (best) out.push({ kind: best.kind, hue });
    else if (hue.only) out.push({ kind: 'hair', hue });
  });
  return out;
}

const firstIndex = (t: string, re: RegExp) => t.search(re);

export function parseWords(text: string): Spec {
  const t = ` ${text.toLowerCase()} `;
  const s: Spec = {};
  const spanish = (t.match(w('el|la|los|las|con|de|y|una?|pelo|años|que|ropa')) ?? []).length > 0
    && firstIndex(t, w('the|with|and|hair|years|wearing')) < 0;

  // sex: the first explicit word wins; otherwise a Spanish adjective's ending
  const f = firstIndex(t, FEMALE), m = firstIndex(t, MALE);
  if (f >= 0 || m >= 0) s.sex = f >= 0 && (m < 0 || f < m) ? 'female' : 'male';
  else if (ADJ_F.test(t) !== ADJ_M.test(t)) s.sex = ADJ_F.test(t) ? 'female' : 'male';

  // age: "34 años", "30 years old", "around 30", "in her 30s", "treintañera"
  const num = t.match(/(\d{1,2})\s*(?:años|año|years?|yrs|yo|y\/o|-year)/) ?? t.match(/(?:around|about|aged?|unos|aprox\w*|~|de)\s*(\d{1,2})(?!\d|[,.]\d)/);
  const decade = t.match(/(?<!\d)([2-8])0\s*'?s\b/);
  const DECADES: [RegExp, number][] = [[stem('veint'), 25], [stem('treint'), 34], [stem('cuarent'), 44], [stem('cincuent'), 54], [stem('sesent'), 64], [stem('setent'), 73], [stem('ochent'), 83]];
  if (num && Number(num[1]) >= 6) s.age = Number(num[1]);
  else if (decade) s.age = Number(decade[1]) * 10 + 4;
  else s.age = DECADES.find(([re]) => re.test(t))?.[1]
    ?? (stem('niñ|kid|child|infantil').test(t) ? 9 : stem('adolesc|teen').test(t) ? 15
      : stem('abuel|ancian|elderly|jubilad|senior|tercera edad').test(t) || w('old|viej[oa]|mayor|grandmother|grandfather|grandma|grandpa').test(t) ? 72
        : w('joven|young|veinteañer[oa]').test(t) ? 24 : w('maduro|madura|middle-aged|mediana edad').test(t) ? 50 : undefined);
  if (s.age === undefined) delete s.age;

  const origin: Origin | undefined = stem('afric|afro|nigeri|kenia|ghan|etíop|ethiop|senegal').test(t) ? 'african'
    : stem('asi[aá]tic|japon|chin[oa]|chinese|corean|korean|asian|vietnam|filipin|tailand|thai').test(t) ? 'asian'
      : w('indi[oa]|india|hindú|indian|south asian|pakistan\\w*|bangladesh\\w*').test(t) ? 'indian'
        : stem('latin|mexic|colombi|peru|perú|argentin|chilen|venezol|bolivi|ecuator|hispan').test(t) ? 'latin' : undefined;
  if (origin) s.origin = origin;

  // build and height
  if (stem('atlétic|athletic|muscul|músculos|fuerte|strong|fornid|fit\\b|deportista').test(t)) s.build = 'athletic';
  else if (stem('corpulent|robust|gordit|gord[oa]|rellenit|heavy|chubby|curvy|curvas|grand[eo]te|big build|plus size|fat\\b').test(t)) s.build = 'heavy';
  else if (stem('delgad|flac|slim|thin|skinny|esbelt|lean\\b').test(t)) s.build = 'slim';
  else if (stem('complexión media|average build|normal build').test(t)) s.build = 'average';
  if (w('alt[oa]|tall|altísim[oa]').test(t)) s.height = 'tall';
  else if (w('baj[oa]|bajit[oa]|petite|menud[oa]').test(t) || /(?<![\p{L}])short(?!\s+(?:\p{L}+\s+){0,2}hair)(?=\s+(?:woman|man|guy|girl|person|and|,))/u.test(t)) s.height = 'short';

  // hair style
  const HAIRWORDS: [RegExp, HairStyle][] = [
    [stem('calv|bald|rapad|shaved|sin pelo|pelad[oa]\\b'), 'bald'],
    [stem('afro\\b|afro '), 'afro'],
    [stem('trenza|braid'), 'braid'],
    [stem('coleta|ponytail|cola de caballo'), 'ponytail'],
    [stem('moño|bun\\b|recogid|updo|chongo'), 'bun'],
    [stem('rizad|rizos|crespo|curly|curls|rulos|enrulad'), 'curly'],
    [stem('ondulad|wavy|waves|ondas'), 'wavy'],
    [stem('bob\\b|melena corta|media melena|carré|carre\\b'), 'bob'],
    [/(?:pelo|cabello)\s+(?:\p{L}+\s+){0,2}(?:largo|larga)|(?<![\p{L}])largo|long\s+(?:\p{L}+\s+){0,2}hair|melena(?! corta)|long-haired/u, 'long'],
    [/(?:pelo|cabello)\s+(?:\p{L}+\s+){0,2}corto|short\s+(?:\p{L}+\s+){0,2}hair|short-haired|pelo al rape|(?<![\p{L}])corto/u, 'short'],
  ];
  const hair = HAIRWORDS.find(([re]) => re.test(t))?.[1];
  if (hair) s.hair = hair;

  // colours, routed to hair, eyes, skin or clothes
  let outfitNoun: Outfit | undefined;
  const noun = (k: Kind): k is Outfit => !['hair', 'eyes', 'skin', 'person', 'clothes', 'bottom'].includes(k);
  for (const tok of t.replace(/t[- ]?shirt/g, 'tshirt').match(/[\p{L}\d]+/gu) ?? []) {
    const k = NOUNS.find(([re]) => re.test(tok))?.[1];
    if (k && noun(k)) { outfitNoun = k; break; }
  }
  for (const { kind, hue } of colours(t, spanish)) {
    if (kind === 'hair' && hue.hair && !s.hairColor) s.hairColor = hue.hair;
    else if (kind === 'eyes' && hue.eyes && !s.eyes) s.eyes = hue.eyes;
    else if (kind === 'skin' && hue.tone && !s.tone) s.tone = hue.tone;
    else if (kind === 'person') {
      if (hue.only === 'hair' || (hue.hair && hue.tone === 'medium')) s.hairColor ??= hue.hair;
      if (hue.tone && !hue.only) s.tone ??= hue.tone;
    } else if ((noun(kind) || kind === 'clothes') && hue.cloth && !s.outfitColor) s.outfitColor = hue.cloth;
  }

  // outfit: the first garment named, else a style word
  if (outfitNoun) s.outfit = outfitNoun;
  else if (stem('elegant|formal|ejecutiv|business|oficina|office').test(t)) s.outfit = 'suit';
  else if (stem('deport|sporty|gym|sport\\b|running|fitness').test(t)) s.outfit = 'sport';
  else if (w('trabajo de campo|obrer[oa]|workwear|construcción|construction').test(t)) s.outfit = 'overalls';

  if (w('gafas de sol|lentes de sol|anteojos de sol|sunglasses|shades').test(t)) s.glasses = 'sunglasses';
  else if (stem('gafas|lentes|anteojos|glasses|spectacles').test(t)) s.glasses = 'glasses';
  if (stem('aros|pendientes|aretes|earring|zarcillos').test(t)) s.earrings = true;
  return s;
}

// ---------------------------------------------------------------------------------------------------- building

const ageBucket = (age: number) => (age < 38 ? 'young' : age < 60 ? 'middleage' : 'old');
const MIX: Record<Origin | Tone, [number, number, number]> = {
  african: [0.9, 0, 0.1], dark: [0.9, 0, 0.1], asian: [0, 0.95, 0.05], indian: [0.15, 0.25, 0.6],
  latin: [0.15, 0.25, 0.6], medium: [0.15, 0.25, 0.6], light: [0.02, 0.05, 0.93],
};
function skinFor(sex: Sex, age: number, tone?: Tone, origin?: Origin): string | undefined {
  const b = ageBucket(age);
  if (origin === 'asian' && tone !== 'dark') return `${b}_asian_${sex}`;
  if (tone === 'dark' || (origin === 'african' && !tone)) return `${b}_african_${sex}`;
  if (tone === 'medium' || ((origin === 'latin' || origin === 'indian') && !tone)) {
    if (origin === 'indian' && sex === 'female') return 'cutoff3d_indian_female_skin';
    return `toigo_light_skin_${sex}_bronze`;
  }
  if (tone === 'light') return `${b}_caucasian_${sex}`;
  return undefined;
}

/** Hints from a photo fit (Anny phenotypes, 0..1): they fill sex and age when the words do not say. */
export type Hint = { gender?: number; age?: number };

export type Resolved = { sex: Sex; hair: HairStyle | 'preset'; hairColor?: HairColor; tone?: Tone; build?: Build; outfit: Outfit | 'casual'; outfitColor?: Cloth };

export function buildAvatar(spec: Spec, hint: Hint = {}): { avatar: Avatar; summary: string[]; look: Resolved } {
  const sexWanted: Sex | undefined = spec.sex ?? (hint.gender !== undefined ? (hint.gender >= 0.5 ? 'male' : 'female') : undefined);
  const age = spec.age ?? (hint.age !== undefined ? Math.round(hint.age * 78) : 34);
  const origin = spec.origin ?? (spec.tone === 'dark' ? 'african' : undefined);
  const score = (c: Character) => {
    const g: Sex = c.pheno.gender >= 0.5 ? 'male' : 'female';
    let v = sexWanted && g === sexWanted ? 6 : 0;
    v -= Math.abs(c.age - age) / 6;
    const note = `${c.note} ${c.skin}`.toLowerCase();
    if (origin === 'african' && /african|lagos|atlanta/.test(note)) v += 4;
    if (origin === 'asian' && /asian|shanghai|osaka/.test(note)) v += 4;
    if (origin === 'indian' && /indian|pune/.test(note)) v += 4;
    if (origin === 'latin' && /latin|bogot|lima|cdmx|mexico/.test(note)) v += 4;
    if (spec.tone === 'light' && /caucasian/.test(note)) v += 2;
    return v;
  };
  const base = [...CHARACTERS].sort((a, b) => score(b) - score(a))[0];
  const a = fromCharacter(base);
  const sex: Sex = sexWanted ?? (a.pheno.gender >= 0.5 ? 'male' : 'female');
  if (spec.sex) a.pheno.gender = sex === 'male' ? 1 : 0;
  a.pheno.age = Math.min(0.98, Math.max(0.1, age / 78));

  // skin: the preset's, unless a tone or origin was asked for
  const skin = skinFor(sex, age, spec.tone, spec.origin);
  if (skin) a.skin = skin;
  const mix = spec.tone ? MIX[spec.tone] : spec.origin ? MIX[spec.origin] : null;
  if (mix) Object.assign(a.pheno, { african: mix[0], asian: mix[1], caucasian: mix[2] });

  if (spec.build === 'slim') Object.assign(a.pheno, { weight: 0.25, muscle: 0.45 });
  if (spec.build === 'average') Object.assign(a.pheno, { weight: 0.5, muscle: 0.5 });
  if (spec.build === 'athletic') Object.assign(a.pheno, { weight: 0.45, muscle: 0.85 });
  if (spec.build === 'heavy') Object.assign(a.pheno, { weight: 0.88, muscle: 0.4 });
  if (spec.height) a.pheno.height = spec.height === 'tall' ? 0.85 : 0.25;

  // hair: the asked style, else the preset's own when it suits the sex, else a plain default
  const hairStyle: HairStyle | 'preset' = spec.hair ?? ((base.pheno.gender >= 0.5 ? 'male' : 'female') === sex ? 'preset' : sex === 'male' ? 'short' : 'long');
  a.hair = hairStyle === 'preset' ? base.hair : HAIR[hairStyle][sex];
  if (spec.hairColor) a.hairColor = HAIR_HEX[spec.hairColor];
  else if (age >= 62 && hairStyle !== 'preset') a.hairColor = HAIR_HEX.grey;
  else if (spec.tone === 'dark' || (spec.origin && spec.origin !== 'latin')) a.hairColor = HAIR_HEX.black; // not a borrowed preset colour
  if (spec.eyes) a.eyes = spec.eyes;

  // clothes: the asked outfit (a white tee is the plain white one), its colour, and the preset's shoes
  const outfit = spec.outfit === 'tee' && spec.outfitColor === 'white' && sex === 'male' ? 'male_casualsuit06'
    : spec.outfit ? OUTFIT[spec.outfit][sex] : DEFAULT_OUTFIT[sex];
  a.clothes = [outfit, a.clothes.find((c) => c.startsWith('shoes')) ?? 'shoes02'];
  const tint = spec.outfitColor && spec.outfitColor !== 'original' && outfit !== 'male_casualsuit06' ? CLOTH_HEX[spec.outfitColor] : undefined;
  a.tints = tint ? { [outfit]: tint } : {};

  a.accessories = [
    ...(spec.glasses ? [{ id: spec.glasses }] : []),
    ...(spec.earrings ? [{ id: 'hoops' as const }] : []),
  ];
  return {
    avatar: a,
    summary: [base.name, sex, String(age), a.skin, a.hair || 'bald', outfit, ...(tint ? [tint] : [])],
    look: { sex, hair: hairStyle, hairColor: spec.hairColor, tone: spec.tone, build: spec.build, outfit: spec.outfit ?? 'casual', outfitColor: spec.outfitColor },
  };
}

/** Drops undefined/empty overrides so they do not erase what the words said. */
export function merge(spec: Spec, over: Partial<Spec> | undefined): Spec {
  const out: Spec = { ...spec };
  for (const [k, v] of Object.entries(over ?? {})) if (v !== undefined && v !== null && v !== '') (out as Record<string, unknown>)[k] = v;
  return out;
}
