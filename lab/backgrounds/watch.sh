#!/bin/bash
# Watchdog for gen.py (CLAUDE.md: if memory gets tight or the Mac heats up, stop everything and report).
#   lab/backgrounds/watch.sh <out_dir>
# Kills the generation when memory pressure stays above normal for 15 s (45 s while the model loads: that one spike is
# expected and passes), goes critical at any moment, swap grows by more than 3 GB since the watch started (macOS
# grows its swap file, so "free swap" means little), or macOS limits the CPU for heat.
# Prints one line per check worth reading and one final line.
OUT=$1
used() { sysctl vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/' | cut -d. -f1; }
bad=0; start=$(used)
stop() { pkill -f "lab/backgrounds/[g]en.py"; echo "$(date +%H:%M:%S) STOPPED for memory or heat ($1)"; exit 1; }
while pgrep -f "lab/backgrounds/[g]en.py" >/dev/null; do
  lvl=$(sysctl -n kern.memorystatus_vm_pressure_level)
  grown=$(( $(used) - start ))
  heat=$(pmset -g therm | grep -E "CPU_Speed_Limit *= *[0-9]{1,2}$" || true)
  [ "$(cat "$OUT/.status" 2>/dev/null)" = "loading" ] && limit=9 || limit=3
  [ "$lvl" -ge 4 ] && stop "memory critical"
  [ -n "$heat" ] && stop "heat: $heat"
  if [ "$lvl" -gt 1 ] || [ "$grown" -gt 3000 ]; then bad=$((bad+1)); echo "$(date +%H:%M:%S) WARN level=$lvl swap+${grown}M ($bad/$limit)"; else bad=0; fi
  [ $bad -ge $limit ] && stop "level=$lvl swap+${grown}M"
  sleep 5
done
echo "$(date +%H:%M:%S) generation finished"
