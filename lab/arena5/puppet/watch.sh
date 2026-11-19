#!/bin/bash
# Watchdog for gen.py, copied from lab/backgrounds/watch.sh (CLAUDE.md: stop everything on memory pressure or heat).
# Kills the generation when memory pressure stays above normal for 15 s (45 s while the model loads), goes critical,
# swap grows by more than 3 GB, or macOS limits the CPU for heat. Also logs the lowest free-memory percentage seen.
ST="$(dirname "$0")/chars/.status"
PAT=${WATCH_PAT:-lab/arena5/puppet/[g]en.py}
used() { sysctl vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/' | cut -d. -f1; }
bad=0; start=$(used); minfree=100
stop() { pkill -f "$PAT"; echo "$(date +%H:%M:%S) STOPPED for memory or heat ($1)"; exit 1; }
sleep 2
while pgrep -f "$PAT" >/dev/null; do
  lvl=$(sysctl -n kern.memorystatus_vm_pressure_level)
  grown=$(( $(used) - start ))
  free=$(memory_pressure | awk -F': ' '/free percentage/{gsub("%","",$2); print $2}')
  [ -n "$free" ] && [ "$free" -lt "$minfree" ] && minfree=$free
  heat=$(pmset -g therm | grep -E "CPU_Speed_Limit *= *[0-9]{1,2}$" || true)
  [ "$(cat "$ST" 2>/dev/null)" = "loading" ] && limit=9 || limit=3
  [ "$lvl" -ge 4 ] && stop "memory critical"
  [ -n "$heat" ] && stop "heat: $heat"
  if [ "$lvl" -gt 1 ] || [ "$grown" -gt 3000 ]; then bad=$((bad+1)); echo "$(date +%H:%M:%S) WARN level=$lvl swap+${grown}M ($bad/$limit)"; else bad=0; fi
  [ $bad -ge $limit ] && stop "level=$lvl swap+${grown}M"
  sleep 5
done
echo "$(date +%H:%M:%S) generation finished; lowest free memory ${minfree}%, swap grew ${grown}M"
