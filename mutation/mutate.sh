#!/bin/sh
# Mutation checks of #855 on a copy of the worktree (the mount is read-only).
IC=backend/app/strategies/index_conditions.py
RP=tools/research/index_condition_report.py
T=tests/test_strategy_index_conditions.py
run() {
  name="$1"; file="$2"; expr="$3"
  rm -rf /tmp/w && cp -r /src /tmp/w && cd /tmp/w
  sed -i "$expr" "$file"
  if git -c safe.directory='*' diff --quiet 2>/dev/null && cmp -s "/src/$file" "$file"; then
    echo "== $name: sed changed nothing"; return
  fi
  echo "== $name ($file: $expr)"
  cd backend && python -m pytest -q -p no:cacheprovider --basetemp /tmp/pt "$T" 2>&1 \
    | grep -E '^FAILED|^[0-9]+ (passed|failed)' | sed 's/ - .*//' | head -8
  cd /
}
run "樣本日數門檻 5→3" $IC 's/^OVERNIGHT_MIN_REMOVED_DAYS = 5/OVERNIGHT_MIN_REMOVED_DAYS = 3/'
run "o5 門檻 −1%→−2%" $IC 's/("o5", "SPX", -0.01, True)/("o5", "SPX", -0.02, True)/'
run "o6 門檻 +1%→+0.5%" $IC 's/("o6", "SPX", 0.01, False)/("o6", "SPX", 0.005, False)/'
run "o2 門檻 −1%→−0.5%" $IC 's/("o2", "SOX", -0.01, True)/("o2", "SOX", -0.005, True)/'
run "讀到 E 當天的列（bisect_left→bisect_right）" $IC 's/bisect.bisect_left(dates, entry)/bisect.bisect_right(dates, entry)/'
run "母體不扣成本" $RP 's/ - ic.TRACKING_COST$//'
run "成交日拿 T 比" $RP 's/elif entry is not None and filled == entry:/elif filled == key[1]:/'
run "T+5 取代 T+20" $RP 's/\.get(20))$/.get(5))/'
