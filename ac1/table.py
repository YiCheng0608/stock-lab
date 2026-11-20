import json
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))


def pct(n, m):
    return "—" if not m else f"{100 * n / m:.2f}%"


print(f"讀入 {d['read'][0]}～{d['read'][1]}；第一個訊號日 {d['first_signal_day']}")
print()
print("| 年 | 交易所 | 交易日 | 有融資名單的日 | 母體檔日 | 有籌碼列 | 外資缺 | 投信缺 | 自營缺 | 三者皆有 | 融資餘額缺 | 融資餘額＝0 | 當日無名單 | 在名單內 |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
rows = sorted(d["by_year"].items(), key=lambda kv: (kv[0].split(":")[0], kv[0].split(":")[1] != "TWSE"))
for key, s in rows:
    year, ex = key.split(":")
    m = s.get("member_days", 0)
    print(
        f"| {year} | {ex} | {d['sessions'].get(year, 0)} | {d['list_sessions'].get(f'{ex}:{year}', 0)} | {m:,} | "
        f"{pct(s.get('chip_row', 0), m)} | {pct(s.get('foreign_buy_null', 0), m)} | {pct(s.get('trust_buy_null', 0), m)} | "
        f"{pct(s.get('dealer_buy_null', 0), m)} | {pct(s.get('institutional_all3', 0), m)} | {pct(s.get('margin_balance_null', 0), m)} | "
        f"{pct(s.get('margin_balance_zero', 0), m)} | {pct(s.get('no_list_day', 0), m)} | {pct(s.get('in_list', 0), m)} |"
    )
print()
print("訊號期（第一個訊號日～2019-12-31）合計：")
print()
print("| 交易所 | 母體檔日 | 三者皆有 | 融資餘額缺 | 融資餘額＝0 | 當日無名單 | 在名單內 |")
print("|---|---|---|---|---|---|---|")
for ex, s in sorted(d["signal_period"].items(), key=lambda kv: kv[0] != "TWSE"):
    m = s["member_days"]
    print(
        f"| {ex} | {m:,} | {pct(s.get('institutional_all3', 0), m)} | {pct(s.get('margin_balance_null', 0), m)} | "
        f"{pct(s.get('margin_balance_zero', 0), m)} | {pct(s.get('no_list_day', 0), m)} | {pct(s.get('in_list', 0), m)} |"
    )
