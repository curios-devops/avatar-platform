// three.js runtime for the baked human (human/baker.py): materials, a procedural rig animator
// (idle, breathing, blinks, gaze, walk), facial expressions and lip sync from Speech.
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { EXPRESSIONS, type Weights } from './visemes';
import { SKIN, applySkin, skinShader, type SkinParams } from './skin';

export type Look = {
  skin?: string; // asset path of the skin diffuse texture
  eyes?: string; // asset path of the iris texture
  hairColor?: string; // multiply tint, '#ffffff' keeps the texture
  clothesColor?: string;
  tints?: Record<string, string>; // per proxy (mesh name), wins over clothesColor
  accessories?: Accessory[];
  faceTexture?: string; // full URL of a projected face texture (Twin mode), replaces `skin`
};
export type Accessory = { id: 'hoops' | 'studs' | 'glasses' | 'sunglasses'; color?: string };
export type Framing = 'face' | 'bust' | 'full';
/** What sits under the pointer: the mesh kind from the baker (body, hair, clothes, shoes…) and the proxy name. */
export type Pick = { kind: string; name: string };

const X = new THREE.Vector3(1, 0, 0);
const Y = new THREE.Vector3(0, 1, 0);
const Z = new THREE.Vector3(0, 0, 1);
// GLTFLoader sanitizes node names (PropertyBinding.sanitizeNodeName drops "." and friends): "eye.L" arrives as "eyeL".
const key = (name: string) => name.replace(/[[\].:/]/g, '').replace(/\s/g, '_');

/**
 * Dye a garment: a multiply tint cannot turn a blue tee white, so the texture is taken to luminance and
 * the new colour painted over it, keeping a third of the original shading for seams, folds and prints.
 */
function dye(m: THREE.MeshPhysicalMaterial, hex: string) {
  const c = new THREE.Color(hex);
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uDye = { value: c };
    sh.fragmentShader = sh.fragmentShader
      .replace('void main() {', 'uniform vec3 uDye;\nvoid main() {')
      .replace('#include <map_fragment>', `#include <map_fragment>
        float dyeL = dot(diffuseColor.rgb, vec3(0.299, 0.587, 0.114));
        diffuseColor.rgb = uDye * mix(1.0, clamp(dyeL / 0.42, 0.25, 1.6), 0.35);`);
  };
  m.customProgramCacheKey = () => 'dye';
}

export class HumanEngine {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(30, 1, 0.02, 60);
  readonly controls: OrbitControls;
  private root = new THREE.Group();
  private model: THREE.Object3D | null = null;
  private bones = new Map<string, THREE.Bone>();
  private rest = new Map<string, { q: THREE.Quaternion; p: THREE.Vector3; parentWorld: THREE.Quaternion; world: THREE.Quaternion }>();
  private morphMeshes: THREE.Mesh[] = [];
  private textures = new Map<string, Promise<THREE.Texture>>();
  private clock = new THREE.Clock();
  private raf = 0;
  private resizeObserver: ResizeObserver;
  private look: Look = {};
  private exprTarget: Weights = {};
  private expr: Weights = {};
  private blinkAt = 2;
  private saccade = new THREE.Vector2();
  private saccadeAt = 1;
  private gaze = new THREE.Vector2();
  private walkPhase = 0;
  private walkAngle = 0;
  private walkBlend = 0;
  private armDrop = { L: 0.8, R: 0.8 };
  private frames = 0;
  private fpsAt = 0;
  private lights!: { key: THREE.DirectionalLight; fill: THREE.DirectionalLight; rim: THREE.DirectionalLight };
  fps = 0;
  walking = false;
  mouth: () => Weights = () => ({});

  private accessories = new THREE.Group();
  private ray = new THREE.Raycaster();
  private shift = 0;
  private lift = 0;
  /** Camera distance for the full-body framing; the studio pulls back so the UI never covers the feet. */
  fullDistance = 4.4;
  private ground!: THREE.Mesh;

  /** `transparent`: no background or fog, the floor only catches shadows, so the page behind shows through. */
  constructor(private host: HTMLElement, private assetBase: string, transparent = false) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: transparent });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    Object.assign(this.renderer.domElement.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block' });
    host.appendChild(this.renderer.domElement);
    (window as any).__human = this; // debugging and the comparison harness

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.55;
    if (!transparent) {
      this.scene.background = new THREE.Color('#2b2e34');
      this.scene.fog = new THREE.Fog('#2b2e34', 8, 22);
    }

    const key = new THREE.DirectionalLight('#fff4e8', 2.4);
    key.position.set(1.6, 3.2, 2.4);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = key.shadow.camera.bottom = -4;
    key.shadow.camera.right = key.shadow.camera.top = 4;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.02;
    const fill = new THREE.DirectionalLight('#cfe0ff', 0.6);
    fill.position.set(-2.5, 1.6, 1.5);
    const rim = new THREE.DirectionalLight('#ffffff', 1.4);
    rim.position.set(-1.2, 2.4, -2.6);
    this.scene.add(key, fill, rim, new THREE.HemisphereLight('#dde6ff', '#3a3330', 0.35));
    this.lights = { key, fill, rim };

    const ground = this.ground = new THREE.Mesh(new THREE.CircleGeometry(12, 64), transparent
      ? new THREE.ShadowMaterial({ opacity: 0.22 })
      : new THREE.MeshStandardMaterial({ color: '#3a3e45', roughness: 0.95 }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground, this.root);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.minDistance = 0.25;
    this.controls.maxDistance = 9;
    this.controls.maxPolarAngle = Math.PI * 0.55;

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
    this.resize();
    this.frame(this.bust);
    const loop = () => { this.raf = requestAnimationFrame(loop); this.tick(); };
    loop();
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.resizeObserver.disconnect();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  private resize() {
    const w = this.host.clientWidth || 1, h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    if (this.shift || this.lift) this.camera.setViewOffset(w, h, -this.shift * w, this.lift * h, w, h);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
  }

  /** Slide the subject sideways on screen (fraction of the width, + = right) without changing the perspective. */
  setShift(f: number, lift = this.lift) {
    this.shift = f;
    this.lift = lift;
    this.resize();
  }

  // ------------------------------------------------------------------------------------------- model

  async load(glb: ArrayBuffer, look: Look) {
    const gltf = await new GLTFLoader().parseAsync(glb, '');
    const model = gltf.scene;
    const first = !this.model;
    if (this.model) this.root.remove(this.model);
    this.model = model;
    this.root.add(model);
    this.bones.clear();
    this.rest.clear();
    this.morphMeshes = [];
    model.traverse((o) => {
      if ((o as THREE.Bone).isBone) this.bones.set(o.name, o as THREE.Bone);
      const mesh = o as THREE.SkinnedMesh;
      if (mesh.isMesh) {
        mesh.frustumCulled = false;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        if (mesh.morphTargetDictionary) this.morphMeshes.push(mesh);
      }
    });
    model.updateMatrixWorld(true);
    for (const [name, b] of this.bones) {
      const parentWorld = new THREE.Quaternion();
      b.parent?.getWorldQuaternion(parentWorld);
      this.rest.set(name, { q: b.quaternion.clone(), p: b.position.clone(), parentWorld, world: b.getWorldQuaternion(new THREE.Quaternion()) });
    }
    // Anny's rest pose is an A pose whose arm angle depends on the shape: drop each arm to ~78 degrees below horizontal
    for (const side of ['L', 'R'] as const) {
      const a = this.bone(`upperarm01.${side}`), b = this.bone(`lowerarm01.${side}`);
      const rest = Math.atan2(b.y - a.y, Math.abs(b.x - a.x));
      this.armDrop[side] = THREE.MathUtils.clamp(rest + 1.36, 0, 1.6);
    }
    this.anchorAccessories();
    await this.setLook(look);
    if (first) this.frame('bust');
  }

  async setLook(look: Look) {
    this.look = { ...this.look, ...look };
    if (!this.model) return;
    const jobs: Promise<void>[] = [];
    this.model.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh || !mesh.material || (mesh.material as THREE.Material).userData?.accessory) return;
      const old = mesh.material as THREE.Material;
      const extras = (old.userData ?? {}) as Record<string, any>;
      jobs.push(this.material(extras, mesh.name).then((m) => {
        mesh.material = m;
        mesh.renderOrder = extras.zDepth ?? 0;
        mesh.castShadow = !['eyelashes', 'eyebrows'].includes(extras.kind);
      }));
    });
    await Promise.all(jobs);
    this.buildAccessories();
  }

  /** The body part or garment under a page point, or null over empty space. */
  pick(clientX: number, clientY: number): Pick | null {
    if (!this.model) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    this.ray.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), this.camera);
    // skinned meshes raycast against their posed vertices (three applies the bones in SkinnedMesh.raycast)
    for (const hit of this.ray.intersectObject(this.root, true)) {
      const m = (hit.object as THREE.Mesh).material as THREE.Material;
      const kind = m?.userData?.accessory ? 'accessory' : m?.userData?.kind;
      if (!kind || ['eyelashes', 'teeth', 'tongue'].includes(kind)) continue;
      const name = hit.object.name;
      // the baker files shoes and hats under "clothes": tell them apart by name
      if (kind === 'clothes') return { kind: /^shoes/.test(name) ? 'shoes' : /fedora|hat/.test(name) ? 'hat' : 'clothes', name };
      return { kind, name };
    }
    return null;
  }

  // ------------------------------------------------------------------------------------------- accessories

  // Earrings and glasses are drawn here, not baked: MakeHuman has no CC0 jewellery. They ride the head bone.
  // rest-pose world points; the accessory group undoes the head's rest transform, so children live in rest world space
  private ears: { L: THREE.Vector3; R: THREE.Vector3 } | null = null;
  private eyes: THREE.Vector3[] = [];

  /** Find the ear lobes on the rest-pose body: the outermost skin points at lobe height beside the head. */
  private anchorAccessories() {
    this.ears = null;
    const head = this.bones.get(key('head'));
    let body: THREE.Mesh | undefined;
    this.model!.traverse((o) => { if ((o as THREE.Mesh).isMesh && ((o as THREE.Mesh).material as THREE.Material).userData?.kind === 'body') body = o as THREE.Mesh; });
    if (!head || !body) return;
    const eyeL = this.bone('eye.L'), eyeR = this.bone('eye.R');
    const eyeY = (eyeL.y + eyeR.y) / 2, eyeZ = (eyeL.z + eyeR.z) / 2, iod = eyeL.distanceTo(eyeR) || 0.064;
    const pos = body.geometry.getAttribute('position');
    const v = new THREE.Vector3();
    const best = { L: new THREE.Vector3(), R: new THREE.Vector3() }, far = { L: 0, R: 0 };
    body.updateMatrixWorld(true);
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(body.matrixWorld);
      // lobes sit about 0.6 IOD under the eyes and ~1.3 IOD behind them
      if (Math.abs(v.y - (eyeY - 0.62 * iod)) > 0.18 * iod || Math.abs(v.z - (eyeZ - 1.35 * iod)) > 0.35 * iod) continue;
      const side = v.x > 0 ? 'L' : 'R';
      if (Math.abs(v.x) > far[side]) { far[side] = Math.abs(v.x); best[side].copy(v); }
    }
    if (!far.L || !far.R) return;
    this.ears = best;
    this.eyes = [eyeL, eyeR];
    this.accessories.matrixAutoUpdate = false;
    this.accessories.matrix.copy(head.matrixWorld).invert();
    head.add(this.accessories);
  }

  private buildAccessories() {
    for (const c of [...this.accessories.children]) {
      this.accessories.remove(c);
      (c as THREE.Mesh).geometry?.dispose();
    }
    if (!this.ears) return;
    const local = (w: THREE.Vector3) => w.clone();
    const metal = (hex = '#d9b56a') => {
      const m = new THREE.MeshPhysicalMaterial({ color: hex, metalness: 1, roughness: 0.22 });
      m.userData = { accessory: true };
      return m;
    };
    const iod = this.eyes[0].distanceTo(this.eyes[1]) || 0.064;
    for (const a of this.look.accessories ?? []) {
      if (a.id === 'hoops' || a.id === 'studs') {
        for (const side of ['L', 'R'] as const) {
          const lobe = this.ears[side].clone().add(new THREE.Vector3(Math.sign(this.ears[side].x) * 0.001, 0, 0));
          const mesh = a.id === 'hoops'
            ? new THREE.Mesh(new THREE.TorusGeometry(0.3 * iod, 0.022 * iod, 12, 48), metal(a.color))
            : new THREE.Mesh(new THREE.SphereGeometry(0.05 * iod, 16, 12), metal(a.color ?? '#f2f2f2'));
          const p = local(lobe);
          if (a.id === 'hoops') { p.y -= 0.28 * iod; mesh.rotation.y = Math.PI / 2; }
          mesh.position.copy(p);
          mesh.castShadow = true;
          this.accessories.add(mesh);
        }
      } else {
        // glasses: two rounded rims in front of the eyes, a bridge and temples back to the ears
        const sun = a.id === 'sunglasses';
        const frame = metal(a.color ?? (sun ? '#1a1a1a' : '#2a2320'));
        frame.metalness = sun ? 0.2 : 0.6;
        frame.roughness = 0.35;
        const g = new THREE.Group();
        const eyes = this.eyes.map((e) => e.clone().add(new THREE.Vector3(0, 0, 0.42 * iod)));
        for (const e of eyes) {
          const rim = new THREE.Mesh(new THREE.TorusGeometry(0.36 * iod, 0.035 * iod, 10, 40), frame);
          rim.scale.set(1.12, 0.86, 1);
          rim.position.copy(local(e));
          g.add(rim);
          const lens = new THREE.Mesh(new THREE.CircleGeometry(0.36 * iod, 40), new THREE.MeshPhysicalMaterial(sun
            ? { color: '#141414', roughness: 0.05, metalness: 0.4, transparent: true, opacity: 0.88 }
            : { color: '#ffffff', roughness: 0, transmission: 1, transparent: true, opacity: 0.12 }));
          lens.material.userData = { accessory: true };
          lens.scale.copy(rim.scale);
          lens.position.copy(rim.position);
          g.add(lens);
        }
        const mid = local(eyes[0].clone().lerp(eyes[1], 0.5));
        const bridge = new THREE.Mesh(new THREE.CylinderGeometry(0.03 * iod, 0.03 * iod, 0.3 * iod, 8), frame);
        bridge.rotation.z = Math.PI / 2;
        bridge.position.copy(mid).add(new THREE.Vector3(0, 0.08 * iod, 0));
        g.add(bridge);
        for (const i of [0, 1]) {
          const side = eyes[i].x > 0 ? 'L' : 'R';
          const from = local(eyes[i].clone().add(new THREE.Vector3(Math.sign(eyes[i].x) * 0.4 * iod, 0.05 * iod, 0)));
          const to = local(this.ears[side].clone().add(new THREE.Vector3(0, 0.55 * iod, 0)));
          const len = from.distanceTo(to);
          const temple = new THREE.Mesh(new THREE.CylinderGeometry(0.025 * iod, 0.025 * iod, len, 6), frame);
          temple.position.copy(from).lerp(to, 0.5);
          temple.quaternion.setFromUnitVectors(Y, to.clone().sub(from).normalize());
          g.add(temple);
        }
        g.traverse((o) => { o.castShadow = true; });
        this.accessories.add(g);
      }
    }
  }

  /** Skin shading: 'base' = Lambert + GGX with the warm wrap hack; 'callisto' adds the Callisto BRDF terms. */
  setSkin(p: Partial<SkinParams>) {
    applySkin(p);
    this.model?.traverse((o) => {
      const m = (o as THREE.Mesh).material as THREE.MeshPhysicalMaterial | undefined;
      if (m?.userData?.kind === 'body' && m.sheen !== (SKIN.sheen ? 0.35 : 0)) { m.sheen = SKIN.sheen ? 0.35 : 0; m.needsUpdate = true; }
    });
  }

  /** Test lighting: the default studio rig, or a single key from the front, the side (90°) or behind (rim). */
  setLighting(preset: 'studio' | 'front' | 'side' | 'back') {
    const { key, fill, rim } = this.lights;
    const studio = preset === 'studio';
    fill.visible = rim.visible = studio;
    this.scene.environmentIntensity = studio ? 0.55 : 0.12;
    key.intensity = studio ? 2.4 : 3.2;
    const head = this.bone('head');
    const at = { studio: [1.6, 3.2, 2.4], front: [0, 0.15, 3], side: [3, 0.15, 0], back: [-0.9, 0.4, -3] }[preset];
    if (studio) key.position.set(at[0], at[1], at[2]);
    else key.position.set(head.x + at[0], head.y + at[1], head.z + at[2]);
    key.target.position.copy(studio ? new THREE.Vector3() : head);
    key.target.updateMatrixWorld();
  }

  private tex(path: string, color = true): Promise<THREE.Texture> {
    const url = path.startsWith('http') || path.startsWith('blob:') || path.startsWith('data:') ? path : `${this.assetBase}/asset/${path}`;
    let p = this.textures.get(url + color);
    if (!p) {
      p = new THREE.TextureLoader().loadAsync(url).then((t) => {
        t.flipY = false;
        t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        t.anisotropy = 8;
        return t;
      });
      this.textures.set(url + color, p);
    }
    return p;
  }

  private async material(extras: Record<string, any>, name = ''): Promise<THREE.Material> {
    const kind = extras.kind as string;
    const tint = (hex?: string) => new THREE.Color(hex ?? '#ffffff');
    if (kind === 'body') {
      const map = this.look.faceTexture ?? this.look.skin;
      const m = new THREE.MeshPhysicalMaterial({
        map: map ? await this.tex(map) : null, color: map ? '#ffffff' : '#c99b84',
        roughness: 0.5, specularIntensity: 0.45, sheen: SKIN.sheen ? 0.35 : 0, sheenRoughness: 0.8, sheenColor: new THREE.Color('#ff9a85'),
      });
      m.userData = extras;
      skinShader(m);
      return m;
    }
    const diffuse = kind === 'eyes' && this.look.eyes ? this.look.eyes : extras.diffuseTexture;
    const cutout = ['hair', 'eyebrows', 'eyelashes'].includes(kind) || extras.transparent;
    const m = new THREE.MeshPhysicalMaterial({
      map: diffuse ? await this.tex(diffuse) : null,
      normalMap: extras.normalmapTexture ? await this.tex(extras.normalmapTexture, false) : null,
      color: kind === 'hair' || kind === 'eyebrows' ? tint(this.look.hairColor) : kind === 'clothes' && !this.look.tints?.[name] ? tint(this.look.clothesColor) : '#ffffff',
      roughness: kind === 'eyes' ? 0.12 : kind === 'teeth' ? 0.3 : kind === 'hair' ? 0.55 : 0.82,
      clearcoat: kind === 'eyes' ? 1 : 0,
      // eyes reflect only off the tear film (coat, 4 %); a second base lobe doubled it past the measured 2.5-5.5 % (Callisto)
      specularIntensity: kind === 'eyes' ? 0 : 1,
      sheen: kind === 'clothes' ? 0.6 : kind === 'hair' ? 0.25 : 0,
      sheenRoughness: 0.7,
      side: cutout ? THREE.DoubleSide : THREE.FrontSide,
      alphaTest: cutout ? 0.35 : kind === 'clothes' ? 0.5 : 0, // some garments cut holes (hems, laces) with alpha
      alphaToCoverage: !!cutout,
      transparent: false,
    });
    m.userData = extras;
    const recolor = kind === 'clothes' ? this.look.tints?.[name] : undefined;
    if (recolor && recolor.toLowerCase() !== '#ffffff') dye(m, recolor);
    return m;
  }

  // ------------------------------------------------------------------------------------------- camera

  private bone(name: string) {
    const b = this.bones.get(key(name));
    return b ? b.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0, 1, 0);
  }

  frame(framing: Framing | (() => void), smooth = false) {
    if (typeof framing === 'function') return framing();
    const target = framing === 'face' ? this.bone('head').add(new THREE.Vector3(0, 0.07, 0.02))
      : framing === 'bust' ? this.bone('neck01').add(new THREE.Vector3(0, -0.05, 0))
      : this.bone('spine03').add(new THREE.Vector3(0, -0.05, 0));
    // full body: people taller than 1.75 m pull the camera back so they still fit; shorter ones stay small
    const tall = Math.max(1, (this.bone('head').y + 0.16) / 1.75);
    const dist = framing === 'face' ? 0.75 : framing === 'bust' ? 1.6 : this.fullDistance * tall;
    // the studio turns the person, not the camera: frame from the front of the stage unless walking
    const facing = this.walking ? this.root.getWorldDirection(new THREE.Vector3()) : new THREE.Vector3(0, 0, 1);
    const pos = target.clone().addScaledVector(facing, dist).add(new THREE.Vector3(0, framing === 'full' ? 0.25 : 0.03, 0));
    if (smooth) { this.camGoal = { target, pos }; return; }
    this.camGoal = null;
    this.controls.target.copy(target);
    this.camera.position.copy(pos);
    this.controls.update();
  }
  private camGoal: { target: THREE.Vector3; pos: THREE.Vector3 } | null = null;

  /** Turn the person on the spot (drag on the body in the studio). */
  turn(rad: number) {
    if (!this.walking) this.root.rotation.y += rad;
  }

  private bust = () => {
    this.controls.target.set(0, 1.45, 0);
    this.camera.position.set(0, 1.5, 1.6);
    this.controls.update();
  };

  /** Show only the meshes whose proxy name is listed (null = everything). Accessories follow `withAccessories`. */
  isolate(names: string[] | null, withAccessories = names === null) {
    this.model?.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const acc = !!(mesh.material as THREE.Material)?.userData?.accessory;
      mesh.visible = acc ? withAccessories : names === null || names.includes(mesh.name);
    });
  }

  /** A transparent PNG of the current frame for thumbnails: no floor, eyes open, after the textures settle. */
  async cutout(): Promise<string> {
    const wasVisible = this.ground.visible;
    this.ground.visible = false;
    this.blinkAt = this.clock.elapsedTime + 100;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const url = this.screenshot();
    this.ground.visible = wasVisible;
    return url;
  }

  /** Frame an arbitrary bone range: used for shoes (feet) and hats (head top). */
  frameBones(from: string, to: string, pad = 1.6) {
    const a = this.bone(from), b = this.bone(to);
    const target = a.clone().lerp(b, 0.5);
    const size = Math.max(a.distanceTo(b), 0.12) * pad;
    const dist = size / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)));
    const facing = this.root.getWorldDirection(new THREE.Vector3());
    this.controls.target.copy(target);
    this.camera.position.copy(target).addScaledVector(facing, dist).add(new THREE.Vector3(0, size * 0.25, 0));
    this.controls.update();
  }

  screenshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }

  setExpression(name: string) {
    this.exprTarget = EXPRESSIONS[name] ?? {};
  }

  // ------------------------------------------------------------------------------------------- animation

  /** Rotate a bone by `angle` around a world axis taken in the parent's rest frame (keeps chains simple). */
  private rot(name: string, axis: THREE.Vector3, angle: number) {
    const b = this.bones.get(key(name)), r = this.rest.get(key(name));
    if (!b || !r || !angle) return;
    const w = new THREE.Quaternion().setFromAxisAngle(axis, angle);
    const delta = r.parentWorld.clone().invert().multiply(w).multiply(r.parentWorld);
    b.quaternion.premultiply(delta);
  }

  private tick() {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    const t = this.clock.elapsedTime;
    if (this.camGoal) {
      const k = Math.min(1, dt * 5);
      this.controls.target.lerp(this.camGoal.target, k);
      this.camera.position.lerp(this.camGoal.pos, k);
      if (this.camera.position.distanceTo(this.camGoal.pos) < 0.002) this.camGoal = null;
    }
    this.controls.update();
    if (this.model) this.animate(t, dt);
    this.renderer.render(this.scene, this.camera);
    this.frames++;
    if (t - this.fpsAt >= 1) { this.fps = this.frames / (t - this.fpsAt); this.frames = 0; this.fpsAt = t; }
  }

  private animate(t: number, dt: number) {
    for (const [name, r] of this.rest) {
      const b = this.bones.get(name)!;
      b.quaternion.copy(r.q);
      b.position.copy(r.p);
    }
    const n = (f: number, s = 0) => Math.sin(t * f + s) * 0.6 + Math.sin(t * f * 2.31 + s * 1.7) * 0.4; // cheap smooth noise

    // walk cycle (blended in and out so the idle and the stride never pop)
    this.walkBlend += ((this.walking ? 1 : 0) - this.walkBlend) * Math.min(1, dt * 3);
    const wb = this.walkBlend;
    if (wb > 0.001) {
      this.walkPhase += dt * Math.PI * 2 * 0.95 * wb;
      const radius = 2.4, speed = 1.15 * wb;
      this.walkAngle += (speed / radius) * dt;
      const before = this.root.position.clone();
      this.root.position.set(Math.sin(this.walkAngle) * radius, 0, Math.cos(this.walkAngle) * radius - radius);
      // the camera travels with the character so it never walks out of frame
      const moved = this.root.position.clone().sub(before);
      this.camera.position.add(moved);
      this.controls.target.add(moved);
      this.root.rotation.y = this.walkAngle + Math.PI / 2;
    }
    const p = this.walkPhase;
    for (const [side, s, ph] of [['L', 1, 0], ['R', -1, Math.PI]] as const) {
      const hip = 0.42 * Math.sin(p + ph);
      const knee = 0.12 + 0.75 * Math.max(0, Math.sin(p + ph + 1.25)) ** 1.5;
      const ankle = -0.18 * Math.sin(p + ph - 0.4);
      this.rot(`upperleg01.${side}`, X, -hip * wb);
      this.rot(`lowerleg01.${side}`, X, knee * wb);
      this.rot(`foot.${side}`, X, ankle * wb);
      // arms: down from the T pose, relaxed elbows, swing opposite to the leg
      this.rot(`upperarm01.${side}`, Z, -s * (this.armDrop[side] + 0.02 * n(0.7, s)));
      this.rot(`upperarm01.${side}`, Y, -s * 0.12);
      this.rot(`upperarm01.${side}`, X, 0.3 * Math.sin(p + ph) * wb - 0.05);
      this.rot(`lowerarm01.${side}`, Y, -s * (0.22 + 0.25 * wb * (0.5 + 0.5 * Math.sin(p + ph))));
      this.rot(`shoulder01.${side}`, Z, s * 0.04 * Math.sin(t * 1.6));
    }
    const rootBone = this.bones.get(key('root'));
    if (rootBone) rootBone.position.y += (-0.025 * Math.abs(Math.cos(p)) * wb) + 0.004 * Math.sin(t * 1.6);
    this.rot('root', Y, 0.07 * Math.sin(p) * wb + 0.015 * n(0.25));
    this.rot('root', Z, 0.012 * n(0.21, 1) * (1 - wb));
    this.rot('spine03', Y, -0.08 * Math.sin(p) * wb);

    // breathing: about 15 breaths a minute in the chest and shoulders
    const breath = Math.sin(t * Math.PI * 2 * 0.25);
    this.rot('spine02', X, -0.018 * breath);
    this.rot('spine04', X, 0.01 * breath);

    // head: follows the camera in idle, faces the path when walking, plus micro motion
    const head = this.bone('head');
    const toCam = this.camera.position.clone().sub(head);
    const facing = this.root.rotation.y;
    let yaw = Math.atan2(toCam.x, toCam.z) - facing;
    yaw = Math.atan2(Math.sin(yaw), Math.cos(yaw));
    const pitch = Math.atan2(toCam.y, Math.hypot(toCam.x, toCam.z));
    const look = 1 - wb;
    const hy = THREE.MathUtils.clamp(yaw, -0.7, 0.7) * look + 0.03 * n(0.31, 2);
    const hp = THREE.MathUtils.clamp(pitch, -0.35, 0.35) * look + 0.02 * n(0.27, 3);
    this.rot('neck02', Y, hy * 0.35);
    this.rot('head', Y, hy * 0.45);
    this.rot('neck02', X, -hp * 0.3);
    this.rot('head', X, -hp * 0.4);
    this.rot('head', Z, 0.02 * n(0.19, 4));

    // eyes: look at the camera with small saccades
    if (t > this.saccadeAt) {
      this.saccade.set((Math.random() - 0.5) * 0.08, (Math.random() - 0.5) * 0.05);
      this.saccadeAt = t + 0.6 + Math.random() * 2.2;
    }
    const eyeYaw = THREE.MathUtils.clamp(yaw - hy * 0.8, -0.45, 0.45) * look + this.saccade.x;
    const eyePitch = THREE.MathUtils.clamp(pitch - hp * 0.7, -0.3, 0.3) * look + this.saccade.y;
    this.gaze.lerp(new THREE.Vector2(eyeYaw, eyePitch), Math.min(1, dt * 25));
    for (const side of ['L', 'R']) {
      this.rot(`eye.${side}`, Y, this.gaze.x);
      this.rot(`eye.${side}`, X, -this.gaze.y);
    }

    // face: expression + lip sync + blinks + lids following the gaze
    for (const k of new Set([...Object.keys(this.expr), ...Object.keys(this.exprTarget)])) {
      this.expr[k] = THREE.MathUtils.lerp(this.expr[k] ?? 0, this.exprTarget[k] ?? 0, Math.min(1, dt * 6));
    }
    const face: Weights = { ...this.expr };
    for (const [k, v] of Object.entries(this.mouth())) face[k] = (face[k] ?? 0) + v;
    if (t > this.blinkAt + 0.16) this.blinkAt = t + 1.8 + Math.random() * 4;
    const b = t > this.blinkAt ? Math.sin(((t - this.blinkAt) / 0.16) * Math.PI) : 0;
    face.eyeBlinkLeft = Math.max(face.eyeBlinkLeft ?? 0, b);
    face.eyeBlinkRight = Math.max(face.eyeBlinkRight ?? 0, b);
    if (this.gaze.y < 0) { face.eyeLookDownLeft = -this.gaze.y * 1.2; face.eyeLookDownRight = -this.gaze.y * 1.2; }
    face.browInnerUp = (face.browInnerUp ?? 0) + 0.06 * Math.max(0, n(0.4, 5));
    for (const mesh of this.morphMeshes) {
      const dict = mesh.morphTargetDictionary!, inf = mesh.morphTargetInfluences!;
      inf.fill(0);
      for (const [k, v] of Object.entries(face)) {
        const i = dict[k];
        if (i !== undefined) inf[i] = THREE.MathUtils.clamp(v, 0, 1);
      }
    }
  }
}
