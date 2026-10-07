# R0–R3 執行清單

更新：2026-10-07。本文件管理工作 ID、狀態、依賴與完成條件；優先順序見 [ROADMAP](ROADMAP.md)，精確規格見各列連結。

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

核心選題與跨輪停滯計數依 [AGENTS](../AGENTS.md#核心選題與進度判定)，優先順序依 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。下表列工作狀態與驗收邊界；子能力完成不代表完整 M1／M2／M3 或 R2-E1 通過。

| 工作 ID | 狀態與必要依賴 | 已接受範圍／完成條件 |
| --- | --- | --- |
| UNIT-LOTS-1 | 已review（功能前置，非核心完成）；canonical股／int64及相容輸入契約不變。 | 日常張數／精確零股／原股稽核與具名輸入已接受；前置1批、core0／dep0、當時stall1，M1後current26src必要兼容回歸已核。見[UI §10.3](UI_COPY_SPEC.md#103-張零股)／[個股頁 §7.1](STOCK_RESEARCH_PAGE.md#71-unit-lots-1-日常張數與原股稽核有限接受)。 |
| M1-PRICE-1 | 已review（有限核心）；dataset11370獨立policy／固定body及兩股2026-10-05真價量。 | 唯一trusted載入→1 GET→actual API／headline／chart／面板同股同日；切6488同cache、GET／重複POST零額外source、default／explicit10/02不滲新日、具名桌面／窄版及owned清理已核。core+1／dep+1／stall0，fixes／UNIT兼容回歸同批；非MA20／trend／研究／PIT／保存。見[個股頁 §25](STOCK_RESEARCH_PAGE.md#25-m1-price-1上櫃兩股單日價量閉環有限接受)。 |
| M2-FOCUS-LOTS-1 | 已review（有限核心）；從M1 merged `704b2df`起輪，可見四角色gate、本輪同兩股／10/05 fresh GET、原policy／body pins與instrument准入已核；source10與owned清理接受。 | `price-lot-focus/m2-v1`：精確min_lots字串與canonical股比較、code順序，20,000只3105／10,000兩股／50,000真零、10/02unavailable countnull；48127.911／48127.912邊界及同cutoff個股返回原字串已核。Core+1／dep0／reliability0／stall0，SHA wrap退修及必要重驗同批。只process memory／既有來源，非前日漲跌／trend／PIT／保存或完整M2；權威見[個股頁 §26](STOCK_RESEARCH_PAGE.md#26-m2-focus-lots-1精確成交張數關注與同截止往返有限接受)。 |
| M2-FOCUS-DAY-MOVE-1 | 已review（有限核心）；起始merged `a7bcdd37ae35ee27fd520a6682467b3b9f9355ae`、新四角色可見gate、fresh exact11370／原policy pins／用途／instrument核通；source9與owned清理接受。 | `price-lot-focus/m2-v2`：精確張門檻＋all/up/down/flat、原O/C兩理由去重／code順；10k all2/up3105/down6488/flat0、精確邊界、422及10/02 countnull已核。具名桌面／窄版同cutoff研究，safe local返回日期／min_lots尾零／方向；core+1／dep0／reliability0／stall0，非前日漲跌／trend／PIT／保存；[個股頁 §27](STOCK_RESEARCH_PAGE.md#27-m2-focus-day-move-1單日方向關注與完整條件往返有限接受)。 |
| M2-FOCUS-TURNOVER-1 | 已review（有限核心）；起始merged `230af7ea1bf031eea698f937d8ce6f713ba275f6`、新四角色可見gate、fresh exact11370／原policy pins／TWD stock用途與execution核通；source9與owned清理接受。 | `price-lot-focus/m2-v3`：canonical int64元原字串min_turnover配張門檻／O/C，三理由去重／code順、samecutoff研究及四條件safe返回。25e9一股／20e9兩股／down25e9真0、兩股等額＋1元、422／10/02未知及桌面／窄版已核；core+1／dep0／reliability0／stall0，wrap退修同批。非歷史／PIT／排名／Signal／Plan，權威見[個股頁 §28](STOCK_RESEARCH_PAGE.md#28-m2-focus-turnover-1精確成交金額與四條件往返有限接受)。 |
| M2-FOCUS-DAY-RANGE-1 | 已review／freeze／索引及qualified coverage／exact commit／local master merge至 `2cbd4e1842f7dc1929469a245287e6dbdd019861`；source18、新10/06兩股來源及可信操作有限接受。 | `price-lot-focus/m2-v4`四理由／五條件、精確振幅與samecutoff往返，core+1／dep+1／reliability0／stall0；最後額外invalid fallback native未送達邊界保留。Page／RAM服務已清，profile NO-RETRY保留；現行三股另用獨立新scope，歷史契約見[個股頁 §29](STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返)。 |
| M2-FOCUS-STOCK-SCOPE-1 | 有限核心及source17／DOC8 exact freeze／七分區qualified索引／exact commit與另准ff-only master merge `50c228d` 已接受；starting merged `2cbd4e1`，新四角色可見gate已核、新增5347普通股identity／catalogue及11370三股policy／body／金融正面准入、source17已接受。 | `price-lot-focus/m2-v5`完整三股gate→四理由去重／code順→samecutoff五原條件返回；actual API精確邊界及可信桌面／窄版5347往返、真零／三股code順已核，core+1／selected identity-source scope dep+1／reliability0／stall0。Default新三股與explicit舊兩股immutable tuples保持，無第六URL條件；owned清理已核，未驗保存／跨程序／PIT／20／21歷史或完整M1／M2／M3。見[個股頁 §30](STOCK_RESEARCH_PAGE.md#30-m2-focus-stock-scope-1三股關注與同截止往返)。 |
| M1-CLOSE-RESOURCE-1-OBSERVE-1 | 已review（有限有界觀測）；新四角色visible gate及原root continuation已接受，exact dataset17257 GET一次、無參數／redirect／retry／disk。 | 890列／890碼均10/06單日JSON，body137622B；欄名差異、MarketValue單位與普通股全scope未核，不能補20／21close／完整日曆或strategy／time／execution。[來源 §22](SOURCE_REGISTRY.md#22-m1-close-resource-1有界單日-json-觀測)管理實際來源與邊界；無API／UI／核心依賴解除，不計implementation batch，繼承stall0。 |
| M2-FOCUS-STOCK-SCOPE-2-B1 | 已review／前輪已合併；新5274普通股／fresh11370用途、四股 `.2` policy與source13有限接受。 | 四股完整gate／actual API八案／可信5274 raw五字串往返／真零恢復已核，coreoperation+1／scope dep+1／reliability0／stall0；source13＋DOC8 freeze21／七scope qualified索引／exact commit／正常ff-only master merge `899fa622` 已接受，explicit舊tuples保持。見[個股頁 §31](STOCK_RESEARCH_PAGE.md#31-m2-focus-stock-scope-2四股關注與同截止往返)。 |
| M1-HISTORY-QUERY-1-METADATA-1 | 已review（有限只讀）；NEW官方stock-pricing／tradingStock monthly lead，primary HTML／JS可追溯。 | Exact M wire／歷史自動用途未准入、resourceLINK未核，歷史金融body GET0；20／21close／完整calendar／strategy time execution未解除。core0／dep0、不計implementation batch、stall0保持，不作全域不可能主張，見[來源 §24](SOURCE_REGISTRY.md#24-m1-history-query-1官方月查詢線索與准入缺口)。 |
| M2-FOCUS-STOCK-SCOPE-3-B1 | 已review／已合併；3293普通股／fresh catalogue與11370用途、五股`.3`及source12 accepted。 | 四→五股完整gate／90欄與30金融值、actual API10案／inclusive張元振幅／六cached POST、可信desktop1277×924與窄版390×844 raw五原字串往返／真零恢復已核；core+1／selected scope dep+1／reliability0／stall0。當輪CSV GET3／final worker1／preloadedfalse及owned清理保留；source12＋DOC8／freeze20／qualified索引／正常ff-only master merge `fb945708` 已接受，見[個股頁 §32](STOCK_RESEARCH_PAGE.md#32-m2-focus-stock-scope-3五股關注與同截止往返)。 |
| M1-HISTORY-MONTH-WIRE-1-DISCOVERY-1 | 已review（metadata-only）；primary script支持Gregorian YYYY/MM/01／encoded wire推論、export GET／regular JSON POST方法。 | Server／historical finance未執行，exact historical automated-use／20／21close／complete calendar／strategy time execution未准入；core0／dep0、非implementation batch、不增加stall，不作全域不可能主張，見[來源 §26](SOURCE_REGISTRY.md#26-m1-history-month-wire-1月參數推論與用途缺口)。 |
| M2-FOCUS-STOCK-SCOPE-4-B1 | 已review／已合併；8069身份／fresh catalogue／11370用途與`.4` policy，source13有限接受。 | 六股108欄／36金融值、actual API10案／七cached POST零新增source、精確邊界及可信往返已核；coreoperation+1／selected dependency+1／reliability0／stall0。Source13＋DOC8／freeze21／qualified七分區索引、exact commit／正常ff-only master merge及下一統籌visible gate已接受，見[個股頁 §33](STOCK_RESEARCH_PAGE.md#33-m2-focus-stock-scope-4六股關注與同截止往返)。 |
| M1-HISTORY-OPEN-DATA-LINK-1 | 已review（metadata-only）；REST11371 daily CSV、suggest136936 SSR與完整REST reply history。 | Exact月資源／自動用途仍未准入；guide nativeGET原exit1與rendered官方REST指南分報、masked身份未證；historical financial GET0／core0／dep0／非implementation batch／stall0。見[來源 §28](SOURCE_REGISTRY.md#28-m1-history-open-data-link-1開放平台metadata與歷史用途缺口)。 |
| M2-FOCUS-STOCK-SCOPE-5-B1 | 已review／已合併；`.5`七股source14、exact commit／qualified七scope／ff-only master merge已接受。 | 126欄／42金融、API10案／八cached POST、可信raw五字串往返；core+1／selected dep+1／reliability0／stall0，舊契約與pins保持，見[個股頁 §34](STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)。 |
| M1-PRICE-SAVE-1-B1 | 已review／已合併；source13＋DOC8 freeze21／qualified索引、exact commit及正常另准ff-only master merge c1388b1已接受。 | 七股10/06三檔／NEW reader／具名API及UI、core+1／necessary dep+1／reliability0／stall0按原Windows範圍有效；private三檔NO-RETRY及missing-file UI未跑不變，見[來源 §30](SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)。 |
| M1-CHIPS-CUTOFF-1006-1-B1 | 已review／已合併；source10＋DOC8 freeze18／qualified七分區、exact commit及另准ff-only master merge fc4a35b已接受。 | explicit10/06的3105／6488真5／20日12net、完整24 observed calendar／20真daily、actual API／可信desktop窄版及same-token502清值；coreoperation+1／necessary source-use-calendar-daily dep+1／reliability0／stall0。W8／default保持、非PIT，按[來源 §31](SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)／[個股頁 §36](STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)原範圍有效。 |
| M1-SAVED-PRICE-FOCUS-1006-1-B1 | 已review（有限核心）；source13／net84588B、finite existing-private read-use／新2677B consumer、actual API／可信操作及owned runtime清理已接受。 | 七股10/06四條件精確篩選→saved detail→五原字串返回、全七股gate／inclusive三邊界／flat真零／focus與detail same-token502清值；NEW emptyStore／memorydisabled，metadata／financialGET0／newdisk0／DBmut0，coreoperation+1／necessary readonly-use dep+1／reliability0／stall0。DOC review／freeze／qualified索引／Git尚待，來源與操作見[§32](SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)／[個股頁 §37](STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)。 |
| M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1 | 條件式下一候選，未准入／未派工；saved-only allPOST禁止／chips Store未准入阻擋共同guarded entry，baseline co-render已存在。 | 新root先核兩source-use／consumer policies、private有限只讀、samecutoff／來源時間及NEW empty stores；oldchips raw釋放，fresh bounded22 GET僅准入後取得。Actual saved-focus→3105／6488價格＋5／20net→追溯／五原條件返回才計core；若已可執行或route不可行，拒絕空轉並另核ordinary第八股identity／scope／用途，不把capture／review當dep。 |
| M1：R2-A2／D1 | 整體未完成；所採來源、窗口／交易日coverage、時間、分類與版本。 | 新兩股explicit10/06窗口／24完整觀測日曆及W8兩股八截止來源、96 net／actual API及16具名可信native已有限接受，owned清理已核；範圍外unavailable、突破／回踩固定保守。真8/25／27日曆／新policy及pins已核，非PIT／保存／研究；餘項見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。 |
| M1-P1 | 已 review（有限）；准入 STOCK_DAY_ALL 原件與共用日期截止。 | TWSE 1101／2330、2026-10-01 真實價格六欄、截止／追溯及桌面／窄版操作；記憶體 SQLite，不是多日、法人或 PIT。見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。 |
| M1-P2a | 已 review（有限）；exact TPEx 單來源 manifest／pins／profile。 | 3105／6488、2026-10-02 單日原件→capture→摘要 CLI 與具名拒收；未含多日／日曆或產品接線。見[來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。 |
| M1-P2b | 已 review（有限）；P2a、明示 server ZIP／日期與總覽截止。 | 兩檔單日原件→API 二十個數值、追溯、端點一致及桌面／窄版操作；5／20 日仍 unavailable。見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。 |
| M1-W1 | 已 review（有限依賴）；獨立政府 CSV policy／外部 pins、有界完整日曆與窗口版本。 | TPEx 3105／6488、唯一截止2026-10-02，20日真原件／22完整開市日、40 selected rows／880金融原字串及12窗口 net 重算已接受；解除此範圍來源／日曆／計算依賴，未交 API／UI 操作。見[來源 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)。 |
| M1-W2 | 已 review（有限操作）；W1 範圍、共用截止、明示首次取得及零外網 GET。 | TPEx 3105／6488、10/02的12窗口 net、原列／來源／缺日及具名 API／UI 操作已接受；22新原件不混用 W1 receipt。其他範圍／PIT／研究條件仍缺，見[個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)。 |
| M1-W3 | 已 review（有限來源／操作）；新版獨立 policy／外部固定 pins、完整22日曆及共用 cutoff。 | TPEx 3105／6488新增9/30、10/1並保留10/2；新增兩日真原件、三截止36 net／actual API與 native切換、來源／缺日0及拒用已接受。union24原件只存記憶體，未含保存／PIT／研究條件；見[來源 §14](SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)及[個股頁 §19](STOCK_RESEARCH_PAGE.md#19-m1-w3三截止法人窗口與原件追溯)。 |
| M1-W4 | 已review（有限來源／具名操作）；23日曆、全月OHLC及新固定policy／pins。 | 新8/31 daily／8月index、production26、兩股四截止48 net／actual API及可信原生表單已接受；兩股窄版原列、TWSE route拒用及actual服務清理已核。非PIT／保存／研究條件，見[來源 §15](SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)及[個股頁 §20](STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯)。 |
| M1-W5 | 已review（有限真來源／具名操作）；24日曆、全月OHLC及新固定policy／pins。 | 新8/28 daily／完整24日曆、production27、兩股五截止60 net／actual API及可信原生操作已接受；來源外層／兩股新原列、unsupported恢復及TWSE route拒用、actual服務清理已核。非PIT／保存／研究條件，見[來源 §16](SOURCE_REGISTRY.md#16-m1-w5五截止法人來源與完整有界日曆)及[個股頁 §21](STOCK_RESEARCH_PAGE.md#21-m1-w5五截止法人窗口與原件追溯)。 |
| M1-W6 | 已review（有限真來源／計算／actual API／具名可信native）；owned服務清理已核。 | 同兩股新增9/23、保留五cutoff，共72 net。真8/27全列／44金融欄、三月43全OHLC／完整25日曆、新policy／固定pins，production28原件及獨立72 net／2700重疊API原字串已核；9/23恰20、5日起9/17／20日起8/27。見[來源 §17](SOURCE_REGISTRY.md#17-m1-w6六截止法人來源與完整有界日曆)／[個股頁 §22](STOCK_RESEARCH_PAGE.md#22-m1-w6六截止法人窗口與原件追溯)，非PIT／trend／研究條件／保存。 |
| M1-W7 | 已review（有限真來源／計算／actual API／具名可信native）；owned page／服務清理已核。 | 同兩股新增9/22、保留六cutoff，共84 net。真8/26全列／44金融欄、三月43全OHLC／完整26日曆、新policy／固定pins，production29原件及ALL29 receipt SHA獨算、1144金融原字串／3150重疊API字串已核；9/22恰20、5日起9/16／20日起8/26。見[來源 §18](SOURCE_REGISTRY.md#18-m1-w7七截止法人來源與完整有界日曆)／[個股頁 §23](STOCK_RESEARCH_PAGE.md#23-m1-w7七截止法人窗口與原件追溯)，非PIT／trend／研究條件／Signal／保存。 |
| M1-W8 | 已review（有限真來源／計算／actual API／具名可信native）；owned page／服務清理已核。 | 同兩股新增9/21、保留七cutoff，共96 net。真8/25全列／44金融欄、三月43全OHLC／完整27日曆、新policy／pins，production30原件及ALL30 body／canonical receipt SHA獨算、1188金融原字串／3600重疊API字串已核；9/21恰20、5日起9/15／20日起8/25。見[來源 §19](SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)／[個股頁 §24](STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯)，非PIT／trend／研究條件／Signal／保存。 |
| M1-W9（歷史候選） | 已封存；只有bootstrap／接手，無implementation batch，未採為本輪下一工作；8/24 daily／新policy／pins仍未准入。 | 原未實作計畫： 同兩股新增9/18、保留八cutoff，九截止108 net；候選28sessions／31GET／59MiB、9/18恰20／5日起9/14／20日起8/24皆待新root正面核。8/24全OHLC已驗未採不代daily，不需8/21；真來源／完整日曆／新版本正面後才計算／API／native，無路徑在實作前重選必要gate全齊最小M3具名Plan或waiting，不空轉可靠性或降gate。 |
| M1-P3a | 已 review（有限）；原四來源固定 pins 與 TWT48U memory consumer。 | 0056（ETF）／1449／1463 selected 四欄／列序／雙 hash 與拒收；發布／首次可得 unknown，原件未保存，不支持離線重播或 ZIP 輸入。見[來源 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)。 |
| M1-P3b | 已 review（有限）；P3a、明示啟用／首次 POST、臺北觀測日 cutoff。 | selected 總覽、API 四欄／追溯、cache 再用及具名操作；普通 GET 零外網，未來生效預告保留。見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。 |
| M1-P4a | 審查接受；來源未准入，等待 exact 用途權利證據。 | 未取得法人原件或新增 consumer／API／UI，不計核心依賴解除；取得正面證據後才驗完整單日原件與接線。見[來源 §12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口)。 |
| M1／R1-A2 成交量呈現 | 已 review（有限）；既有精確整數 gate／磁碟 HTTP 與相容表示。 | synthetic API→JSON／JavaScript→個股精確字串及具名操作；圖形高度近似。未證真官方／正式 DB／完整 M1。見[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)。 |
| M2：R2-A1／D1 | 整體未完成；採用理由須來源／時間／版本，可信排名另需分類品質。 | 本輪七股張／O-C／成交額／振幅四理由、五條件API／可信desktop窄版samecutoff往返有限接受；coreoperation+1／selected scope dep+1。其他來源／標的、分類品質與完整整合仍缺；[個股頁 §34](STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)管理現行範圍。 |
| M2-P1 | 已 review（有限）；P3a／P3b、全 feed gate、cache／鎖、截止與 catalogue。 | 2026-10-03 原件 58 列／58 股→API，三檔可連 M1，其餘 55 股無測試 catalogue 連結；同股多事件／空 feed／截斷另由 fixture 驗。見[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。 |
| M2-P2 | 已 review（有限）；P1 全 feed gate、先搜尋後100股上限及固定返回條件。 | 原件／符合／顯示／截斷分列，來源代碼／名稱搜尋與研究往返；空原件／無符合／來源不可用可辨識。見[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。 |
| M3：R2-B1／B2／C1／D1，R0-C2／C4／C5 | 整體未完成；所交付子能力的來源、時間、版本、官方 tick／費稅／合法時段、保存及執行 gate。 | 保存後跨程序讀回相同版本計畫；觸發、到期、未成交、模擬與退出分開驗收。未知風險不給張數，觸價不當成交，預設切換仍須 B7。 |
| M3-P1 | 已 review（有限）；既有 Float 可信股數與 strict 互斥輸入。 | 當時安全整數呈現／失精輸入拒收；大數保存由 P2 補齊。見[UI 契約](UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)。 |
| M3-P2 | 已 review（有限）；nullable INTEGER、0008／八 markers、safe legacy backfill。 | int64 精確保存、指定 migration normal／fault、磁碟／兩程序重開與產品操作；unsafe 原值不捨入修復。見[UI 契約](UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)、[R0 §8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)。 |
| M3-P3 | 已 review（有限）；成本／停損／風險 nullable Float 與原整列覆寫／清欄語義。 | 非法輸入拒收、既有列保留、合法零／空白清欄；不含 Decimal exact 或 risk sizing。見[UI 契約](UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)。 |
| M3-P4 | 已 review（有限）；P3 與原持倉 stop gates。 | 價值讀回三態及非法停損隔離，不證污染修復或全估值。見[UI 契約](UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)。 |
| M3-P5 | 已 review（有限）；P2 quantity／P4 value、必要估值／held／篩選／計數 caller。 | 可信股數與估值／持倉判定一致；大數金融估值 unsupported。見[UI 契約](UI_COPY_SPEC.md#m3-p5-可信庫存股數與既有估值持倉判定一致)。 |
| M3-P6a | 已 review（有限）；可信股數／成本、raw close 與用途分離。 | 庫存 local_estimate 與展開／收合，來源／日期 unverified；原 Actions 500 由 P6b 另補。見[UI 契約](UI_COPY_SPEC.md#m3-p6a-庫存收盤數值隔離與本地試算可檢視)。 |
| M3-P6b | 已 review（有限）；raw 八欄、120列窗口、unlocated 日期、TAIEX／原 file gates。 | Actions 清單逐列行情隔離；不證污染個股詳情或完整 ActionsPage。見[UI 契約](UI_COPY_SPEC.md#m3-p6b-actions-清單逐列行情讀回污染隔離)。 |
| M3-P6c | 已 review（有限）；個股行情日期／窗口與原來源／時間／raw file gates。 | 行情讀回隔離與具名有限操作；有效歷史窄版溢出未通過，canvas／真正截止表單未驗。見[個股頁 §15](STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)。 |
| M3-P6d | 已 review（有限）；stock-only Signal／StrategyVersion raw reader 與原 gates。 | 20列窗口與 canonical 全集分開、bad latest 不 fallback、unlocated 拒用、健康行情／alternate 保留。見[個股頁 §16](STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)。 |
| M3-P6e | 已 review（有限）；FeatureSnapshot／Chip raw reader、共同截止及原研究／持倉 gates。 | 壞特徵／籌碼只隔離該區塊，不較早 fallback，健康行情／研究保留；API／App／六個具名有限操作及六表不變已驗。見[個股頁 §17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。 |

本輪M1-SAVED-PRICE-FOCUS-1006-1-B1 starting／current／master `fc4a35b67535a7d21b1bba080f799ac6ad46529f`；原root／三child、visible gate與SINGLE continuation保持。Source13／net84588B、finite saved read-use／actual API／可信操作與owned runtime清理已接受；operation+1／necessary readonly-use dep+1／reliability0／stall0。Exact8 DOC review→freeze→qualified affected七分區／coverage→exact commit→另准master merge仍待。OldCHIPS四角色正常close／ONE archive已接受，worktree／branch仍為retained baseline，待replacement qualified索引／baseline unneeded／merged clean／無unsaved與新ignored及resolved outside-owner exact scope才移除；現未執行。Private1791644B三檔與整個DAY-RANGE strict NO-RETRY／at-cap不增diskcases保持，原task留完整收據，見[接手紀錄](TASK_COORDINATION.md)。

本批saved來源scope／grant／pins／金融真值由[來源 §32](SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)管理，actual five-condition操作由[個股頁 §37](STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)管理。下一integration只是上表conditional候選：需具體缺失的共同guarded entry及新准入、NEW stores與實際joined operation，不把已有co-render／review／duplicate capture計核心。普通20／21 dated stock closes缺新正面official route／用途證據，24 index calendar不能替代；最小M3 strategy／tick費稅／time／execution及完整ROADMAP仍缺，不重複舊audit或以fixture完成。

M1依賴與接線按所採範圍驗收；W1–W7歷史及W8有限接受不外推：

| 工作 | 必要條件 | 完成條件 |
| --- | --- | --- |
| 多日法人及交易日證據 | 已准入來源／用途、具名免費取得路徑與核定範圍；既有單日證據不代多日。 | W8已接受兩股27日原件、三月全返回OHLC與完整有界日曆／八cutoff，見[§19](SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)；§13–18保留歷史。範圍外另須逐欄／單位／修訂／缺日與完整基準，缺列不推休市；未採來源缺證見[§10](SOURCE_REGISTRY.md#10-m1-後續依賴審查來源候選與等待邊界)／[§12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口)。 |
| 5／20 日淨超窗口計算 | 上述證據滿足，統籌核定窗口、交易日／缺日處理與版本。 | W8兩股／八截止96 net逐欄獨立重算及actual API已接受；其他範圍另驗，缺日不補零、縮窗或較早／未來fallback。 |
| 研究規則計算 | 所採策略輸入／時間／分類與規則版本齊備。 | 成立／未成立／資料不足有真實原因，不跨策略拼值或補零；W1 不進 Signal／研究條件，仍待實作驗收。 |
| API／UI 及產品驗收 | 已驗計算與同一研究截止。 | W8兩股／八截止原件→actual API、16可信native表單、來源／兩股新8/25原列／拒用及owned清理已有限接受；缺／壞8/25只有必要synthetic API／SSR，actual missing0。新範圍另驗來源、日曆／版本、數值與可信操作。 |

M3-P1～P6e 是既有庫存與讀回可靠性成果，不計新 Plan 或完整生命週期。最小計畫操作須先列實際資料、來源／availability、decision／execution 時間、版本及必要合法執行條件；涉及保存須驗隔離磁碟保存／跨程序讀回。

詳細命令、原始失敗、驗證範圍與副作用見[開發入口](development-baseline/README.md)；版本與清理收據見 Git／原 task。子能力驗收不取代 R0／R1 完整資料驗收或 R2-E1 的 backend 全套、production build 與瀏覽器關鍵流程。

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
| R0-B2／B2-persist | 已 review（局部）；整體未完成 | R0-A1、G-ID | Bridge B opt-in detached candidate、capture v2 selected bar／v3 prior volumes 最多20筆本地 metadata；獨立 verifier 只證 caller 指定本地 selected-bar 證據一致，不升格 bytes_unverified 或 prior volumes。真實檔案／snapshot 整合、其餘輸入／歷史原件／availability／PIT、consumer 與 paired replay 待驗，70個既有案例未跑；完整 tuple 未齊時不重複搜尋或建 fixture。精確 API／拒收條件見[Artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。 |
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
| R1-A1 | 已 review（局部）；整體未完成 | G-SOURCE；來源可行性可先行，實際 as-of 接線才依賴 R0-C4。 | 原 snapshot 四來源 registry／capture、兩個磁碟 consumer 及窄修正已有限 review；另 TWT48U selected／feed、explicit TPEx 單日 selected，以及 W1／W3／W4／W5／W6／W7／W8獨立政府 CSV／有界日曆來源與 consumer 的具名版本已有限 review。其餘 collector、公司行動／停復牌、授權、時間／修訂／歷史與 PIT 仍待驗，具名範圍見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。 |
| R1-A2 | 已 review（指定子批）；整體未完成 | 本批採用的 R1-A1 來源；逐市場／欄位用途驗證。 | TAIEX 身分／成交額狀態、單一離線缺額／零樣本、兩路徑八個 migration 磁碟案例、指定 selected invalid／拒收、legacy 精確整數 gate／磁碟重開及 synthetic browser 呈現已有限接受。其他 invalid／拒收、正式 DB、真實逐欄 coverage／其他股數精度待驗。完整驗收要求 exchange＋symbol＋session＋欄位用途有 raw 追溯，缺值、合成或截斷值不當有效零／可用欄位。支持範圍見[資料來源](DATA_SOURCES.md)與[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)。 |
| R1-A3 | 提案 | R1-A1、R0-B5；公司行動與停復牌。 | raw／adjusted basis、因子、版本、可得時間與 applied-through 可重建；TWSE／TPEx 覆蓋分開；不足時 ATR／tracking fail-closed。 |
| R1-B1 | 提案 | 本批採用的 R1-A1 來源與時間／版本證據；實際 as-of gate 接線依 R0-C4 必要輸入。 | unknown time、date conflict、backfill、revision／withdrawal、feed-only URL、無內文均有案例；排序與 cursor 綁 snapshot／version；無可信時間者不搶占「最新」。 |
| R1-B2 | 提案 | R1-B1；同事件 grouping 與 new-information。 | 同源與跨源 dedupe 可重跑，保留每篇來源；首次／補充／更正／撤回分開；負面或轉載不增加正向催化；所有摘要回指合法原文。 |
| R1-B3 | 提案；來源可行性待驗 | R1-A1、G-SOURCE；免費官方 macro／可信媒體可行性。 | 每個候選以實際抓取、時間、保存／摘要權利與穩定性驗證；沒有可接受來源就記 `受限`，不以搜尋摘要或模型記憶補內文。 |
| R1-C1 | 提案；R16／17、R35–38 的身分小批已有限 review | 本批分類來源、版本與期間；採用事件形成題材時才需 R1-B2。正式分類修復依自身資料與驗收，不加無關 capture 工作作前置。 | 產業／題材分層及有來源、版本、期間的 membership。成員報酬、candidate 決策、backfill 納入及 public 展示各有有限成果，語意不得互換；正式分類與歷史 PIT／回算未完成。精確規則見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。 |
| R1-C2 | 提案 | R1-C1、R1-A2；題材品質與去重。 | 相同 as-of 的相對強弱、廣度、集中度、延伸與事件方向各自有窗口／缺項；重疊題材不重複計候選或曝險；不改 `hot_group_v1` gate。 |
| R1-D1 | 提案 | R1-A1；官方當沖資料。 | 先固定分子／分母、股數／金額、T／T+1／T+2 修訂與 availability；兩市場分開驗證；修訂可按當時版本重放。 |
| R1-D2 | 提案 | R1-A1；融券／借券／持股欄位。 | 每欄來源、單位、日期、revision、coverage 與 null policy 有證據；欄位存在不算已收集。 |
| R1-D3 | 提案；來源可行性待驗 | R1-A1、G-SOURCE；券商／分點來源可行性。 | 交易資料接入／匯入待做；完整驗收要求穩定合法歷史、通道識別、單位與 PIT。局部匯入可獨立驗收，不等於完整歷史或每日自動更新；不足標受限，不推論投資人身分或預測。可得性見 [DATA_SOURCES](DATA_SOURCES.md#券商分點與主力統計的來源邊界後續待做)。 |
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
| R3-B1 | 提案；來源可行性待驗 | R1-B2、G-SOURCE、G-MODEL；本地／免費事件理解基準。 | 先用人工標註小集評估來源忠實、引用、事件／關聯／方向與拒絕率；模型／提示／輸入 hash 可重現；無可用本地／免費模型時保留 deterministic baseline 並標 AI 能力 `受限`。 |
| R3-B2 | 提案 | R3-B1；事件理解接線。 | 結構驗證、prompt-injection 隔離、更正／撤回、低把握待核實與回退規則通過；摘要流暢度不算策略增益。 |
| R3-C1 | 提案 | R3-A2；量化基準。 | 先跑固定技術基準，再依序加入題材、新聞、籌碼、AI；同 universe／window／cost；所有嘗試與失敗保留，不挑最好結果後改門檻。 |
| R3-C2 | 提案 | R3-C1；walk-forward／OOS／校準。 | train、tune/calibration、final test 按時間隔離；報成本後報酬、回撤、尾損、成交率、有效樣本、coverage、不可比率及 Brier／校準；適用外或失敗時 probability 為 null。 |
| R3-D1 | 等待時間累積 | R3-A1、R2-E1；前瞻模擬。 | 每日先封存 snapshot、候選、plan、零候選、模型失敗及撤回，再等待 trigger 與 H／退出完成；不得回寫舊決策。等待長度與最低有效樣本由 R3-A1 事先決定，未達前保持 `等待`。 |
| R3-D2 | 等待樣本／市場狀態 | R3-D1；漂移與壓力期。 | 覆蓋事先要求的市場狀態與成本敏感度；來源中斷、模型失效及固定規則回退演練；日曆時間超過三個月本身仍不等於足夠。 |
| R3-E1 | 等待統籌決策 | R3-C2、R3-D2。 | 統籌依預先門檻做採用／拒絕／延長觀察；只有達標版本能候選成為預設，仍非投資保證；其餘保持 research-only。 |

## 更新方式

文件角色每輪依統籌核定的完成狀態與驗收邊界，在 freeze／索引前更新受影響的工作列及主題契約。穩定內容不重寫，文件交付與結案依 [AGENTS](../AGENTS.md#文件與交接)。來源／前瞻樣本不足保持提案、等待或受限，不縮小原驗收條件。
