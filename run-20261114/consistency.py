import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app/tools/research")
import portfolio_research as tool  # noqa: E402

line = tool.run_hypothesis(
    Path("/db/stock.db"),
    "H1",
    tool.FORWARD,
    Path("/db/out/consistency"),
    cutoff=date(2026, 11, 13),
    since=date(2024, 11, 1),
    command="consistency check: run_hypothesis(since=2024-11-01, cutoff=2026-11-13)",
    progress=lambda text: print(text, file=sys.stderr, flush=True),
)
print(json.dumps(line, ensure_ascii=False))
