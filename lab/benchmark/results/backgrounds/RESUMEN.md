# Fondos estilo Meet en MEYA (2026-11-14)

## Qué hay
- **Crear:** en Subir foto, Selfie y Animado 3D aparece la fila «Fondo»: Original, Difuminado, escenas de MEYA y
  «Subir tu fondo». La persona se recorta en el navegador (MediaPipe, modelo multiclase con el pelo aparte) y la foto
  compuesta pasa a ser la imagen del ser. La selfie muestra el fondo en vivo, como en una videollamada.
- **3D:** la captura del personaje ya es transparente, así que se pone sobre la escena sin recortar. La vista previa
  en vivo muestra la escena detrás del personaje.
- **Clips de cuerpo:** `lab/poses/background.py` aplica la misma escena fotograma a fotograma, con la máscara suavizada
  en el tiempo para que los bordes no tiemblen.

## Pruebas
| Prueba | Resultado |
|---|---|
| Foto de Marcelo sobre «Costa al atardecer» | Recorte limpio, también en el pelo (`marcelo_costa.jpg`) |
| Vídeo Pruna desde esa foto (6,4 s) | El fondo se queda quieto: cambio medio de 0,7 a 2,6 sobre 255 en cielo y laterales (`marcelo_costa_pruna.mp4`) |
| Clips de Jin (ronda 3) con la costa | Cinco clips en 92 s de CPU, sin parpadeo; la silla desaparece con el fondo (`jin_explain_costa.mp4`) |
| Personaje 3D con fondo | Captura y vista previa con la escena detrás |

**Costo:** unos 0,25 USD (Pruna, 6,4 s); un primer intento devolvió 504 y pudo cobrarse también, como mucho 0,5 USD.

## Pendiente
- Escenas por categoría (2026-11-15/16): las 13 escenas de Z-Image q4 están generadas y publicadas, 15 fondos en
  total en 6 categorías (Nuevos 3, Profesional 3, Casa acogedora 3, Lugares 2, Fantasía 3, Lisos 2). Unos 110 s por
  imagen, pico de 4,7 GB; el vigilante paró la cola cinco veces cuando otras tareas (Chrome, pruebas) apretaban la
  memoria, y `run_all.sh` siempre retomó donde quedó. Con la tapa cerrada el Mac duerme aunque caffeinate esté activo.
