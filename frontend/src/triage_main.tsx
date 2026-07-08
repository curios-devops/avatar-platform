/** Dev-only triage entry: /triage.html?ply=<url> renders AvatarViewer
 *  with an arbitrary PLY so renderer bugs can be isolated from the
 *  upload/job flow. Not part of the app build. */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { AvatarViewer } from './pages/AvatarViewer';

const ply = new URLSearchParams(location.search).get('ply')
  ?? 'http://127.0.0.1:8787/reference_head.ply';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <AvatarViewer avatarUrl={ply} serverUrl="http://localhost:8000" />,
);
