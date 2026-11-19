#!/bin/bash
# The keyframe generator (kf.py serve) under caffeinate and the watchdog; queue jobs with kf.py add, end with kf.py quit.
# Refuses to start while another image job runs (CLAUDE.md: never two heavy tasks).
cd "$(dirname "$0")/../../.."
if pgrep -f "lab/backgrounds/[g]en.py|lab/arena5/puppet/[g]en.py|lab/arena5/puppet/[k]f.py serve" >/dev/null; then echo "another image job is running"; exit 1; fi
PY=${MFLUX_PY:-/private/tmp/claude-501/-Users-mac-Documents-avatar-platform/97e46d35-7d99-47b9-9102-a40ceaf3683c/scratchpad/mfvenv2/bin/python}
caffeinate -i -t 7200 & CAF=$!
"$PY" -u lab/arena5/puppet/kf.py serve & GEN=$!
WATCH_PAT="lab/arena5/puppet/[k]f.py serve" bash lab/arena5/puppet/watch.sh
wait $GEN; kill $CAF 2>/dev/null; echo "RUN_DONE"
