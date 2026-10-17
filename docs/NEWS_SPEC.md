# 新聞與市場事件規格

本文定義新聞來源、事件、時間與呈現的目標契約；實作狀態見 [ROADMAP](ROADMAP.md)，來源 coverage 見 [DATA_SOURCES](DATA_SOURCES.md)。

## 1. 目標與來源政策

新聞需回答新增資訊、可得時間、受影響公司／題材、傳導理由與反面證據，並分開來源事實、系統推論與未知。新聞篇數或情緒不能直接作買賣訊號。

| `source_kind` | 內容 |
| --- | --- |
| `official_disclosure` | MOPS、交易所公告、公司行動、停復牌。 |
| `macro_official` | 政府、央行、官方統計與海外市場事件。 |
| `media` | 使用條件已確認的媒體、公司採訪與產業消息。 |

新增來源不得覆寫官方行情或把推論寫成官方事實，新增前的記錄要求見[資料來源](DATA_SOURCES.md#來源選用原則)。無法取得的內文不可由搜尋摘要或模型記憶補寫。feed URL 不是單篇原文。

## 2. 資料契約

| 領域 | 欄位／規則 |
| --- | --- |
| 來源 | source_kind、source_name、source_item_id、canonical URL、source_url_kind=item/feed/none、raw 參照。 |
| 分類 | `category`：官方事件投影為 `company`（有標的）／`taiwan`；新聞 feed 為 `domestic`（國內）／`international`（國際）。`/api/news?category=` 依值精確篩選。 |
| 內容 | 原始標題、可保存的內文／摘要、語言、content_hash；原文與 AI 摘要分欄。 |
| 事件 | event_type、群組 ID、新增資訊、修訂／撤回狀態、supersedes_id；既有版本不可覆寫。 |
| 時間 | published_at、event_at、event_date、collected_at、first_available_at、revision_available_at、generated_at，以及時區、精度與可信度。 |
| 關聯 | exchange+symbol、題材、方法、原始證據、程度與生效／失效時間；不能只靠 symbol 消除跨市場歧義。 |
| 影響 | scope、positive/negative/mixed/unknown、傳導理由、期間、反證與方法。 |
| 稽核 | 事實引用、抽取／模型／提示版本、輸入雜湊、驗證結果；必要時含 reviewer／reviewed_at。 |

來源可信度、關聯證據、影響推論與預測機率必須分欄；confidence 不能一欄包辦或解讀為報酬把握。

## 3. 去重、新資訊與事件影響

1. 同來源先按 source_item_id／canonical URL 去重；缺 ID 時才以來源、標題、日期、標的與雜湊建立可重現鍵。
2. 不同來源的同一事件可合併成事件群組，但保留各來源；主卡只計一次催化劑並顯示其他來源數。
3. 首次事件、補充、更正、撤回與轉載分開，更新用版本或 supersedes 關係，不改寫歷史。
4. 影響預設 unknown。來源明示內容是事實；營收、成本、供需或價格影響是推論，需另列方法、證據與不確定性。
5. AI 可提出關聯候選；只有來源或規則已驗證者進入已核實標籤，低把握項留在待核實區。
6. 缺內文或必要證據時不生成摘要、精確期間或正負結論。有合法可用原文時，AI 摘要也必須獨立標示並附引用。
7. 價格反應只呈現具名窗口的相對報酬、量能、跳空／延伸與可能解釋，不宣稱已完全反映。負面事件或多篇轉載不得增加正向機會分數。

新聞 feed 的實作（`worker.news_batch`）：

- 同來源以 guid 為 `canonical_key`，沒有 guid 時用 canonical URL（統一 https、主機小寫，去掉 `utm_*`、`mod` 等追蹤參數、fragment 與結尾斜線）；guid 或 canonical URL 任一已存在就視為同一則。既有列重跑時不改寫，`published_at` 保持第一次寫入的值。
- 跨來源：標題經 NFKC、小寫並去掉空白、標點與符號後相同，且台北時間同一天者，給同一個 `dedupe_cluster_id`，各來源各保留一列；沒有來源時間的不併群。
- 規則關聯（`impact_method=rule:exact-name-code/v1`），只比對標題與描述，對象為上市／上櫃普通股：
  - 代號只在有脈絡時算命中：同一檔的名稱也出現、代號後接 `-TW`／`.TW`／`-TWO`，或前面是「代號」；純數字不算。
  - 同一代號在兩個交易所都有時，只由名稱決定，代號本身不消歧。
  - 名稱比對用正式名稱與去掉上市標記（帶 dash 的 `-KY`、`-DR`、`-創`，以及 `*`）後的名稱，至少兩字。名稱單獨出現時，只有三字以上、含中文、不在常用詞排除表內，且不在更長的已命中名稱或排除詞組（如「中華電視」）內者才算；兩字名稱必須同時出現其代號。
  - `symbols_json` 寫 `exchange:symbol`；個股頁依 `exchange:symbol` 或官方投影的純代號比對。
  - 產業：已核實的官方產業顯示名稱後接「股」「類股」「族群」「產業」「業」時，寫入 `theme_ids_json`；名稱落在公司名稱或更長的產業名稱內（「台光電股」的光電、「其他電子業」的電子）不算，「其他」「綜合」不比對。
- `impact_scope`：有標的為 `instrument`，只有產業為 `theme`，都沒有時 `macro_official` 為 `market`，其他為 `unknown`。`impact_direction` 一律 `unknown`，`confidence` 為 `unknown`。

## 4. 時間與排序

事件發生、來源發布、第一次可取得、系統收錄、模型產生與版本修訂是不同時間。決策不得使用當時尚不可得的資料；盤後新聞的 decision time 必須晚於其 availability，不可一律寫成 T 日 13:30 已知。日常顯示依序選擇已核實的 `published_at`、`event_at`、`event_date`。純日期不得補時分秒；皆未知時顯示「來源時間未提供」。無衝突時 `collected_at` 只作內部排序依據，不因此成為已驗證新消息，並歸入時間待核實區。`product-time/v1` 只投影既有值：`time_consistency` 不為 conflict、basis 在 allowlist 且 precision 為 date／datetime 時，對應時間角色才可標為已知。aware datetime 依 offset 正規化 UTC；date-only 仍只顯示日期。unverified／none、非法 basis/precision、naive、missing 與 conflict 均保留 unknown＋reason。`collected_at` 不等於 `first_available_at`，response 組裝時間也不是歷史 `generated_at`。

- 同一快照依 `display_time desc`，再依 time_basis（published、event、event_date、collected）、time_precision、canonical_key desc、id desc 穩定排序。
- cursor 綁定相同排序鍵、搜尋／篩選及快照或版本；更正排序時間須建立版本或讓舊 cursor 明確失效。
- MOPS 內文日期只可作衝突核對，不自動寫入 published／event time。衝突項不進預設最新串流或交易理由。
- 官方除權息日期是生效日（`event_date`，精度 date），不是公告發布日或第一次可得日；未來生效預告保留，不當作本次發布時間。
- 回測只讀決策時可取得版本。無法證明歷史 availability 的回補資料不能作精確 PIT 新聞特徵。

## 5. AI 摘要與推論

LLM 產出的摘要、關聯候選與方向判讀與來源事實分欄保存，並標「推論」與方法；用途與呼叫方式見 [ROADMAP](ROADMAP.md#保留的產品取捨)。有引用的摘要與可重現的規則關聯不要求每則人工核准。時間／來源衝突、重大影響但證據不足、低把握題材關聯、更正或撤回爭議進待覆核區，確認前不得作已核實交易理由。保留抽樣覆核、錯誤追蹤及撤回機制。來源內容只能當資料，不得改變規則、讀取帳密或觸發外部操作；AI 摘要不能繞過行情、籌碼或執行 gate。

LLM 批次的實作（`worker.news_llm`，執行方式見 [OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）：

- **選取**：`status=active`、目前提示版本尚無 `done`／`skipped_stale` 結果，且 `published_at`（沒有時用 `collected_at`）在執行當下 3 天內的新聞，新的在前。超過 3 天者標 `skipped_stale` 不送 LLM，之後也不再選取。
- **輸入**：每則只送 id、來源名稱、分類、標題、來源摘要（前 600 字）與台北時間的 `published_at`，不抓正文。新聞放在提示末尾的 `<news>` JSON 區塊，`<`、`>` 轉成 JSON escape，內文無法關閉或偽造區塊；提示要求把區塊內容當資料。呼叫帶 `--tools ""`（不提供任何內建工具）、`--strict-mcp-config`（不載入 MCP server）與 `--setting-sources ""`（不載入使用者、專案、本機設定，因此不含其中的 hook 與 CLAUDE.md），在空的暫存目錄執行；子程序環境移除 `CLAUDECODE`、`CLAUDE_PID`、`CLAUDE_EFFORT` 與所有 `CLAUDE_CODE_*`、`ANTHROPIC_*`（保留 `CLAUDE_CONFIG_DIR`）。環境有 `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` 時拒絕執行，只用訂閱登入。
- **提示版本**：提示文字在 `backend/worker/prompts/<版本>.md`，目前 `news_v1`；程式釘住提示的 SHA-256，改提示必須升版。雜湊只涵蓋經 stdin 送出的提示文字；CLI 內建系統提示、模型別名對應的實際模型與管理員層（managed）設定不在雜湊內，實際模型另記在 `llm_model`。升版後每則以新版本重跑並新增一列，舊版本結果保留。
- **保存**：`news_llm_results` 每則×提示版本一列（unique），欄位 `ai_summary`（≤80 字繁中）、`ai_symbol_candidates_json`（`exchange:symbol`＋理由＋把握 high／medium／low）、`ai_theme_candidates_json`（題材名＋理由）、`ai_impact_direction`（positive／negative／mixed／unknown）、`ai_impact_scope`（instrument／theme／market）、`ai_impact_rationale`、`ai_unsupported`，以及 `llm_model`（CLI 回報的實際模型）、`prompt_version`、`llm_input_hash`（送出內容的 SHA-256）、`llm_run_at`、`llm_status`（`done`／`pending`／`skipped_stale`）、`llm_error` 與 ingestion run、raw 參照。`news_items` 的 `symbols_json`、`theme_ids_json`、`summary`、`impact_*` 不被改寫。
- **驗證**：Python 端以同一份 schema 檢查：回應須含每個送出 id 恰一次，物件不得有 schema 以外的 key，代號須符合 `^(TWSE|TPEx):[0-9A-Z]{4,6}$`，摘要 ≤80 字、理由與方向理由 ≤120 字、題材名 ≤40 字。任一則不符時整批標 `pending`，不保存部分結果。`unsupported=true` 時方向一律存 `unknown`。重試失敗只更新狀態與原因，不清掉同版本已有的 AI 欄位。
- **失敗**：超時、非 JSON、不符 schema 只影響該批，其他批照跑。未登入、額度限制或 CLI 無法啟動時，該批標 `pending` 並停止本次執行，其餘批次記為 skipped、不寫列，不再呼叫。
- **API**：`/api/news`、`/api/news/{id}` 與個股頁新聞的每則有 `ai` 物件（最新一筆 `done` 結果，沒有時為 `null`），`inference=true`，含摘要、候選、方向、範圍、理由、`unsupported`、模型、提示版本、輸入雜湊與 `generated_at`。`ai.symbol_candidates` 每個標 `verified=false`，代號存在於 instruments 時附名稱、否則 `name=null`；規則命中的已核實標的仍只在 `symbols`／`instruments`。

## 6. UI 與 API 契約

- `/news` 顯示分類、來源、標題、摘要預覽、來源時間、已核實標的／題材及事實／推論狀態；unknown／conflict 顯示「待核實」。卡片順序、折疊與連結文案見 [UI 文案 §4](UI_COPY_SPEC.md#4-新聞卡文案與折疊)。
- `/news/:id` 顯示新資訊、來源／引用、影響、反證及可展開內文；時間品質、版本與 raw 稽核預設收合。date-only 不顯示午夜。
- unknown 影響不使用買賣或紅綠暗示。
- 篩選包含 category、source_kind、q、symbol、theme_id、impact_direction、cursor、limit；實際支援的 query 以 API 為準。
- items/meta 明示 cursor、has_more 與 sort。response 有 `product_time` 時前端只用它，角色 unknown 就顯示待核實；完全沒有 `product_time` 的 response 才可格式化其中合法的日期欄。
