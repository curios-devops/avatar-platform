// Speech for the three.js human: the same A0 orchestrator WebSocket the Feed uses
// (/api/v1/converse/ws), without avatar_id so it streams audio + visemes instead of MuseTalk video.
// Each phrase arrives as MP3 chunks with a cumulative viseme timeline relative to the phrase start.
// Streaming (default): chunks are appended to a live MediaSource as they arrive, like the Feed, and each
// phrase's visemes are anchored at the media time where its first chunk landed. Fallback (no MSE for
// audio/mpeg): a phrase is decoded once complete and queued on WebAudio, visemes on the same clock.
import { VISEME_TO_ARKIT, type Weights } from './visemes';

type Visema = { t_ms: number; id: string; peso?: number };
type Cue = { t: number; id: string; w: number };
type Phrase = { text: string; chunks: Uint8Array[]; visemes: Map<string, Visema>; start?: number; cues?: Cue[] };

export type SpeechStats = { firstAudioMs?: number; firstChunkMs?: number; firstChunkServerMs?: number; phrases: number; streaming: boolean };

const MS: typeof MediaSource | undefined = (window as any).MediaSource ?? (window as any).ManagedMediaSource;
const STREAMING = !!MS?.isTypeSupported?.('audio/mpeg');

const bytes = (b64: string) => Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));

/** ARKit weights for a sorted cue list at time `now`: the active viseme crossfading into the next one. */
function blend(cues: Cue[], now: number): Weights {
  let i = cues.length - 1;
  while (i > 0 && cues[i].t > now) i--;
  const a = cues[i];
  if (!a || a.t > now) return {};
  const b = cues[i + 1];
  const fade = 0.07;
  const k = b && b.t - now < fade ? 1 - (b.t - now) / fade : 0;
  const out: Weights = {};
  const add = (cue: Cue, w: number) => {
    for (const [name, v] of Object.entries(VISEME_TO_ARKIT[cue.id] ?? {})) out[name] = (out[name] ?? 0) + v * cue.w * w;
  };
  add(a, 1 - k);
  if (b && k > 0) add(b, k);
  return out;
}

const sortedCues = (p: Phrase, offset: number): Cue[] =>
  [...p.visemes.values()].sort((a, b) => a.t_ms - b.t_ms).map((v) => ({ t: offset + v.t_ms / 1000, id: v.id, w: v.peso ?? 1 }));

/** One response streamed into a MediaSource; phrases keep their start time on the media timeline. */
class Stream {
  readonly audio = new Audio();
  private ms = new MS!();
  private sb: SourceBuffer | null = null;
  private queue: { data: Uint8Array; phrase: Phrase }[] = [];
  private ended = false;
  private url: string;
  phrases: Phrase[] = [];

  constructor() {
    (this.audio as any).disableRemotePlayback = true; // required by ManagedMediaSource (iOS)
    this.url = URL.createObjectURL(this.ms);
    this.audio.src = this.url;
    this.ms.addEventListener('sourceopen', () => {
      this.sb = this.ms.addSourceBuffer('audio/mpeg');
      this.sb.mode = 'sequence';
      this.sb.addEventListener('updateend', () => this.pump());
      this.pump();
    });
  }

  push(phrase: Phrase, data: Uint8Array) {
    if (phrase !== this.phrases[this.phrases.length - 1]) this.phrases.push(phrase);
    this.queue.push({ data, phrase });
    this.pump();
  }

  end() { this.ended = true; this.pump(); }

  stop() {
    this.audio.pause();
    this.queue = [];
    URL.revokeObjectURL(this.url);
  }

  get bufferedEnd() {
    const b = this.sb?.buffered;
    return b?.length ? b.end(b.length - 1) : 0;
  }

  private pump() {
    if (!this.sb || this.sb.updating || this.ms.readyState !== 'open') return;
    const next = this.queue.shift();
    if (next) {
      next.phrase.start ??= this.bufferedEnd; // first chunk of the phrase: it starts where the media ends now
      try { this.sb.appendBuffer(next.data as BufferSource); } catch (err) { console.warn('[human:speech] append', err); }
    } else if (this.ended) {
      try { this.ms.endOfStream(); } catch { /* already ended */ }
    }
  }
}

export class Speech {
  readonly ctx = new AudioContext();
  private ws: WebSocket | null = null;
  private current: Phrase | null = null;
  private stream: Stream | null = null;
  private shown: Phrase | null = null;
  // WebAudio fallback
  private cues: Cue[] = [];
  private playhead = 0;
  private sources: AudioBufferSourceNode[] = [];
  private chain: Promise<void> = Promise.resolve();
  private sentAt = 0;
  stats: SpeechStats = { phrases: 0, streaming: STREAMING };
  onState: (state: 'idle' | 'thinking' | 'speaking' | 'offline', text?: string) => void = () => {};
  onStats: (s: SpeechStats) => void = () => {};

  constructor(private serverUrl: string, private voiceId?: string) {}

  connect() {
    const ws = new WebSocket(`${this.serverUrl.replace(/^http/, 'ws')}/api/v1/converse/ws`);
    this.ws = ws;
    ws.onopen = () => this.onState('idle');
    ws.onclose = () => this.onState('offline');
    ws.onmessage = (ev) => this.handle(JSON.parse(ev.data));
  }

  close() {
    this.stop();
    const ws = this.ws;
    if (!ws) return;
    // a closed instance must not report state anymore (React mounts twice in dev and shares the setter)
    ws.onclose = ws.onmessage = null;
    if (ws.readyState === WebSocket.OPEN) ws.close();
    else ws.onopen = () => ws.close();
  }

  say(text: string) {
    if (!text.trim() || this.ws?.readyState !== WebSocket.OPEN) return false;
    void this.ctx.resume();
    this.stop();
    this.stats = { phrases: 0, streaming: STREAMING };
    this.sentAt = performance.now();
    if (STREAMING) this.startStream(); // created inside the click so play() keeps the user gesture
    this.ws.send(JSON.stringify({ type: 'user_text', text, ...(this.voiceId ? { voice_id: this.voiceId } : {}) }));
    this.onState('thinking');
    return true;
  }

  stop() {
    this.ws?.readyState === WebSocket.OPEN && this.ws.send(JSON.stringify({ type: 'interrupt' }));
    this.stream?.stop();
    this.stream = null;
    this.shown = null;
    this.sources.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
    this.sources = [];
    this.cues = [];
    this.current = null;
    this.playhead = 0;
  }

  get speaking() {
    if (this.stream) return !this.stream.audio.paused && !this.stream.audio.ended;
    return this.ctx.currentTime < this.playhead;
  }

  /** ARKit weights for the mouth right now. */
  mouth(): Weights {
    if (!this.stream) {
      const now = this.ctx.currentTime;
      return this.cues.length && now < this.playhead ? blend(this.cues, now) : {};
    }
    const { audio, phrases } = this.stream;
    if (audio.paused || audio.ended) return {};
    const now = audio.currentTime;
    let p: Phrase | undefined;
    for (const q of phrases) if (q.start != null && q.start <= now) p = q;
    if (!p) return {};
    if (p !== this.shown) { this.shown = p; this.onState('speaking', p.text); }
    p.cues ??= sortedCues(p, p.start!);
    return blend(p.cues, now);
  }

  private startStream() {
    const s = new Stream();
    this.stream = s;
    s.audio.addEventListener('playing', () => {
      if (this.stats.firstAudioMs == null) {
        this.stats.firstAudioMs = Math.round(performance.now() - this.sentAt);
        this.onStats({ ...this.stats });
      }
    });
    s.audio.addEventListener('ended', () => { if (this.stream === s) this.onState('idle'); });
    s.audio.play().catch(() => { /* resumes once data arrives */ });
  }

  private handle(m: any) {
    if (m.type === 'error') { console.warn('[human:speech]', m.detail); return; }
    if (!('estado' in m)) return;
    if (m.lat_primer_chunk_ms != null) this.stats.firstChunkServerMs = m.lat_primer_chunk_ms;
    if (m.audio_chunk) {
      this.stats.firstChunkMs ??= Math.round(performance.now() - this.sentAt);
      if (this.current && this.current.text !== m.texto_frase) this.flush();
      if (!this.current) {
        this.current = { text: m.texto_frase ?? '', chunks: [], visemes: new Map() };
        this.stats.phrases++;
        this.onStats({ ...this.stats });
      }
      const data = bytes(m.audio_chunk);
      for (const v of (m.visemas ?? []) as Visema[]) this.current.visemes.set(`${v.t_ms}:${v.id}`, v);
      this.current.cues = undefined; // timeline grew: re-sort on next frame
      if (this.stream) this.stream.push(this.current, data);
      else this.current.chunks.push(data);
    } else if (m.estado === 'idle' && m.fin_de_respuesta) {
      this.flush();
      this.stream?.end();
    }
  }

  private flush() {
    const phrase = this.current;
    this.current = null;
    if (this.stream || !phrase?.chunks.length) return; // streamed phrases are already in the MediaSource
    const all = new Uint8Array(phrase.chunks.reduce((n, b) => n + b.length, 0));
    let o = 0;
    for (const b of phrase.chunks) { all.set(b, o); o += b.length; }
    // decode in order so phrases never overtake each other
    this.chain = this.chain.then(async () => {
      const buffer = await this.ctx.decodeAudioData(all.buffer);
      const start = Math.max(this.ctx.currentTime + 0.05, this.playhead);
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.ctx.destination);
      src.start(start);
      src.onended = () => { if (!this.speaking) this.onState('idle'); };
      this.sources.push(src);
      this.playhead = start + buffer.duration;
      this.cues.push(...sortedCues(phrase, start), { t: this.playhead, id: 'sil', w: 1 });
      if (this.stats.firstAudioMs == null) {
        this.stats.firstAudioMs = Math.round(performance.now() - this.sentAt + (start - this.ctx.currentTime) * 1000);
      }
      this.onStats({ ...this.stats });
      this.onState('speaking', phrase.text);
    }).catch((err) => console.warn('[human:speech] decode', err));
  }
}
