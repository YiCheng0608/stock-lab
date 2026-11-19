from __future__ import annotations

import json
import sys

from .pipeline import evaluate


if __name__ == "__main__":
    # Same as `python -m worker.cli evaluate [--force]` (#841).
    force = "--force" in sys.argv[1:]
    print(json.dumps(evaluate(force=force), ensure_ascii=False, indent=2))
