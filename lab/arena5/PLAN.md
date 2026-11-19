# Arena 5: a talking character that runs on the person's device (plan, 2026-11-15)

Status: plan, plus one entrant built since: the **styled portrait puppet** (section 3.1, `puppet/README.md`), now the
primary candidate. The rest of the plan is unchanged and not built.

Original status: plan only. Nothing installed, cloned or built. Every fact in section 2 was read from the repository, model card or
page on 2026-11-15 (GitHub API, raw README and LICENSE files, Hugging Face API, npm registry); what could not be read is
listed at the end.

## 1. The question and the bar

**Question.** Can a person hold a real-time spoken conversation with a MEYA being whose face and body are rendered and
lip-synced entirely on their own device (MacBook, iPhone Safari), with zero GPU or per-minute API cost to us for the
avatar, and look enough like the being's photo? Which entrant does it best?

Inherited rules: no GPU server during the call; a GPU at creation time only if optional and cents; licences clean for a
commercial product in the EU and the US (no NC weights, no GPL code linked into what we ship; a GPL tool may run offline
if its output is ours; CC0 and CC-BY with credits are fine).

**Pass/fail** (all measured on the same call, section 5; "today" is the baseline's last measured value):

| Measure | How | Pass | Baseline today |
|---|---|---|---|
| Frame rate, M2 Pro | rAF frame times over the whole call, Chrome and Safari | median ≥ 60 fps, p5 ≥ 50 | 105 fps (Chrome) |
| Frame rate, iPhone Safari | Web Inspector timeline, 5 min call | median ≥ 30 fps, p5 ≥ 24, no drop after 5 min | not measured |
| CPU | main-thread ms per frame (performance marks); tab CPU on the M2 (`top`, 1 Hz) | M2 ≤ 4 ms and ≤ 30 % of one core; iPhone ≤ 10 ms | 0.24 ms per frame |
| Turn end → first moving lip | end of the person's turn in the WAV → first frame with mouth aperture above rest | ≤ 1.8 s with ElevenLabs; avatar's own share (first audio sample → first lip) ≤ 100 ms | first audio 1.38-1.62 s |
| Lip timing | cross-correlation of rendered mouth aperture vs voice envelope | lag within ±60 ms | 83 ms late |
| Lip quality | render metric (`a2f/arena4_render_metric.py`): aperture vs voice r; closed on /p b m/; closed in silence | r ≥ 0.65; ≥ 80 % of /p b m/ closed; silence aperture ≤ 1 % | r 0.70-0.71 |
| Identity | ArcFace (`benchmark/metrics.py`) vs the portrait, frontal and 3/4 | 3D ≥ 0.45 (beats 0.41); 2D photo ≥ 0.70 | 0.41 frontal / 0.38 3/4 |
| Barge-in | the scripted interruption | mouth at rest ≤ 200 ms after the being's audio stops | not measured |
| Can be changed | hair, clothes, expression by a text edit | no GPU, no rebuild over 5 s | bake 0.2-0.45 s |
| Creation | portrait → ready character | ≤ 2 min, ≤ 0.01 USD, GPU not required | 11-12 s CPU |
| Download | first load, transferred bytes (Resource Timing) | ≤ 15 MB per character + ≤ 3 MB runtime (gz) | GLB 3.8 MB + 5 MB texture |
| Licence | every file that ships | MIT / Apache / BSD / CC0 / CC-BY; nothing NC; no GPL linked | Apache-2.0 + CC0 + CC-BY |

The lab's visual gate also applies: a side-by-side sheet and a judgement by eye; "it ran" is not a pass.

## 2. Every candidate, verified

Stars and last push are from the GitHub API on 2026-11-15.

### 2.1 From chat 1 (3D)

| Candidate | What it really is (read today) | Code / weights-assets licence | Activity | Runs on | Photo → character | Talks in the browser | Main risk | Verdict |
|---|---|---|---|---|---|---|---|---|
| **MediaPipe Face Landmarker** | 478 3D landmarks, 52 blendshape scores, head transform; Web, iOS, Python | Apache-2.0; both model cards (Face Mesh V2, Blendshape V2) link Apache-2.0 | 37.7k stars, pushed 2026-11-14; `@mediapipe/tasks-vision` 1.2.3 (31 MB unpacked, Apache-2.0) | browser (WASM/WebGL) or CPU | gives the fit targets, not a model | n/a (input tool) | none new; already in the baseline (`human/landmarks.py`) | **IN** (shared component) |
| **MPFB2 / MakeHuman** | Blender add-on that builds parametric humans | code GPLv3; assets CC0; LICENSE section D: output (exports, renders, scripted output) belongs to the user | 704 stars, pushed 2026-11-12; needs Blender ≥ 4.2 | Blender (CPU) | no photo fit of its own; we would write it | yes, via the CC0 "Visemes 02" (Oculus) and "Faceunits 01" (ARKit) packs (released 2026-02-07) and TalkingHead's MPFB rig | GPL code: keep it a build tool, never linked | **IN** (as 3D-A's builder) |
| **Blender headless** | `blender -b -P script.py`; glTF export | GPL tool; output ours (blender.org returned 403, see end) | 5.3.0 released 2026-11-10; macOS arm64 dmg 360 MB, Linux tar 407 MB | CPU | builder only | n/a | needs a server CPU job or the Mac at creation | **IN** (tool) |
| **Rigify** | Blender's rig generator | part of Blender | n/a | Blender | n/a | n/a | not needed: MPFB + TalkingHead ship a Mixamo-compatible rig | **OUT** (not needed) |
| **TRELLIS.2** | image → textured 3D object (O-Voxel), 4B parameters, 512³-1536³ | code MIT, weights `microsoft/TRELLIS.2-4B` MIT. **But** `pipeline.json` loads `briaai/RMBG-2.0` (CC BY-NC 4.0, "non commercial use only", gated) and `facebook/dinov3-vitl16-pretrain-lvd1689m` (custom DINOv3 licence, manual gating), and `setup.sh --nvdiffrast` installs nvdiffrast (NVIDIA "1-Way Commercial": research or evaluation only) | 12.9k stars, pushed 2026-07-10 | Linux only, NVIDIA ≥ 24 GB, verified on A100/H100; 1024³ takes ~17 s on an H100 | yes, but a generic object: no face rig, no known topology | no: needs retopology, body rig and a face rig | licence chain for production; identity of a generated mesh untested; no face animation | **LATER** (one paid probe only if 3D-A misses identity) |
| **Make-It-Animatable** | predicts skeleton, skinning weights and pose for a humanoid mesh (CVPR 2025), v2 branch | code MIT; weights `jasongzy/Make-It-Animatable` Apache-2.0; inference needs Mixamo bone/animation FBX from `jasongzy/Mixamo`, which is **not anonymously accessible**; trained on Adobe Mixamo characters | 476 stars, pushed 2026-09-08 | CUDA (training settings are for an A100 80 GB; inference VRAM not stated) | body rig only | body only, no face | only useful after TRELLIS; Mixamo data terms | **LATER** (with TRELLIS) |
| **Hunyuan3D 2.1** (named by chat 1 as excluded) | image → 3D | LICENSE: "does not apply in the European Union, United Kingdom and South Korea" | n/a | GPU | n/a | n/a | territory | **OUT** (chat 1 was right) |
| **UnumAvatar** | photo → MediaPipe face mesh + photo texture in Blender, Three.js viewer, Rhubarb lip-sync, records MP4 | **no licence** (all rights reserved); uses InsightFace `buffalo_l`, whose models are "for non-commercial research purposes only" | 1 star, created 2026-05-23, last push 2026-05-25, **archived** | Blender 4.2 Linux + offline recorder | yes (frontal face patch, ellipsoid "hair cap") | offline playback of a precomputed Rhubarb track, not live | nothing usable; our Twin already does more | **OUT** (idea reference only) |
| **Rhubarb Lip Sync** (inside UnumAvatar) | C++ CLI: WAV → mouth-shape track | MIT; output belongs to the user | 2.8k stars, pushed 2026-06-16 | desktop/server binary on a whole file | n/a | not streaming, not in the browser | latency: needs the full audio first | **OUT** for live calls |

**Chat 1's "Pipeline A" already exists: it is the baseline.** `avatar-platform-human` (2026-11-05) fits a parametric
body (Anny, Apache-2.0) to the photo's MediaPipe points, projects the photo onto the UVs, dresses it with MakeHuman CC0
assets and plays 52 ARKit morphs in three.js (ArcFace 0.41). What is new in the MPFB route is the MakeHuman mesh with its
CC0 viseme and face-unit packs, and TalkingHead's runtime.

### 2.2 From chat 2 (styles)

The six styles are art directions, not technologies; no repository to verify. Each needs its own head sculpt, materials
and expression set, so each is a separate asset project. No open (CC0/MIT) base exists for "Animated Feature Film";
"Anime 3D" maps to VRM (below); Block, Cartoon and Crochet need bespoke rigs. Decision in section 3.

### 2.3 From chat 3 (2D)

| Candidate | What it really is | Licence | Activity | Runs on | Photo → character | Talks in the browser | Main risk | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Kugutu** | JSON + SVG mascot driven by CSS transforms; `speak()` takes timed visemes; `visemesFromText`, `attachAudioLipSync` | MIT; `@kugutu/runtime-web` 0.2.0 on npm (199 KB) | **0 stars**, last push 2026-07-12 | browser, no WebGL | no: vector parts from a catalogue | yes, mascot level | flat vector look, single developer | **OUT** (owner's call confirmed) |
| **Iki** | Live2D-style WebGL2 puppet engine: warp meshes, clipping masks, spring physics, an auto-rigger from role-named PNG/PSD layers, MCP server | MIT; `@ikijs/engine` 0.11.0 (813 KB) | 41 stars, created 2026-06-04, **pushed today**, "early, but real", schema still settling | browser WebGL2 | parts are drawn by an image model through the Codex CLI in an agent loop with critic agents; or from layered art | yes: blink, gaze, lip-sync, head turn, nod, hair physics | not basic, but illustration-only; creation is an agent loop, not a cheap call | **LATER** (runtime for an anime 2D style) |
| **Doll Studio** | layered PSD → WebGL puppet with lip-sync, MediaPipe tracking, desktop pet | **no LICENSE file** (404): all rights reserved | 59 stars, created 2026-11-09 | browser | needs a layered PSD from See-through or an agent skill | yes | cannot be used at all | **OUT** |
| **idle-web-animation** | layered PNGs + one JSON, DOM/CSS: breathing, blinking, looking; built for FiveM's old Chromium | MIT | **0 stars**, last push 2026-09-15 | browser | no | **no lip-sync** | not a talking engine | **OUT** |
| **lipsync-engine** (Amoner) | AudioWorklet + FFT: 5 band energies, amplitude and zero-crossing rate → one of 15 Oculus-named visemes, EMA smoothing; SVG/Canvas/CSS renderers | MIT | 68 stars; **3 commits in ~80 min on 2026-02-07, nothing since**, co-authored by Claude, no tests; the npm package its README installs (`@beer-digital/lipsync-engine`) **does not exist on npm** | browser | n/a | audio-driven mouth; the visemes are spectral guesses, not phonemes | unmaintained prototype | **component**, in the lip-sync test (3.3) |
| **Wireface 2D** | any picture → 468-point face rig in WebGL2; expressions, blinks, teeth three ways, audio-driven lip-sync; exported characters play offline | proprietary SDK: free Personal Licence; a product you charge for needs a **Developer Licence, GBP 50/year** (< 10 employees, one product), no source code (Enterprise only) | n/a | browser | yes, but "Wireface builds its rig and transfer data on the server" and "Gemini finds the face": the photo goes to them | yes | closed, one small vendor, user photos to a third party | **IN** as the commercial yardstick for 2D-A |
| **See-through** (what Doll Studio relies on) | one anime illustration → up to 23 inpainted layers with depth order (SIGGRAPH 2026) | code Apache-2.0; weights OpenRAIL++ (fine-tunes of Animagine XL 4.0 and Marigold), SAM part Apache-2.0 | 5.7k stars, pushed 2026-11-14 | CUDA, 12-16 GB VRAM at 1280 px (8 GB with NF4); 2-3 min per image on their demo | anime only | via Iki or StretchyStudio (MIT, 531 stars) | anime-only, use restrictions of OpenRAIL++ | **LATER** (anime 2D style) |

### 2.4 Added (missed by the chats)

| Candidate | What it really is | Licence | Activity | Photo → character | Talks in the browser | Verdict |
|---|---|---|---|---|---|---|
| **TalkingHead** (met4citizen) | three.js class for full-body GLB avatars: lip-sync, moods, gestures, eye contact, dynamic bones, streaming mode, `speakAudio` takes words or Oculus visemes with times; documented **MPFB route** (Blender add-on + rig + weights, MIT) and a `retargeter.mjs` | MIT | 1.7k stars, pushed 2026-11-04; tested on desktop Chrome/Firefox/Safari/Edge and iPad | no (the avatar is made elsewhere) | yes; lip-sync language modules: en, fi, de, fr, lt, pt_br, bn: **no Spanish** (we would feed visemes directly) | **IN** (runtime of 3D-A) |
| **HeadAudio** (same author) | AudioWorklet viseme detector: MFCC + Gaussian prototypes + Mahalanobis classifier; outputs Oculus visemes; model trained on English ("model-en-mixed"); the author calls its accuracy "far from optimal" at low SNR | MIT | 59 stars, pushed 2026-11-10; tested on desktop browsers, iPad and iPhone | n/a | audio-only lip-sync, 50-100 ms latency to compensate | **component**, add to the lip-sync test |
| **Photo puppet** (in-house, 2D-A) | the portrait itself as a WebGL mesh over MediaPipe's 478 points, deformed by our 52 ARKit shapes; what UnumAvatar and Wireface 2D do, built from Apache parts we already use | ours + Apache-2.0 | n/a | yes, in seconds on the device | yes, through the same viseme bus | **IN** |
| **VRM / @pixiv/three-vrm** | standard anime avatar format with expressions (aa, ih, ou, ee, oh), blink, look-at | MIT | 2.3k stars, pushed 2026-10-22 | no open photo → VRM generator found; VRoid Studio is a manual desktop app; TalkingHead's own VRoid sample is non-commercial | yes | **LATER** (anime 3D style) |
| **Inochi2D** | open Live2D-style engine (D language) | BSD-2-Clause | 1.9k stars, pushed 2026-11-10 | no: puppets are rigged by hand in Inochi Creator | web only through WASM with a patched D runtime | **OUT** (no automation, weak web path) |
| **LAM** (Gaussian head) | one photo → animatable Gaussian head; WebGL renderer released; OpenAvatarChat SDK | code Apache-2.0 | 1.1k stars, pushed 2026-06-10 | yes | yes, head only | **OUT** for this arena: our Etapa B measured ArcFace 0.23 vs the baseline's 0.41, and the lab already replaced it |
| **Ready Player Me** | the format TalkingHead grew up on | its sample avatar is CC BY-NC | `readyplayer.me` now resolves to mail (MX) records only; the site does not answer | no | n/a | **OUT** (service gone) |

Voice, for completeness (section 6): **HeadTTS** (MIT, Kokoro in the browser with phoneme timestamps) is English only.
**Kokoro-82M** (Apache-2.0 weights) has 3 Spanish voices, but its Spanish front end is eSpeak NG (GPL-3.0); the
`phonemizer` npm package that `kokoro-js` bundles is labelled Apache-2.0 while wrapping eSpeak NG. That needs a legal
check before it ships.

### 2.5 Where the chats were wrong or incomplete

- Chat 1's Pipeline A is not new: it is the baseline already in `avatar-platform-human`.
- TRELLIS.2 is MIT, but its default pipeline is not: a CC BY-NC background remover, a gated DINOv3 encoder and NVIDIA's research-only nvdiffrast. It also needs Linux and ≥ 24 GB.
- Make-It-Animatable's weights are Apache-2.0, not MIT. Its inference needs Mixamo files we cannot download anonymously.
- UnumAvatar is not a "reference implementation" we can use: it has no licence, was archived two days after it was created, and depends on non-commercial InsightFace models.
- Doll Studio is not "open": it has no licence.
- Kugutu, the chat's "favourite to try first", has 0 stars and has been idle since July. idle-web-animation has no lip-sync.
- lipsync-engine is a one-afternoon prototype. The package its README tells you to install was never published. HeadAudio does the same job with a trained model and was tested on iPhone.
- Iki is not "too basic": it has warp meshes, physics and an auto-rigger. It is illustration-only, though, and makes characters through an agent loop.
- Wireface 2D's licence is as chat 3 says. It also costs GBP 50/year and comes without source, and the photo is processed on their server with Gemini.

## 3. The line-up

**Style: all three (owner's decision, 2026-11-16).** The owner chose MEYA's three visual styles for the arena, not
"realistic only": **Animated Feature Film** (top priority, MEYA's default), **Realistic Game Character** and **Anime 3D**.
Every entrant is judged on an original character in each style. That favours an entrant whose style is decided once, at
creation, by an image model, over one that needs a sculpt, materials and an expression set per style (3D-A).

| Slot | Entrant | What it answers |
|---|---|---|
| **2D-S (primary)** | **Styled portrait puppet** (built, `puppet/`): one styled portrait made once by an image model, animated in the browser by a WebGL mesh warp over MediaPipe landmarks, text-timed visemes, an inner-mouth layer, blinks, gaze, head motion and a listening state | can one image per character, in any of the three styles, talk live on the device with zero GPU and zero per-minute cost? |
| **B0 baseline** | three.js human, `avatar-platform-human` (Anny + MakeHuman CC0, Twin fit, our engine and visemes) | the bar every entrant must beat; first iPhone numbers |
| **3D-A** | MPFB2 (headless Blender) + CC0 visemes and face units + Twin fit ported to the MakeHuman mesh, played by **TalkingHead** | does a mature runtime (gestures, moods, eye contact) and MakeHuman's face rig beat our engine at the same cost? |
| **2D-A** | **Photo puppet** (in-house): the portrait as a MediaPipe-meshed WebGL puppet driven by our 52 ARKit shapes | highest identity at near-zero cost: is a talking photo with ±12° of head motion good enough? |
| **2D-R** | **Wireface 2D** (commercial yardstick, evaluated under its free Personal Licence) | how far 2D-A is from a finished product; whether GBP 50/year is worth it |

### 3.1 Styled portrait puppet (primary candidate)

Built and measured on 2026-11-16; results, numbers and frame sheets in `puppet/README.md`. It is 2D-A with two changes:
the portrait is a **styled** image of the character (Z-Image-Turbo locally for the lab; for a person's own photo an
image-edit model once at creation, see the README), and the mouth interior is solved explicitly (a drawn inner mouth
layer, compared with image-to-image mouth sprites). It reuses the lip-sync test's `mouth-driver.js` (text-timed visemes)
unchanged. 2D-A (the person's own unstyled photo) remains as a variant of the same runtime.

**Browser lip-sync is a shared component, not an entrant.** One viseme bus feeds every renderer:

```
call audio (streamed) ─┬─> source: text-timed visemes (TTS alignment, current visemes.ts)   [control]
                       ├─> source: HeadAudio (MFCC, trained)                               [audio-only]
                       └─> source: lipsync-engine (FFT bands)                              [audio-only]
                                 │  (chosen by the lip-sync test, built by the other person)
                                 v
            viseme bus: 15 Oculus visemes + intensity on the AudioContext clock (+ lead offset)
                                 v
     per-entrant mapper: ARKit morphs (B0, 3D-A via TalkingHead visemes/vtimes) | mesh warp (2D-A) | Wireface say()
```

The lip-sync test picks the default source. Arena 5 runs every entrant twice: once with text-timed visemes (today's
path) and once with the test's audio-only winner. That second run stands in for a local TTS without timestamps. The
~80 ms lead fix goes on the bus, so it applies to every entrant.

## 4. Build plans (IN only)

The Mac rule holds throughout: one heavy task at a time. Nothing starts while the current image-generation job runs. No
entrant needs a GPU at creation or at call time, so **planned GPU cost: 0 USD**.

### 4.0 Shared harness (all entrants), ~8-10 h

1. One page in the baseline frontend, `?human=arena5&engine=b0|th|puppet|wireface&lips=text|headaudio|lse`. It reuses the A0 streaming voice path (`speech.ts`). Each engine implements `load(character)`, `onViseme(frame)`, `setExpression`, `lookAt` and `setListening`.
2. A logger for frame times, long tasks, `transferSize` per resource and the latency markers (turn end, first audio sample, first lip frame), written to JSON.
3. Recording: headless Chrome with the WAV as the microphone (lab flags: `--use-file-for-fake-audio-capture` without `%noloop`, `--disable-features=AudioServiceOutOfProcess,AudioServiceSandbox`, `--mute-audio`). `canvas.captureStream()` plus the call audio go to webm.
4. iPhone: iOS Safari has no fake-capture flag, so `?fakeMic=<wav>` injects the same WAV into the call input. Measure with Safari Web Inspector over USB.

Tools: none new (Playwright and ffmpeg are already in the lab). Mac: light.

### 4.1 B0 baseline, ~3 h

Build Jin through the existing Twin fit (11-12 s CPU) and pick hair from the catalogue. Run it in the harness unchanged.
This is also the first measurement on an iPhone. Mac: light; recording a 3D render counts as heavy, so run it alone.

### 4.2 3D-A: MPFB2 + TalkingHead, ~20-24 h

| Step | What | Hours |
|---|---|---|
| 1 | Cheap first look: load the **baseline GLB** in TalkingHead through `retargeter.mjs`, to separate "runtime" from "mesh" | 2-3 |
| 2 | Install Blender 5.3.0 (macOS arm64, 360 MB; fall back to 4.5 LTS if MPFB2 does not load) and MPFB2 from Blender's extension list. MakeHuman system assets are already on disk (`avatar-platform-human/human/assets_src`, 937 MB with skins and hair). Add the CC0 packs "Visemes 02" and "Faceunits 01", and TalkingHead's MPFB add-on, rig and weights (MIT) | 1-2 |
| 3 | Make one avatar by hand, following TalkingHead's `blender/MPFB/MPFB.md`, as the reference GLB | 1-2 |
| 4 | Script it headless (`blender -b -P lab/arena5/mpfb/build.py -- jin.json`, after MPFB's `script_samples/`): macro parameters, CC0 skin, hair, brows and clothes, the TalkingHead rig, visemes and face units, then GLB export with 2K textures | 5-6 |
| 5 | Identity: port the Twin fit to the MakeHuman mesh (MediaPipe 478 points → least squares over MPFB's face targets) and reuse `twin.py`'s photo projection on MakeHuman UVs | 7-8 |
| 6 | Run in the harness: TalkingHead streaming mode (Appendix G), with visemes from the bus passed as `visemes/vtimes`, so no Spanish module is needed; moods, gestures and eye contact on | 3 |

Mac: each Blender build is a CPU job, estimated at 1-3 min and 1-2 GB (to be measured). Run builds one at a time and
never next to another heavy task. GPU: none. Shipping it means a small CPU builder (Blender on a server), since Blender
cannot run in the browser. Risk: MPFB2 on Blender 5.3 is unverified, and a photo fit on MakeHuman's face targets may not
reach the Twin's 0.41.

### 4.3 2D-A: photo puppet, ~18-22 h

| Step | What | Hours |
|---|---|---|
| 1 | Creation, in the browser in under 5 s: head-and-shoulders crop (Jin's face is small in the frame), Face Landmarker 478 points + z, selfie segmentation for hair, body and background layers (as in `poses/background.py`) | 3 |
| 2 | Mesh: Delaunay over the landmarks plus an outer ring (skull, hair, neck) with soft falloff; landmark z gives ±12° head-turn parallax | 3 |
| 3 | Shapes: carry Anny's 52 ARKit morph deltas through the Twin correspondence (Anny vertex ↔ landmark) to the image plane, so 2D-A takes exactly the same 52-shape input as B0 | 4-5 |
| 4 | Mouth interior (dark cavity, MakeHuman CC0 teeth tinted to the photo, tongue) behind the lips; blink by stretching the upper lid; gaze by moving the iris crop inside a sclera mask | 5-6 |
| 5 | Breathing and sway on the torso layer, plus the B0 engine's blink, saccade and listening timers; orthographic three.js render | 3-4 |

Mac only, light; no GPU. It can run with zero server: creation happens on the device. Risks: an open mouth and teeth
that do not belong to the photo, head motion limited to ±12°, and identity dropping when the mouth opens.

### 4.4 2D-R: Wireface 2D, ~3-4 h

Download their ES-module SDK (size to be recorded) and create Jin's character on their site. Jin is a generated person,
so no real person's photo leaves our system. Export it and play it offline in the harness through `face.say(...)` on our
AudioContext, after checking whether it accepts streamed audio. Mac: light. No cost under the Personal Licence for the
evaluation; buying the Developer Licence is an owner decision, and only if it wins.

### 4.5 Not built now, with their price if wanted later

| Item | When | GPU and cost (lab's RunPod prices) |
|---|---|---|
| TRELLIS.2 identity probe: does a TRELLIS head, used as a shape target for our rig, beat 0.41? Lab evaluation is allowed under nvdiffrast's licence | only if 3D-A and B0 both stay under 0.45 | RTX 3090/4090 24 GB, ~1.5 h with install and the 4B weights: 0.33-0.75 USD (3090) or 0.51-1.34 USD (4090); production blocked until RMBG-2.0 and nvdiffrast are replaced |
| Anime 2D: illustration → See-through layers → Iki or StretchyStudio | if the owner wants an anime style | RTX A5000, ~1 h set-up and tests 0.16-0.27 USD; then 2-3 min per character ≈ 0.01 USD |
| Anime 3D (VRM) | same | none |

## 5. Test protocol

- **Face:** Jin, round 2 portrait `lab/inputs/jin.png`: a generated person, frontal, no glasses. The round 3 look adds glasses, which would confound the face fit.
- **Voice:** Jin's ElevenLabs voice "Brian - Social Media" (`U9TSK9KHMlMU2qkeXlQP`) through the A0 streaming path (LLM + ElevenLabs with alignment), the same for every entrant.
- **Script** (the lab's call, about 3 min, one WAV as the microphone): greeting; "three things to look at when choosing headphones" (a list answer); a question about paying for an AI code assistant; **an interruption** mid-answer ("Espera, espera. Dímelo en una sola frase."); goodbye.
- **Runs:** each entrant × {text visemes, audio-only winner} × {M2 Chrome headless (recorded), M2 Safari, iPhone Safari}, 3 runs each, median reported. One run at a time, with the Mac otherwise idle and a 2 min cool-down between runs.
- **Recorded per run:**
  - webm of both sides of the call;
  - frame-time JSON and CPU samples;
  - the latency markers;
  - bytes downloaded;
  - creation time and cost;
  - ArcFace frontal and 3/4;
  - the render mouth metric (r, lag, silence, /p b m/ closure);
  - a contact sheet.
- **Output:** `results/arena5/arena5_jin.mp4` (the four side by side, with audio) and "Round 5" in `benchmark/RESULTS.md`.

## 6. Open decisions for the owner

1. **Voice and brain.** Does "no API that costs us money" also cover the voice (ElevenLabs) and the LLM? The avatars here cost 0 per minute, but every call still pays both. If it does, the arena needs a voice track. The browser's own speech synthesis is free on the device, with variable quality. Kokoro has Spanish voices but carries a GPL phonemizer that needs a legal check. HeadTTS is English only.
2. **Style.** Decided 2026-11-16: all three styles (Animated Feature Film first, Realistic Game Character, Anime 3D).
3. **Wireface.** May we evaluate a closed SDK whose character preparation runs on their server with Gemini? If it wins, the cost is GBP 50/year, and user photos would go to a third party (a GDPR processor agreement).
4. **Where creation runs.** 2D-A can be built entirely on the person's device. 3D-A needs Blender on a small CPU server. Does that count as "not spending resources"?
5. **iPhone.** Which model and iOS version is the reference? The test needs a cable and Safari's Web Inspector on the Mac.

## Not verified

- **blender.org licence page:** it answers 403 to scripts, so Blender's statement that output is not covered by the GPL was not re-read today.
- **TRELLIS.2 and nvdiffrast:** which pipeline steps call nvdiffrast at inference.
- **Gated licences:** the DINOv3 licence text and the `jasongzy/Mixamo` terms.
- **Sizes not fetched:** HeadAudio's model, the Wireface SDK, TRELLIS.2's and See-through's weights.
- **MPFB2 and Blender 5.3:** whether MPFB2 runs on Blender 5.3.
- **VRoid Studio:** its terms.
- **Rendering quality and phone performance:** Wireface's quality on a real photo, and any iPhone performance figure (none of the projects publishes one for iPhone except HeadAudio's "tested").
- **Ready Player Me:** only its DNS was checked; the shutdown itself was not read from a page.
- **RunPod prices:** the lab's known ranges were used, not re-checked today.
