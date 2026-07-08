/**
 * Orbit camera for 3D avatar viewing.
 *
 * Coordinate system: Y-up right-handed (matches FLAME / avatar bundle).
 * Projection uses WebGPU NDC Z ∈ [0, 1] (NOT OpenGL's [-1, 1]).
 */

export class Camera {
  // Portrait-lens setup: narrow FOV from further back. A wide FOV at 0.3 m
  // renders faces like a selfie lens — huge nose, stretched centre.
  private fov    = 22 * (Math.PI / 180);
  private aspect = 16 / 9;
  private near   = 0.01;   // 1 cm
  private far    = 10;     // 10 m

  // Orbit state
  private rotX   = 0;      // vertical   (pitch)
  // Avatars face +z (canonical convention — verified against LAM output and a
  // reference viewer, docs/lam-migration.md). Camera starts at +z, facing them.
  private rotY   = 0;      // horizontal (yaw)
  private distance = 0.65;  // metres from target — same framing as 45°@0.3 m

  private isDragging = false;
  private lastX = 0;
  private lastY = 0;

  /** Keep projection in sync when the canvas backing store is resized. */
  setAspect(aspect: number) { this.aspect = aspect; }

  constructor(canvas: HTMLCanvasElement) {
    this.aspect = canvas.width / canvas.height;
    canvas.addEventListener('mousedown', this._down.bind(this));
    canvas.addEventListener('mousemove', this._move.bind(this));
    canvas.addEventListener('mouseup',   this._up.bind(this));
    canvas.addEventListener('wheel',     this._wheel.bind(this), { passive: false });
  }

  // ── matrices ────────────────────────────────────────────────────────────────

  getViewMatrix(): Float32Array {
    // Camera position on orbit sphere
    const x = this.distance * Math.sin(this.rotY) * Math.cos(this.rotX);
    const y = this.distance * Math.sin(this.rotX);
    const z = this.distance * Math.cos(this.rotY) * Math.cos(this.rotX);

    // LookAt (target = origin)
    const zAxis = norm([x, y, z]);
    const xAxis = norm(cross([0, 1, 0], zAxis));
    const yAxis = cross(zAxis, xAxis);

    // Column-major view matrix
    const m = new Float32Array(16);
    m[0]=xAxis[0]; m[1]=yAxis[0]; m[2]=zAxis[0]; m[3]=0;
    m[4]=xAxis[1]; m[5]=yAxis[1]; m[6]=zAxis[1]; m[7]=0;
    m[8]=xAxis[2]; m[9]=yAxis[2]; m[10]=zAxis[2];m[11]=0;
    m[12]=-dot(xAxis,[x,y,z]);
    m[13]=-dot(yAxis,[x,y,z]);
    m[14]=-dot(zAxis,[x,y,z]);
    m[15]=1;
    return m;
  }

  getProjectionMatrix(): Float32Array {
    // WebGPU perspective: Z ∈ [0, 1]  (NOT OpenGL's [-1, 1])
    const f  = 1 / Math.tan(this.fov / 2);
    const nf = 1 / (this.near - this.far);

    const m = new Float32Array(16);
    m[0]  = f / this.aspect;
    m[5]  = f;
    m[10] = this.far * nf;          //  far / (near - far)
    m[11] = -1;
    m[14] = this.near * this.far * nf;  // near*far / (near - far)
    return m;
  }

  // ── mouse handlers ──────────────────────────────────────────────────────────

  private _down(e: MouseEvent) {
    this.isDragging = true;
    this.lastX = e.clientX;
    this.lastY = e.clientY;
  }

  private _move(e: MouseEvent) {
    if (!this.isDragging) return;
    this.rotY += (e.clientX - this.lastX) * 0.005;
    this.rotX += (e.clientY - this.lastY) * 0.005;
    this.rotX  = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, this.rotX));
    this.lastX = e.clientX;
    this.lastY = e.clientY;
  }

  private _up()               { this.isDragging = false; }
  private _wheel(e: WheelEvent) {
    e.preventDefault();
    // Min 0.25 m keeps perspective distortion of the face acceptable
    this.distance = Math.max(0.25, Math.min(2, this.distance + e.deltaY * 0.001));
  }
}

// ── math helpers ─────────────────────────────────────────────────────────────
type V3 = [number,number,number] | number[];
const dot   = (a: V3, b: V3) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const cross = (a: V3, b: V3): V3 => [
  a[1]*b[2] - a[2]*b[1],
  a[2]*b[0] - a[0]*b[2],
  a[0]*b[1] - a[1]*b[0],
];
const norm = (v: V3): V3 => {
  const l = Math.sqrt(dot(v, v));
  return [v[0]/l, v[1]/l, v[2]/l];
};
