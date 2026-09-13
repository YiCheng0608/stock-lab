from __future__ import annotations

import json

from .pipeline import analyze


if __name__ == "__main__":
    print(json.dumps(analyze(), ensure_ascii=False, indent=2))
