#!/bin/bash
# One generation run under the watchdog and caffeinate:  lab/arena5/puppet/run.sh portraits [ids]  |  mouths <char> [shapes]
# Refuses to start while another image job runs (CLAUDE.md: never two heavy tasks).
cd "$(dirname "$0")/../../.."
if pgrep -f "lab/backgrounds/[g]en.py|lab/arena5/puppet/[g]en.py" >/dev/null; then echo "another image job is running"; exit 1; fi
PY=${MFLUX_PY:-/private/tmp/claude-501/-Users-mac-Documents-avatar-platform/97e46d35-7d99-47b9-9102-a40ceaf3683c/scratchpad/mfvenv/bin/python}
caffeinate -i -t 7200 & CAF=$!
"$PY" -u lab/arena5/puppet/gen.py "$@" & GEN=$!
bash lab/arena5/puppet/watch.sh
wait $GEN; kill $CAF 2>/dev/null; echo "RUN_DONE"
