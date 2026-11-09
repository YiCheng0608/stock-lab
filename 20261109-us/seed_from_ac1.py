"""#568 screenshot data: us-collect on an empty task database from the AC-1 answers.

No request is sent: the four FinMind answers saved in AC-1 (2026-11-09 07:57
Taipei, /ac1/<symbol>.json) are what ``fetch`` returns, filtered to the
requested window.  Taipei day 2026-11-09, so the request ends 2026-11-08.
"""

import json
import socket
import sys
from datetime import date
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, "/app/backend")


def no_network(*args, **kwargs):
    raise AssertionError("no network in the screenshot seed")


socket.socket.connect = no_network

from app.db import SessionLocal, init_db  # noqa: E402
from worker import us_index_bars as us  # noqa: E402

FILES = {"^GSPC": "GSPC", "^IXIC": "IXIC", "^DJI": "DJI", "^SOX": "SOX"}


def fetch(url):
    query = parse_qs(urlsplit(url).query)
    data_id = query["data_id"][0]
    start, end = query["start_date"][0], query["end_date"][0]
    with open(f"/ac1/{FILES[data_id]}.json", encoding="utf-8") as handle:
        answer = json.load(handle)
    answer["data"] = [row for row in answer["data"] if start <= row["date"] <= end]
    return answer


init_db()
with SessionLocal() as db:
    result = us.collect_us_indexes(
        db, session=date(2026, 11, 9), fetch=fetch, trigger="manual"
    )
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
