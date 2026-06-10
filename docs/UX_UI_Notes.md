# UX/UI Notes – Avatar Creation Flow

## EJECUTAR
./scripts/dev.sh

## Objetivo
Crear un onboarding premium y cinematográfico para generar identidades digitales con foto, video o prompt, manteniendo la lógica del backend existente.

## Principios UX
- Identity-first: el usuario siente que crea su “yo digital”.
- Progressive revelation: no exponer pipeline técnico.
- Cinematic feedback: transiciones suaves, iluminación y estados expresivos.

## IA del producto
Rutas principales:
- `/` landing con hero cinematográfico
- `/create/method-select` selección de método
- `/create/upload-photo` carga de foto
- `/create/upload-video` captura o subida de video
- `/create/prompt-avatar` prompt creativo
- `/create/processing-live` formación de identidad
- `/create/identity-preview` preview interactivo
- `/create/refine` ajustes finos
- `/create/full-avatar-studio` estudio completo
- `/create/export` exportación

## Diseño visual
- Base oscura (#0B0F17)
- Acentos neon (cyan / violet)
- Glassmorphism, blur suave, sombras profundas
- Tipografía Inter/SF Pro, headings grandes

## Estados y copy
- “Identity Formation Mode” para procesamiento
- “Your digital identity is ready” en preview
- Copy guiado en photo/video capture

## Integración backend
- Se conserva `POST /upload` y `POST /job` con `input_type`.
- El frontend mantiene las validaciones mínimas de tamaño y duración.

## Notas
- Rutas antiguas (`/upload`, `/dashboard`, `/avatar/[id]`) redirigen al flujo nuevo.
