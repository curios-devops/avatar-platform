# Round 3 — Jin's new look, speaking clips, a clip per sentence, tighter FlashHead anchoring (2026-11-13, midday)

**Jin, new look.** Closer to the tech-creator reference: navy t-shirt with the MEYA mark, thin black glasses, blue-lit
tech studio, smartwatch. `gpt-image-2.6-sunburst` image edit with our logo as the only input image (2 drafts, ~0.075 USD;
`inputs/round3/jin/gen.py`). Voice: ElevenLabs "Brian - Social Media" (`U9TSK9KHMlMU2qkeXlQP`, young, casual, neutral
Latin American Spanish); no Spanish voice with an East Asian accent exists in the library. `digital-humans/jin.json` updated.

**Five body clips per being** (`lab/musetalk/make_round3_clips.py`, all from the portrait's pose, 480p):

| Clip | Model | How | Length |
|---|---|---|---|
| greet | p-video-2-pro-avatar | a line in Jin's voice -> waves, smiles | 4.4 s |
| explain | p-video-2-pro-avatar | a line in Jin's voice -> open-hand gestures on the rhythm of speech | 6.8 s |
| emphasis | p-video-2-pro-avatar | "tres cosas: primero..." -> counts on his fingers | 7.0 s |
| listen | p-video-2-pro-reference | lips closed, nods, breathing | 5.2 s |
| think | p-video-2-pro-reference | looks aside, taps his chin, nods | 5.2 s |

The speaking clips come from real speech, so the gestures follow a voice; the live engine repaints the mouth.

**A clip per sentence** (`body_layer.plan_for`, and the same rules in the MuseTalk bridge, `patch_states.py` round 3):
- The call's first sentence uses *greet*.
- Each sentence with a list word or "ojo" uses *emphasis*; the others use *explain*.
- Every clip plays at least 2 s.
- *think* fills the gap between the person's last word and the first audio of the answer (FlashHead).

Example: "Buena pregunta... / tres cosas: primero... / Al final, vale la pena" -> explain, emphasis, explain.

**FlashHead anchoring v3** (`lab/flashhead/body_layer.py`, offline test on real FlashHead frames, `fh_dump.py` +
`compose_offline.py`):
- **Registration.** v3 tracks 11 anchors frame by frame (eye corners, nose, mouth corners) and fits them by weighted least squares (a similarity plus half an affine), so the eyes and the mouth both land. v2 matched the eyes only.
- **No lag.** The clip track is smoothed over 3 frames with zero phase, and FlashHead's track with a One Euro filter. v2 used 7 frames plus an exponential average, which trailed quick nods.
- **Soft edges.** Alpha fades with the distance to the face outline, so the face is transparent towards the borders. The mask and the colour match are smoothed over time, so the seam does not change from one frame to the next.
- **Both faces.** The face is pasted only where both faces are, FlashHead's and the clip's. FlashHead skin never lands on the clip's background or hair, which caused the double jaw line.

| 22 s of Jin's voice, 5 clips | v2 (round 2) | v3 |
|---|---|---|
| anchor error, mean / p95 (px, 720×1280) | 1.91 / 3.49 | **1.71 / 3.17** |
| face pasted outside the clip's face, mean / p95 | 2.4 % / 4.0 % | **0 %** (0.7 % / 2.1 % before the intersection) |

In v2 a light band shows outside the jaw on both sides; v3 has a clean jaw line (`results/round3/fh/worst_frames_v2_vs_v3.jpg`).
FlashHead Lite on an RTX 3090 (community, 0.22 USD/h) runs at 0.55 s per 0.96 s chunk (1.75× real time), so a 3090 is
enough for a live call.

**Cost:** about 0.6–0.75 USD in all.
- Pruna, 480p: about 0.5–0.65 USD.
- Images: 0.075 USD.
- RunPod: 0.04 USD.

At the end both RunPod accounts were at 0 pods and 0 USD/h.

**Pending live test:**
- one call per engine with the new clips;
- for MuseTalk, building Jin's avatar from greet + explain + emphasis (`MEYA_SEGMENTS` with `greet`);
- for MuseTalk, *think* still needs a second silent video in LiveTalking.

Files: `results/round3/fh/compose_v2_vs_v3.mp4` (side by side, with audio), `compose_v3.mp4`, `clips_*.jpg`.

# Round 2 — body states and a wider arena (2026-11-13, morning)

**The being.** **Jin**, a tech creator (male, East Asian, original), made the MEYA way: described → drawn by
`gpt-image-2.6-sunburst` (1024×1536, 0.035 USD) in the style of Pruna's p-video-2-pro-avatar "creator" demo (bright
home office, sweater, hands on the desk), voice ElevenLabs Antonio, `digital-humans/jin.json` (Ada was removed).

**Body states (new).** Three 10 s half-body clips per being, all starting from the portrait's pose, lips closed:
*listening* (breathing, nods, hands resting), *explaining* (open-hand gestures), *emphasis* (leans in, counts on his
fingers). Made with Pruna `p-video-2-pro-reference` (768p, mode "cost", ~0.26 USD and ~25–45 s each; one listening clip
was redone because the camera zoomed in). The local route was ruled out first: the Mac is an M2 Pro with 16 GB, and
Wan 2.1 image-to-video only exists at 14B (the 1.3B MLX figure, ~90 s per step on an M4 Max, is text-to-video), so a
10 s clip would take hours, far above the 5 min limit.
During the call: silence → listening clip; each answer → explaining, or emphasis when its text lists things or insists
("primero… segundo…", "ojo", "importante", several "!"). Switches cross-fade.
- MuseTalk: LiveTalking's own silent custom video plays the listening clip; the avatar is built from explaining +
  emphasis and the ping-pong loop stays inside the chosen segment (`lab/musetalk/patch_states.py`). The "LiveTalking"
  text it drew on every frame is gone.
- FlashHead: `fh_server.py --clips listen=…,explain=…,emphasis=…`.

**The round 1 "ghost", explained and fixed.** Two causes. (1) FlashHead moves its own head inside its crop, but the
face was placed where the *portrait's* eyes were, so it slid over the clip's head. (2) The soft edge of the elliptical
mask crossed the brows and jaw, so where the two faces differed (the clip's identity drift, raised brows in a gesture)
both showed at once: double brows. Fix: both sides are now tracked with the same detector (Face Mesh eye corners on the
clip and on every FlashHead frame), the face is warped eye to eye, and the mask is FlashHead's own face outline, cut
above the brows and feathered inwards so the seam lies on skin. Checked on the worst case (emphasis clip, leaning in)
offline and then in a new live call: single brows, eyes in place, no seam. ~20 ms per frame on the CPU.

**The arena.** Live engines ran the real call (guest → Jin's profile → *Videollamada* → ElevenLabs agent; the simulated
person asks for "three things to look at" in headphones, then about AI code assistants, then interrupts). The others
rendered 10 s of that call (seconds 11–21: two seconds of listening, then the list answer).

| | MuseTalk + states | FlashHead + states (v2) | Pruna p-video-2-pro-avatar | Boson Higgs Avatar | EchoMimicV3 preview |
|---|---|---|---|---|---|
| Mode | **live call** | **live call** | API, batch | API, batch (+ streaming / LiveKit modes) | rendered |
| Speed | real time (A5000 class) | 2.8× real time (4090), 1.8× (A5000, round 1) | 57 s for 10 s (768p) | **10.7 s for 10 s** (480×640) | did not run (below) |
| Turn end → first lip-synced frame | ~0.9 s (V1; not measured this round) | **0.54–0.69 s** | n/a | n/a | n/a |
| Body | states follow the call; emphasis on lists | same clips, same states | **gestures follow the speech** | still | — |
| Identity (ArcFace mean / p10) | 0.63 / 0.54 | 0.64 / 0.54 | **0.79 / 0.74** | 0.62 / 0.50 | — |
| Sharpness (face) | 82 | 53 | **159** | 16 | — |
| Head / body motion | 10.9 / **9.2** | 8.3 / 7.6 | 9.0 / 8.2 | 5.8 / 1.8 | — |
| Lip-sync proxy | 0.47 (call audio mixes both sides) | 0.09 (WebRTC capture) | 0.46 | 0.33 | — |
| Cost | ~0.002 USD/min + 3 clips ≈ 0.8 USD once | ~0.0045 USD/min + the same clips | 0.04 USD/s (768p) = 2.4 USD/min | not on the pages read | — |

Videos (`results/round2/`, not in git): `arena_jin_10s.mp4` (the four side by side), `call-musetalk-states_jin.mp4`,
`call-flashhead-states_jin.mp4` (fixed) and `call-flashhead-states-v1ghost_jin.mp4` (before the fix),
`render-pruna-avatar_jin.mp4`, `render-boson_jin.mp4`. Clips: `lab/inputs/round2/jin/clips/`.

**EchoMimicV3: why the body did not move, and why it still is out.** Round 1 ran the *Flash* model with talking-head
settings (8 steps, TeaCache, CFG 6 / audio 3, 373 frames in one go). Their half-body demos use the *preview* model:
Flow sampler, **25 steps** ("5 for talking head, 15–25 for talking body"), CFG 4 / audio 2.9 with dynamic CFG, a
negative prompt for hands, 113-frame windows. `lab/echomimic/run_em_preview.py` runs exactly that. It does not fit:
24 GB (4090) runs out of memory loading the pipeline (its T5 text encoder alone is ~23 GB in fp32); model offload then
fails in the VAE; sequential offload had not finished one step in 2.5 min. On 48 GB (RTX 6000 Ada) the 113-frame window
runs out of memory; with 65-frame windows it runs at **479 s per step** (≈13 h for 10 s). Their "12 GB" applies to the
Flash model through their quantized GradioUI; the half-body preview was tested on an A100 80 GB. Not pursued further.

**Real time: estimates only (no multi-GPU runs).**
- EchoMimic Flash measured 237 s of denoising for 15 s on an A100 (≈16× slower than real time). Real time needs
  ≈16 A100-equivalents ≈ 6 H100 at perfect scaling, ~8 H100 with sequence parallelism (Ulysses, in their code) at
  realistic efficiency: ~21 USD/h per call on RunPod community H100 SXM (2.69 USD/h), and the latency is at least one
  window (4.5 s at 113 frames). The body-capable preview needs ~3× the steps plus extra CFG passes: dozens of H100.
  Not a live option.
- LiveAvatar: 23× slower than real time on one A100 (round 1). Its authors report 45 fps on 5× H800 (4 steps,
  pipeline over 5 GPUs, v1.1). Minimum for one live call: **5× H100 80 GB SXM** (NVLink; an H800 is an H100 with
  slower interconnect); a planned 3-step version would need 4. Cost: 5 × 2.69 ≈ **13.5 USD/h ≈ 0.22 USD per call-minute**
  (community), ~22 USD/h secure, about 100× MuseTalk. A100s do not get there (no FP8, ~⅓ of an H100).
- Pruna avatar: no streaming or real-time mode documented; 768p took 5.7× the audio length, 480p is documented at
  ~1× of execution. Even sentence by sentence that is seconds of delay and 1.2–2.4 USD per minute.
- Boson: the batch call already ran at ~1× (10.7 s for 10 s with upload and queue), and it has a streaming endpoint
  (fragmented MP4) and a LiveKit real-time mode: the only hosted option here that could be live. Its picture is the
  weakest (480×640, identity 0.62, still body).

**Reading.** The states turn the gesture loop into a body that agrees with the call: still and attentive while the
person talks, open hands while explaining, counting on fingers when the answer is a list. Both live engines carry it;
the arena's best *picture* is Pruna's avatar (speech-driven gestures, sharp, true to the portrait), but it is batch.
The live engines' identity (~0.63) is held back by the clips themselves (generated from the portrait, they drift).

**Recommendation, round 2.**
- **Live calls: MuseTalk + states**, primary: real time on the cheapest card, two calls per GPU, the sharpest live
  face and the most body. **FlashHead + states (v2)** next to it: faster turn start (0.54–0.69 s), clearer articulation;
  the ghost is gone, so it stays in the race.
- Next: make the explaining/emphasis clips with **Pruna p-video-2-pro-avatar** (driven by a sample sentence, so the
  gestures are speech-shaped) instead of the reference model; add a "thinking" and a "greeting" clip; choose the clip
  per sentence, not per answer; keep each clip closer to the portrait (identity).
- **Pre-recorded content: Pruna p-video-2-pro-avatar** (or LiveAvatar where its licence allows).
- **Boson**: worth one live test through its LiveKit mode if a hosted live face is ever wanted.
- **EchoMimic**: out (not live-capable; its body model needs an 80 GB GPU for a slow offline render).

Cost of round 2: RunPod 0.88 USD (4090 secure 0.89 USD/h for the calls, cut by its own 0.6 USD watchdog before the
EchoMimic attempt finished; RTX 6000 Ada 1.09 USD/h for EchoMimic), Pruna ≈1.4 USD (4 clips + avatar), OpenAI 0.07,
Boson a few cents: **≈2.4 USD**.

---

# Round 1 — avatar arena V3: half-body presence (2026-11-13, night)

Question: a face that only moves its mouth is not presence. Can we get a half-body being that breathes, moves head,
shoulders and hands, and still talks live? Same being, same call, every engine.

**The being.** **Ada**, a tech creator made the MEYA way: described → drawn by the runtime's new image model
(`gpt-image-2.6-sunburst`, 1024×1536, medium: **0.035 USD**, 22 s; Flare costs the same, 9 s) → voice (ElevenLabs
Valeria) → `digital-humans/ada.json` (by @marcelo). Original person: the reference screenshots showed a real, named
person, so only their format was used (home studio, ring light, mic, half body). The runtime now draws with
`gpt-image-2.6-sunburst` at medium quality (gpt-image-2 retires 2027-02-10).

**The call.** Guest opens Ada's profile → *Videollamada* → ElevenLabs agent; a simulated person asks about headphones,
then about paying for an AI code assistant, and **interrupts her mid-answer** ("Espera, espera. Dímelo en una sola
frase."); the guest minute ends with the sign-up invite. The two live engines ran that call for real. The two that cannot
hold a call on one GPU rendered **her side of the same call** (the live server's tape: her speech and her silences).

**The gesture layer** (new, `lab/flashhead/fh_server.py --body`). One 10 s half-body clip of the being made once from
her portrait (breathing, head tilts, a glance up, an open-hands gesture, lips closed; Pruna p-video 720p, ~0.20 USD, 19 s)
plays in a ping-pong loop under the live face, while she listens and while she talks. Her face is tracked in every
frame of the clip (MediaPipe eyes: centre, distance, tilt; smoothed), and FlashHead's live face is warped there,
colour-matched to the clip and pasted with a soft ellipse from the brows to the chin, so hair, ears, neck, body and
hands stay the clip's. 8–12 ms per frame on the CPU. MuseTalk gets the same clip as its avatar video, so both live
engines wear the same body.

| | MuseTalk 1.5 + body clip | FlashHead Lite + gesture layer | EchoMimicV3-Flash | LiveAvatar (Wan2.2-S2V-14B + LoRA) |
|---|---|---|---|---|
| Mode | **live call** | **live call** | rendered (same call) | rendered (same call) |
| GPU used | RTX A5000, 0.27 USD/h | RTX A5000, 0.27 USD/h | A100 80 GB, 1.39 USD/h | A100 80 GB, 1.39 USD/h |
| Speed | real time, 25 fps | **1.8× real time** | 406 s for 15 s: **27× slower** | load ~2 min + 277 s for 12 s: **23× slower** |
| Turn end → first lip-synced frame | ~0.94 s (V1) | **0.81–0.93 s** (this call) | n/a | n/a (live needs 5× 80 GB GPUs) |
| Barge-in | works | works | n/a | n/a |
| Body | the clip's loop (not tied to speech) | the clip's loop (not tied to speech) | still: hands never move | **gestures follow speech**: hands move when she explains, rest when she listens |
| Head motion (% face) | 13.2 | 11.7 | 0.9 | 7.1 |
| Body motion (0–255) | 4.1 | **5.1** | 0.3 | 4.2 |
| Identity vs portrait (ArcFace mean / p10) | 0.71 / 0.64 | 0.67 / 0.54 | 0.78 / 0.73 | **0.78 / 0.67** |
| Lip-sync proxy | not measurable (call audio mixes both sides) | 0.16 (WebRTC capture) | 0.60 | **0.65** |
| Sharpness (face) / output | **29** / 768×1152 | 21 / 720×1280 | 26 / 512×768 | 16 / 384×576 |
| GPU per minute | ~0.002 USD (2 calls/GPU) | ~0.0045 USD (1 call/GPU) | ~0.63 USD per minute of video | ~0.53 USD per minute of video; live ≈ 5×80 GB ≈ 0.2 USD per call-minute |
| One-off per being | body clip 0.20 + avatar build 3 min | body clip 0.20 | none | none |

Videos (`results/round1/`, not in git): `arena_ada_12s.mp4` (the four side by side, her voice from the call),
`call-{musetalk,flashhead}-body_ada.mp4` (the whole live calls, both sides), `render-{echomimic,liveavatar}_ada.mp4`.
Logs: `live_calls.txt`, `big_pod_times.txt`. Metrics: `results/metrics.json` (`metrics.py` now also measures body motion).

**Reading.**
- The gesture layer works live: FlashHead keeps real time and its latency with a moving body (0.81–0.93 s), and the
  composite holds through 36° head tilts with no seam. Presence goes from "a talking photo" to "someone at her desk".
  Its limit: the body loop does not know what she says. The live engines' identity drops to ~0.7 because the clip's
  own face (jaw, hair, light) frames the live one.
- LiveAvatar is the only engine whose body *means* something: it explains with its hands and goes quiet to listen,
  with the best lip sync and identity. It is not a live option for us: 23× slower than real time on one A100, and
  the real-time setup needs five 80 GB GPUs per call. Its LoRA weights' licence is not stated (code and base Apache).
- EchoMimicV3-Flash did not move her arms at all here and is 27× slower than real time. Discard (again).
- MusePose: not run on purpose. Its released weights are non-commercial, it needs a pose video to drive it, and it is
  an SD 1.5 dance model from 2024. "Body clip + live face" reaches the same goal with parts we can ship.
- Boson Higgs Avatar: not tested. Its API is batch (≤ 60 s, 640×640 max) with a separate LiveKit real-time mode, and the
  key was not in `backend/.env` during the run.

**Recommendation V3.**
- **Live calls: FlashHead Lite + gesture layer**, primary. Next: a small set of clips per being (listening, explaining,
  emphasis) chosen by the call state (speaking or listening), as Mynah's instinct layer does, so the body agrees with
  the words; make those clips with an open model instead of Pruna (LiveAvatar's own renders are the best candidate,
  once its licence is clear).
- **MuseTalk + body clip**, secondary: same presence, half the GPU per call, sharper, weaker articulation.
- **Pre-recorded video (Ada's posts, presentations): LiveAvatar**, ~0.5 USD per minute on an A100, the most human body;
  verify the LoRA licence first.
- Cheapest live card stays the RTX 3090 / A5000 class. Avoid hosts that drop UDP (one 3090 community host never
  connected WebRTC); secure-cloud A5000 worked.

Cost of this run: RunPod ~1.05 USD (A5000 + A100 + a 3090 replaced), Pruna ~0.20, OpenAI 0.07: **~1.3 USD of 4**.

---

# Avatar benchmark V2: real-time calls (2026-11-12, night)

Only live calls, no pre-rendered video. The full MEYA flow: a new companion, **Lexi**, created the MEYA way (described →
drawn by the runtime's image model, half-body) → animated by each engine → a guest opens her profile, taps
*Videollamada*, and talks to her through the ElevenLabs agent. A simulated person (a WAV as the microphone) answers,
waits, asks for music and **interrupts her mid-answer**. Both engines on **one RTX A5000 (24 GB, 0.27 USD/h)**, the
cheapest card that held real time for both; same call, same agent, same voice.

| | MuseTalk 1.5 (LiveTalking) | FlashHead Lite (our `lab/flashhead/fh_server.py`, engine after Mynah) |
|---|---|---|
| Input it needs | a short video of her (Pruna, 24 s, ~0.16 USD) + avatar build ~3 min | **the photo only** |
| Speed on the A5000 | real time, 25 fps | **1.8× real time** (0.53 s per 0.96 s chunk) |
| Turn end → first lip-synced frame | ~0.94 s (audio → first sound, V1) | **0.83–0.85 s** (measured in the call) |
| Barge-in | works | works |
| Calls per GPU | ~2 | 1 |
| VRAM | ~7.7 GB | 5.8 GB |
| Start-up of the server | ~2.8 min from the image | load 36 s + warm-up/idle loop 3 min (once per pod) |
| Identity vs her portrait (ArcFace) | 0.56 (the generated clip drifts) | **0.89** |
| Head/body motion | **high** (the clip's own motion) | low: only the head moves, the body is a still canvas |
| Mouth | moves, mostly closed | **clear articulation** (teeth, syllables) |
| Sharpness (face) | **67** | 48 |
| GPU per minute of call | ~0.002 USD | ~0.0045 USD |

Recordings: `scratchpad/live/lexi_{musetalk,flashhead}_call.webm` (both sides of the call), cut to 30 s in
`results/rt-{musetalk,flashhead}_lexi.mp4`.

**Reading.** FlashHead is the better *face* for a being made from a photo: it is her, and she articulates. MuseTalk is
the better *presence*: the body moves, but only as well as the clip we feed it, and the clip drifts from her identity.
The gap is the body: Mynah's answer is the same as what we see in Atmee (pre-made idle/gesture clips of the half-body
canvas, played while she listens and between turns, with the live head on top).

**Recommendation V2.** Primary for live calls: **FlashHead Lite** for beings created from a photo (no prep, true to the
portrait), with a half-body idle/gesture layer as the next step. Secondary: **MuseTalk** (cheaper per call, more body
motion, and the fallback when FlashHead's LTX VAE licence or capacity is a problem). Cheapest card that does both in
real time: **RTX 3090 / A5000 class (~0.22–0.27 USD/h)**; a 16 GB A4000 is unlikely to hold FlashHead above 1×.

---

# Avatar benchmark V1 (2026-11-12)

Same portrait, same voice, same line (~13 s) for every engine. Two cases: **Imani** (one of our beings, film
portrait) and **Noa** (a new companion created the MEYA way: described → drawn by the runtime's image model → voice).
A third, **Sofía** (a licensed stock photo "uploaded" → MEYA portrait), went through MuseTalk only.

Videos: `results/comparativa_{imani,noa}.mp4` (2×2, MuseTalk aligned to its speech onset). Raw: `results/*.mp4`.

## Speed

| Engine | GPU | Mode | Steady speed | Per-call startup | New character prep |
|---|---|---|---|---|---|
| MuseTalk 1.5 + LiveTalking | RTX 3090 | live, WebRTC | real time, 25 fps | first frame 1.0–1.6 s; **0.94 s** audio → first sound | 8 s clip (Pruna, ~20 s, ~0.16 USD) + avatar build 1.5–2.7 min |
| FlashHead Lite | RTX 5090 | offline run (streaming exists, not wired yet) | **0.19 s per ~0.93 s chunk ≈ 4.8× real time** | model load 9–35 s + warm-up 28–106 s, once per process | none: the photo is enough |
| FlashHead Pro | RTX 5090 | offline | 1.65 s per ~1.08 s chunk ≈ **0.65× real time** (not live on 1 GPU) | load 12–59 s + warm-up 35–148 s | none |
| EchoMimicV3-Flash | RTX 5090 | offline, whole clip at once | ~160 s for 12.8 s ≈ **12× slower than real time** | included | none |

MuseTalk pod from the new image (`devopsavatar/meya-livetalking`): image pull ~2 min, cached avatar from R2 in 6 s,
server ~40 s → **~2.8 min** to ready (was ~7 min with the install script).

## Quality (`metrics.py`)

| Video | Identity (ArcFace, mean / p10) | Lip-sync proxy (corr @ lag) | Sharpness (face) | Head motion |
|---|---|---|---|---|
| musetalk_imani | 0.72 / 0.63 | **+0.38** @ 120 ms | **226** | **6.8** |
| flashhead_lite_imani | 0.76 / 0.68 | **+0.39** @ −40 ms | 25 | 6.3 |
| flashhead_pro_imani | **0.84 / 0.80** | +0.23 @ 200 ms | 77 | 2.9 |
| echomimic_imani | 0.73 / 0.68 | +0.07 @ 0 ms | 87 | 1.7 |
| musetalk_noa | 0.73 / 0.63 | **+0.45** @ 200 ms | **26** | **10.3** |
| flashhead_lite_noa | 0.82 / 0.77 | +0.21 @ 0 ms | 7 | 2.1 |
| flashhead_pro_noa | **0.83 / 0.78** | +0.25 @ 0 ms | 14 | 4.0 |
| echomimic_noa | 0.66 / 0.62 | +0.19 @ 200 ms | 14 | 1.2 |
| musetalk_nueva (Sofía) | 0.69 / 0.53 | +0.23 @ 160 ms | 235 | 8.2 |

Reading: identity is against the source photo (MuseTalk loses some because its input is a generated clip that already
drifts from the photo). Sharpness only compares within a case (Noa's portrait is dark and soft). The lip-sync number is
a rough proxy (mouth opening vs loudness); judge it with the videos. By eye: MuseTalk is the crispest and most alive;
FlashHead Lite is visibly softer (LTX VAE) and drifted on Imani; Pro keeps identity best and is expressive;
EchoMimic is smooth but stiff.

## Cost

| Engine | GPU price seen | Per minute of talk (GPU only) | Per new character |
|---|---|---|---|
| MuseTalk live | 3090 0.22 USD/h (community) | ~0.004 USD (1 call), ~0.002 (2 per GPU) | ~0.17 USD + ~3 min |
| FlashHead Lite live (projected from 4.8×) | 5090 0.69 USD/h | ~0.012 (1 call), ~0.003 (4 per GPU) | 0 |
| FlashHead Pro offline | 5090 0.69 USD/h | ~0.018 USD per minute of video | 0 |
| EchoMimic offline | 5090 0.69 USD/h | ~0.14 USD per minute of video | 0 |

Plus, every engine: the ElevenLabs agent (voice + brain), ~880 credits/min (grant).

## Licences

- MuseTalk (MIT code; weights per their model cards), LiveTalking Apache-2.0.
- SoulX-FlashHead Apache-2.0 (repo). **Lite uses the LTX-Video VAE, whose licence is not Apache: verify before production.** Pro uses the Wan VAE (Apache-2.0).
- EchoMimicV3 Apache-2.0 (base Wan2.1-Fun, Apache-2.0).
- Not tested: Live Avatar (real time needs 5×H800; research preview), AvatarForcing (academic-only licence).

## Recommendation

- **Live calls, primary: MuseTalk + LiveTalking** (what we run today). Real time on the cheapest GPU, sub-second
  start of speech, the sharpest and most alive picture. Its cost is the per-character prep (a short clip).
  To do: the ~120–200 ms lip lag, and the prep step as part of creating a being.
- **Live calls, secondary: FlashHead Lite**, the only photo-only engine fast enough for live (≈5× real time, ~4 calls
  per 5090), zero prep. Before it can be primary: wire its streaming mode to WebRTC and measure the real call latency,
  improve sharpness, and clear the LTX VAE licence.
- **Pre-recorded video (presentations, posts): FlashHead Pro.** Best identity, Apache all the way, ~0.02 USD per minute.
- **EchoMimicV3: discard** (stays in the lab as experimental): 12× slower than real time, lowest identity and motion.
