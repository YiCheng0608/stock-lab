#!/usr/bin/env bash
# #865 AC-2: trade_research 探索段 R1,R2，只跑一次。
set -eu
export MSYS_NO_PATHCONV=1
O=C:/Users/YiCheng/t865/explore
GIT_RO=(-v "C:/Users/YiCheng/Desktop/taiwan-stock-research/.git:/repo.git:ro" -v "C:/Users/YiCheng/t865/gitfile:/app/.git:ro")
R=(--network none --memory 4g --memory-swap 4g -v stock-lab-research:/research -v "$O":/out "${GIT_RO[@]}")
RERUN=(--oom-score-adj 1000)
docker run -d --name research-865-explore "${R[@]}" "${RERUN[@]}" t865-backend:6acdb631 \
  sh -c 'grep MemAvailable /proc/meminfo > /out/run.log; python -B tools/research/trade_research.py --db /research/stock.db --segment exploration --hypotheses R1,R2 --out /out/exploration >> /out/run.log 2>&1; echo exit=$? >> /out/run.log'
