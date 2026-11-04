import React, { useState } from 'react';
import { Upload } from './pages/Upload';
import { AvatarViewer } from './pages/AvatarViewer';
import { FeedMode } from './pages/FeedMode';
import { HumanLab } from './pages/HumanLab';

const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000';

// ETAPA A: ?feed=1 entra directo al modo Feed (avatar demo) durante el dev
const START_FEED = new URLSearchParams(window.location.search).has('feed');
// exp/three-human: ?human=1 abre el creador three.js (Anny + MakeHuman)
const START_HUMAN = new URLSearchParams(window.location.search).has('human');

// Entrada desde MEYA (/create → ?from=meya&lang=es): enlace de vuelta a su flujo de creación.
// El destino sale de VITE_MEYA_URL, nunca de la query (sin open redirect).
const params = new URLSearchParams(window.location.search);
const MEYA_URL = (import.meta.env.VITE_MEYA_URL || '').replace(/\/$/, '');
const BACK_TO_MEYA = MEYA_URL && params.get('from') === 'meya'
  ? `${MEYA_URL}${params.get('lang') === 'es' ? '/es' : ''}/create`
  : null;

function App() {
  const [currentView, setCurrentView] = useState<'upload' | 'viewer' | 'feed' | 'human'>(
    START_HUMAN ? 'human' : START_FEED ? 'feed' : 'upload');
  const [avatarId, setAvatarId] = useState<string>('');
  const [gaussiansUrl, setGaussiansUrl] = useState<string>('');

  const handleAvatarCreated = (id: string, url: string) => {
    setAvatarId(id);
    setGaussiansUrl(url);
    setCurrentView('viewer');
  };

  return (
    <div style={{ width: '100vw', height: '100vh', backgroundColor: '#000' }}>
      {BACK_TO_MEYA && currentView === 'upload' && (
        <a href={BACK_TO_MEYA} style={{
          position: 'fixed', top: 16, left: 16, zIndex: 10, padding: '8px 14px',
          borderRadius: 999, background: 'rgba(255,255,255,0.08)', color: '#e5e5e5',
          fontSize: 14, textDecoration: 'none', border: '1px solid rgba(255,255,255,0.15)',
        }}>← MEYA</a>
      )}
      {currentView === 'human' ? (
        <HumanLab serverUrl={SERVER_URL} onBack={() => setCurrentView('upload')} />
      ) : currentView === 'feed' ? (
        <FeedMode serverUrl={SERVER_URL} onBack={() => setCurrentView('upload')} />
      ) : currentView === 'upload' ? (
        <Upload serverUrl={SERVER_URL} onAvatarCreated={handleAvatarCreated} />
      ) : (
        <AvatarViewer
          avatarUrl={gaussiansUrl}
          serverUrl={SERVER_URL}
          onBack={() => setCurrentView('upload')}
        />
      )}

    </div>
  );
}

export default App;
