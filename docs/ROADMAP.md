# 開發路線與目前能力

更新：2026-10-07。優先順序與產品範圍由本文件管理；工作 ID／完成條件見[執行清單](ROADMAP_EXECUTION.md)，角色、停滯紀錄與接手狀態見[協作紀錄](TASK_COORDINATION.md)。

## 目前進度（含產品有限核對與 R1-A2 磁碟驗收）

**R0–R3、完整 M1／M2／M3 均未完成。** 已驗收子能力只適用具名市場、標的、日期與操作，不換算產品完成百分比。

| 階段 | 已驗收範圍 | 未完成核心 |
| --- | --- | --- |
| R0：研究基準與時間 | ATR 純核心／獨立保存、有限 migration／startup、artifact／比較／replay／capture、Bridge B 本地 metadata、獨立 selected-bar verifier、B4b／B5b caller-input 純核心。 | 真實檔案／snapshot verifier 整合與待跑回歸、完整歷史原件／來源／availability、ATR worker、產品保存與時間接線、官方 tick／費稅／日曆、PIT、新舊同 snapshot 比較及選版。 |
| R1：可靠資料與事件 |官方行情／法人／融資收集與回補；指定來源准入及 consumer、TAIEX 身分與成交額狀態、指定 synthetic 磁碟／精確整數案例、產業期間與停復牌／公司行動局部修正；W8兩股27日CSV／完整有界交易日及八截止96 net窗口計算。 新explicit10/06兩股完整24觀測日曆／20真daily及5／20日net。 | 範圍外真實逐市場／逐欄 coverage、多日法人與完整交易日、時間／修訂、完整事件與公司行動、正式 DB 升級／分類修復、其他股數精度、當沖／借券／分點／必要基本面。 |
| R2：候選與交易計畫 |v1候選、行動摘要、持倉、個股頁；W8有限法人窗口／具名操作、M1單日價量、M2官方事件及精確張／O-C／成交額／振幅四理由；普通TPEx支援6→7、七股actual API及可信桌面／窄版五條件往返有限接受；既有庫存精確保存／讀回隔離。 新explicit10/06兩股完整24觀測日曆／20真daily及5／20日net。 | 範圍外M1法人／歷史研究、M2其他來源與分類品質、完整ActionsPage、新Plan保存及觸發／成交／退出、部位／題材曝險及整合驗收。 |
| R3：AI 與有效性 | 固定規則、既有追蹤與回測、研究規格。 | 預先定義目標／採用門檻、樣本外／校準、walk-forward、前瞻樣本及模型採用；沒有經驗收 AI 預測或勝率。 |

W8已有限接受TPEx3105／6488、2026-09-21／09-22／09-23／09-24／09-29／09-30／10-01／10-02八截止5／20日法人來源／缺日、96 net actual API及16組具名可信native與owned服務清理，見[個股頁 §24](STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯)。範圍外仍unavailable，突破／回踩固定保守；補資料或Signal不自動啟用trend／研究條件，完整M1未完成。

UNIT-LOTS-1台股數量主值／輸入前置已有限接受：日常張值、精確零股／原股稽核，DB／API／來源仍canonical股，價格／成本仍元／股；見[UI §10.3](UI_COPY_SPEC.md#103-張零股)／[個股頁 §7.1](STOCK_RESEARCH_PAGE.md#71-unit-lots-1-日常張數與原股稽核有限接受)。本前置1批、core0／dep0、當時stall1；M1後必要UNIT兼容回歸current26src及原斷言已核，原24src收據保留，見[開發入口](development-baseline/README.md#unit-lots-1-台股張數前置的記憶體驗證入口)。

M1-PRICE-1已有限接受TPEx3105／6488、2026-10-05真單日價量、唯一production capture、actual API、headline／chart／面板及具名trusted桌面／窄版；切股／GET／重複POST同cache零新增外網，default／explicit10/02不滲10/05。core+1／dep+1、stall0；source／操作／保存界線見[來源 §20](SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)／[個股頁 §25](STOCK_RESEARCH_PAGE.md#25-m1-price-1上櫃兩股單日價量閉環有限接受)。Loader／validator與必要回歸屬同批；完整M1及趨勢／研究條件未完成。

M2-FOCUS-LOTS-1已有限接受選定2026-10-05、TPEx3105／6488的精確成交張數理由與同cutoff往返；20,000張只3105、10,000張兩股、50,000張真零與10/02unavailable／countnull已核，返回保留原as_of／min_lots字串。core+1／dep0／reliability0／stall0；wrap退修含同批，詳見[個股頁 §26](STOCK_RESEARCH_PAGE.md#26-m2-focus-lots-1精確成交張數關注與同截止往返有限接受)。10/05是來源日，不是10/06今日即時資料、前日漲跌、PIT或完整M2。

M2-FOCUS-DAY-MOVE-1已有限接受同兩股／10/05的精確張門檻＋單日O/C方向；10k全部兩股／收高3105／收低6488／平收真零、精確邊界與unavailable均核。兩來源理由去重、同cutoff研究及返回門檻尾零／方向的桌面／窄版具名操作已接受。core+1／dep0／reliability0／stall0；當輪 `price-lot-focus/m2-v2` 見[個股頁 §27](STOCK_RESEARCH_PAGE.md#27-m2-focus-day-move-1單日方向關注與完整條件往返有限接受)，新觀測見[來源 §20.5](SOURCE_REGISTRY.md#205-m2-focus-day-move-1-同來源的新觀測與方向-consumer)。仍非前日漲跌、趨勢／PIT或完整M2。

M2-FOCUS-TURNOVER-1已有限接受同兩股／10/05的精確TWD成交額條件：10k張／all配25,000,000,000元只3105、20,000,000,000元兩股、down配25,000,000,000元真零；兩股等額／加1元及int64邊界、10/02未知、三理由與四條件具名往返已核。當時 `price-lot-focus/m2-v3`，core+1／dep0／reliability0／stall0；wrap退修同批，契約見[個股頁 §28](STOCK_RESEARCH_PAGE.md#28-m2-focus-turnover-1精確成交金額與四條件往返有限接受)，新觀測見[來源 §20.6](SOURCE_REGISTRY.md#206-m2-focus-turnover-1-同來源的新觀測與成交額-consumer)。原件只memory且owned服務已清，不稱完整M1／M2或PIT。

M2-FOCUS-DAY-RANGE-1已有限接受新10/06來源准入、actual API及可信桌面／窄版操作，consumer `price-lot-focus/m2-v4`：本日精確振幅配既有張／O-C／成交額，四理由、五原條件同截止safe往返；6.000只6488、10真零、精確邊界及缺資料≠0已核。core+1／dep+1／reliability0／stall0；四owned pages已關、兩RAM服務及compiler已停止，held原件memory釋放；最後額外invalid fallback click未送達，不稱該case已通。詳見[個股頁 §29](STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返)／[來源 §20.7](SOURCE_REGISTRY.md#207-m2-focus-day-range-1新日期來源准入與本日振幅-consumer)。

前輪M1-PRICE-SAVE-1-B1 source13＋DOC8／freeze21、qualified索引、exact commit及正常另准ff-only master merge `c1388b1cbb247dd0a015c1062b5aad14ef6ce057`已接受，為本輪starting／current／master HEAD；coreoperation+1／necessary dep+1／reliability0／stall0。私人三檔NO-RETRY與missing-file UI未跑仍保持，詳[開發入口](development-baseline/README.md#m1-price-save-1-私人磁碟保存與新程序驗證入口)。

籌碼三區：三大法人已有資料；主力進出與券商分點的匯入、統計、排行、歷史及更新待做。免費官方人工查詢入口不是已接資料集，定義見[個股頁 §8](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)。

### 接下來的順序：近期產品里程碑

使用流程：**今日關注 → 個股研究 → 條件計畫 → 追蹤回看**。建置順序：**M1 個股研究 → M2 今日關注串個股 → M3 條件計畫與追蹤**。沿用五個主導航與既有量化契約；每批只核對所採能力需要的依賴。

| 里程碑 | 完成後的使用者操作 | 完成條件 |
| --- | --- | --- |
| M1 個股研究總覽 | 在同一研究截止查看價格、5／20 交易日外資／投信／自營商各別淨買賣超、趨勢、新聞／官方事件及研究條件。 | 統籌核定窗口、交易日／缺日判準、來源、分類與規則版本；數值回指真實來源，成立／未成立／資料不足有真實原因。保留各資料日期及發布／事件時間，不補零、跨策略拼價位或推論事件影響。列支援市場／標的／日期及未支援區塊；全屏 placeholder 不算交付。 |
| M2 今日關注串個股 | 查看可追溯關注理由，同股去重後進入 M1，再返回原條件。 | 每項理由有已驗收來源、時間與版本；零候選和來源不足可區分。分類未核實不作可信排名，不為湊名單補候選。 |
| M3 條件計畫與追蹤 | 保存並讀回版本化計畫，操作觸發、到期、未成交、模擬成交與退出。 | 逐子能力滿足來源、時間、版本、官方 tick／費稅、合法時段及必要執行 gate；磁碟保存／跨程序讀回驗收。未知風險預算不給張數，觸價不當成交，legacy tracking 不代新計畫生命週期。B4／B5／B7 與預設切換 gate 保留。 |

**前輪M2-FOCUS-STOCK-SCOPE-1已有限接受普通TPEx支援2→3。** 3105穩懋／5347世界／6488環球晶在2026-10-06來源日具名計算／API及可信桌面／窄版往返；consumer `price-lot-focus/m2-v5`，四理由、code順、同cutoff五原條件返回，core+1／selected identity-source scope dependency+1／reliability0／stall0。新三股policy／body與explicit舊兩股immutable tuples分開；金融／來源由[§21](SOURCE_REGISTRY.md#21-m2-focus-stock-scope-1三股來源准入)管理，操作由[個股頁 §30](STOCK_RESEARCH_PAGE.md#30-m2-focus-stock-scope-1三股關注與同截止往返)管理。完整M1／M2／M3仍未完成。

M1-CLOSE-RESOURCE-1單日觀測與前輪M2-FOCUS-STOCK-SCOPE-2四股 `.2`／m2-v6依原範圍已接受並合併 `899fa62260e495075cc756ff31869a57df6b3895`，來源與操作留[§22～23](SOURCE_REGISTRY.md#22-m1-close-resource-1有界單日-json-觀測)／[個股頁 §31](STOCK_RESEARCH_PAGE.md#31-m2-focus-stock-scope-2四股關注與同截止往返)。前輪M1-HISTORY-QUERY-1-METADATA-1找到官方stock-pricing／tradingStock月查詢NEW線索，但exact M wire與歷史自動用途仍未准入，歷史金融body GET0，core0／dep0、不是implementation batch，stall0保持；詳見[來源 §24](SOURCE_REGISTRY.md#24-m1-history-query-1官方月查詢線索與准入缺口)。

前輪M2-FOCUS-STOCK-SCOPE-3-B1已合併：普通TPEx支援4→5新增3293鈊象，五股10/06四理由／五條件actual API10案及可信desktop1277×924／窄版390×844往返已有限接受。`.3`／m2-v7與explicit舊tuples分開；coreoperation+1／selected identity-source scope dependency+1／reliability0／stall0。當輪金融CSV GET3與final non-preloaded worker1、原失敗界線由[來源 §25](SOURCE_REGISTRY.md#25-m2-focus-stock-scope-3五股來源准入)管理，操作見[個股頁 §32](STOCK_RESEARCH_PAGE.md#32-m2-focus-stock-scope-3五股關注與同截止往返)。Owned page／服務／compiler／observer清理與source12＋DOC8／freeze20／qualified索引／正常ff-only merge已接受。

前輪`M1-HISTORY-MONTH-WIRE-1-DISCOVERY-1`支持Gregorian YYYY/MM/01的primary-script wire推論與export GET／JSON POST方法，沒有server／historical finance／automated-use准入。本輪`M1-HISTORY-OPEN-DATA-LINK-1`再核REST11371 daily-only及suggest136936完整reply history，exact月資源用途仍缺；core0／dep0、非implementation batch、stall0保持。新證據與guide原失敗／masked帳號未證邊界見[來源 §28](SOURCE_REGISTRY.md#28-m1-history-open-data-link-1開放平台metadata與歷史用途缺口)，不作全域不可能主張。

前輪`M2-FOCUS-STOCK-SCOPE-4-B1`普通TPEx5→6新增8069來源／API／可信操作及版本封存已接受；本輪獨立正面核心`M2-FOCUS-STOCK-SCOPE-5-B1`支援6→7新增6510精測。七股10/06四理由／五原條件、actual API10案與可信desktop1277×924／窄版390×844往返、精確inclusive邊界及真零／恢復已核。新`.5`／m2-v9與explicit舊tuples分開；coreoperation+1／selected identity-source-date-policy dependency+1／reliability0／stall0。當輪financial GET2，final post-edit native firstload觸發NEW worker1／Store1／preloadedfalse；金融由[來源 §29](SOURCE_REGISTRY.md#29-m2-focus-stock-scope-5七股來源准入)、具名操作由[個股頁 §34](STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)管理。Owned清理已接受，完整M1／M2／M3未完成。

`M1-PRICE-SAVE-1-B1`有限接受七股10/06完整raw／兩canonical receipt私人保存、NEW empty Store reader及actual API／UI；`.1`獨立storage grant，`.5`memory事實不改，captured／saved time非publication／PIT。來源與操作見[§30](SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)／[個股頁 §35](STOCK_RESEARCH_PAGE.md#35-m1-price-save-1私人單日保存與跨程序操作)。Actual missing-file UI未跑，清理拒絕與功能驗收分報。

前輪 `M1-CHIPS-CUTOFF-1006-1-B1`已有限接受並正常commit／另准ff-only master merge `fc4a35b67535a7d21b1bba080f799ac6ad46529f`；source10＋DOC8／freeze18、qualified七分區與原task收據已接受。新來源用途／完整24 observed calendar／20真daily、同10/06兩股12net與可信操作按[來源 §31](SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)／[個股頁 §36](STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)原範圍保持；coreoperation+1／necessary dep+1／reliability0／stall0，memory raw已釋放。

`M1-SAVED-PRICE-FOCUS-1006-1-B1`已有限接受：七股10/06既有private來源精確四條件篩選→saved detail→五原字串返回；NEW empty Store／memorydisabled，current metadata／financial GET0、新diskwrites0／DBmut0。Coreoperation+1／necessary derived saved-source readonly-use dependency+1／reliability0／stall0；完整原件／新consumer pins由[來源 §32](SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)管理，actual API／可信desktop窄版及focus/detail502清值見[個股頁 §37](STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)。本地版本封存／另准master merge已接受，清理fences不變。

`M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1-B1` 已有限接受NEW guarded API／preview：四卡saved-focus→3105／6488同explicit10/06 saved OHLC＋真5／20net→追溯／五RAW條件back；fresh22、同token502清兩來源與owned runtime退出已核，coreoperation+1／necessary joint-source-use-guard dep+1／reliability0／stall0。四舊policies獨立，price financialGET0／外部來源metadataGET0／new product disk0；私人三檔仍在、missing-file UI未跑。來源與操作見[§33](SOURCE_REGISTRY.md#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口)／[個股頁 §38](STOCK_RESEARCH_PAGE.md#38-m1-saved-price-chips-integration-1006-1共同入口與同截止往返)；本地版本封存／master合併已由原task接受，原有限範圍保持。

本輪 `M1-SAVED-PRICE-CHIPS-FOCUS-1006-1-B1` 已實作八條件入口／guarded consumer，但只actual unavailable受驗：首次Oct index含10/7超出immutable10/6scope，indexGET2／1502B、dailyGET0，沒有本輪12net。七price完整亦不把缺chips轉成count0；matching／verifiedzero／jointdetail／八RAWback／負門檻actual未驗。Coreoperation0／dependency0／reliability0／stall1（前0）；來源與操作由[來源 §34](SOURCE_REGISTRY.md#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口)／[個股頁 §39](STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界)管理，DOC review／freeze／qualified索引／Git待。下一conditional `M2-FOCUS-STOCK-SCOPE-6-B1` 尚未准入：fresh ordinary第8股identity／實際date／scope/profile/use與可能新versioned日期guard須GET前核，current worker只fixed10/5+10/6／latest.5七股；不承諾新wire日期、不擴private7／joint2或重試本failedproducer。完整ROADMAP仍未完成。

M1-W9已封存，只有bootstrap／接手、沒有implementation batch；原「新增9/18第九cutoff／108 net」只是未實作歷史候選，不機械續作。歷史W8真8/25／27日曆／96 net仍按已驗範圍有效。下一題與跨輪計數依[AGENTS](../AGENTS.md#核心選題與進度判定)，不因文件／索引／Git歸零。

| 核心路徑 | 目前缺口 | 下一步與驗收 |
| --- | --- | --- |
| M1 資料證據 | W8及新explicit10/06兩股用途／24觀測日曆／20真daily依賴已解除；範圍外、PIT／修訂／TWSE用途仍缺。 | 只按已驗exact集合／新版本使用；缺列不推休市，權威見[來源 §31](SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)。 |
| M1 計算與接線 | W8／兩股10/06真5／20net、七股saved focus及前輪共同入口有限接受；本批八條件seam只unavailable受驗，正向filter／真零／jointdetail／八RAWback與本輪完整日曆／20daily仍缺。 | [來源 §34](SOURCE_REGISTRY.md#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口)／[個股頁 §39](STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界)管理新缺口；calendar替代須另准fresh parser/schema/policy/use，不retry原failedproducer。普通20／21stock closes／trend／strategy inputs／membership／time／execution仍缺。 |
| M2 關注理由 | 七股memory／saved四理由與五RAW往返有限接受；兩股新institutional filter尚缺正向actual驗收，分類品質／範圍外仍待。 | ordinary第8股為conditional fallback：須fresh identity／觀測date／來源用途／新日期scopeguard及actual API/native，既有private七股及joint兩股pins不擴張；見[個股頁 §39](STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界)，候選未准入。 |
| M3 計畫操作 | caller-input 純核心已驗，實際來源／時間與新 Plan 產品保存未接。 | 具名列最小操作、真實資料及其必要 gate；滿足後接保存、API、UI 與追蹤。未滿足項列解除條件，不以 unknown 顯示代替必要條件。 |

R0–R3 是完整資料、技術與驗收分層，不要求先清完全部基線才交付獨立核心操作。R0-B2 不是全域第一主題；其 snapshot／body／receipt／registry pins tuple 未齊，保持待驗，不重複搜尋或建 fixture 冒稱接入。[Artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果) 管理精確缺口。

## 已接受成果的查閱位置

| 子能力 | 已接受範圍 | 權威契約 |
| --- | --- | --- |
| M1-P1 | TWSE 1101／2330、2026-10-01 單日價格六欄、截止／來源總覽與具名桌面／窄版操作；資料日期篩選不是 PIT。 | [個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽) |
| M1-P2a／P2b | TPEx 3105／6488、2026-10-02 單日法人來源／摘要、原件→API 二十個數值與總覽操作；不包含多日或完整日曆。 | [來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)、[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線) |
| M1-W1 | TPEx 3105／6488、2026-10-02 截止的20日真 CSV／完整有界22開市日及5／20日精確淨超計算；依賴解除，不含 API／UI、研究條件或 PIT。 | [來源 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日) |
| M1-W2 | 同兩股／單截止的5／20日三類 net、來源／缺日／原列追溯及具名操作；首次新取得、GET 零外網，非保存／PIT。 | [個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯) |
| M1-W3 | 同兩股新增9/30／10/1並保留10/2，36 net及三截止 native切換／來源／缺日查看；24原件 process memory，非保存／PIT。 | [來源 §14](SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)、[個股頁 §19](STOCK_RESEARCH_PAGE.md#19-m1-w3三截止法人窗口與原件追溯) |
| M1-W4 | 同兩股新增9/29並切四截止的48 net／actual API／可信原生表單已有限接受；26原件memory，服務清理已核，非PIT／保存。 | [來源 §15](SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)、[個股頁 §20](STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯) |
| M1-W5 | 同兩股新增9/24並切五截止60 net／actual API／可信原生表單、來源／新8/28原列與拒用已有限接受；27原件memory、服務已核清，非PIT／保存。 | [來源 §16](SOURCE_REGISTRY.md#16-m1-w5五截止法人來源與完整有界日曆)、[個股頁 §21](STOCK_RESEARCH_PAGE.md#21-m1-w5五截止法人窗口與原件追溯) |
| M1-W6 | 同兩股新增9/23、六截止72 net／actual API已有限接受；新8/27 daily／25日曆／28原件memory，具名可信native／服務已核清，非PIT／保存。 | [來源 §17](SOURCE_REGISTRY.md#17-m1-w6六截止法人來源與完整有界日曆)、[個股頁 §22](STOCK_RESEARCH_PAGE.md#22-m1-w6六截止法人窗口與原件追溯) |
| M1-W7 | 同兩股新增9/22、七截止84 net／actual API與14具名可信native已有限接受；新8/26 daily／26日曆／29原件memory，全部29 receipt SHA獨算、owned服務已核清，非PIT／保存。 | [來源 §18](SOURCE_REGISTRY.md#18-m1-w7七截止法人來源與完整有界日曆)、[個股頁 §23](STOCK_RESEARCH_PAGE.md#23-m1-w7七截止法人窗口與原件追溯) |
| M1-W8 | 同兩股新增9/21、八截止96 net／actual API與16具名可信native已有限接受；真8/25 daily／27日曆／30原件memory、全部30 body及canonical receipt SHA獨算、owned服務清理已核，非PIT／保存。 | [來源 §19](SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)、[個股頁 §24](STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯) |
| M1-P3a／P3b | TWT48U selected 0056（ETF）／1449／1463 四欄、追溯與總覽操作；發布／首次可得 unknown，未保存 live 原件。 | [來源 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)、[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線) |
| M2-P1／P2 | 2026-10-03 真原件 58 列／58 股的官方事件清單、搜尋與研究往返；測試 catalogue 只有三檔可連 M1，其餘 55 股無連結。 | [個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)、[§13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返) |
| M2-FOCUS-LOTS-1 | TPEx3105／6488、明選10/05與精確成交張門檻；真候選／零候選／來源不足分清，同cutoff個股往返及原字串保留。 | [個股頁 §26](STOCK_RESEARCH_PAGE.md#26-m2-focus-lots-1精確成交張數關注與同截止往返有限接受) |
| M2-FOCUS-DAY-MOVE-1 | 同兩股／10/05、精確張門檻＋全部／收高／收低／平收，actual API與具名桌面／窄版往返保留日期／尾零／方向。 | [個股頁 §27](STOCK_RESEARCH_PAGE.md#27-m2-focus-day-move-1單日方向關注與完整條件往返有限接受) |
| M2-FOCUS-TURNOVER-1 | 同兩股／10/05、精確張門檻＋O/C＋TWD整數元成交額三理由，actual API與具名桌面／窄版同cutoff往返保留日期／張尾零／方向／金額四條件。 | [個股頁 §28](STOCK_RESEARCH_PAGE.md#28-m2-focus-turnover-1精確成交金額與四條件往返有限接受) |
| M2-FOCUS-DAY-RANGE-1 | 新10/06兩股精確振幅四理由／五條件可信往返有限接受，core+1／dep+1／reliability0／stall0；已正式合併 `2cbd4e1`，舊profile NO-RETRY保留。 | [個股頁 §29](STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返) |
| M2-FOCUS-STOCK-SCOPE-1 | 新5347普通股身分／scope與來源版本准入，三股計算／API及可信桌面／窄版samecutoff五原條件往返有限接受；core+1／dep+1／reliability0／stall0，owned清理已核，freeze／qualified索引／本地master合併 `50c228d` 已接受。 | [來源 §21](SOURCE_REGISTRY.md#21-m2-focus-stock-scope-1三股來源准入)、[個股頁 §30](STOCK_RESEARCH_PAGE.md#30-m2-focus-stock-scope-1三股關注與同截止往返) |
| M2-FOCUS-STOCK-SCOPE-2-B1 | 新5274與四股 `.2`／m2-v6來源／API／可信往返有限接受，core+1／dep+1／reliability0／stall0；source13＋DOC8 freeze21／qualified索引／exact commit與正常ff-only master merge `899fa622` 已接受。 | [來源 §23](SOURCE_REGISTRY.md#23-m2-focus-stock-scope-2四股來源准入)、[個股頁 §31](STOCK_RESEARCH_PAGE.md#31-m2-focus-stock-scope-2四股關注與同截止往返) |
| M1-HISTORY-QUERY-1-METADATA-1 | NEW官方月查詢primary metadata有限review；exact M wire／歷史自動用途未准入，歷史body GET0、core0／dep0、不計核心批次。 | [來源 §24](SOURCE_REGISTRY.md#24-m1-history-query-1官方月查詢線索與准入缺口) |
| M2-FOCUS-STOCK-SCOPE-3-B1 | 五股`.3` source12／actual API10案／可信往返有限接受，core+1／dep+1／reliability0／stall0；source12＋DOC8／freeze20／qualified七分區索引及正常ff-only local master merge已接受。 | [來源 §25](SOURCE_REGISTRY.md#25-m2-focus-stock-scope-3五股來源准入)、[個股頁 §32](STOCK_RESEARCH_PAGE.md#32-m2-focus-stock-scope-3五股關注與同截止往返) |
| M2-FOCUS-STOCK-SCOPE-4-B1 | 六股`.4`來源／操作有限接受；source13＋DOC8／freeze21／qualified索引、exact commit及正常ff-only master merge、下一統籌gate已接受，core+1／dep+1／reliability0／stall0。 | [來源 §27](SOURCE_REGISTRY.md#27-m2-focus-stock-scope-4六股來源准入)、[個股頁 §33](STOCK_RESEARCH_PAGE.md#33-m2-focus-stock-scope-4六股關注與同截止往返) |
| M1-HISTORY-OPEN-DATA-LINK-1 | 三份native metadata有限review，REST11371 daily-only／suggest REST有reply history；月資源用途未准入、歷史金融GET0／core0／dep0／非implementation batch。 | [來源 §28](SOURCE_REGISTRY.md#28-m1-history-open-data-link-1開放平台metadata與歷史用途缺口) |
| M2-FOCUS-STOCK-SCOPE-5-B1 | 七股`.5`／source14／actual API及可信往返有限接受，core+1／selected dep+1／reliability0／stall0；七scope索引／本地merge已接受。 | [來源 §29](SOURCE_REGISTRY.md#29-m2-focus-stock-scope-5七股來源准入)、[個股頁 §34](STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返) |
| M1-PRICE-SAVE-1-B1 | 七股10/06 private三檔／NEW reader／actual API及可信操作，core+1／necessary dep+1／reliability0／stall0；source13＋DOC8 freeze21／qualified索引與本地master merge c1388b1已接受，三檔NO-RETRY保持。 | [來源 §30](SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)、[個股頁 §35](STOCK_RESEARCH_PAGE.md#35-m1-price-save-1私人單日保存與跨程序操作) |
| M1-SAVED-PRICE-FOCUS-1006-1-B1 | 七股10/06既有保存來源精確四條件篩選、NEW reader／actual API及可信五原字串往返／focus與detail502清值；core+1／necessary readonly-use dep+1／reliability0／stall0，本地版本封存已接受。 | [來源 §32](SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)、[個股頁 §37](STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返) |
| M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1-B1 | 3105／6488同10/06 saved OHLC＋true5／20net共同入口、可信桌面窄版五RAW往返及same-token502清兩來源；core+1／necessary joint-guard dep+1／reliability0／stall0，本地版本封存／master合併已依原task接受。 | [來源 §33](SOURCE_REGISTRY.md#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口)、[個股頁 §38](STOCK_RESEARCH_PAGE.md#38-m1-saved-price-chips-integration-1006-1共同入口與同截止往返) |
| M1-SAVED-PRICE-CHIPS-FOCUS-1006-1-B1 | guarded八條件seam及actual unavailable受驗；Oct10/7extra拒immutable10/6、index2／daily0；正向matching／真零／jointdetail／八RAWback未驗，core0／dep0／reliability0／stall1。 | [來源 §34](SOURCE_REGISTRY.md#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口)、[個股頁 §39](STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界) |
| M1-P4a | 有界來源審查接受；TWSE 法人來源與 exact 用途權利未准入，未取得原件或增加功能。 | [來源 §12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口) |
| R1-A2／M1 成交量 | 指定成交額 migration、selected 拒收、legacy 精確整數磁碟案例及 synthetic HTTP／JavaScript／個股呈現；不證真實全市場 coverage。 | [資料來源](DATA_SOURCES.md)、[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現) |
| M3-P1～P5 | 既有庫存精確股數、int64 保存／指定磁碟重開、成本／停損／風險輸入與讀回、估值／持倉判定一致。 | [UI 文案](UI_COPY_SPEC.md)、[R0 §8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受) |
| M3-P6a／P6b | 庫存本地試算及 Actions 清單行情讀回隔離；行情來源／日期仍未核實。 | [UI 文案](UI_COPY_SPEC.md) |
| M3-P6c／P6d／P6e | 個股行情、研究候選、特徵／籌碼獨立讀回隔離；已接受必要 API／App 與具名有限操作。P6c 有效歷史窄版溢出未通過，canvas 與真正截止表單未驗。 | [個股頁 §15](STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)、[§16](STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)、[§17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離) |

M3-P1～P6e 改善既有庫存與讀回可靠性，不計新 Plan 或完整生命週期完成。子能力驗收不取代 R2-E1 的 backend 全套、production build 與瀏覽器整合驗收。逐項未驗範圍及驗證入口見[開發入口](development-baseline/README.md)；版本封存以 Git／原 task 為準，不重複逐輪收據。

## R0 要修正的五件事

| ID | 已有能力 | 剩餘驗收 |
| --- | --- | --- |
| R0-1 ATR | Wilder 純核心與保存層；worker 仍用 legacy 算法。 | 官方輸入與時間、B3-wire、PIT 及新舊重播比較。 |
| R0-2 信心與保存輸入 | 新產出固定規則 confidence=null；legacy 值保留且非機率（[R0 §5.1](R0_IMPLEMENTATION.md#51-欄位語意)）；artifact／capture／Bridge B 與獨立本地證據 verifier。 | 真實 tuple 整合、其餘輸入及歷史原件／版本／availability、consumer 與 paired replay／選版。 |
| R0-3 價位 | 規則參考價與 B4b 盤後 long caller-input 純核心。 | 官方 tick／費稅／日曆、來源／時間、保存與產品接線、完整 replay／paired comparison；未形成產品計畫。 |
| R0-4 時間 | 時間保存、API／UI 投影與 caller-declared cutoff 純核心。 | 保存與產品關聯、完整實際依賴／來源／歷史決策、合法執行、修訂／回補與 PIT。 |
| R0-5 DB 邊界 | 有限 migration、canonical rebuild、唯讀 startup gate。 | 正式 migration／restore／deployment、其他 schema 與服務 reload。 |

算法、schema、支援／拒收形狀與版本由 [R0 實作](R0_IMPLEMENTATION.md) 管理，預設切換另須 B7 與統籌決策。

## R1–R3 驗收方向

- R1：逐市場、標的、日期與用途驗來源／coverage；成交額缺失或無效存數值 0 並另存 unavailable／原因，明確來源零才是有效零。契約見[資料來源](DATA_SOURCES.md)、[新聞](NEWS_SPEC.md)、[產業分類](INDUSTRY_CLASSIFICATION.md)。
- R2：公司品質、事件機會、交易位置與持倉風險分開，交付可拒絕交易的完整計畫。契約見[產品規格](PRODUCT_SPEC.md)。
- R3：先定目標與門檻，再驗增量、樣本外與前瞻；樣本不足等待，未校準不給機率。契約見[策略驗證](STRATEGIES.md)。

## 產品取捨與待決定事項

| 項目 | 現行處理 |
| --- | --- |
| 使用情境 | 盤後 long、最早 T+1、數天至數週；精確期間與做空待決。T+5／T+20 是追蹤窗口，不是必然退出日。 |
| 風險預算 | 未知時不預填個人比例或張數；一般研究方案可先版本化。 |
| 來源／AI | 使用免費公開來源；供應商、預算、歷史權限、部署及成本／隱私未選定。目標／採用門檻須在看測試結果前記錄。 |
| 資訊審核 | 來源准入、逐項證據、高風險／低把握覆核；不要求每則合格摘要人工點選。 |
| 保留能力 | 來源／時間／品質追溯、策略版本、回測、模擬追蹤、持倉風險、新聞、族群、個股頁；raw／run／coverage／原因碼／公式留研究後台。 |
| 降低新增優先 | 全 ETF 專用策略、完整財務記帳、大量新指標、細碎呈現改版；保留既有相容能力。 |
| 第一版不含 | 盤中即時交易、自動下單、無來源 AI 報價、未驗證勝率、確定身分的「隔日沖主力」標籤。 |

資料收集排程與交易自動化各須明確操作授權。前者驗來源可靠性、重試與觀測，不以策略績效為前置。
