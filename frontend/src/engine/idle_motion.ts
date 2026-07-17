/**
 * Procedural idle/speech head motion for the splat viewer.
 *
 * The static PLY has no rig, so "life" comes from a rigid model matrix:
 * slow sinusoidal yaw/pitch/roll (a person holding still is never frozen),
 * a breathing bob, and amplitude-driven micro-nods while speaking.
 *
 * The matrix is folded into the view matrix on the CPU each frame
 * (view' = view · model), so the shader's covariance math stays untouched
 * and the depth sort keeps using the camera-only view.
 */

/** Column-major 4×4 multiply: out = a · b. */
export function mulMat4(a: Float32Array, b: Float32Array): Float32Array {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      out[c * 4 + r] =
        a[r]      * b[c * 4]     +
        a[4 + r]  * b[c * 4 + 1] +
        a[8 + r]  * b[c * 4 + 2] +
        a[12 + r] * b[c * 4 + 3];
    }
  }
  return out;
}

// Rotating about the neck (not the head centre) makes the head arc the way
// a real neck moves. LAM canonical head spans y ∈ [-0.22, 0.15] m.
const NECK_PIVOT_Y = -0.15;

/**
 * Rigid idle/speak transform. `t` in seconds, `amp` = speech amplitude [0,1].
 * Angles stay under ~4° so the small-rotation sort approximation holds.
 */
export function idleModelMatrix(t: number, amp: number): Float32Array {
  // Two incommensurate sines per axis → organic, never-repeating sway. The
  // amp-driven nod is deliberately small (0.02): at 0.05 a saturated speech
  // envelope produced a fast metronome nod that buried the base idle sway.
  const yaw   = 0.05  * Math.sin(0.6 * t)       + 0.02 * Math.sin(1.7 * t + 1.3);
  const pitch = 0.03  * Math.sin(0.9 * t + 0.5) + amp * 0.02 * Math.sin(4.5 * t);
  const roll  = 0.012 * Math.sin(0.4 * t + 2.0);
  const ty    = 0.0025 * Math.sin(1.1 * t);     // breathing bob (±2.5 mm)

  const cy = Math.cos(yaw),   sy = Math.sin(yaw);
  const cx = Math.cos(pitch), sx = Math.sin(pitch);
  const cz = Math.cos(roll),  sz = Math.sin(roll);

  // R = Ry · Rx · Rz, stored column-major
  const m = new Float32Array(16);
  m[0]  = cy * cz + sy * sx * sz;   // row0 col0
  m[1]  = cx * sz;                  // row1 col0
  m[2]  = -sy * cz + cy * sx * sz;  // row2 col0
  m[4]  = -cy * sz + sy * sx * cz;  // row0 col1
  m[5]  = cx * cz;                  // row1 col1
  m[6]  = sy * sz + cy * sx * cz;   // row2 col1
  m[8]  = sy * cx;                  // row0 col2
  m[9]  = -sx;                      // row1 col2
  m[10] = cy * cx;                  // row2 col2
  m[15] = 1;

  // Full transform: T(pivot + ty·ŷ) · R · T(-pivot)
  // → translation column = pivot - R·pivot + (0, ty, 0)
  m[12] = -m[4] * NECK_PIVOT_Y;
  m[13] = NECK_PIVOT_Y - m[5] * NECK_PIVOT_Y + ty;
  m[14] = -m[6] * NECK_PIVOT_Y;
  return m;
}
