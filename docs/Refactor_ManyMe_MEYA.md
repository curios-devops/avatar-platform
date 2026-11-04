# PR (Plan de Requerimientos) – Refactor de ManyMe hacia MEYA

## 1. Arquitectura actual y módulos reutilizables

Mapearemos el sistema actual identificando componentes clave para aprovecharlos sin reescribirlos desde cero. Por ejemplo:  
- **Backend Python** (Flask/Django): define rutas/API actuales, modelos de datos (usuarios, clones, conversaciones), lógica de agentes, autenticación, etc.  
- **Frontend React+TypeScript**: estructura de carpetas (`src/pages`, `src/components`, `src/hooks`, `src/utils`, etc.), componentes de UI (feed, chat, creadores, perfil), servicios de llamadas API.  
- **Módulos reutilizables**: p.ej. módulo de autenticación (login/registro), gestor de sesiones, base de datos (modelos de seres digitales), cliente de API de IA (p.ej. OpenAI), componentes de interfaz común (botones, formularios). Estos módulos existentes deben documentarse brevemente y conservarse en el refactor.  
- **Infraestructura**: pipelines de despliegue (p.ej. Vercel u otro servidor), sistema de CI/CD actual, esquema de base de datos, variables de entorno usadas, etc.  

**Cita:** Un plan de refactor típicamente incluye una sección de “Arquitectura” donde se explica cómo está organizado el código actual. Esto facilita decidir qué extraer o reestructurar sin romper funcionalidades.

## 2. Alcance del refactor y entregables del MVP

Definiremos qué incluye exactamente la primera versión (MVP) y qué se pospone. De acuerdo con las mejores prácticas de planificación, el plan debe listar *“¿Qué trabajo se va a realizar?”* y *“¿Cuáles son los entregables principales?”*. Proponemos como **entregables del MVP**:  

- **Registro e inicio de sesión:** Módulo de autenticación funcional (usuarios creadores y simples).  
- **Home Feed social:** Pantalla de inicio estilo red social donde se ven publicaciones de seres digitales. Debe permitir acciones inmediatas (ver perfil, conversar, seguir) como en Character.AI.  
- **Explore/Catálogo:** Sección de descubrimiento filtrable (Personas/Twins, Compañeros, Expertos, Trabajadores) con fichas de cada ser digital (foto/avatar, descripción, “probar” y “añadir a mi mundo”).  
- **Creación de seres digitales:** Asistente guiado (via formularios o IA) para crear tu *Twin* (clon personal) o un *Character* (original). Incluye selección de rol, apariencia y capacidades. (Back-end debe soportar crear la entidad y guardar su configuración).  
- **My World (Gestión personal):** Página donde el usuario ve sus seres creados y añadidos. Puede editar propiedades básicas (nombre, avatar), ver estadísticas de uso y eliminar seres.  
- **Inbox/Chat único:** Chat centralizado donde hablar con cualquier ser digital propio o seguido. Unificaría conversaciones privadas.  
- **Conversación con IA:** Integración básica con agente de IA por texto (y voz opcional) para cada ser. (El MVP puede usar IA por texto, p.ej. GPT, para validación).  
- **Red social:** Publicaciones simples con video o mensaje de presentación de cada ser. Compartir en feed, follow, like.  
- **Diseño móvil:** Toda interfaz optimizada para mobile (p.ej. menú inferior, diseño responsive). *Mobile-first* es fundamental: se debe priorizar la experiencia móvil.  

Estos entregables coinciden con construir un núcleo social e interactivo. Funcionalidades complejas (p.ej. agentes 24/7, pagos, salud, integración a apps externas) quedan fuera del MVP.  

**Cita:** Un plan de proyecto debe responder “¿Qué se hará?” (deliverables) y “¿Por qué?”. En este caso, cada elemento anterior es un entregable clave del MVP.

## 3. Servicios externos y variables de entorno

El sistema requerirá integrar APIs externas de IA y servicios varios. Definiremos las siguientes variables de entorno en un fichero `.env` (sin valores, como placeholders):  

- `OPENAI_API_KEY=` – Clave para la API de OpenAI (GPT, embeddings, etc.).  
- `VERCEL_AI_KEY=` – Clave de Vercel AI (si se usa su SDK de agentes).  
- `GOOGLE_OAUTH_CLIENT_ID=` y `GOOGLE_OAUTH_CLIENT_SECRET=` – Si se usa Google para login.  
- `DB_URL=` o `DATABASE_URL=` – Cadena de conexión a la base de datos (p.ej. PostgreSQL).  
- `JWT_SECRET=` – Semilla para tokens de autenticación (si aplica).  
- `SENTRY_DSN=` – URL de Sentry para monitoreo (opcional).  
- `ANALYTICS_KEY=` – API key de Google Analytics u otro servicio.  
- `REACT_APP_*` o `VITE_*` (según builder) – Variables front-end, ej. `VITE_API_URL=` o `REACT_APP_MAPBOX_TOKEN=` para claves que cliente frontal necesite.  

En React (o Vite), las variables de entorno deben tener prefijos especiales: p.ej. `VITE_` para Vite o `REACT_APP_` para Create-React-App. Para Next.js no se requiere prefijo en `.env.local`. En cualquier caso, nunca exponer en el frontend una clave secreta; sólo exponer las necesarias de forma segura.  

**Cita:** En entornos React, las variables del cliente se nombran con un prefijo (`REACT_APP_` o `VITE_`). Se usarán placeholders en `.env` para todas las API keys y URLs externas requeridas.

## 4. Plan de trabajo detallado (tareas, tiempos y responsables)

A continuación se propone un plan de desarrollo siguiendo técnicas ágiles (timeboxing). Cada tarea indica responsable y plazo estimado:

- [ ] **Paso 1: Auditoría inicial (1 día)** – *Responsable: Desarrollador Principal / Tú*. Revisión del código actual: identificar todas las rutas backend, servicios React existentes, librerías de IA en uso, y documentar módulos reutilizables. Registrar dependencias clave (por ejemplo, `python-dotenv`, `react-router`, etc.).  
- [ ] **Paso 2: Especificación técnica (2 días)** – *Responsable: Tú (Product/Arquitecto)*. Detallar el alcance del refactor y entregar un documento de especificaciones funcionales y técnicas. Incluir diagramas de arquitectura actual y refactorizada. Alinear objetivos del MVP con el plan general.  
- [ ] **Paso 3: Preparación del entorno (.env) (medio día)** – *Responsable: Desarrollador*. Crear `.env.example` con variables placeholder definidas arriba. Configurar lectura de `dotenv` en Python y React (por ejemplo, usando `python-dotenv` y cargar `process.env` en cliente).  
- [ ] **Paso 4: Instalación de servicios externos (1 día)** – *Responsable: Desarrollador / DevOps*. Registrar e instalar SDKs de OpenAI, Vercel AI, y configurar OAuth. Verificar conexión de backend con `OPENAI_API_KEY` (p.ej. una prueba mínima de llamada a API).  
- [ ] **Paso 5: Esqueleto de la nueva app (2 días)** – *Responsable: Desarrollador*. Establecer la base del nuevo frontend: crear proyecto React (o Next.js) en Typescript con rutas `/home`, `/explore`, `/create`, `/my-world`, `/inbox`. Crear backend Python con endpoints base `/api/feed`, `/api/explore`, `/api/create`, `/api/world`, `/api/chat`. Implementar autenticación JWT básica.  
- [ ] **Paso 6: Home Feed (3 días)** – *Responsable: Desarrollador + UX/UI Designer*. Construir UI de feed con tarjetas de seres digitales (foto, nombre, breve descripción). Integrar API para listar publicaciones. Incluir botones “Probar” (abre chat) y “Seguir”. *Nota de diseño:* menú inferior fijo para mobile, uso de iconos claros y tipografía legible en smartphones.  
- [ ] **Paso 7: Explore/Catálogo (3 días)** – *Responsable: Desarrollador*. Tablas o listas de filtros por categorías (Twins, Compañeros, Expertos, Trabajadores). Llamadas a backend para obtener colecciones. Creación de componente reutilizable para ficha de ser digital. Implementar “Agregar a Mi Mundo” enviando petición al backend.  
- [ ] **Paso 8: Creación de ser (4 días)** – *Responsable: Desarrollador + IA Engineer*. Formularios guiados para crear un Twin o un Character. Recopilar datos (nombre, rol, apariencia deseada, descripción). Llamada a backend para generar entidad (posiblemente invocar IA para inicializar personalidad). Crear endpoints de backend `/api/create/twin` y `/api/create/character`.  
- [ ] **Paso 9: My World (2 días)** – *Responsable: Desarrollador*. Página personal del usuario listando “Creado por mí” y “Añadidos”. Permitir editar o eliminar cada ser en su instancia local (no afecta al creador original). Endpoint `/api/world` para consultar.  
- [ ] **Paso 10: Inbox/Chat centralizado (3 días)** – *Responsable: Desarrollador + IA Engineer*. Integrar chat de texto (p.ej. usando WebSockets o long polling). Habilitar conversación one-to-one con los seres del usuario. El backend debe enrutar mensajes al módulo de IA correspondiente (p.ej. enviando el texto al agente de GPT para ese personaje). Se debe mantener el historial mínimo necesario.  
- [ ] **Paso 11: Testeo y QA (2 días)** – *Responsable: QA / Dev*. Probar todos los flujos de usuario en móvil y escritorio. Verificar que nada nuevo rompa (test de regresión). Ajustes UI/UX (ej. botones táctiles grandes, contraste). *Revisión móvil:* usar emuladores o pruebas reales (ramotion señala que el 59% del tráfico es móvil, por lo que la usabilidad en smartphone es crítica).  
- [ ] **Paso 12: Despliegue y llave Vercel AI (1 día)** – *Responsable: DevOps / Tú*. Configurar el hosting (Vercel o servidor propio). Añadir la clave de Vercel AI en producción. Realizar prueba final en web pública.  
- [ ] **Paso 13: Informe de cierre** – *Responsable: Tú*. Entregar resumen del trabajo, aclarar dudas restantes (ver preguntas abajo) y cerrar tareas.  

Cada tarea se abordará con *timeboxing*: por ejemplo, dedicar bloques de 1–2 horas concentradas (café en mano) para cumplirlas. Al terminar cada bloque, se comprueba el avance y se ajustan prioridades.

**Cita:** Un plan formal debe especificar claramente *“¿Quién?”* (roles) y *“¿Cuándo?”* (cronograma/milestones). Además, aplicar timeboxes ayuda a enfocar esfuerzos y limitar el alcance diario.

## 5. Preguntas abiertas para ingenieros de IA y arquitecto senior

1. **Estructura actual:** ¿Usamos Django o Flask en el backend? ¿Qué versión de Python y dependencias clave (ORM, librerías IA) tenemos?  
2. **Bases de datos:** ¿Cuál es el modelo actual de datos (tablas/colecciones)? ¿Se usarán instancias nuevas o la misma base?  
3. **Autenticación:** ¿Cómo se manejan roles actuales? ¿Implementamos OAuth (Google/Apple) u otro sistema?  
4. **IA y agentes:** ¿Qué proveedores de IA se prefieren? (¿OpenAI, Anthropic, Vercel AI?) ¿Tenemos ya integraciones funcionando?  
5. **Generación de contenido:** Para crear las presentaciones de los seres (vídeos/carruseles), ¿usamos servicios externos (p.ej. DALL·E, Pexels API)? ¿O se reduce a texto e imágenes estáticas?  
6. **Seguridad y privacidad:** ¿Qué datos de usuario podemos compartir? (especialmente si implementamos *Wellness Me* o clones privados).  
7. **Despliegue:** ¿Se utilizará Vercel (para frontend y Serverless) o un servidor dedicado para Python?  
8. **Analytics:** ¿Qué métricas definimos para probar la adopción (p.ej. activaciones semanales de seres)? ¿Usaremos Google Analytics u otro sistema?  
9. **Diseño:** ¿Hay guías de estilo o prototipos UI previos? ¿Tenemos un UX/UI designer asignado para validar los mockups móviles?  
10. **Prioridades adicionales:** Si el tiempo lo permite, ¿qué funcionalidad post-MVP consideran esencial? (p.ej. pagos, suscripciones, agentes 24/7).  

Estas preguntas deben clarificar la visión técnica y asegurar que el desarrollo del refactor siga los lineamientos del arquitecto senior (tú).  

---

**Fuentes:** Este plan sigue buenas prácticas de gestión de proyectos (PMBOK) que enfatizan un documento formal con tareas, cronograma y entregables claros. Además, integra enfoques ágiles de timeboxing y conceptos de *mobile-first* para asegurar la mejor experiencia en smartphones. Las variables de entorno y detalles técnicos se basan en guías estándar de React/Django. 

