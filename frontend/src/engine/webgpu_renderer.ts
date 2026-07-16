/**
 * WebGPU Gaussian Splatting Renderer
 * Renders Gaussian splats as alpha-blended billboard quads.
 *
 * Depth sorting: every frame the CPU sorts 50 K splat indices back-to-front
 * using the current view matrix (only 200 KB/frame upload).  Without sorting,
 * the pre-multiplied-alpha blend produces a noisy white wash because the first
 * 5 drawn splats at each pixel dominate 99 %+ of the final colour.
 *
 * Supports real-time jaw animation driven by audio amplitude (binding 4).
 */

import { GaussianData } from '../../../shared/types';

export class WebGPURenderer {
  private device!: GPUDevice;
  private context!: GPUCanvasContext;
  private pipeline!: GPURenderPipeline;

  private positionBuffer!: GPUBuffer;
  private scaleBuffer!: GPUBuffer;
  private colorBuffer!: GPUBuffer;
  private cameraUniformBuffer!: GPUBuffer;
  private speakBuffer!: GPUBuffer;
  private indexBuffer!: GPUBuffer;        // sorted splat indices (u32 per splat)
  private rotationBuffer!: GPUBuffer;     // quaternions (w,x,y,z) per splat
  private bindGroup!: GPUBindGroup;

  // CPU-side data for per-frame depth sort
  private _cpuPos!: Float32Array;         // padded vec4 positions (same as positionBuffer)
  private _sortedIdx!: Uint32Array;       // indices sorted back-to-front
  private _viewZ!: Float32Array;          // view-space z scratch
  private _lastViewKey = '';              // skip re-sort when camera hasn't moved

  private canvas: HTMLCanvasElement;
  gaussianCount = 0;

  // Last uploaded view matrix — passed in via updateCamera, used by render()
  private _view = new Float32Array(16);

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }

  async initialize(): Promise<boolean> {
    if (!navigator.gpu) {
      console.error('[renderer] WebGPU not supported');
      return false;
    }
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) { console.error('[renderer] no GPU adapter'); return false; }

    this.device = await adapter.requestDevice();
    this.device.addEventListener('uncapturederror', e => {
      console.error('[renderer] GPU error:', (e as GPUUncapturedErrorEvent).error);
    });

    this.context = this.canvas.getContext('webgpu')!;
    this.context.configure({
      device: this.device,
      format: navigator.gpu.getPreferredCanvasFormat(),
      alphaMode: 'opaque',
    });

    await this._createPipeline();
    console.log('[renderer] WebGPU renderer initialized');
    return true;
  }

  private async _createPipeline() {
    const module = this.device.createShaderModule({ code: SPLAT_SHADER });

    const info = await module.getCompilationInfo();
    for (const msg of info.messages) {
      const fn = msg.type === 'error' ? console.error : console.warn;
      fn(`[renderer] WGSL ${msg.type} line ${msg.lineNum}: ${msg.message}`);
    }
    if (info.messages.some(m => m.type === 'error')) {
      throw new Error('WGSL compilation failed — see console for details');
    }

    this.pipeline = this.device.createRenderPipeline({
      layout: 'auto',
      vertex:   { module, entryPoint: 'vs_main' },
      fragment: {
        module, entryPoint: 'fs_main',
        targets: [{
          format: navigator.gpu.getPreferredCanvasFormat(),
          blend: {
            color: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' },
            alpha: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' },
          },
        }],
      },
      primitive: { topology: 'triangle-strip' },
    });
  }

  loadGaussians(data: GaussianData) {
    this.gaussianCount = data.count;

    // WGSL array<vec3<f32>> has 16-byte stride — pad to vec4
    const pos4 = new Float32Array(data.count * 4);
    const scl4 = new Float32Array(data.count * 4);
    for (let i = 0; i < data.count; i++) {
      pos4[i*4]   = data.positions[i*3];
      pos4[i*4+1] = data.positions[i*3+1];
      pos4[i*4+2] = data.positions[i*3+2];
      pos4[i*4+3] = 1;

      scl4[i*4]   = data.scales[i*3];
      scl4[i*4+1] = data.scales[i*3+1];
      scl4[i*4+2] = data.scales[i*3+2];
      scl4[i*4+3] = 0;
    }

    // Keep CPU copy of positions for per-frame depth sort
    this._cpuPos      = pos4;
    this._sortedIdx   = new Uint32Array(data.count);
    this._viewZ       = new Float32Array(data.count);
    for (let i = 0; i < data.count; i++) this._sortedIdx[i] = i;

    this.positionBuffer = this._buf(pos4,        GPUBufferUsage.STORAGE);
    this.scaleBuffer    = this._buf(scl4,        GPUBufferUsage.STORAGE);
    this.colorBuffer    = this._buf(data.colors, GPUBufferUsage.STORAGE);
    // Quaternions (w,x,y,z) per splat — anisotropic covariance needs them
    this.rotationBuffer = this._buf(
      data.rotations ?? new Float32Array(data.count * 4),
      GPUBufferUsage.STORAGE,
    );

    this.cameraUniformBuffer = this.device.createBuffer({
      size: 128,   // 2 × mat4x4<f32>
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    // Sorted-index buffer (u32 per splat) — updated every frame
    this.indexBuffer = this.device.createBuffer({
      size: Math.max(data.count * 4, 16),
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    // Initialise with identity order
    this.device.queue.writeBuffer(this.indexBuffer, 0, this._sortedIdx);

    // Speak (jaw amplitude) uniform — 16 bytes (vec4, x = amplitude [0,1])
    this.speakBuffer = this.device.createBuffer({
      size: 16,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    console.log(`[renderer] scale[0] = ${data.scales[0].toExponential(2)} m`);
    console.log(`[renderer] pos[0]   = (${data.positions[0].toFixed(3)}, ${data.positions[1].toFixed(3)}, ${data.positions[2].toFixed(3)})`);

    this.bindGroup = this.device.createBindGroup({
      layout: this.pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: this.cameraUniformBuffer } },
        { binding: 1, resource: { buffer: this.positionBuffer } },
        { binding: 2, resource: { buffer: this.scaleBuffer } },
        { binding: 3, resource: { buffer: this.colorBuffer } },
        { binding: 4, resource: { buffer: this.speakBuffer } },
        { binding: 5, resource: { buffer: this.indexBuffer } },
        { binding: 6, resource: { buffer: this.rotationBuffer } },
      ],
    });

    console.log(`[renderer] Loaded ${this.gaussianCount} gaussians`);
  }

  updateCamera(view: Float32Array, proj: Float32Array, sortView?: Float32Array) {
    // Store view for per-frame depth sort in render(). When the caller folds
    // an idle model matrix into `view`, it passes the camera-only matrix as
    // `sortView`: re-sorting 50 K splats every frame for a <4° sway buys
    // nothing visually, and this keeps the "camera static → skip sort" fast path.
    this._view.set(sortView ?? view);

    const d = new Float32Array(32);
    d.set(view, 0); d.set(proj, 16);
    this.device.queue.writeBuffer(this.cameraUniformBuffer, 0, d);
  }

  /** Drive jaw animation from audio amplitude [0, 1]. Call every RAF frame. */
  setAmplitude(v: number) {
    this._amplitude = Math.max(0, Math.min(1, v));
  }
  private _amplitude = 0;

  updateDeformation(positions?: Float32Array) {
    if (positions) this.device.queue.writeBuffer(this.positionBuffer, 0, positions);
  }

  render() {
    if (!this.bindGroup || this.gaussianCount === 0) return;

    // Depth sort: back-to-front using current view matrix.
    // Row 2 of the view matrix (col-major: indices 2, 6, 10) gives the
    // camera's Z-axis in world space.  Dot-product with each splat position
    // gives view-space z; sort descending = back-to-front.
    this._depthSort();

    // amplitude + viewport size (shader needs pixels for covariance focal)
    this.device.queue.writeBuffer(
      this.speakBuffer, 0,
      new Float32Array([this._amplitude, this.canvas.width, this.canvas.height, 0]),
    );

    const enc  = this.device.createCommandEncoder();
    const pass = enc.beginRenderPass({
      colorAttachments: [{
        view:       this.context.getCurrentTexture().createView(),
        clearValue: { r: 0.05, g: 0.04, b: 0.09, a: 1 },
        loadOp:  'clear',
        storeOp: 'store',
      }],
    });
    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, this.bindGroup);
    pass.draw(4, this.gaussianCount);
    pass.end();
    this.device.queue.submit([enc.finish()]);
  }

  // ── depth sort ───────────────────────────────────────────────────────────────

  private _depthSort() {
    if (!this._cpuPos || !this.indexBuffer) return;

    // Column-major view matrix: row 2 = (view[2], view[6], view[10])
    // This row dotted with a world position gives view-space z.
    const v = this._view;
    const r20 = v[2], r21 = v[6], r22 = v[10];

    // Encode the camera orientation as a short string to skip re-sort when static.
    const key = `${r20.toFixed(4)},${r21.toFixed(4)},${r22.toFixed(4)}`;
    if (key === this._lastViewKey) return;
    this._lastViewKey = key;

    const n   = this.gaussianCount;
    const pos = this._cpuPos;
    const z   = this._viewZ;
    const idx = this._sortedIdx;

    // Compute view-space z for every splat (no translation — only direction matters for sort)
    for (let i = 0; i < n; i++) {
      const b = i * 4;
      z[i] = r20 * pos[b] + r21 * pos[b+1] + r22 * pos[b+2];
    }

    // Back-to-front: ascending dot-product order → farthest splats drawn first,
    // nose (highest dot value, closest to camera) drawn last and composites on top.
    idx.sort((a, b) => z[a] - z[b]);

    // Upload the 200 KB index array (50 K × 4 bytes)
    this.device.queue.writeBuffer(this.indexBuffer, 0, idx);
  }

  // ── helpers ──────────────────────────────────────────────────────────────────

  private _buf(data: Float32Array, usage: GPUBufferUsageFlags): GPUBuffer {
    const buf = this.device.createBuffer({
      size: Math.max(data.byteLength, 16),
      usage: usage | GPUBufferUsage.COPY_DST,
      mappedAtCreation: true,
    });
    new Float32Array(buf.getMappedRange()).set(data);
    buf.unmap();
    return buf;
  }

  destroy() {
    this.positionBuffer?.destroy();
    this.scaleBuffer?.destroy();
    this.colorBuffer?.destroy();
    this.cameraUniformBuffer?.destroy();
    this.speakBuffer?.destroy();
    this.indexBuffer?.destroy();
    this.rotationBuffer?.destroy();

  }
}

// ── WGSL shader ───────────────────────────────────────────────────────────────
const SPLAT_SHADER = /* wgsl */`
struct Camera {
  view:       mat4x4<f32>,
  projection: mat4x4<f32>,
}

// u_speak: x = jaw amplitude [0,1], y/z = viewport width/height in pixels
struct Speak { amplitude: f32, vp_w: f32, vp_h: f32, _p2: f32 }

@group(0) @binding(0) var<uniform>       camera:         Camera;
@group(0) @binding(1) var<storage, read> positions:      array<vec4<f32>>;
@group(0) @binding(2) var<storage, read> scales:         array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> colors:         array<vec4<f32>>;
@group(0) @binding(4) var<uniform>       u_speak:        Speak;
@group(0) @binding(5) var<storage, read> sorted_indices: array<u32>;
@group(0) @binding(6) var<storage, read> rotations:      array<vec4<f32>>;

struct VOut {
  @builtin(position) pos:   vec4<f32>,
  @location(0)       color: vec4<f32>,
  @location(1)       uv:    vec2<f32>,
}

// Full anisotropic 3DGS rasterisation (EWA splatting, as in the reference
// INRIA/antimatter15 implementations): project each gaussian's 3D covariance
// R·S·Sᵀ·Rᵀ through the view + perspective Jacobian, eigen-decompose the 2D
// covariance, and stretch the quad along the ellipse axes.
@vertex
fn vs_main(
  @builtin(vertex_index)   vi: u32,
  @builtin(instance_index) ii: u32,
) -> VOut {
  var quad = array<vec2<f32>, 4>(
    vec2<f32>(-2.0, -2.0),
    vec2<f32>( 2.0, -2.0),
    vec2<f32>(-2.0,  2.0),
    vec2<f32>( 2.0,  2.0),
  );
  let corner = quad[vi];
  let si     = sorted_indices[ii];
  var center = positions[si].xyz;
  let scale  = scales[si].xyz;

  // Speech motion: soft radial mask around the lips, so only the mouth area
  // moves (the old version shifted everything below y=0 — the whole lower
  // face stretched like a band). Mouth centre in LAM canonical space
  // (head spans y ∈ [-0.22, 0.15], face at +z).
  let mouth  = vec3<f32>(0.0, -0.06, 0.045);
  let m_dist = distance(center, mouth);
  let m_mask = 1.0 - smoothstep(0.030, 0.095, m_dist);
  // Chin follows fully, upper lip barely — a jaw opens downward only.
  let below  = clamp(0.5 - (center.y - mouth.y) * 12.0, 0.0, 1.0);
  let drop   = u_speak.amplitude * 0.016 * m_mask * (0.25 + 0.75 * below);
  center = vec3<f32>(center.x, center.y - drop, center.z - drop * 0.3);

  var out: VOut;
  let cam_pos = camera.view * vec4<f32>(center, 1.0);
  let clip    = camera.projection * cam_pos;
  // Cull behind-camera / far outside frustum
  if (clip.w <= 0.0 || abs(clip.x) > 1.3 * clip.w || abs(clip.y) > 1.3 * clip.w) {
    out.pos = vec4<f32>(0.0, 0.0, 2.0, 1.0);
    return out;
  }

  // 3D covariance: M = R(q)·S  →  Σ = M·Mᵀ   (q stored as w,x,y,z)
  let q = normalize(rotations[si]);
  let w = q.x; let x = q.y; let y = q.z; let z = q.w;
  // Written in row-major reading order; WGSL fills column-major → transpose
  let R = transpose(mat3x3<f32>(
    1.0 - 2.0*(y*y + z*z), 2.0*(x*y + w*z),       2.0*(x*z - w*y),
    2.0*(x*y - w*z),       1.0 - 2.0*(x*x + z*z), 2.0*(y*z + w*x),
    2.0*(x*z + w*y),       2.0*(y*z - w*x),       1.0 - 2.0*(x*x + y*y),
  ));
  let S = mat3x3<f32>(
    scale.x, 0.0, 0.0,
    0.0, scale.y, 0.0,
    0.0, 0.0, scale.z,
  );
  let M     = R * S;
  let sigma = M * transpose(M);

  // View rotation (upper-left 3×3 of the view matrix)
  let W = mat3x3<f32>(camera.view[0].xyz, camera.view[1].xyz, camera.view[2].xyz);

  // Perspective Jacobian at the splat centre (focal lengths in pixels)
  let focal = vec2<f32>(
    camera.projection[0][0] * u_speak.vp_w * 0.5,
    camera.projection[1][1] * u_speak.vp_h * 0.5,
  );
  let t  = cam_pos.xyz;
  // Note -focal.y: compensates the NDC↔pixel y-flip (as in the reference
  // antimatter15 implementation) — without it ellipse tilts mirror and the
  // splat grid renders as dark cross-hatching.
  // Written in row-major reading order; WGSL fills column-major → transpose
  // (same convention fix as R above — without it the covariance is computed
  // with Jᵀ and off-centre splats get scrambled ellipses).
  let J  = transpose(mat3x3<f32>(
    focal.x / t.z, 0.0, -(focal.x * t.x) / (t.z * t.z),
    0.0, -focal.y / t.z, (focal.y * t.y) / (t.z * t.z),
    0.0, 0.0, 0.0,
  ));
  let T    = transpose(J * W);
  let cov4 = transpose(T) * sigma * T;   // 2D covariance (pixels²)
  let c00 = cov4[0][0] + 0.3;            // +0.3 px anti-alias floor
  let c11 = cov4[1][1] + 0.3;
  let c01 = cov4[0][1];

  // Eigen-decomposition → ellipse axes (clamped so one splat can't fill the screen)
  let mid    = 0.5 * (c00 + c11);
  let radius = length(vec2<f32>(0.5 * (c00 - c11), c01));
  let l1     = mid + radius;
  let l2     = max(mid - radius, 0.1);
  let diag   = normalize(vec2<f32>(c01, l1 - c00));
  let v1     = min(sqrt(2.0 * l1), 512.0) * diag;
  let v2     = min(sqrt(2.0 * l2), 512.0) * vec2<f32>(diag.y, -diag.x);

  let center_ndc = clip.xy / clip.w;
  // px → NDC: NDC spans 2 units over vp pixels, so scale by 2/vp
  let offset_ndc = (corner.x * v1 + corner.y * v2) * 2.0 / vec2<f32>(u_speak.vp_w, u_speak.vp_h);
  out.pos = vec4<f32>(center_ndc + offset_ndc, 0.0, 1.0);

  let a     = colors[si].a;
  out.color = vec4<f32>(colors[si].rgb * a, a);
  out.uv    = corner;
  return out;
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
  // uv is in ellipse-normalised units (quad spans ±2σ·√2); standard gaussian
  let a = -dot(in.uv, in.uv);
  if (a < -4.0) { discard; }
  let falloff = exp(a);
  // Premultiplied blending: rgb carries the same total alpha as the α channel
  return vec4<f32>(in.color.rgb * falloff, in.color.a * falloff);
}
`;
