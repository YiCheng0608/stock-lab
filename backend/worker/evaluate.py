from __future__ import annotations

import json

from .pipeline import evaluate


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
