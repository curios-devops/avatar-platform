# Capibara: Tripo frente a three.js procedural (2026-11-06)

Pregunta: ¿se puede conseguir en three.js, en CPU y sin pagar a Tripo, un capibara animado como el
del vídeo de Summer Plays (low-poly facetado)? Comparación lado a lado en la misma escena y con el
mismo instante del paseo: `.triage/tripo_capy/proc_vs_tripo.jpg` y
`.triage/tripo_capy/capybara_proc_vs_tripo.mp4`.

| | Tripo (API v3) | three.js procedural (`tripo/viewer/capybara.html`) |
|---|---|---|
| Coste | 85 créditos ≈ 0,84 USD (texto→3D 20, low-poly 30, rig 25, paseo 10) | 0 USD |
| Tiempo de generación | ~634 s (134 + 470 + 21 + 9) | **10–17 ms** en CPU, al cargar la página |
| Peso | GLB de 3,37 MB, 1,7 MB de ellos texturas | GLB exportado con el paseo **249 KB**; o **4,5 KB de código** (2 KB comprimido) que lo genera en el cliente |
| Triángulos | 26.832 | **1.580** |
| Animación | rig de 41 huesos con skinning; paseo de 2,6 s (~26 KB) | 11 nodos rígidos; paseo procedural (pares diagonales, bote, cabeceo), horneado a 24 frames para el GLB |
| Aspecto | más detalle en la cara, textura de pelo, postura casi erguida | estilizado y sin textura (color por cara), postura de cuadrúpedo como en el vídeo |
| Generalidad | **cualquier prompt** → personaje | **un personaje por cada programa** |

## Conclusión

- Para un capibara low-poly como el del vídeo, three.js en CPU basta. Cuesta 0 USD, carga en 17
  veces menos polígonos y pesa entre 14 y 1.600 veces menos (según se envíe el GLB o el código).
- Lo que se pierde: detalle y textura. Y sobre todo **escala**: cada criatura nueva hay que
  programarla. La variante a probar es que un LLM escriba ese generador procedural desde un prompt
  (unos céntimos por personaje), con el mismo esqueleto de paseo.
- Tripo sigue teniendo sentido para personajes únicos o detallados. Para web conviene pedir
  `face_limit` de unos 5.000 y texturas WebP.

## Sesión 2: un LLM escribe el capibara desde texto (solo three.js)

**Pregunta:** ¿puede un LLM generar, solo con texto, un capibara de más detalle y con textura, más
cercano a los 26.832 triángulos de Tripo, en sus dos posturas (cuadrúpedo y casi erguido), sin Tripo
ni GPU? Clip: `.triage/tripo_capy/llm/capybara_llm_vs_tripo.mp4`. Lado a lado:
`llm/lineup_quad.jpg` (LLM · Tripo · procedural anterior) y `llm/lineup_upright.jpg` (LLM · Tripo).

**Cómo funciona.**

- **Generación.** `tripo/creature_llm.py` pide a Claude una especificación JSON de unos 5 KB:
  - formas (elipsoides, cápsulas y cajas) cada una asignada a un hueso;
  - zonas de pintura (panza, hocico, pies);
  - piezas rígidas (ojos, dientes, garras);
  - clips formados por osciladores.
- **Construcción.** `tripo/viewer/kit.js` la convierte en el navegador, en CPU:
  - Las formas se funden de forma suave (SDF) y una malla de surface nets las convierte en una sola
    pieza. El tamaño de celda se elige para llegar al objetivo de triángulos.
  - Cada vértice recibe pesos suaves por hueso, en un SkinnedMesh.
  - El pelo es una textura de trazos pintada en un canvas, aplicada en triplanar con un relieve
    ligero. Se descarga 0 bytes.
- **Autocorrección.** El LLM recibe una hoja de 4 vistas × poses de su propio render y corrige la
  especificación.

| | Tripo | Procedural a mano (sesión 1) | **LLM + kit, cuadrúpedo** | **LLM + kit, erguido** |
|---|---|---|---|---|
| Coste | 0,84 USD | 0 | 0,25 USD (generar + 1 corrección, Opus) | 0,46 USD (generar + 2 correcciones, Opus) |
| Tiempo | ~634 s | programarlo a mano | 44 s + 36 s de LLM; **0,44 s** de construcción | 50 + 49 + 50 s de LLM; **0,47 s** de construcción |
| Triángulos | 26.832 | 1.580 | 14.192 (11.952 cuerpo + 2.240 piezas) | 16.372 (14.052 + 2.320) |
| Peso | 3,37 MB GLB | 249 KB GLB | spec de 5,2 KB (**1,2 KB** comprimida) o GLB de 385 KB | spec de 5,9 KB (1,2 KB) o GLB de 458 KB |
| Rig / clips | 41 huesos, walk | 11 nodos rígidos, walk | 11 huesos con skinning, walk | 11 huesos, idle + walk |
| Aspecto | facetado, textura horneada | facetado, color plano | liso y continuo, pelo, panza y hocico pintados | idem |

El kit pesa 22 KB (7,9 KB comprimido) y lo comparten todos los personajes. El GLB exportado lleva
colores de vértice; el pelo triplanar es un shader del kit y no va dentro del GLB.

**Resultados.**

- **Cuadrúpedo.** Se reconoce como capibara a la primera, de una pieza y con el paseo en pares
  diagonales correcto. La corrección le agrandó la cabeza.
- **Erguido.** La primera versión y su autocorrección se leían como una marmota o un castor:
  dientes de castor, cuerpo alto y cabeza corta. Hizo falta una nota humana de dirección de arte
  (`--note`) para llegar a la cabeza grande en bloque y al cuerpo rechoncho. Conclusión: la
  autocorrección arregla errores, pero no corrige sola el *carácter* del personaje.
- **Detalle.** Queda entre el procedural (1,6k triángulos) y Tripo (26,8k), y se regula con
  `detail` (6k–20k). Tripo sigue siendo mejor en el perfil del hocico; el kit gana en pelo y en
  continuidad de la malla.

**Gasto y tope.** Gasto del LLM: **0,70 USD** en 5 llamadas a Opus 5.5. Para pruebas es
demasiado; el tope acordado es 0,25 USD. `creature_llm.py` ahora:

- usa Sonnet 5.5 por defecto (`--model haiku` es unas 40 veces más barato que Opus);
- pide `effort` bajo y limita la salida a 12.000 tokens;
- se niega a llamar si el gasto del día más el peor caso de la llamada supera `--budget`
  (0,25 USD por defecto).

## Sesión 3: el mismo brief con los niveles de OpenAI (solo texto, sin 3D)

`tripo/creature_openai.py` envía el mismo prompt de sistema y el brief del cuadrúpedo a los modelos
de cada nivel, y comprueba la respuesta como texto contra el formato del kit:

- que sea JSON válido y que haya una sola raíz;
- que cada padre, hueso y color referenciado exista;
- que los tipos y los canales sean válidos y los armónicos enteros;
- que la forma más baja quede en y ≈ 0.

No se renderizó nada. Salida: `tripo/specs/openai/`, con el informe en `report_capybara_quad.json`.

| | Claude Opus 5.5 (sesión 2) | **Sol** (`gpt-6.1-sol`) | Luna (`gpt-6-luna`) |
|---|---|---|---|
| Coste | 0,116 USD | **0,034 USD** | 0,0012 USD |
| Tiempo | 43,5 s | 25,2 s | 16,0 s |
| Tokens de salida (razonamiento) | 5.353 | 3.043 (0) | 2.055 (303) |
| Formato | válido, 0 incidencias | válido, 0 incidencias | válido, 0 incidencias |
| Formas / piezas / huesos | 19 / 6 / 11 | 16 / 8 / 10 | 11 / 2 / 6 |
| Pistas del paseo | 13 | 10 | 4 |

Lectura del contenido:

- **Sol** está al nivel de Claude.
  - Cada pata tiene muslo y rodilla, o brazo y muñeca. El paseo va en pares diagonales
    (delantera izquierda con trasera derecha) y las rodillas se doblan en el sentido correcto.
  - La cabeza es un bloque con el hocico oscuro y ancho. Las orejas son pequeñas, las mejillas y
    el interior de las orejas van pintados, hay una línea de boca tallada y 3 dedos por pata.
  - Frente a Claude le faltan el hueso del pecho, el balanceo lateral y el giro de cabeza.
- **Luna** devuelve un formato válido, pero falla en el contenido.
  - Solo anima `front_L` y `back_L`: las patas derechas quedarían quietas y la marcha no es
    diagonal.
  - Las patas no tienen rodilla.
  - La cabeza (0,49 × 0,44 × 0,51 m) es casi tan grande como el cuerpo, y las orejas son grandes
    cuando el brief las pedía pequeñas.
- **Astra** no se ejecutó. Con unos 1.700 tokens de entrada y 3.000–5.000 de salida, a 10/50
  USD por millón, costaría unos 0,17–0,27 USD por personaje: por encima del tope de 0,10 USD de
  esta prueba.

**Recomendación.** Usar Sol para generar personajes: cuesta 3,4 veces menos que Opus y da una
especificación igual de completa. Luna queda para tareas simples. Falta confirmar el resultado de
Sol en 3D. Los precios de OpenAI salen de listados de terceros consultados el 2026-11-06, no de la
página oficial.

## Código

- `tripo/creature_openai.py`: los mismos briefs con Luna, Sol o Astra, con un tope de coste
  `--budget` y una verificación de la especificación como texto.
- `tripo/creature_llm.py`: texto → especificación (`gen`) y render → especificación corregida
  (`refine`, con `--note`). Sus instrucciones de sistema documentan el formato.
  `tripo/specs/*.json` guarda las especificaciones con cada ronda (`.vN.json`).
- `tripo/viewer/kit.js`: especificación → personaje. `tripo/viewer/creature.html`: visor
  (`?spec=`, `clip`, `tripo=1`, `proc=1`, `zoom`), con `window.sheet()`, `exportGlb()` y `still()`.
  `tripo/serve.py`: servidor estático con `POST /save`.
- `tripo/tripo.py`: cliente de la API v3 de Tripo. `tripo/capybara_chain.py`: low-poly v2.0 →
  rig de cuadrúpedo v2.5 → `preset:quadruped:walk`.
- `tripo/viewer/index.html`: visor de GLB rigeados. `tripo/viewer/capybara.html`: capibara
  procedural, con `?tripo=1` para el lado a lado y `window.exportGlb()` para medir.

## Capibara que habla (2026-11-07, comparación de decisiones)

- `tripo/specs/capybara_talk.json`: la capibara erguida con un hueso `jaw` hijo de `head`. El hocico
  acaba en la línea de la boca, debajo va una caja de mandíbula inferior, y hay pintura oscura dentro
  de la boca. Editado a mano, sin coste de LLM.
- `tripo/viewer/creature.html` expone `window.creature` y un gancho `window.afterPose(t)` por frame.
  La grabación mueve `jaw.rotation.x` con los visemas del audio.
- Resultado (`.triage/decide/2b_kit.mp4`): la mandíbula acompaña al habla, pero se nota poco. Es
  nivel marioneta. Para criaturas es la única vía; ver `docs/DECISIONES_TECNOLOGIA.md` en el repo
  principal.
