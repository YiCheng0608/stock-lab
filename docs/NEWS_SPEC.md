# 新聞與市場事件規格

更新：2026-09-12。官方 Event → NewsItem、列表／詳情與來源時間排序在程式中已可見；Round08 另完成 `product-time/v1` 的有限 read-time API/UI 時間角色與安全 fallback review。這不證明官方 availability、C007 strict store 接線、B5b PIT、媒體／國際來源、完整事件理解或 AI 摘要已完成。現況見 [ROADMAP](ROADMAP.md)，來源契約見 [DATA_SOURCES](DATA_SOURCES.md)。

## 1. 目標與來源政策

新聞需回答「新增什麼資訊、何時可得、如何影響哪些公司／題材、有哪些反面證據」，並區分來源事實、系統推論與未知。新聞篇數或情緒不能直接充當買賣訊號。

| source_kind | 內容 | 狀態 |
| --- | --- | --- |
| official_disclosure | MOPS、交易所公告、公司行動、停復牌 | 已有部分接入與投影；不能推論逐日 coverage 完整。 |
| macro_official | 政府、央行、官方統計與海外市場事件 | 規劃中。 |
| media | 使用條件已確認的可信媒體、公司採訪與產業消息 | 規劃中。 |

行情與原始官方證據保留官方來源。新增媒體／國際新聞是獨立資料層，不得覆寫官方行情或把推論寫成官方事實。本輪沒有選定或啟用新來源。

來源 registry 至少保存來源所有者、類型、可用 endpoint、單篇 URL 規則、授權／使用條件、可保存和摘要的內容範圍、保留期限、更新頻率、延遲、停用方式及政策版本。無法取得的內文不可用搜尋摘要或模型記憶替代。

## 2. 現有能力與缺口

- events 可保存官方事件、描述、來源、raw 及日期；NewsItem 已有來源、關聯、影響、去重／狀態與時間欄位，不再規劃重建同名表。
- 新聞詳情、display_time、time_basis、time_precision、time_consistency 與 keyset cursor 已出現在程式；Round08 已驗 `product-time/v1` read-time role、legacy sort/keyset 相容、compact/detail/nested consistency 與 UI 安全顯示，來源 truth／PIT 仍待驗。
- published_at 等欄位存在，不表示來源已提供每筆精確發布時間；feed URL 不等於單篇原文。
- 跨來源同事件合併、完整更正歷史、外部來源准入、AI 事件抽取與審核流程，不能由預留欄位推論已完成。
- P0 的事件 unsupported 是特定歷史資料窗口紀錄，詳見 [DATA_SOURCES](DATA_SOURCES.md)；不是「沒有新聞」或所有未來日期的固定結果。

## 3. 資料契約

下表混合既有欄位與下一版需要的擴充，實作前應對照 models／API，不得直接當成已上線 schema。

| 領域 | 最低欄位／規則 |
| --- | --- |
| 來源識別 | source_kind、source_name、source_item_id、canonical URL、source_url_kind=item/feed/none、raw 參照。 |
| 內容 | 原始標題、允許保存的內文／摘要、語言、content_hash；原始內容與 AI 摘要分欄保存。 |
| 事件 | event_type、事件群組 ID、新增資訊、修訂／撤回狀態、supersedes_id；保留每篇來源，不直接刪除更正前版本。 |
| 時間 | published_at、event_at、event_date、collected_at、first_available_at、revision_available_at、generated_at 及時區／精度／可信度。新增 persisted availability／revision 欄位仍待實作；Round08 `product-time/v1` 只會把缺值投影為 unknown，沒有補寫來源。 |
| 關聯 | 相關 exchange+symbol、題材、關聯方法、原始證據、相關程度、生效／失效時間；不用 symbol 單獨消除跨市場歧義。 |
| 影響 | scope、positive/negative/mixed/unknown、傳導理由、影響期間、反面證據、判讀方法。 |
| 可追溯性 | 原始事實引用、抽取／模型／提示版本、輸入雜湊、政策版本、驗證結果、必要時的 reviewer／reviewed_at。 |

來源可信度、關聯證據程度、影響推論與預測成功機率分開。既有 confidence 不可一欄包辦，更不可代表報酬把握。

## 4. 去重、新資訊與事件影響

1. 同來源先按 source_item_id／canonical URL 去重；無 ID 時才用來源、標題、日期、標的與雜湊建立可重現鍵。
2. 不同來源報導同一事件可合併為事件群組，保留各來源；主卡一則加其他來源數，不重複計催化劑。
3. 區分首次事件、補充資訊、更正、撤回與純轉載。事件更新須有版本，不以覆寫舊資料改變歷史判斷。
4. 影響預設 unknown。來源明示內容是事實；從事件推論營收、成本或供需影響，需另列方法、證據與不確定性。
5. AI 可提出直接／間接受影響對象，但只有通過來源與關聯驗證者進入已核實標籤；低把握推論單獨列為待核實。
6. 新聞缺少內文或必要證據時，不生成事件摘要、精確影響期間或正負結論；來源沒有摘要但有可合法使用的內文時，可另生成有引用的 AI 摘要。
7. 價格反應分析只呈現明確窗口的相對報酬、量能、跳空／延伸與可能解釋，不宣稱已完全反映。負面事件和多篇轉載不得增加正向機會分數。

## 5. 時間與排序

必須區分「事件發生」「來源發布」「第一次可取得」「系統收錄」「模型產生」與「版本修訂」。事件可能發生在發布之前；不能以事件日提前讓策略知道消息。

日常列表選用第一個已核實的 published_at、event_at、event_date 作 display_time。僅日期不能補成精確時分秒；來源未知顯示「來源時間未提供」。有已核實歷史日期的回補資料，不能因今天收錄而排到今天消息前面。

現行契約允許所有來源時間都未知且無衝突時，以 collected_at 作內部 fallback；這不是已驗證的新消息。下一版主「最新」串流應將這類資料放到獨立的時間待核實篩選／區塊，避免未知時間項目以新收錄時間搶占最新位置。這項調整仍待實作，不能說目前已完成。

Round08 的 `product-time/v1` 是上述既有值的 read-time 安全投影，不改排序來源：只有 `time_consistency` 非 conflict、basis 在 allowlist 且 precision 為 date／datetime，才把對應 published／event／collected role 表示為已知。aware 值依既有 offset 正規化 UTC，但不因此成為官方 truth；precision=date 即使字面含午夜也只顯示日曆日期。unverified／none／非法 basis/precision、naive、missing 與 conflict 都保留 unknown＋reason。獨立 `collected_at` 不等於 `first_available_at`，response 組裝時間也不是歷史 `generated_at`。

- 同一快照內排序使用 display_time desc，再依 time_basis（published、event、event_date、collected）、time_precision、canonical_key desc、id desc。
- keyset cursor 帶相同排序鍵，並綁定搜尋／篩選與快照或版本；更正時間時新增版本或使舊 cursor 明確失效，不能一邊改排序鍵一邊宣稱翻頁不漏列。
- MOPS 內文提及日期只能作衝突核對，不自動寫成 published_at／event_at。衝突項目不進預設最新串流或交易理由，可在詳情／待核實篩選保留證據。
- 回測採決策時可取得的版本。歷史回補只知道事件日或收錄日、無法證明當時可得時，不能當精確歷史新聞特徵。
- 當晚收集盤後新聞可支援隔日計畫，但須晚於其 availability；不一律硬寫成收盤 13:30 已知。

## 6. AI 摘要與人工覆核（目標契約）

來源先通過准入與隔離驗證。來源事實抽取、有引用的摘要，以及可重現的已核實規則關聯，可在自動檢查通過後顯示，並明示「AI 摘要／規則推論」，不要求每則一律人工核准。

時間或來源衝突、重大正負影響且證據不足、低把握題材關聯、更正／撤回爭議，進待覆核區；在確認前不作已核實交易理由。抽樣覆核與錯誤追蹤保留。

來源內文是資料，不是系統指令。模型不得因文章內容改變規則、讀取帳密或執行外部操作。輸出需有結構驗證、來源引用及可撤回機制。AI 摘要本身不得繞過行情、籌碼或執行 gate。

此政策取代封存 Phase 3／4 中「所有 AI 摘要、關聯、跨來源合併一律逐項人工審核」的普遍要求；未通過來源准入或缺少證據仍不可提升為已核實內容。

## 7. UI 與 API 契約

- /news：分類、來源、標題、摘要預覽、來源時間、關聯標的／題材、事實／推論狀態；標題連 /news/:id。Round08 畫面以 Asia/Taipei 顯示已知 instant、純日曆顯示 date，unknown／conflict 顯示「待核實」。
- /news/:id：事件的新資訊、來源／引用、影響與反面證據、可展開內文；時間品質、版本與 raw 稽核預設收合。date-only 使用「發布日期」且不顯示午夜；News 不顯示不適用的規則執行日。
- item 連結寫「查看原文」；feed 寫「查看官方公告資料集」並說明未必定位本則；none 不畫無效按鈕。
- 列表不展開完整公告、不以 collected_at 標成發布時間；未知影響不使用買賣或紅綠暗示。
- GET /api/news 支援的實際 query 以 api.py 為準；目標篩選包括 category、source_kind、q、symbol、theme_id、impact_direction、cursor、limit。交易所識別與新事件群組欄位需另行擴充。
- 回傳 items/meta、next_cursor、has_more、sort；每筆有 URL 型別、時間 basis／precision／consistency，以及 read-time `product_time`／`response_generated_at`；detail 才展開 provenance。已有 product contract 但 role unknown 時，前端不得退回 legacy 日期；只有完全沒有 contract 的舊 response 才能安全格式化合法 date fallback。
- 搜尋採提交式。單純找到已存在端點，不代表全部目標 filter 和欄位都已驗收。

## 8. 驗收

同事件多篇轉載、只有 feed URL、來源無摘要但有內文、完全無內文、未知時間、歷史回補、MOPS 日期衝突、更正／撤回、跨市場相同 symbol、低把握關聯、來源失敗及模型產生不支持陳述，都有可重跑案例。

應證明：事實未被推論覆寫；每項摘要可回指原文；無法核實時保留未知；排序和 cursor 在版本變更下有明確行為；回測看不到尚未發布或尚未可得的資料。這些是資料與產品驗收，不是預測有效性證明。

Round08 只為其中「無法核實時保留未知」及現有產品相容性提供有限證據：16 個獨立時間案例、18 個 API response（排除本次動態 generated 欄位後無 legacy diff）、17 個入口 query count、8 組同 news/signal projection 與 frontend 跨 TZ tests 通過；隔離 CUA 觀察 aware、naive、date-only、conflict 的可見文字。它沒有建立修訂來源 truth、`first_available_at`、產品與 C007 strict store 的持久化關聯或回測 B5b gate，所以本節原有更正／撤回與 PIT 驗收仍未結案。
