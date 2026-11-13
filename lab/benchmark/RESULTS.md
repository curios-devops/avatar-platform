# Avatar arena V3: half-body presence (2026-11-13, night)

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

Videos (`results/arena/`, not in git): `arena_ada_12s.mp4` (the four side by side, her voice from the call),
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
