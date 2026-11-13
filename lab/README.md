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
