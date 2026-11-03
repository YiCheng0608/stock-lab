#!/usr/bin/env bash
# The LLM step and the watchdog with no tokens (#337 AC-4), run in the scheduler container by
# tools/compose/smoke.sh step 5 with no env file:
#
#   docker compose run --rm --no-deps scheduler bash /app/tools/compose/no_env_llm.sh
#
# On a throwaway database under /tmp (not the stock-data volume) with one news item, the real
# claude runs news-llm: the batch must end pending (not_logged_in) and news-llm exit 1, with no
# crash; then the watchdog must end 0 with gh refused (exit 4) and the llm_auth comment held
# back. Prints the evidence; exits 1 on the first mismatch.
set -uo pipefail

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

tokens="$(env | grep -cE '^(CLAUDE_CODE_OAUTH_TOKEN|GH_TOKEN|GITHUB_TOKEN|ANTHROPIC_[A-Z_]*)=')"
[ "$tokens" = 0 ] || fail "$tokens token variables in the container"
[ ! -e "$HOME/.claude/.credentials.json" ] || fail "a claude login is in the container"
echo "ok no token variable and no claude login in the container"

# Not the volume: compose fixes STOCK_* to /data, these override it for this script only.
export STOCK_DATA_DIR=/tmp/no-env STOCK_DB_PATH=/tmp/no-env/stock.db STOCK_RAW_DIR=/tmp/no-env/raw
cd /app/backend || fail "no /app/backend"
python -m worker.cli init-db > /tmp/init-db.out 2>&1 < /dev/null || fail "init-db: $(tail -n 3 /tmp/init-db.out)"
python - < /dev/null 2> /tmp/insert.err <<'PY' || fail "insert: $(tail -n 3 /tmp/insert.err)"
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import NewsItem

now = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
with SessionLocal() as db:
    db.add(
        NewsItem(
            canonical_key="news:compose-smoke:1",
            category="domestic",
            source_kind="media",
            source_name="compose smoke",
            source_url="https://news.example/1",
            source_url_kind="item",
            title="新聞標題",
            summary="來源摘要",
            published_at=now,
            display_time=now,
            time_basis="published",
            time_precision="datetime",
            time_consistency="verified",
            collected_at=now,
            symbols_json=[],
            theme_ids_json=[],
            impact_scope="unknown",
            impact_direction="unknown",
            impact_method="rule:exact-name-code/v1",
            status="active",
        )
    )
    db.commit()
PY

python -m worker.cli news-llm > /tmp/news-llm.json 2> /tmp/news-llm.err < /dev/null
code=$?
[ "$code" = 1 ] || fail "news-llm exit $code, want 1: $(tail -n 3 /tmp/news-llm.err)"
! grep -q Traceback /tmp/news-llm.err || fail "news-llm crashed: $(tail -n 5 /tmp/news-llm.err)"
python - < /dev/null <<'PY' || exit 1
import json
import sqlite3
import sys

result = json.load(open("/tmp/news-llm.json", encoding="utf-8"))
batch = result["batches"][0]
rows = sqlite3.connect("/tmp/no-env/stock.db").execute(
    "SELECT llm_status, count(*) FROM news_llm_results GROUP BY 1"
).fetchall()
print(f"ok news-llm exit 1: status={result['status']} batch {batch['status']} {batch['reason']}")
print(f"   error: {batch['error']}")
print(f"   news_llm_results: {rows}")
if (result["status"], batch["status"], batch["reason"]) != ("failed", "pending", "not_logged_in"):
    sys.exit("FAIL: news-llm did not leave the batch pending as not_logged_in")
if rows != [("pending", 1)]:
    sys.exit(f"FAIL: news_llm_results {rows}, want [('pending', 1)]")
PY

bash /app/tools/ops/watchdog.sh --data-dir /tmp/no-env --python "$(command -v python)" > /tmp/watchdog.out 2>&1 < /dev/null
code=$?
[ "$code" = 0 ] || fail "watchdog exit $code: $(tail -n 3 /tmp/watchdog.out)"
grep -q ' gh_auth_failed exit=4 ' /tmp/watchdog.out || fail "no gh_auth_failed exit=4: $(cat /tmp/watchdog.out)"
grep -q ' anomaly_not_commented key=llm_auth ' /tmp/watchdog.out || fail "llm_auth not held back: $(cat /tmp/watchdog.out)"
echo "ok watchdog exit 0:"
grep -E ' (gh_auth_failed|anomaly_not_commented) ' /tmp/watchdog.out | sed 's/^/   /'
