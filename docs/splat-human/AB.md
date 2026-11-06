# Humano splat: A/B Pruna orbital frente a TripoSplat (2026-11-06)

Pregunta: ¿se puede sacar un humano 3D tipo "Splat Human" (VoxelKei) de una sola imagen, en MB y sin
GPU alquilada? Dos rutas con la misma semilla, una persona inventada en pose A generada con Pruna
p-image. Hoja comparativa: `.triage/splat_ab/AB_sheet.jpg`.

## Resultados

| Ruta | Coste | Tiempo | Peso | Calidad |
|---|---|---|---|---|
| **A. Pruna vídeo + COLMAP + entreno local** | 0,20 USD (p-video) + 0,25 USD (p-video-2) | vídeo 18 s; frames y máscaras 63 s; COLMAP 35 s (CPU) | — | p-video no gira (corta de plano). p-video-2 sí da la vuelta, pero baja los brazos. COLMAP registra 95/96 frames (0,9 px). **El entreno local no salió**: msplat colapsa a negro o a niebla (PSNR 12–16) y Brush lo bloqueó el control de permisos. |
| **B. TripoSplat, imagen entera** | 30 créditos ≈ 0,30 USD | **17 s** | 8,4 MB `.splat` (262.144 gaussianas; ~3–4 MB en SPZ, estimado) | Cuerpo excelente en 360°: espalda y perfiles creíbles, pose A intacta. **Cara mala: ArcFace 0,0** contra la semilla. |
| **B'. TripoSplat, recorte de busto** | 0 (demo HF con token) | 11 s | 17,8 MB PLY | **Cara fotorrealista, ArcFace 0,29–0,35**. La coleta queda como rejilla flotante, la espalda translúcida y la nariz se ensancha a 3/4. |
| Referencia: Twin three.js (Anny) | ~0 | segundos | 4,8 MB, con 52 morphs | ArcFace 0,41, medido contra otra foto real |

Carga en el navegador con Spark 2.4: 134–148 ms para 262.144 gaussianas en el Mac.

## Conclusiones

1. **TripoSplat sustituye a "vídeo orbital + entreno"**: cuesta un tercio, va más de 10 veces más
   rápido y da mejor resultado. El vídeo generado no aguanta quieta la pose (los brazos se mueven),
   y eso rompe cualquier reconstrucción clásica aunque COLMAP encuentre las poses.
2. **La cara necesita su propio splat.** Con la imagen entera, las 262.000 gaussianas se reparten
   por todo el cuerpo y la cara pierde la identidad. Con el busto recortado vuelve a ser
   fotorreal. La receta sería **dos llamadas**: cuerpo y busto, más una fusión. `worker/b2/fuse.py`
   (Etapa B) ya hace esa costura cabeza-cuerpo.
3. **Peso**: ~4–8 MB por persona en SPZ. Sigue siendo MB, en línea con VoxelKei.
4. Pendiente y sin probar: animación (rig con Anny + SplatSkinning), fusión cuerpo+busto y bocas
   abiertas.

## Capibara (rama `exp/tripo-chars`)

Tripo texto→3D v3.1 con textura: 20 créditos ≈ 0,20 USD, 134 s. Resultado: buen low-poly
estilizado, pero un GLB de **42,6 MB con 1,42 M triángulos**. Para web hace falta "Smart Low-poly"
(+10 créditos, ~20.000 caras) o decimar en local. El rig-check (gratis) dice `riggable: true,
rig_type: quadruped`. Rig (25 créditos) y animaciones (10 cada una) no se hicieron, para no pasar
del tope de 1 USD.

## Gasto

Pruna ≈ 0,455 USD (p-image ~0,005 + p-video 0,20 + p-video-2 0,25) + Tripo 50 créditos
(≈ 0,49 USD) = **≈ 0,95 USD**. La demo de TripoSplat en Hugging Face no costó nada.

## Sesión 2: fusión cuerpo + busto y capibara animado

Hoja: `.triage/splat_ab/AB_sheet_v2.jpg`.

**Fusión** (`splat/fuse_bust.py`, numpy + scipy, 5 s en CPU, 0 USD):

- **Alineación.** Las dos nubes se ponen con +Y arriba y la cara hacia -Z. El busto se prueba en
  los 4 giros posibles; la escala sale de la altura entre la coronilla y el cuello y se afina con
  ICP con escala. Gana el giro de 90° (residuo 0,0019).
- **Composición.** La mitad delantera de la cabeza sale del busto y la nuca y la coleta, del
  cuerpo. Ambas mitades se solapan y se funden en el plano central de la cabeza, con una rampa de
  0,3 r. El color del busto se acerca al del cuello del cuerpo.
- **Resultado.** 303.163 gaussianas en 9,7 MB `.splat`. Carga en 0,7 s. Cuerpo limpio en 360°,
  cara fotorrealista de frente, a 3/4 y de perfil, nuca con coleta. **ArcFace 0,30–0,35**, también
  en el plano de cuerpo entero (0,346); el cuerpo de TripoSplat sin fusionar daba 0,0.
- **Defecto que queda.** Un ligero salto de tono entre la mandíbula y el cuello.
- **Dos fallos encontrados por el camino:**
  1. Una matriz→cuaternión ingenua degenera con medios giros (w = 0) y anula todas las
     orientaciones: las superficies salen en rejilla. La solución es el método de Shepperd, que
     ahora usan `fuse_bust.py` y `normalize.py`.
  2. Por encima de 2^18 = 262.144 gaussianas, Spark activa el LOD, que a esta distancia mezcla
     gaussianas y lava la espalda. El visor lo desactiva salvo con `?lod=1`. En producción hay que
     pasar `lod: false` o podar a ≤ 262.144.

**Capibara** (`tripo/capybara_chain.py`, rama `exp/tripo-chars`):

| Paso | Créditos | Tiempo | Resultado |
|---|---|---|---|
| Texto→3D v3.1 (sesión 1) | 20 | 134 s | 1,42 M tris, 42,6 MB |
| Low-poly v2.0 con textura horneada (v1.0 no hornea) | 30 | 470 s | 26.832 tris, 2,8 MB |
| Rig de cuadrúpedo v2.5 | 25 | 21 s | 41 huesos, 3,34 MB |
| Paseo `preset:quadruped:walk` | 10 | 9 s | clip de 2,6 s, **3,37 MB en total** (la animación son ~26 KB) |

Carga en three.js con `GLTFLoader` en 54 ms y el paseo se reproduce con `AnimationMixer`
(`tripo/viewer/`). De los 3,37 MB, 1,7 MB son texturas: pasarlas a WebP lo reduciría bastante.

**Gasto de la sesión 2:** 65 créditos de Tripo ≈ 0,64 USD (quedan 85 créditos).

## Sesión 3: el splat humano animado con el esqueleto de Anny

`splat/viewer/animate.html` (Spark `SplatSkinning` + Anny `human.glb`, todo en el navegador, 0 USD).
Clip: `.triage/splat_ab/fused/splat_human_anim.mp4`.

1. **Alineación.** Anny se gira para mirar a -z y se escala por eje: la altura da y, los muslos la
   anchura y una columna central del pecho la profundidad (en pose A los brazos inflan cualquier
   franja de la cintura). Los brazos de Anny se orientan hacia las manos del splat (giro de ~15°).
2. **Pesos.** Cada gaussiana mezcla los huesos de los 4 vértices de Anny más cercanos, ponderados
   por la inversa de la distancia, con una rejilla de claves numéricas. Tarda 7 s para 303.000
   gaussianas (con claves de texto eran 62 s).
3. **Mandíbula.** Anny no tiene hueso de mandíbula, solo el morph ARKit `jawOpen`. Un hueso virtual
   ajusta por mínimos cuadrados una rotación a esos desplazamientos: 18,4° para `jawOpen` = 1, con
   la bisagra en el eje x del mundo. El peso de mandíbula de cada gaussiana es cuánto mueve
   `jawOpen` su vértice, con un smoothstep casi binario para que los labios se separen.
4. **Fallo de Spark encontrado.** Su shader aplica `p' = R·p + t`, pero `setBoneQuatPos` construye
   `R = rest⁻¹·q` y `t = pos − pos_rest`, que solo vale para huesos que giran sobre el origen. Por
   eso el reposo va en la identidad y cada hueso recibe su transformación completa
   `T = O⁻¹ · M_ahora · M_rest⁻¹ · O`.
5. **Resultado.** Reposo con respiración, giro e inclinación de cabeza, saludo (codo en x+) y
   mandíbula, sin desgarros. **33 fps** en Chrome en el M2 Pro, con el skinning de 303.000
   gaussianas en cada frame.
6. **Falta:** el interior de la boca. Al abrirla se ve piel, no una cavidad oscura. Los dientes de
   Anny y la cavidad (`?mouth=1`) aún salen mal colocados. También queda conectar los visemas reales
   (hoy la mandíbula sigue una onda) y medir en el móvil.

## Código

- `splat/pruna.py`: imagen y vídeo con Pruna, con `PRUNA_K_API_KEY` y respaldo `PRUNA_API_KEY`.
- `splat/tripo.py`: cliente de la API v3 de Tripo (endpoint global `openapi.tripo3d.ai`; `.com` es China).
- `splat/recon.py`: frames → máscaras (fondo local + GrabCut + sombra) → COLMAP (`SIMPLE_PINHOLE`;
  con fx≠fy msplat no encaja las vistas) → envolvente visual → msplat.
- `splat/normalize.py`, `splat/score.py` (ArcFace) y `splat/viewer/` (Spark; `lib/` y `data/` van
  en `.gitignore`).
