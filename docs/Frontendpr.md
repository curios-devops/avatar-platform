Aquí tienes un PR listo para un agente AI frontend (tipo “UI Builder Agent”) para implementar tu onboarding + creación de avatar estilo MetaHuman + premium AI studio.

Incluye:

* estructura de producto
* referencias visuales (UI inspiration real)
* comportamiento de animaciones
* layout system
* estados
* copy
* guidelines para implementación

⸻

📦 PR: Avatar Creation UX (Photoreal AI Human Generator)

🎯 Objective

Build a premium, cinematic onboarding + creation flow for a photorealistic AI avatar generator using Gaussian Splat / NeRF-based reconstruction.

The experience should feel like:

* MetaHuman Creator (Unreal Engine) → precision + realism
    https://www.metahuman.com/create  ￼
* Runway ML → AI magic + simplicity
* Apple Vision Pro onboarding → spatial + calm premium UI
* Midjourney → minimal input → powerful output
* Arc Browser onboarding → smooth, animated transitions
* Figma prototyping feel → clean layout + fast iteration

⸻

🧠 Core UX Philosophy

1. “Identity-first, not tool-first”

User should feel:

“I am creating my digital self”

NOT:

“I am uploading media to generate a model”

⸻

2. Progressive revelation (critical)

Never show:

* Gaussian splat
* mesh reconstruction
* rigging pipeline

Instead reveal:

* “We are understanding your face”
* “We are building your digital identity”
* “Your avatar is forming”

⸻

3. Cinematic feedback loop

Every step must include:

* motion
* morphing geometry
* soft UI transitions
* micro visual artifacts of 3D reconstruction

⸻

🧩 INFORMATION ARCHITECTURE

/landing
/create
  /method-select
  /upload-photo
  /upload-video
  /prompt-avatar
  /processing-live
  /identity-preview
  /refine
  /full-avatar-studio
  /export

⸻

🧭 FLOW SPECIFICATION

1. Landing (Hero experience)

Layout

* Fullscreen WebGL face mesh looping slowly
* Soft volumetric light
* Subtle scan lines

Copy

Create your digital human
Photoreal avatars from photo, video, or imagination

CTA:

* [ Create Avatar ]

Secondary:

* Watch demo

⸻

Visual references:

* Apple Vision Pro landing aesthetics
* https://www.apple.com/apple-vision-pro/
* Runway landing UI

⸻

2. Method Selection Screen

Grid cards (glassmorphism + hover depth)

[📷 Photo]  →  “Best for realism”
[🎥 Video]  →  “Best for accuracy”
[✨ Prompt] →  “Best for creativity”

Interaction:

* hover = card “breathes”
* click = expands full screen

⸻

3A. Photo Upload Flow

Layout style: MetaHuman-like structured simplicity

Reference:
MetaHuman character creation flow
https://www.metahuman.com/create  ￼

⸻

UI

* drag & drop zone (center)
* webcam capture fallback
* live preview thumbnails

Guidance copy

For best results:
- neutral expression
- front-facing light
- no filters or sunglasses

Upload states

* empty → “Drop your face here”
* uploading → “Reading facial structure…”
* complete → thumbnail morph into 3D blob

⸻

3B. Video Capture Flow

UI

* full screen camera
* guided motion path overlay (arc line)

Instructions

Slowly turn your head left → right
Keep eyes level

Real-time feedback

* face tracking dots
* silhouette mesh forming behind user face

⸻

3C. Prompt Flow

UI style: Midjourney minimal input

Describe your avatar
"A futuristic photographer with soft cinematic lighting..."

Settings chips:

* realism level
* age range
* style preset

⸻

⚙️ 4. LIVE PROCESSING (KEY DIFFERENTIATOR)

This is the most important screen.

DO NOT use loader.

Use:

“Identity Formation Mode”

Layout

* central evolving 3D head (Gaussian splat proxy)
* floating system feedback nodes
* soft particles assembling into face

⸻

Status pipeline (animated steps)

Detecting facial structure...
Mapping geometry...
Estimating depth field...
Constructing volumetric identity...
Generating skin response model...
Aligning expression space...

⸻

Reference inspiration:

* Unreal Engine MetaHuman pipeline UX
* https://www.metahuman.com/create  ￼
* Runway Gen-2 loading animations

⸻

👤 5. IDENTITY PREVIEW (CRITICAL MOMENT)

This is the “wow moment”.

Layout

* full 3D interactive head
* orbit + zoom
* cinematic lighting rig

⸻

UI panels (floating glass cards)

Left:

* similarity score
* identity confidence

Right:

* sliders:
    * age
    * skin detail
    * symmetry
    * realism intensity

⸻

Copy

Your digital identity is ready
We estimate this is you with 93% similarity

⸻

Interaction behavior

* slider change → avatar instantly morphs
* no reloads
* real-time shader update

⸻

🧍 6. FULL AVATAR STUDIO

Reference:
MetaHuman Creator editing system
https://www.metahuman.com/create  ￼

⸻

Layout

Left panel:

* face
* hair
* skin
* expression
* voice

Center:

* full body avatar viewer

Right:

* outfit system

⸻

Style system

Categories:

* Realistic
* Cinematic
* Cyberpunk
* Fashion
* Corporate
* Fantasy

⸻

🎥 7. EXPORT / USAGE SCREEN

UI

* “Your avatar is ready”

Options:

* Download model
* Animate
* Use in video
* API access

⸻

Motion

Avatar performs subtle idle behavior:

* breathing
* blinking
* micro expressions

⸻

🎨 DESIGN SYSTEM (IMPORTANT FOR AGENT)

Visual Style

* dark UI (#0B0F17 base)
* neon accent (cyan / violet)
* glassmorphism layers
* soft blur depth fields

⸻

Typography

* Inter / SF Pro
* large headings (48–72px)
* minimal labels

⸻

Animation rules

* 300–600ms easing
* spring-based transitions
* no abrupt cuts
* always morph, never replace

⸻

Lighting style

* volumetric soft light
* rim lighting on avatars
* subtle HDR environment reflections

⸻

🧪 COMPONENTS LIST (FOR FRONTEND AGENT)

AvatarCanvas (Three.js / R3F)
FaceScanOverlay
IdentityPipelineTimeline
UploadZone
CameraCaptureComponent
PromptInputAI
SliderMorphControls
AvatarStudioLayout
ExportPanel
GlassCard
ProgressMorphBar

⸻

⚡ CRITICAL UX RULES

1. Never show technical terms to user
2. Never show loading spinners alone
3. Always show partial avatar evolution
4. Always keep 3D element visible
5. Every step must feel like “identity transformation”

⸻

🧭 FINAL PRODUCT POSITIONING

This should feel like:

“MetaHuman meets Midjourney meets Apple Vision Pro”

Not:

* “3D model generator”
* “AI reconstruction tool”
* “Gaussian splat pipeline”