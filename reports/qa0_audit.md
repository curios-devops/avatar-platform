# QA0 — Auditoría del estado real de la Etapa B

Fecha: 2026-07-22 · Agente: Claude Opus 4.8 (Claude Code)
Alcance: inventariar lo que EXISTE de B1→B4 y B1.5, con paths reales y
evidencia de validación. **No se arregla nada en esta fase** (Principio QA0).

> Nota crítica: la sección "Harness de QA visual" de `docs/nueva_arquitectura.md`
> declara «B1, B1.5, B2, B3, B4 YA implementados». Ese texto proviene de la
> arquitectura ANTERIOR al pivote a Etapa A. **No refleja el estado actual del
> repo.** Esta auditoría corrige esa premisa con evidencia.

## Tabla: fase × artefacto × validación

| Fase | Artefacto esperado (doc) | Existe en repo | Path real | ¿Validado con evidencia? |
|---|---|---|---|---|
| **B1 cabeza** | `head.ply` (LAM) | ✅ Sí | `.triage/lam_head_v7.ply` (20 018 gaussianos, PLY INRIA std), endpoint `avatar-lam-v4` | 🟡 Parcial — live-verified 2026-07-09 en el visor WebGPU (memoria `project_lam_migration`), pero **sin hoja comparativa ni métrica de identidad** |
| **B1 cuerpo** | `body.ply` (LHM) | 🟡 POC | worker `avatar-lhm-v1` (apagado); commit `b890eb4` | ❌ No — sin render 360° validado, sin asset local |
| **B1 meta** | `meta.json` (SMPL-X/FLAME + cámaras) | ❌ No como tal | params dispersos en el worker LAM | ❌ No |
| **B1.5 vistas** | `make_views.py` + `views/` + `views_meta.json` (SV3D/multiview + filtro ArcFace) | 🟡 Distinto | `backend/app/pipeline/multiview_generator.py` (8 vistas Nano Banana/gpt-image) | ❌ No — se hizo para alimentar **MICA**, no el refinamiento LAM que pide la doc; sin filtro de identidad ArcFace |
| **B1.5 reconstruye** | `reconstruct.py` (refina head.ply con vistas) | ❌ No | — | ❌ No |
| **B2 fusión** | `fuse.py` → `avatar_body.spz` + `avatar_head.spz` + `rig.json` | ❌ **No existe** | — | ❌ No — es "el trabajo duro", sin empezar |
| **B3 runtime** | SparkRenderer (spark v2.x) + visemas→FLAME | ❌ No Spark | `frontend/src/engine/webgpu_renderer.ts` (rasterizador propio) + `AvatarViewer.tsx` | 🟡 El visor propio funciona (jaw-anim por amplitud) pero **no es Spark**; idle/blink procedural desactivado por artificial |
| **B4 UX 3D** | botón "Ver en 3D" + órbita/zoom + transición Feed↔3D | 🟡 Parcial | `AvatarViewer.tsx` (órbita/zoom); en Feed el botón 3D está **deshabilitado** (A4) | ❌ No — sin transición Feed↔3D real |
| **QA harness** | `qa/render_sweep.py` `make_sheet.py` `metrics.py` `review.py` `gates.json` | ❌ Falta | solo `qa/gate_a2_lipsync.py` (de Etapa A) | ❌ No |

## Huecos de validación (lista explícita — Gate QA0)

1. **Identidad de la cabeza LAM nunca se midió** — el `head.ply` se aprobó a ojo
   en el visor, sin ArcFace vs. foto original ni barrido de ángulos fijo.
2. **Huecos/oclusiones laterales sin cuantificar** — no sabemos el % de agujeros
   del splat LAM en |yaw|≤45°, que es justo lo que B1.5 debería reducir.
3. **B2 (fusión) inexistente** — no hay costura que medir porque no hay fusión.
4. **Cuerpo LHM sin render validado** — POC apagado, sin evidencia visual.
5. **No hay línea base reproducible** — sin un sweep versionado, cualquier mejora
   futura (B1.5, Spark) es injuzgable ("corrió sin errores").

## Decisión derivada

El primer trabajo de la Etapa B **no** es re-validar (no hay qué re-validar de B2/B3),
sino **construir el harness determinista** (QA1) que hace medible la cabeza LAM que
sí existe, estableciendo la línea base sobre `.triage/lam_head_v7.ply`. Sobre esa
base se juzgarán después B1.5 (refinamiento) y B2 (fusión).

**Renderer del harness:** rasterizador 3DGS **offline en CPU (numpy)** — no Spark
(aún no integrado) ni WebGPU headless (frágil). Determinista, sin GPU, sin browser;
lee los mismos campos del PLY que el visor.
