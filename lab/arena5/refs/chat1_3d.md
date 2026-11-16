Esta es una copia de un chat compartido de ChatGPT. No se añadirá a la memoria.

Informar sobre la conversación
MEYA Avatar Factory — estrategia sin costes fijos

Estoy de acuerdo contigo. Cambiaría la recomendación anterior: nada de contratar servicios de $800 mensuales antes de tener clientes.

Y creo que podemos hacer algo mejor: construir un primer generador de personajes bastante sencillo, con Blender y bibliotecas abiertas, y utilizar GPU en la nube solamente cuando alguien solicite un avatar.

Hay que recordar nuestro objetivo comercial: conseguir los primeros 800 clientes a 1 €, es decir, aproximadamente 800 € de ingresos iniciales. No necesitamos resolver ahora la reconstrucción humana perfecta. Necesitamos un resultado suficientemente atractivo para que la gente quiera probarlo y comprarlo.

He encontrado varias piezas interesantes de código abierto, algunas bastante recientes.

1. Qué he encontrado investigando
 

MediaPipe Face Landmarker

Muy útil para el MVP

478 puntos faciales 3D estimados.

52 coeficientes de expresión.

Funciona con una fotografía.

Puede ejecutarse en navegador o servidor.

Es una buena base para adaptar la geometría de una cabeza a una persona real. No reconstruye por sí solo un modelo 3D completo. 
Google for Developers

Documentación oficial 
 

MakeHuman / MPFB2

Muy útil para el cuerpo

Cuerpos humanos paramétricos.

Proporciones, anatomía, ropa y pelo.

Integración con Blender.

Assets CC0, aunque el código del plugin MPFB es GPLv3.

Nos permite evitar generar un cuerpo diferente desde cero para cada persona. 
GitHub
+1

Repositorio MPFB2 
 

TRELLIS.2

Candidato para experimento

Una imagen a geometría 3D.

Texturas y materiales.

Código bajo licencia MIT.

Requiere infraestructura GPU y postprocesamiento.

Importante: genera objetos 3D, pero no garantiza un personaje humano riggeado ni una cara animable. 
GitHub
+1

Repositorio oficial 
 

Make-It-Animatable

Candidato para rigging

Predice huesos y pesos de skinning.

Convierte mallas humanoides en personajes animables.

Implementación MIT.

Investigación publicada en CVPR 2025.

Puede ahorrarnos mucho trabajo de rigging. No resuelve por sí solo las expresiones faciales. 
Open Access CVF
+2

Repositorio oficial 

Una advertencia de licencias: no utilizaría Hunyuan3D 2.1 en nuestro despliegue desde España. Su licencia comunitaria excluye expresamente la Unión Europea, Reino Unido y Corea del Sur. TRELLIS.2 es una alternativa con código MIT, aunque hay que verificar las licencias de sus dependencias. 
GitHub
+2

2. Los dos pipelines que probaría

No haría una investigación interminable de veinte tecnologías. Probaría dos alternativas que representan dos filosofías distintas.

Pipeline A — Geometría paramétrica + Blender
Mi favorito para lanzar MEYA

La idea es que no necesitamos reconstruir cada milímetro de la persona. Creamos un personaje de plastilina que conserve sus rasgos reconocibles.

 

1. Fotografía

Una selfie frontal

 

2. MediaPipe

Detectar ojos, nariz, boca, mandíbula y proporciones

 

3. Head Builder

Adaptar una malla facial base a las proporciones detectadas

 

4. Body Builder

Crear cuerpo, ropa y pelo desde plantillas paramétricas

 

5. Clay Renderer

Materiales, proporciones, colores y acabado artístico

 

6. Rigging + Export

Esqueleto común, expresiones y GLB

La decisión inteligente aquí: construir un único cuerpo base riggeado y una cabeza con topología conocida y expresiones preparadas.

Cada usuario recibe una versión deformada de esa misma estructura. No tenemos que riggear cada personaje individualmente.

Para la cara:

Ajustamos la forma del cráneo, mandíbula, ojos, nariz y boca.

Aplicamos una textura o color adaptado a la foto.

Estilizamos las proporciones para que parezca una figura de plastilina.

Generamos las expresiones mediante Shape Keys predefinidas.

Para el cuerpo:

Un conjunto reducido de proporciones.

Varias prendas y peinados.

Un cuerpo estilizado, no una reconstrucción anatómica inventada a partir de la cara.

Ventaja: muy barato, predecible, reproducible y compatible con animación.

Limitación: no tendremos una réplica 3D exacta. La cara será una interpretación artística reconocible.

Pipeline B — Reconstrucción 3D con TRELLIS.2 + Blender
Experimento de mayor calidad potencial

Aquí dejamos que un modelo de reconstrucción genere la geometría a partir de la fotografía y después la preparamos para animación.

Fotografía

 

TRELLIS.2

Reconstrucción de geometría y textura 3D

 

Blender

Retopología, estilización Clay, materiales y limpieza

 

Make-It-Animatable

Rigging corporal automático

 

Face Rig + GLB

Añadir expresiones faciales compatibles con MEYA

 

Este pipeline podría producir personajes visualmente mucho más ricos, pero tiene dos problemas:

La geometría generada puede no conservar suficientemente la identidad de la cara.

La malla generada no tiene necesariamente una topología adecuada para deformar ojos, labios y mandíbula.

No confiaría en el auto-rigging para resolver también el facial rigging. Son problemas distintos.

La alternativa Make-It-Animatable es interesante porque predice un esqueleto y pesos de skinning, pero habrá que validar sus resultados con nuestros personajes Clay. 
GitHub
+1

3. Blender: lo utilizaría como motor de construcción, no como aplicación de usuario

Aquí creo que tenemos una oportunidad importante.

Blender puede ejecutarse sin interfaz gráfica y controlarse mediante Python. Es decir, podemos tener un servicio que reciba parámetros y construya personajes automáticamente.

Avatar Builder — Python

text
input/
  portrait.jpg
  avatar_config.json

pipeline/
  face_analyzer.py
  head_builder.py
  body_builder.py
  clay_materials.py
  facial_rig.py
  animation_rig.py
  export_glb.py

output/
  avatar.glb
  preview.png
  metadata.json

El backend ejecuta Blender en modo background, genera el personaje y exporta GLB. React/Three.js solo recibe el resultado.

La documentación de Blender incluye Rigify, su sistema de generación de esqueletos, y exportación glTF. 
Blender 5.3 Manual
+1

Para MEYA sería un servicio independiente, inicialmente en Python, que se comunica con el backend actual mediante una tarea asíncrona.

4. ¿Cuánto nos costaría realmente?

Podemos evitar completamente una suscripción mensual.

RunPod ofrece GPU serverless con facturación por segundos. En su tarifa consultada, una RTX 4090 cuesta $1,34/hora y una L4 $0,75/hora. 
Runpod
+1

Ejemplo de coste GPU

$0,0223

Coste de una RTX 4090 por minuto, usando la tarifa publicada de $1,34/hora.

Tiempo de GPU

	

Coste




1 minuto

	

$0,022




3 minutos

	

$0,067




5 minutos

	

$0,112




10 minutos

	

$0,223

Son cálculos ilustrativos, no mediciones de TRELLIS.2. El tiempo real, los arranques, el almacenamiento y las tareas fallidas deben medirse.

Mi objetivo sería:

Pipeline A: coste marginal muy bajo, con Blender y procesamiento convencional.

Pipeline B: pagar GPU únicamente cuando se genere el avatar.

Animación: siempre en Three.js en el dispositivo del usuario.

Almacenamiento: R2, sin mantener GPU encendida.

Y un detalle importante: no necesitamos generar de nuevo el personaje cuando habla. Se crea una vez, se guarda y se reutiliza.

5. Qué probaría primero: un sprint de 7 días

No construiría los dos pipelines completos. Haría una comparación controlada con las mismas cinco fotografías.

Día

	

Trabajo

	

Resultado




1

	

Preparar Blender + MediaPipe

	

Detección facial




2

	

Construir cabeza paramétrica

	

Primera identidad 3D




3

	

Añadir cuerpo y Clay shader

	

Personaje completo




4

	

Rig facial y corporal

	

Personaje animable




5

	

Probar TRELLIS.2

	

Segundo candidato




6

	

Comparar calidad y rendimiento

	

Evaluación




7

	

Integrar el ganador en MEYA

	

Demo funcional

Qué vamos a medir

¿Reconocemos a la persona?

¿Se parece más a una figura de plastilina que a un muñeco genérico?

¿Puede abrir la boca, sonreír y parpadear?

¿Se deforma bien cuando habla?

¿Cuánto cuesta producirlo?

¿Cuánto tarda?

¿Funciona en el iPhone?

6. Mi decisión: dos niveles de producto

No esperaría a tener la reconstrucción perfecta.

LANZAMIENTO

MEYA Clay Avatar — 1 €

 

Una fotografía.

Pipeline A.

Personaje reconocible.

Conversación de prueba.

Guardar el personaje.

EVOLUCIÓN PRO

MEYA Premium Avatar

 

Varias fotografías.

Reconstrucción de mayor fidelidad.

Más estilos.

Ropa y accesorios.

Personalización avanzada.

Exportación GLB.

Los 1 € los trataría como precio de lanzamiento para la creación del primer avatar, no como una suscripción que nos obligue a mantener costes recurrentes.

7. Una última tecnología que merece atención

He encontrado también un proyecto llamado 
UnumAvatar. Combina MediaPipe, Blender, Three.js y Rhubarb Lip Sync para crear una cabeza 3D parlante desde una fotografía. 
GitHub

No lo tomaría como nuestra solución final, pero sí como referencia de implementación para el primer prototipo facial.

Repositorio: UnumAvatar en GitHub .

Mi recomendación definitiva
GO — Pipeline A

Empezaría por:

MediaPipe para extraer rasgos faciales.

Blender + Python para generar una cabeza paramétrica.

MakeHuman/MPFB o nuestro propio cuerpo base.

Rig facial común con 52 expresiones compatibles.

Exportación GLB.

Three.js para animación.

Y en paralelo haría una prueba pequeña de TRELLIS.2 para ver si podemos mejorar la geometría sin disparar costes.

No compraría Avatar SDK. No contrataría una GPU permanente. No entrenaría ningún modelo.

La inversión inicial sería nuestro trabajo de integración y desarrollo, que además nos dejaría una infraestructura propia.

Mi objetivo sería tener una primera versión que podamos enseñar y cobrar antes de Navidad, aunque inicialmente el resultado sea más estilizado que realista.

Y una idea comercial adicional: el primer avatar debería poder compartirse como una pequeña tarjeta o enlace público. Cada persona que comparte su personaje puede traer nuevos visitantes a MEYA.

Creo que por fin tenemos un proyecto con un alcance técnico razonable, un coste variable controlable y una propuesta comercial fácil de entender.

ChatGPT es una IA y puede equivocarse.

## Links
Documentación oficial -> https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker?utm_source=chatgpt.com
Repositorio MPFB2 -> https://github.com/makehumancommunity/mpfb2?utm_source=chatgpt.com
Repositorio oficial -> https://github.com/microsoft/TRELLIS.2?utm_source=chatgpt.com
Repositorio oficial -> https://github.com/jasongzy/Make-It-Animatable?utm_source=chatgpt.com
 -> https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker?utm_source=chatgpt.com
 -> https://blenderartists.org/t/face-retopology-wireframe/1294005?utm_source=chatgpt.com
 -> https://medium.com/%40little_michael101/shaders-retaining-colors-when-applying-a-toon-shader-in-blender3d-21b441fb8753?utm_source=chatgpt.com
 -> https://kidteller.com/create-book?utm_source=chatgpt.com
 -> https://rubika-edu.com/realisations/lavomatrix-luka-blendshapes?utm_source=chatgpt.com
 -> https://lizhe00.github.io/?utm_source=chatgpt.com
 -> https://www.behance.net/gallery/110876433/Boy-stylized-character?utm_source=chatgpt.com
 -> https://www.unrealengine.com/marketplace/en-US/product/creepy-mannequin?utm_source=chatgpt.com
 -> https://justcreate3d.itch.io/stylized-fantasy-characters?utm_source=chatgpt.com
 -> https://www.aiai.com/image/ai-clay-art-generator?utm_source=chatgpt.com
 -> https://www.etsy.com/listing/1884432632/custom-claymation-portrait-from-your?utm_source=chatgpt.com
UnumAvatar en GitHub -> https://github.com/corpunum/UnumAvatar?utm_source=chatgpt.com
