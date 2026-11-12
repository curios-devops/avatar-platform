# MEYA lab

Technologies on trial, kept apart from the product. A technology that wins moves to production (behind its own
interface); one that loses is either removed or kept here, marked experimental.

| Folder | What |
|---|---|
| `inputs/` | The benchmark's inputs, identical for every engine: a portrait and a ~13 s line in the being's own voice (`make_inputs.py`). |
| `musetalk/` | MuseTalk 1.5 through LiveTalking, live over WebRTC (the `devopsavatar/meya-livetalking` image). `make_clip.py` turns a portrait into the short video MuseTalk needs; `bench_client.py` plays the browser's part. |
| `benchmark/pod/` | GPU pod for the photo-to-video engines (SoulX-FlashHead Lite/Pro, EchoMimicV3-Flash): `setup.sh`, `run.sh`, and `pod.py` (RunPod with watchdog and in-pod self-stop). |
| `benchmark/metrics.py` | Quality, measured the same way for every video: identity (ArcFace), lip sync, sharpness, head motion. |
| `benchmark/RESULTS.md` | The latest run, its numbers and the recommendation. |

Rules: every GPU pod has a watchdog that survives network errors and its own self-stop; it is terminated when the
work is done (see the root `CLAUDE.md`). Media stays out of git (`.gitignore`).
