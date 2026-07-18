import React, { useState } from 'react';
import { Upload } from './pages/Upload';
import { AvatarViewer } from './pages/AvatarViewer';
import { FeedMode } from './pages/FeedMode';

const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000';

// ETAPA A: ?feed=1 entra directo al modo Feed (avatar demo) durante el dev
const START_FEED = new URLSearchParams(window.location.search).has('feed');

function App() {
  const [currentView, setCurrentView] = useState<'upload' | 'viewer' | 'feed'>(
    START_FEED ? 'feed' : 'upload');
  const [avatarId, setAvatarId] = useState<string>('');
  const [gaussiansUrl, setGaussiansUrl] = useState<string>('');

  const handleAvatarCreated = (id: string, url: string) => {
    setAvatarId(id);
    setGaussiansUrl(url);
    setCurrentView('viewer');
  };

  return (
    <div style={{ width: '100vw', height: '100vh', backgroundColor: '#000' }}>
      {currentView === 'feed' ? (
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
