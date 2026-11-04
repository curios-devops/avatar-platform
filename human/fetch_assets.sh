#!/usr/bin/env bash
# Downloads the MakeHuman CC0 asset packs the baker uses (~700 MB) into human/assets_src.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p assets_src && cd assets_src
for pack in makehuman_system_assets skins01 skins02 hair01; do
  [ -d "${pack}_cc0" ] && continue
  curl -fSL -o "${pack}_cc0.zip" "https://files.makehumancommunity.org/asset_packs/${pack}/${pack}_cc0.zip"
  mkdir -p "${pack}_cc0" && unzip -q -o "${pack}_cc0.zip" -d "${pack}_cc0" && rm "${pack}_cc0.zip"
done
echo "assets ready in $(pwd)"
