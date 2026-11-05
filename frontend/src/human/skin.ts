// Skin shading for the three.js human. Default ('base'): three.js Lambert + GGX, a warm indirect lift standing in for
// subsurface scattering, and a peach sheen. Optional ('callisto'): the Callisto BRDF terms below.
// A/B on 2026-11-05 (docs/three-human/CALLISTO.md): the terms reproduce the baseline exactly at their defaults and cost
// nothing measurable, but at no setting did they make the face read more real (ArcFace and CLIP unchanged; strong values
// wash out front light and leave a red seam at the terminator). Kept off until there are reference photos to fit against.
import * as THREE from 'three';

export type SkinParams = {
  model: 'base' | 'callisto';
  warm: boolean; // warm indirect lift, a cheap stand-in for subsurface scattering
  sheen: boolean;
  fresnel: number; fresnelTint: string; fresnelFalloff: number;
  retro: number; retroTint: string; retroFalloff: number;
  terminator: number; terminatorTint: string; terminatorLength: number;
  specFalloff: number; dualScale: number; dualOpacity: number;
};

export const SKIN: SkinParams = {
  model: 'base', warm: true, sheen: true,
  fresnel: 1, fresnelTint: '#ffffff', fresnelFalloff: 0.75,
  retro: 1, retroTint: '#ffffff', retroFalloff: 0.75,
  terminator: 0, terminatorTint: '#ffffff', terminatorLength: 0.5,
  specFalloff: 0.5, dualScale: 2, dualOpacity: 0,
};

const SKIN_UNIFORMS = {
  uCallisto: { value: 0 }, uWarm: { value: 1 },
  uRhoF: { value: new THREE.Color(1, 1, 1) }, uRhoR: { value: new THREE.Color(1, 1, 1) },
  uFalloff: { value: new THREE.Vector4(0.75, 0.75, 0.75, 0.75) },
  uTerm: { value: new THREE.Vector2(0, 0.5) }, uTermTint: { value: new THREE.Color(1, 1, 1) },
  uSpec: { value: new THREE.Vector3(0.5, 2, 0) },
};

// Callisto BRDF (Jimenez & Petersen, "The Rendering of The Callisto Protocol", SIGGRAPH 2023 Advances, slides 85, 90, 95):
//   Lo = (c1(θd,θh)·f_lambert + f_ggx) · c2(θi) · Li·cosθi
//   c1 = lerp(1, ρf, αf) · lerp(1, ρr, αr)            diffuse Fresnel × retroreflection
//   αf = h(θd, r(nf), θh, r(mf)), αr = h(θh, r(nr), θd, r(mr)), h(θ,n,φ,m) = (1−cosθ)^5n · cosφ^5m, r(x) = 2(1−x)
//   c2 = lerp(1, smoothstep(0, αs·p, cosθi), αs·o),    αs = (1−(1−cosθd)³)(1−(1−cosθh)³)   smooth terminator
//   F  = f0 + sat(2 − r(ns))·(f90 − f0)·(1 − cosθvh)^(5·r(ns))                              specular Fresnel falloff
// plus their dual specular: a second GGX lobe with roughness × scale, mixed by opacity. Defaults equal Lambert + GGX.
const CALLISTO_GLSL = /* glsl */ `
uniform float uCallisto;
uniform vec3 uRhoF;
uniform vec3 uRhoR;
uniform vec4 uFalloff;
uniform vec2 uTerm;
uniform vec3 uTermTint;
uniform vec3 uSpec;
float cR( float x ) { return max( 2.0 * ( 1.0 - x ), 1e-3 ); }
vec3 callistoGGX( vec3 L, vec3 V, vec3 N, PhysicalMaterial material, float roughness ) {
  float alpha = pow2( roughness );
  vec3 H = normalize( L + V );
  float dotNL = saturate( dot( N, L ) ), dotNV = saturate( dot( N, V ) ), dotNH = saturate( dot( N, H ) ), dotVH = saturate( dot( V, H ) );
  float r = cR( uSpec.x );
  vec3 F = material.specularColor + saturate( 2.0 - r ) * ( material.specularF90 - material.specularColor ) * pow( 1.0 - dotVH, 5.0 * r );
  return F * V_GGX_SmithCorrelated( alpha, dotNL, dotNV ) * D_GGX( alpha, dotNH );
}
`;

const CALLISTO_DIRECT = /* glsl */ `
  if ( uCallisto > 0.5 ) {
    vec3 L = directLight.direction;
    vec3 H = normalize( L + geometryViewDir );
    float NoH = saturate( dot( geometryNormal, H ) ), LoH = saturate( dot( L, H ) );
    float af = pow( 1.0 - LoH, 5.0 * cR( uFalloff.x ) ) * pow( NoH, 5.0 * cR( uFalloff.y ) );
    float ar = pow( 1.0 - NoH, 5.0 * cR( uFalloff.z ) ) * pow( LoH, 5.0 * cR( uFalloff.w ) );
    vec3 c1 = mix( vec3( 1.0 ), uRhoF, af ) * mix( vec3( 1.0 ), uRhoR, ar );
    float as = ( 1.0 - pow3( 1.0 - LoH ) ) * ( 1.0 - pow3( 1.0 - NoH ) );
    vec3 c2 = mix( vec3( 1.0 ), vec3( smoothstep( 0.0, max( as * uTerm.y, 1e-4 ), dotNL ) ), as * uTerm.x * uTermTint );
    vec3 spec = mix( callistoGGX( L, geometryViewDir, geometryNormal, material, material.roughness ),
                     callistoGGX( L, geometryViewDir, geometryNormal, material, min( material.roughness * uSpec.y, 1.0 ) ), uSpec.z );
    reflectedLight.directSpecular += irradiance * spec * c2;
    reflectedLight.directDiffuse += irradiance * c1 * c2 * BRDF_Lambert( material.diffuseColor );
  } else {
    reflectedLight.directSpecular += irradiance * BRDF_GGX_Multiscatter( directLight.direction, geometryViewDir, geometryNormal, material );
    reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
  }
`;

// the two lines of RE_Direct_Physical (three r181) that the Callisto terms wrap; the build strips blank lines
const DIRECT_LINES = /reflectedLight\.directSpecular \+= irradiance \* BRDF_GGX_Multiscatter\([^;]*\);\s*reflectedLight\.directDiffuse \+= irradiance \* BRDF_Lambert\( material\.diffuseColor \);/;
const SKIN_CHUNK = (() => {
  const chunk = THREE.ShaderChunk.lights_physical_pars_fragment;
  if (!DIRECT_LINES.test(chunk) || !chunk.includes('void RE_Direct_Physical')) {
    console.warn('[human] three.js changed RE_Direct_Physical: Callisto skin disabled');
    return chunk;
  }
  // the helpers need PhysicalMaterial and the GGX terms, all declared earlier in the same chunk
  return chunk.replace(DIRECT_LINES, CALLISTO_DIRECT).replace('void RE_Direct_Physical', `${CALLISTO_GLSL}\nvoid RE_Direct_Physical`);
})();

export function skinShader(m: THREE.MeshPhysicalMaterial) {
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, SKIN_UNIFORMS);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <lights_physical_pars_fragment>', SKIN_CHUNK)
      .replace('#include <lights_fragment_end>', `#include <lights_fragment_end>
      reflectedLight.indirectDiffuse += uWarm * diffuseColor.rgb * vec3(0.10, 0.035, 0.02);`)
      .replace('void main() {', 'uniform float uWarm;\nvoid main() {');
  };
}

/** Updates the shared skin uniforms; every skin material reads them, so no recompile is needed. */
export function applySkin(p: Partial<SkinParams>) {
  Object.assign(SKIN, p);
  const u = SKIN_UNIFORMS;
  u.uCallisto.value = SKIN.model === 'callisto' ? 1 : 0;
  u.uWarm.value = SKIN.warm ? 1 : 0;
  u.uRhoF.value.set(SKIN.fresnelTint).multiplyScalar(SKIN.fresnel);
  u.uRhoR.value.set(SKIN.retroTint).multiplyScalar(SKIN.retro);
  u.uFalloff.value.set(SKIN.fresnelFalloff, 0.75, SKIN.retroFalloff, 0.75);
  u.uTerm.value.set(SKIN.terminator, SKIN.terminatorLength);
  u.uTermTint.value.set(SKIN.terminatorTint);
  u.uSpec.value.set(SKIN.specFalloff, SKIN.dualScale, SKIN.dualOpacity);
}
