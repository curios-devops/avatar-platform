#!/usr/bin/env bash
# Downloads the MakeHuman asset packs the baker uses (~850 MB) into human/assets_src.
# All CC0 except hair02/hair03, which are CC-BY (strand-textured hair cards; credit the authors).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p assets_src && cd assets_src
for pack in makehuman_system_assets_cc0 skins01_cc0 skins02_cc0 hair01_cc0 hair02_ccby hair03_ccby; do
  [ -d "$pack" ] && continue
  curl -fSL -o "$pack.zip" "https://files.makehumancommunity.org/asset_packs/${pack%_*}/$pack.zip"
  mkdir -p "$pack" && unzip -q -o "$pack.zip" -d "$pack" && rm "$pack.zip"
done
../.venv/bin/python ../fix_pngs.py .
echo "assets ready in $(pwd)"
