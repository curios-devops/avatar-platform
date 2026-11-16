// Checks for the words → character parser (no test runner in this app; esbuild bundles it for Node):
//   npx esbuild src/human/studio/words.test.ts --bundle --platform=node --format=esm --define:import.meta.env={} \
//     --banner:js="globalThis.window={location:{search:''}};globalThis.document={documentElement:{}};globalThis.sessionStorage={getItem:()=>null,setItem(){}};" \
//     | node --input-type=module
import { buildAvatar, merge, parseWords, type Spec } from './words';

let failed = 0;
const eq = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : `\n     got  ${JSON.stringify(got)}\n     want ${JSON.stringify(want)}`}`);
};
const pick = (s: Spec, keys: (keyof Spec)[]) => Object.fromEntries(keys.filter((k) => s[k] !== undefined).map((k) => [k, s[k]]));

// --- reading
eq('woman around 30, long brown hair', pick(parseWords('woman around 30, long brown hair'), ['sex', 'age', 'hair', 'hairColor']),
  { sex: 'female', age: 30, hair: 'long', hairColor: 'darkbrown' });
eq('blue jacket is a jacket, not a tee', pick(parseWords('a man in a blue jacket'), ['sex', 'outfit', 'outfitColor']), { sex: 'male', outfit: 'jacket', outfitColor: 'blue' });
eq('black hair, blue jacket', pick(parseWords('black hair, blue jacket'), ['hairColor', 'outfit', 'outfitColor']), { hairColor: 'black', outfit: 'jacket', outfitColor: 'blue' });
eq('chaqueta roja y pelo negro', pick(parseWords('hombre con chaqueta roja y pelo negro'), ['sex', 'hairColor', 'outfit', 'outfitColor']),
  { sex: 'male', hairColor: 'black', outfit: 'jacket', outfitColor: 'red' });
eq('pelo castaño y camiseta verde', pick(parseWords('mujer de 28 años, pelo castaño y camiseta verde'), ['sex', 'age', 'hairColor', 'outfit', 'outfitColor']),
  { sex: 'female', age: 28, hairColor: 'darkbrown', outfit: 'tee', outfitColor: 'green' });
eq('mujer negra con pelo afro', pick(parseWords('mujer negra con pelo afro'), ['sex', 'tone', 'hair', 'hairColor']), { sex: 'female', tone: 'dark', hair: 'afro' });
eq('vestida de blanco is clothes, not skin', pick(parseWords('una mujer vestida de blanco'), ['tone', 'outfitColor']), { outfitColor: 'white' });
eq('rubia, alta, 30 años', pick(parseWords('rubia, alta, 30 años'), ['sex', 'age', 'hairColor', 'height']), { sex: 'female', age: 30, hairColor: 'blonde', height: 'tall' });
eq('mujer morena', pick(parseWords('mujer morena de ojos verdes'), ['sex', 'tone', 'hairColor', 'eyes']), { sex: 'female', tone: 'medium', hairColor: 'darkbrown', eyes: 'green' });
eq('hombre calvo con gafas', pick(parseWords('hombre calvo con gafas'), ['sex', 'hair', 'glasses']), { sex: 'male', hair: 'bald', glasses: 'glasses' });
eq('gafas de sol', parseWords('chico con gafas de sol').glasses, 'sunglasses');
eq('"son amables" is not a man', parseWords('son amables y alegres').sex, undefined);
eq('"human" is not a man', parseWords('a friendly human being').sex, undefined);
eq('a height is not an age', parseWords('mide de 1,70 y es simpática').age, undefined);
eq('in his 60s', pick(parseWords('asian man in his 60s, slim'), ['sex', 'age', 'origin', 'build']), { sex: 'male', age: 64, origin: 'asian', build: 'slim' });
eq('pelo corto', parseWords('chica con el pelo corto').hair, 'short');
eq('short messy brown hair', parseWords('a man around 40, short messy brown hair').hair, 'short');
eq('pelo largo y ondulado castaño', parseWords('mujer de pelo muy largo castaño').hair, 'long');
eq('short woman with long hair', pick(parseWords('short woman with long hair'), ['height', 'hair']), { height: 'short', hair: 'long' });
eq('ropa deportiva', parseWords('hombre joven con ropa deportiva').outfit, 'sport');
eq('traje elegante', parseWords('ejecutiva con traje gris').outfit, 'suit');
eq('elegante alone', parseWords('una señora elegante').outfit, 'suit');
eq('sudadera', pick(parseWords('chico con sudadera negra'), ['outfit', 'outfitColor']), { outfit: 'sweater', outfitColor: 'black' });
eq('red hair is hair, not clothes', pick(parseWords('woman with red hair and a white shirt'), ['hairColor', 'outfit', 'outfitColor']), { hairColor: 'red', outfit: 'shirt', outfitColor: 'white' });
eq('t-shirt', pick(parseWords('guy in a black t-shirt'), ['outfit', 'outfitColor']), { outfit: 'tee', outfitColor: 'black' });
eq('trenza', parseWords('niña con trenza').hair, 'braid');
eq('rizado', parseWords('hombre de pelo rizado').hair, 'curly');
eq('moño', parseWords('abuela con moño y canas').hair, 'bun');
eq('canas', parseWords('abuela con moño y canas').hairColor, 'grey');
eq('abuela age', parseWords('abuela con moño').age, 72);
eq('atlético', parseWords('hombre atlético').build, 'athletic');
eq('corpulento', parseWords('señor corpulento').build, 'heavy');

// --- building
const empty = buildAvatar({});
eq('nothing said: a casual outfit with no third-party print (plain blue tee)', empty.avatar.clothes[0], 'male_casualsuit04');
const fromPhotoF = buildAvatar({}, { gender: 0.1, age: 0.4 });
eq('photo of a woman, no words: female hair and clothes', [fromPhotoF.look.sex, fromPhotoF.avatar.clothes[0]], ['female', 'female_casualsuit02']);
const jacket = buildAvatar(parseWords('mujer con chaqueta azul'));
eq('woman in a blue jacket wears the jacket, dyed blue', [jacket.avatar.clothes[0], jacket.avatar.tints], ['male_casualsuit05', { male_casualsuit05: '#2f5d9e' }]);
const dark = buildAvatar(parseWords('hombre negro de 50 años'));
eq('dark skin follows tone and age', [dark.avatar.skin, dark.avatar.pheno.african], ['middleage_african_male', 0.9]);
const light = buildAvatar(parseWords('mujer de piel clara, 30 años'));
eq('light skin', light.avatar.skin, 'young_caucasian_female');
const asian = buildAvatar(parseWords('hombre asiático de 25 años con pelo rizado'));
eq('asian man: asian skin, short curls, black hair', [asian.avatar.skin, asian.avatar.hair, asian.avatar.hairColor], ['young_asian_male', 'afro01', '#141414']);
const bald = buildAvatar(parseWords('hombre calvo'));
eq('bald has no hair proxy', bald.avatar.hair, '');
const chips = buildAvatar(merge(parseWords('mujer de 30 años, pelo largo'), { hair: 'curly', hairColor: 'red', outfit: 'sweater', outfitColor: 'navy', hairColorX: undefined } as Spec));
eq('chips override words', [chips.avatar.hair, chips.avatar.hairColor, chips.avatar.clothes[0], chips.look.outfitColor], ['punkduck_alpha7_curly2', '#8a3a1c', 'male_casualsuit02', 'navy']);
eq('empty overrides keep words', merge({ hair: 'long' }, { hair: undefined }).hair, 'long');

// variety: ten different descriptions, ten different characters
const descs = ['woman around 30, long brown hair', 'hombre de 45 años con chaqueta azul', 'mujer negra con pelo afro y camiseta amarilla',
  'abuela con moño y canas', 'chico asiático de 20 años con sudadera negra', 'hombre calvo con traje', 'rubia, alta, ropa deportiva',
  'pelirroja con trenza y camisa blanca', 'señor corpulento de 60 años con peto', 'mujer morena de pelo rizado con vestido rojo'];
const keys = descs.map((d) => JSON.stringify(buildAvatar(parseWords(d)).avatar));
eq('ten descriptions give ten characters', new Set(keys).size, descs.length);

// every id the builder can produce is in the live catalog (skipped when the human server is not running)
try {
  const cat = await (await fetch('http://localhost:8010/catalog')).json() as Record<string, { id: string }[]>;
  const has = (list: string, id: string) => !id || cat[list].some((i) => i.id === id);
  const all = [...descs, 'hombre', 'mujer', 'mujer asiática', 'hombre indio', 'mujer india', 'latino de 70 años', 'mujer de piel oscura', 'bob', 'coleta', 'ondulado', 'pelo largo hombre']
    .flatMap((d) => [buildAvatar(parseWords(d)).avatar, buildAvatar(merge(parseWords(d), { sex: 'male' })).avatar, buildAvatar(merge(parseWords(d), { sex: 'female' })).avatar]);
  const missing = all.flatMap((a) => [
    ...(has('skins', a.skin) ? [] : [`skin ${a.skin}`]), ...(has('hair', a.hair) ? [] : [`hair ${a.hair}`]),
    ...a.clothes.filter((c) => !has('clothes', c)).map((c) => `garment ${c}`)]);
  eq('every resolved id exists in the catalog', [...new Set(missing)], []);
} catch {
  console.log('skip catalog check (human server not reachable)');
}

console.log(failed ? `\n${failed} failed` : '\nall passed');
if (failed) throw new Error(`${failed} failed`);
