import json
from pathlib import Path

b = json.loads(Path("/out/bias.json").read_text(encoding="utf-8"))
lines = []
P = lines.append


def g(d, k):
    return d.get(k, 0)


for name in ("X3", "X4", "X7", "S"):
    for seg, body in b["hypotheses"][name].items():
        P(f"## {name} {seg} {body['window'][0]}..{body['window'][1]}")
        P("year days | md act/del/tr | miss_any act/del/tr | del miss% | del inst / all-days-missing | del_reason | del known pass/known | act pass/known | picks del+tr | would_rank del+tr")
        tot = {"md_d": 0, "miss_d": 0, "md": 0, "picks": 0, "picks_dt": 0, "would": 0, "pass_d": 0, "known_d": 0, "pass_a": 0, "known_a": 0, "md_t": 0, "miss_t": 0}
        for y, r in body["years"].items():
            md = r["member_days"]
            ma = r["missing"].get("any", {})
            reason = r["yoy_reason"].get("delisted", {})
            kn, ps = r["known_all_filters"], r["passed_all_filters"]
            picks = r["picks_by_status"]
            would = r["missing_would_rank_in_top"]
            inst = r["instruments"]
            allm = r["instruments_missing_every_day"]
            dpct = 100 * g(ma, "delisted") / g(md, "delisted") if g(md, "delisted") else 0
            P(
                f"{y} {r['days']} | {g(md,'active')}/{g(md,'delisted')}/{g(md,'transferred')} | "
                f"{g(ma,'active')}/{g(ma,'delisted')}/{g(ma,'transferred')} | {dpct:.0f}% | "
                f"{g(inst,'delisted')}/{g(allm,'delisted')} | {reason} | "
                f"{g(ps,'delisted')}/{g(kn,'delisted')} | {g(ps,'active')}/{g(kn,'active')} | "
                f"{g(picks,'delisted')+g(picks,'transferred')}/{sum(picks.values())} | "
                f"{g(would,'delisted')+g(would,'transferred')}"
            )
            tot["md_d"] += g(md, "delisted"); tot["miss_d"] += g(ma, "delisted")
            tot["md_t"] += g(md, "transferred"); tot["miss_t"] += g(ma, "transferred")
            tot["md"] += sum(md.values())
            tot["picks"] += sum(picks.values()); tot["picks_dt"] += g(picks, "delisted") + g(picks, "transferred")
            tot["would"] += g(would, "delisted") + g(would, "transferred")
            tot["pass_d"] += g(ps, "delisted"); tot["known_d"] += g(kn, "delisted")
            tot["pass_a"] += g(ps, "active"); tot["known_a"] += g(kn, "active")
        P(f"TOTAL {tot}")
        P("")

h = b["hypotheses"]["H1"]
P(f"## H1 historical {h['historical_start']}..{h['until']}")
P("year days | md act/del/tr | miss_high12 act/del/tr | days cut tie decided by high12 | days with nonactive missing in cut tie | tied missing act/del/tr")
for y, r in h["years"].items():
    md, mh, tm = r["member_days"], r["missing_high12"], r["tied_at_cut_missing_high12"]
    P(
        f"{y} {r['days']} | {g(md,'active')}/{g(md,'delisted')}/{g(md,'transferred')} | "
        f"{g(mh,'active')}/{g(mh,'delisted')}/{g(mh,'transferred')} | {r['days_high12_decides_cut']} | "
        f"{r['days_cut_tie_has_missing_nonactive']} | {g(tm,'active')}/{g(tm,'delisted')}/{g(tm,'transferred')}"
    )
Path("/out/summary.txt").write_text("\n".join(lines), encoding="utf-8")
