"""A2 — Worker de lip-sync con MuseTalk residente (pod GPU persistente).

FastAPI en el pod (puerto 8600):
  GET  /health            → {ready, models_loaded, avatars: [...]}
  POST /prepare           → {avatar_id, clips: {nombre: mp4_b64}} —
                            precomputa latentes por clip (Avatar preparation)
  POST /speak             → {avatar_id, gesto, audio_b64, audio_mime} —
                            repinta la boca sobre los frames del clip del
                            gesto y devuelve MP4 H.264 (b64) con el audio.

Diseño (plan A2): los modelos (VAE+UNet+whisper) viven en VRAM desde el
arranque; cada clip base preparado = un "avatar" MuseTalk cuyos latentes se
cachean en disco. El scheduler de frases elige el clip por `gesto` y recorre
sus frames en ping-pong (como hace MuseTalk) para cubrir la duración del
audio. Un pod 24 GB debe sostener ≥3 sesiones a 25 fps (aceptación).

Este módulo importa código de MuseTalk (clonado por bootstrap.sh en
/workspace/MuseTalk) adaptando scripts/realtime_inference.py a servicio.
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MUSETALK_ROOT = Path(os.getenv("MUSETALK_ROOT", "/workspace/MuseTalk"))
AVATARS_DIR = Path(os.getenv("AVATARS_DIR", "/workspace/avatars"))
FPS = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("musetalk_worker")

app = FastAPI(title="musetalk-worker")
_lock = Lock()                      # una inferencia GPU a la vez (MVP)
_models: dict = {}                  # modelos residentes
_avatars: dict[str, "object"] = {}  # (avatar_id, clip) → Avatar preparado


# ── carga residente de modelos (una vez) ─────────────────────────────────────

def _load_models() -> None:
    """Replica la carga global de scripts/realtime_inference.py."""
    if _models:
        return
    os.chdir(MUSETALK_ROOT)
    sys.path.insert(0, str(MUSETALK_ROOT))
    t0 = time.time()
    import torch
    from musetalk.utils.utils import load_all_model
    from musetalk.utils.audio_processor import AudioProcessor
    from transformers import WhisperModel

    vae, unet, pe = load_all_model(
        unet_model_path=str(MUSETALK_ROOT / "models/musetalkV15/unet.pth"),
        vae_type="sd-vae",
        unet_config=str(MUSETALK_ROOT / "models/musetalkV15/musetalk.json"),
        device="cuda",
    )
    # half precision como el script oficial
    pe = pe.half().to("cuda")
    vae.vae = vae.vae.half().to("cuda")
    unet.model = unet.model.half().to("cuda")

    audio_processor = AudioProcessor(feature_extractor_path=str(MUSETALK_ROOT / "models/whisper"))
    whisper = WhisperModel.from_pretrained(str(MUSETALK_ROOT / "models/whisper"))
    whisper = whisper.to(device="cuda", dtype=torch.float16).eval()
    whisper.requires_grad_(False)

    _models.update(vae=vae, unet=unet, pe=pe,
                   audio_processor=audio_processor, whisper=whisper)
    logger.info("modelos MuseTalk residentes en %.1fs", time.time() - t0)


def _make_avatar(avatar_key: str, video_path: str, preparation: bool):
    """Instancia la clase Avatar del repo con los modelos residentes."""
    import scripts.realtime_inference as ri

    # la clase usa globals del módulo — inyectamos los residentes
    for k, v in _models.items():
        setattr(ri, k, v)
    ri.args = type("A", (), {
        "version": "v15", "extra_margin": 10, "parsing_mode": "jaw",
        "skip_save_images": True, "audio_padding_length_left": 2,
        "audio_padding_length_right": 2, "fps": FPS, "batch_size": 20,
        "output_vid_name": None, "left_cheek_width": 90, "right_cheek_width": 90,
        "result_dir": str(AVATARS_DIR), "avatar_dir": str(AVATARS_DIR),
    })()
    return ri.Avatar(avatar_id=avatar_key, video_path=video_path,
                     bbox_shift=0, batch_size=20, preparation=preparation)


# ── API ──────────────────────────────────────────────────────────────────────

class PrepareReq(BaseModel):
    avatar_id: str
    clips: dict[str, str]           # nombre → mp4 base64


class SpeakReq(BaseModel):
    avatar_id: str
    gesto: str = "idle_a"
    audio_b64: str                  # mp3/wav de UNA frase
    audio_mime: str = "audio/mpeg"


@app.get("/health")
def health():
    return {"ready": bool(_models), "avatars": sorted(_avatars.keys())}


@app.on_event("startup")
def startup():
    _load_models()
    # re-adoptar avatares ya preparados en disco (reinicios del server)
    for d in glob.glob(str(AVATARS_DIR / "*__*")):
        key = Path(d).name
        try:
            _avatars[key] = _make_avatar(key, video_path="", preparation=False)
            logger.info("avatar re-adoptado: %s", key)
        except Exception as e:
            logger.warning("no se pudo re-adoptar %s: %s", key, e)


@app.post("/prepare")
def prepare(req: PrepareReq):
    t0 = time.time()
    done = []
    with _lock:
        for name, b64 in req.clips.items():
            key = f"{req.avatar_id}__{name}"
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(base64.b64decode(b64))
                path = f.name
            try:
                _avatars[key] = _make_avatar(key, video_path=path, preparation=True)
                done.append(name)
                logger.info("preparado %s (%.1fs acumulado)", key, time.time() - t0)
            finally:
                os.unlink(path)
    return {"prepared": done, "seconds": round(time.time() - t0, 1)}


@app.post("/speak")
def speak(req: SpeakReq):
    key = f"{req.avatar_id}__{req.gesto}"
    if key not in _avatars:
        # fallback al idle si el gesto no está preparado
        key = f"{req.avatar_id}__idle_a"
        if key not in _avatars:
            raise HTTPException(404, f"avatar/gesto no preparado: {req.avatar_id}/{req.gesto}")
    t0 = time.time()
    suffix = ".wav" if "wav" in req.audio_mime else ".mp3"
    with tempfile.TemporaryDirectory() as td:
        audio_in = Path(td) / f"in{suffix}"
        audio_in.write_bytes(base64.b64decode(req.audio_b64))
        wav = Path(td) / "in.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio_in),
                        "-ar", "16000", "-ac", "1", str(wav)], check=True)

        with _lock:
            out_name = f"chunk_{int(time.time()*1000)}"
            _avatars[key].inference(audio_path=str(wav), out_vid_name=out_name,
                                    fps=FPS, skip_save_images=True)
        # el script deja el video en {avatar_dir}/{key}/vid_output/{out_name}.mp4
        candidates = glob.glob(str(AVATARS_DIR / key / "vid_output" / f"{out_name}*"))
        if not candidates:
            raise HTTPException(500, "MuseTalk no produjo video")
        raw = candidates[0]
        final = Path(td) / "final.mp4"
        # H.264 + mux del audio original (el raw sale sin audio)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-i", str(audio_in),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(final)], check=True)
        video_b64 = base64.b64encode(final.read_bytes()).decode()
        os.unlink(raw)
    dt = time.time() - t0
    logger.info("/speak %s: %.2fs", key, dt)
    return {"video_b64": video_b64, "seconds": round(dt, 2), "clip": key.split("__")[-1]}
