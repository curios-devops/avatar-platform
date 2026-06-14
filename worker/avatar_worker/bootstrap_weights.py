"""
Weights bootstrap — download model weights to the network volume on first boot.

RunPod serverless workers start with an empty filesystem except for the
attached network volume (/weights). Instead of uploading weights manually via
a file-browser pod, the worker downloads them once from presigned R2 URLs:

  MICA_TAR_URL   → $MICA_WEIGHTS_PATH/mica.tar              (~503 MB)
  FLAME_PKL_URL  → $MICA_WEIGHTS_PATH/FLAME2020/generic_model.pkl  (~51 MB)

Both env vars are set on the RunPod template. Downloads are skipped when the
target file already exists (subsequent cold starts find the volume populated).
A `.part` temp file + atomic rename guards against truncated downloads if a
worker is killed mid-fetch.
"""

import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

MICA_WEIGHTS = os.getenv("MICA_WEIGHTS_PATH", "/weights/mica")

_TARGETS = {
    "MICA_TAR_URL":  os.path.join(MICA_WEIGHTS, "mica.tar"),
    "FLAME_PKL_URL": os.path.join(MICA_WEIGHTS, "FLAME2020", "generic_model.pkl"),
}


def _download(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    logger.info("bootstrap: downloading %s (...)", os.path.basename(dest))
    with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(8 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)
    logger.info(
        "bootstrap: %s ready (%.0f MB)",
        os.path.basename(dest), os.path.getsize(dest) / 1e6,
    )


def ensure_weights() -> None:
    """Download any missing weight files whose URL env vars are set."""
    for env_key, dest in _TARGETS.items():
        url = os.getenv(env_key, "")
        if not url:
            continue
        if os.path.exists(dest) and os.path.getsize(dest) > 1e6:
            continue
        try:
            _download(url, dest)
        except Exception as exc:
            logger.warning("bootstrap: %s failed (%s) — continuing", env_key, exc)

    # MICA looks for FLAME in its local data/ dir — symlink to volume weights
    mica_data = "/opt/MICA/data"
    os.makedirs(mica_data, exist_ok=True)
    flame_link = os.path.join(mica_data, "FLAME2020")
    flame_real = os.path.join(MICA_WEIGHTS, "FLAME2020")
    if not os.path.exists(flame_link) and os.path.isdir(flame_real):
        try:
            os.symlink(flame_real, flame_link)
            logger.info("bootstrap: symlinked FLAME2020 to %s", flame_link)
        except FileExistsError:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_weights()
