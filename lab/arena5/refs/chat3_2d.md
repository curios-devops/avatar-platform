Esta es una copia de un chat compartido de ChatGPT. No se añadirá a la memoria.

Informar sobre la conversación

Sí. Y creo que aquí podemos conseguir una mejora importante para MEYA: separar la creación del personaje de su animación conversacional. En 2D incluso podemos ir más lejos que en 3D: generar el aspecto una sola vez y hacer que el personaje hable en el navegador, sin ejecutar MuseTalk ni otro modelo de vídeo por cada respuesta.

Hay una distinción clave: si queremos que una fotografía fija se convierta automáticamente en un vídeo realista hablando, normalmente seguimos necesitando inferencia de IA. Pero si aceptamos un personaje 2D preparado para animación, podemos mover ojos, boca, cabeza y cuerpo en el cliente con muy poco coste.

Voy a comparar las tecnologías con ese criterio: proyectos abiertos, licencia, calidad visual, ejecución en navegador y facilidad de integrarlos con vuestro stack React/TypeScript.

1. Lo que encontré: hay alternativas bastante prometedoras

Hay una familia tecnológica que nos interesa especialmente: los 2D puppet avatars. No generan un vídeo nuevo: construyen un personaje a partir de piezas gráficas y lo animan en tiempo real.

 

Kugutu

Mi favorito para probar primero

MIT · SVG · JavaScript · React

Personajes construidos con SVG y JSON. Tiene ojos, parpadeo, respiración, gestos, emociones, piezas intercambiables y sincronización labial. Puede recibir visemas del audio o texto. No necesita WebGL ni GPU. 
GitHub
+1

GitHub / Kugutu  · Demo Studio 

 

Iki

Muy interesante para MEYA

MIT · TypeScript · WebGL2

Un motor abierto tipo Live2D. Importa piezas gráficas, genera un rig, y permite animar ojos, boca, cabeza, cabello y cuerpo. Tiene un plugin para que un agente de código ayude a dibujar y montar personajes. Es joven, versión 0.x, pero su arquitectura es muy atractiva para nuestra fábrica. 
GitHub
+1

GitHub / Iki  · Demo 

 

Doll Studio

Proyecto abierto · PSD por capas · MediaPipe

Convierte un PSD de personaje en un avatar animado. Tiene parpadeo, movimiento de cabeza, ojos, cejas, boca, respiración y seguimiento facial. Su sistema usa análisis de audio para mover la boca y MediaPipe para el tracking. Es especialmente interesante como referencia de implementación. 
GitHub
+1

GitHub / Doll Studio 

 

idle-web-animation

Open source · JSON · DOM/CSS

Una alternativa sencilla para personajes por capas: respiran, parpadean, miran y reaccionan. Sin motor de videojuegos ni licencia de editor. No es un sistema completo de conversación, pero puede ser una buena base de animación ambiental. 
GitHub
+1

GitHub / idle-web-animation 

Una observación: Kugutu e Iki son proyectos jóvenes. Que sean MIT no significa que estén listos para producción. Hay que probarlos en Safari de iPhone, comprobar rendimiento, estabilidad y calidad de las animaciones antes de elegir.

2. La pieza que puede reemplazar a MuseTalk: lip-sync en el navegador

Encontré un proyecto pequeño que merece una prueba:

LipSync Engine

GitHub / Amoner/lipsync-engine 

MIT.

Aproximadamente 15 KB minificado.

Utiliza Web Audio API y AudioWorklet.

Analiza el audio y emite eventos de visemas.

Funciona con SVG, Canvas y otros renderizadores.

No requiere GPU ni modelo de IA. 
GitHub
+1

Hay una diferencia importante: analizar frecuencias no es lo mismo que reconocer fonemas. Puede producir una boca que acompaña bastante bien al sonido, pero no garantiza que los labios formen exactamente las palabras pronunciadas.

Kugutu tiene otra opción interesante: recibir una secuencia de visemas con tiempos, o estimarlos a partir del texto. Si nuestro TTS nos entrega marcas temporales, esa sería mi primera elección.

También encontré 
Wireface 2D: permite animar una fotografía, dibujos y personajes anime directamente en el navegador, con un rig facial de 468 puntos. Es una demostración muy cercana a lo que buscamos, pero ojo: para integrar el SDK en un SaaS comercial exige una licencia Developer; no es una alternativa open source gratuita para nuestro producto. 
wireface.dev
+1

Ver Wireface 2D 
3. ¿Qué haría con los estilos 2D?

No copiaría exactamente los estilos 3D. En 2D tenemos una oportunidad de ofrecer personajes más ilustrados y expresivos.

 

Animated Illustration

El equivalente 2D del estilo ToonBee. Mi primera opción.

 

Anime / Manga

Muy reconocible y fácil de expresar emociones.

 

Cartoon 2D

Incluye una variante de cartoon occidental tipo sitcom, inspirada en la estética de Los Simpson sin copiarla.

 

Semi-realistic

Más parecido a la persona, menos exageración.

 

Pixel / Block

Roblox, Minecraft y estética retro.

 

Crochet

Una identidad visual artesanal, con textura de lana.

Mi criterio sería mantener los mismos seis estilos de marca en 2D y 3D cuando tenga sentido, pero permitir que cada uno tenga una representación propia.

4. La arquitectura que propongo para MEYA

Aquí está lo interesante: podemos hacer que los dos sistemas compartan el mismo cerebro.

MEYA Digital Being

Identidad · Memoria · Personalidad · Herramientas

Conversation / Animation Controller

Audio · Texto · Emociones · Visemas · Gestos

2D

Kugutu / Iki

SVG / WebGL · boca · ojos · expresiones · gestos

3D

Three.js

GLB · morph targets · rig · expresiones · gestos

Mismo audio TTS y mismo agente

El navegador anima el personaje localmente

La generación de la identidad visual se realiza una vez. Después, el personaje se descarga desde R2 y la animación ocurre en el dispositivo.

¿Y cómo se mueve la boca?

Tenemos tres niveles posibles:

Método

	

Resultado

	

Coste de ejecución




Audio RMS / frecuencia

	

Boca abre y cierra, aproximada

	

Mínimo




Visemas con tiempos

	

Forma de boca según pronunciación

	

Mínimo




Modelo de IA tipo MuseTalk

	

Vídeo facial mucho más realista

	

GPU

Para MEYA empezaría con el segundo. Si nuestro proveedor TTS no devuelve visemas, utilizaría el análisis de audio como alternativa.

5. Mi recomendación: no reemplazaría MuseTalk todavía

Haría algo más inteligente: dos modalidades 2D.

2D Interactive

Principal

Personaje ilustrado, rig por capas, SVG o WebGL, animación local y lip-sync. No hay generación de vídeo durante la conversación.

2D Photorealistic

Mantendría MuseTalk como opción para quien quiera una fotografía que habla de manera realista. Su coste y latencia se justifican cuando la fidelidad visual sea el producto, no como requisito para cada conversación.

6. Plan de prueba técnica

No dedicaría semanas a desarrollar un motor propio sin antes comparar los proyectos existentes.

Prueba

	

Tecnología

	

Qué queremos comprobar




A

	

Kugutu

	

Personaje conversacional en React




B

	

Iki

	

Calidad de deformación, rig y movimiento




C

	

Doll Studio

	

Transformar ilustración generada en personaje por capas




D

	

LipSync Engine

	

Sincronización con audio real del TTS

Prueba de aceptación: generar un personaje humano a partir de una imagen, hacerlo respirar, parpadear, mirar, sonreír, hablar con una voz real y ejecutar todo en Safari de un iPhone sin GPU remota.

Mi apuesta técnica inicial sería:

Kugutu para probar la experiencia y la integración React.

Iki para explorar una fábrica de personajes 2D más sofisticada y automatizable.

LipSync Engine para la sincronización de audio.

Three.js se queda como motor 3D.

Una última consideración: el proyecto que más me interesa no es necesariamente el que mejor anima hoy, sino el que nos permita generar personajes automáticamente. Iki y Kugutu tienen una ventaja conceptual: describen sus personajes mediante datos y estructuras que un agente de programación puede crear o modificar.

Esto podría permitir que Avatar Factory genere tanto el avatar 2D como el 3D desde una misma identidad. Sin pagar por generación de vídeo en cada conversación.

Como siguiente paso, prepararía un pequeño benchmark técnico con esos cuatro proyectos y una misma cara, voz y conversación, para decidir con resultados reales cuál incorporamos a MEYA.

ChatGPT es una IA y puede equivocarse.

## Links
GitHub / Kugutu -> https://github.com/neka-nat/kugutu?utm_source=chatgpt.com
Demo Studio -> https://kugutu-studio.vercel.app/?utm_source=chatgpt.com
GitHub / Iki -> https://github.com/zeikar/iki?utm_source=chatgpt.com
Demo -> https://zeikar.dev/projects/iki/?utm_source=chatgpt.com
GitHub / Doll Studio -> https://github.com/link-ding/doll-studio?utm_source=chatgpt.com
GitHub / idle-web-animation -> https://github.com/broening/idle-web-animation?utm_source=chatgpt.com
GitHub / Amoner/lipsync-engine -> https://github.com/Amoner/lipsync-engine?utm_source=chatgpt.com
Ver Wireface 2D -> https://wireface.dev/2d/?utm_source=chatgpt.com
