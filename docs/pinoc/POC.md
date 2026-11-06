# PoC: personajes de PINOC animados en la web (2026-11-06)

**Objetivo.** Recuperar programáticamente un personaje que ya exista en PINOC (Viggle) y animarlo en
nuestra página con el motor web oficial. Es un primer paso hacia los avatares conversacionales de
MEYA.

**Estado (cerrado).** Un personaje de PINOC se recupera por el MCP y se anima en nuestra página con
el motor oficial: reposo, caminar, saludo en capa, asentir y cabeza en tiempo real. No había ningún
personaje previo en la cuenta, así que se generó uno con autorización (6 créditos). Ver
[Resultado](#resultado-personaje-de-pinoc-animado-en-nuestra-web-2026-11-06).

## Primer bloqueo: falta la credencial

- **API REST.** Pide `Authorization: Bearer <api key>`. La clave se crea en
  https://portal.viggle.ai/keys. En `backend/.env` no hay ninguna clave de Viggle, solo un
  comentario ("3D spalts VIGLE PINOCLE").
  - Verificado en vivo: `GET https://apis.viggle.ai/v1/characters` sin clave responde `401 UNAUTHENTICATED`.
  - `GET /v1/motion-templates` también responde 401, no 404: la ruta existe.
- **MCP.** Está en `https://pinoc.mcp.viggle.ai/mcp` y usa OAuth, sin clave.
  - Verificado en vivo: un `initialize` sin token responde `401` con
    `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource"`.
  - Ese metadata indica el servidor de autorización `https://auth.viggle.ai` y los scopes
    `pinoc:read` y `pinoc:generate`.
  - El inicio de sesión es con Google en el navegador, así que requiere una persona.
- **Assets públicos.** No existe ningún `.vsplat` público de muestra. Los paquetes npm no traen
  assets, y el README remite a https://viggle.ai/pinoc/app/.

## Con la clave `VIGLE_K_API_KEY` (verificado en vivo, 2026-11-06)

Se probó a través de `pinoc/server.py`, con llamadas GET gratuitas.

| Llamada | Resultado |
|---|---|
| `GET /v1/credits` | 200 · `{"balance": 100}`, el saldo inicial de una cuenta nueva |
| `GET /v1/characters` | 200 · **0 personajes** |
| `GET /v1/motions` | 200 · **0 movimientos** |
| `GET /v1/motion-templates` | **404** `page not found` (sin clave daba 401) |

**Segundo bloqueo.** Los personajes creados en la web de PINOC no aparecen bajo la clave de API. La
clave es de un proyecto y la documentación no explica cómo se relaciona con los assets de la app.
Además, el catálogo de plantillas que se cita en `POST /motions/import` no existe en producción.
Por REST no hay nada existente que reutilizar.

**Alternativas, de menor a mayor coste:**

1. **MCP de PINOC** con el inicio de sesión de Google y el scope `pinoc:read`. Su página promete
   "see your own assets" y una biblioteca de presets gratuita. Es la única vía documentada hacia los
   personajes que ya existen en la app. Requiere que una persona inicie sesión.
2. **Crear por API.** Un personaje `type=vsplat` (30 créditos, o 25 con `enhance=false`) más un
   movimiento por texto (10 créditos). Caben en los 100 créditos gratuitos (≈ 0,40 USD de valor),
   pero hay que autorizarlo.

## Por el MCP (verificado en vivo, 2026-11-06)

**Conexión.** `pinoc/mcp_client.py` implementa el flujo OAuth 2.1 que anuncia el servidor, con PKCE,
registro dinámico del cliente, redirección a un puerto local y el MCP como `resource`.

- Marcelo inició sesión con Google y concedió solo `pinoc:read`. El token queda en
  `pinoc/.mcp_token.json` (modo 600, fuera de git) y no se imprime nunca.
- `auth.viggle.ai` responde **403 al User-Agent por defecto de Python**. Hubo que enviar uno
  propio, y quizá por eso falló `/mcp`.

**Herramientas.** El servidor `pinoc` expone 18. Solo se usaron las gratuitas:

| Herramienta | Resultado |
|---|---|
| `get_credit_balance` | 60 créditos gratuitos del plan de PINOC (distinto de los 100 de la API) |
| `list_my_characters` | **0 personajes**, `hasMore: false` |
| `search_library` (personajes) | 0 |
| `list_my_motions` | 0 |
| `list_motion_library` | 108 clips gratuitos (54 nombres, cada uno dos veces) |
| `take_library_motions` por id | 4 clips, `creditsCharged: 0` (por nombre fallan: hay duplicados) |
| `get_asset` con `format: splat-skeleton-glb` | URL firmada y `status: ready` |

**Clips descargados en `pinoc/assets/`** (rig MetaHuman de 441 huesos con cara, sin malla). El motor
oficial los carga en el navegador:

| Clip | Id | Duración | Peso | Carga |
|---|---|---|---|---|
| Standing Idle | 1cbf45b5-… | 5,0 s · 151 frames · 30 fps | 835 KB | 14 ms |
| Walking | 32d71c7f-… | 10,3 s | 1,39 MB | 12 ms |
| Wave Hello | fcd078a0-… | 1,7 s | 480 KB | 7 ms |
| Nod Yes | 1fc82778-… | 3,7 s | 694 KB | 7 ms |

**Bloqueo definitivo: la cuenta no tiene ningún personaje.** Ni por API ni por MCP hay un
personaje existente que reutilizar. Las animaciones gratuitas ya están, pero sin personaje no hay
nada que animar.

**Alternativa directa.** `generate_character` cuesta **6 créditos** de los 60 gratuitos, a partir de
un texto o de una foto; con `refine` son 10. Requiere:

- autorización explícita;
- una nueva sesión OAuth con el scope `pinoc:generate`;
- una foto de una persona inventada (por ejemplo, la semilla generada con Pruna para el splat
  humano) o un texto. Nunca una persona real sin su consentimiento.

## Resultado: personaje de PINOC animado en nuestra web (2026-11-06)

**Personaje.** Con la autorización de Marcelo (6 créditos), se hizo una nueva sesión OAuth con
`pinoc:read pinoc:generate` y se generó el personaje.

- **Origen.** `prepare_upload` + PUT de `.triage/splat_ab/seed.jpg`, la persona inventada en pose A.
  Después, `generate_character` con `refine: false`.
- **Resultado.** Asset `265bec00-56ea-4487-b8fb-f29dae4e8346` ("Asian Woman"), listo en unos 50 s.
  `creditsCharged: 6` (quedan 54).
- **Niveles descargados con `get_asset`** (formato VIGGCHAR v1):

  | Nivel | Gaussianas | Peso |
  |---|---|---|
  | `high` | 48.000 | 1,30 MB |
  | `balanced` | 32.000 | 0,87 MB |
  | `performance` | 16.000 | 0,44 MB |
  | `full` | 131.072 | 3,55 MB |

**Demo:** `http://127.0.0.1:8770/?char=local:asian_woman_high.vsplat&idle=local:standing_idle.glb&move=local:walking.glb&auto=1`,
con `&backend=webgpu` opcional. Evidencias en `.triage/pinoc/`:

| Archivo | Qué muestra |
|---|---|
| `01_idle.png` | reposo, de frente |
| `02_walk.png` | caminar, a mitad de paso |
| `03_wave_layer_head30.png` | saludo en capa `upperBody` sobre el reposo, con la cabeza girada 30° por `poseModifier` |
| `04_jaw_axes.jpg` | `FACIAL_C_Jaw` girado ±25° en x, y y z |
| `pinoc_demo.mp4` | 17 s: reposo → caminar → saludo y mirada → asentir → reposo (grabado del canvas) |
| `05_video_frames.jpg` | tira de fotogramas del vídeo |
| `06_webgpu.png` | caminar con el backend WebGPU |

### Medido

| | WebGL2 | WebGPU |
|---|---|---|
| Carga del `.vsplat` high | 46–49 ms | 46 ms |
| Carga de los clips | 7–14 ms cada uno | igual |
| Splats tras la poda por defecto | 42.628 | 42.628 |
| CPU por frame: pose + skinning | 2,23 ms | 0,16 ms |
| Frame completo, incluida la GPU (2200×1600, M2 Pro) | 2,63 ms | 1,25 ms |
| fps en la ventana | 30, limitado por la ventana de pruebas; el coste da margen para más de 300 | 30, igual |

- **Errores.** Ninguno en carga, reproducción, crossfade, capas ni cambio de backend.

### Evaluación

- **Realismo.** Alto. Es fotorrealista (cara, ropa y zapatillas) y fiel a la foto semilla. Supera a
  nuestro splat TripoSplat fusionado, que además pesa 9,7 MB.
- **Estabilidad.** Caminar, saludar y girar la cabeza no producen desgarros ni gaussianas sueltas,
  y el cuello aguanta el giro.
- **Problemas encontrados.**
  1. **Orientación.** Con `SplatEngine.shared`, el personaje queda mirando a −Z. La demo lo gira
     180° (`?flip=0` lo desactiva).
  2. **El clip de la biblioteca "Nod Yes" (`1fc82778…`) gira el cuerpo unos 110°.** La pelvis
     queda a −24° frente a los 85–90° de los demás clips, así que el personaje sale de perfil. Su
     duplicado (`94a692a9…`) se puede tomar pero `get_asset` responde `not_found`. Los clips de la
     biblioteca no vienen normalizados en orientación: hay que revisar cada uno o compensarlo al
     reproducirlo.
  3. **El hueso `head` de MetaHuman** tiene x hacia delante, y lateral y z hacia abajo, así que el
     giro horizontal es una rotación sobre la z local.
  4. Con `WebGPURenderer` y `LinearSRGBColorSpace` (lo que aconseja el README para los splats), los
     materiales normales de three.js salen más oscuros (en la demo, el fondo y el suelo).
- **Control en tiempo real.** Verificado:
  - `play` y `crossFadeTo` para encadenar reposo, caminar y asentir;
  - `playLayer` por región del cuerpo, para mezclar el saludo con el reposo;
  - `poseModifier` para mover cualquier hueso en cada frame (mirada y cabeza).
- **Cara y lip-sync.**
  - El personaje se generó por el MCP con 441 huesos (355 `FACIAL_*`) sin pedirlo; no hay
    parámetro `joint_set` como en la API REST.
  - Girar `FACIAL_C_Jaw` en z baja la mandíbula y la piel la sigue sin romperse.
  - **Pero la boca no se abre de verdad.** El splat se capturó con la boca cerrada y no hay ni
    dientes ni cavidad, así que solo se estiran los labios.
  - No hay API de visemas, blendshapes ni parpadeo. Habría que moverlos uno a uno entre los unos
    100 huesos de labios y los de párpados, sin una referencia de cómo mapear cada visema.
- **Coste:** 6 créditos de PINOC, de los 60 gratuitos. 0 USD. La API REST no se usó para generar
  (sigue con 100 créditos).

### Recomendación para MEYA

1. **Sí para cuerpo y presencia.** Personaje de PINOC + `@viggle/splat-engine-three` en WebGPU,
   con WebGL como respaldo.
   - Gana en calidad, peso (0,4–1,3 MB) y coste por frame a nuestras rutas de splat.
   - Los clips gratuitos de la biblioteca cubren reposo, gestos y caminar.
   - El acceso a assets debe ir en el backend, como hace `server.py`: credenciales y URLs
     firmadas nunca en el navegador.
2. **No todavía para la conversación cara a cara.** Sin boca abierta ni visemas no hay lip-sync
   creíble.
   - Opciones, de menor a mayor esfuerzo:
     - (a) planos medios o lejanos, con solo mandíbula y cabeza;
     - (b) pedir a Viggle personajes con la boca entreabierta o clips faciales MetaHuman;
     - (c) un híbrido: la cara con nuestro Twin three.js o el vídeo de Etapa A, y el cuerpo con
       el splat.
3. **Antes de integrar.**
   - Normalizar la orientación de cada clip, por el caso de "Nod Yes".
   - Fijar el acceso: MCP para un uso con persona, y la API REST con
     `characters/{id}/export` cuando los personajes estén en el proyecto de la clave (hoy la API
     no ve los de la app).

## Comparación para la cara que habla (2026-11-06)

Hoja: `.triage/pinoc/09_compare_opt2_vs_opt3.jpg`. Vídeo del híbrido: `.triage/pinoc/opt3_hybrid_talk.mp4`.

- **Opción 1: planos medios con solo mandíbula.** Se descarta: es la peor. El splat no tiene boca
  por dentro (`04_jaw_axes.jpg`).
- **Opción 2: pedir a Viggle la boca abierta o clips faciales.** Probada con 10 créditos.
  - **Personaje.** Se generó por texto un personaje "con los labios entreabiertos y los dientes
    visibles". La imagen fuente sí los tiene (`assets/open_mouth_source.jpg`), pero **PINOC
    normaliza el personaje a boca cerrada**. Al abrir `FACIAL_C_Jaw` se estiran y difuminan los
    labios, sin dientes ni cavidad.
  - **Clips faciales.** Se generó un movimiento de 4 s, "talking expressively: lips and jaw…, blinks"
    (4 muestras). **Ninguna mueve un solo hueso facial** respecto a la cabeza: 0 mm en mandíbula,
    labios y párpados. PINOC anima el cuerpo y la cabeza, no la cara.
  - **Veredicto.** Es el máximo realismo en reposo, pero **no puede hablar**.
- **Opción 3: híbrido con la cara del Twin** (`web/hybrid.html`).
  - **Montaje.**
    - El cuerpo, el pelo y las orejas son el splat de PINOC.
    - La cara es el Twin: `POST /twin/fit` local, gratis, 104 s, sobre `seed_head.jpg`, la misma
      persona, más un bake de 3 MB.
    - Se recorta la cara a la zona frontal (7.574 triángulos) y se encaja por los ojos (escala
      1,084).
    - Sigue cada frame al hueso `head` del splat.
    - La cara del splat se funde con un hook de color y la del Twin con `alphaHash`, en una banda
      de 0,35 veces la distancia entre los ojos.
  - **Lo que gana.** **La boca se abre de verdad**: dientes, vocales redondas y parpadeo, con los
    51 morphs ARKit. Queda lista para conectar a los visemas de la voz.
  - **Lo que pierde.** Fotorrealismo en la cara:
    - piel CG más lisa;
    - iris rojizo y grande (el ojo de MakeHuman);
    - costura visible en la frente (punteado del `alphaHash`) y en la barbilla.
  - **Veredicto.** Habla, pero se ve como un personaje CG sobre un cuerpo foto. Resulta extraño de
    cerca.

**Conclusión.**

- **Reposo.** La opción 2 (splat puro) es la más realista.
- **Hablar.** Solo la opción 3 articula, a costa del fotorrealismo de la cara.
- **Siguiente prueba si se quiere fotorrealismo hablando.** La variante de vídeo de la opción 3:
  splat para el cuerpo y el plano general, y el vídeo de Etapa A (Pruna Pro, unos 0,04 USD/s)
  para los primeros planos con lip-sync. No se probó, por coste.

**Gasto de la comparación.** 10 créditos de PINOC (quedan 44). El Twin es local y gratis. 0 USD.

## Operaciones documentadas

Base: `https://apis.viggle.ai/v1`.

| Para qué | Operación | Coste |
|---|---|---|
| Listar personajes | `GET /characters` (los 100 más recientes, sin paginación) | gratis |
| Metadatos | `GET /characters/{id}` (`status`, `type`, `vsplat.status`, `capabilities`) | gratis |
| Archivo `.vsplat` | `GET /characters/{id}/export?download_type=vsplat` → `vsplat_url` firmada 1 h | gratis |
| Listar movimientos propios | `GET /motions` | gratis |
| GLB de un movimiento | `GET /motions/{id}/export?download_type=glb\|fbx` → `metahuman_url` (441 huesos, con cara), `metahuman_body_url` (86), `mixamo_url` (50) | gratis |
| Catálogo oficial | `GET /motion-templates` | gratis (es un GET) |
| Importar una plantilla | `POST /motions/import` | **1 crédito/s**; la respuesta de ejemplo es `type: render`, `glb: null`, es decir, no consta que genere GLB |
| Crear un movimiento | por texto 10 créditos; por vídeo 5 créditos/s | de pago |
| Saldo | `GET /credits` | gratis |

- **Movimientos 3D gratuitos.** Son los GLB que la cuenta ya tenga (exportarlos es gratis), o la
  "preset library" del MCP, que su página marca como gratuita.
- **Pendiente de comprobar.** Si los personajes creados en la web de PINOC aparecen en
  `GET /characters` con una clave de proyecto.

## Motor web: `@viggle/splat-engine-three` 0.3.0

- Paquete oficial de Viggle (mantenedores `viggle-dev` y `sichengyi`), MIT, three ≥ 0.186.
- Verificado: se carga en Chrome 156 en el M2 Pro, con WebGL2 y con WebGPU.
- Su API documentada:
  - **Carga y reproducción.** `VSplatLoader` → `SplatCharacter` (un `Object3D`). `SplatClipLoader`
    lee los GLB del rig MetaHuman. Controles: `play`, `crossFadeTo`, `stop`, `timeScale`, `time`,
    `paused` y los eventos `finished` / `loop`.
  - **Capas por región.** `playLayer(name, clip, { region: 'upperBody', weight })`.
  - **Movimiento y huesos.** Root motion; `getBoneWorldMatrix(name)`, `boneNames`.
  - **Control en tiempo real.** `armature.poseModifier = (pose) => …` edita la pose de cada hueso
    en cada frame, por encima del clip. Los tipos lo describen para "a look-at, a blink".
    `armature.poseProvider` sustituye la animación entera.
- **Control facial.**
  - **Solo existe a nivel de huesos.**
    - Un personaje creado con `joint_set=full` tiene 441 huesos, incluidos los `FACIAL_*`
      (MetaHuman).
    - Con `expression`, de 119 huesos, la cara se mueve rígida con la cabeza.
    - Con `body`, de 86 huesos (el valor por defecto), no hay cara.
  - **Sin evidencia** de API de visemas, blendshapes, parpadeo ni mirada. Habría que construirlos
    moviendo los huesos `FACIAL_*` con `poseModifier`, y solo en personajes de 441 huesos.

## Demo (lista, a falta de assets)

- **Rama y directorio.** Rama `exp/pinoc-3dgs`, directorio `pinoc/`.
- **`pinoc/server.py`: el broker de assets.**
  - Es el único que conoce la clave y llama solo a endpoints documentados.
  - Descarga cada URL firmada una vez a `pinoc/cache/` y sirve los bytes.
  - Registra cada llamada en `pinoc/logs/broker.log`, sin la clave ni las URLs.
  - Expone `/api/status`, `/api/characters[/<id>[/vsplat]]`, `/api/motions[/<id>/glb?rig=]` y
    `/api/local`.
  - Sirve también `/assets/` para lo que se baje por el MCP.
- **`pinoc/web/index.html`: solo renderiza.**
  - No tiene credenciales: habla con `/api/*` y `/assets/*`.
  - Funciones: selector de personaje y de clips, Reposo / Movimiento con crossfade de 0,35 s,
    giro de cabeza en tiempo real vía `poseModifier`, y panel de errores.
  - Muestra fps, número de splats, de huesos y de huesos faciales, y los tiempos de carga.
  - `window.state` deja todo eso legible para pruebas automáticas.

Reproducir:

```bash
cd pinoc && npm install --ignore-scripts      # three 0.186.0 + @viggle/splat-engine-three 0.3.0
python3 server.py 8770                       # http://127.0.0.1:8770/?auto=1   (&backend=webgpu)
```

Sin clave, la página muestra "falta VIGGLE_API_KEY (solo assets locales)" y el error
`[assets] no hay ningún personaje con vsplat listo`. Captura:
`.triage/pinoc/blocked_no_credentials.png`.

**Coste hasta ahora:** 0 créditos de Viggle. Solo se hicieron 4 llamadas GET gratuitas, y el saldo
sigue en 100.
