"""A2 — Worker serverless de lip-sync (MuseTalk) con network volume.

Jobs:
  {"job_type": "bootstrap"}                      → aprovisiona el volumen
      (clona MuseTalk, pip --target, pesos HF). Idempotente, ~20-30 min la
      primera vez; después no-op. Único job que no necesita los modelos.
  {"job_type": "warmup"}                         → carga modelos residentes
  {"job_type": "prepare_avatar", "avatar_id", "clips": {nombre: mp4_b64}}
      → precomputa latentes por clip en el VOLUMEN (persisten entre workers)
  {"job_type": "speak", "avatar_id", "gesto", "audio_b64", "audio_mime"}
      → repinta boca sobre frames del clip del gesto → {"video_b64", ...}

Diseño: imagen mínima (base runpod/pytorch cu118 + este archivo); todo lo
pesado vive en /runpod-volume. Modelos LAZY — nunca cargar en import
(lección LAM: bloquea el registro del worker). Latentes por avatar en el
volumen → FlashBoot + prepare-once + cualquier worker sirve a cualquier
avatar.
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

VOL = Path("/runpod-volume")
MUSETALK_ROOT = VOL / "MuseTalk"
DEPS = VOL / "pydeps"
AVATARS_DIR = VOL / "avatars"
FPS = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("musetalk_worker")

_models: dict = {}
_avatars: dict = {}
_MODELS_ERR: str | None = None


# ── bootstrap del volumen ────────────────────────────────────────────────────

def _sh(cmd: str) -> None:
    logger.info("$ %s", cmd)
    subprocess.run(cmd, shell=True, check=True)


def do_bootstrap() -> dict:
    t0 = time.time()
    steps = []
    VOL.mkdir(exist_ok=True)
    if not MUSETALK_ROOT.exists():
        _sh(f"git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git {MUSETALK_ROOT}")
        steps.append("clone")
    if not (DEPS / ".ok").exists():
        DEPS.mkdir(exist_ok=True)
        # requirements del repo + mmlab (wheels precompiladas cu118/torch2.0)
        # al target del volumen; torch ya está en la imagen base.
        _sh(f"pip install --no-cache-dir --target {DEPS} -r {MUSETALK_ROOT}/requirements.txt "
            f"|| true")
        # mmcv desde las wheels precompiladas de OpenMMLab (mim no soporta
        # --target; pip con el find-links equivalente sí es determinista)
        _sh(f"pip install --no-cache-dir --target {DEPS} 'mmcv==2.0.1' "
            f"-f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html")
        _sh(f"pip install --no-cache-dir --target {DEPS} mmengine 'mmdet==3.1.0' 'mmpose==1.1.0'")
        _sh(f"pip install --no-cache-dir --target {DEPS} transformers accelerate librosa "
            f"soundfile imageio[ffmpeg] 'huggingface_hub[cli]<1.0'")
        (DEPS / ".ok").touch()
        steps.append("deps")
    if not (DEPS / ".hfstack_v3").exists():
        # Pins EXACTOS del requirements.txt de MuseTalk (fuente de verdad):
        # diffusers 0.30.2 ya NO importa cached_download (eso era 0.27), y
        # transformers 4.39.2 trae el shim de pytree para torch 2.0.1.
        # --ignore-installed fuerza TODO al volumen (pip --target salta lo que
        # ya está en la imagen → volumen incompleto → resolución a la imagen).
        _sh(f"rm -rf {DEPS}/diffusers* {DEPS}/transformers* {DEPS}/huggingface_hub* "
            f"{DEPS}/accelerate* {DEPS}/tokenizers* {DEPS}/safetensors*")
        _sh(f"pip install --no-cache-dir --target {DEPS} --ignore-installed --no-deps "
            f"'transformers==4.39.2' 'diffusers==0.30.2' 'accelerate==0.28.0' "
            f"'huggingface_hub==0.30.2' 'tokenizers==0.15.2' 'safetensors>=0.4.2' "
            f"'regex' 'requests' 'pyyaml' 'filelock' 'fsspec' 'importlib_metadata'")
        (DEPS / ".hfstack_v3").touch()
        steps.append("hfstack_v3")
    if not (DEPS / ".strip_torch").exists():
        # requirements.txt de MuseTalk metió torch 2.13 (CPU) al volumen via
        # --target; según qué import gane, se mezcla con el 2.0.1+cu118 de la
        # imagen (errores pytree intermitentes). El volumen NO lleva torch:
        # manda siempre el de la imagen.
        _sh(f"rm -rf {DEPS}/torch {DEPS}/torch-* {DEPS}/torchvision* "
            f"{DEPS}/torchaudio* {DEPS}/functorch* {DEPS}/nvidia* {DEPS}/triton* "
            f"{DEPS}/torchgen*")
        (DEPS / ".strip_torch").touch()
        steps.append("strip_torch")
    if not (MUSETALK_ROOT / "models/musetalkV15/unet.pth").exists():
        dw = MUSETALK_ROOT / "download_weights.sh"
        if dw.exists():
            _sh(f"cd {MUSETALK_ROOT} && PYTHONPATH={DEPS} bash download_weights.sh")
        else:
            _sh(f"PYTHONPATH={DEPS} {DEPS}/bin/huggingface-cli download TMElyralab/MuseTalk "
                f"--local-dir {MUSETALK_ROOT}/models")
        steps.append("weights")
    AVATARS_DIR.mkdir(exist_ok=True)
    # ffmpeg en la imagen (apt) — por si la base no lo trae
    if subprocess.run("which ffmpeg", shell=True).returncode != 0:
        _sh("apt-get update -qq && apt-get install -y -qq ffmpeg")
        steps.append("ffmpeg")
    return {"bootstrapped": steps or ["noop"], "seconds": round(time.time() - t0, 1)}


# ── modelos residentes (lazy) ────────────────────────────────────────────────

def _ensure_models() -> None:
    global _MODELS_ERR
    if _models or _MODELS_ERR:
        return
    try:
        t0 = time.time()
        sys.path.insert(0, str(DEPS))
        sys.path.insert(0, str(MUSETALK_ROOT))
        os.chdir(MUSETALK_ROOT)
        # El stack HF del volumen debe ganar al de la imagen: si algo ya
        # importó huggingface_hub/transformers desde /usr/local/lib, queda
        # cacheado en sys.modules y NUESTRO path insert no aplica → purgar.
        for mod in list(sys.modules):
            if mod.split(".")[0] in ("huggingface_hub", "transformers",
                                     "diffusers", "tokenizers", "safetensors"):
                del sys.modules[mod]
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


# ── handler ──────────────────────────────────────────────────────────────────

def do_diag() -> dict:
    """Visibilidad total del volumen: versiones instaladas + resolución real
    de imports (sin cargar modelos). Para depurar conflictos sin adivinar."""
    out = {"dist_info": {}, "imports": {}}
    for d in sorted(DEPS.glob("*.dist-info")):
        name = d.name.replace(".dist-info", "")
        out["dist_info"][name.rsplit("-", 1)[0]] = name.rsplit("-", 1)[-1]
    sys.path.insert(0, str(DEPS))
    for mod in list(sys.modules):
        if mod.split(".")[0] in ("huggingface_hub", "transformers", "diffusers",
                                 "tokenizers", "safetensors", "peft", "accelerate"):
            del sys.modules[mod]
    for name in ("torch", "huggingface_hub", "transformers", "diffusers",
                 "peft", "accelerate", "mmcv", "mmpose"):
        try:
            m = __import__(name)
            out["imports"][name] = {"version": getattr(m, "__version__", "?"),
                                    "file": getattr(m, "__file__", "?")}
        except Exception as e:
            out["imports"][name] = {"error": f"{type(e).__name__}: {e}"[:300]}
    return out


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
                    "error": _MODELS_ERR}

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
