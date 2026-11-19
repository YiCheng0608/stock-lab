判讀 session：ebad51dc-a59c-4191-95d8-9dd6e9ee4d8c

（ID 取自本專案 transcript 目錄裡唯一的 `.jsonl` 檔名）

## T10 候選進出點說明（today.md）

| 樣本 | 結果 | 證據 |
| --- | --- | --- |
| （0 筆） | 無法判定 | `manual/T10.json` 的 `rule` 是「candidates.json 依名次前 3 檔」，`trading_date` 為 2026-11-19，`items` 是 `[]`。 |

**為何 0 筆：** `api/candidates.json` 的 `status` 是 `success`，`trading_date` 為 `2026-11-19`，`items` 是 `[]`。
- 數量：`evaluated_signals: 4666`，`pool_count: 0`，`candidate_count: 0`。
- 原因：`zero_reason: "all_excluded"`，`zero_reason_text` 為「成立的訊號都因 ETF、價位不合法、成交量低於門檻或評分資料不足被排除」。
- 排除明細：`exclusions` 列出 `instrument_type_excluded:etf: 1`、`low_volume: 9`。

當日名單是空的，沒有任何 `llm_note` 或 `levels` 可以比對。檔內沒有 `error`。

## N7 AI 摘要忠於原文（news.md）

樣本依 `manual/N7.json`（rule 是 domestic 新聞中台北發布日等於 2026-11-19、有 AI 判讀的前 5 則，API 順序），共 5 則。

| id | 結果 | 證據 |
| --- | --- | --- |
| 34597 | 通過 | 摘要寫的「3萬8歷史高檔」「第一波限空令後降至11月18日的1.25%」「整戶擔保維持率163.16%」都在 `summary`／`description` 原句裡。來源摘要停在「台股」，AI 摘要沒有替它補完。 |
| 34598 | 通過 | 摘要寫的「11月19日重挫1768點、收38426點跌破年線」「杜金龍看好W底第二隻腳成形」「逆勢加碼台積電」都和 `summary` 原句一致，沒有新增事實。 |
| 34599 | 通過 | 「Anthropic今掛牌上市」「超車SpaceX…史上最大IPO」「台積電ADR漲3.14%」出自 `title`，「美股四大指數全數上漲」出自 `summary`（「今（19）日全數上漲」）。來源摘要以「...」截斷，AI 摘要沒有補出原文沒有的內容。 |
| 34590 | 通過 | 摘要寫的「發行價高過先前公布的目標區間」「加強市場對AI相關類股的信心」「美股主要指數開盤走揚」都和 `summary` 原句一致。 |
| 34600 | 通過 | 來源摘要停在「暫停向「部分中國客戶」」。AI 摘要補上的「出貨」「多手機品牌恐受波及」，以及「FT報導」的歸屬，都出自同一則 `title`「FT：台積電、三星暫停部分中國客戶出貨，多手機品牌恐受波及」。「繼輝達新團隊決定」對應 `description` 的「繼輝達新團隊做出新決定後」。 |

## N8 AI 方向與關聯有原文依據（news.md）

樣本同 N7（`manual/N8.json`，5 則，內容與 N7 相同）。這 5 則的 `ai.unsupported` 都是 false，`hidden_symbol_candidates` 都是 `[]`。

| id | 結果 | 證據 |
| --- | --- | --- |
| 34597 | 通過 | 方向是 `unknown`，理由是「原文為市場數據與金管會措施描述，未明示對後市的方向」。原文確實只有數據與措施描述，沒有明示多空，所以未判定有依據。沒有個股候選。 |
| 34598 | 通過 | 方向是 `mixed`，理由「大盤重挫跌破年線，但杜金龍看好W底並加碼台積電」對應原文的「重挫1768點、跌破年線」與「看好W底…逆勢加碼台積電」。候選 2330 台積電在原文有提及（「台積電（2330）」），交易所 TWSE 沒有不符。 |
| 34599 | 通過 | 方向是 `positive`，理由「美股四大指數開高且台積電ADR上漲」對應 `title` 的「美股四大指數全開高　台積電ADR漲3.14%」。候選 2330 台積電由 `title` 的「台積電ADR」提及。 |
| 34590 | 通過 | 方向是 `positive`，理由「IPO提振市場對AI相關類股信心，指數開盤走揚」與 `summary` 原句一致。沒有個股候選。 |
| 34600 | 通過 | 方向是 `negative`，理由「台積電暫停部分中國客戶出貨」出自 `title`。候選 2330 台積電在 `title` 與 `description` 都有提及。 |

## 彙總

| 檢查 | 結果 | 一句理由 |
| --- | --- | --- |
| T10 | 無法判定 | 樣本 0 筆：`candidates.json` 回 success，但 `candidate_count: 0`、`zero_reason: all_excluded`（4666 個訊號評估後全部被排除，`exclusions` 列 ETF 1、低量 9），沒有 `llm_note` 可判。 |
| N7 | 通過 | 5 則的 AI 摘要裡，主體、數字、時間與事件都能在同一則的 `title`／`summary`／`description` 找到；被截斷的來源摘要也只用同一則已有的內容補完。 |
| N8 | 通過 | 5 則的方向與理由都能由原文推得，其中 34597 原文未明示多空，判 `unknown` 合理；個股候選 2330 台積電在原文都有提及，交易所沒有不符。 |
