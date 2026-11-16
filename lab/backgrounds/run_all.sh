#!/bin/bash
# The MEYA scenes in one go, safely: generation (gen.py: one process, one image at a time) under the watchdog
# (watch.sh stops it on memory pressure or heat), publishing each scene to the web as soon as it is done
# (publish.py, seconds). Best with heavy browser tabs closed: a 16 GB Mac with a video call and many tabs open sits
# at memory pressure "warn" before the model even loads. A stopped run resumes: with no ids it only makes the scenes
# that have no PNG yet.
#   lab/backgrounds/run_all.sh            # whatever is missing
#   lab/backgrounds/run_all.sh mars moon  # redo these
cd "$(dirname "$0")/../.." || exit 1
VENV=${MFLUX_VENV:-/private/tmp/claude-501/-Users-mac-Documents-avatar-platform/97e46d35-7d99-47b9-9102-a40ceaf3683c/scratchpad/mfvenv}
WEB=/Users/mac/Documents/ManyMe/apps/web
OUT=lab/inputs/backgrounds
PUBLISH="backend/.venv/bin/python lab/backgrounds/publish.py $OUT $WEB/public/backgrounds $WEB/src/lib/background/presets.json"
caffeinate -i -t 7200 &
CAF=$!
rm -f "$OUT/.status"
AFTER_EACH="$PUBLISH" "$VENV/bin/python" -u lab/backgrounds/gen.py "$OUT" "$@" 2> "$OUT/gen.err" &  # stderr: progress bars and tracebacks
sleep 2
lab/backgrounds/watch.sh "$OUT"; rc=$?
kill $CAF 2>/dev/null
rm -f "$OUT/.status"
$PUBLISH
[ $rc -ne 0 ] && { echo "stopped: memory or heat. Close heavy apps and run again; it resumes where it stopped."; exit 1; }
echo ALL_DONE
