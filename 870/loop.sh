#!/bin/bash
# usage: loop.sh <runs> <burners> <parallel> <label>
runs=$1; burners=$2; parallel=$3; label=$4
cd /app/backend
for i in $(seq "$burners"); do python -c 'while 1: pass' & done
one() {
  local n=$1
  local out=/out/$label-$n.txt
  start=$(date +%s)
  python -B -m pytest -p no:cacheprovider -q -x \
    "tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]" \
    --basetemp "/tmp/b-$label-$n" > "$out" 2>&1
  code=$?
  echo "$label run=$n exit=$code seconds=$(( $(date +%s) - start )) $(grep -o 'serve end job=daily pid=[0-9]* exit=[0-9]* seconds=[0-9]*' "$out" | head -1)"
}
export -f one; export label
seq "$runs" | xargs -P "$parallel" -I{} bash -c 'one {}'
kill $(jobs -p) 2>/dev/null
