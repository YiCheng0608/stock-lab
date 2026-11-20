#!/bin/bash
# usage: run.sh <name> <outsub> [extra docker args...] -- <tool args...>
set -u
cd C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-866-explore-m1m2 || exit 1
T=C:/Users/YiCheng/t866
IMG=t866-backend:6acdb631
NAME=$1; SUB=$2; shift 2
DOPTS=(); while [ "$1" != "--" ]; do DOPTS+=("$1"); shift; done; shift
O="$T/$SUB"; mkdir -p "$O"
busy=$(docker ps --filter volume=stock-lab-research --format '{{.Names}}')
if [ -n "$busy" ]; then echo "busy: $busy"; exit 3; fi
export MSYS_NO_PATHCONV=1
docker run -d --name "research-866-$NAME" --network none --memory 4g --memory-swap 4g "${DOPTS[@]}" \
  -v stock-lab-research:/research -v "$O":/out \
  -v "$(git rev-parse --git-common-dir):/repo.git:ro" -v "$T/gitfile:/app/.git:ro" \
  "$IMG" sh -c 'grep MemAvailable /proc/meminfo > /out/run.log; python -B tools/research/mainstream_research.py "$@" >> /out/run.log 2>&1; echo $? > /out/exit.code' _ "$@"
