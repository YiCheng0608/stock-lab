from __future__ import annotations

import argparse
import json
from datetime import date

from .pipeline import run_daily


def main() -> None:
    parser = argparse.ArgumentParser(description="台股研究每日 worker")
    parser.add_argument("--date", dest="run_date", help="YYYY-MM-DD；未指定使用最近工作日")
    parser.add_argument("--months-back", type=int, choices=range(4), default=0)
    args = parser.parse_args()
    result = run_daily(
        date.fromisoformat(args.run_date) if args.run_date else None,
        months_back=args.months_back,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
