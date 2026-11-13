# Ronda 2: resumen ejecutivo (2026-11-13)

**Objetivo:** un ser de MEYA en videollamada con medio cuerpo vivo (gestos y postura que acompañan la conversación), con un costo por llamada que se pueda sostener.

**Lo que se probó:** Jin, creador tech de MEYA. Cada motor recibió el mismo retrato y la misma llamada.

## Resultado

| Motor | Modo | Cuerpo | Nitidez | Identidad | Veredicto |
|---|---|---|---|---|---|
| **MuseTalk + estados** | en vivo, ~0,9 s de latencia | sigue la llamada (escuchar, explicar, énfasis) | 82 | 0,63 | **Motor principal en vivo** |
| **FlashHead + estados** | en vivo, 0,54–0,69 s de latencia | sigue la llamada | 53 | 0,64 | Al lado: responde antes y articula mejor |
| Pruna avatar | por lotes (57 s para 10 s de vídeo) | gestos al ritmo de la voz | **159** | **0,79** | Mejor imagen; para vídeo pregrabado y clips |
| Boson | por lotes (casi en tiempo real) | quieto | 16 | 0,62 | Imagen débil; solo como referencia |
| EchoMimic V3 | no cabe en una GPU | — | — | — | Descartado para vivo |
| LiveAvatar | no probado en vivo | — | — | — | Descartado: 5 H100 por llamada |

## Claves

- **Cuerpo según el momento.** Cada ser tiene clips cortos (escuchar, explicar, énfasis) y la llamada elige uno según lo que dice. Cuando responde con una lista o insiste en algo, cuenta con los dedos.
- **El fantasma de FlashHead quedó resuelto.** La cara generada se ancla a los ojos del clip cuadro a cuadro y se mezcla siguiendo el contorno real de la cara.
- **Costo por llamada.** MuseTalk atiende dos llamadas por GPU de unos 0,3–0,9 USD/h. Las opciones de cuerpo completo generado (EchoMimic y LiveAvatar) costarían de 13 a 21 USD/h por llamada.
- **Clips.** Se generan en la nube (Pruna, de 0,02 a 0,04 USD/s). En el Mac no se pueden generar a tiempo.

## Decisión y siguiente paso

MuseTalk + estados queda como motor en vivo, con FlashHead como alternativa. El siguiente paso es la ronda 3:
- clips de hablar hechos con Pruna avatar, para que los gestos sigan la voz;
- clips de "pensando" y "saludo";
- elegir el clip por frase.

**Gasto de la ronda:** unos 2,4 USD (RunPod 0,88, APIs ~1,5).

Vídeos: `arena_jin_10s.mp4` (los cuatro lado a lado) y `call-flashhead-states_jin.mp4` (la llamada en vivo).
