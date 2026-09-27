# R0–R3 執行清單

更新：2026-09-27。本文件管理工作 ID、狀態、依賴與完成條件；優先順序見 [ROADMAP](ROADMAP.md)，精確規格見各列連結。

## 1. 執行界線與狀態

僅免費公開資料與本地測試；來源不可合法、穩定、可重現取得時標受限，不以 fixture、欄位或模型介面冒充接入。帳戶、付費額度、正式 DB、排程與交易的操作授權依 [AGENTS](../AGENTS.md)。

| 狀態 | 意義 |
| --- | --- |
| 提案 | 有契約，尚無對應實作／資料證據。 |
| 進行中 | 正在執行，交付或 review 未完成。 |
| 暫停 | 依使用者指示停止；建立 task 或更新文件不代表恢復。 |
| 已實作 | 有變更與執行證據，尚待統籌 review。 |
| 已 review | 統籌已核對／重現具名驗收，只接受該有限範圍。 |
| 等待 | 依賴來源、樣本／時間累積或決策。 |
| 受限 | 免費來源或 PIT 證據不足，維持不可用／探索。 |

驗證與證據保存依 [AGENTS](../AGENTS.md#驗證資料與暫存)；mock 測試不證真實 coverage、策略有效性或前瞻結果。

## 2. 依賴與共同 gate

來源准入可與安全基線及 artifact 工作並行；實際資料接線才等待時間／版本依賴。B2、B3-wire、B4b、B5b 匯入 B7，同 snapshot 比較後才考慮預設切換。R2／R3 只依賴該批真正採用的來源，受限且未採用來源不作全域 blocker。

| Gate | 條件 | 未滿足 |
| --- | --- | --- |
| G-SAFE | 需要 DB 操作時確認授權／路徑、唯讀原資料、必要隔離副本與可恢復備份，驗 integrity／row preservation。 | 不執行該 migration、重算或 replay。 |
| G-ID | feature／strategy／execution／prediction／signal semantics／presentation 版本及 artifact identity 明確。 | 不覆寫 legacy 或同版本改語意。 |
| G-TIME | market／published／first available／collected／revision／decision／generated／earliest execution 與 timezone 分開。 | 歷史排除不合輸入；live fail closed。 |
| G-SOURCE | 所有者／來源類型、免費與保存／摘要權利、延遲、修訂、歷史、停用方式；四種用途分開准入。 | 該用途 restricted／unsupported；unknown 保留 reason，不改寫成明文禁止或跨用途放行。 |
| G-PRODUCT | 可先採盤後 long 假設；精確期間、做空、一般風險由統籌版本化，個人部位才需個人風險預算。 | 未知風險不給張數；T+5／T+20 不當退出日。 |
| G-MODEL | target、H、成本、不可比、split、校準／採用門檻在看 final test 前預先登錄。 | 只探索，probability=null，不採用；僅個人偏好參數另詢問。 |
| G-FORWARD | 先封存當日 plan，再等 trigger 與 H／退出完成，累積事先要求樣本／市場狀態。 | 等待，不用歷史 fixture 或短樣本結案。 |

## 3. R0：研究基準與時間

### R0-A：安全與 migration 基線

| ID | 狀態 | 依賴 | 已接受範圍與限制 |
| --- | --- | --- | --- |
| R0-A1／B6 | 已 review（局部） | G-SAFE | 唯讀盤點、隔離升級／fresh DB、六表 backup→故障→restore；不是正式 restore／deployment。 |
| R0-A2 | 已 review（局部） | R0-A1、C010／C011 | News JSON 空陣列 defaults、0004→0005→0006 的原子 migration／parity；只含具名 SQLite schema。 |
| R0-A3／R27 | 已 review（局部） | R0-A1／A2 | API startup 唯讀 readiness；建庫／升級仍須明確 init-db。未驗完整資料 integrity 或 reload。 |
| R0-A4／R28 | 已 review（局部） | R0-A1、G-ID | Canonical instruments rebuild、9 個 inbound FK、rollback／同 DB 重試；只支援具名形狀，未知 schema 拒絕。 |
| R0-A5／R29 | 已 review（局部） | R0-A1、R28 transaction envelope | 9／14 欄 settlements 升為 signal＋horizon；保留 payload／id、缺 horizon 預設 20，未知形狀拒絕。 |
| R0-A6／R30 | 已 review（局部） | R0-A3／A5 | 涉及 signal_id／horizon 的 UNIQUE 須符合 canonical 定義，任意 UNIQUE expression 拒絕；不解析 CHECK／trigger 或驗任意 INSERT。 |
| R0-A7／R31 | 已 review（局部） | R0-A3／A4 | 檢查 market／exchange／symbol 欄位及相關 UNIQUE，任意 UNIQUE expression 拒絕；canonical identity 是 exchange＋symbol，market 不屬 identity。 |

上述精確支援／拒絕形狀與驗收案例以 [R0 migration／readiness 契約](R0_IMPLEMENTATION.md#8-r0-5migration-head-與實際-db-revision)為準。各批只有有限成果，不證正式 migration／restore／deployment、任意 INSERT、PIT 或整體 R0 完成；安全工作不被 B7 反向阻塞。

### R0-B：版本化 artifact 與 ATR

| ID | 狀態 | 依賴 | 完成條件／目前邊界 |
| --- | --- | --- | --- |
| R0-B1／C-001 | 已 review（局部） | 無 migration | confidence 安全語意；不推論 B2 完成。 |
| R0-B2／B2-persist | 四個小批、bridge A、B adapter、selected bar 與 prior volumes 本地 metadata 接線已有限 review；獨立 selected-bar verifier 有程式與純記憶體案例的有限 review；整體未完成 | R0-A1、G-ID | B 只接受 opt-in capture→detached canonical candidate；caller 明示 current snapshot path／SHA、exact attempt／ordinal 與新研究 aware decision，保存另由 caller 明示 attempt／run。Capture v2 封存 selected bar close／volume；v3 封存實際 prior volumes 最多 20 筆有序本地列與 raw metadata。獨立 `verify_selected_bar_evidence` 對 caller 指定的 snapshot、v2／v3 selected call、raw FK 所指 `body.bin`／同目錄 `receipt.json` 及外部 receipt／registry pins 回 detached `local_evidence_consistent`，只證當次本地 selected-bar 證據一致；不改 bridge 的 `bytes_unverified` 或升格 prior volumes。真實檔案／SQLite snapshot／零寫入整合未驗；下一步尋找已授權可唯讀的 snapshot／body／receipt／registry pins tuple，缺 specimen 或 pins 則保持待驗，不建附件或 fixture。70 個既有案例未跑，pytest／必要磁碟驗證受目前落盤配額所限；見[協作紀錄](TASK_COORDINATION.md)。歷史原件／上游版本、availability／歷史決策／PIT、其餘衍生輸入仍未證；consumer、同 snapshot paired replay 及產品選版仍缺。API 與拒絕條件見 [Artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。 |
| R0-B3／C-002 | 已 review（純核心） | 無 I/O | Wilder ATR及strict caller inputs；未接官方來源或worker。 |
| R0-B4／B3-persist | 已 review（局部） | R0-A1、G-ID、R0-B3 | Immutable ATR store、精確雙唯讀比較及 schema1／v2 相容邊界；不相容輸出不可比，官方來源／PIT／worker 接線仍缺。完整支援與拒絕條件見 [R0](R0_IMPLEMENTATION.md)。 |
| R0-B5／B3-wire | 提案 | R0-B4、G-TIME、G-SOURCE | 官方session／halt／公司行動／previous-close均有raw／版本／availability；缺來源reason code fail closed，worker explicit opt-in讀artifact，預設候選不切換。 |

### R0-C：價位、時間與 paired replay

| ID | 狀態 | 依賴 | 完成條件／目前邊界 |
| --- | --- | --- | --- |
| R0-C1／B4a | 已 review（read-time） | G-ID | signal-level-semantics/v1涵蓋signal／action／stock／tracking及UI；僅canonical兩個v1策略推導legacy-risk-levels/v1，未知identity／basis／歷史時間fail closed。持倉與成交價不當規則價，原v1數值不改。 |
| R0-C2／B4b | caller-input 純核心已有限 review；完整 B4b 未完成 | R0-C1、G-PRODUCT | `calculate_trade_plan` 以 `caller-trade-plan/v1`／`caller-execution/v1` 對盤後 long 假設作嚴格輸入、單一 caller tick、保守捨入、gap／成本／流動性／停牌及事件／到期判定；完整 session 的 stop／target 順序未知回不可比。結果明示 `post_session_hypothetical`、PIT／成交未主張，觸價只是觀察。官方 tick／費稅／日曆、來源與 availability／PIT、合法交易時段、持久化、worker／API／UI、完整 legacy replay 及逐欄 paired comparison 仍待驗；見 [R0 實作 §6.2](R0_IMPLEMENTATION.md#62-新交易計畫的隔離邊界)。 |
| R0-C3／B5a | 已 review（兩個分離小批） | R0-A1、G-TIME | time-evidence/v1 caller store與product-time/v1 API/UI projection已review，但未有persisted linkage；unknown呈現不是execution gate。 |
| R0-C4／B5b | 提案 | R0-C3 | 每個必要版本available_at<=decision_at，live另要collected_at<=decision_at；T+2修訂不改T+1 artifact，無可信first_available_at的backfill不進歷史決策。 |
| R0-C5／B7 | 提案 | R0-B2／B5、R0-C2／C4 | 同一唯讀snapshot產隔離legacy／new；比較ATR、狀態、confidence、價位、availability、migration及不可比。重現成功、缺資料、gap、公司行動、legacy confidence、盤後與修訂案例。 |
| R0-C6 | 等待 | R0-C5 review | 各R0項按已review範圍更新；研究／預設切換另決策。R0-5可依B6獨立更新，不能因純核心／schema／fixture將整體標完成。 |

## 4. R1：可靠資料與事件

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R1-A1 | 已 review（局部）；整體未完成 | G-SOURCE；來源可行性可先行，實際 as-of 接線才依賴 R0-C4。 | 四來源 registry／capture、兩個 consumer 及窄修正已有限 review；其餘 collector、公司行動／停復牌、授權、時間／修訂／歷史與 PIT 仍待驗，具名範圍見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。 |
| R1-A2 | 提案 | R1-A1；官方行情／TAIEX／法人／融資逐域驗證。 | 以 exchange＋symbol＋session＋欄位用途產 coverage；錯日／缺日／unknown 不補 0；TWSE／TPEx 單位與 market identity 不混用；raw 可追溯。 |
| R1-A3 | 提案 | R1-A1、R0-B5；公司行動與停復牌。 | raw／adjusted basis、因子、版本、可得時間與 applied-through 可重建；TWSE／TPEx 覆蓋分開；不足時 ATR／tracking fail-closed。 |
| R1-B1 | 提案 | R1-A1、R0-C4；官方事件與 NewsItem 時間回歸。 | unknown time、date conflict、backfill、revision／withdrawal、feed-only URL、無內文均有案例；排序與 cursor 綁 snapshot／version；無可信時間者不搶占「最新」。 |
| R1-B2 | 提案 | R1-B1；同事件 grouping 與 new-information。 | 同源與跨源 dedupe 可重跑，保留每篇來源；首次／補充／更正／撤回分開；負面或轉載不增加正向催化；所有摘要回指合法原文。 |
| R1-B3 | 提案／可能受限 | R1-A1、G-SOURCE；免費官方 macro／可信媒體可行性。 | 每個候選以實際抓取、時間、保存／摘要權利與穩定性驗證；沒有可接受來源就記 `受限`，不以搜尋摘要或模型記憶補內文。 |
| R1-C1 | 提案；R16／17、R35–38 的身分小批已有限 review | R1-B2；正式分類修復依自身資料與驗收，不加無關 capture 工作作前置。 | 產業／題材分層及有來源、版本、期間的 membership。成員報酬、candidate 決策、backfill 納入及 public 展示各有有限成果，語意不得互換；正式分類與歷史 PIT／回算未完成。精確規則見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。 |
| R1-C2 | 提案 | R1-C1、R1-A2；題材品質與去重。 | 相同 as-of 的相對強弱、廣度、集中度、延伸與事件方向各自有窗口／缺項；重疊題材不重複計候選或曝險；不改 `hot_group_v1` gate。 |
| R1-D1 | 提案 | R1-A1；官方當沖資料。 | 先固定分子／分母、股數／金額、T／T+1／T+2 修訂與 availability；兩市場分開驗證；修訂可按當時版本重放。 |
| R1-D2 | 提案 | R1-A1；融券／借券／持股欄位。 | 每欄來源、單位、日期、revision、coverage 與 null policy 有證據；欄位存在不算已收集。 |
| R1-D3 | 提案／可能受限 | R1-A1、G-SOURCE；券商／分點來源可行性。 | 交易資料接入／匯入待做；完整驗收要求穩定合法歷史、通道識別、單位與 PIT。局部匯入可獨立驗收，不等於完整歷史或每日自動更新；不足標受限，不推論投資人身分或預測。可得性見 [DATA_SOURCES](DATA_SOURCES.md#券商分點與主力統計的來源邊界後續待做)。 |
| R1-E1 | 提案 | R1-A1、R0-C4；必要基本面。 | 只補公司品質／事件驗證所需欄位；會計期間與實際公告時間分開，更正保留版本；不擴成完整財報產品。 |
| R1-F1 | 提案 | 當次 daily/backfill 明列的必要來源集合；條件式分點或未採用來源不作全域 blocker。 | 對所選來源做隔離 daily/backfill 重試、冪等、rate limit、觀測、備份與失敗通知；未准入／受限來源保持 unavailable 並從該 job 明確排除。排程本身需另行明確授權，且與自動交易分開。 |

## 5. R2：候選與完整交易計畫

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R2-A1 | 提案 | R1-C2；題材研究輸出。 | 同方法／窗口輸出強弱、熱度變化、廣度、領漲集中、延伸、籌碼分歧、事件方向與 coverage；原值與正規化值可追溯。 |
| R2-A2 | 提案 | 已准入且本批採用的事件／基本面來源；缺少或受限的面向可先明確為 unknown，不阻塞不依賴它的交易位置與持倉風險。 | 公司品質、事件機會、交易位置、持倉風險分開；矛盾可同時呈現，不硬湊單一「好股分數」，也不把 unknown 補 0。 |
| R2-B1 | 提案 | R0-C2、G-PRODUCT；trade-plan schema 與純計算。 | 觸發／確認、進場區間、不追價、失效、目標／移動停利、時間／事件失效、成本、tick、流動性、期限與版本俱全；無合法計畫可輸出不交易。 |
| R2-B2 | 提案 | R2-B1；執行與 lifecycle。 | 未觸發、到期、rejected_gap、無法成交、模擬成交、實際成交、退出與 incomparable 分開；stop 不保證成交；同日 stop／target 無順序不偏向有利結果。 |
| R2-C1 | 提案 | R2-B1、G-PRODUCT；部位與曝險。 | 使用精確股數；單筆／單股／同題材風險可追溯；同股多策略／多題材不重複占用；風險預算未知時不給張數。 |
| R2-C2 | 提案 | R2-A2、R2-C1；行動摘要。 | 同 exchange＋symbol＋as_of 一張卡；產品 A–E 合併矩陣全覆蓋；已驗證持倉風險優先，完整 observation 不被誤標資料待補。 |
| R2-D1 | 提案 | 本批已完成的 R2-A／B／C 能力；受限來源對應區塊顯示 unavailable，不延伸成假資料。 | `/news`、`/themes`、`/stocks`、`/actions` 的已接能力使用同版本與時間；中文標籤、來源、未知、單位與價位語意一致；診斷/raw 預設收合。 |
| R2-D2 | 提案（後續待做） | R1-D3 在本批實際可用且已驗收的範圍；受限來源只讓對應區塊 unavailable。 | 依[個股頁 §8](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)整合三大法人、主力統計與券商分點介面；驗買賣超／家數差／5 日與 20 日集中度、分點排行與單一分點歷史、券商彙總、缺值及來源。局部匯入不代表完整歷史、PIT 或每日自動更新。 |
| R2-E1 | 提案 | R2-D1 與本批實際採用的來源／功能集合；條件式分點不作無關功能的 blocker。 | 零候選、缺資料、重疊題材、跳空、停牌、公司行動、修訂、持倉優先與多策略中適用案例可重跑；受限來源另驗 unavailable；production build、backend 全套與瀏覽器關鍵流程各自留證據。 |

## 6. R3：AI 與研究有效性

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R3-A1 | 等待決策 | G-MODEL、G-PRODUCT。 | 在看 final test 前凍結 target event、H、trigger／fill、stop／target、成本、不可比、universe、split、metric、校準與採用門檻；文件有版本／hash。 |
| R3-A2 | 提案 | R3-A1 預先登錄的 feature set 所列、已准入且實際採用的來源；未列入或受限來源不作 blocker，也不得被模型暗中使用。 | 保存當時 universe（含下市／失敗標的）、來源與 membership 版本、input snapshot、available-at gate、label window；重疊持有期有 embargo／purge 規則；65 日資料不得冒充充分歷史。 |
| R3-B1 | 提案／可能受限 | R1-B2、G-SOURCE、G-MODEL；本地／免費事件理解基準。 | 先用人工標註小集評估來源忠實、引用、事件／關聯／方向與拒絕率；模型／提示／輸入 hash 可重現；無可用本地／免費模型時保留 deterministic baseline 並標 AI 能力 `受限`。 |
| R3-B2 | 提案 | R3-B1；事件理解接線。 | 結構驗證、prompt-injection 隔離、更正／撤回、低把握待核實與回退規則通過；摘要流暢度不算策略增益。 |
| R3-C1 | 提案 | R3-A2；量化基準。 | 先跑固定技術基準，再依序加入題材、新聞、籌碼、AI；同 universe／window／cost；所有嘗試與失敗保留，不挑最好結果後改門檻。 |
| R3-C2 | 提案 | R3-C1；walk-forward／OOS／校準。 | train、tune/calibration、final test 按時間隔離；報成本後報酬、回撤、尾損、成交率、有效樣本、coverage、不可比率及 Brier／校準；適用外或失敗時 probability 為 null。 |
| R3-D1 | 等待時間累積 | R3-A1、R2-E1；前瞻模擬。 | 每日先封存 snapshot、候選、plan、零候選、模型失敗及撤回，再等待 trigger 與 H／退出完成；不得回寫舊決策。等待長度與最低有效樣本由 R3-A1 事先決定，未達前保持 `等待`。 |
| R3-D2 | 等待樣本／市場狀態 | R3-D1；漂移與壓力期。 | 覆蓋事先要求的市場狀態與成本敏感度；來源中斷、模型失效及固定規則回退演練；日曆時間超過三個月本身仍不等於足夠。 |
| R3-E1 | 等待統籌決策 | R3-C2、R3-D2。 | 統籌依預先門檻做採用／拒絕／延長觀察；只有達標版本能候選成為預設，仍非投資保證；其餘保持 research-only。 |

## 更新方式

文件角色每輪依統籌核定的完成狀態與驗收邊界，在 freeze／索引前更新受影響的工作列及主題契約。穩定內容不重寫，文件交付與結案依 [AGENTS](../AGENTS.md#文件與交接)。來源／前瞻樣本不足保持提案、等待或受限，不縮小原驗收條件。
