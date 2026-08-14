#!/bin/bash
# Sapiens-1B (4.68GB) ships as split COPY layers (docker/assets/sapiens_chunks/)
# instead of one big layer — Docker Hub push kept dying mid-upload on a single
# 4.68GB blob (3/3 identical "broken pipe" failures against the same proxy).
# Reassemble once per cold start before launching the real handler.
set -e
TARGET=/opt/LHM/pretrained_models/sapiens/pretrained/checkpoints/sapiens_1b/sapiens_1b_epoch_173_torchscript.pt2
PARTS_DIR=/opt/LHM/sapiens_chunks
if [ ! -f "$TARGET" ]; then
  cat "$PARTS_DIR"/sapiens_1b.pt2.part_* > "$TARGET"
fi
exec python -u /opt/LHM/rp_handler.py
