// Speech for the three.js human: the same A0 orchestrator WebSocket the Feed uses
// (/api/v1/converse/ws), without avatar_id so it streams audio + visemes instead of MuseTalk video.
// Each phrase arrives as MP3 chunks with a cumulative viseme timeline relative to the phrase start;
// a phrase is decoded once complete and queued on WebAudio, and its visemes go on the same clock.
import { VISEME_TO_ARKIT, type Weights } from './visemes';

type Visema = { t_ms: number; id: string; peso?: number };
type Cue = { t: number; id: string; w: number };
type Phrase = { text: string; chunks: string[]; visemes: Map<string, Visema> };

export type SpeechStats = { firstAudioMs?: number; firstChunkServerMs?: number; phrases: number };

export class Speech {
  readonly ctx = new AudioContext();
  private ws: WebSocket | null = null;
  private current: Phrase | null = null;
  private cues: Cue[] = [];
  private playhead = 0;
  private sources: AudioBufferSourceNode[] = [];
  private sentAt = 0;
  private chain: Promise<void> = Promise.resolve();
  stats: SpeechStats = { phrases: 0 };
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
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.close();
    else if (this.ws) this.ws.onopen = () => this.ws?.close();
  }

  say(text: string) {
    if (!text.trim() || this.ws?.readyState !== WebSocket.OPEN) return false;
    void this.ctx.resume();
    this.stop();
    this.stats = { phrases: 0 };
    this.sentAt = performance.now();
    this.ws.send(JSON.stringify({ type: 'user_text', text, ...(this.voiceId ? { voice_id: this.voiceId } : {}) }));
    this.onState('thinking');
    return true;
  }

  stop() {
    this.ws?.readyState === WebSocket.OPEN && this.ws.send(JSON.stringify({ type: 'interrupt' }));
    this.sources.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
    this.sources = [];
    this.cues = [];
    this.current = null;
    this.playhead = 0;
  }

  get speaking() {
    return this.ctx.currentTime < this.playhead;
  }

  /** ARKit weights for the mouth right now: the active viseme crossfading into the next one. */
  mouth(): Weights {
    const now = this.ctx.currentTime;
    if (!this.cues.length || now >= this.playhead) return {};
    let i = this.cues.length - 1;
    while (i > 0 && this.cues[i].t > now) i--;
    const a = this.cues[i];
    if (a.t > now) return {};
    const b = this.cues[i + 1];
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

  private handle(m: any) {
    if (m.type === 'error') { console.warn('[human:speech]', m.detail); return; }
    if (!('estado' in m)) return;
    if (m.lat_primer_chunk_ms != null) this.stats.firstChunkServerMs = m.lat_primer_chunk_ms;
    if (m.audio_chunk) {
      if (this.current && this.current.text !== m.texto_frase) this.flush();
      if (!this.current) this.current = { text: m.texto_frase ?? '', chunks: [], visemes: new Map() };
      this.current.chunks.push(m.audio_chunk);
      for (const v of (m.visemas ?? []) as Visema[]) this.current.visemes.set(`${v.t_ms}:${v.id}`, v);
    } else if (m.estado === 'idle' && m.fin_de_respuesta) {
      this.flush();
    }
  }

  private flush() {
    const phrase = this.current;
    this.current = null;
    if (!phrase?.chunks.length) return;
    const bytes = phrase.chunks.map((c) => Uint8Array.from(atob(c), (ch) => ch.charCodeAt(0)));
    const all = new Uint8Array(bytes.reduce((n, b) => n + b.length, 0));
    let o = 0;
    for (const b of bytes) { all.set(b, o); o += b.length; }
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
      const cues = [...phrase.visemes.values()].sort((a, b) => a.t_ms - b.t_ms)
        .map((v) => ({ t: start + v.t_ms / 1000, id: v.id, w: v.peso ?? 1 }));
      this.cues.push(...cues, { t: this.playhead, id: 'sil', w: 1 });
      if (this.stats.firstAudioMs == null) {
        this.stats.firstAudioMs = Math.round(performance.now() - this.sentAt + (start - this.ctx.currentTime) * 1000);
      }
      this.stats.phrases++;
      this.onStats({ ...this.stats });
      this.onState('speaking', phrase.text);
    }).catch((err) => console.warn('[human:speech] decode', err));
  }
}
