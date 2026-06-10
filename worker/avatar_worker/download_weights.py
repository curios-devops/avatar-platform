"""
Download model weights to the weights directory.

Run once before deploying, or inside the Docker build to bake weights in.
On RunPod, mount a Network Volume at /weights and run this script once.

Usage:
    python download_weights.py [--all] [--deca] [--mica] [--emoca]

Environment variables (override default paths / download URLs):
    WEIGHTS_DIR          default /weights (or ./weights on dev machines)
    DECA_GDRIVE_ID       Google Drive file ID for deca_model.tar
    MICA_DOWNLOAD_URL    Direct URL for mica.tar  (set after registering at mica.is.tue.mpg.de)
    EMOCA_DOWNLOAD_URL   Direct URL for emoca.tar (set after registering at emoca.is.tue.mpg.de)

DECA weights — Google Drive (handled by gdown):
    File ID: 1rp8kdyLPvErw2dTmqtjISRVvQLj6Yzje  (~430 MB)
    Manual:  https://github.com/YadiraF/DECA → "Data and Model"

MICA weights — requires registration:
    1. Register at https://mica.is.tue.mpg.de/
    2. Download mica.tar  (~200 MB) and cfg.yaml
    3. Place at $WEIGHTS_DIR/mica/mica.tar and $WEIGHTS_DIR/mica/cfg.yaml
    OR set MICA_DOWNLOAD_URL to a pre-signed URL and re-run this script.
    Insightface antelopev2 models are auto-downloaded by the insightface library.

EMOCA weights — requires registration:
    1. Register at https://emoca.is.tue.mpg.de/
    2. Download EMOCA_v2.zip (~1.5 GB), unzip to $WEIGHTS_DIR/emoca/
       (should contain emoca.tar + cfg.yaml)
    OR set EMOCA_DOWNLOAD_URL to a pre-signed URL and re-run this script.
"""

from __future__ import annotations

import argparse
import os
import sys

# ── path setup ────────────────────────────────────────────────────────────────
_default_dir = (
    "/weights"
    if os.path.isdir("/weights")
    else os.path.join(os.path.dirname(__file__), "../../weights")
)
WEIGHTS_DIR = os.getenv("WEIGHTS_DIR", os.path.abspath(_default_dir))

# ── download sources ──────────────────────────────────────────────────────────
DECA_GDRIVE_ID     = os.getenv("DECA_GDRIVE_ID",     "1rp8kdyLPvErw2dTmqtjISRVvQLj6Yzje")
MICA_DOWNLOAD_URL  = os.getenv("MICA_DOWNLOAD_URL",  "")
EMOCA_DOWNLOAD_URL = os.getenv("EMOCA_DOWNLOAD_URL", "")


# ── helpers ───────────────────────────────────────────────────────────────────

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _size_mb(path: str) -> float:
    return os.path.getsize(path) / 1e6


def _wget(url: str, dest: str) -> None:
    """Download url → dest using wget (available in the Docker image)."""
    import subprocess
    print(f"  Downloading {url}\n  → {dest}")
    ret = subprocess.run(["wget", "-q", "--show-progress", "-O", dest, url])
    if ret.returncode != 0:
        raise RuntimeError(f"wget failed for {url}")


def _gdown(gdrive_id: str, dest: str) -> None:
    """Download Google Drive file by ID using gdown."""
    try:
        import gdown  # type: ignore[import]
    except ImportError:
        print("gdown not found — installing…")
        os.system(f"{sys.executable} -m pip install -q gdown")
        import gdown  # type: ignore[import]
    print(f"  Downloading Drive ID {gdrive_id} → {dest}")
    gdown.download(id=gdrive_id, output=dest, quiet=False)


# ── individual downloaders ────────────────────────────────────────────────────

def download_deca() -> None:
    dest = os.path.join(WEIGHTS_DIR, "deca_model.tar")
    _ensure_dir(WEIGHTS_DIR)

    if os.path.exists(dest):
        print(f"[DECA] Already at {dest} ({_size_mb(dest):.0f} MB) — skipping.")
        return

    print("[DECA] Downloading deca_model.tar from Google Drive…")
    _gdown(DECA_GDRIVE_ID, dest)

    if os.path.exists(dest):
        print(f"[DECA] Done — {_size_mb(dest):.0f} MB at {dest}")
    else:
        print("[DECA] Download failed. See the module docstring for manual instructions.")
        sys.exit(1)


def download_mica() -> None:
    mica_dir  = os.path.join(WEIGHTS_DIR, "mica")
    ckpt_dest = os.path.join(mica_dir, "mica.tar")
    _ensure_dir(mica_dir)

    if os.path.exists(ckpt_dest):
        print(f"[MICA] Already at {ckpt_dest} ({_size_mb(ckpt_dest):.0f} MB) — skipping.")
        return

    if not MICA_DOWNLOAD_URL:
        print(
            "[MICA] MICA_DOWNLOAD_URL not set.\n"
            "  Register at https://mica.is.tue.mpg.de/ and download mica.tar,\n"
            f"  then place it at {ckpt_dest}\n"
            "  OR re-run with MICA_DOWNLOAD_URL=<pre-signed-url>."
        )
        return

    print(f"[MICA] Downloading mica.tar from {MICA_DOWNLOAD_URL[:60]}…")
    _wget(MICA_DOWNLOAD_URL, ckpt_dest)
    if os.path.exists(ckpt_dest):
        print(f"[MICA] Done — {_size_mb(ckpt_dest):.0f} MB at {ckpt_dest}")
    else:
        print("[MICA] Download failed — check MICA_DOWNLOAD_URL.")
        sys.exit(1)


def download_emoca() -> None:
    emoca_dir = os.path.join(WEIGHTS_DIR, "emoca")
    ckpt_dest = os.path.join(emoca_dir, "emoca.tar")
    _ensure_dir(emoca_dir)

    if os.path.exists(ckpt_dest):
        print(f"[EMOCA] Already at {ckpt_dest} ({_size_mb(ckpt_dest):.0f} MB) — skipping.")
        return

    if not EMOCA_DOWNLOAD_URL:
        print(
            "[EMOCA] EMOCA_DOWNLOAD_URL not set.\n"
            "  Register at https://emoca.is.tue.mpg.de/ and download EMOCA_v2.zip,\n"
            f"  unzip to {emoca_dir}/ (should contain emoca.tar + cfg.yaml)\n"
            "  OR re-run with EMOCA_DOWNLOAD_URL=<pre-signed-url>."
        )
        return

    print(f"[EMOCA] Downloading emoca.tar from {EMOCA_DOWNLOAD_URL[:60]}…")
    _wget(EMOCA_DOWNLOAD_URL, ckpt_dest)
    if os.path.exists(ckpt_dest):
        print(f"[EMOCA] Done — {_size_mb(ckpt_dest):.0f} MB at {ckpt_dest}")
    else:
        print("[EMOCA] Download failed — check EMOCA_DOWNLOAD_URL.")
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Download avatar worker model weights")
    parser.add_argument("--all",   action="store_true", help="Download all weights")
    parser.add_argument("--deca",  action="store_true", help="Download DECA weights only")
    parser.add_argument("--mica",  action="store_true", help="Download MICA weights only")
    parser.add_argument("--emoca", action="store_true", help="Download EMOCA weights only")
    args = parser.parse_args()

    # Default to --all if nothing specified
    if not any([args.deca, args.mica, args.emoca]):
        args.all = True

    print(f"Weights directory: {WEIGHTS_DIR}\n")

    if args.all or args.deca:
        download_deca()
    if args.all or args.mica:
        download_mica()
    if args.all or args.emoca:
        download_emoca()

    print("\nDone.")


if __name__ == "__main__":
    main()
