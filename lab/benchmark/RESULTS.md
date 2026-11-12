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
