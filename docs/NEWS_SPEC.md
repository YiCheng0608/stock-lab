# 新聞與市場事件規格

更新：2026-09-16。本文定義新聞來源、事件、時間與呈現；實作狀態見 [ROADMAP](ROADMAP.md)，來源 coverage 見 [DATA_SOURCES](DATA_SOURCES.md)。未具名驗收的欄位與流程仍是目標契約。

## 1. 目標與來源政策

新聞需回答新增資訊、可得時間、受影響公司／題材、傳導理由與反面證據，並分開來源事實、系統推論與未知。新聞篇數或情緒不能直接作買賣訊號。

| `source_kind` | 內容 | 現況 |
| --- | --- | --- |
| `official_disclosure` | MOPS、交易所公告、公司行動、停復牌 | 部分接入；不代表逐日 coverage 完整。 |
| `macro_official` | 政府、央行、官方統計與海外市場事件 | 規劃中。 |
| `media` | 使用條件已確認的媒體、公司採訪與產業消息 | 規劃中。 |

新增來源不得覆寫官方行情或把推論寫成官方事實。來源 registry 至少保存所有者、類型、endpoint、單篇 URL 規則、授權／使用條件、可保存與摘要的內容、保留期限、頻率、延遲、停用方式及政策版本。無法取得的內文不可由搜尋摘要或模型記憶補寫。

## 2. 現有能力與缺口

- 現有官方 Event、NewsItem、列表／詳情、時間投影與 keyset cursor 只有有限能力；欄位存在或 legacy fallback 不證明來源時間、availability 或 PIT 正確。
- feed URL 不是單篇原文。跨來源合併、更正歷史、外部來源准入及 AI 抽取／審核仍待完成；特定歷史窗口 event unsupported 也不表示永遠沒有新聞。

## 3. 資料契約

下列是最低目標契約；部分欄位仍待實作，使用前須對照實際 models／API。

| 領域 | 欄位／規則 |
| --- | --- |
| 來源 | source_kind、source_name、source_item_id、canonical URL、source_url_kind=item/feed/none、raw 參照。 |
| 內容 | 原始標題、可保存的內文／摘要、語言、content_hash；原文與 AI 摘要分欄。 |
| 事件 | event_type、群組 ID、新增資訊、修訂／撤回狀態、supersedes_id；舊版本不可覆寫。 |
| 時間 | published_at、event_at、event_date、collected_at、first_available_at、revision_available_at、generated_at，以及時區、精度與可信度。 |
| 關聯 | exchange+symbol、題材、方法、原始證據、程度與生效／失效時間；不能只靠 symbol 消除跨市場歧義。 |
| 影響 | scope、positive/negative/mixed/unknown、傳導理由、期間、反證與方法。 |
| 稽核 | 事實引用、抽取／模型／提示版本、輸入雜湊、政策版本、驗證結果；必要時含 reviewer／reviewed_at。 |

來源可信度、關聯證據、影響推論與預測機率必須分欄；既有 confidence 不能一欄包辦或解讀為報酬把握。

## 4. 去重、新資訊與事件影響

1. 同來源先按 source_item_id／canonical URL 去重；缺 ID 時才以來源、標題、日期、標的與雜湊建立可重現鍵。
2. 不同來源的同一事件可合併成事件群組，但保留各來源；主卡只計一次催化劑並顯示其他來源數。
3. 首次事件、補充、更正、撤回與轉載分開，更新用版本或 supersedes 關係，不改寫歷史。
4. 影響預設 unknown。來源明示內容是事實；營收、成本、供需或價格影響是推論，需另列方法、證據與不確定性。
5. AI 可提出關聯候選；只有來源或規則已驗證者進入已核實標籤，低把握項留在待核實區。
6. 缺內文或必要證據時不生成摘要、精確期間或正負結論。有合法可用原文時，AI 摘要也必須獨立標示並附引用。
7. 價格反應只呈現具名窗口的相對報酬、量能、跳空／延伸與可能解釋，不宣稱已完全反映。負面事件或多篇轉載不得增加正向機會分數。

## 5. 時間與排序

事件發生、來源發布、第一次可取得、系統收錄、模型產生與版本修訂是不同時間。決策不得使用當時尚不可得的資料。

日常顯示依序選擇已核實的 `published_at`、`event_at`、`event_date`。純日期不得補時分秒；皆未知時顯示「來源時間未提供」。現行可在無衝突時以 `collected_at` 作內部排序 fallback，但不因此成為已驗證新消息；目標是將這類資料移到時間待核實區。

`product-time/v1` 只投影既有值：`time_consistency` 不為 conflict、basis 在 allowlist 且 precision 為 date／datetime 時，對應時間角色才可標為已知。aware datetime 依 offset 正規化 UTC；date-only 仍只顯示日期。unverified／none、非法 basis/precision、naive、missing 與 conflict 均保留 unknown＋reason。`collected_at` 不等於 `first_available_at`，response 組裝時間也不是歷史 `generated_at`。

- 同一快照依 `display_time desc`，再依 time_basis（published、event、event_date、collected）、time_precision、canonical_key desc、id desc 穩定排序。
- cursor 綁定相同排序鍵、搜尋／篩選及快照或版本；更正排序時間須建立版本或讓舊 cursor 明確失效。
- MOPS 內文日期只可作衝突核對，不自動寫入 published／event time。衝突項不進預設最新串流或交易理由。
- 回測只讀決策時可取得版本。無法證明歷史 availability 的回補資料不能作精確 PIT 新聞特徵。
- 盤後新聞可支援隔日計畫，但 decision time 必須晚於其 availability，不可一律寫成 T 日 13:30 已知。

## 6. AI 摘要與人工覆核（目標契約）

來源先通過准入與隔離驗證。來源事實抽取、有引用的摘要、可重現且已驗證的規則關聯，可在自動檢查通過後顯示並標示方法；不要求每則一律人工核准。

時間／來源衝突、重大影響但證據不足、低把握題材關聯、更正或撤回爭議進待覆核區，確認前不得作已核實交易理由。保留抽樣覆核、錯誤追蹤及撤回機制。來源內容只能當資料，不得改變規則、讀取帳密或觸發外部操作；AI 摘要不能繞過行情、籌碼或執行 gate。

## 7. UI 與 API 契約

- `/news` 顯示分類、來源、標題、摘要預覽、來源時間、已核實標的／題材及事實／推論狀態；unknown／conflict 顯示「待核實」。
- `/news/:id` 顯示新資訊、來源／引用、影響、反證及可展開內文；時間品質、版本與 raw 稽核預設收合。date-only 不顯示午夜。
- item 連結寫「查看原文」；feed 寫「查看官方公告資料集」並說明未必定位本則；none 不畫按鈕。
- 列表不展開全文、不把 collected_at 標成發布時間，unknown 影響不使用買賣或紅綠暗示。
- 實際 query 以 API 為準；目標篩選包含 category、source_kind、q、symbol、theme_id、impact_direction、cursor、limit。發現欄位存在不等於已驗收。
- items/meta 應明示 cursor、has_more 與 sort。已有 `product_time` 但角色 unknown 時，前端不得退回 legacy 日期；只有完全沒有 contract 的舊 response 才可安全格式化合法 date fallback。
- 搜尋採提交式。

## 8. 驗收

可重跑案例須涵蓋同事件轉載、三種 URL、來源有／無內文或摘要、未知時間、歷史回補、MOPS 日期衝突、更正／撤回、跨市場同 symbol、低把握關聯、來源失敗及模型不受支持陳述。

驗收須證明事實未被推論覆寫、摘要可回指原文、unknown 未被補值、排序／cursor 的版本行為明確，且回測看不到尚未可得的資料。現有有限 review 只支持 unknown 安全投影與產品相容；availability／revision truth、strict store 接線與 PIT gate 仍未完成。
