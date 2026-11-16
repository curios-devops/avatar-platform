# Prueba de poses: ¿grabar a la persona da un Twin mejor que animar su foto?

La idea: en vez de generar los clips de cuerpo con Pruna a partir de una foto, la persona se graba haciendo las cinco
poses que usa la llamada. Un ser de MEYA (Jin) le muestra cada una, cuenta 3, 2, 1 y graba. Si gana, en el producto
sería una mejora opcional («Hazlo más tú») después de crear el Twin, nunca un paso obligatorio.

## Las cinco poses

| Pose | Duración | Qué hace | Habla |
|---|---|---|---|
| `listen` | 8 s | Escucha: asiente despacio, boca cerrada, manos relajadas | No |
| `greet` | 5 s | Saluda con una mano y sonríe | «¡Hola! Soy …» |
| `explain` | 15 a 30 s | Explica con las manos abiertas | Lee el guion entero: **también es la muestra para clonar la voz** |
| `emphasis` | 8 s | Cuenta uno, dos, tres con los dedos y se inclina en la palabra clave | «Tres cosas: …» |
| `think` | 6 s | Mira arriba, se toca la barbilla y vuelve a mirar a la cámara | No |

Son los mismos nombres que usan la capa de gestos (`flashhead/body_layer.py`) y los estados de cuerpo de LiveTalking
(`musetalk/patch_states.py`), así que las tomas sustituyen directamente a los clips de Pruna.

## Cómo se graba (unos 3 minutos, nada pesado en el Mac)

```bash
backend/.venv/bin/python lab/poses/server.py          # abre http://localhost:8770 en Chrome
backend/.venv/bin/python lab/poses/prepare.py marcelo # después: recorte, cortes y muestra de voz (unos 12 s)
```

- La página comprueba cada toma en vivo y al terminar: cara visible, dentro del recuadro vertical, distancia, luz,
  y boca cerrada en las poses en silencio. Se puede repetir cualquier toma sola.
- Las tomas quedan en `lab/inputs/poses/<nombre>/raw/` y los clips listos en `lab/inputs/poses/<nombre>/clips/`
  (480x704 a 24 fps, como los de Jin de la ronda 3, más el audio de cada toma hablada, `voice_sample.wav` y `sheet.jpg`).
- Toda la carpeta `lab/inputs/poses/` está fuera de git: son grabaciones de una persona real.

Consejos: cámara fija a la altura de los ojos, luz de frente (una ventana delante sirve), fondo tranquilo, sentado y con
las dos manos dentro del recuadro.

## La comparación A/B (cuando estén las tomas)

Misma persona, misma voz, mismo motor en vivo y misma conversación; solo cambian los clips de cuerpo.

| | A: foto animada (lo actual) | B: poses grabadas |
|---|---|---|
| Clips | Pruna desde su foto (`musetalk/make_round3_clips.py` con su retrato), unos 0,55 USD a 480p | Sus tomas, 0 USD |
| Voz | La clonada de `voice_sample.wav` (créditos de ElevenLabs) | La misma |
| Esfuerzo de la persona | Una foto | Unos 3 min de sesión |

Pasos:
1. Marcelo graba la sesión y se ejecuta `prepare.py` (local, ligero).
2. Clonar la voz desde `voice_sample.wav`.
3. A: generar los clips con Pruna desde su foto (se pide permiso antes por el coste).
4. Pod de RunPod, máximo 1 h, con vigilante y autoapagado (regla del `CLAUDE.md`): llamada real con cada juego de
   clips, como en las rondas (web, micro simulado, interrupción), y grabación de ambas.
5. Hoja comparativa y vídeo lado a lado, métricas (`benchmark/metrics.py`: identidad ArcFace, sincronía de labios) y
   juicio visual, y un `RESUMEN.md` en `benchmark/results/poses/`.

B pasa al producto si en la llamada real se ve claramente más natural y más parecido a la persona, sin costuras de la
capa de gestos, y si la sesión se completa en menos de 3 minutos con como mucho una repetición por pose.
