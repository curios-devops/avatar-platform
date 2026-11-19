# Styled portrait puppet (arena 5, primary candidate, 2026-11-16 to 2026-11-19)

**Question.** Can a MEYA character talk in real time in the person's browser, rendered locally from one styled portrait,
with no GPU server and no paid API during the call, and still look like MEYA's three styles while it talks?

**Answer.** Yes for **Animated Feature Film** (MEYA's default): the talking frames keep the portrait's look, and with
the generated mouth sprites the open mouth looks like it belongs to the character. **Anime 3D**: yes, with a simpler
mouth that reads as stylised, which suits the style. **Realistic Game Character**: only partly: the face, eyes and
head motion hold up, but the drawn inner mouth gives a realistic face away when it opens; the sprites close most of that
gap (see below), and the limit of a 2D puppet (head turns of a few degrees only) is most visible on a realistic face.
It runs at the display's 120 fps on the M2 Pro with about 0.55 ms of main-thread work per frame, and the mouth is on the
voice within the lip-sync test's numbers (+67 / -67 ms, the same as method C there).

## What was built

```
creation (once per character)                       call (every frame, in the browser)
portrait (Z-Image-Turbo, local)                     mouth-driver.js 'text' (../lipsync, unchanged): visemes from the
  -> prepare.py: MediaPipe 478 landmarks (JSON)       TTS character timestamps on the heard-audio clock, 50 ms lead
  -> puppet renders each mouth shape (drawn mouth)  idle.js: blinks, saccades, head noise, nods, brows, breathing, smile
  -> gen.py mouths: img2img on a mouth crop          puppet.js: deform ~700 vertices on the CPU, 3 WebGL2 draws
     (optional: sprite technique)
```

- `puppet.js`: the renderer. Mesh = MediaPipe's 852 face triangles (the mouth and eyes are holes there), a fan filling
  each eye around the iris centre, and 6 rings scaled from the face oval out past the image edge (hair, neck,
  shoulders, backdrop). Motion = 11 per-vertex bases built from the landmarks once (jaw, lip part, upper-lip lift for
  teeth, width, round, press, lower-lip tuck, smile, brows, a blink per eye), then a small 3D head rotation using
  MediaPipe's landmark depth for parallax (yaw, pitch, roll of 1 to 4 degrees), then breathing on the shoulders. Gaze
  moves the iris with a fragment-level warp inside each eye ellipse. The inner lips are welded on their midline at rest,
  so a portrait with a slight lip gap shows no seam when closed.
- `idle.js`: speaking mode (more head motion that follows the mouth's energy, looks away at phrase starts, brow lift on
  phrase onsets) and **listening** mode (eye contact with micro-saccades, a nod every 3.5 to 7.5 s, slight tilt, soft
  smile). Blinks every 2 to 6 s, sometimes double.
- `app.js`, `index.html`: one page; character (grouped by style), mouth technique, voice line; live fps, main-thread ms
  per frame (mean / p95), audio-to-mouth lag of the last line, current viseme. `window.__puppet` scripts it
  (`speak`, `freeze`, `capture`, `sheet`, `exportPre`, `detect`). `measure.js` is the scripted run used here.
- `gen.py` + `run.sh` + `watch.sh`: Z-Image-Turbo q4 (mflux) under the watchdog and `caffeinate`, the pattern of
  `lab/backgrounds/gen.py`. `prepare.py`: landmarks (MediaPipe Face Landmarker, Python, CPU). `serve.py`: static server
  with one write endpoint limited to `chars/`.
- No third-party runtime code: the puppet is ~700 lines of our own JS. MediaPipe tasks-vision 0.10.14 (Apache-2.0) is
  only loaded from jsDelivr by `__puppet.detect()`, to show the browser gets the same landmarks as `prepare.py`.

## The characters (original, generated locally)

| Style | Woman | Man |
|---|---|---|
| Animated Feature Film | `film_w` Lia: light-brown skin, dark curly updo, big brown eyes | `film_m` Teo: deep dark-brown skin, coiled hair, beard |
| Realistic Game Character | `game_w` Mei: East Asian, black ponytail, olive jacket | `game_m` Rowan: fair skin, auburn hair and beard |
| Anime 3D | `anime_w` Sora: silver-lavender hair, teal eyes, cardigan | `anime_m` Kai: tan skin, spiky hair with orange highlights |

Prompts are in `gen.py` (style block + person + a common block: front-facing, neutral, lips closed, eyes on camera,
plain backdrop, no logos). No reference to any studio, character or real person. One regeneration each for the two
anime characters: the first tries read as teenagers (one in a sailor-collar school uniform), so the prompts now say
"clearly adult" with adult clothes. All six were accepted on the first or that second try.

## Generation: time and memory (M2 Pro 16 GB, Z-Image-Turbo q4, 9 steps)

| Run | Size | Time per image | MLX peak | Notes |
|---|---|---|---|---|
| Portraits | 1024x1024 | 150 s (16.4 s per step) | 4.6 GB | the 2nd image tripped the watchdog (memory pressure "warn" 15 s) with the usual apps open; its file was cut mid-write |
| Portraits | 896x896, tiled VAE | 113 to 120 s (12.4 s per step) | 4.4 GB | one process per image from then on, so memory is released between images; model load + prompt encoding 7 to 13 s |
| Mouth sprites | 512x512 crop, strength 0.42 | 23 to 24 s | 7.2 GB | 5 per character, 210 s for the five in one process |

Lowest free memory seen by the watchdog during the mouth runs: 26 % (film_w) and 24 % (game_w), swap +199 MB; 1 to 2 short "warn" readings per run, never sustained. One heavy job at a time
throughout; the browser tab was blanked during generation. The 1024 portrait of `film_w` is kept; the other five are 896.

## Mouth techniques compared (same character, same voice line)

1. **Drawn inner mouth** (`mouth=drawn`): a procedural layer under the lips, drawn in the fragment shader from the
   warped inner-lip corners and midpoints: dark cavity tinted from the lip colour, upper teeth hanging from the upper
   lip (longer for F/V), lower teeth when the jaw is well open, a tongue that lifts for T/D/N/L, a soft shadow inside
   both lips. Automatic for any face, 0 creation cost.
2. **Generated mouth sprites** (`mouth=sprites`): the puppet renders the character at 5 shapes (mid, aa, E, O, FF)
   with the drawn mouth, and a 512 px crop around the mouth is refined by Z-Image image-to-image at strength 0.42 with
   a mouth-only prompt, then pasted back with a feathered edge. Because the input already has the warp's geometry, the
   sprite lines up with the mesh: MediaPipe on the sprite finds the lip points within 0.7 to 1.6 % of the mouth width
   of the pre-render for mid, aa and E, and 2.7 to 3.2 % for O and FF (`prepare.py check`). At run time each sprite is
   mapped through the same deformed mesh (its UVs are the mesh at its own pose), and the sprites are blended by
   distance in pose space (open, width, round, tuck, teeth, press) over the lips and the hole, feathered at 0.55 to 0.95
   mouth widths.

**Result: the sprites win**, modestly on the film style and clearly on the realistic style. On `film_w` both read
well in motion; the sprites give shaded, rounded teeth, a gum line and lips that continue into the opening, where the
drawn layer looks slightly cut out. No ghosting or teeth popping was visible between shapes in the 2 s sheets (the
blend is between images of the same teeth). Costs: 2 to 3 minutes of local generation per character, and a slightly
soft area under the nose (the crop is upscaled from 512). The FF sprite did not produce a real lip tuck (neither does
the drawn layer much): F/V reads as "lips nearly closed with teeth". The drawn mouth stays as the automatic fallback
for a new character until its sprites exist.

**Realistic style (`game_w`)**: here the sprites are the difference between "uncanny" and "plausible". The drawn
teeth look like a graphic on photoreal skin; the sprites give real enamel, lip volume and shadow. Image-to-image drifts
more on a realistic face: lip points moved 1.5 to 4.1 % of the mouth width for mid, FF, E and aa, but **12 % (max 23 %)
for O**, so the O sprite was rejected by the gate (kept as `mouth/_rejected_O.png`) and O is blended from its
neighbours; it is passable (teeth show inside the O). Compare `chars/game_w/shots/drawn_still_aa.png` with
`sprites_still_aa.png`.

## Numbers (Chrome, M2 Pro, 120 Hz display; text-timed visemes, 50 ms lead)

| Character | Mouth | Canvas | fps median / p5 | main-thread ms per frame mean / p95 | lag (r) |
|---|---|---|---|---|---|
| film_w | drawn | 1216x1520 (608 css px, dpr 2) | 120 / 109 | 0.53 / 1.0 | +67 ms (0.38), nova_es |
| film_w | sprites | 1216x1520 | 120 / 108 | 0.56 / 1.0 | +67 ms (0.38) |
| film_m | drawn | 1216x1520 | 120 / 111 | 0.52 / 0.9 | -67 ms, imani_en |
| game_w | drawn | 1216x1520 | 120 / 112 | 0.56 / 1.0 | +67 ms |
| game_m | drawn | 1216x1520 | 120 / 108 | 0.59 / 1.0 | -67 ms |
| anime_w | drawn | 1216x1520 | 120 / 111 | 0.60 / 1.1 | +67 ms |
| anime_m | drawn | 1216x1520 | 120 / 108 | 0.58 / 1.0 | -67 ms |
| game_w | sprites | 1216x1520 | 120 / 109 | 0.35 / 0.7 | +67 ms |
| film_w | drawn | **390 px** viewport: 716x895 (358 css, dpr 3 capped at 2) | 120 / 110 | 0.52 / 1.0 | +67 ms |
| film_w | sprites | 390 px: 716x895 | 120 / 112 | 0.60 / 1.0 | +67 ms |

Chrome's 4x CPU throttle changed nothing measurable (0.49 ms, 120 fps), so it is not used as a phone stand-in.

- ms per frame is the JS of one frame (driver update + idle + deform + WebGL calls), not GPU time; the frame rate is
  pinned at the display's 120 Hz, so the GPU is not the limit at this size. p95 reads 1.0 ms partly because of the
  timer's 0.1 ms resolution.
- Lag is the lip-sync test's metric on the rendered inner-lip gap; +67 ms on Nova and -67 ms on Imani are exactly what
  that test measured for method C with a 50 ms lead (ElevenLabs' alignment on Nova starts late at the opening "¡").
  r is low by construction for text visemes (see `../lipsync/README.md`).
- Load (local server): a character loads in 33 ms with the drawn mouth and 153 ms with 5 sprites (portrait PNG 0.6 to
  1.1 MB, landmarks JSON 25 KB, sprites the size of the portrait). MediaPipe in the browser (`__puppet.detect()`,
  tasks-vision 0.10.14 from jsDelivr) gives the same 478 points as `prepare.py` (mean 0.01 px, max 0.02 px) in 110 ms
  after a 275 ms runtime load, so creation can run entirely on the device. As webp the portrait would be about 0.1 to 0.2 MB.
- Male characters spoke with the female timed clips (only three timed clips exist); the mouth does not care.

## What it looks like, per style (judged by eye on the stills and the 2 s sheets)

| Style | While talking | Failure modes seen |
|---|---|---|
| Animated Feature Film | **reaches the reference look.** The talking frames are the portrait: same skin, hair, eyes, light; blinks, gaze and nods keep it alive; the listening state (soft smile, tilt, nods) is convincing | head turns limited to a few degrees; slight softness under the nose with sprites; F/V weak |
| Realistic Game Character | face, eyes and idle motion hold up; **the open mouth is the weak point**: the drawn teeth look graphic on photoreal skin; the sprites fix most of it | uncanny when the drawn mouth opens wide; any rubber-sheet stretch is easier to spot on realistic skin; small head motion reads as "talking photo" |
| Anime 3D | works; anime mouths are simple, the drawn mouth fits | a hard cut-out edge on the opening; a thin brown line at the upper lip on `anime_m` (the seam pixels) |

No rubber-sheet warping was visible at these amplitudes (jaw drop 12 % of the face height, head 1 to 4 degrees), no
mouth seams after welding the lips at rest, no dead eyes (blinks, saccades, iris moves inside the eye). Compared with
the three.js baseline (`../baseline/embed_05_variety_sheet.png`), the puppet is far closer to the reference look in all
three styles, because it animates the styled image itself; the baseline has a full body, free head turns and
gestures, which the puppet does not.

Files to look at (media, not in git), under `chars/<id>/shots/`:
- stills: `drawn_still_{sil,aa,O,FF}.png`, `sprites_still_*.png` (film_w, game_w), listening `*_listening.png`;
- 2 s sheets during speech (12 frames, 1/6 s apart, time and viseme in each tile): `sheet_drawn.png`,
  `sheet_sprites.png`; at 390 px: `sheet_390_drawn.png`;
- best: `chars/film_w/shots/sheet_sprites.png`, `sprites_aa.png`, `sprites_listening.png`;
  `chars/game_w/shots/sheet_sprites.png` vs `sheet_drawn.png`.

## What a product version needs

**1. A person's own photo to a styled portrait with their identity.** Text-to-image (what made these six) cannot keep
a real person's identity. It needs an image-edit model once at creation: input the selfie, output the same person,
front-facing, neutral, mouth closed, in the chosen style.

| Option | Licence (HF API, read 2026-11-16) | Where | Cost per character |
|---|---|---|---|
| **FLUX.2 [klein] 4B** (`black-forest-labs/FLUX.2-klein-4B`), multi-reference edit | **Apache-2.0**, not gated | local: already supported by mflux 0.24 on the Mac (`mflux-generate-flux2-edit`); on a server any 16-24 GB GPU | 0 per image on the device (1 to 3 min on an M2 Pro, to be measured); on a rented GPU about 0.001 to 0.005 USD per image (lab's RunPod price ranges, not re-checked) |
| **Qwen-Image-Edit-2511** (`Qwen/Qwen-Image-Edit-2511`), 20B | **Apache-2.0**, not gated | too large for a 16 GB Mac; server GPU with 40 GB+ (or 24 GB quantised) | about 0.005 to 0.02 USD per image on a rented GPU (estimate) |
| FLUX.2 klein 9B, flux-3 klein, FLUX.1 Kontext [dev], Bria Fibo-Edit | "other": non-commercial or gated terms | | **not usable** without a commercial licence |
| Hosted edit APIs (OpenAI gpt-image, Google's Gemini image model, BFL Kontext Pro, Pruna) | commercial terms of the provider | cloud | a few US cents per image (list prices not re-checked today; none called) |

Identity adapters that need InsightFace (InstantID, PuLID) are out: InsightFace's models are non-commercial. The lab's
gate for identity applies: ArcFace (`benchmark/metrics.py`) between the selfie and the styled portrait, with a lower bar
for stylised styles (Anime will not pass a photo-level ArcFace bar by design). The recommended first probe is FLUX.2
[klein] 4B locally, because it is the only clean licence that runs on the Mac and on a cheap GPU.

**2. The mouth set for a new character, automatically.** The method here is already automatic: after the portrait,
(a) landmarks (MediaPipe, in the browser or on the server, about 100 ms), (b) the puppet renders the 5 mouth poses with
the drawn mouth (in the browser, instantly), (c) one image-to-image pass per pose on a 512 px crop with the style's
mouth prompts (5 x 23 s on the Mac with Z-Image-Turbo, Apache-2.0; seconds on a server GPU), (d) `prepare.py check`
rejects a sprite whose lip points moved more than about 4 % of the mouth width, and the drawn mouth covers that shape.
The character can talk with the drawn mouth from second one and switch to the sprites when they arrive.

**3. The rest of the call:** stream the TTS with character timestamps (`../lipsync/README.md`), feed `setCues()` per
chunk, background compositing behind the portrait's plain backdrop (selfie segmentation, as `poses/background.py`),
and for barge-in, `stop()` closes the mouth through the smoother within about 60 ms.

## Not verified

- **Safari and iPhone**: not run. Only Chrome on the Mac. The renderer is plain WebGL2 with 3 draws and ~2,300
  triangles, so a phone should cope, but no number exists.
- **390 px**: emulated in desktop Chrome (viewport 390 wide, dpr 3 capped at 2), not a phone.
- **ArcFace**: not measured (the characters are generated, not a person's photo); identity of photo-to-style edits is
  untested.
- **A full call**: lines of 3 to 4 s were played, not a 3 min call with an interruption; long-run frame stability and
  live (chunked) cues were not run here (the lip-sync test ran them with the same driver).
- **Sprites** were made for `film_w` and `game_w` only; the other four use the drawn mouth.
- **Image-edit options**: licences read from the HF API; speed, memory and identity of FLUX.2 [klein] 4B on the Mac
  are not measured; hosted prices not re-checked.

## How to run

```
python3 lab/arena5/puppet/serve.py 8791        # then http://127.0.0.1:8791/puppet/?char=film_w&mouth=sprites
lab/arena5/puppet/run.sh portraits [id[@seed]]  # Z-Image under watchdog + caffeinate; one heavy job at a time
backend/.venv/bin/python lab/arena5/puppet/prepare.py   # landmarks + chars/index.json
# in the page: await __puppet.exportPre('film_w'); then: lab/arena5/puppet/run.sh mouths film_w
```
