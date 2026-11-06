"""ArcFace identity of each render against the seed image (qa/metrics.py helpers, CPU).

    backend/.venv/bin/python splat/score.py seed.jpg shots_dir/*.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "avatar-platform" / "qa"))
from metrics import _embed  # noqa: E402


def main() -> None:
    ref = _embed(np.array(Image.open(sys.argv[1]).convert("RGB")))
    out = {}
    for p in sys.argv[2:]:
        e = _embed(np.array(Image.open(p).convert("RGB")))
        out[Path(p).name] = None if e is None or ref is None else round(float(np.dot(e, ref)), 3)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
