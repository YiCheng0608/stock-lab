# 開發路線與目前能力

更新：2026-10-04。本文件管能力、優先順序與待決事項；工作 ID／完成條件見[執行清單](ROADMAP_EXECUTION.md)，接手與暫停狀態見[協作紀錄](TASK_COORDINATION.md)。

## 目前進度（含產品有限核對與 R1-A2 磁碟驗收）

**R0–R3 均未整體完成。** 下表依既有有限驗收、opt-in prior volumes 本地列接線、獨立 selected-bar verifier，以及 B4b／B5b 各自 caller-input 純核心的有限 review 整理；verifier 只判定指定本地證據一致，尚無實際檔案／snapshot 整合驗收或既有流程接線。相關回歸仍待補，見[協作紀錄](TASK_COORDINATION.md)。

| 階段 | 已有能力 | 主要缺口 |
| --- | --- | --- |
| R0：研究基準與時間 | 信心／價位／時間相容語意；ATR 純核心及獨立保存層；有限 migration／startup gate；artifact、離線比較、pure-rule replay、worker capture、Bridge B opt-in candidate adapter；selected bar close／volume 與 prior volumes 最多 20 筆本地 metadata 關係；獨立 `STOCK_DAY_ALL` selected-bar 本地證據一致性 verifier；B4b 事後假設與 B5b caller-declared time-cutoff 各有純核心有限 review。 | 待跑回歸與 verifier 真實 tuple 整合、其餘衍生輸入、歷史原件／來源版本與 availability／歷史決策證據、artifact consumer、ATR worker 接線、完整 B4b 的官方 tick／費稅／日曆、完整 B5b 的實際依賴與來源／PIT gate、產品／持久化接線與 legacy-v2 paired replay。 |
| R1：可靠資料與事件 | 官方行情／法人／融資與 raw、backfill；原四來源 registry／capture、兩個有限磁碟 consumer，另 TWT48U selected 事件及本次 feed 記憶體摘要已有限 review；explicit TPEx 日法人來源准入與單日 selected 摘要已有限 review；TAIEX 身分窄修正與 TWSE／TPEx 成交額 availability 已各有限接受；TWSE selected 缺額／明確零的單一 offline file-backed capture→SQLite→API 測試、legacy migration 兩路徑八案例、指定三種 selected invalid／四類拒收的磁碟重開→API 整合已各有限驗收；legacy 日行情成交量精確整數 gate／TPEx 空結果條件及指定 capture→collect→SQLite 重開→HTTP 精確整數與拒收保留均已有限接受；產業期間、停復牌與公司行動局部修正。 | 成交量在指定 synthetic API／JavaScript／個股範圍已有限接受；真實逐欄 coverage 與其他股數投影精度仍待驗；其他未覆蓋 selected／legacy invalid 或拒收磁碟整合與正式 DB 升級待驗。逐市場／逐欄 coverage、TAIEX 合成 OHLC／量額、可得時間／修訂、完整公司行動及停復牌、正式舊分類修復、完整事件群組／摘要與其他來源產品接線、當沖／借券／分點資料與必要基本面仍缺。免費官方分點人工查詢入口不等於已接資料集。 |
| R2：候選與交易計畫 | v1 候選、行動摘要、持倉；群組候選身分、回補範圍及來源日展示；個股研究頁、繁中、表外單位與官方分點入口；M1-P1 截止一致總覽、P2b TPEx 單日法人原件、P3b selected 官方事件原件 API／UI、M2-P1 官方事件關注接個股總覽、M2-P2 搜尋／研究往返，以及 M3-P1／P2 的既有庫存精確呈現、int64 保存與指定磁碟重開、M3-P3 的成本／停損／風險輸入檢核與拒收保留、M3-P4 三態可信讀回與非法停損隔離、M3-P5 可信股數與既有估值／持倉判定一致、M3-P6a 庫存收盤數值隔離與可收合的本地試算已各有限 review；P6a 來源／日期證據仍未核實。 | 完整 M1 的法人／交易日窗口、完整事件 coverage 及研究條件；完整 M2 的其他理由與分類品質；行動行情預載污染隔離、庫存估值所用行情的來源／日期／價格可信讀回、污染／遺失意圖修復、歷史身分／PIT、完整計畫與成交／退出流程、成本／tick／gap／流動性、倉位／題材曝險及整合驗收。 |
| R3：AI 與有效性 | 固定規則、追蹤、回測及研究規格。 | 預先定義目標／採用門檻、walk-forward、樣本外／校準、前瞻樣本與模型採用；尚無經驗收 AI 預測或勝率。 |

**籌碼三區仍待做**：三大法人沿用已有資料；主力進出與券商分點的交易匯入、統計、排行／歷史及自動更新尚未完成。定義見[個股頁 §8](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)。

### 接下來的順序：近期產品里程碑

使用者已確認完整使用流程為 **今日關注 → 個股研究 → 條件計畫 → 追蹤回看**；建置先後為 **M1 個股研究 → M2 今日關注串個股 → M3 條件計畫與追蹤**。沿用既有五個主導航與量化契約；M1-P1／P2a／P2b／P3a／P3b 已有下列有限交付，完整 M1、M2、M3 仍未完成，規劃不算驗收。

1. **M1 個股研究總覽**：在已有 K 線、五分頁、每日法人、新聞與行動摘要之上，新增同一研究截止（`as_of`）的研究總覽，整合價格窗口、最近 5／20 交易日外資／投信／自營商各別淨買賣超與趨勢、近期新聞／官方事件的可追溯入口，以及研究條件「成立／未成立／資料不足」與真實原因；各資料日期、新聞發布／事件原時間保留，不強改為同日。實作前由統籌核定窗口、交易日判準、來源、缺日處理及版本，數值須可回指來源且不補零。只採已准入且本批驗收的資料與既有策略版本，不跨策略拼價位或虛構事件影響；既有分類待核實標示保留。缺來源使相關區塊為 unknown／unavailable，其他獨立區塊仍可用。交付須具名列出支援市場、標的、資料範圍與未支援區塊，不將既有頁重新計成交付，也不能只有全屏不可用 placeholder 就算完成。
2. **M2 今日關注串個股**：依本批實際採用的事件、族群與個股資料，提供可追溯的關注理由、時間與來源；同一股去重後可直接進入 M1 詳情。分類未核實時不得產生可信排名；零候選與來源不足須可區分，不能為湊名單補候選或推論事件影響。
3. **M3 條件計畫與追蹤回看**：只對來源、時間與版本門檻具體滿足的子能力核定接線，完成計畫保存、API、UI 與追蹤操作。觸發、到期、未成交、模擬成交及退出分開驗收；未知個人風險預算不給張數。既有 B4／B5／B7 完整 gate 與預設切換決策保留，必要依賴未滿足時保持等待，不以 unknown 標示規避該子能力的必要資料或合法執行條件。

**M1-P1 截止一致與來源可追溯總覽**：已新增共用資料日期截止、原件合格價格的實際區間／筆數、來源 details，以及法人、事件、研究條件的具體缺項。TWSE 1101／2330 的 2026-10-01 單日真實 selected 原件→consumer→記憶體 SQLite→API 六欄、指定截止與端點一致性、桌面及窄版具名操作已有限 review；後端邊界、前端 SSR／型別／build 通過，保留大型 JS chunk 警告。`as_of` 是事後資料日期篩選，非 PIT；不外推多日、TAIEX、TPEx 或法人數值。權威契約見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。完整 M1 尚缺其餘法人來源准入、交易日基準、5／20 日可驗窗口、事件及成立／未成立條件，不由 P1 宣稱已具備 M2 完整接線條件。

**M1-P2a TPEx 日法人來源與 selected 摘要**：必要基礎批次已解除 M1 的 TPEx 日法人來源 gate，以另 explicit 單來源 manifest／pins 接 exact OpenAPI capture 與唯讀摘要 library／CLI；來源及程式已有限 review，3105／6488 的 2026-10-02 單日數值、具名負向拒收與純記憶體靶向回歸已接受。詳細契約見[來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。M1-P2a 本身未接多日、DB、總覽 API／UI 或完整交易日曆；單日總覽接線另由下列 P2b 交付，TWSE T86 准入仍未知。完整 5／20 日窗口仍需交易日與缺日判準、多日原件及逐欄 coverage。

**M1-P2b 單日法人原件總覽接線**：明示 server ZIP／日期設定後，沿用 P2a gate 在總覽提供獨立 TPEx 單日原件區塊，已有限 review。3105／6488、2026-10-02 的原件→實際 API 二十個數值、detail／總覽一致與追溯欄位、桌面兩檔／截止操作及窄版展開雜湊已具名核對。契約與支持範圍見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。不補零、不稱最新資料，5／20 日仍 unavailable；無新 calendar 准入、DB／legacy 改寫或 PIT 完成。後端記憶體靶向回歸、前端 SSR／不落盤型別核對與記憶體全 App bundle 通過；本輪未跑完整 backend 或 production Vite build，完整 M1 不因單日接線完成。

**M1-P3a TWT48U selected 官方事件原件摘要**：必要基礎批次已解除 M1 的 selected 官方事件原件 consumer 缺口，沿用原四來源 manifest／pins，以零落盤記憶體 capture 與摘要 library／CLI 交付；程式及 TWSE 0056（ETF）／1449／1463 的當次未來生效預告已有限 review。原件四欄、列序與雙 hash 可追溯，缺 selected 拒收，事件日不當發布／首次可得時間、不推論價格影響；精確支持範圍見[來源契約 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)。純記憶體回歸及 source gate 縮窄後必要靶向複驗通過，未重跑現完整案例或完整 backend。本次 live 原件未保存，不能離線重播；P3a 本身未接 API／UI／DB，後續 selected 總覽接線由 P3b 有限交付，見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。PIT 與完整歷史仍缺。

各里程碑可拆成能獨立操作與驗收的子能力，但完成狀態須明列支援範圍；局部交付不等於 R0／R1 整體完成，也不取代 R2-E1 完整整合驗收。R0–R3 是技術、資料依賴與完整驗收分層，原全範圍保留；每批只處理所交付能力需要的依賴。工作映射與下一個可執行項見[執行清單](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。

**M1-P3b selected 官方事件總覽接線**：TWSE 0056（ETF）／1449／1463 當次原件→API 四欄／追溯、截止排除、detail／獨立總覽一致、成功 cache 再用，以及桌面三個標的／日期／來源／授權、窄版 details／表格自身捲動已有限 review。普通 GET 零外網、首次按鈕只取得一次；臺北觀測日不推導截止，未來生效預告保留，發布／首次可得仍 unknown。後端靶向回歸、前端型別／SSR 與記憶體全 App bundle 通過；完整 backend／production Vite build 未跑。主契約見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。無新 DB／legacy 或 PIT 完成，完整 M1 的 5／20 日與研究條件仍缺。

**M2-P1 官方事件關注清單接個股總覽（已 review，有限）**：沿用 exact TWT48U 記憶體來源與固定 pins，以本次合格 feed 同股一張、固定代碼順序與可追溯事件理由接 M1，不排名或推論利多。2026-10-03 一次真原件 58 列／58 股的四欄／列序→API、0056（ETF）／1449／1463 的相同截止 M1、桌面首次取得／截止排除與復原／來源授權及窄版具名操作已接受；其餘 55 股在測試 catalogue 無對應，保留事件但無連結。合法空 feed、同股多事件、100 股截斷及拒收另由記憶體 fixture 核對；時間、操作與精確支持範圍見[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。完整 backend／production Vite build 未跑，live 原件不能離線重播；不升格完整 M2 或真行情／DB coverage，也不放行 M1 的 5／20 日或研究條件。

**M2-P2 官方事件清單搜尋與研究往返（已 review，有限；已版本封存）**：支援 M2／R2-D1，已解除完整合格清單找標的及 M1 返回原條件的斷點。先驗全原件，再依來源代碼／名稱搜尋，符合結果最後才套 100 股上限；原件、符合、顯示及截斷分列，空原件／無符合／不可用可辨識。2026-10-03 一次真原件 58 列／58 股的四欄及列序→API、具名名稱／代碼／大小寫／查無搜尋、桌面 M1 改截止後返回原條件與 390×844 窄版搜尋／清除／往返已有限核對；fixture 邊界、前端必要複驗與未跑完整 backend／production build 分報，精確支持範圍見[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。不新增排名、來源、金融推論、PIT 或 DB 寫入，不升格完整 M1／M2。

**前輪 M1-P4a：TWSE 單日法人官方來源有界可行性與准入（有界審查已接受；來源未准入，等待精確證據）**。來源及程式唯讀審查已接受，exact 用途權利仍 unknown；未取得法人原件或實作 consumer／API／UI，不增加能力完成度。缺證與恢復條件集中見[來源 §12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口)。取得正面證據後才由統籌核定有界完整單日驗證，gate 具體滿足才核定必要單日總覽能力與白名單，不提前准入／改 pins；完整 5／20 日及 PIT 不作該批前置，也不由有界審查追認完成。

**前輪 R1-A2 legacy 成交額 migration 關閉後讀回與失敗復原（已有限接受）**：支援 M1 資料可信／R1 基線，解除 Alembic `0006→0007` 與已知 fallback-only `1→6→7` 兩路徑的指定磁碟驗證缺口；各四個可重建 synthetic fixture 案例，共八個專用 unittest 全過、無 skip，測試與清理分報成功、無新增殘留，已本地提交／合併。精確 fixture／NULL／marker 限度見[資料來源](DATA_SOURCES.md#r1-a2-legacy-成交額-migration-磁碟驗收有限接受)。未改產品來源或正式 DB，不增加 UI、官方 coverage、完整 5／20 日或 PIT 完成度，本輪不重跑。

**前輪 R1-A2 selected invalid／拒收磁碟整合（已有限接受並提交／合併）**：支援 M1 研究資料可信／R1-A2 基線，解除指定三種無效成交額與四類 selected 拒收的 production capture→collect→磁碟重開→API fixture 整合缺口；第三次實測 1 compound unittest／0 skip、十一個 API 回應及測試／清理成功已限定接受，核定根已不存在。該輪未改產品來源，其他未覆蓋 invalid／拒收及 R1-A2 全域驗收仍待驗。精確範圍與來源限度見[資料來源](DATA_SOURCES.md#r1-a2-selected-invalid拒收磁碟整合有限接受)，入口與配額見[開發入口](development-baseline/README.md#r1-a2-selected-invalid拒收的磁碟驗證入口)，清理狀態見[協作紀錄](TASK_COORDINATION.md)。

**前輪 R1-A2 legacy TWSE／TPEx 日行情成交量精確整數 gate（已有限接受並提交／合併）**：解除兩個日行情 parser 的浮點取整缺口，保留合法零、大整數及既有欄位，並避免 TPEx 將非空全拒收表格列為合法空結果。固定 synthetic fixture 的 parser／wrapper／adapter 記憶體驗證已接受，`_fetch` 以記憶體 metadata 替換；數值格式與具名支持範圍見[資料來源](DATA_SOURCES.md#r1-a2-legacy-日行情成交量精確整數-gate有限接受)，零落盤入口見[開發入口](development-baseline/README.md#r1-a2-legacy-成交量的零落盤驗證入口)，接手與封存狀態見[協作紀錄](TASK_COORDINATION.md)。該批未驗 collect、SQLite、API、live、UI、production startup 或完整 backend，不增加完整 R1-A2、5／20 日、M3 或 PIT 完成度。

**前輪 R1-A2 legacy 成交量 gate→capture／collect／SQLite／reopen／API 精確保存與拒收保留（已有限接受並提交／合併）**，支援 M1 研究資料可信／R1-A2 基線，解除指定 fixture 的最小磁碟驗收缺口。首次實際磁碟測試 1 compound unittest／0 skip、兩次 force collect 與 60 個 HTTP 回應已接受，測試／清理成功、核定根已不存在；六個合法零／大整數、24 個拒收 existing／empty、第二次全 invalid 保留及磁碟重開後 HTTP int token 的精確支持範圍見[資料來源](DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)，入口與配額見[開發入口](development-baseline/README.md#r1-a2-legacy-成交量的磁碟整合驗證入口)，freeze／封存狀態見[協作紀錄](TASK_COORDINATION.md)。產品來源 diff 為 0；真官方、live、UI、正式 DB、完整 backend、production startup、Decimal capture、5／20 日與 PIT 均未驗，不升格完整 R1-A2 或 browser 端精度。

**前輪 M1／R1-A2 成交量 HTTP→JavaScript→個股精確呈現（已有限接受並提交／合併）**：支援 M1 研究資料可信／R1-A2，解除指定 synthetic API→JavaScript→個股文字的精度缺口。保留既有數字欄位、增添精確整數字串與舊回應的有限回退，接通可用的 App 頂部、行情／總覽、圖表提示及等效資料表，圖形高度明示近似，並補窄版長數字換行。程式、必要記憶體／HTTP 與完整字串邊界複驗、TWSE／TPEx `MAX`／`ODD`／`ZERO0` 具名操作、390px 與截止按鈕操作已有限接受；測試產物／殘留為 0，自有 tab／程序／listener 已核實關閉或不存在，兩個 serve 的 exit 1 與測試 exit 0 分報。主契約、fixture 及精確支持範圍見[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)，入口見[開發入口](development-baseline/README.md#m1r1-a2-成交量精確呈現的零落盤驗證入口)，freeze／封存見[協作紀錄](TASK_COORDINATION.md)。不稱真官方／live、不放寬 TWSE selected gate 或 TPEx 總覽、不升格完整 M1、正式 DB、5／20 日或 PIT。

**前輪 M3-P1 既有庫存股數呈現與失精輸入拒收（已有限接受並版本封存）**：以當時可信 Float 安全整數支持精確張／零股／原股、commit 前拒收及兩市場桌面／390px 操作；純 helper 的 int64 與 Float 保存支持分報，記憶體讀回不當磁碟重開、不還原已失精舊值。當時新增測試產物／殘留為 0，首次 cached whitespace 檢查失敗與正常 follow-up 提交／master 合併分報，詳見[協作紀錄](TASK_COORDINATION.md)。原有限契約與具名範圍見 [UI 文案](UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)，原入口見[開發入口](development-baseline/README.md#m3-p1-既有庫存股數的零落盤驗證入口)。

**前輪 M3-P2 可信整數保存與磁碟重開（已有限接受並版本封存）**：支援 M3／R2-C1 保存基線，解除股數字串到 SQLite int64、必要 0008 migration／readiness 及指定 close／reopen 的斷點。26 個程式檔與必要記憶體、兩 migration 路徑 normal／fault 的四個磁碟案例、actual main owned-fixture startup／HTTP，以及兩市場桌面／390px 的 ODD／MAX 保存、第二程序重開、MAX+1／張數超限拒收與完整列保留、最大張數／刪除已有限接受。主契約見 [UI 文案](UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)，有限 migration 與入口見 [R0 §8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)／[開發入口](development-baseline/README.md#m3-p2-可信整數保存與磁碟重開驗證入口)。隔離 DB 已清；額外 HAR 的審核拒絕殘留、原始失敗及 freeze／索引／commit／merge 狀態另列[協作紀錄](TASK_COORDINATION.md)。不回復捨入舊值，不宣稱大數金融估值 exact、正式 DB／production deployment、真官方／live、新 Plan、完整 backend／production build、完整 M3 或 PIT。

**前輪 M3-P3 庫存成本／停損／風險輸入可信檢核與拒收保留（已有限接受並版本封存）**：支援 M3／R2-C1，解除非有限／失真輸入被保存，或在 JSON 序列化後成為 null 清欄的斷點。三層 gate 分為 UI 原始成本／停損字串、actual upsert helper 的序列化前檢核、raw HTTP 的 server 拒收；合法有限非負數、零、null／省略與既有整列覆寫語義保留，拒收不改完整列、UI draft 保留。七檔程式、必要記憶體 router／前端／118 個 actual HTTP，以及 TWSE 實際桌面 1298×924 非零保存、TPEx 390×844 零／空白清欄與具名負向操作已有限接受；原 12 列完整 JSON 保持，自有 memory 程序／tab／listener 已清，新測試磁碟產物 0。主契約及具名支持範圍見 [UI 文案](UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)，入口見[開發入口](development-baseline/README.md#m3-p3-庫存價值輸入的零落盤驗證入口)，freeze／索引／commit／merge 狀態見[協作紀錄](TASK_COORDINATION.md)。這是 Float 輸入 gate，不宣稱十進位 exact、既有污染修復、風險行動／所有估值、risk sizing、新 Plan、正式 DB／磁碟重開、完整 backend／production build、完整 M3 或 PIT。

**前輪 M3-P4 既有庫存價值可信讀回與非法停損隔離（已有限接受並版本封存）**：支援 M3／R2-C1，三欄 known／missing／invalid、可信成本損益、非法停損隔離與原 gate 優先已有限接受。九檔程式／五文件已 freeze／五分區索引／正常 commit／ff-only merge；十四列 SQL 不變、17 actual HTTP 與具名兩市場讀值／研究頁、自有資源清理及新產物 0 的原範圍保留，不因換輪重跑。主契約見 [UI 文案](UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)，入口見[開發入口](development-baseline/README.md#m3-p4-庫存價值可信讀回的零落盤驗證入口)；不推定污染修復、行情可信、所有估值／風險行動或完整 M3。

**前輪 M3-P5 可信庫存股數與既有估值／持倉判定一致（已有限接受並版本封存）**：支援 M3／R2-C1，解除可信 int64／safe legacy 股數與既有估值、held、篩選、計數及優先集合互相矛盾的缺口。未知記錄保留並隔離決策，超 safe 的 exact 股數／held 保留而估值明示 unsupported；有限 Float 估算不證行情來源／日期／價格可信。十檔實作、必要零落盤 direct／前端、45 actual HTTP 核十六列／十六 decisions／whole SQL 不變，以及真正 desktop／390px 庫存／行動／首頁／研究詳情操作已有限接受；詳情 badge 同輪退修後才通過。主契約與具名結果見 [UI 文案](UI_COPY_SPEC.md#m3-p5-可信庫存股數與既有估值持倉判定一致)，入口／原始失敗見[開發入口](development-baseline/README.md#m3-p5-可信股數與估值持倉判定的零落盤驗證入口)；十五檔已 freeze／五分區索引／正常本地 commit／乾淨 master ff-only merge，限量外部清理已由新統籌完成，見[協作紀錄](TASK_COORDINATION.md)。新測試產物 0、自有 QA／程序已清；M3-P4 兩索引 logs 713 bytes blocked 與更早 HAR／blocked／occupied 排除、不重試，不冒稱歷史全清或磁碟／完整 M3 通過。

**本輪 M3-P6a 庫存收盤數值隔離與本地試算可檢視（已有限接受）**：支援 M3／R2-C1，解除庫存 full ORM 污染阻斷、非法 close 與未核實估值日常顯示的缺口；來源／日期證據仍 unverified。七檔實作、修正版零落盤 SQLite→router→JSON→JavaScript／Portfolio、二十庫存／十八行情兩整表不變、actual full App 上 Portfolio 的桌面／390px 真正收合操作已接受；主契約及具名結果見 [UI 文案](UI_COPY_SPEC.md#m3-p6a-庫存收盤數值隔離與本地試算可檢視)，入口／原始失敗見[開發入口](development-baseline/README.md#m3-p6a-庫存本地行情與試算的零落盤驗證入口)，freeze／索引／commit／merge 由[協作紀錄](TASK_COORDINATION.md)追蹤。自有 QA／程序已清、新測試磁碟產物 0；原 actions context 仍因 `not-a-date` 造成兩次 500／頁面資料載入 error，Portfolio 可用不表示完整 ActionsPage 或行動端點回歸通過。行情來源／日期／availability、正式 DB／磁碟重開、官方／live／M1 正向 file gate、Decimal exact、production／完整 backend／Vite build、新 Plan／保存刪除 UI／完整 M3／PIT 未驗，不以 memory 降低原契約。

下一具名候選為 **M3-P6b「行動行情讀回污染隔離」**，支援 M3／R2-C2。合併後交新獨立 worktree／統籌先有界核 `decision._prepare_decision_context` 的 Date／DateTime／close 預載、source／time／purpose gates、所有必要 caller、as_of 與計數 scope，再核定可獨立操作／驗收的最小能力及互斥白名單；不預定修法，不 catch 後補 0、提供建議或更改來源准入／tick／time gate。完整 verified portfolio quote 仍需其必要實件證據，未驗保持待驗；這是具名下一依賴，不把其他 ROADMAP 餘項列為全域阻擋。規劃不算能力交付，真正磁碟驗收仍受原配額與完成條件。

M3 可由既有 caller-input 計畫純核心評估接線，但新計畫保存／合法執行仍須其本身的官方 tick／費稅／合法時段／來源與時間 gate，且磁碟保存驗收不能用記憶體取代；不由 legacy tracking 推論新計畫已完成。

**M1 後續依賴審查**：2026-10-03 的唯讀審查已接受，但在該次選題、既有授權與現有證據下，未找到可解除依賴的新實作，不增加能力完成度。完整 5／20 交易日窗口及成立／未成立研究條件保持**等待外部來源或完整證據**，上述依賴等待本身不是使用者暫停，也不表示 ROADMAP 全部餘項受阻。恢復窗口須有可信完整交易日基準、已准入的多日法人原件及所採範圍／缺日 coverage；研究條件另須滿足必要輸入、來源、時間與分類門檻。成交日實列只能證已觀測日，不能由缺列推休市或最近 5／20 日完整性。來源候選服務恢復時可先作有界可行性核實，服務可讀不等於上述門檻通過；詳細審查證據見[來源 §10](SOURCE_REGISTRY.md#10-m1-後續依賴審查來源候選與等待邊界)。最近 M2-P2 已沿既有事件來源有限交付並版本封存；前輪 M1-P4a 有界審查已接受但來源未准入，未解除完整窗口與研究條件門檻。角色接手依 [AGENTS](../AGENTS.md#每輪流程)，目前 roster 與範圍見[協作紀錄](TASK_COORDINATION.md)。

R0-B2 是依賴工作，並非全局第一主題。其已授權唯讀 snapshot／body／receipt／registry pins tuple 尚缺，依賴未變時保持待驗，不再重複搜尋或建 specimen／fixture 冒稱來源接入；其他可行工作依里程碑推進。精確缺口與原有限成果見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)，既有輪限制見[協作紀錄](TASK_COORDINATION.md)。

## R0 要修正的五件事

| ID | 現況 | 剩餘驗收 |
| --- | --- | --- |
| R0-1 ATR | Wilder 純核心與保存層已有限 review；worker 仍用 legacy 算法。 | 官方輸入與可得時間、B3-wire、PIT 及新舊重播比較。 |
| R0-2 信心與保存輸入 | 新固定規則 confidence 為 null；legacy 值不代表機率。保存、比較、replay、capture、bridge A、B adapter、selected bar 與 prior volumes 本地 metadata 關係及獨立 selected-bar 本地證據 verifier 各有有限成果。 | 待跑回歸與 verifier 真實 tuple 整合、逐輸入歷史原件／上游版本、availability／完整歷史輸入、consumer／產品接線、同 snapshot 新舊 paired replay 與選版。 |
| R0-3 價位 | 已標規則參考價；B4b caller-input 純核心有限 review 可對盤後 long 假設檢查 tick、成本、gap、不追價、流動性、期限及日線先後未知，結果不主張 PIT 或成交。 | 完整 B4b 的官方 tick／費稅／交易日曆、來源與 availability／PIT、持久化及 worker／API／UI、完整 legacy replay／新舊逐欄 paired comparison；尚未形成產品交易計畫。 |
| R0-4 時間 | 已有時間保存與顯示基礎，兩者尚未接通；B5b 的 caller-declared time-cutoff 純核心有限 review 能檢查精確配對輸入的首次可得／修訂／live 收集時間，但不證來源真實性或完整依賴。 | Store／worker／產品關聯、實際來源與歷史決策證據、完整 B5b／PIT gate、修訂與回補整合。 |
| R0-5 DB 邊界 | 有限 migration、canonical rebuild 與唯讀 startup gates 已 review。 | 正式 migration／restore／deployment、未支援 schema 及服務 reload。 |

算法、schema 與驗收限制由 [R0 實作](R0_IMPLEMENTATION.md)負責。修正須辨識 feature、strategy、execution、presentation 及資料版本，不沿用 v1 名稱改歷史語意；預設切換另需 B7 與決策。

## 已接受成果的查閱位置

具名工作狀態見[執行清單](ROADMAP_EXECUTION.md)，細節按[文件索引](README.md)查各契約。歷史測試數、命令與提交證據由 Git／原 task 追溯，不換算成產品完成百分比。

## R1–R3 驗收方向

- **R1**：逐市場、標的、日期與用途驗來源／coverage；成交額缺失／無效依已選契約以數值 `0` 另存 `unavailable` 與原因，不能當有效零，其餘 unknown 不補零。完整條件見[資料來源](DATA_SOURCES.md)、[新聞](NEWS_SPEC.md)與[產業分類](INDUSTRY_CLASSIFICATION.md)。
- **R2**：分開公司品質、事件機會、交易位置與持倉風險；交付可拒絕交易的完整計畫，見[產品規格](PRODUCT_SPEC.md)。
- **R3**：先定目標與採用門檻，再驗增量、樣本外與前瞻；樣本不足保持等待，未校準不給機率，見[策略驗證](STRATEGIES.md)。

## 產品取捨與待決定事項

| 項目 | 現行處理 |
| --- | --- |
| 成交額缺值 | 已選定保留有效 OHLC／volume，缺失或無效成交額數值存 `0` 並另存狀態／原因；明確來源零才是可用零。有限實作與待驗邊界見 [R1-A2](ROADMAP_EXECUTION.md#4-r1可靠資料與事件)。 |
| 使用情境 | 暫以盤後 long、最早 T+1、數天至數週設計；精確期間與做空待決。T+5／T+20 是追蹤窗口，不是必然退出日。 |
| 風險預算 | 未知時不預填個人比例或具體張數；一般研究方案可先版本化設計。 |
| 來源／AI | 免費公開來源先做可行性；供應商、預算、歷史權限、部署、成本／隱私未選定。預測／採用門檻在看測試結果前記錄。 |
| 資訊審核 | 來源准入、逐項證據及高風險／低把握覆核；不要求每則合格摘要一律人工點選。 |
| 保留加強 | 來源／時間／品質追溯、策略版本、回測、模擬追蹤、持倉風險、新聞、族群、個股頁。raw／run／coverage／原因碼／完整公式留研究後台。 |
| 降低新增優先 | 全 ETF 專用策略、完整財務記帳、大量新指標、細碎呈現改版；既有相容能力保留。 |
| 第一版不含 | 盤中即時交易、自動下單、無來源 AI 報價、未驗證勝率、確定身分的「隔日沖主力」標籤。 |

資料收集排程與交易自動化分開：前者依來源可靠性、重試與觀測驗收，不以策略績效作前置；實際排程及交易各須明確操作授權。
