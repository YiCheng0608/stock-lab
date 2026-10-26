"""#260 AC-6: compare the exported baseline with the replayed copy, row by row.

usage: python compare.py <baseline.db> <replay stock.db> <out dir>
Writes <out>/compare.md (summary) and <out>/diffs.jsonl (every differing field).
"""

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATES = ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22")
# table -> (key columns, date column, ignored columns)
TABLES = {
    "signals": (("signal_key",), "signal_date", {"id", "created_at"}),
    "technical_features": (
        ("instrument_id", "trading_date"),
        "trading_date",
        {"id", "created_at"},
    ),
    "group_daily_scores": (("group_id", "trading_date"), "trading_date", {"id"}),
}
JSON_COLUMNS = {"rule_evidence_json", "features_json", "details_json"}

base_path, replay_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
base = sqlite3.connect(f"file:{base_path}?mode=ro", uri=True)
replay = sqlite3.connect(f"file:{replay_path}?mode=ro", uri=True)
for con in (base, replay):
    con.row_factory = sqlite3.Row
symbols = {
    row["id"]: f"{row['exchange']}:{row['symbol']}"
    for row in replay.execute("SELECT id, exchange, symbol FROM instruments")
}


def flatten(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from flatten(item, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        yield prefix, json.dumps(value, sort_keys=True, ensure_ascii=False)
    else:
        yield prefix, value


def fields(row, ignored):
    result = {}
    for key in row.keys():
        if key in ignored:
            continue
        value = row[key]
        if key in JSON_COLUMNS and value is not None:
            for sub, item in flatten(json.loads(value)):
                result[f"{key}.{sub}"] = item
        else:
            result[key] = value
    return result


def load(con, table, keys, column, ignored):
    marks = ",".join("?" * len(DATES))
    rows = con.execute(f"SELECT * FROM {table} WHERE {column} IN ({marks})", DATES)
    return {tuple(row[k] for k in keys): (row[column], fields(row, ignored)) for row in rows}


def numeric_gap(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b)
    return None


lines = ["# AC-6 比對結果", ""]
diff_file = (out / "diffs.jsonl").open("w", encoding="utf-8")
for table, (keys, column, ignored) in TABLES.items():
    left = load(base, table, keys, column, ignored)
    right = load(replay, table, keys, column, ignored)
    per_day = defaultdict(Counter)
    field_counts = defaultdict(Counter)  # date -> field -> rows
    field_gap = defaultdict(float)
    examples = {}
    for key in sorted(set(left) | set(right), key=str):
        day = (left.get(key) or right.get(key))[0]
        if key not in right:
            per_day[day]["only_baseline"] += 1
            diff_file.write(json.dumps({"table": table, "key": key, "kind": "only_baseline"}, ensure_ascii=False) + "\n")
            continue
        if key not in left:
            per_day[day]["only_replay"] += 1
            diff_file.write(json.dumps({"table": table, "key": key, "kind": "only_replay"}, ensure_ascii=False) + "\n")
            continue
        a, b = left[key][1], right[key][1]
        changed = {
            name: (a.get(name), b.get(name))
            for name in set(a) | set(b)
            if a.get(name) != b.get(name)
        }
        if not changed:
            per_day[day]["equal"] += 1
            continue
        per_day[day]["different"] += 1
        for name, (x, y) in changed.items():
            field_counts[day][name] += 1
            gap = numeric_gap(x, y)
            if gap is not None:
                field_gap[name] = max(field_gap[name], gap)
            examples.setdefault(name, (key, x, y))
        diff_file.write(
            json.dumps(
                {"table": table, "key": key, "kind": "different", "changed": changed},
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )
    lines += [f"## {table}", "", "| 日期 | 基準列數 | 重播列數 | 逐列相符 | 欄位不同 | 只在基準 | 只在重播 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for day in DATES:
        c = per_day[day]
        n_left = c["equal"] + c["different"] + c["only_baseline"]
        n_right = c["equal"] + c["different"] + c["only_replay"]
        lines.append(f"| {day} | {n_left} | {n_right} | {c['equal']} | {c['different']} | {c['only_baseline']} | {c['only_replay']} |")
    lines.append("")
    all_fields = Counter()
    for day in DATES:
        all_fields.update(field_counts[day])
    if all_fields:
        lines += ["| 不同的欄位 | 列數（四日合計） | 各日 | 最大數值差 | 例 |", "| --- | --- | --- | --- | --- |"]
        for name, count in all_fields.most_common(40):
            key, x, y = examples[name]
            label = key
            if table == "technical_features":
                label = (symbols.get(key[0], key[0]), key[1])
            daily = "/".join(str(field_counts[d][name]) for d in DATES)
            gap = f"{field_gap[name]:.3g}" if name in field_gap else ""
            lines.append(f"| `{name}` | {count} | {daily} | {gap} | {label}: `{x}` → `{y}` |")
        lines.append("")
diff_file.close()
(out / "compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
