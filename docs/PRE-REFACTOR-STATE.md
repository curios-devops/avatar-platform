# Estado antes del big refactor — 2026-07-18

Checkpoint para revisitar **después** del refactor de arquitectura. Para cada
hilo: qué quedó hecho, qué estaba en vuelo, y qué decidir al volver (¿continuar,
cancelar o borrar?). Nada perdido: todo lo de abajo está en git (rama `main`,
último commit `c89ca5a` + este doc + el Dockerfile v3).

---

## Hilo A — Visor + animación + tier B (lipsync realista de cabeza)

### Hecho y commiteado
- **Animación procedural** del visor WebGPU (idle/boca/parpadeo) iterada y luego
  **desactivada** por poco realista (`PROCEDURAL_ANIM=false` / `?anim=1` para A/B,
  en `frontend/src/pages/AvatarViewer.tsx`). La boca (lipsync por amplitud) fue lo
  único que se mantuvo activo un tiempo. Commits `0d8d733`, `e14366c`, `fd140b2`,
  `9b98936`, `da6ce7f`, `93ac5de`.
- **Camera clamp** a encuadre retrato (pitch −0.20..0.45 rad, yaw ±0.70) en
  `frontend/src/engine/camera.ts` (commit `0608686`).
- **Líneas negras bajo la barbilla = limitación del dato de LAM, NO del renderer.**
  Verificado renderizando el mismo PLY en el visor de referencia (mkkellogg): sale
  igual. Causa: reconstrucción one-shot (la foto no vio la parte inferior/trasera).
  Tier B **no** lo arregla. El clamp lo oculta.

### Tier B (lipsync real) — investigado y de-risgeado, NO integrado
Plan completo en `docs/tier-b-lipsync-plan.md`. Piezas de LAM:
1. **Rig**: los gaussians de LAM son FLAME (LBS + 51 blendshapes ARKit). Se
   exportan a un ZIP `{name}/skin.glb + offset.ply + animation.glb + vertex_order.json`.
2. **Audio→expresión**: `LAM_Audio2Expression` (audio→ARKit, streaming, PyTorch).
3. **Renderer**: `LAM_WebRender` = npm `gaussian-splat-renderer-for-lam` (WebGL).

**M0 — VALIDADO:** el renderer carga y anima el avatar de muestra; el drive por
frame en vivo funciona (callback `getExpressionData()` → `{arkitName: peso}`).

**M1 — exportador Blender-free PROBADO end-to-end** (`tools/lam_asset_export/`):
`inject_flame_vertices.py` intercambia solo el bloque POSITION del `skin.glb`
plantilla (Python puro, sin Blender). Round-trip sin pérdida; el ZIP reempaquetado
renderiza idéntico en LAM_WebRender. Commit `882e234`.

**M1 restante (NO hecho):** extraer los vértices FLAME del avatar desde el worker
LAM (`flame_model.save_shaped_mesh()`, 20018 vértices en orden de plantilla),
confirmar que nuestro `offset.ply` comparte marco (el `skin.glb` plantilla está en
marco de figura de pie, cabeza y≈1.5–1.8 m), hornear las 3 plantillas en la imagen
del worker, cablear el inyector, subir ZIP a R2, devolver `asset_zip_url`.

**M2 (NO hecho):** montar `LAM_Audio2Expression` (job en el worker LAM o endpoint
propio); `/speak` devuelve `{audio_url, expression_url}`.

**M3 (NO hecho):** swap del visor a `gaussian-splat-renderer-for-lam` cargando el
ZIP; alimentar el stream ARKit sincronizado con el audio; re-tunear cámara.

### Decisiones clave (para juzgar relevancia tras el refactor)
- **Blender es innecesario** (probado): solo hacía FBX→GLB + `vertex_order.json`;
  el rig/pesos/51 blendshapes son plantilla fija, los gaussians son neuronales.
  Quitarlo **no toca el realismo**. (`docs/renderer-architecture-comparison.md`)
- **Spark 2.0 NO es un upgrade de realismo para la cabeza**: tiene LBS experimental
  pero **no blendshapes**, y el lipsync ARKit necesita los 51 correctivos. Solo
  LAM_WebRender los mueve de fábrica. Spark queda para unificar cabeza+cuerpo +
  LoD/escena/VR más adelante. (`docs/renderer-architecture-comparison.md`)
- **Multiview descartado para LAM**: LAM es one-shot; el multiview alimentaba la
  ruta legacy MICA (ya sustituida). Vistas de difusión no son 3D-consistentes →
  ghosting. Para talking-head, el clamp gana.

---

## Hilo B — LHM (avatar de medio/cuerpo completo, tiers 2-3)

### Estado
- **Endpoint** `avatar-lhm-v1` = `vd52f2vtq86buv` (template `w10p5l00xu`), pin CUDA
  12.1–12.6, FlashBoot, idle 300, workers 0-2. **Sigue apuntando a la imagen v1**
  (el deploy a v3 nunca se completó).
- `RUNPOD_LHM_ENDPOINT_ID=vd52f2vtq86buv` en `backend/.env`. Los tiers half/full de
  la UI se activan solos cuando el backend arranca con esa var.
- **Cadena de fixes de imagen** (en `docker/lhm_worker.incremental.Dockerfile`,
  ahora commiteado):
  - v1 (en Hub): base + LHM-500M-HF, pero **le faltaba pytorch3d** (compila desde
    fuente bajo qemu y falla sin abortar).
  - v2 (en Hub): añade **pytorch3d** wheel precompilada. → destapó 2º fallo.
  - v3 (**construida solo LOCAL, 35.3 GB, NO en Hub**): añade el árbol de modelos
    prior (`LHM_prior_model.tar`: VGGHead, SMPL-X, sam2, sapiens… 22 GB) que faltaba.

### BLOQUEO actual: subir v3 a Docker Hub
La capa de priors son **22 GB en un solo blob**. El **proxy interno de Docker
Desktop** (`http.docker.internal:3128`, no configurado por el usuario) corta ese
blob porque no cabe en su ventana de subida (~30 min). `docker push` reintenta
desde cero cada vez. Anoche subí ~13.7/35 GB con **skopeo** (bypass del proxy,
reanudable) pero se cortó al recalentar el Mac.

**Opciones para retomar (elegir al volver):**
1. **Volumen de red RunPod** (recomendado): imagen pequeña sin los 22 GB; RunPod
   baja los pesos directo del OSS (rápido, sin calentar el Mac). Ata workers a un
   datacenter. Patrón correcto de producción.
2. **Reanudar skopeo en frío**: `taskpolicy -b` (E-cores) + `caffeinate`. Reusa
   blobs ya subidos, reempuja el resto. ~1–1.5 h, calor moderado.
3. **Split por subdirectorios**: build multi-stage que parte los priors en capas
   <2-3 GB; `docker push` normal completa cada blob. Sigue subiendo 22 GB desde el
   Mac.
- URL de los pesos: `https://virutalbuy-public.oss-cn-hangzhou.aliyuncs.com/share/aigc3d/data/LHM/LHM_prior_model.tar`
- **Diagnóstico e2e pendiente:** el último fallo real fue `ModuleNotFoundError:
  pytorch3d` (arreglado en v2) → luego `vgg_heads_l.trcd not found` (arreglado en
  v3). v3 aún no probado en RunPod porque no está desplegada.

### Cuota de workers (revertir si hace falta)
Bajé `avatar-mica` (`nwzu1fx25zkin9`) a `workersMax=0` para liberar cuota (era
10/10). Restaurar con un PATCH si MICA se revive.

---

## Estado de infraestructura / local
- **Docker Hub** `devopsavatar/lhm-worker`: tags `v1`, `v2` presentes; `v3` NO.
  Imagen `v3` existe **local** (35.3 GB).
- **RunPod endpoints:** `avatar-lam-v4` (`x1hmke8mv6xouc`, LAM cabeza, operativo),
  `avatar-lhm-v1` (`vd52f2vtq86buv`, en v1), `avatar-mica` (`nwzu1fx25zkin9`,
  workers a 0), `avatar-platform`/`ltx2-video` (legacy).
- **Servidores locales** (pueden seguir vivos): backend :8000, vite app :3000,
  estático :8787, demo LAM_WebRender en vite (scratchpad, puerto propio).
- **Gemini/ElevenLabs/R2** sin cambios; `backend/.env` con todos los secretos
  (gitignored — NUNCA commitear).
- Assets de triage en `.triage/` (git-excluido): PLYs LAM, capturas de la
  investigación (líneas negras, blink, mouth diffs, LAM_WebRender), `reframed_full.jpg`.
- **Clon de LAM_WebRender** en el scratchpad de sesión (no en el repo); el asset de
  muestra `p2-1.zip` y el inyector validado sí están referenciados.

## Docs de referencia en el repo
- `docs/tier-b-lipsync-plan.md` — plan tier B + resultados M0/M1.
- `docs/renderer-architecture-comparison.md` — Spark 2.0 vs LAM_WebRender, rol de Blender.
- `docs/lam-migration.md` — runbook LAM (CUDA pin, ops learnings, deploy LHM).
- `tools/lam_asset_export/` — inyector GLB Blender-free + README.

## Al volver del refactor: qué decidir
1. ¿El talking-head realista (tier B con LAM_WebRender) sigue en el plan, o el
   refactor cambia el enfoque de render/animación?
2. ¿LHM (cuerpo) sigue como tiers 2-3, o se replantea? Si sigue → resolver el
   deploy de v3 (volumen de red recomendado).
3. ¿Se mantiene el visor WebGPU propio (cuerpo/estático) o se unifica todo bajo un
   renderer (p.ej. Spark 2.0 con blendshapes portados)?
4. ¿La animación procedural (desactivada) se borra o se conserva como fallback?
