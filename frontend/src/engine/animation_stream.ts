/**
 * Animation Streaming
 * Handles WebSocket connection for real-time avatar animation
 */

import { DeformationUpdate } from '../../../shared/types';

export class AnimationStream {
  private ws: WebSocket | null = null;
  private onDeformationCallback?: (update: DeformationUpdate) => void;

  connect(avatarId: string, serverUrl: string) {
    const wsUrl = `${serverUrl}/api/v1/stream/${avatarId}`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('Animation stream connected');

      // Send ping to keep alive
      setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'pong') {
        return;
      }

      // Deformation update
      if (data.timestamp !== undefined) {
        const update: DeformationUpdate = {
          timestamp: data.timestamp,
          positions: data.positions ? new Float32Array(data.positions) : undefined,
          rotations: data.rotations ? new Float32Array(data.rotations) : undefined,
        };

        this.onDeformationCallback?.(update);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = () => {
      console.log('Animation stream closed');
    };
  }

  onDeformation(callback: (update: DeformationUpdate) => void) {
    this.onDeformationCallback = callback;
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
