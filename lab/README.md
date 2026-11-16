# MEYA lab

Technologies on trial, kept apart from the product. A technology that wins moves to production (behind its own
interface); one that loses is either removed or kept here, marked experimental.

| Folder | What |
|---|---|
| `inputs/` | The benchmark's inputs, identical for every engine: a portrait and a ~13 s line in the being's own voice (`make_inputs.py`). |
| `musetalk/` | MuseTalk 1.5 through LiveTalking, live over WebRTC (the `devopsavatar/meya-livetalking` image). `make_clip.py` turns a portrait into the short video MuseTalk needs; `bench_client.py` plays the browser's part. |
| `flashhead/` | SoulX-FlashHead Lite live over WebRTC (`fh_server.py`, same `/offer` protocol as LiveTalking; engine after Mynah). `--body clip.mp4` adds the gesture layer: a half-body clip loops under the live face, tracked and blended per frame. `setup_fh.sh` installs it on a meya-livetalking pod. |
| `liveavatar/` | The 80 GB pod of the arena: `setup_big.sh` (EchoMimicV3-Flash + LiveAvatar, own venvs) and `run_big.sh` (renders the being's side of a live call). |
| `inputs/round1/ada/` | Ada, the tech creator of round 1 (arena V3): `gen.py` draws her with both gpt-image-2.6 models and logs the cost. |
| `musetalk/make_state_clips.py`, `musetalk/patch_states.py` | Round 2 body states: a listening / explaining / emphasis clip per being (Pruna p-video-2-pro-reference), and the LiveTalking patch that plays them by call state. |
| `echomimic/` | EchoMimicV3 *preview* with the authors' half-body settings (`setup_em.sh`, `run_em_preview.py`); needs an 80 GB GPU. |
| `api_avatars/render.py` | Hosted avatars for the arena: Pruna p-video-2-pro-avatar and Boson Higgs Avatar, from the same call audio. |
| `inputs/round2/jin/` | Jin, the tech creator of round 2: portrait (`gen.py`) and body clips (`clips/`, media not in git). |
| `benchmark/pod/` | GPU pod for the photo-to-video engines (SoulX-FlashHead Lite/Pro, EchoMimicV3-Flash): `setup.sh`, `run.sh`, and `pod.py` (RunPod with watchdog and in-pod self-stop). |
| `benchmark/metrics.py` | Quality, measured the same way for every video: identity (ArcFace), lip sync, sharpness, head motion. |
| `benchmark/RESULTS.md` | The latest run, its numbers and the recommendation. |

Rules: every GPU pod has a watchdog that survives network errors and its own self-stop; it is terminated when the
work is done (see the root `CLAUDE.md`). Media stays out of git (`.gitignore`).
| `flashhead/body_layer.py`, `fh_dump.py`, `compose_offline.py` | Round 3: the gesture layer on its own (clips per moment, a clip per sentence, v3 anchoring on eyes, nose and mouth with soft edges), FlashHead raw frames dumped on a pod, and offline compositing on a laptop to measure and see the ghost. |
| `musetalk/make_round3_clips.py` | Round 3 clips: greet / explain / emphasis from Jin's voice (Pruna p-video-2-pro-avatar) and listen / think (p-video-2-pro-reference), 480p. |
| `a2f/setup_a2f.sh`, `a2f/a2f_dump.cpp` | Round 4: NVIDIA Audio2Face-3D SDK + v3.0 on a RunPod GPU (public TensorRT tarball), dumps ARKit weights per frame from a 16 kHz wav. |
| `a2f/arena4_metrics.py`, `a2f/lab_files.py` | Round 4 arena (Jasom, three.js visemes vs Audio2Face): jaw-vs-voice sync metrics, and the local file server the `?human=arena4` page uses. |
| `a2f/a2f_calibrate.py`, `a2f/arena4_render_metric.py` | Round 4: per-shape calibration profile that maps Audio2Face weights onto our rig (rest bias + gain), and the render-based mouth aperture metric (teeth/interior pixels vs voice). |
| `poses/` | Pose session: a person records the five body moments (listen, greet, explain, emphasis, think) guided by Jin's clips (`server.py` + `record.html`, live face, light and lips checks); `prepare.py` turns the takes into round 3 format clips plus a voice sample. A/B plan against Pruna clips from a photo in `poses/README.md`. |
| `poses/background.py` | Backgrounds on body clips frame by frame (MediaPipe selfie multiclass, mask smoothed over time), so the live call keeps the scene of the being's photo. |
| `backgrounds/` | MEYA's Meet-style scenes by category (new, professional, cosy home, places, fantasy, plain): `run_all.sh` queues `gen.py` (Z-Image-Turbo q4 on the Mac, one 1024x768 image at a time with cool-downs and heat/memory pauses) under `watch.sh` (stops it on memory pressure or heat) and `publish.py` puts each finished scene in the web (webp + thumbnail + the category manifest; two plain backdrops are drawn in code). |
