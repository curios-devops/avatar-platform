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

**Pilot 2 (2026-11-19), below: the verdict was still "AI slop"** (only a mouth patch moves; teeth a white strip; a seam
on the realistic face; no age in the face). The fix piloted here: **the whole face changes**, from 8 full-face key poses
per character made by an image-edit model, morphed in the browser. It works for the film and semi-realistic styles
and for crochet; clay still fails the "no wrinkles" rule.

## Pilot 2: whole-face expression keyframes (2026-11-19)

### What changed

```
creation (once per character, Mac, ~5 min)                     call (every frame, browser, 0.3 ms)
portrait --FLUX.2 [klein] 4B edit (kf.py)--> 7 key poses         viseme weights + smile + laugh + blink channels
  talk_mid, aa, OU, E, MBP, laugh, blink (+ rest = portrait)       -> keyframe weights, upper face and lower face apart
  -> kfprep.py gate: landmark drift + outside-face drift + eye     -> one interpolated mesh (keyframe meshes aligned to
  -> kfprep.py adopt: colour mean matched, MediaPipe mesh            rest on stable points, blended per vertex)
     per keyframe (kf/index.json)                                  -> portrait warped to it (hair, neck, backdrop), the
                                                                      face oval cut with a feathered mask and refilled
                                                                      with the 2-4 nearest keyframes, each warped from
                                                                      its own mesh: no patch, no seam (morph.js)
```

- **Edit model: FLUX.2 [klein] 4B**, `mflux-community/flux2-klein-4b-mflux-q4` (Apache-2.0, base
  `black-forest-labs/FLUX.2-klein-4B`; 4.62 GB download; mflux 0.24 `Flux2KleinEdit`, 4 steps, guidance 1). The
  portrait is the only reference image; no reference photo, brand or real person went into any prompt.
- **Time and memory (M2 Pro 16 GB)**: 53 s per keyframe at 768 px (film_w), **31 s at 640 px** (the other three),
  new portraits 27 s at 768 (text-to-image, same weights). MLX peak 3.5 to 5.3 GB. 56 images in 31 min of compute,
  ~65 min wall clock with cool-downs and restarts. The watchdog stopped the first runs three times (memory pressure
  "warn" for 15 s at the first denoising step; the Mac had 4 GB in swap and 3.4 GB in the compressor from other apps);
  what fixed it: the 4B text encoder dropped after encoding each batch, tiled VAE, MLX cache 256 MB, 640 px with a
  640 px reference, and no Chrome tab open while generating. One process (`kf.py serve`) works through a job queue.
- **Runtime (`morph.js`)**: visemes map to keyframes (sil rest, PP MBP, FF MBP+talk, TH/DD/SS/nn talk, kk talk+aa,
  CH/RR talk+OU, aa, E, I E+talk, O OU+aa, U OU); laugh and smile channels; blink. Upper and lower face have their own
  weights (the mesh vertex's region mixes them), so a blink does not freeze the mouth. Shape weights are smoothed
  (35/60 ms); the colour weights are sharpened (power 40 on the eyes, 10 on the mouth), because a half-way
  cross-fade shows two sets of eyes or faint teeth on closed lips. A per-pass depth test stops folded triangles at the
  laugh's mouth corners from being added twice (bright streaks in the first try). Clay and crochet use
  `mode: 'replace'`: the strongest keyframe per region swapped in hard, decided on twos (12 Hz, each face held 2 frames
  of 24), head motion stepped the same, no morph.
- New characters (original): `semi_m` Dario (semi-realistic painted illustration, ~40, warm key and cool rim, stubble,
  crow's feet), `clay_w` Greta (plasticine stop motion), `crochet_m` Bruno (amigurumi). Prompts, seeds, seconds and
  peaks of every image: `chars/<id>/kf/gen.jsonl`; gate numbers: `kf/raw/gate.json`; which raw became which pose:
  `kf/index.json` (`src`).

### Numbers (Chrome, M2 Pro, 120 Hz, canvas 1216x1520; voice line + a 1.4 s laugh)

| Character | Engine | fps median / p5 | main-thread ms mean / p95 | load | lag (line without laugh) |
|---|---|---|---|---|---|
| film_w | sprites (old) | 120 / 111 | 0.65 / 1.1 | 182 ms | +50 ms |
| film_w | morph | 120 / 112 | 0.28 / 0.6 | 161 ms | +83 ms |
| semi_m | morph | 120 / 112 | 0.36 / 0.6 | 124 ms | -67 ms (drawn: -67) |
| clay_w | replace | 120 / 108 | 0.35 / 0.5 | 109 ms | +117 ms |
| crochet_m | replace | 120 / 109 | 0.34 / 0.6 | 117 ms | -50 ms |

The morph is cheaper than the sprites (one mesh, 3 to 5 draws of ~900 triangles). It costs ~16 to 33 ms of extra lag
from its own weight smoothing, and the 12 Hz hold of the replacement faces costs ~50 ms more; both can be paid back
with the bus's lead offset. Keyframes are 0.5 to 1.2 MB PNG each (7 per character plus the portrait, 5 to 7 MB; webp would cut that several times; not tried).

### Verdict per character, against the four rules (judged on `shots/compare.png`, `shots/kf_poses.png`, harshly)

| Character | 1 whole face moves | 2 teeth | 3 seam | 4 age | Overall |
|---|---|---|---|---|---|
| film_w Lia (round 1) | **yes**: real jaw drop (chin 15 % of face width down), cheeks up and eyes into crescents in the laugh, smile cheeks on E | individual upper teeth, lower row partly hidden; gum hint faint | none visible | n/a (twenties, no wrinkles: correct) | **pass**: the laugh is the clearest win over the old puppet |
| semi_m Dario (3 rounds) | **yes**; laugh with eyes squeezed, brows down, cheeks up | individual upper teeth with ink outlines; lower row shows more than asked | none on the cel shading | **yes**: crow's feet and nasolabial folds at rest, deeper in E and laugh | **pass** after round 2 (round 1: teeth in MBP and OU, a closed grin as laugh) and round 3 (round 1-2 talk pose was a clenched grimace) |
| clay_w Greta (3 rounds, stop) | yes (replacement faces) | separate clay teeth | none | **fail**: the laugh still has crow's feet and forehead folds; aa sticks the tongue out (rejected, aa falls back to talk) | **fail on rule 4**; round 1-2 also turned clay into human skin, fixed in round 3 with a simpler puppet head |
| crochet_m Bruno (round 1) | yes (replacement faces); laugh and blink become stitched lines | felt teeth, separate | none | no wrinkles: correct | **pass**, with a stop-motion "boil": the beard's bulk changes between faces |

Best sheets: `chars/film_w/shots/compare.png` (row 1 old sprites, row 2 morph; same timeline, laugh at the end),
`chars/semi_m/shots/compare.png`, `chars/crochet_m/shots/compare.png`; key poses: `chars/<id>/shots/kf_poses.png`.

### Still failing

- **Transition frames**: the frame where the laugh comes in (rest to laugh at about half weight) still shows a dirty
  mouth: the laugh's dark mouth squeezed into a half-open shape. One frame at 60 fps, visible on a still.
- **Rule 4 on clay**: the edit model draws human creases on any laugh; three prompt rounds did not stop it.
- **Identity drift is small but real**: faces get slightly rounder in the laugh and the beard on crochet changes bulk;
  the backdrop tone shifts 5 to 15 levels (matched on the face, not used outside it).
- **Not covered**: game_w (the realistic seam of rule 3) was not regenerated with keyframes; the eyes no longer
  saccade on replacement faces; no smile when listening (no closed-smile key pose); Safari and phones untested.
- **Lag numbers** for the male characters use a different voice clip than the female ones (as in pilot 1).

## Nico "Lucky" Moretti, a new character on the keyframe morph (2026-11-19)

`nico`: an original AI character, a creator who covers a crime sandbox game from **Sol Harbor**, an invented coastal
city. Painted crime-game loading-screen style (cel-painted planes, ink lines, warm key, cool rim, dark plain
backdrop), American man of about 30, fair skin, short messy dark-brown hair, light blue eyes, square jaw, stubble, a
plain white t-shirt and a silver chain, framed **4:5 from the head to mid-chest** (the first non-square character).
No reference image, logo, brand, real person or game name went into any prompt. Page:
`http://127.0.0.1:8791/puppet/?char=nico` (a character with keyframes now opens on its keyframe engine).

**Made with** FLUX.2 [klein] 4B q4, the pilot 2 setup (`kf.py serve`, one process, text encoder dropped, tiled VAE),
under `watch.sh` with the load allowance cut to the same 3 checks (`LOAD_LIMIT=3`) and the swap guard at 600 MB for the
last job (`SWAP_MB`). Prompts, seeds, seconds and MLX peaks: `chars/nico/kf/gen.jsonl`; gate numbers:
`chars/nico/kf/raw/gate.json`; which raw became which pose: `chars/nico/kf/index.json`.

| Step | Size | Time per image | MLX peak | Notes |
|---|---|---|---|---|
| Portrait, 2 rounds x 4 seeds | 640x800 | 25 s | 3.1-3.2 GB | 768x960 was stopped by the watchdog; round 1 (71-74) read as clean vector comic art, round 2 asks for gouache-like posterized brush strokes; **seed 76** chosen (asymmetry, a hint of a smirk, the most "painted") |
| Keyframes, 2 rounds, 15 edits | 512x640 (ref 512x640) | **27-28 s** | 3.9-4.3 GB | 640x800 and 576x720 edits were stopped at the first denoising step (memory pressure "warn" 15 s); 512x640 with the MLX cache at 0 (`MLX_CACHE_MB=0`) passed |

Generation 14:47 to 15:06 (19 min wall, ~10 min of compute). The watchdog stopped the process 5 times (all
memory pressure, never heat); other apps held ~4.5 GB in the compressor (a dev server, Chrome, another session's
tests) and swap reached 4.8 GB, so round 3 was not run and `blink` stayed on round 1.

**Key poses (9)**: rest (the portrait), talk_mid (`talk_soft`), aa, OU (`OU3`: a gentle "you", not a pucker), E (`E2`:
the wide grin), MBP, laugh (`laugh2`), blink, and a new **smirk**: a closed-mouth confident smile for listening.
`morph.js` takes `smirk` as an optional 9th key: the listening share of the lower face (and 60 % of the upper face)
moves to it; `app.js` eases it in over ~0.6 s when he stops talking and out in ~0.1 s when he speaks. Characters
without it are unchanged (it falls back to rest).

Rejected on sight (round 1): talk, OU and MBP had his stubble shaved off and the face airbrushed (the "smooth skin,
no wrinkles" line did it; round 2 says "no wrinkles" and "keep the same stubble and brush texture"); OU2 was duck
lips. Gate: every adopted pose passes (stable 0.6-1.8 %, out 5.5-6.3).

**Voice** (`nico_voice.py`, the `fetch_timed.py` recipe: `stream/with-timestamps`, eleven_v4_turbo, no tags):
ElevenLabs premade **Liam** (young, American, "social media creator"). 4 lines, 495 characters, 247 credits billed
(about 0.05 USD). Clips: `../lipsync/clips/nico_{en_1,en_2,es_1,es_2}.json` (text, alignment, stream log; the mp3s stay
local). The "Ha ha!" in `nico_en_1` is marked in the JSON (`laughs`: start and length from the alignment) and drives the
laugh channel on the heard-audio clock.

- EN 1: "Yo, what's up, Sol Harbor! Nico here, your favorite AI, so I have zero excuses for crashing. Ha ha! Quick tip:
  park the getaway car facing the exit. Trust me."
- EN 2: "Real talk: stop driving into the ocean. The jet ski is right there, man. Stick around and I'll show you where."
- ES 1: "¡Qué onda, Sol Harbor! Soy Nico, una IA con muy buen gusto. Tip rápido: guarda el coche antes de la misión. De
  nada, bro."
- ES 2: "Sí, ya sé: otra vez perdiste la moto en el puerto. Tranqui, en treinta segundos te enseño dónde reaparece."

**Numbers** (Chrome, M2 Pro, canvas 1216x1520): 120 fps median (p5 102), 0.34 ms main thread per frame (p95 0.6);
lag -67 ms (`nico_en_1`) and -50 ms (`nico_es_2`); listening 0.28 ms per frame.

**Sheet**: `chars/nico/shots/sheet_nico.png` (`__puppet.poseSheet()`): row 1 the nine held poses, rows 2-3 a
12-frame timeline of `nico_en_1` with its laugh at 6.6 s and the smirk once he stops. `shots/live_listen.png`: the
live page while listening.

**Verdict, harshly.** Looks: a good-looking, likeable face with a real grin and the chain and t-shirt intact in
every pose; the smirk and the laugh sell the character. Slop: the portrait itself still reads as a polished "AI comic
portrait" more than a hand-painted loading screen, and the edits at 512 px lose some of its brush texture (the face
is a little smoother and more vector-like than the rest pose, visible when it cross-fades). Teeth: separate and
softly shaded in E and laugh, lower row partly hidden: pass.

**Still failing**
- **Laugh wrinkles**: both laugh rounds have strong crow's feet and creases on the forehead and nose bridge, more than
  "light, at 30"; E2 and smirk are within bounds. Same failure as clay: the edit model draws a laugh with creases.
- **O viseme**: O is OU 0.6 + aa 0.4; Nico's OU is nearly closed, so the blend stretches it open into a pink slot.
  A per-character viseme map (O to OU only) or a rounder OU key would fix it.
- **Transition frames**: the grey half-teeth when the mouth passes between keys (pilot 2's open issue) shows on E.
- Generated at 512x640 and upscaled to 640x800: soft on a large screen; needs a quieter Mac (or a GPU) for 768+.

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

# pilot 2: keyframes (FLUX.2 klein 4B q4, mfvenv2), one process, a job queue; one heavy job at a time
lab/arena5/puppet/kfrun.sh &                                             # caffeinate + watchdog + kf.py serve
<mflux-py> lab/arena5/puppet/kf.py add portrait semi_m 41 42             # new character (text to image)
SIZE=640 <mflux-py> lab/arena5/puppet/kf.py add kf semi_m [pose ...] [--tag r2]   # edits of chars/<id>/kf/ref.png
<mflux-py> lab/arena5/puppet/kf.py quit
backend/.venv/bin/python lab/arena5/puppet/kfprep.py gate semi_m        # then look at every raw image
backend/.venv/bin/python lab/arena5/puppet/kfprep.py adopt semi_m [pose=raw_name ...]; ... prepare.py
# page: ?char=film_w&mouth=morph (clay, crochet: mouth=replace); Laugh button; __puppet.compare({id}) writes
# chars/<id>/shots/compare.png (old engine vs new, same offline timeline, laugh at the end)
# nico: SIZE=640x800 ... add portrait nico 76; SIZE=512x640 ... add kf nico talk_soft aa OU3 E2 MBP2 laugh2 blink smirk
# (MLX_CACHE_MB=0 for kf.py serve); python3 lab/arena5/puppet/nico_voice.py; page ?char=nico, __puppet.poseSheet()
```
