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
      ],
    });

    console.log(`[renderer] Loaded ${this.gaussianCount} gaussians`);
  }

  updateCamera(view: Float32Array, proj: Float32Array) {
    // Store view for per-frame depth sort in render()
    this._view.set(view);

    const d = new Float32Array(32);
    d.set(view, 0); d.set(proj, 16);
    this.device.queue.writeBuffer(this.cameraUniformBuffer, 0, d);
  }

  /** Drive jaw animation from audio amplitude [0, 1]. Call every RAF frame. */
  setAmplitude(v: number) {
    if (!this.speakBuffer) return;
    this.device.queue.writeBuffer(
      this.speakBuffer, 0,
      new Float32Array([Math.max(0, Math.min(1, v)), 0, 0, 0]),
    );
  }

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

  }
}

// ── WGSL shader ───────────────────────────────────────────────────────────────
const SPLAT_SHADER = /* wgsl */`
struct Camera {
  view:       mat4x4<f32>,
  projection: mat4x4<f32>,
}

// u_speak.x = jaw amplitude [0,1] — drives lower-face displacement
struct Speak { amplitude: f32, _p0: f32, _p1: f32, _p2: f32 }

@group(0) @binding(0) var<uniform>       camera:         Camera;
@group(0) @binding(1) var<storage, read> positions:      array<vec4<f32>>;
@group(0) @binding(2) var<storage, read> scales:         array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> colors:         array<vec4<f32>>;
@group(0) @binding(4) var<uniform>       u_speak:        Speak;
@group(0) @binding(5) var<storage, read> sorted_indices: array<u32>;

struct VOut {
  @builtin(position) pos:   vec4<f32>,
  @location(0)       color: vec4<f32>,
  @location(1)       uv:    vec2<f32>,
}

@vertex
fn vs_main(
  @builtin(vertex_index)   vi: u32,
  @builtin(instance_index) ii: u32,
) -> VOut {
  var quad = array<vec2<f32>, 4>(
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 1.0, -1.0),
    vec2<f32>(-1.0,  1.0),
    vec2<f32>( 1.0,  1.0),
  );
  let corner = quad[vi];

  // Use sorted index so instances are drawn back-to-front
  let si     = sorted_indices[ii];
  var center = positions[si].xyz;
  let scale  = scales[si].xyz;

  // Jaw animation: Gaussians below y=0 (lower face) shift down with amplitude
  let jaw_factor = clamp(-center.y * 15.0, 0.0, 1.0);
  let jaw_disp   = u_speak.amplitude * jaw_factor * 0.025;
  center = vec3<f32>(center.x, center.y - jaw_disp, center.z + jaw_disp * 0.4);

  let clip   = camera.projection * camera.view * vec4<f32>(center, 1.0);
  // Billboard radius in clip space: scale × 3 σ, divided by clip.w for
  // perspective-correct screen size (clip.w ≈ view-space depth).
  let radius = max(max(scale.x, scale.y), scale.z) * 3.0;

  var out: VOut;
  out.pos   = vec4<f32>(
    clip.x + corner.x * radius,
    clip.y + corner.y * radius,
    clip.z,
    clip.w,
  );
  let a     = colors[si].a;
  out.color = vec4<f32>(colors[si].rgb * a, a);
  out.uv    = corner;
  return out;
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
  let r2    = dot(in.uv, in.uv);
  let alpha = exp(-2.0 * r2);
  if alpha < 0.01 { discard; }
  return vec4<f32>(in.color.rgb, in.color.a * alpha);
}
`;
