import React, { useEffect, useRef, useState } from 'react';
import { WebGPURenderer } from '../engine/webgpu_renderer';
import { SplatLoader } from '../engine/splat_loader';
import { AnimationStream } from '../engine/animation_stream';
import { Camera } from '../engine/camera';
import QUICK_LINES from '../data/quick_lines.json';

interface AvatarViewerProps {
  avatarUrl: string;
  animationId?: string;
  serverUrl: string;
  onBack?: () => void;
}

const VOICES = [
  { name: 'Rachel', id: '21m00Tcm4TlvDq8ikWAM' },
  { name: 'Domi',   id: 'AZnzlk1XvdvUeBnXmlld' },
  { name: 'Antoni', id: 'ErXwobaYiN019PkySvjV' },
  { name: 'Josh',   id: 'TxGEqnHWrfWFTfGW9XjX' },
  { name: 'Bella',  id: 'EXAVITQu4vr4xnSDxMaL' },
];

export const AvatarViewer: React.FC<AvatarViewerProps> = ({
  avatarUrl, animationId, serverUrl, onBack,
}) => {
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<WebGPURenderer | null>(null);
  const streamRef   = useRef<AnimationStream | null>(null);
  const rafRef      = useRef<number>(0);

  // Web Audio refs — set when audio plays, read inside RAF loop
  const analyserRef  = useRef<AnalyserNode | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ampDataRef   = useRef<any>(null);
  const audioCtxRef  = useRef<AudioContext | null>(null);

  const [stage, setStage]               = useState('Starting…');
  const [ready, setReady]               = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [fps, setFps]                   = useState(0);
  const [gaussianCount, setGaussianCount] = useState(0);

  // Speak panel state
  const [showSpeak, setShowSpeak]   = useState(false);
  const [speakText, setSpeakText]   = useState('');
  const [voiceId, setVoiceId]       = useState(VOICES[0].id);
  const [speakStatus, setSpeakStatus] = useState<'idle' | 'loading' | 'playing'>('idle');
  const [speakError, setSpeakError] = useState<string | null>(null);
  const [suggOffset, setSuggOffset] = useState(0);

  const suggestions = Array.from({ length: 3 }, (_, i) =>
    QUICK_LINES[(suggOffset + i) % QUICK_LINES.length]
  );
  const shuffleSuggestions = () =>
    setSuggOffset(o => (o + 3) % QUICK_LINES.length);

  // ── 3D render loop ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    let frames = 0;
    let fpsTimer = performance.now();

    const init = async () => {
      if (!canvasRef.current || cancelled) return;
      try {
        setStage('Initialising WebGPU…');
        const renderer = new WebGPURenderer(canvasRef.current);
        const ok = await renderer.initialize();
        if (!ok || cancelled) { renderer.destroy(); return; }
        rendererRef.current = renderer;

        const camera = new Camera(canvasRef.current);

        setStage('Loading avatar data…');
        const loader    = new SplatLoader();
        const gaussians = await loader.loadFromURL(avatarUrl);
        if (cancelled) { renderer.destroy(); return; }

        setStage('Uploading to GPU…');
        renderer.loadGaussians(gaussians);
        setGaussianCount(gaussians.count);

        if (animationId) {
          const stream = new AnimationStream();
          stream.connect(animationId, serverUrl);
          stream.onDeformation(u => renderer.updateDeformation(u.positions));
          streamRef.current = stream;
        }

        setReady(true);
        setStage('');

        const loop = () => {
          if (cancelled) return;

          // Feed audio amplitude into jaw shader every frame
          if (analyserRef.current && ampDataRef.current) {
            analyserRef.current.getByteFrequencyData(ampDataRef.current);
            let sum = 0;
            for (let i = 0; i < ampDataRef.current.length; i++) sum += ampDataRef.current[i];
            const amp = sum / (ampDataRef.current.length * 128.0);
            renderer.setAmplitude(amp);
          }

          renderer.updateCamera(camera.getViewMatrix(), camera.getProjectionMatrix());
          renderer.render();
          frames++;
          const now = performance.now();
          if (now - fpsTimer >= 1000) {
            setFps(frames);
            frames = 0;
            fpsTimer = now;
          }
          rafRef.current = requestAnimationFrame(loop);
        };
        rafRef.current = requestAnimationFrame(loop);

      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setStage('');
        console.error('[viewer]', err);
      }
    };

    init();
    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
      rendererRef.current?.destroy();
      rendererRef.current = null;
      streamRef.current?.disconnect();
      streamRef.current = null;
    };
  }, [avatarUrl, animationId, serverUrl]);

  // ── audio → Web Audio ─────────────────────────────────────────────────────
  const _playAudio = async (url: string) => {
    // Fetch as blob to avoid cross-origin issues with Web Audio API
    const resp = await fetch(url);
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);

    // Close any previous AudioContext
    await audioCtxRef.current?.close().catch(() => {});

    const ctx      = new AudioContext();
    const audio    = new Audio(blobUrl);
    const source   = ctx.createMediaElementSource(audio);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyser.connect(ctx.destination);

    analyserRef.current = analyser;
    ampDataRef.current  = new Uint8Array(analyser.frequencyBinCount);
    audioCtxRef.current = ctx;

    audio.onended = () => {
      setSpeakStatus('idle');
      // Decay amplitude back to 0
      analyserRef.current = null;
      rendererRef.current?.setAmplitude(0);
      URL.revokeObjectURL(blobUrl);
    };

    await ctx.resume();
    await audio.play();
    setSpeakStatus('playing');
  };

  const handleSpeak = async () => {
    if (!speakText.trim()) return;
    setSpeakStatus('loading');
    setSpeakError(null);
    try {
      const resp = await fetch(`${serverUrl}/api/v1/avatar/${animationId || 'preview'}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: speakText.trim(), voice_id: voiceId }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'TTS request failed');
      }
      const { audio_url } = await resp.json();
      await _playAudio(audio_url);
    } catch (e) {
      setSpeakError(e instanceof Error ? e.message : String(e));
      setSpeakStatus('idle');
    }
  };

  const handleDownload = () => {
    const a = document.createElement('a');
    a.href = avatarUrl;
    a.download = 'avatar.ply';
    a.click();
  };

  return (
    <div style={css.page}>
      {/* ── top bar ── */}
      <div style={css.topBar}>
        <button style={css.backBtn} onClick={onBack}>← Back</button>
        <div style={css.titleGroup}>
          <span style={{ fontSize: 20 }}>🧑‍🎤</span>
          <span style={css.title}>Your 3D Avatar</span>
        </div>
        <div style={css.badge}>
          {ready
            ? <><span style={{ color: '#4ade80' }}>●</span> {fps} fps</>
            : <span style={{ color: '#555' }}>Loading…</span>}
        </div>
      </div>

      {/* ── main canvas area ── */}
      <div style={css.main}>
        <div style={css.glowRing} />

        <div style={css.frame}>
          <canvas ref={canvasRef} width={1280} height={720} style={css.canvas} />

          {!ready && !error && (
            <div style={css.overlay}>
              <div style={css.spinner} />
              <span style={{ color: '#888', fontSize: 13, marginTop: 14 }}>{stage}</span>
            </div>
          )}

          {error && (
            <div style={css.overlay}>
              <span style={{ fontSize: 36 }}>⚠️</span>
              <p style={{ color: '#fca5a5', maxWidth: 340, textAlign: 'center', marginTop: 12, fontSize: 14, lineHeight: 1.6 }}>
                {error}
              </p>
            </div>
          )}

          {ready && (
            <>
              <div style={{ ...css.corner, top: 12, left: 12 }}>
                <span style={css.dot} />3D Gaussian Splat
              </div>
              <div style={{ ...css.corner, top: 12, right: 12, left: 'auto' }}>
                {(gaussianCount / 1000).toFixed(0)}K splats
              </div>
              {speakStatus === 'playing' && (
                <div style={css.playingBadge}>
                  <span style={{ animation: 'pulse 0.6s ease-in-out infinite' }}>🎤</span>
                  <span>Speaking…</span>
                  <WaveBar /><WaveBar delay={0.1} /><WaveBar delay={0.2} /><WaveBar delay={0.15} />
                </div>
              )}
            </>
          )}
        </div>

        {ready && (
          <p style={css.hint}>🖱 Drag to rotate &nbsp;·&nbsp; Scroll to zoom</p>
        )}

        {/* ── action buttons ── */}
        {ready && (
          <div style={css.actions}>
            <ActionButton
              emoji="🎤"
              label="Make it Talk"
              sub={speakStatus === 'playing' ? 'Speaking…' : 'ElevenLabs TTS'}
              primary
              active={showSpeak}
              loading={speakStatus === 'loading'}
              onClick={() => { setShowSpeak(s => !s); setSpeakError(null); }}
            />
            <ActionButton
              emoji="💾"
              label="Download PLY"
              sub="Raw Gaussian file"
              onClick={handleDownload}
            />
            <ActionButton
              emoji="🔄"
              label="New Avatar"
              sub="Upload another photo"
              onClick={onBack}
            />
          </div>
        )}

        {/* ── speak panel ── */}
        {ready && showSpeak && (
          <div style={css.speakPanel}>
            {/* suggestion chips */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10, flexWrap: 'wrap' as const }}>
              <span style={{ fontSize: 11, color: '#444', flexShrink: 0 }}>Try:</span>
              {suggestions.map((line, i) => (
                <button key={i} onClick={() => setSpeakText(line)} style={css.suggChip}
                  title={line}>
                  {line.length > 42 ? line.slice(0, 42) + '…' : line}
                </button>
              ))}
              <button onClick={shuffleSuggestions} style={css.shuffleBtn} title="More suggestions">🔀</button>
            </div>
            <textarea
              style={css.speakTextarea}
              placeholder="Hello! I'm your personal 3D avatar…"
              value={speakText}
              onChange={e => setSpeakText(e.target.value)}
              rows={3}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' as const }}>
              <select
                style={css.voiceSelect}
                value={voiceId}
                onChange={e => setVoiceId(e.target.value)}
              >
                {VOICES.map(v => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
              <button
                style={{
                  ...css.speakBtn,
                  opacity: (!speakText.trim() || speakStatus === 'loading') ? 0.5 : 1,
                  cursor: (!speakText.trim() || speakStatus === 'loading') ? 'not-allowed' : 'pointer',
                }}
                disabled={!speakText.trim() || speakStatus === 'loading'}
                onClick={handleSpeak}
              >
                {speakStatus === 'loading' ? '⏳ Generating…' : '▶ Speak'}
              </button>
              {speakStatus === 'playing' && (
                <span style={{ fontSize: 12, color: '#4ade80' }}>
                  🎵 Playing…
                </span>
              )}
            </div>
            {speakError && (
              <p style={{ fontSize: 12, color: '#fca5a5', marginTop: 8, marginBottom: 0 }}>
                ⚠️ {speakError}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── bottom info strip ── */}
      {ready && (
        <div style={css.infoStrip}>
          <Stat icon="✦" label="Splats"  value={gaussianCount.toLocaleString()} />
          <Stat icon="📐" label="Rig"    value="FLAME 2023" />
          <Stat icon="🎨" label="Render" value="WebGPU" />
          <Stat icon="🎤" label="Voice"  value="ElevenLabs" />
        </div>
      )}

      <style>{KEYFRAMES}</style>
    </div>
  );
};

// ── sub-components ────────────────────────────────────────────────────────────

const WaveBar: React.FC<{ delay?: number }> = ({ delay = 0 }) => (
  <div style={{
    width: 3, borderRadius: 2, background: '#a78bfa',
    animation: `wavebar 0.6s ease-in-out ${delay}s infinite alternate`,
    height: 8,
  }} />
);

const ActionButton: React.FC<{
  emoji: string; label: string; sub: string;
  primary?: boolean; disabled?: boolean; active?: boolean;
  loading?: boolean; onClick?: () => void;
}> = ({ emoji, label, sub, primary, disabled, active, loading, onClick }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    style={{
      flex: 1, padding: '14px 10px',
      background: active
        ? 'linear-gradient(135deg,rgba(124,58,237,0.5),rgba(79,70,229,0.5))'
        : primary
          ? 'linear-gradient(135deg,rgba(124,58,237,0.3),rgba(79,70,229,0.3))'
          : 'rgba(255,255,255,0.03)',
      border: `1px solid ${(primary || active) ? 'rgba(124,58,237,0.5)' : 'rgba(255,255,255,0.07)'}`,
      borderRadius: 12, cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.45 : 1,
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
      transition: 'all 0.2s', minWidth: 120,
      boxShadow: active ? '0 0 16px rgba(124,58,237,0.3)' : 'none',
    }}
  >
    <span style={{ fontSize: 22 }}>{loading ? '⏳' : emoji}</span>
    <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{label}</span>
    <span style={{ color: '#444', fontSize: 11 }}>{sub}</span>
  </button>
);

const Stat: React.FC<{ icon: string; label: string; value: string }> = ({ icon, label, value }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, flex: 1 }}>
    <span style={{ fontSize: 11, color: '#333' }}>{icon} {label}</span>
    <span style={{ fontSize: 13, color: '#a78bfa', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
  </div>
);

// ── styles ────────────────────────────────────────────────────────────────────
const css: Record<string, React.CSSProperties> = {
  page: {
    width: '100vw', height: '100vh',
    background: 'radial-gradient(ellipse at 50% 0%, #1a0a2e 0%, #0c0c0e 60%)',
    display: 'flex', flexDirection: 'column',
    fontFamily: "'Inter', system-ui, sans-serif",
    color: '#f0f0f0', overflow: 'hidden',
  },
  topBar: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 24px',
    borderBottom: '1px solid rgba(167,139,250,0.1)',
    background: 'rgba(0,0,0,0.3)', backdropFilter: 'blur(12px)',
    flexShrink: 0,
  },
  backBtn: {
    background: 'none', border: '1px solid #2a2a3a',
    borderRadius: 8, color: '#888', padding: '6px 16px',
    fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
  },
  titleGroup: { display: 'flex', alignItems: 'center', gap: 8 },
  title: {
    fontSize: 16, fontWeight: 700,
    background: 'linear-gradient(135deg, #a78bfa, #60a5fa)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
  },
  badge: {
    fontSize: 12, color: '#555', fontVariantNumeric: 'tabular-nums',
    minWidth: 70, textAlign: 'right',
    display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'flex-end',
  },
  main: {
    flex: 1, display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center',
    padding: '20px 24px 8px', position: 'relative', gap: 12,
    overflowY: 'auto',
  },
  glowRing: {
    position: 'absolute',
    width: 'min(80vw, 700px)', height: 'min(45vw, 400px)',
    borderRadius: '50%',
    background: 'radial-gradient(ellipse, rgba(124,58,237,0.12) 0%, transparent 70%)',
    pointerEvents: 'none', zIndex: 0,
  },
  frame: {
    position: 'relative', zIndex: 1,
    width: 'min(88vw, 860px)', aspectRatio: '16/9',
    borderRadius: 16,
    border: '1px solid rgba(167,139,250,0.25)',
    boxShadow: '0 0 0 1px rgba(167,139,250,0.08), 0 0 40px rgba(124,58,237,0.15), 0 32px 80px rgba(0,0,0,0.6)',
    overflow: 'hidden', background: '#050508',
  },
  canvas: { width: '100%', height: '100%', display: 'block' },
  overlay: {
    position: 'absolute', inset: 0,
    display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center',
    background: 'rgba(5,5,8,0.88)',
  },
  spinner: {
    width: 36, height: 36,
    border: '3px solid rgba(167,139,250,0.2)',
    borderTopColor: '#7c3aed', borderRadius: '50%',
    animation: 'spin 0.9s linear infinite',
  },
  corner: {
    position: 'absolute', bottom: 'auto',
    display: 'flex', alignItems: 'center', gap: 6,
    background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)',
    padding: '4px 10px', borderRadius: 6,
    fontSize: 11, color: '#555',
    border: '1px solid rgba(255,255,255,0.05)',
  },
  playingBadge: {
    position: 'absolute', bottom: 12, left: '50%',
    transform: 'translateX(-50%)',
    background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)',
    padding: '6px 14px', borderRadius: 20,
    display: 'flex', alignItems: 'center', gap: 6,
    fontSize: 12, color: '#a78bfa',
    border: '1px solid rgba(167,139,250,0.3)',
    boxShadow: '0 0 12px rgba(124,58,237,0.3)',
  },
  dot: {
    display: 'inline-block', width: 6, height: 6,
    borderRadius: '50%', background: '#4ade80',
    boxShadow: '0 0 6px #4ade80',
  },
  hint: { fontSize: 12, color: '#333', margin: 0, letterSpacing: '0.02em' },
  actions: { display: 'flex', gap: 10, width: 'min(88vw, 860px)', zIndex: 1 },
  speakPanel: {
    width: 'min(88vw, 860px)', zIndex: 1,
    background: 'rgba(22,22,28,0.95)',
    border: '1px solid rgba(167,139,250,0.2)',
    borderRadius: 14, padding: '18px 20px',
    backdropFilter: 'blur(16px)',
    boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
  },
  speakTextarea: {
    width: '100%', background: 'rgba(0,0,0,0.3)',
    border: '1px solid #1e1e2e', borderRadius: 9,
    color: '#f0f0f0', fontSize: 14, padding: '10px 12px',
    resize: 'vertical', outline: 'none',
    boxSizing: 'border-box', fontFamily: 'inherit',
    lineHeight: 1.5, marginBottom: 10,
  },
  voiceSelect: {
    background: 'rgba(0,0,0,0.4)', border: '1px solid #1e1e2e',
    borderRadius: 8, color: '#aaa', fontSize: 13,
    padding: '7px 12px', cursor: 'pointer',
    fontFamily: 'inherit', outline: 'none',
  },
  speakBtn: {
    padding: '8px 20px', fontSize: 13, fontWeight: 600,
    border: 'none', borderRadius: 9,
    background: 'linear-gradient(135deg,#7c3aed,#4f46e5)',
    color: '#fff', fontFamily: 'inherit',
    boxShadow: '0 2px 12px rgba(124,58,237,0.4)',
  },
  suggChip: {
    padding: '4px 10px', fontSize: 11, borderRadius: 20,
    border: '1px solid #1e1e2e',
    background: 'rgba(167,139,250,0.07)', color: '#666',
    cursor: 'pointer', fontFamily: 'inherit',
    transition: 'all 0.15s', whiteSpace: 'nowrap' as const,
    maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis',
  },
  shuffleBtn: {
    padding: '4px 8px', fontSize: 13, borderRadius: 8,
    border: '1px solid #1e1e2e', background: 'transparent',
    color: '#444', cursor: 'pointer', flexShrink: 0,
    fontFamily: 'inherit',
  },
  infoStrip: {
    display: 'flex', alignItems: 'center',
    padding: '10px 24px',
    borderTop: '1px solid rgba(255,255,255,0.04)',
    background: 'rgba(0,0,0,0.2)', flexShrink: 0,
  },
};

const KEYFRAMES = `
  @keyframes spin    { to { transform: rotate(360deg); } }
  @keyframes pulse   { 0%,100%{opacity:1} 50%{opacity:0.4} }
  @keyframes wavebar { from { height: 4px; } to { height: 16px; } }
`;
