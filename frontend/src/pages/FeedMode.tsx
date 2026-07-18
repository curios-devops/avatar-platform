/**
 * ETAPA A — A3: Cliente Feed (móvil-first, 9:16).
 *
 * MVP del plan: player básico + estados visuales + barge-in.
 *  - Video por estados: loops de clips base (idle_a/b, listen) servidos por
 *    el backend. Cuando A2 esté cableado, los chunks con lip-sync sustituyen
 *    al loop durante `hablando`.
 *  - Audio: MediaSource (audio/mpeg) — los audio_chunk del contrato se
 *    van anexando y suenan en streaming, sin esperar la frase completa.
 *  - Barge-in v0: mantener pulsado el micro interrumpe (interrupt) y graba;
 *    al soltar se envía como user_audio (STT en el orquestador). VAD wasm
 *    (silero) queda como mejora.
 */
import React, { useEffect, useRef, useState } from 'react';

type Estado = 'idle' | 'escuchando' | 'hablando' | 'pensando';

const CLIP_FOR: Record<string, string> = {
  idle: 'idle_a', pensando: 'idle_b', escuchando: 'listen', hablando: 'idle_a',
};

interface Props { serverUrl: string; avatarId?: string; onBack?: () => void }

/** Audio streaming: anexa chunks MP3 (b64) a un MediaSource en vivo. */
class MseAudio {
  private audio = new Audio();
  private ms: MediaSource | null = null;
  private sb: SourceBuffer | null = null;
  private queue: Uint8Array[] = [];
  private ended = false;

  start() {
    this.stop();
    this.ms = new MediaSource();
    this.ended = false;
    this.audio = new Audio(URL.createObjectURL(this.ms));
    this.audio.play().catch(() => {});
    this.ms.addEventListener('sourceopen', () => {
      if (!this.ms || this.sb) return;
      this.sb = this.ms.addSourceBuffer('audio/mpeg');
      this.sb.addEventListener('updateend', () => this._pump());
      this._pump();
    });
  }
  append(b64: string) {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    this.queue.push(buf);
    this._pump();
  }
  end() { this.ended = true; this._pump(); }
  stop() {
    try { this.audio.pause(); } catch {}
    this.queue = []; this.sb = null; this.ms = null;
  }
  private _pump() {
    if (!this.sb || this.sb.updating) return;
    const next = this.queue.shift();
    if (next) { try { this.sb.appendBuffer(next.buffer as ArrayBuffer); } catch {} }
    else if (this.ended && this.ms?.readyState === 'open') {
      try { this.ms.endOfStream(); } catch {}
    }
  }
}

export const FeedMode: React.FC<Props> = ({ serverUrl, avatarId = 'demo', onBack }) => {
  const [estado, setEstado] = useState<Estado>('idle');
  const [pregunta, setPregunta] = useState('');
  const [subtitulo, setSubtitulo] = useState('');
  const [texto, setTexto] = useState('');
  const [recording, setRecording] = useState(false);
  const [wsUp, setWsUp] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const mseRef = useRef(new MseAudio());
  const recRef = useRef<MediaRecorder | null>(null);
  const vidA = useRef<HTMLVideoElement>(null);
  const vidB = useRef<HTMLVideoElement>(null);
  const activeVid = useRef<'a' | 'b'>('a');
  const clipShown = useRef('');

  const clipUrl = (name: string) => `${serverUrl}/dev-storage/clips/${avatarId}/${name}.mp4`;

  // ── video por estados con crossfade entre dos <video> ──────────────────
  const showClip = (name: string) => {
    if (clipShown.current === name) return;
    clipShown.current = name;
    const cur = activeVid.current === 'a' ? vidA.current : vidB.current;
    const nxt = activeVid.current === 'a' ? vidB.current : vidA.current;
    if (!cur || !nxt) return;
    nxt.src = clipUrl(name);
    nxt.loop = true; nxt.muted = true;
    nxt.play().then(() => {
      nxt.style.opacity = '1'; cur.style.opacity = '0';
      activeVid.current = activeVid.current === 'a' ? 'b' : 'a';
    }).catch(() => {});
  };

  useEffect(() => { showClip(CLIP_FOR[estado]); }, [estado]);

  // ── WebSocket del orquestador ──────────────────────────────────────────
  useEffect(() => {
    const ws = new WebSocket(`${serverUrl.replace(/^http/, 'ws')}/api/v1/converse/ws`);
    wsRef.current = ws;
    ws.onopen = () => setWsUp(true);
    ws.onclose = () => setWsUp(false);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      console.debug('[feed:contract]', m.seq ?? m.type, m.estado ?? '', m.audio_chunk ? `audio(${m.audio_chunk.length}b64)` : '', m.texto_frase ?? '', m.fin_de_respuesta ? 'FIN' : '');
      if (m.type === 'transcript') { setPregunta(m.text); return; }
      if (m.type === 'error') { console.warn('[feed]', m.detail); return; }
      if (!('estado' in m)) return;
      if (m.audio_chunk) {
        if (m.lat_primer_chunk_ms != null) mseRef.current.start();
        mseRef.current.append(m.audio_chunk);
        setEstado('hablando');
        if (m.texto_frase) setSubtitulo(m.texto_frase);
        // TODO(A2): sustituir loop por video_chunk con lip-sync
      } else if (m.estado === 'escuchando') {
        setEstado('escuchando');
      } else if (m.estado === 'idle') {
        if (m.fin_de_respuesta) { mseRef.current.end(); setEstado('idle'); setSubtitulo(''); }
        else setEstado('pensando');
      }
    };
    return () => { ws.close(); mseRef.current.stop(); };
  }, [serverUrl]);

  const enviarTexto = () => {
    if (!texto.trim() || !wsRef.current) return;
    mseRef.current.stop();
    setPregunta(texto);
    wsRef.current.send(JSON.stringify({ type: 'user_text', text: texto }));
    setTexto('');
    setEstado('pensando');
  };

  // ── hold-to-talk + barge-in ────────────────────────────────────────────
  const micDown = async () => {
    if (!wsRef.current) return;
    // barge-in: si está hablando, corta ya
    wsRef.current.send(JSON.stringify({ type: 'interrupt' }));
    mseRef.current.stop();
    setEstado('escuchando');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      const parts: Blob[] = [];
      rec.ondataavailable = (e) => parts.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(parts, { type: 'audio/webm' });
        const b64 = btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer())));
        wsRef.current?.send(JSON.stringify({ type: 'user_audio', audio_b64: b64, mime: 'audio/webm' }));
        setEstado('pensando');
      };
      rec.start();
      recRef.current = rec;
      setRecording(true);
    } catch (e) { console.warn('mic:', e); }
  };
  const micUp = () => { recRef.current?.stop(); recRef.current = null; setRecording(false); };

  const chip = { idle: '', pensando: 'Pensando…', escuchando: 'Escuchando…', hablando: '' }[estado];

  return (
    <div style={S.wrap}>
      <div style={S.stage}>
        <video ref={vidA} style={{ ...S.video, opacity: 1 }} playsInline />
        <video ref={vidB} style={{ ...S.video, opacity: 0 }} playsInline />
        {pregunta && <div style={S.question}>{pregunta}</div>}
        {chip && <div style={S.chip}>{chip}</div>}
        {subtitulo && <div style={S.subtitle}>{subtitulo}</div>}
        {onBack && <button style={S.back} onClick={onBack}>←</button>}
        {!wsUp && <div style={S.offline}>conectando…</div>}
      </div>
      <div style={S.controls}>
        <input
          id="feed-text" name="feed-text" style={S.input}
          placeholder="Escribe… (o mantén pulsado el micro)"
          value={texto} onChange={e => setTexto(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && enviarTexto()}
        />
        <button
          style={{ ...S.mic, ...(recording ? S.micOn : {}) }}
          onPointerDown={micDown} onPointerUp={micUp} onPointerLeave={() => recording && micUp()}
        >🎤</button>
      </div>
    </div>
  );
};

const S: Record<string, React.CSSProperties> = {
  wrap: { width: '100vw', height: '100vh', background: '#000', display: 'flex',
          flexDirection: 'column', alignItems: 'center' },
  stage: { position: 'relative', height: 'calc(100vh - 76px)', aspectRatio: '9/16',
           maxWidth: '100vw', overflow: 'hidden', borderRadius: 12, background: '#111' },
  video: { position: 'absolute', inset: 0, width: '100%', height: '100%',
           objectFit: 'cover', transition: 'opacity 250ms ease' },
  question: { position: 'absolute', top: 14, left: '50%', transform: 'translateX(-50%)',
              maxWidth: '86%', background: 'rgba(0,0,0,0.55)', color: '#fff', padding: '8px 14px',
              borderRadius: 18, fontSize: 14, backdropFilter: 'blur(6px)', textAlign: 'center' },
  chip: { position: 'absolute', bottom: 64, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(0,0,0,0.5)', color: '#ddd', padding: '4px 12px', borderRadius: 12,
          fontSize: 12 },
  subtitle: { position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
              width: '90%', textAlign: 'center', color: '#fff', fontSize: 16, fontWeight: 600,
              textShadow: '0 1px 4px rgba(0,0,0,0.9)' },
  back: { position: 'absolute', top: 12, left: 12, background: 'rgba(0,0,0,0.5)', color: '#fff',
          border: 'none', borderRadius: 10, width: 34, height: 34, fontSize: 16, cursor: 'pointer' },
  offline: { position: 'absolute', top: 12, right: 12, color: '#f87171', fontSize: 12 },
  controls: { display: 'flex', gap: 10, alignItems: 'center', padding: '12px 16px',
              width: 'min(100vw, 480px)' },
  input: { flex: 1, background: '#1a1a1e', color: '#eee', border: '1px solid #333',
           borderRadius: 22, padding: '12px 18px', fontSize: 15, outline: 'none' },
  mic: { width: 52, height: 52, borderRadius: '50%', border: 'none', fontSize: 22,
         background: '#4f46e5', cursor: 'pointer' },
  micOn: { background: '#dc2626', transform: 'scale(1.15)' },
};
