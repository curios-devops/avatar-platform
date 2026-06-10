import React, { useState, useRef, useCallback } from 'react';
import { MultiViewOrbit } from '../components/MultiViewOrbit';

interface UploadProps {
  serverUrl: string;
  onAvatarCreated: (jobId: string, gaussiansUrl: string) => void;
}

// ── constants ──────────────────────────────────────────────────────────────────
const STEP_LABELS: Record<string, string> = {
  downloading: 'Getting ready…',
  ingest:      'Checking your photo…',
  preprocess:  'Polishing the image…',
  multiview:   'Generating multiple views…',
  flame_fit:   'Mapping your face…',
  reconstruct: 'Sculpting your 3D avatar…',
  rig:         'Rigging the skeleton…',
  package:     'Packing the bundle…',
  publish:     'Almost there…',
  generating:  'Imagining your character…',
};

const PIPELINE_STEPS = [
  { key: 'downloading', icon: '⬇️', label: 'Download' },
  { key: 'ingest',      icon: '🔍', label: 'Check' },
  { key: 'preprocess',  icon: '✨', label: 'Polish' },
  { key: 'multiview',   icon: '🔄', label: 'Multi-view' },
  { key: 'flame_fit',   icon: '🗺️', label: 'Map face' },
  { key: 'reconstruct', icon: '🧊', label: '3D sculpt' },
  { key: 'rig',         icon: '🦴', label: 'Rig' },
  { key: 'package',     icon: '📦', label: 'Pack' },
  { key: 'publish',     icon: '🚀', label: 'Publish' },
];

const CHARACTER_PRESETS = [
  { label: 'Talking Monkey',  emoji: '🐒' },
  { label: 'Friendly Robot',  emoji: '🤖' },
  { label: 'Cute Dragon',     emoji: '🐉' },
  { label: 'Anime Hero',      emoji: '🌸' },
  { label: 'Space Explorer',  emoji: '🚀' },
  { label: 'Wizard',          emoji: '🧙' },
];

const STYLES = [
  { name: 'Cartoon',   emoji: '🎨' },
  { name: 'Realistic', emoji: '📷' },
  { name: 'Anime',     emoji: '⛩️' },
  { name: '3D Render', emoji: '💎' },
];

function friendlyError(raw: string): string {
  if (raw.includes('no_face'))        return "We couldn't find a face. Try a clear front-facing photo.";
  if (raw.includes('multiple_faces')) return "We see more than one person. Use a solo photo.";
  if (raw.includes('too_small'))      return "Photo too small — try a higher-quality image.";
  if (raw.includes('off_angle'))      return "Face is turned too far sideways. Look straight at the camera.";
  if (raw.includes('invalid_format')) return "Unsupported format. Please use JPEG or PNG.";
  return "Something went wrong. Please try again.";
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

// ── component ──────────────────────────────────────────────────────────────────
export const Upload: React.FC<UploadProps> = ({ serverUrl, onAvatarCreated }) => {
  type Tab = 'photo' | 'video' | 'imagine';
  const [tab, setTab] = useState<Tab>('photo');

  // photo
  const [photoFile, setPhotoFile]   = useState<File | null>(null);
  const [photoLocal, setPhotoLocal] = useState<string | null>(null);
  const [camActive, setCamActive]   = useState(false);
  const camStreamRef = useRef<MediaStream | null>(null);
  const camVideoRef  = useRef<HTMLVideoElement>(null);
  const camCanvasRef = useRef<HTMLCanvasElement>(null);

  // voice
  const [audioLocal, setAudioLocal]   = useState<string | null>(null);
  const [recording, setRecording]     = useState(false);
  const [recSecs, setRecSecs]         = useState(0);
  const voiceRecRef  = useRef<MediaRecorder | null>(null);
  const voiceChunks  = useRef<Blob[]>([]);
  const recTimerRef  = useRef<number>(0);

  // video
  const [videoFile, setVideoFile]       = useState<File | null>(null);
  const [videoLocal, setVideoLocal]     = useState<string | null>(null);
  const [vidCamActive, setVidCamActive] = useState(false);
  const [recordingVid, setRecordingVid] = useState(false);
  const [vidRecSecs, setVidRecSecs]     = useState(0);
  const [vidPrompt, setVidPrompt]       = useState('');
  const vidCamStreamRef = useRef<MediaStream | null>(null);
  const vidCamRef       = useRef<HTMLVideoElement>(null);
  const vidRecRef       = useRef<MediaRecorder | null>(null);
  const vidChunks       = useRef<Blob[]>([]);
  const vidTimerRef     = useRef<number>(0);

  // imagine
  const [preset, setPreset]       = useState<string | null>(null);
  const [customDesc, setCustomDesc] = useState('');
  const [style, setStyle]         = useState('Cartoon');

  // pipeline
  const [status, setStatus]     = useState<'idle' | 'building' | 'ready' | 'failed'>('idle');
  const [progress, setProgress] = useState(0);
  const [currentStage, setCurrentStage] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [gaussiansUrl, setGaussiansUrl] = useState<string | null>(null);
  const [resultJobId, setResultJobId]   = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [multiviewImages, setMultiviewImages] = useState<Record<string, string> | null>(null);

  // ── camera ───────────────────────────────────────────────────────────────────
  const startPhotoCamera = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
      camStreamRef.current = s;
      if (camVideoRef.current) { camVideoRef.current.srcObject = s; camVideoRef.current.play(); }
      setCamActive(true);
    } catch { alert('Camera not available.'); }
  };

  const stopPhotoCamera = useCallback(() => {
    camStreamRef.current?.getTracks().forEach(t => t.stop());
    camStreamRef.current = null;
    setCamActive(false);
  }, []);

  const capturePhoto = () => {
    const v = camVideoRef.current!;
    const c = camCanvasRef.current!;
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext('2d')!.drawImage(v, 0, 0);
    c.toBlob(blob => {
      if (!blob) return;
      setPhotoFile(new File([blob], 'photo.jpg', { type: 'image/jpeg' }));
      setPhotoLocal(URL.createObjectURL(blob));
      stopPhotoCamera();
    }, 'image/jpeg', 0.95);
  };

  // ── voice ─────────────────────────────────────────────────────────────────────
  const startVoice = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceChunks.current = [];
      const rec = new MediaRecorder(s);
      rec.ondataavailable = e => voiceChunks.current.push(e.data);
      rec.onstop = () => {
        const blob = new Blob(voiceChunks.current, { type: 'audio/webm' });
        setAudioLocal(URL.createObjectURL(blob));
        s.getTracks().forEach(t => t.stop());
        clearInterval(recTimerRef.current);
      };
      voiceRecRef.current = rec;
      rec.start();
      setRecording(true); setRecSecs(0);
      recTimerRef.current = window.setInterval(() => setRecSecs(x => x + 1), 1000);
    } catch { alert('Microphone not available.'); }
  };

  const stopVoice = useCallback(() => {
    if (voiceRecRef.current?.state === 'recording') voiceRecRef.current.stop();
    clearInterval(recTimerRef.current);
    setRecording(false);
  }, []);

  // ── video camera ──────────────────────────────────────────────────────────────
  const startVideoCamera = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: true });
      vidCamStreamRef.current = s;
      if (vidCamRef.current) { vidCamRef.current.srcObject = s; vidCamRef.current.play(); }
      setVidCamActive(true);
    } catch { alert('Camera or microphone not available.'); }
  };

  const stopVideoCamera = useCallback(() => {
    vidCamStreamRef.current?.getTracks().forEach(t => t.stop());
    vidCamStreamRef.current = null;
    setVidCamActive(false); setRecordingVid(false);
    clearInterval(vidTimerRef.current);
  }, []);

  const startVideoRec = () => {
    if (!vidCamStreamRef.current) return;
    vidChunks.current = [];
    const rec = new MediaRecorder(vidCamStreamRef.current);
    rec.ondataavailable = e => vidChunks.current.push(e.data);
    rec.onstop = () => {
      const blob = new Blob(vidChunks.current, { type: 'video/webm' });
      setVideoFile(new File([blob], 'recording.webm', { type: 'video/webm' }));
      setVideoLocal(URL.createObjectURL(blob));
      stopVideoCamera();
    };
    vidRecRef.current = rec; rec.start();
    setRecordingVid(true); setVidRecSecs(0);
    vidTimerRef.current = window.setInterval(() => setVidRecSecs(x => x + 1), 1000);
  };

  const stopVideoRec = () => {
    vidRecRef.current?.stop();
    setRecordingVid(false);
    clearInterval(vidTimerRef.current);
  };

  // ── pipeline ──────────────────────────────────────────────────────────────────
  const build = async () => {
    setStatus('building'); setError(null); setProgress(3); setCurrentStage('downloading');

    try {
      if (tab === 'imagine') {
        const description = preset ?? customDesc;
        const resp = await fetch(`${serverUrl}/api/v1/avatar/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ description, style }),
        });
        if (!resp.ok) throw new Error('Generation failed');
        const { id } = await resp.json();
        await pollJob(id);
        return;
      }

      const file = tab === 'photo' ? photoFile : videoFile;
      const form = new FormData();
      form.append('file', file!);
      const upResp = await fetch(`${serverUrl}/api/v1/avatar/upload`, { method: 'POST', body: form });
      if (!upResp.ok) throw new Error('Upload failed');
      const { video_url } = await upResp.json();

      const endpoint = tab === 'photo' ? '/api/v1/avatar/process' : '/api/v1/avatar/create';
      const body = tab === 'photo'
        ? JSON.stringify({ photo_url: video_url })
        : JSON.stringify({ video_url, mode: 'head' });

      const r = await fetch(`${serverUrl}${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
      });
      if (!r.ok) throw new Error('Could not start pipeline');
      const { id } = await r.json();
      await pollJob(id);

    } catch (e) {
      setError('Something went wrong. Please try again.');
      setStatus('failed');
    }
  };

  const pollJob = (jobId: string) => new Promise<void>((resolve, reject) => {
    const iv = setInterval(async () => {
      try {
        const r   = await fetch(`${serverUrl}/api/v1/avatar/job/${jobId}/status`);
        const job = await r.json();
        setProgress(Math.round((job.progress ?? 0) * 100));
        if (job.result?.stage) setCurrentStage(job.result.stage);
        if (job.result?.multiview_images) setMultiviewImages(job.result.multiview_images);
        if (job.status === 'done') {
          clearInterval(iv);
          setPreviewUrl(job.result?.preview ?? null);
          setGaussiansUrl(job.result?.gaussians ?? null);
          setResultJobId(jobId);
          setStatus('ready');
          resolve();
        } else if (job.status === 'failed') {
          clearInterval(iv);
          console.error('[avatar pipeline]', job.error);
          setError(friendlyError(job.error ?? ''));
          setStatus('failed');
          reject();
        }
      } catch { /* keep polling */ }
    }, 2000);
  });

  const reset = () => {
    setStatus('idle'); setProgress(0); setCurrentStage('');
    setPhotoFile(null); setPhotoLocal(null);
    setAudioLocal(null);
    setVideoFile(null); setVideoLocal(null);
    setPreviewUrl(null); setGaussiansUrl(null);
    setResultJobId(null); setError(null);
    setMultiviewImages(null);
    setPreset(null); setCustomDesc('');
  };

  const switchTab = (t: Tab) => {
    reset();
    stopPhotoCamera(); stopVoice(); stopVideoCamera();
    setTab(t);
  };

  const canBuild =
    (tab === 'photo'   && !!photoFile) ||
    (tab === 'video'   && !!videoFile) ||
    (tab === 'imagine' && !!(preset || customDesc.trim()));

  const stepIndex = PIPELINE_STEPS.findIndex(s => s.key === currentStage);

  // ── READY SCREEN ─────────────────────────────────────────────────────────────
  if (status === 'ready') {
    return (
      <div style={P.page}>
        <div style={{ ...P.card, textAlign: 'center', maxWidth: 440 }}>
          {/* confetti header */}
          <div style={{ fontSize: 48, marginBottom: 4, animation: 'pop 0.4s ease' }}>🎉</div>
          <h2 style={P.heroTitle}>Your avatar is ready!</h2>
          <p style={P.heroSub}>Here's a preview of your new 3D character</p>

          {/* circular preview */}
          {previewUrl ? (
            <div style={{
              width: 180, height: 180, borderRadius: '50%', overflow: 'hidden',
              margin: '20px auto',
              border: '3px solid rgba(167,139,250,0.6)',
              boxShadow: '0 0 0 6px rgba(167,139,250,0.1), 0 0 40px rgba(124,58,237,0.4)',
            }}>
              <img src={previewUrl} alt="preview"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            </div>
          ) : (
            <div style={{
              width: 180, height: 180, borderRadius: '50%', margin: '20px auto',
              background: 'linear-gradient(135deg,#1e1030,#0c0c1e)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '3px solid rgba(167,139,250,0.4)',
              fontSize: 56,
            }}>🧑‍🎤</div>
          )}

          <button
            style={{ ...P.primaryBtn(false), marginBottom: 10, fontSize: 16, padding: '16px' }}
            onClick={() => onAvatarCreated(resultJobId!, gaussiansUrl!)}
          >
            View in 3D →
          </button>
          <button onClick={reset} style={P.ghostBtn}>
            ← Create another avatar
          </button>
        </div>
        <style>{KEYFRAMES}</style>
      </div>
    );
  }

  // ── BUILDING SCREEN ───────────────────────────────────────────────────────────
  if (status === 'building') {
    return (
      <div style={P.page}>
        <div style={{ ...P.card, maxWidth: 480, textAlign: 'center' }}>
          <div style={{ fontSize: 40, marginBottom: 12, animation: 'spin 3s linear infinite' }}>⚙️</div>
          <h2 style={{ ...P.heroTitle, marginBottom: 6 }}>Building your avatar</h2>
          <p style={{ ...P.heroSub, marginBottom: 28 }}>
            {STEP_LABELS[currentStage] || 'Starting up…'}
          </p>

          {/* circular progress ring */}
          <div style={{ position: 'relative', width: 120, height: 120, margin: '0 auto 28px' }}>
            <svg width="120" height="120" style={{ transform: 'rotate(-90deg)' }}>
              <circle cx="60" cy="60" r="50" fill="none" stroke="#1e1e2e" strokeWidth="8" />
              <circle cx="60" cy="60" r="50" fill="none"
                stroke="url(#pg)" strokeWidth="8" strokeLinecap="round"
                strokeDasharray={`${2 * Math.PI * 50}`}
                strokeDashoffset={`${2 * Math.PI * 50 * (1 - progress / 100)}`}
                style={{ transition: 'stroke-dashoffset 0.5s ease' }}
              />
              <defs>
                <linearGradient id="pg" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#7c3aed" />
                  <stop offset="100%" stopColor="#60a5fa" />
                </linearGradient>
              </defs>
            </svg>
            <div style={{
              position: 'absolute', inset: 0,
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: '#f0f0f0' }}>{progress}%</span>
            </div>
          </div>

          {/* multi-view orbit animation — shown when views are ready */}
          {multiviewImages && Object.keys(multiviewImages).length > 1 && (
            <div style={{ margin: '0 auto 20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <p style={{ ...P.heroSub, marginBottom: 12, fontSize: 12 }}>
                Analysing multiple angles for better reconstruction
              </p>
              <MultiViewOrbit
                images={multiviewImages}
                converge={currentStage !== 'multiview'}
              />
            </div>
          )}

          {/* step pills */}
          <div style={{ display: 'flex', gap: 6, justifyContent: 'center', flexWrap: 'wrap' }}>
            {PIPELINE_STEPS.map((s, i) => {
              const done    = i < stepIndex;
              const current = i === stepIndex;
              return (
                <div key={s.key} style={{
                  padding: '4px 10px', borderRadius: 20,
                  fontSize: 11, fontWeight: 500,
                  background: done    ? 'rgba(74,222,128,0.1)'
                             : current ? 'rgba(124,58,237,0.2)'
                             :           'rgba(255,255,255,0.03)',
                  border: `1px solid ${done ? 'rgba(74,222,128,0.3)' : current ? 'rgba(124,58,237,0.5)' : '#1e1e2e'}`,
                  color: done ? '#4ade80' : current ? '#a78bfa' : '#333',
                  animation: current ? 'pulse 1.5s ease-in-out infinite' : 'none',
                  display: 'flex', gap: 4, alignItems: 'center',
                }}>
                  {done ? '✓' : s.icon} {s.label}
                </div>
              );
            })}
          </div>
        </div>
        <style>{KEYFRAMES}</style>
      </div>
    );
  }

  // ── MAIN UPLOAD SCREEN ────────────────────────────────────────────────────────
  return (
    <div style={P.page}>
      {/* hero */}
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <div style={{ fontSize: 52, marginBottom: 12, lineHeight: 1 }}>🧑‍🎤</div>
        <h1 style={P.heroTitle}>Create Your 3D Avatar</h1>
        <p style={P.heroSub}>Upload a photo, record a video, or just describe your character</p>
      </div>

      <div style={P.card}>
        {/* tabs */}
        <div style={P.tabBar}>
          {([
            { id: 'photo',   emoji: '📸', label: 'Photo'   },
            { id: 'video',   emoji: '🎥', label: 'Video'   },
            { id: 'imagine', emoji: '✨', label: 'Imagine'  },
          ] as {id: Tab; emoji: string; label: string}[]).map(t => (
            <button key={t.id} style={P.tab(tab === t.id)} onClick={() => switchTab(t.id)}>
              <span>{t.emoji}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </div>

        {/* ── PHOTO ─────────────────────────────────────────────────────────── */}
        {tab === 'photo' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <SectionLabel>Your photo</SectionLabel>

            {camActive ? (
              <div>
                <div style={{ position: 'relative', borderRadius: 12, overflow: 'hidden', background: '#000' }}>
                  <video ref={camVideoRef} autoPlay muted playsInline
                    style={{ width: '100%', display: 'block', maxHeight: 260 }} />
                  {/* face guide oval */}
                  <div style={{
                    position: 'absolute', inset: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    pointerEvents: 'none',
                  }}>
                    <div style={{
                      width: '48%', height: '70%',
                      border: '2px dashed rgba(167,139,250,0.6)',
                      borderRadius: '50%',
                    }} />
                  </div>
                </div>
                <canvas ref={camCanvasRef} style={{ display: 'none' }} />
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button style={{ ...P.primaryBtn(false), flex: 1 }} onClick={capturePhoto}>📷 Take Photo</button>
                  <button style={{ ...P.ghostBtn, padding: '10px 16px' }} onClick={stopPhotoCamera}>✕ Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <DropZone
                  hasFile={!!photoFile}
                  preview={photoLocal}
                  previewType="image"
                  icon="🖼️"
                  hint="Tap to choose a photo  or  drag & drop"
                  accept="image/*"
                  onChange={f => { setPhotoFile(f); setPhotoLocal(URL.createObjectURL(f)); }}
                />
                <button style={P.ghostBtn} onClick={startPhotoCamera}>
                  📷 Use camera instead
                </button>
              </>
            )}

            <Divider />
            <SectionLabel optional>Voice for your avatar (optional)</SectionLabel>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {!recording
                ? <button style={P.ghostBtn} onClick={startVoice}>🎙 Record voice</button>
                : <button style={{ ...P.ghostBtn, borderColor: '#ef4444', color: '#f87171', animation: 'pulse 1s infinite' }} onClick={stopVoice}>
                    ⏹ Stop — {fmt(recSecs)}
                  </button>
              }
              <label style={{ ...P.ghostBtn, cursor: 'pointer', position: 'relative' as const }}>
                📁 Upload audio
                <input type="file" accept="audio/*" style={P.hiddenInput}
                  onChange={e => { const f = e.target.files?.[0]; if (f) setAudioLocal(URL.createObjectURL(f)); }} />
              </label>
            </div>
            {audioLocal && (
              <audio controls src={audioLocal}
                style={{ width: '100%', height: 36, borderRadius: 8 }} />
            )}
          </div>
        )}

        {/* ── VIDEO ─────────────────────────────────────────────────────────── */}
        {tab === 'video' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <InfoBanner>
              Your voice is captured automatically — just speak naturally while recording 🎤
            </InfoBanner>

            {vidCamActive ? (
              <div>
                <div style={{ position: 'relative', borderRadius: 12, overflow: 'hidden', background: '#000' }}>
                  <video ref={vidCamRef} autoPlay muted playsInline
                    style={{ width: '100%', display: 'block', maxHeight: 260 }} />
                  {recordingVid && (
                    <div style={{
                      position: 'absolute', top: 10, right: 10,
                      background: 'rgba(239,68,68,0.85)', color: '#fff',
                      padding: '4px 12px', borderRadius: 20, fontSize: 13, fontWeight: 700,
                      display: 'flex', alignItems: 'center', gap: 6,
                    }}>
                      <span style={{ animation: 'pulse 1s infinite' }}>●</span> {fmt(vidRecSecs)}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  {!recordingVid
                    ? <button style={{ ...P.primaryBtn(false), flex: 1 }} onClick={startVideoRec}>● Start Recording</button>
                    : <button style={{ ...P.ghostBtn, flex: 1, borderColor: '#ef4444', color: '#f87171' }} onClick={stopVideoRec}>⏹ Stop Recording</button>
                  }
                  <button style={{ ...P.ghostBtn, padding: '10px 16px' }} onClick={stopVideoCamera}>✕</button>
                </div>
              </div>
            ) : (
              <>
                <DropZone
                  hasFile={!!videoFile}
                  preview={videoLocal}
                  previewType="video"
                  icon="🎬"
                  hint="Tap to choose a video  or  drag & drop"
                  accept="video/*"
                  onChange={f => { setVideoFile(f); setVideoLocal(URL.createObjectURL(f)); }}
                />
                <button style={P.ghostBtn} onClick={startVideoCamera}>
                  🎥 Record with camera & mic
                </button>
              </>
            )}

            <Divider />
            <SectionLabel optional>What should your avatar say? (optional)</SectionLabel>
            <textarea
              style={P.textarea}
              placeholder={`e.g. Hello! I'm so excited to meet you…`}
              value={vidPrompt}
              onChange={e => setVidPrompt(e.target.value)}
              rows={2}
            />
          </div>
        )}

        {/* ── IMAGINE ───────────────────────────────────────────────────────── */}
        {tab === 'imagine' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <SectionLabel>Pick a character</SectionLabel>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8 }}>
              {CHARACTER_PRESETS.map(p => (
                <button key={p.label}
                  style={{
                    padding: '14px 8px', borderRadius: 12, cursor: 'pointer',
                    border: `1px solid ${preset === p.label ? '#a78bfa' : '#1e1e2e'}`,
                    background: preset === p.label ? 'rgba(167,139,250,0.12)' : 'rgba(255,255,255,0.02)',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                    transition: 'all 0.15s',
                  }}
                  onClick={() => { setPreset(p.label); setCustomDesc(''); }}>
                  <span style={{ fontSize: 28 }}>{p.emoji}</span>
                  <span style={{ fontSize: 11, color: preset === p.label ? '#a78bfa' : '#555', fontWeight: 500 }}>
                    {p.label}
                  </span>
                </button>
              ))}
            </div>

            <Divider label="or describe your own" />
            <textarea
              style={P.textarea}
              placeholder="e.g. a happy golden retriever wearing sunglasses"
              value={customDesc}
              onChange={e => { setCustomDesc(e.target.value); setPreset(null); }}
              rows={2}
            />

            <SectionLabel>Style</SectionLabel>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {STYLES.map(s => (
                <button key={s.name}
                  style={{
                    padding: '7px 14px', borderRadius: 20, fontSize: 12, fontWeight: 500,
                    border: `1px solid ${style === s.name ? '#a78bfa' : '#1e1e2e'}`,
                    background: style === s.name ? 'rgba(167,139,250,0.12)' : 'transparent',
                    color: style === s.name ? '#a78bfa' : '#555', cursor: 'pointer',
                    display: 'flex', gap: 5, alignItems: 'center',
                  }}
                  onClick={() => setStyle(s.name)}>
                  {s.emoji} {s.name}
                </button>
              ))}
            </div>

            {(preset || customDesc) && (
              <div style={{
                padding: '10px 14px', background: 'rgba(167,139,250,0.06)',
                border: '1px solid rgba(167,139,250,0.2)', borderRadius: 10,
                fontSize: 13, color: '#888',
              }}>
                ✨ Generating: <strong style={{ color: '#a78bfa' }}>{preset ?? customDesc}</strong> · {style}
              </div>
            )}
          </div>
        )}

        {/* ── error ─────────────────────────────────────────────────────────── */}
        {status === 'failed' && error && (
          <div style={{
            marginTop: 16, padding: '12px 16px',
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: 10, color: '#fca5a5', fontSize: 14, lineHeight: 1.5,
          }}>
            ⚠️ {error}
          </div>
        )}

        {/* ── build button ──────────────────────────────────────────────────── */}
        <button
          style={{ ...P.primaryBtn(!canBuild), marginTop: 20, fontSize: 15, padding: '14px' }}
          disabled={!canBuild}
          onClick={build}
        >
          {tab === 'imagine' ? '✨ Generate My Avatar' : '🚀 Create My Avatar'}
        </button>
      </div>

      <style>{KEYFRAMES}</style>
    </div>
  );
};

// ── small shared components ────────────────────────────────────────────────────
const SectionLabel: React.FC<{ children: React.ReactNode; optional?: boolean }> = ({ children, optional }) => (
  <span style={{ fontSize: 13, color: '#666', display: 'block', fontWeight: 500 }}>
    {children}
    {optional && <span style={{ color: '#333', fontWeight: 400, marginLeft: 6 }}>(optional)</span>}
  </span>
);

const Divider: React.FC<{ label?: string }> = ({ label }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
    <div style={{ flex: 1, height: 1, background: '#1e1e2e' }} />
    {label && <span style={{ fontSize: 11, color: '#333', whiteSpace: 'nowrap' }}>{label}</span>}
    {label && <div style={{ flex: 1, height: 1, background: '#1e1e2e' }} />}
  </div>
);

const InfoBanner: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{
    padding: '10px 14px', background: 'rgba(96,165,250,0.06)',
    border: '1px solid rgba(96,165,250,0.15)', borderRadius: 10,
    fontSize: 13, color: '#6fa8dc', lineHeight: 1.5,
  }}>
    {children}
  </div>
);

const DropZone: React.FC<{
  hasFile: boolean; preview: string | null; previewType: 'image' | 'video';
  icon: string; hint: string; accept: string;
  onChange: (f: File) => void;
}> = ({ hasFile, preview, previewType, icon, hint, accept, onChange }) => (
  <label style={{
    display: 'block', borderRadius: 12, overflow: 'hidden',
    border: `2px dashed ${hasFile ? '#a78bfa' : '#1e1e2e'}`,
    background: hasFile ? 'rgba(167,139,250,0.05)' : 'rgba(255,255,255,0.01)',
    cursor: 'pointer', transition: 'all 0.2s', position: 'relative',
    minHeight: 120,
  }}>
    <input type="file" accept={accept} style={P.hiddenInput}
      onChange={e => { const f = e.target.files?.[0]; if (f) onChange(f); }} />
    {preview ? (
      previewType === 'image'
        ? <img src={preview} alt="preview"
            style={{ width: '100%', maxHeight: 220, objectFit: 'cover', display: 'block' }} />
        : <video src={preview} controls
            style={{ width: '100%', maxHeight: 220, display: 'block' }} />
    ) : (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', padding: '32px 16px', gap: 8,
      }}>
        <span style={{ fontSize: 36 }}>{icon}</span>
        <span style={{ fontSize: 13, color: '#444', textAlign: 'center' }}>{hint}</span>
        <span style={{
          marginTop: 4, padding: '4px 12px', borderRadius: 20,
          background: 'rgba(167,139,250,0.08)', border: '1px solid rgba(167,139,250,0.2)',
          fontSize: 11, color: '#a78bfa',
        }}>Browse files</span>
      </div>
    )}
    {hasFile && (
      <div style={{
        position: 'absolute', bottom: 8, right: 8,
        background: 'rgba(167,139,250,0.2)', padding: '3px 10px',
        borderRadius: 20, fontSize: 11, color: '#a78bfa',
      }}>
        ✓ Tap to change
      </div>
    )}
  </label>
);

// ── palette ────────────────────────────────────────────────────────────────────
const P = {
  page: {
    minHeight: '100vh',
    background: 'radial-gradient(ellipse at 50% -10%, #1a0a2e 0%, #0c0c0e 55%)',
    color: '#f0f0f0',
    fontFamily: "'Inter', system-ui, sans-serif",
    display: 'flex', flexDirection: 'column' as const,
    alignItems: 'center',
    padding: '40px 20px 80px',
  },
  heroTitle: {
    fontSize: 26, fontWeight: 800,
    marginTop: 0, marginRight: 0, marginBottom: 6, marginLeft: 0,
    background: 'linear-gradient(135deg, #c4b5fd, #60a5fa)',
    WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
  } as React.CSSProperties,
  heroSub: {
    fontSize: 14, color: '#444',
    marginTop: 0, marginRight: 0, marginBottom: 0, marginLeft: 0,
  },
  card: {
    width: '100%', maxWidth: 520,
    background: 'rgba(22,22,28,0.9)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 20,
    padding: 28,
    boxShadow: '0 8px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04)',
    backdropFilter: 'blur(20px)',
    display: 'flex', flexDirection: 'column' as const, gap: 0,
  },
  tabBar: {
    display: 'flex', gap: 4,
    background: 'rgba(0,0,0,0.3)', borderRadius: 12, padding: 4,
    marginBottom: 24,
    border: '1px solid rgba(255,255,255,0.04)',
  },
  tab: (active: boolean): React.CSSProperties => ({
    flex: 1, padding: '9px 0',
    fontSize: 13, fontWeight: 600,
    border: 'none', borderRadius: 9,
    cursor: 'pointer',
    background: active
      ? 'linear-gradient(135deg,rgba(124,58,237,0.4),rgba(79,70,229,0.4))'
      : 'transparent',
    color: active ? '#c4b5fd' : '#444',
    transition: 'all 0.2s',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
    boxShadow: active ? '0 0 12px rgba(124,58,237,0.2)' : 'none',
    fontFamily: 'inherit',
  }),
  primaryBtn: (disabled: boolean): React.CSSProperties => ({
    width: '100%', padding: '13px',
    fontSize: 14, fontWeight: 700,
    border: 'none', borderRadius: 12,
    background: disabled
      ? 'rgba(255,255,255,0.04)'
      : 'linear-gradient(135deg,#7c3aed,#4f46e5)',
    color: disabled ? '#333' : '#fff',
    cursor: disabled ? 'not-allowed' : 'pointer',
    transition: 'opacity 0.2s, transform 0.1s',
    boxShadow: disabled ? 'none' : '0 4px 20px rgba(124,58,237,0.4)',
    letterSpacing: '0.02em',
    fontFamily: 'inherit',
  }),
  ghostBtn: {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '8px 14px', fontSize: 13, fontWeight: 500,
    border: '1px solid #1e1e2e', borderRadius: 9,
    background: 'transparent', color: '#666',
    cursor: 'pointer', transition: 'all 0.2s',
    fontFamily: 'inherit',
  } as React.CSSProperties,
  hiddenInput: {
    position: 'absolute' as const, inset: 0,
    opacity: 0, cursor: 'pointer', width: '100%', height: '100%',
  },
  textarea: {
    width: '100%', background: 'rgba(0,0,0,0.3)',
    border: '1px solid #1e1e2e', borderRadius: 10,
    color: '#f0f0f0', fontSize: 14, padding: '11px 14px',
    resize: 'vertical' as const, outline: 'none',
    boxSizing: 'border-box' as const, fontFamily: 'inherit', lineHeight: 1.5,
  },
};

const KEYFRAMES = `
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
  @keyframes pop   { 0%{transform:scale(0.7);opacity:0} 60%{transform:scale(1.2)} 100%{transform:scale(1);opacity:1} }
`;
