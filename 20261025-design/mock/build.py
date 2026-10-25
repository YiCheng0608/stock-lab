"""#277 wireframe: static HTML built from 10/22 read-only-copy data (mock_data.json)."""
import json, sys, html
from pathlib import Path
d = json.load(open(sys.argv[1], encoding="utf-8")); out = Path(sys.argv[2])
E = html.escape
def px(v): return "" if v is None else f"{v:,.2f}"
def pct(v): return "" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v)*100:.2f}%"
def tone(v): return "tone-flat" if not v else ("tone-up" if v > 0 else "tone-down")
MK = {"TWSE": "上市", "TPEx": "上櫃"}
SL = {"breakout_v1": "突破條件", "pullback_v1": "回踩條件"}
def grp(g): return "無所屬產業或題材" if not g else f"{E(g[0].replace('Industry · ', ''))}（{'產業' if 'industry' in (g[1] or '') else '題材'}，第 {g[2]} 名）"
def levels(r):
    l = r["levels"]
    entry = f"{px(l['pullback_low'])}～{px(l['pullback_high'])}" if r["strategy"] == "pullback_v1" else px(l["breakout_price"])
    tg = px(l["target_1"]) + (f"／{px(l['target_2'])}" if l.get("target_2") else "")
    return entry, px(l["invalid_price"]), tg
SHORT = {"price": "價格", "volume": "量能", "zone": "支撐區", "trend": "趨勢", "group": "族群", "inst": "法人", "margin": "融資"}
def unmet_text(r):
    parts = []
    for u in r["unmet"]:
        if u == "price": parts.append(f"收盤站上前 20 日高點（還差 {abs(r['gap'])*100:.1f}%）")
        elif u == "zone": parts.append(f"收盤回到 MA20 支撐區（{'高於上緣' if r['gap'] > 0 else '低於下緣'} {abs(r['gap'])*100:.1f}%）")
        elif u == "volume": parts.append(f"量能 {'≥ 1.2 倍' if r['strategy']=='breakout_v1' else '0.6～1.2 倍'}（今日 {r['vr']:.2f} 倍）")
        else: parts.append(SHORT[u])
    return parts
def met_text(r):
    allc = ["price", "volume", "group", "inst", "margin"] if r["strategy"] == "breakout_v1" else ["trend", "zone", "volume", "group", "inst", "margin"]
    met = [SHORT[c] for c in allc if c not in r["unmet"] and c not in ("price", "zone", "volume")]
    return "、".join(met) + "已達成"
cands = d["candidates"]; other = [r for r in d["other_conditional"] if r["type"] != "etf"]; near = [r for r in d["near"] if r["type"] != "etf"]
obs = [r for r in d["observe_sample"] if r["type"] != "etf"]
def sym(r): return f"<a class='sym'>{E(r['symbol'])} {E(r['name'])}</a><div class='sub'>{MK.get(r['exchange'], '')} · {grp(r['group'])}</div>"
def close_cell(r): return f"<td class='num'>{px(r['close'])}<div class='{tone(r['chg'])} small'>{pct(r['chg'])}</div></td>"
cand_rows = "".join(f"<tr><td class='rank'>#{r['rank']}</td><td>{sym(r)}</td><td>{SL[r['strategy']]}<div class='sub'>全部條件成立 · 最早 T+1</div></td>{close_cell(r)}" + "".join(f"<td class='num {c}'>{v}</td>" for v, c in zip(levels(r), ('', 'stop', 'target'))) + f"<td class='num'>{round(r['score']*100)}</td><td><a class='lnk'>策略總表 →</a></td></tr>" for r in cands[:8])
other_rows = "".join(f"<tr><td>{sym(r)}</td><td>{SL[r['strategy']]}<div class='sub'>條件成立，未進今日候選前 20</div></td>{close_cell(r)}" + "".join(f"<td class='num {c}'>{v}</td>" for v, c in zip(levels(r), ('', 'stop', 'target'))) + "<td><a class='lnk'>策略總表 →</a></td></tr>" for r in other[:5])
near_rows = "".join(f"<tr><td>{sym(r)}</td><td><span class='badge primary'>接近{SL[r['strategy']]}</span></td><td>{'<br>'.join('差：' + E(t) for t in unmet_text(r))}<div class='sub'>{met_text(r)}</div></td>{close_cell(r)}<td class='num'>{'已達成' if not r['gap'] else f"{abs(r['gap'])*100:.1f}%"}</td><td><a class='lnk'>策略總表 →</a></td></tr>" for r in near[:8])
obs_rows = "".join(f"<li><b>{E(r['symbol'])} {E(r['name'])}</b> <span class='sub'>{SL[r['strategy']]}差 {r['n']} 項：{'、'.join(SHORT[u] for u in r['unmet'])}</span></li>" for r in obs[:4])
def card(r, kind):
    head = f"<div class='crow'><b>{E(r['symbol'])} {E(r['name'])}</b><span class='cclose'>{px(r['close'])} <em class='{tone(r['chg'])}'>{pct(r['chg'])}</em></span></div><div class='sub'>{MK.get(r['exchange'],'')} · {grp(r['group'])}</div>"
    if kind == "cand":
        e, s, t = levels(r)
        return f"<div class='ccard'><div class='crow'><span class='rk'>#{r['rank']}</span><b>{E(r['symbol'])} {E(r['name'])}</b><span class='cclose'>{px(r['close'])} <em class='{tone(r['chg'])}'>{pct(r['chg'])}</em></span></div><div class='sub'>{MK.get(r['exchange'],'')} · {grp(r['group'])}</div><div class='sub'>{SL[r['strategy']]} · 全部條件成立 · 最早 T+1</div><div class='lv'><div><small>進場</small><b>{e}</b></div><div><small>停損</small><b class='stop'>{s}</b></div><div class='full'><small>目標</small><b class='target'>{t}</b></div></div><a class='lnk'>策略總表 →</a></div>"
    return f"<div class='ccard'>{head}<span class='badge primary'>接近{SL[r['strategy']]}</span><ul class='ul'>{''.join('<li>差：' + E(x) + '</li>' for x in unmet_text(r))}</ul><div class='sub'>{met_text(r)}</div><a class='lnk'>策略總表 →</a></div>"
cand_cards = "".join(card(r, "cand") for r in cands[:3]); near_cards = "".join(card(r, "near") for r in near[:3])
# Tier counts over the 1,867 action-center rows (tiers.py on actions_1022.json); the row
# lists above come from signals, so a few borderline rows differ (e.g. 180 vs 172 near).
n_c, n_o, n_n, n_watch_hidden, n_obs = 20, 50, 172, 2, 1308
tpl = Path(sys.argv[3]).read_text(encoding="utf-8")
page = (tpl.replace("{{CAND_ROWS}}", cand_rows).replace("{{OTHER_ROWS}}", other_rows).replace("{{NEAR_ROWS}}", near_rows).replace("{{OBS}}", obs_rows)
        .replace("{{CAND_CARDS}}", cand_cards).replace("{{NEAR_CARDS}}", near_cards)
        .replace("{{N_C}}", str(n_c)).replace("{{N_O_REST}}", str(n_o - 5)).replace("{{N_O}}", str(n_o)).replace("{{N_N}}", str(n_n))
        .replace("{{N_DEFAULT}}", f"{n_c+n_o+n_n+n_watch_hidden:,}").replace("{{N_WITH_OBS}}", f"{n_c+n_o+n_n+n_watch_hidden+n_obs:,}"))
(out / "actions.html").write_text(page, encoding="utf-8")
# theme members
t = d["theme"]; ms = t["members"]
def badge(s): return "" if not s else f"<span class='badge success'>{E(s)}</span>"
mrows = "".join(f"<tr><td><a class='sym'>{E(m['symbol'])}</a></td><td><a class='sym'>{E(m['name'])}</a> {badge(m['status'])}</td><td>{MK.get(m['exchange'],'')}</td><td class='num'>{px(m['close'])}</td><td class='num {tone(m['chg'])}'>{pct(m['chg'])}</td><td class='num'>{'' if m['turnover'] is None else f'{m['turnover']/1e8:,.2f}'}</td><td class='num {tone(m['x5'])}'>{pct(m['x5'])}</td><td class='num {tone(m['x20'])}'>{pct(m['x20'])}</td></tr>" for m in ms[:12])
mcards = "".join(f"<div class='ccard'><div class='crow'><b>{E(m['symbol'])} {E(m['name'])}</b> {badge(m['status'])}<span class='cclose'>{px(m['close'])} <em class='{tone(m['chg'])}'>{pct(m['chg'])}</em></span></div><div class='mgrid'><div><small>成交值 億元</small><b>{'' if m['turnover'] is None else f'{m['turnover']/1e8:,.2f}'}</b></div><div><small>5 日相對</small><b class='{tone(m['x5'])}'>{pct(m['x5'])}</b></div><div><small>20 日相對</small><b class='{tone(m['x20'])}'>{pct(m['x20'])}</b></div></div></div>" for m in ms[:6])
tp = Path(sys.argv[4]).read_text(encoding="utf-8").replace("{{MROWS}}", mrows).replace("{{MCARDS}}", mcards).replace("{{NM}}", str(len(ms)))
(out / "theme.html").write_text(tp, encoding="utf-8")
print("ok", n_c, n_o, n_n)
