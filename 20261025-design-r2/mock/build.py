import json, sys, html
sp = sys.argv[1]
c = json.load(open(sp + '/mock/candidates.json', encoding='utf-8'))
closes = {r['symbol']: r for r in json.load(open(sp + '/mock/closes.json', encoding='utf-8'))}
board = json.load(open(sp + '/mock/today-board.json', encoding='utf-8'))
dash = json.load(open(sp + '/mock/dashboard.json', encoding='utf-8'))
E = html.escape
def f2(x): return f"{x:,.2f}"
def sgn(x, d=2): return ("+" if x > 0 else ("" if x == 0 else "−")) + f"{abs(x):,.{d}f}"
def tone(x): return "up" if x > 0 else ("down" if x < 0 else "flat")
STRAT = {'breakout_v1': '突破條件', 'pullback_v1': '回踩條件'}
MKT = {'TWSE': '上市', 'TPEx': '上櫃'}
BOARD = {'industry': '產業', 'theme': '題材'}
def group_text(it):
    if not it['groups']: return '無所屬產業或題材'
    g = it['groups'][0]
    r = f"第 {g['rank']} 名" if g['rank'] else '當日未排名'
    return f"{E(g['name'])}<span class='muted'>（{BOARD[g['board']]}，{r}）</span>"
def price(x): return f"{x:,.2f}"
def zone(L):
    z = L['entry_zone']
    return price(z['low']) if z['low'] == z['high'] else f"{price(z['low'])}～{price(z['high'])}"
def targets(L):
    return price(L['target_1']) + (f"／{price(L['target_2'])}" if L.get('target_2') else '')
rows = []
cards = []
for it in c['items']:
    L = it['levels']; s = it['instrument']['symbol']; cl = closes[s]
    reason = E(it['reasons'][0]['text'])
    note = it.get('llm_note') or {}
    ai = f"""<details class='ai-row'><summary>AI 說明</summary><div class='ai-block'><div class='ai-head'><b>AI 進出點說明</b><span class='badge accent'><i></i>AI 推論</span></div>
<div class='k'>為何入選</div><p>{E(note.get('selection',''))}</p><div class='k'>進場區、停損與目標</div><p>{E(note.get('levels',''))}</p><div class='k'>需留意的風險</div><p>{E(note.get('risks',''))}</p>
<p class='fine'>由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。</p></div></details>"""
    rows.append(f"""<tr><td class='rank'>#{it['rank']}</td><td><a class='sym'>{s} {E(it['instrument']['name'])}</a><div class='sub'>{MKT[it['instrument']['exchange']]} · {STRAT[it['strategy']]}</div></td>
<td class='grp'>{group_text(it)}</td><td class='num'>{price(cl['close'])}<div class='sub tone-{tone(cl['change'])}'>{sgn(cl['pct'])}%</div></td>
<td class='num'>{zone(L)}</td><td class='num stop'>{price(L['invalid_price'])}</td><td class='num target'>{targets(L)}</td><td class='num'><span class='badge primary'>{L['risk_reward']:.2f}</span></td>
<td class='num score'>{round(it['total_score']*100)}</td><td class='reason'>{reason}</td><td><span class='badge accent tog'><i></i>AI 推論 {'▾' if it['rank']==1 and len(sys.argv) < 3 else '▸'}</span></td></tr>""")
    if it['rank'] == 1 and len(sys.argv) < 3:
        comps = it['components']
        cs = ''.join(f"<div class='cp'><small>{comps[k]['label']}{'（推論）' if comps[k]['inference'] else ''}</small><b>{round(comps[k]['score']*100)}</b></div>" for k in ('technical','chips','group','news_sentiment'))
        rs = ''.join(f"<li>{E(r['text'])}{' <span class=badge>推論</span>' if r['inference'] else ''}</li>" for r in it['reasons'])
        rows.append(f"""<tr class='detail'><td></td><td colspan='10'><div class='dgrid'><div><div class='k'>理由（全部）</div><ul class='rl'>{rs}</ul><div class='k'>四分項（0–100）</div><div class='cps'>{cs}</div></div>
<div class='ai-block'><div class='ai-head'><b>AI 進出點說明</b><span class='badge accent'><i></i>AI 推論</span></div><div class='k'>為何入選</div><p>{E(note.get('selection',''))}</p><div class='k'>進場區、停損與目標</div><p>{E(note.get('levels',''))}</p><div class='k'>需留意的風險</div><p>{E(note.get('risks',''))}</p><p class='fine'>由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。<br>模型 {note.get('model')} · 提示版本 {note.get('prompt_version')}</p></div>
<div><div class='k'>資料日期與來源</div><p class='fine'>資料日期 2026/10/22 · 權重涵蓋 100%<br>來源：訊號 pullback_v1 · 行情 臺灣證券交易所 · 籌碼 臺灣證券交易所 · 族群 hot_group_v1 · 新聞方向 LLM 判讀 news_v1（推論）</p><a class='lnk'>評分細節與策略總表 → 個股頁</a></div></div></td></tr>""")
    cards.append(f"""<div class='ccard'><div class='crow'><span class='rk'>#{it['rank']}</span><a class='sym'>{s} {E(it['instrument']['name'])}</a><span class='cscore'><small>總分</small> {round(it['total_score']*100)}</span></div>
<div class='sub'>{MKT[it['instrument']['exchange']]} · {STRAT[it['strategy']]} · {group_text(it)}</div>
<div class='lv'><div><small>收盤</small><b>{price(cl['close'])}</b><em class='tone-{tone(cl['change'])}'>{sgn(cl['pct'])}%</em></div><div><small>進場區</small><b>{zone(L)}</b></div><div><small>停損</small><b class='stop'>{price(L['invalid_price'])}</b></div><div><small>目標</small><b class='target'>{targets(L)}</b></div></div>
<div class='creason'>{reason}</div>{ai}</div>""")
top_rows = ''.join(rows[:10]); more_rows = ''.join(rows[10:])
top_cards = ''.join(cards[:10]); more_cards = ''.join(cards[10:])
groups = ''
for g in board['items'][:5]:
    rr = g['relative_returns']; q = '熱門族群' if g['quality'] == 'complete' else '技術與籌碼觀察（事件資料待補）'
    groups += f"<li><span class='rk'>#{g['rank']}</span><span class='gname'>{E(g['display_name'])}<div class='sub'>{q}</div></span><span class='num'>{g['score']:.2f}</span>" + ''.join(f"<span class='num tone-{tone(rr[k])}'>{sgn(rr[k]*100)}%</span>" for k in ('1d','5d','20d')) + "</li>"
DIR = {'positive': ('可能正向', 'up'), 'negative': ('可能負向', 'down'), 'mixed': ('正負互見', 'flat')}
news = ''
for n in dash['news'][:3]:
    ai = n.get('ai') or {}
    d, t = DIR.get(ai.get('impact_direction'), ('影響尚未判定', None))
    dot = f"<i class='dot {t}'></i>" if t else ''
    news += f"<li><div class='sub'><span class='badge'>{E(n.get('source_name') or '')}</span> 國內 · 媒體報導 · 發布於 2026/10/25 {(int(n['published_at'][11:13])+8):02d}{n['published_at'][13:16]}</div><div class='ntitle'>{E(n['title'])}</div><div class='sub'>{dot}{d} <span class='badge accent'><i></i>AI 推論</span></div></li>"
tpl = open(sp + '/mock/template.html', encoding='utf-8').read()
out = tpl.replace('{{TOP_ROWS}}', top_rows).replace('{{MORE_ROWS}}', more_rows).replace('{{TOP_CARDS}}', top_cards).replace('{{MORE_CARDS}}', more_cards).replace('{{GROUPS}}', groups).replace('{{NEWS}}', news)
open(sp + '/mock/home.html', 'w', encoding='utf-8').write(out)
print('ok', len(out))
