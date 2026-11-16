// Method C: visemes with timestamps from the text.
// Input: ElevenLabs character alignment ({characters, character_start_times_seconds, character_end_times_seconds}),
// which `/text-to-speech/{voice}/stream/with-timestamps` returns next to every audio chunk.
// Output: cues [{t, id}] (t in seconds, a cue holds until the next one) and a sampler that turns cues into weights.
//
// Spanish is rule-based and close to phonemic, because Spanish spelling is: v = b (lips closed, not F), h is silent,
// u is silent in que/qui/gue/gui, c/z before e/i is S (Latin American; `distincion: true` gives TH for Spain),
// n before p/b/v/m closes the lips, r/rr is a tongue-tip tap or trill with no lip rounding (DD, not the English RR),
// ll and consonant y are palatal (I). English is a rough grapheme approximation (digraphs, silent final e, magic e).

const LETTER = /[\p{L}']/u;

function esWord(w, opts) {
  const V = { a: 'aa', á: 'aa', e: 'E', é: 'E', i: 'I', í: 'I', o: 'O', ó: 'O', u: 'U', ú: 'U', ü: 'U' };
  const front = (c) => c !== undefined && 'eéiíy'.includes(c);
  const out = [];
  for (let i = 0; i < w.length; i++) {
    const c = w[i], p = w[i - 1], n = w[i + 1];
    let ids;
    if (V[c]) ids = c === 'u' && (p === 'q' || (p === 'g' && front(n))) ? [] : [V[c]];
    else switch (c) {
      case 'h': ids = []; break; // silent, and the second letter of ch
      case 'c': ids = n === 'h' ? ['CH'] : front(n) ? [opts.distincion ? 'TH' : 'SS'] : ['kk']; break;
      case 'z': ids = [opts.distincion ? 'TH' : 'SS']; break;
      case 'q': case 'k': case 'g': case 'j': ids = ['kk']; break;
      case 'x': ids = i === 0 ? ['SS'] : ['kk', 'SS']; break;
      case 'l': ids = n === 'l' ? ['I'] : p === 'l' ? [] : ['DD']; break;
      case 'y': ids = ['I']; break;
      case 'ñ': ids = ['nn']; break;
      case 'n': ids = n && 'pbvm'.includes(n) ? ['PP'] : n === 'f' ? ['FF'] : ['nn']; break;
      case 'm': case 'p': case 'b': case 'v': ids = ['PP']; break;
      case 'w': ids = ['U']; break;
      case 'f': ids = ['FF']; break;
      case 'd': case 't': ids = ['DD']; break;
      case 's': ids = ['SS']; break;
      case 'r': ids = p === 'r' ? [] : ['DD']; break;
      default: ids = [];
    }
    out.push(ids);
  }
  return out;
}

function enWord(w) {
  const out = w.split('').map(() => []);
  const vowel = (c) => c !== undefined && 'aeiouy'.includes(c);
  const magicE = (i) => !vowel(w[i + 1]) && w[i + 1] !== undefined && w[i + 2] === 'e' && i + 3 === w.length;
  for (let i = 0; i < w.length;) {
    const c = w[i], two = w.slice(i, i + 2), three = w.slice(i, i + 3);
    const set = (len, ...ids) => { out[i] = ids; i += len; };
    if (c === 'i' && (w === 'i' || w === 'hi' || w.startsWith("i'"))) { set(1, 'aa', 'I'); continue; } // the pronoun I, hi
    if (c === 'y' && i === w.length - 1 && w.length === 2 && !vowel(w[0])) { set(1, 'aa', 'I'); continue; } // my, by
    if (three === 'tch') { set(3, 'CH'); continue; }
    if (three === 'igh') { set(3, 'aa', 'I'); continue; }
    if (two === 'th') { set(2, 'TH'); continue; }
    if (two === 'sh' || two === 'ch') { set(2, 'CH'); continue; }
    if (two === 'ph') { set(2, 'FF'); continue; }
    if (two === 'wh') { set(2, 'U'); continue; }
    if (two === 'ck') { set(2, 'kk'); continue; }
    if (two === 'ng') { set(2, 'nn'); continue; }
    if (two === 'qu') { set(2, 'kk', 'U'); continue; }
    if (two === 'gh') { set(2, ...(i === 0 ? ['kk'] : [])); continue; }
    if (['ee', 'ea', 'ie'].includes(two)) { set(2, 'I'); continue; }
    if (two === 'oo' || (two === 'ou' && w === 'you')) { set(2, 'U'); continue; }
    if (['ou', 'ow', 'oa', 'au', 'aw'].includes(two)) { set(2, 'O'); continue; }
    if (['ai', 'ay', 'ei', 'ey'].includes(two)) { set(2, 'E'); continue; }
    if (['oi', 'oy'].includes(two)) { set(2, 'O', 'I'); continue; }
    if (['er', 'ir', 'ur'].includes(two) && !vowel(w[i + 2])) { set(2, 'RR'); continue; }
    let ids;
    switch (c) {
      case 'a': ids = magicE(i) ? ['E'] : ['aa']; break;
      case 'e': ids = i === w.length - 1 && w.length > 2 ? [] : ['E']; break;
      case 'i': ids = magicE(i) ? ['aa', 'I'] : ['I']; break;
      case 'o': ids = ['O']; break;
      case 'u': ids = !vowel(w[i + 1]) && w[i + 1] !== undefined && !vowel(w[i + 2]) ? ['aa'] : ['U']; break;
      case 'y': ids = ['I']; break;
      case 'w': ids = ['U']; break;
      case 'r': ids = ['RR']; break;
      case 'l': case 'd': case 't': ids = ['DD']; break;
      case 'm': case 'b': case 'p': ids = ['PP']; break;
      case 'f': case 'v': ids = ['FF']; break;
      case 's': case 'z': ids = ['SS']; break;
      case 'c': ids = vowel(w[i + 1]) && 'eiy'.includes(w[i + 1]) ? ['SS'] : ['kk']; break;
      case 'g': case 'k': case 'q': ids = ['kk']; break;
      case 'x': ids = ['kk', 'SS']; break;
      case 'j': ids = ['CH']; break;
      case 'n': ids = ['nn']; break;
      default: ids = []; // h, apostrophe
    }
    set(1, ...ids);
  }
  return out;
}

/**
 * Alignment -> cues. A pause (space or punctuation lasting >= pauseS, or a gap between letters) becomes sil;
 * a silent letter's time goes to the sound before it. Consecutive equal visemes merge.
 */
export function cuesFromAlignment(alignment, lang = 'es', opts = {}) {
  const chars = alignment.characters, st = alignment.character_start_times_seconds, en = alignment.character_end_times_seconds;
  const pauseS = opts.pauseS ?? 0.1;
  const segs = [];
  let i = 0;
  while (i < chars.length) {
    if (!LETTER.test(chars[i])) {
      let j = i;
      while (j < chars.length && !LETTER.test(chars[j])) j++;
      const s = st[i], e = en[j - 1];
      if (e - s >= pauseS || i === 0) segs.push({ id: 'sil', s, e });
      i = j;
      continue;
    }
    let j = i;
    while (j < chars.length && LETTER.test(chars[j])) j++;
    const word = chars.slice(i, j).join('').toLowerCase();
    const per = lang.startsWith('es') ? esWord(word, opts) : enWord(word);
    for (let k = 0; k < per.length; k++) {
      const s = st[i + k], e = en[i + k], ids = per[k];
      if (!ids.length) { if (segs.length) segs[segs.length - 1].e = e; continue; }
      const d = (e - s) / ids.length;
      ids.forEach((id, n) => segs.push({ id, s: s + n * d, e: s + (n + 1) * d }));
    }
    i = j;
  }
  const cues = [];
  for (const g of segs) {
    if (cues.length && cues[cues.length - 1].id === g.id) continue;
    cues.push({ t: +g.s.toFixed(4), id: g.id });
  }
  if (chars.length && cues[cues.length - 1]?.id !== 'sil') cues.push({ t: +en[en.length - 1].toFixed(4), id: 'sil' });
  return cues;
}

/**
 * The text-only fallback when the TTS gives no timestamps: letters spread evenly over the voiced span
 * [t0, t1] (found from the audio energy), pauses weighted by punctuation. Same output shape as the real alignment.
 */
export function estimateAlignment(text, t0, t1) {
  const chars = [...text];
  const w = chars.map((c) => (LETTER.test(c) ? 1 : /[.,!?;:¡¿]/.test(c) ? 2.5 : c === ' ' ? 0.6 : 0));
  const total = w.reduce((a, b) => a + b, 0) || 1;
  const starts = [], ends = [];
  let t = t0;
  for (const x of w) { starts.push(t); t += (x / total) * (t1 - t0); ends.push(t); }
  return { characters: chars, character_start_times_seconds: starts, character_end_times_seconds: ends };
}

/**
 * Weights at time t from sorted cues: the active viseme cross-fading into the next one over `xfade` seconds
 * (shortened to half the active cue so a 40 ms P still closes the lips). Cues before their time are never used,
 * so the sampler also works while cues are still arriving (live mode).
 */
export function sampleCues(cues, t, xfade = 0.07) {
  if (!cues.length || t < cues[0].t) return { sil: 1 };
  let lo = 0, hi = cues.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (cues[m].t <= t) lo = m; else hi = m - 1; }
  const a = cues[lo], b = cues[lo + 1];
  if (!b) return { [a.id]: 1 };
  const x = Math.min(xfade, (b.t - a.t) * 0.5);
  const k = b.t - t < x ? 1 - (b.t - t) / x : 0;
  if (k <= 0) return { [a.id]: 1 };
  return a.id === b.id ? { [a.id]: 1 } : { [a.id]: 1 - k, [b.id]: k };
}
