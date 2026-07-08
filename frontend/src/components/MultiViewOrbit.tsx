/**
 * MultiViewOrbit — shows generated face views orbiting in a ring,
 * then converging onto the central frontal image.
 *
 * This is a pure visual effect to communicate that multiple viewpoints
 * are being analysed. It has no effect on the reconstruction pipeline.
 *
 * Props:
 *   images   — { angle_key: imageUrl }  from job.result.multiview_images
 *   converge — when true, animate all side views flying into centre
 */

import React, { useEffect, useRef, useState } from 'react';

interface Props {
  images: Record<string, string>;
  converge?: boolean;
}

// Order in which to lay out angle keys around the ring
const RING_ORDER = [
  'left_90', 'left_60', 'left_30',
  'front',
  'right_30', 'right_60', 'right_90',
  'up', 'down',
];

// How many degrees apart to space items in the ring
const RING_RADIUS = 110;   // px
const THUMB_SIZE = 52;     // px (side views)
const FRONT_SIZE = 78;     // px (centre / frontal)

export const MultiViewOrbit: React.FC<Props> = ({ images, converge = false }) => {
  const [, setTick]           = useState(0);          // drives continuous rotation
  const [done, setDone]       = useState(false);       // stops rotation after converge
  const rafRef                = useRef<number>(0);
  const startRef              = useRef<number | null>(null);
  const rotRef                = useRef(0);

  // Animate rotation (12°/sec) until converge kicks in
  useEffect(() => {
    if (converge || done) return;

    const step = (ts: number) => {
      if (startRef.current === null) startRef.current = ts;
      const elapsed = (ts - startRef.current) / 1000;   // seconds
      rotRef.current = (elapsed * 12) % 360;
      setTick(t => t + 1);
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [converge, done]);

  // When converge activates, run a 600 ms ease-in animation then stop
  useEffect(() => {
    if (!converge) return;
    cancelAnimationFrame(rafRef.current);
    const timeout = setTimeout(() => setDone(true), 700);
    return () => clearTimeout(timeout);
  }, [converge]);

  const keys = RING_ORDER.filter(k => k in images);
  const nSide = keys.filter(k => k !== 'front').length;

  const frontUrl = images['front'];

  return (
    <div style={{
      position: 'relative',
      width: RING_RADIUS * 2 + FRONT_SIZE + 20,
      height: RING_RADIUS * 2 + FRONT_SIZE + 20,
      margin: '0 auto',
      flexShrink: 0,
    }}>

      {/* Centre — frontal image */}
      {frontUrl && (
        <img
          src={frontUrl}
          alt="frontal"
          style={{
            position: 'absolute',
            width:  FRONT_SIZE,
            height: FRONT_SIZE,
            borderRadius: '50%',
            objectFit: 'cover',
            top:  '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            border: '2px solid rgba(167,139,250,0.8)',
            boxShadow: '0 0 20px rgba(124,58,237,0.5)',
            animation: 'pop 0.45s ease',
            zIndex: 10,
          }}
        />
      )}

      {/* Ring items */}
      {keys.filter(k => k !== 'front').map((key, i) => {
        const angleDeg = (i / nSide) * 360 + rotRef.current;
        const rad      = (angleDeg * Math.PI) / 180;
        const cx       = RING_RADIUS + FRONT_SIZE / 2 + 10;   // centre px
        const cy       = cx;

        const xFar = cx + Math.cos(rad) * RING_RADIUS - THUMB_SIZE / 2;
        const yFar = cy + Math.sin(rad) * RING_RADIUS - THUMB_SIZE / 2;

        // converge: fly toward centre
        const xNear = cx - THUMB_SIZE / 2;
        const yNear = cy - THUMB_SIZE / 2;

        const t = converge ? 1 : 0;
        const x = xFar + (xNear - xFar) * t;
        const y = yFar + (yNear - yFar) * t;

        const opacity = converge ? 0 : 0.85;

        return (
          <img
            key={key}
            src={images[key]}
            alt={key}
            style={{
              position: 'absolute',
              width:  THUMB_SIZE,
              height: THUMB_SIZE,
              borderRadius: '50%',
              objectFit: 'cover',
              left: x,
              top:  y,
              border: '1px solid rgba(167,139,250,0.4)',
              opacity,
              transition: converge
                ? 'left 0.6s ease-in, top 0.6s ease-in, opacity 0.5s ease-in'
                : 'none',
              // pop-in as each generated view arrives (keyframes from Upload.tsx)
              animation: converge ? 'none' : 'pop 0.45s ease',
              pointerEvents: 'none',
              zIndex: 5,
            }}
          />
        );
      })}

      {/* Subtle ring guide */}
      {!done && (
        <div style={{
          position: 'absolute',
          top:    '50%',
          left:   '50%',
          width:  RING_RADIUS * 2,
          height: RING_RADIUS * 2,
          transform: 'translate(-50%, -50%)',
          border: '1px dashed rgba(167,139,250,0.12)',
          borderRadius: '50%',
          pointerEvents: 'none',
        }} />
      )}
    </div>
  );
};
