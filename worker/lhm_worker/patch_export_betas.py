#!/usr/bin/env python3
"""Build-time patch: LHM's own infer_mesh() computes SMPL-X betas (needed to
build the canonical gaussians in the first place) but never saves them —
only the .ply comes out. B2 (fuse.py) needs those betas to build the SMPL-X
body mesh for head/neck segmentation and FLAME<->SMPL-X registration.

Patches LHM/runners/infer/human_lrm.py to dump a sidecar
"<name>_betas.npy" next to each exported .ply. Fails loudly (non-zero exit)
if the anchor line is gone — never silently no-ops on an upstream change.

Usage (Docker build step, see docker/lhm_worker.Dockerfile):
    python patch_export_betas.py /opt/LHM/LHM/runners/infer/human_lrm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ANCHOR = "        output_gs.save_ply(os.path.join(dump_mesh_dir, output_gs_path))"

PATCH = ANCHOR + """

        # --- avatar-platform B2 patch: export the betas LHM discards ---
        import numpy as _np_b2patch
        _betas_path = os.path.join(
            dump_mesh_dir, output_gs_path.replace('.ply', '_betas.npy')
        )
        _np_b2patch.save(_betas_path, smplx_params['betas'].detach().cpu().numpy())
        print(f"[avatar-platform B2] saved smplx betas to {_betas_path}")
        # --- end patch ---
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_export_betas.py <path to human_lrm.py>")
        return 1
    path = Path(sys.argv[1])
    src = path.read_text()
    if PATCH.strip() in src:
        print(f"[patch] already applied to {path}")
        return 0
    if src.count(ANCHOR) != 1:
        print(f"[patch] FAILED: expected exactly 1 occurrence of the anchor "
             f"line in {path}, found {src.count(ANCHOR)}. LHM upstream code "
             f"changed — update ANCHOR in this script.")
        return 1
    path.write_text(src.replace(ANCHOR, PATCH, 1))
    print(f"[patch] applied to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
