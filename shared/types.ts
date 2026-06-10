// Shared TypeScript types for avatar platform

export interface Avatar {
  id: string;
  gaussians_url: string;
  rig: Record<string, any>;
  type: 'head' | 'full_body';
  created_at: string;
}

export interface Animation {
  id: string;
  avatar_id: string;
  stream_url: string;
}

export interface CreateAvatarRequest {
  video_url: string;
  mode: 'head' | 'full_body';
}

export interface AnimateAvatarRequest {
  avatar_id: string;
  audio_url: string;
}

export interface JobStatus {
  id: string;
  status: 'pending' | 'processing' | 'done' | 'failed';
  progress: number;
  result?: any;
  error?: string;
}

export interface GaussianData {
  positions: Float32Array;
  scales: Float32Array;
  rotations: Float32Array;
  colors: Float32Array;
  opacities: Float32Array;
  count: number;
}

export interface DeformationUpdate {
  timestamp: number;
  positions?: Float32Array;
  rotations?: Float32Array;
}
