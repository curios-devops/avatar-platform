# Crear un ser en MEYA: rediseño y prueba de punta a punta (2026-11-14)

## Qué cambió

**El flujo de creación** (`/create`) pasó a tener tres pasos y la vista previa del ser siempre a la vista. Usa el diseño del sitio nuevo (Archivo, tokens claro y oscuro, acento naranja).
1. **Aspecto y voz.**
   - Para quién es: tú (Twin), una compañía, un personaje o un experto.
   - Aspecto: Realista, Animado o Animado 3D.
   - Imagen: describir, subir foto, selfie o galería.
   - Voz:
     - Un Twin graba o sube su propia voz siguiendo un guion, y se clona.
     - Los demás reciben una voz predefinida según su tipo (por ejemplo, femenina para una compañía).
     - Cualquiera puede escuchar las voces, describir la que quiere o elegir de la biblioteca.
2. **Personalidad.**
   - Cómo se presenta, con una propuesta de MEYA.
   - Quién es y qué hacéis juntos.
   - Tres deslizadores: participación, extensión y tono.
   - Límites y lo que sabe: datos, alias y preguntas al azar.
3. **Darle vida.**
   - Estado de cada parte y una conversación privada.
   - Ficha: descripción, frase del vídeo y etiquetas.
   - Visibilidad y compartir: enlace, WhatsApp, Telegram, X, LinkedIn, correo y la hoja nativa del móvil.

**Para qué quieres tu Twin** (Many Me): Profesional, Creador de contenido, Personal o Profesor. Cada propósito fija el papel, el tono y el consejo para la foto, y se pueden crear varios Twins.

**Animado 3D en el mismo flujo.**
- Lo manejan el texto o la foto. El personaje three.js aparece vivo en la vista previa y su captura queda como imagen del ser.
- El estudio de selección (pelos, ropa, deslizadores) queda solo en el lab.

**Landing.** La tarjeta «Tu gemelo digital» abre una selfie o la subida de una foto, muestra la vista previa y lleva al flujo con la foto ya cargada.

## Prueba de punta a punta: Marcelo

| Paso | Resultado |
|---|---|
| Foto y consentimiento | Foto propia de Barcelona, recortada |
| Voz | «Hombre adulto, voz cálida y tranquila» encontró a Juan Carlos, y se escuchó presentándose como Marcelo |
| Personalidad | Propuesta de MEYA: gemelo digital de Marcelo, creador de MEYA; consejo y mentoría |
| Conversación | Tres turnos en español. Usa lo que sabe, respeta el estilo y aclara que es un gemelo digital |
| Vídeo de presentación | Pruna, 768x768, 6,3 s, labios sincronizados (`marcelo_presentacion.mp4`) |
| En Mis avatares | «Marcelo · Twin · No listado», con enlace para compartir |
| Voz clonada | Probada con una voz sintética de macOS en un borrador aparte, que después se borró junto con la voz en ElevenLabs |
| Animado 3D | «Hombre de unos 45 años, atlético, gafas, chaqueta verde oliva» dio un personaje three.js, cuya captura quedó como imagen (borrador borrado después) |

**Costo:** unos 0,27 USD.
- Pruna: 6,3 s × 0,04 USD/s = 0,25 USD.
- Claude, en la composición y el chat: menos de 0,02 USD.
- ElevenLabs: dentro de los créditos del plan.

**Wan VACE local:** no es viable en el Mac de 16 GB. Un clip de 1 a 2 s tarda entre 20 y 35 min con la GPU al máximo. Se usa Pruna.

## Pendientes
- Al borrar un Twin, borrar también su voz clonada en ElevenLabs.
- Retomar un borrador desde otro dispositivo; hoy solo se conserva en la pestaña.
- Pasar el texto del 3D por un modelo de lenguaje en lugar de reglas fijas.
- Permitir varias fotos para el Twin.
- La prueba de misiones `missions.test.ts` ya fallaba antes de este trabajo.
