# R0–R3 執行清單

更新：2026-10-04。本文件管理工作 ID、狀態、依賴與完成條件；優先順序見 [ROADMAP](ROADMAP.md)，精確規格見各列連結。

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

來源准入可與安全基線及 artifact 工作並行；實際資料接線才等待時間／版本依賴。B2、B3-wire、B4b、B5b 匯入 B7，同 snapshot 比較後才考慮預設切換。以下 gate 與工作依賴按本批採用的來源、用途及能力核對；受限且未採用來源只阻擋相關能力，不作全域 blocker。必需資料或時間 gate 未滿足的能力仍等待，不能以 unavailable 標示代替驗收。

| Gate | 條件 | 未滿足 |
| --- | --- | --- |
| G-SAFE | 需要 DB 操作時確認授權／路徑、唯讀原資料、必要隔離副本與可恢復備份，驗 integrity／row preservation。 | 不執行該 migration、重算或 replay。 |
| G-ID | feature／strategy／execution／prediction／signal semantics／presentation 版本及 artifact identity 明確。 | 不覆寫 legacy 或同版本改語意。 |
| G-TIME | market／published／first available／collected／revision／decision／generated／earliest execution 與 timezone 分開。 | 歷史排除不合輸入；live fail closed。 |
| G-SOURCE | 所有者／來源類型、免費與保存／摘要權利、延遲、修訂、歷史、停用方式；四種用途分開准入。 | 該用途 restricted／unsupported；unknown 保留 reason，不改寫成明文禁止或跨用途放行。 |
| G-PRODUCT | 可先採盤後 long 假設；精確期間、做空、一般風險由統籌版本化，個人部位才需個人風險預算。 | 未知風險不給張數；T+5／T+20 不當退出日。 |
| G-MODEL | target、H、成本、不可比、split、校準／採用門檻在看 final test 前預先登錄。 | 只探索，probability=null，不採用；僅個人偏好參數另詢問。 |
| G-FORWARD | 先封存當日 plan，再等 trigger 與 H／退出完成，累積事先要求樣本／市場狀態。 | 等待，不用歷史 fixture 或短樣本結案。 |

### 2.1 近期里程碑接線映射

M1／M2／M3 的新增範圍由 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑) 定義；M1-P1 已有有限交付，M1-P2a 已解除 TPEx 日法人來源 gate，P2b 獨立單日總覽、P3a selected 官方事件記憶體摘要、P3b 總覽接線、M2-P1 官方事件關注入口及 M2-P2 搜尋／研究往返已各有限 review，完整里程碑仍未完成。此表只列派工與操作驗收；各主題完整 gate 仍以原工作列為準。

| 里程碑／工作 ID | 實際必要依賴 | 下一個可執行工作／解除條件 | 操作驗收條件 |
| --- | --- | --- | --- |
| M1：R2-A2、R2-D1；所採資料對應 R1-A2／R1-B1 | 本批准入來源與用途、行情／法人窗口及交易日 coverage、事件／新聞時間與版本。只依賴採用範圍；歷史或執行斷言仍須其實際時間 gate。 | 2026-10-03 後續依賴唯讀審查已接受；完整 5／20 日窗口與研究條件等待外部來源或完整證據。恢復須可信完整交易日基準、已准入多日法人原件與範圍／缺日 coverage，研究條件另滿足必要輸入／來源／時間／分類門檻；再核定規則與接線。主缺口及恢復流程見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。 | 從個股入口讀到新增總覽；對來源核對 5／20 日法人數值與趨勢、研究截止一致的條件及原因，保留原資料／事件時間並開啟原始入口；缺日、資料不足與合法零可辨識，列明支持範圍。 |
| M1-P1：R2-A2／D1 的有限總覽接線 | 已准入 exact STOCK_DAY_ALL 的 fetch／store／summarize 與 selected 原件證據；共用資料日期截止，非 PIT。 | 兩檔／單日真實價格、具名產品操作與後端邊界、前端 SSR／型別／build 已有限 review。接續先核定法人、交易日准入與可驗 5／20 日窗口，不當作 M2 已就緒。 | 原件→consumer→記憶體 SQLite→API 六欄與截止排除／晚於價格提示、detail／總覽端點一致、桌面來源 details／日期控制／新聞入口、窄版展開 details 已有限核對；支持 TWSE 1101／2330 的 2026-10-01 selected 真實樣本，不外推 TPEx、TAIEX、多日或法人；精確契約見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。 |
| M1-P2a：R1-A1／A2 的 TPEx 日法人來源基礎 | Exact `tpex_3insti_daily_trading` 用途准入、另 explicit 單來源 manifest／pins、股數口徑與 selected 原件證據。 | 來源及程式已有限 review，具名正負向 CLI 與純記憶體靶向回歸已接受；單日產品接線由 P2b 獨立交付。完整 5／20 日窗口仍需交易日／缺日判準、多日原件及逐欄 coverage。 | 3105／6488、2026-10-02 原件→capture→唯讀摘要 CLI 的 20 個數值一致，錯日期／缺 selected／pin conflict 拒收，ZIP 讀前後不變；P2a 本身只支持單日 selected，不證完整交易日曆、多日、DB／API／UI 或 PIT。精確契約見[來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。 |
| M1-P2b：R2-A2／D1 的單日法人原件接線 | P2a 固定 manifest／pins／profile、明示 server ZIP／expected date、總覽共用截止；只採 TPEx selected。 | 已 review（有限）：3105／6488、2026-10-02 原件→API 二十個數值、追溯欄位及端點一致、桌面兩檔／截止／最新資料操作與窄版展開雜湊已接受。完整 5／20 日與 calendar 仍等待，完整 backend／production Vite build 本輪未跑。 | 每檔十個精確字串股數、來源／授權與可展開的日期／版本／雙 hash／列序；未配置零讀取、未來日期拒用、較早原件提示、無 cutoff／非 TPEx／不合格原件不補值。窄版 body 無橫向溢出、表格可獨立水平捲動；單日可用不放行 5／20 日、DB／legacy 或 PIT。精確契約見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。 |
| M1-P3a：R1-A1／R1-B1 的 TWT48U selected 事件摘要基礎 | 原四來源固定 manifest／pins、exact TWT48U GET 的 fetch／store／summarize 用途與完整性／追溯條件；memory 路徑只接受 TWT48U，不新增磁碟 artifact。 | 已 review（有限）：TWSE 0056（ETF）／1449／1463 當次原件與實際 CLI、缺 selected 拒收、純記憶體回歸與 source gate 縮窄後必要靶向複驗已接受；現完整案例未重跑。後續 P3b 已有限交付 selected 總覽接線與觀測截止，見下一列／[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。 | Exact selected 四欄、列序與雙 hash 一致；三筆未來生效預告保留，發布／首次可得／修訂仍 unknown、不推論價格影響。CLI explicit selectors／pins、stdout 與零落盤已核對；本次 live 不可離線重播，P3a 本身不放行 ZIP 讀入、DB／legacy、PIT、完整歷史或產品完成。精確支持範圍見[來源契約 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)。 |
| M1-P3b：R2-A2／D1 的 selected 官方事件總覽接線 | P3a 固定 TWT48U memory consumer／manifest／pins、server 明示啟用與首次專用 POST、capture 臺北觀測日不晚於共用截止。 | 已 review（有限）：0056（ETF）／1449／1463 當次真原件→API 四欄／追溯、截止排除、端點一致／同 cache 再用、桌面三個標的與窄版 details／表格自身捲動已接受。完整 backend／production Vite build 未跑；後續依賴審查與等待狀態見 M1 列，不增加 P3b 範圍。 | 普通 GET／import 零外網，首次按鈕只取一次，成功 cache 再用不 refresh；缺截止／早截止／來源或 selected 拒收為 unavailable，未來生效預告保留；feed 不冒充單篇原文，不推論價格影響或 PIT。主契約見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。 |
| M2：R2-A1、R2-D1；所採理由對應 R1-B1／B2、R1-C1／C2 | 已接 M1 詳情；每項關注理由所用來源、時間與版本。採用事件去重才需 R1-B2；可信族群排名須先通過分類及相應完整品質 gate。 | 在已驗收資料範圍建立今日關注，完成同股去重與詳情連結；未核實分類保留待核實，不進可信排名。 | 從今日關注進 M1，回查每項理由、時間與來源；同股只一張，零候選與缺來源結果可分辨。 |
| M2-P1：R2-D1 的官方事件關注清單接線 | P3a／P3b 固定 TWT48U memory 來源／pins、全 feed 身分／日期／分類驗證、既有 cache／鎖、明示 `as_of` 與臺北觀測日期 gate；個股連結另須 catalogue 標的存在。 | 已 review（有限）：一次真原件 58 列／58 股的四欄與列序→API、三個已知 catalogue 標的相同截止進 M1、桌面首次取得／截止排除復原／來源授權及 390×844 窄版操作已接受。其餘 55 股無測試 catalogue 連結；fixture 與 live 範圍分報，完整 backend／production Vite build 未跑。M1 完整窗口及研究條件不作本批入口前置，原等待不變；後續 M2-P2 搜尋與研究往返已有限交付，見下一列。 | 普通 GET／import 零外網，首次明示 POST 只取得一次且與 P3b 再用同 cache；同股多事件、空 feed、100 股截斷及非 available 無 `rows` 的邊界由純記憶體 fixture 核對。觀測／生效時間分開、未知 catalogue 不造連結，不推論排名、價格影響或 PIT；精確實作與具名支持範圍見[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。 |
| M2-P2：R2-D1 的官方事件搜尋與研究往返 | M2-P1 固定來源／pins／全 feed gate、同 cache／截止及 known catalogue 入口；先驗全原件，再搜尋來源代碼／任一名稱、排序、100 股 cap，返回路徑固定。 | 已 review（有限），已 freeze／索引／本地 commit：一次真原件 58 列／58 股→API、具名名稱／代碼／大小寫／查無搜尋、桌面改 M1 截止後返回原條件及窄版搜尋／清除／往返已接受。必要記憶體／前端驗證與修正分報，完整 backend／production build 未跑；不增加完整 M1／M2 或 DB／PIT 完成度。 | 原件／符合／顯示／截斷分列，空原件、無符合與來源不可用可分辨；query 長度、匹配外壞列與 101 股以上上限等由 fixture 驗邊界，不冒充 live。固定返回保留原 as_of／q，未知 catalogue 無連結，新 query 不混舊卡。主契約及支持範圍見[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。 |
| M1-P4a：TWSE 單日法人官方來源有界可行性與准入（有界審查已接受；來源未准入，等待精確證據） | 免費官方 exact 來源及用途／權利、實際欄位／日期／單位、完整回應與 selected 可驗性；不先要求完整 5／20 日基準或 PIT。 | 已依使用者恢復授權完成有界來源及程式唯讀審查；用途權利仍 unknown，未取得法人原件或新增實作。取得 exact 正面證據後才由統籌核定有界完整單日驗證，gate 具體滿足才核定必要 consumer／單日總覽能力與精確白名單；不提前准入／改 pins。詳細缺證及恢復條件見[來源 §12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口)。 | 審查不稱產品能力完成；完整欄位／日期／單位及 selected 數值未驗，本輪 tests／backend／production build／UI 操作未跑。真正接線仍須原件→consumer→API 數值與追溯、同截止與具名桌面／窄版操作，未知缺項不補零；單日可用不放行多日／全市場／PIT。下一步由[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)負責。 |
| M1／R1-A2：成交量 HTTP→JavaScript→個股精確呈現 | 前輪精確整數 gate／磁碟 HTTP 證據、核定相容表示；沿用所用來源與 TWSE selected gate，TPEx 總覽仍 unavailable。 | 程式、必要記憶體／HTTP／完整字串複驗及 TWSE／TPEx 具名操作已有限接受，測試產物／殘留為 0；日期與資料說明的 DOM 操作邊界、兩個 serve exit 1 分報。不改 parser／portfolio／來源准入。主契約見[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)。 | 固定 synthetic 來源→實際 router API→JSON parse→具名桌面／窄版操作，核對 int64 上限、安全整數外奇數、零／零股、缺值及格式／溢位拒用；所有文字保留位數，圖形高度明示近似。純記憶體測試與全 App bundle 不代替真官方／live、production build、正式 DB、磁碟或完整 M1／PIT 驗收，實際支持範圍集中見主契約。 |
| M3：R2-B1／B2、R2-C1、R2-D1；R0-C2／C4／C5 | 所交付計畫／追蹤子能力的 B4／B5 來源、時間、版本、合法執行與保存 gate；新舊比較／預設切換仍依 B7 與統籌決策。 | 逐子能力核對實際依賴；滿足才接計畫保存、API、UI 與追蹤，未滿足者等待並列解除條件。既有 caller-input B4b／B5b 純核心未接新 Plan 保存或產品；legacy tracking 只讀既有 evaluation／settlement，不視作新計畫生命周期完成。 | 保存後可讀回相同版本計畫，磁碟驗收不能以記憶體代替；觸發、到期、未成交、模擬與退出各自可操作、可回指證據；未知風險不輸出張數，不以觸價主張成交。 |
| M3-P1：既有可信庫存股數呈現與失精輸入拒收；支援 R2-C1／D1 的單位基線 | 當時持倉 Float 的可信安全整數範圍、StrictInt 四種互斥輸入及精確字串相容表示；synthetic 使用者庫存，不新增來源／計畫 gate。 | 九個程式檔、必要記憶體／HTTP／前端與具名桌面／390px 操作已有限接受並版本封存；該輪測試產物／殘留 0。首次 cached check 失敗及正常 follow-up／合併見[協作紀錄](TASK_COORDINATION.md)，現行大數保存由下列 P2 補齊。原契約見 [UI 文案](UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)／[原入口](development-baseline/README.md#m3-p1-既有庫存股數的零落盤驗證入口)。 | 當時可信 Float 的 SAFE 尾 991、零／未知呈現、股／張失精輸入 422 且既有列保留；純 helper int64 與 Float 保存分報，記憶體讀回不當磁碟重開，不驗估值、新 Plan、正式 DB 或完整 M3。 |
| M3-P2：可信整數保存與磁碟重開；支援 M3／R2-C1、必要 R0 migration／readiness | 保留 Float 相容欄、nullable SQLite INTEGER、一次 safe legacy backfill、互斥 strict numeric／canonical string 輸入、0008／八枚 markers 與唯讀 descriptor；不增加來源／新計畫 gate。 | 26 個程式檔與必要 memory／四個 disk normal＋fault cases／actual main owned-fixture HTTP／兩程序重開／具名 desktop／390px 操作已有限接受。7 檔文件已依接受結論更新，前輪 33 個核准檔已 freeze／索引／本地 commit／合併，最終收據留原 task；隔離 DB 已清，HAR 審核拒絕殘留另列[協作紀錄](TASK_COORDINATION.md)。主契約見 [UI 文案](UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)、[R0 §8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)與[開發入口](development-baseline/README.md#m3-p2-可信整數保存與磁碟重開驗證入口)。 | ODD／MAX exact int 到 SQLite INTEGER，關閉重開完整 NEW JSON 不變；超限股／張不送 POST、完整列保持；最大張數／零股及刪除可操作。Migration 保留 unsafe NULL／原 Float 與非數量資料、fault rollback／retry、冪等、有限 readiness 雜湊不變；不外推捨入舊值修復、大數金融估值、正式 DB／production deployment、真官方／live、完整 backend／Vite production build、新 Plan／完整 M3／PIT。 |
| M3-P3：庫存成本／停損／風險輸入可信檢核與拒收保留；支援 M3／R2-C1 | 既有三個 nullable Float API 欄位、UI 兩個原始輸入、actual upsert 的 pre-JSON guard 與原整列覆寫／清欄語義；不增加來源、schema、新計畫或 risk sizing gate。 | 已 review（有限）：七檔程式、必要記憶體 router／前端／118 個 actual HTTP、TWSE 實際桌面 1298×924 非零保存、TPEx 390×844 零／空白清欄與具名拒收已接受。前輪十二個核准檔已 freeze／索引／本地 commit／ff-only merge，已驗收 master 為 fa6f66fe16cc75c79057fb233871222638f0404a；實際 receipt 留原 task。後續可信讀回與非法停損隔離由下列 M3-P4 有限交付。 | UI 原字串拒收不 POST、draft 保留；helper 在 stringify 前拒非法數字、不 fetch／不改 payload；raw HTTP 422 不改完整列／不新增。零合法，null／省略仍清欄，actual 空白清欄已驗；原 12 列完整 JSON 保持，兩 NEW 僅 memory、自有程序／tab／listener 已清，新測試磁碟產物 0，前輪 HAR 未動。不宣稱十進位 exact、legacy 污染修復、風險行動／所有估值、磁碟重開／正式 DB／production build、新 Plan／risk sizing／完整 M3／PIT。主契約與具名範圍見[UI 文案](UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)，入口見[開發入口](development-baseline/README.md#m3-p3-庫存價值輸入的零落盤驗證入口)。 |
| M3-P4：既有庫存價值可信讀回與非法停損隔離；支援 M3／R2-C1 | M3-P3 輸入基線、三欄 Float 讀取、原 gates／held stop consumer；schema／risk sizing／new Plan 不變。 | 已有限接受並版本封存：九檔程式／五文件已 freeze／五分區索引／正常本地 commit／ff-only merge，原十四列／17 HTTP 與具名操作支持範圍保留，見[主契約](UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)。 | 三態／非法停損隔離有限驗收，不外推污染修復、行情可信或全估值。入口見[開發入口](development-baseline/README.md#m3-p4-庫存價值可信讀回的零落盤驗證入口)，限量清理與 blocked logs 分報見[協作紀錄](TASK_COORDINATION.md)。 |
| M3-P5：可信庫存股數與既有估值／持倉判定一致；支援 M3／R2-C1 | P2 trusted quantity／exact int64、P4 value／stop 信任及原 gates；只接必要 quantity／valuation／held／篩選／計數／優先 consumer，schema／輸入／new Plan／risk sizing 不變。 | 已有限接受並版本封存：十檔實作／五份成果文件已 freeze／五分區索引／正常本地 commit／乾淨 master ff-only merge；原 10 tests／262 router、45 actual HTTP／十六列 SQL 不變與 desktop／390px 結果保留，詳情 badge 退修後才通過。限量外部清理已確認，見[協作紀錄](TASK_COORDINATION.md)。 | 三態、safe 相容／大數 unsupported、gate 優先與 scoped 計數只由[主契約](UI_COPY_SPEC.md#m3-p5-可信庫存股數與既有估值持倉判定一致)負責。新測試產物 0、自有 QA／程序已清；memory 不代真正 disk、正式 DB／行情來源證據／Decimal exact／全部風險行動／完整 M3 未驗，入口見[開發入口](development-baseline/README.md#m3-p5-可信股數與估值持倉判定的零落盤驗證入口)。現行庫存數值隔離／試算見下列 P6a，不倒改 P5 原結果。 |
| M3-P6a：庫存收盤數值隔離與本地試算可檢視；支援 M3／R2-C1 | 可信股數／成本、庫存 SQL 必要投影、close／記錄語法與用途分離。 | 已有限接受並版本封存：七檔實作／五文件已 freeze／五分區索引／正常本地 commit／乾淨 master ff-only merge；原修正版 8 tests／42 router、前端與桌面／390px 收合結果保留，外部清理已核，見[協作紀錄](TASK_COORDINATION.md)。 | local_estimate、展開與舊 API 相容只由[主契約](UI_COPY_SPEC.md#m3-p6a-庫存收盤數值隔離與本地試算可檢視)負責。P6a 原兩次 actions 500 不倒改通過，後續清單範圍見 P6b；來源／日期 unverified、完整行情／官方／live／M1 file gate／正式 DB／磁碟／M3 未驗。入口見[開發入口](development-baseline/README.md#m3-p6a-庫存本地行情與試算的零落盤驗證入口)。 |
| M3-P6b：Actions 清單逐列行情讀回污染隔離；支援 M3／R2-C2 | P6a 的 full ORM 污染缺口；必要 raw 八欄、unlocated date、120 列窗口與 TAIEX 必要投影；原 source／time／purpose、RawPayload／MI_INDEX file gates 與 count scope 保留。 | 已有限接受並版本封存：八檔實作／五文件已 freeze／索引／正常本地 commit／master ff-only merge；原 9 tests／90 router、40 HTTP／24 卡、兩整表不變及真正清單操作保留。自有外部清理及失敗分報見[協作紀錄](TASK_COORDINATION.md)。 | read status、null 價格／空 levels、原 gates／scope 與具名結果只由[主契約](UI_COPY_SPEC.md#m3-p6b-actions-清單逐列行情讀回污染隔離)負責。該輪只驗正常 StockPage 原導航 200，污染詳情未驗，不因 P6c 派工倒改；入口見[開發入口](development-baseline/README.md#m3-p6b-actions-清單行情讀回的零落盤驗證入口)。完整 ActionsPage／M3、正式 DB／磁碟、官方／live／M1 file gate 未驗。 |
| M3-P6c：個股詳情行情讀回污染隔離；支援 M3／R2-C2 | P6b 清單之外的行情 raw 讀回／日期截止／候選窗口與 M1 latest；原來源、用途、時間、raw file gates 與必要 caller 保留。 | 已有限接受並版本封存：十一檔實作／六文件已 freeze／索引／正常 commit／master ff-only merge。原失敗、補驗與程序順序限制分報，外部 owned 資源已清、兩 blocked logs 717 bytes NO-RETRY，見[協作紀錄](TASK_COORDINATION.md)。 | 精確契約與具名操作只由[個股頁 §15](STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)詳述；數量／原始 exit／清理見[開發入口](development-baseline/README.md#m3-p6c-個股詳情行情讀回的零落盤驗證入口)。有效歷史窄版溢出未通過，physical canvas／真正截止表單未驗；正向 file gate、磁碟／正式 DB、production、官方／PIT、完整 M1／M3 未驗，不以 memory 取代，也不列其他餘項全域阻擋。 |
| M3-P6d：個股詳情研究候選讀回污染隔離；支援 M3／R2-C2 | stock-only Signal／StrategyVersion raw 日期／JSON／身份與必要 detail／decision／overview caller；source／time／version 原 gates 保留。 | 已有限接受：九檔實作、必要 direct／actual HTTP／完整 App 讀回及五個桌面 case、四整表／typeof 不變；非字串 status guard 單項退修／必要 pure 補驗亦已接受。自有 QA／程序已清、新產物 0、來源停寫；六文件接受後才 freeze／索引，commit／merge 未執行。 | 20 列窗口與 canonical 全集分開、bad latest 不較早 fallback、unlocated 研究拒用，健康 alternate／正常 observation 保留。精確契約與 native／DOM.click 支持範圍見[個股頁 §16](STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)，原始 exit／數量見[開發入口](development-baseline/README.md#m3-p6d-個股研究候選讀回的零落盤驗證入口)。其他 typed models／legacy Actions／tracking、原 M1 原件／磁碟、官方／PIT、canvas／窄版／表單及完整 M3 未驗。 |
| M3-P6e：個股其他 typed 獨立區塊讀回隔離（FeatureSnapshot／Chip）；支援 M3／R2-C2 | P6d 未納入的 typed caller／processor 及 source／time 有界 audit，或經核定可交付的未完成能力；詳細選題由[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)負責。 | 下一具名候選，尚未派實作；本輪接受／合併後由下一 NEW 統籌／worktree 先核必要依賴與最小能力，不預設修法。 | 核定具體欄位／scope／gates 與零落盤 actual API／App 完成條件後才交付；audit 本身、序列化 catch 或 mock 不當能力完成，不降低來源／原件／磁碟與 inherited 未驗條件。 |

前輪 M1 審查沒有來源／功能變更，不追認能力交付；來源候選與既有單日證據的詳細限制見[來源 §10](SOURCE_REGISTRY.md#10-m1-後續依賴審查來源候選與等待邊界)。上述依賴等待只適用該次 M1 選題與既有授權範圍，本身不標使用者暫停，也不推論其他餘項永久受阻。最近 M2-P2 已有限交付並版本封存；其後的停止要求曾由獨立模型維護保留，本次使用者已明確恢復。M1-P4a 有界審查已接受，來源未准入，等待精確證據，不增加能力完成度；本輪角色已依 [AGENTS 的配置](../AGENTS.md#四個角色) 核對，實際 roster、接手與範圍見[協作紀錄](TASK_COORDINATION.md)。

子能力驗收不取代 R0／R1 的完整資料驗收或 R2-E1 的整合、build、backend 與瀏覽器關鍵流程。必要基礎批次須列支援里程碑與解除的依賴，拆工及續作依 [AGENTS](../AGENTS.md#每輪流程)。

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
| R0-B2／B2-persist | 四個小批、bridge A、B adapter、selected bar 與 prior volumes 本地 metadata 接線已有限 review；獨立 selected-bar verifier 有程式與純記憶體案例的有限 review；整體未完成 | R0-A1、G-ID | B 只接受 opt-in capture→detached canonical candidate；caller 明示 current snapshot path／SHA、exact attempt／ordinal 與新研究 aware decision，保存另由 caller 明示 attempt／run。Capture v2 封存 selected bar close／volume；v3 封存實際 prior volumes 最多 20 筆有序本地列與 raw metadata。獨立 `verify_selected_bar_evidence` 對 caller 指定的 snapshot、v2／v3 selected call、raw FK 所指 `body.bin`／同目錄 `receipt.json` 及外部 receipt／registry pins 回 detached `local_evidence_consistent`，只證當次本地 selected-bar 證據一致；不改 bridge 的 `bytes_unverified` 或升格 prior volumes。真實檔案／SQLite snapshot／零寫入整合未驗；完整已授權 tuple 或 pins 尚缺，依賴未變前保持待驗，不重複搜尋或建附件／fixture。70 個既有案例未跑，pytest／必要磁碟驗證受原輪落盤配額所限；見[協作紀錄](TASK_COORDINATION.md)。歷史原件／上游版本、availability／歷史決策／PIT、其餘衍生輸入仍未證；consumer、同 snapshot paired replay 及產品選版仍缺。API 與拒絕條件見 [Artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。 |
| R0-B3／C-002 | 已 review（純核心） | 無 I/O | Wilder ATR及strict caller inputs；未接官方來源或worker。 |
| R0-B4／B3-persist | 已 review（局部） | R0-A1、G-ID、R0-B3 | Immutable ATR store、精確雙唯讀比較及 schema1／v2 相容邊界；不相容輸出不可比，官方來源／PIT／worker 接線仍缺。完整支援與拒絕條件見 [R0](R0_IMPLEMENTATION.md)。 |
| R0-B5／B3-wire | 提案 | R0-B4、G-TIME、G-SOURCE | 官方session／halt／公司行動／previous-close均有raw／版本／availability；缺來源reason code fail closed，worker explicit opt-in讀artifact，預設候選不切換。 |

### R0-C：價位、時間與 paired replay

| ID | 狀態 | 依賴 | 完成條件／目前邊界 |
| --- | --- | --- | --- |
| R0-C1／B4a | 已 review（read-time） | G-ID | signal-level-semantics/v1涵蓋signal／action／stock／tracking及UI；僅canonical兩個v1策略推導legacy-risk-levels/v1，未知identity／basis／歷史時間fail closed。持倉與成交價不當規則價，原v1數值不改。 |
| R0-C2／B4b | caller-input 純核心已有限 review；完整 B4b 未完成 | R0-C1、G-PRODUCT | `calculate_trade_plan` 以 `caller-trade-plan/v1`／`caller-execution/v1` 對盤後 long 假設作嚴格輸入、單一 caller tick、保守捨入、gap／成本／流動性／停牌及事件／到期判定；完整 session 的 stop／target 順序未知回不可比。結果明示 `post_session_hypothetical`、PIT／成交未主張，觸價只是觀察。官方 tick／費稅／日曆、來源與 availability／PIT、合法交易時段、持久化、worker／API／UI、完整 legacy replay 及逐欄 paired comparison 仍待驗；見 [R0 實作 §6.2](R0_IMPLEMENTATION.md#62-新交易計畫的隔離邊界)。 |
| R0-C3／B5a | 已 review（兩個分離小批） | R0-A1、G-TIME | time-evidence/v1 caller store與product-time/v1 API/UI projection已review，但未有persisted linkage；unknown呈現不是execution gate。 |
| R0-C4／B5b | caller-declared time-cutoff 純核心已有限 review；完整 B5b 未完成 | R0-C3、G-TIME、G-SOURCE | `caller-availability-cutoff/v1` 對 caller 明示的必要輸入與 `time-evidence/v1` 作 ID／subject／source／snapshot／revision identity 精確配對；已知精確 `first_available_at<=decision_at`，revision 另驗 `revision_available_at`，live 另驗 `collected_at`，均以 UTC 比較且相等可通過。unknown／date-only／粗精度／naive fail closed，逐輸入給 reason。`required_inputs_completeness=caller_declared_only`，availability truth／PIT 均 `not_asserted`。尚缺實際完整依賴、來源真實性、store／worker／產品接線、歷史決策與合法 execution gate；T+2 修訂、回補及 B7 同 snapshot 比較仍須整合驗收。詳見 [R0 實作 §7.3](R0_IMPLEMENTATION.md#73-r0-c4b5b-caller-declared-time-cutoff-純核心有限-review)。 |
| R0-C5／B7 | 提案 | R0-B2／B5、R0-C2／C4 | 同一唯讀snapshot產隔離legacy／new；比較ATR、狀態、confidence、價位、availability、migration及不可比。重現成功、缺資料、gap、公司行動、legacy confidence、盤後與修訂案例。 |
| R0-C6 | 等待 | R0-C5 review | 各R0項按已review範圍更新；研究／預設切換另決策。R0-5可依B6獨立更新，不能因純核心／schema／fixture將整體標完成。 |

## 4. R1：可靠資料與事件

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R1-A1 | 已 review（局部）；整體未完成 | G-SOURCE；來源可行性可先行，實際 as-of 接線才依賴 R0-C4。 | 原 snapshot 四來源 registry／capture、兩個磁碟 consumer 及窄修正已有限 review；另 TWT48U selected 事件／本次 feed 記憶體摘要、explicit TPEx 日法人來源准入與單日 selected 摘要已有限 review。其餘 collector、公司行動／停復牌、授權、時間／修訂／歷史與 PIT 仍待驗，具名範圍見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。 |
| R1-A2 | 提案（既有子批及指定 legacy 成交量磁碟整合各有限接受；成交量精確呈現有限接受，整體未完成） | 本批採用的 R1-A1 來源；官方行情／TAIEX／法人／融資逐域驗證。 | TAIEX exchange identity 與成交額狀態保存／使用已有限接受，保留單一離線缺額／明確零 capture→SQLite→API 的原範圍；兩條 migration 路徑各四個可重建 synthetic fixture 磁碟案例已有限接受並提交／合併，支持關閉後讀回與指定失敗復原，精確限度見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-legacy-成交額-migration-磁碟驗收有限接受)。指定三種 selected invalid／四類拒收的 production capture→collect→磁碟重開→API 整合已有限接受並提交／合併，第三次實測 1 compound unittest／0 skip、十一個 HTTP 回應及測試／清理成功，精確限度見[資料來源](DATA_SOURCES.md#r1-a2-selected-invalid拒收磁碟整合有限接受)。更早 legacy TWSE／TPEx 精確整數 gate／TPEx 空結果條件的 parser／wrapper／adapter fixture 已有限接受並提交／合併，精確格式見[資料來源](DATA_SOURCES.md#r1-a2-legacy-日行情成交量精確整數-gate有限接受)。前輪 legacy gate→capture／collect／SQLite／reopen／API 指定磁碟整合已有限接受並提交／合併：首次實際磁碟測試 1 compound unittest／0 skip、兩次 force collect 與 60 個 HTTP 回應通過，test／cleanup／process exit 0、核定根已清；六個合法零／大整數、24 個拒收與第二次全 invalid 保留的精確限度見[資料來源](DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)，入口副作用／配額見[開發入口](development-baseline/README.md#r1-a2-legacy-成交量的磁碟整合驗證入口)。本輪指定 browser 精確呈現已有限接受，具名條件見本文件 §2.1 及[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)；其他未覆蓋 invalid／拒收、正式 DB、真官方／live 與完整 backend 仍待驗。完整驗收仍須以 exchange＋symbol＋session＋欄位用途產具名 coverage，單位／identity 不混用且 raw 可追溯；缺值不當有效零，合成或截斷數值不當可用欄位，fixture 不證真實來源、歷史完整性或 PIT。 |
| R1-A3 | 提案 | R1-A1、R0-B5；公司行動與停復牌。 | raw／adjusted basis、因子、版本、可得時間與 applied-through 可重建；TWSE／TPEx 覆蓋分開；不足時 ATR／tracking fail-closed。 |
| R1-B1 | 提案 | 本批採用的 R1-A1 來源與時間／版本證據；實際 as-of gate 接線依 R0-C4 必要輸入。 | unknown time、date conflict、backfill、revision／withdrawal、feed-only URL、無內文均有案例；排序與 cursor 綁 snapshot／version；無可信時間者不搶占「最新」。 |
| R1-B2 | 提案 | R1-B1；同事件 grouping 與 new-information。 | 同源與跨源 dedupe 可重跑，保留每篇來源；首次／補充／更正／撤回分開；負面或轉載不增加正向催化；所有摘要回指合法原文。 |
| R1-B3 | 提案／可能受限 | R1-A1、G-SOURCE；免費官方 macro／可信媒體可行性。 | 每個候選以實際抓取、時間、保存／摘要權利與穩定性驗證；沒有可接受來源就記 `受限`，不以搜尋摘要或模型記憶補內文。 |
| R1-C1 | 提案；R16／17、R35–38 的身分小批已有限 review | 本批分類來源、版本與期間；採用事件形成題材時才需 R1-B2。正式分類修復依自身資料與驗收，不加無關 capture 工作作前置。 | 產業／題材分層及有來源、版本、期間的 membership。成員報酬、candidate 決策、backfill 納入及 public 展示各有有限成果，語意不得互換；正式分類與歷史 PIT／回算未完成。精確規則見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。 |
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
| R2-A2 | 已 review（局部） | 已准入且本批採用的事件／基本面來源；缺少或受限的面向可先明確為 unknown，不阻塞不依賴它的交易位置與持倉風險。 | M1-P1 具名範圍見 §2.1／[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)，整體未完成；完整驗收仍要求公司品質、事件機會、交易位置、持倉風險分開，矛盾可同時呈現，不硬湊單一「好股分數」，也不把 unknown 補 0。 |
| R2-B1 | 提案 | R0-C2、G-PRODUCT；trade-plan schema 與純計算。 | 觸發／確認、進場區間、不追價、失效、目標／移動停利、時間／事件失效、成本、tick、流動性、期限與版本俱全；無合法計畫可輸出不交易。 |
| R2-B2 | 提案 | R2-B1；執行與 lifecycle。 | 未觸發、到期、rejected_gap、無法成交、模擬成交、實際成交、退出與 incomparable 分開；stop 不保證成交；同日 stop／target 無順序不偏向有利結果。 |
| R2-C1 | 提案 | R2-B1、G-PRODUCT；部位與曝險。 | 使用精確股數；單筆／單股／同題材風險可追溯；同股多策略／多題材不重複占用；風險預算未知時不給張數。 |
| R2-C2 | 已 review（P6b 清單有限）；整體未完成 | R2-A2、R2-C1；行動摘要，P6b 具名範圍見 §2.1。 | 同 exchange＋symbol＋as_of 一張卡；產品 A–E 合併矩陣全覆蓋；已驗證持倉風險優先，完整 observation 不被誤標資料待補。P6b 清單隔離不代污染個股詳情、完整 ActionsPage 或整合驗收。 |
| R2-D1 | 已 review（局部） | 本批已完成的 R2-A／B／C 能力；受限來源對應區塊顯示 unavailable，不延伸成假資料。 | M1-P1 具名範圍見 §2.1／[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)，整體未完成；完整驗收仍要求 `/news`、`/themes`、`/stocks`、`/actions` 的已接能力使用同版本與時間，中文標籤、來源、未知、單位與價位語意一致，診斷/raw 預設收合。 |
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
