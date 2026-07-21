"""A2 — Worker serverless de lip-sync (MuseTalk). Deps EN LA IMAGEN.

Arquitectura (reescrita 2026-07-19 tras 6 ciclos peleando pip --target al
volumen): el repo + todas las deps viven en la imagen (/opt/MuseTalk, entorno
limpio). El NETWORK VOLUME guarda solo lo pesado y persistente:
  /runpod-volume/models   → pesos (~12 GB), symlinkados a /opt/MuseTalk/models
  /runpod-volume/avatars  → latentes por avatar (prepare-once, entre workers)

Jobs:
  {"job_type":"bootstrap"}   → baja los pesos al volumen (una vez). Sin pip.
  {"job_type":"warmup"}      → carga modelos residentes (lazy, nunca en import)
  {"job_type":"prepare_avatar","avatar_id","clips":{nombre: mp4_b64}}
  {"job_type":"speak","avatar_id","gesto","audio_b64","audio_mime"} → MP4 b64
  {"job_type":"diag"}        → versiones + resolución de imports (depurar)
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
import traceback
from pathlib import Path

import runpod

MUSETALK_ROOT = Path(os.getenv("MUSETALK_ROOT", "/opt/MuseTalk"))
VOL = Path("/runpod-volume")
MODELS_VOL = VOL / "models"                 # pesos (persistentes)
AVATARS_DIR = VOL / "avatars"               # latentes por avatar
FPS = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("musetalk_worker")

_models: dict = {}
_avatars: dict = {}
_MODELS_ERR: str | None = None


def _sh(cmd: str) -> None:
    logger.info("$ %s", cmd)
    subprocess.run(cmd, shell=True, check=True)


def _link_models() -> None:
    """Symlink /opt/MuseTalk/models → volumen (los pesos viven en el volumen)."""
    MODELS_VOL.mkdir(parents=True, exist_ok=True)
    link = MUSETALK_ROOT / "models"
    if link.is_symlink():
        if link.resolve() != MODELS_VOL.resolve():
            link.unlink(); link.symlink_to(MODELS_VOL)
    elif link.exists():           # dir real de la imagen → moverlo al volumen 1ª vez
        for p in link.iterdir():
            dest = MODELS_VOL / p.name
            if not dest.exists():
                _sh(f"cp -r '{p}' '{dest}'")
        _sh(f"rm -rf '{link}'"); link.symlink_to(MODELS_VOL)
    else:
        link.symlink_to(MODELS_VOL)


def do_bootstrap() -> dict:
    t0 = time.time()
    steps = []
    _link_models()
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    unet = MODELS_VOL / "musetalkV15" / "unet.pth"
    if not unet.exists() or unet.stat().st_size < 1_000_000:
        # descarga robusta: el repo HF completo al volumen (via symlink models).
        # download_weights.sh depende de flags que cambian con el hub; el
        # download directo es determinista.
        _sh(f"huggingface-cli download TMElyralab/MuseTalk "
            f"--local-dir {MODELS_VOL} --local-dir-use-symlinks False")
        steps.append("weights")
    ok = unet.exists() and unet.stat().st_size > 1_000_000
    size_gb = round(sum(p.stat().st_size for p in MODELS_VOL.rglob('*') if p.is_file()) / 1e9, 1)
    return {"bootstrapped": steps or ["noop"], "weights_ok": ok,
            "unet_mb": round(unet.stat().st_size / 1e6, 1) if unet.exists() else 0,
            "models_gb": size_gb, "seconds": round(time.time() - t0, 1)}


def do_diag() -> dict:
    out = {"imports": {}, "models_dir": []}
    for name in ("torch", "huggingface_hub", "transformers", "diffusers",
                 "mmcv", "mmpose"):
        try:
            m = __import__(name)
            out["imports"][name] = {"version": getattr(m, "__version__", "?"),
                                    "file": getattr(m, "__file__", "?")}
        except Exception as e:
            out["imports"][name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    try:
        out["models_dir"] = sorted(p.name for p in MODELS_VOL.iterdir())
    except Exception as e:
        out["models_dir"] = [f"error: {e}"]
    return out


def _ensure_models() -> None:
    global _MODELS_ERR
    if _models or _MODELS_ERR:
        return
    try:
        t0 = time.time()
        os.chdir(MUSETALK_ROOT)
        sys.path.insert(0, str(MUSETALK_ROOT))
        _link_models()
        import torch
        from musetalk.utils.utils import load_all_model
        from musetalk.utils.audio_processor import AudioProcessor
        from transformers import WhisperModel

        vae, unet, pe = load_all_model(
            unet_model_path="models/musetalkV15/unet.pth",
            vae_type="sd-vae",
            unet_config="models/musetalkV15/musetalk.json",
            device="cuda",
        )
        pe = pe.half().to("cuda")
        vae.vae = vae.vae.half().to("cuda")
        unet.model = unet.model.half().to("cuda")
        audio_processor = AudioProcessor(feature_extractor_path="models/whisper")
        whisper = WhisperModel.from_pretrained("models/whisper")
        whisper = whisper.to(device="cuda", dtype=torch.float16).eval()
        whisper.requires_grad_(False)
        _models.update(vae=vae, unet=unet, pe=pe,
                       audio_processor=audio_processor, whisper=whisper)
        logger.info("modelos residentes en %.1fs", time.time() - t0)
    except Exception:
        _MODELS_ERR = traceback.format_exc()
        logger.error("carga de modelos falló:\n%s", _MODELS_ERR)


def _make_avatar(avatar_key: str, video_path: str, preparation: bool):
    import scripts.realtime_inference as ri
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


def _get_avatar(key: str):
    if key not in _avatars:
        if not (AVATARS_DIR / key).exists():
            return None
        _avatars[key] = _make_avatar(key, video_path="", preparation=False)
    return _avatars[key]


def handler(job):
    inp = job.get("input") or {}
    jt = inp.get("job_type")
    try:
        if jt == "bootstrap":
            return do_bootstrap()
        if jt == "diag":
            return do_diag()
        if jt == "warmup":
            t0 = time.time()
            _ensure_models()
            return {"warmed": _MODELS_ERR is None, "load_s": round(time.time() - t0, 1),
                    "error": (_MODELS_ERR or "")[-600:] or None}

        if jt == "prepare_avatar":
            _ensure_models()
            if _MODELS_ERR:
                return {"error": f"modelos no disponibles: {_MODELS_ERR[-400:]}"}
            t0 = time.time()
            done = []
            for name, b64 in (inp.get("clips") or {}).items():
                key = f"{inp['avatar_id']}__{name}"
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    f.write(base64.b64decode(b64)); path = f.name
                try:
                    _avatars[key] = _make_avatar(key, path, preparation=True)
                    done.append(name)
                finally:
                    os.unlink(path)
            return {"prepared": done, "seconds": round(time.time() - t0, 1)}

        if jt == "speak":
            _ensure_models()
            if _MODELS_ERR:
                return {"error": f"modelos no disponibles: {_MODELS_ERR[-400:]}"}
            t0 = time.time()
            key = f"{inp['avatar_id']}__{inp.get('gesto', 'idle_a')}"
            av = _get_avatar(key) or _get_avatar(f"{inp['avatar_id']}__idle_a")
            if av is None:
                return {"error": f"avatar no preparado: {key}"}
            mime = inp.get("audio_mime", "audio/mpeg")
            suffix = ".wav" if "wav" in mime else ".mp3"
            with tempfile.TemporaryDirectory() as td:
                audio_in = Path(td) / f"in{suffix}"
                audio_in.write_bytes(base64.b64decode(inp["audio_b64"]))
                wav = Path(td) / "in.wav"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio_in),
                                "-ar", "16000", "-ac", "1", str(wav)], check=True)
                out_name = f"chunk_{int(time.time()*1000)}"
                av.inference(audio_path=str(wav), out_vid_name=out_name,
                             fps=FPS, skip_save_images=True)
                cands = glob.glob(str(AVATARS_DIR / key / "vid_output" / f"{out_name}*"))
                if not cands:
                    return {"error": "MuseTalk no produjo video"}
                final = Path(td) / "final.mp4"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", cands[0],
                                "-i", str(audio_in), "-c:v", "libx264", "-preset", "veryfast",
                                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                                str(final)], check=True)
                os.unlink(cands[0])
                return {"video_b64": base64.b64encode(final.read_bytes()).decode(),
                        "seconds": round(time.time() - t0, 2)}

        return {"error": f"job_type desconocido: {jt}"}
    except Exception:
        return {"error": traceback.format_exc()[-1500:]}


runpod.serverless.start({"handler": handler})
