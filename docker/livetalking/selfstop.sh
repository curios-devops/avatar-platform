#!/bin/bash
# The pod terminates itself after MAX_SECONDS, even if the Mac's watchdog is dead. RunPod's env (pod id, pod-scoped
# key) lives in PID 1's environment; an SSH session does not inherit it, so it is read from there. The pod key works
# with GraphQL (runpodctl does not read it from the environment). `selfstop.sh now` terminates at once.
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^RUNPOD_(POD_ID|API_KEY)=' | sed 's/^/export /')"
[ "$1" = now ] || sleep ${MAX_SECONDS:-7200}
gql() { curl -s -m 30 -H "Content-Type: application/json" -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d "{\"query\":\"mutation { $1(input:{podId:\\\"$RUNPOD_POD_ID\\\"}) $2 }\"}" https://api.runpod.io/graphql; }
for i in 1 2 3 4 5 6; do
  echo "$(date) self-stop $RUNPOD_POD_ID try $i"
  out=$(gql podTerminate ""); echo "$out"; echo "$out" | grep -q '"errors"' || exit 0
  out=$(gql podStop "{ id desiredStatus }"); echo "$out"; echo "$out" | grep -q '"errors"' || exit 0
  sleep 30
done
kill 1
