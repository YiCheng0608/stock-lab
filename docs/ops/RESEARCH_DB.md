<!-- owns: 研究 DB、歷史回補的執行方式 -->
# 研究 DB：歷史回補到各來源最早可得

策略研究要用比正式 DB（個股從 2024-09-30 起）更長的歷史，所以另建一份**研究 DB**，把資料補到各官方來源最早可得的日子（[各來源最早可得](../DATA_SOURCES.md#各來源最早可得)）。依據是 [#692 決定](https://github.com/YiCheng0608/stock-lab/issues/692#issuecomment-6873818646)：研究 DB 與正式 DB 分開存放（D1 選 B）、全部補到最早、回補時每個 host 間隔 ≥ 3 秒、2012 年以前的月營收與季報不補。

- **不是正式資料**：正式 DB、daily、scheduler 都不動，正式環境不設定下面的變數。研究 DB 由工程師在任務容器裡建、補、讀，不需要統籌的正式 DB 允許規則。
- **研究工具怎麼讀**：`tools/research/*` 本來就是 `--db <副本>`，直接指向研究 DB 的 `stock.db`；要用回補的範圍時，以 `--segment` 指定探索與驗證段（`feature_evidence.py`、`portfolio_research.py`，見下文）。

## 位置與設定

| 項目 | 值 |
| --- | --- |
| volume | `stock-lab-research`（容器內 `/data`：`stock.db`、`raw/`、`locks/`、`logs/`）；跟正式的 `stock-lab_stock-data` 分開，維護模式與鎖也是這個 volume 自己的 |
| `STOCK_DATA_DIR` | `/data` |
| `STOCK_SESSION_BASIS_START` | `2004-02-11`：個股歷史起點（`app.coverage.SESSION_BASIS_START`，交易日基準、回補 `target_met`、score dates 都從這天起） |
| `STOCK_INDEX_HISTORY_START` | `2004-02-01`：指數日 K 回補的下限（`worker.index_bars.HISTORY_START`），不能晚於上一列 |
| `STOCK_HISTORY_CREATE_UNMATCHED` | `1`：collect 遇到行情表有、DB 沒有的普通股或 ETF 代號時，直接建標的並寫入日線（下節），不記 `unmatched_bar` |

三個變數由 [`app.history_settings`](../../backend/app/history_settings.py) 在程序載入時讀一次。沒設定（或空白）時，就是正式環境的 2024-09-30、2023-09-01 與「不建標的」，由 `backend/tests/test_history_start.py` 驗證。日期只能比預設早，格式不對或比預設晚時，程序起不來。

## 下市與轉板的標的

研究 DB 由正式 DB 的副本開始，只有現存的標的與 2024 年以來的少數下市股；往前回補時，行情表裡早已下市或轉板的公司都不在 `instruments` 裡。不處理的話，它們的日線會被丟掉，每批還會多一列 `unmatched_bar`，長歷史上的結論就有倖存者偏差。設 `STOCK_HISTORY_CREATE_UNMATCHED=1` 時，collect 對這種代號照 `instruments repair --include-delisted` 的規則建標的（`pipeline.create_history_instrument`）：

- 名稱取自那份行情表；ETF 代號建成 `etf`，其他建成 `stock`。
- 另一交易所有同代號的標的時標 `transferred`（轉板），否則標 `delisted`。
- 每個新標的寫一列 `data_quality`（`entity_type=instrument_status`），記建立的日子與 raw id；collect run 的 metadata 列在 `history_instruments_created`。日線、籌碼照一般規則寫入。

已知限制：

- **代號重用**：一個代號下市多年後分配給別家公司時，兩家的日線會接在同一個標的上，這裡分不出來。#702 批 5 後依中斷與名稱稽核，找到 3 段重用：TWSE 2432、TPEx 6130、TPEx 4415（[6915084041](https://github.com/YiCheng0608/stock-lab/issues/702#issuecomment-6915084041)）。DB 不改，研究工具用[日線排除清單](#研究工具的日線排除清單)排除。
  - **上市舊頁的名稱是今天的名稱**：TWSE 舊的 `MI_INDEX`，「證券名稱」寫的是這個代號**現在**的名稱，和 MOPS 舊彙總頁一樣，是用今天的資料重產的。例如 2008-08-25 的頁上，2432 寫「倚天酷碁-創」，但倚天酷碁 2023-05-31 才上市。
  - 所以上市段落不能用前後名稱判斷代號重用，要看中斷期間有沒有籌碼列、收盤價是否連續。上市 2013 年以前另有 4 段中斷，用這兩點判斷是同一家（[6915138263](https://github.com/YiCheng0608/stock-lab/issues/702#issuecomment-6915138263)）。
  - 上櫃舊頁 `dailyQuotes` 印的是當時的名稱，例如 6130 從「亞全」變成「基因」。
- **產業與族群成員**：新建的標的沒有產業成員列，族群相關的研究不含它們。2026-09-08 以前有效的 `group_memberships`（`official_industry`）舊列不能當歷史分類：`valid_from` 是上市日（現行分類往回填），2026-09-07 整批換 id 前的族群標籤是錯的（[#773 決定](https://github.com/YiCheng0608/stock-lab/issues/773#issuecomment-6894054847)）。研究用的當時分類見[官方產業的逐月成員表](#官方產業的逐月成員表)。
- **除權息**（[#821](https://github.com/YiCheng0608/stock-lab/issues/821)）：
  - **上市 2005-01-24 以前的除權**：`TWT49UDetail` 對這段的含權列都回「無相關資料」，2005-01-25 起才有明細。這些事件照樣寫入，但現金股利、配股率留空，`details_json.factor_source` 是 `twt49u_reference`。還原因子用 `TWT49U` 的 `除權息參考價／除權息前收盤價`，和欄位推得出的因子是同一種官方比值，所以還原價、報酬、指標都不受影響；只有個股頁的除權息清單看不到拆分。例外是參考價與前收盤價差在 0.02 元內的列，因子照用 1：370 列裡只有 2343 精業 2004-12-20（10.50／10.49，差不到 0.1%）。2004-02-11～2005-01-24 共 370 列（2004 年 367、2005 年 3，[AC-1](https://github.com/YiCheng0608/stock-lab/issues/821#issuecomment-6916456620)）。
  - **2009 年以前有員工紅利轉增資的除權列**（[#891](https://github.com/YiCheng0608/stock-lab/issues/891)）：
    - **原因**：98-01-01 以前的官方參考價把員工紅利轉增資也算成配股（[寫入防呆](../DATA_SOURCES.md#寫入防呆)）。#891 以前的程式擋下的列共 997 列（三欄寫成 null）：其中 989 列是員工紅利造成，另外 8 列原因不同（下表）。997 列依市場與年分是上市 2005～2008 年 818 列、上櫃 2007～2008 年 178 列、上市 2018 年 1 列。
    - **影響**：價格因子本來就用官方 `除權息參考價／除權息前收盤價`，還原價不受影響；受影響的是只讀欄位的 V3 `cash_yield_12m`（[evidence 第五輪](../spec/evidence.md#第五輪v1v3)）。
    - **補法**：#891 的防呆把這 989 列判為通過，對 2005-01-25～2008-12-31 重跑 `corporate-actions sync --apply` 一次，寫回來源印的股東欄位。這些列的因子固定用官方比，要逐列和補前相同（#891 AC-2），所以不跑 `rebuild`。
    - **研究 DB 的寫入結果**（2026-11-21，run 8886，image 是 PR #894 head `7faa2c1e`）：
      - dry-run 與 `--apply` 都是 `changed_rows` 989、`new_rows` 0，其餘 1,585 列 `unchanged`。`factor_mismatches` 是下表上市 2005 年 2 列加上櫃 5 列。
      - 寫入後對同一區間跑 `corporate-actions check`，2,574 列裡不符的也是這 7 列。
      - 補前、補後全列 31,221 列逐列算因子，最大差 0，三欄有變的是 989 列（[#891 AC-2 回報](https://github.com/YiCheng0608/stock-lab/issues/891#issuecomment-7052720250)）。
      - 寫入後研究 DB 三欄都是 null 的列剩 368 列：360 列是 `twt49u_reference`，另外 8 列在下表。
      - V3 的 `--coverage-only` 中，「窗口內有三欄都是 null 的列」2008 年 0／8,971、2009 年 102／146,889（約 0.07%），2018 年 3／109,430（2723），其他年 0（[AC-4 回報](https://github.com/YiCheng0608/stock-lab/issues/891#issuecomment-7052791150)）。
    - **剩下 8 列**，三欄仍是 null，原因都不是員工紅利：

      | 列 | 原因 |
      | --- | --- |
      | 上市 3142 2005-09-01、3050 2005-10-07 | 官方的配股比欄位少（e −0.0101、−0.0032），原因未明 |
      | 上櫃 6156 2007-12-17 | 除權（權值 1.35），但來源的每仟股無償配股與現金都是 0，沒有配股率 |
      | 上櫃 6266 2008-09-03、5488 2008-09-15、5210 2008-09-18、5475 2008-11-07 | 官方的配股比欄位少（e −0.003～−0.012，差 0.021～0.035 元），原因未明 |
      | 上市 2723 2018-06-21 | 沒有員工紅利；明細印每千股 104 股，`權值+息值` 推得 104.34 股，差 0.0999 元 |

      上市 2005 年那兩列早於 V3 的窗口，其餘 6 列在窗口內（2007-12-02～2019-12-31）。
  - **上櫃 2007-04-23～2007-11-30 沒有除權息事件**：TPEx `exDailyQ` 在 2007-12 以前都回空表，舊版網址也只回當期。研究 DB 的上櫃日線卻從 2007-04-23 開始，所以這段上櫃日線在除權息日會假跌（2007-07、08 是除權息旺季）。研究工具不讀這段上櫃日線（[日線排除清單](#研究工具的日線排除清單)，[#821 決定](https://github.com/YiCheng0608/stock-lab/issues/821#issuecomment-6917103976)）。 MOPS 舊站的「公司股利分派公告資料彙總表」（`t108sb27`）有這段的除權、除息交易日與配發內容，但它只收現在還在的公司：2007 年有日線的 547 檔上櫃普通股裡，之後下市的 100 檔一檔都不在表裡（[查證](https://github.com/YiCheng0608/stock-lab/issues/821#issuecomment-6916792081)）。而且它是公告，沒有官方參考價可以核對因子，所以沒有用它補。
- **月營收**：MOPS 的 `t21sc03` 頁只列今天的公司，回補不到下市股的任何一個月。轉板公司上櫃那幾年的月份則接在上市標的上（[#781 AC-1](https://github.com/YiCheng0608/stock-lab/issues/781#issuecomment-6894356247)）。[#782](https://github.com/YiCheng0608/stock-lab/issues/782) 補其中補得到的部分，規則見 [DATA_SOURCES 的下市與轉板公司的月營收](../DATA_SOURCES.md#下市與轉板公司的月營收)：
  - **轉板**：`revenue transfers --apply` 把上櫃標的範圍內的月份從上市標的複製過來（0 個請求）。2026-11-15 在研究 DB 副本上實測（日線從 2017-03 起）：21 檔都通過同一家公司的核對，寫 1,360 列，重跑全部 `unchanged`，和上市標的逐列比對沒有不同。批 3～5 把日線往前補之後要再跑一次，補上新增的月份。
  - **下市股**：`revenue company-classify`，接著 `revenue company-backfill`，用 MOPS 單一公司查詢，只有仍公開發行的公司查得到。破產、合併消滅等「不繼續公開發行」的公司補不到，這部分的缺口會留下來，偏差方向仍對假設有利。等 #702 批 4 建完標的再發請求，請求數先貼在執行單，經統籌核准才補。
  - **怎麼跑**：三個命令都要 `research-db.json`，沒有就 exit 2；請求間隔、不發的時段、中止條件都寫在 DATA_SOURCES。研究 DB 同時只有一個 writer，由回補執行單（#702）的工程師在批次之間代跑，用 `--max-requests` 切成小段；被時段或失敗中止時 exit 2（`partial`），重跑接續。
  - **分類與 backfill**（[DATA_SOURCES 的下市股分類](../DATA_SOURCES.md#下市與轉板公司的月營收)）：`company-classify` 把每檔分成 `found`、`not_public`、`delisted_notice`（「該 … 上市公司已下市！」）、`foreign_exempt`（「外國發行人免申報本項資訊」）、`no_data`（「查無資料」「資料庫中查無需求資料。」）、`name_mismatch`。只有 `found` 由 `company-backfill` 補，其他各類都不發請求，`company-backfill --plan` 的 `classes` 列出各類檔數。固定頁面不算失敗；KY 的雙幣別表讀新台幣那欄（[#854](https://github.com/YiCheng0608/stock-lab/issues/854)）。
  - **run 8795 的重跑**（2026-11-20 01:36–01:49，`partial`，連續 3 次失敗停在 3697）：用 #854 的程式在研究 DB 副本重讀這次存下的 141 個回應，`failed` 16 只剩 TWSE 3638 2014-09 的 502；其餘 15 檔是 `foreign_exempt` 11、`delisted_notice` 2（3598、3682）、`no_data` 1（TPEx 5371）、`found` 1（1592 英瑞-KY）。副本上 `company-classify --plan` 是 167 檔、27 個請求：3638 與 3697 之後還沒問的 26 檔上市代號；已有存檔回應的 140 檔在 `answered`，不再問。舊程式同一副本是 42 個（多出的 15 檔回應認不得，會再問）。
  - **轉板後又下市**：上櫃 `transferred`、上市 `delisted` 的公司，`transfers` 的輸出列在 `twin_delisted`。上市那段由 `company-backfill` 補，補完再跑一次 `transfers`，上櫃那段才複製得到。
  - **剩下的缺口**：[#786](https://github.com/YiCheng0608/stock-lab/issues/786) 補完後量過，見下一節的[補完後的缺口](#補完後的缺口786)。

## 月營收與季報的下市股缺口（#781）

**缺口**：MOPS 的月營收頁（`t21sc03`）與季報頁（`t163sb04`）每次都用**今天**的上市、上櫃名單重新產生（頁上印的出表日期是查詢當天，舊月份也列著當時還沒上市的公司）。所以兩張表回補到的都只有現存公司：研究 DB 的 `monthly_revenues` 與 `fundamental_snapshots`（`mops_t163sb04`）在 `delisted`、`transferred` 標的上是 **0 列**。2026-11-15 量的時候，日線從 2017-08 起，有日線卻沒有月營收與季報的公司，上市約占 4～6%、上櫃約占 8～11%（2017～2019），2024 年降到 1～2%（[AC-1](https://github.com/YiCheng0608/stock-lab/issues/781#issuecomment-6894356247)）。轉板公司上櫃那段的月營收掛在同一家公司的**上市**標的上，那時上市標的沒有日線，研究工具用不到。條件缺值視為不符合，用到這兩張表的假設選股時會排除之後下市的公司，偏差方向對假設有利（[策略證據](../spec/evidence.md#第一輪x1x8)的加註）。

**目前狀態**（[#786](https://github.com/YiCheng0608/stock-lab/issues/786) 已在研究 DB 補完）
- **季報 EPS**：[#781](https://github.com/YiCheng0608/stock-lab/issues/781) 的工具從 MOPS 的季度 XBRL 整包補（`fundamentals xbrl-fetch`／`xbrl-apply`，[資料來源](../DATA_SOURCES.md#下市股的季度-epsxbrl-整包)）。整包收的是當季全部申報公司，含之後下市的。2013Q1～2024Q3 共 47 季。
- **月營收**：[#782](https://github.com/YiCheng0608/stock-lab/issues/782) 的工具：轉板的舊月份改接到上櫃標的；下市股用 MOPS 單一公司查詢補。
- 用到月營收或季報的已登記假設（S1～S3、X3、X4、X7、H1 歷史樣本外），要等統籌看過[補完後的缺口](#補完後的缺口786)才跑探索段。

**補完後剩下的限制**
- **季報**：
  - 只補 `delisted`／`transferred` 標的；它們要在季底到季底後 670 天內有日線（`quarterly_xbrl.EVIDENCE_WINDOW_DAYS`）。
  - 整包是 2025 年重新打包的，數字是現在的版本：事後更正過的季度，存的是更正後的值（和 `t163sb04` 相同）。
  - 代號重用（見上一節）：清單上 3 段舊公司的最後一根日線都在 2013 年以前（2008-08-25、2008-11-28、2011-11-07），整包從 2013Q1 起，所以寫進這 3 個標的的都是新公司的季報，不必用 `--exclude-file` 重跑。之後清單若加了 2013 年以後才結束的舊公司，以 `--exclude-file`（instrument id 的 JSON 陣列）重跑：
    - 它只擋之後的寫入，輸出的 `excluded_already_written` 是之前已寫進這些標的的列數。
    - 不是 0 時，先停下批次。把列數貼到 Issue，再刪 `fundamental_snapshots` 中 `source = 'mops_tifrs_zip'` 而且 `instrument_id` 在清單裡的列；`raw_payloads` 不動。
- **月營收**：單一公司查詢只查得到下市後仍公開發行的公司。破產或合併消滅、不繼續公開發行的公司（例如 2475 華映、2888 新光金）查不到，這類公司會一直缺值。剩下多少見下面。

### 補完後的缺口（#786）

2026-11-20 在研究 DB 用唯讀連線量。當時日線到 2026-11-13，已補完：

- 季報 EPS：run 8782、8794，共 4,752 列、199 檔。
- 月營收：轉板 run 8783、8862 寫 2,105 列、31 檔；下市股 classify run 8813、backfill run 8814、8861 寫 1,086 列、12 檔。

**分年、分市場**：普通股與 `ipo`，當年有日線的公司數／其中當年沒有任何月營收列的／其中當年沒有任何季報 EPS 列（`period_end` 在當年）的。`dormant` 每個市場只有 1 檔，都不缺，表裡不列。

| 年 | 市場 | active | delisted | transferred |
| --- | --- | --- | --- | --- |
| 2013 | 上市 | 782／8／10 | 69／64／1 | – |
| 2013 | 上櫃 | 566／0／0 | 72／69／3 | 26／4／0 |
| 2014 | 上市 | 800／8／10 | 68／62／2 | – |
| 2014 | 上櫃 | 594／0／0 | 72／70／0 | 25／3／2 |
| 2015 | 上市 | 823／8／10 | 62／56／0 | – |
| 2015 | 上櫃 | 623／0／0 | 74／72／1 | 21／3／1 |
| 2016 | 上市 | 847／8／10 | 61／55／2 | – |
| 2016 | 上櫃 | 652／0／0 | 69／67／2 | 19／2／1 |
| 2017 | 上市 | 867／8／10 | 55／49／2 | – |
| 2017 | 上櫃 | 671／0／0 | 62／60／0 | 19／0／1 |
| 2018 | 上市 | 896／8／10 | 50／44／0 | – |
| 2018 | 上櫃 | 702／0／0 | 55／53／0 | 16／0／0 |
| 2019 | 上市 | 915／8／10 | 41／35／3 | – |
| 2019 | 上櫃 | 721／0／0 | 47／45／2 | 17／0／1 |
| 2020 | 上市 | 927／8／10 | 35／29／1 | – |
| 2020 | 上櫃 | 739／0／0 | 41／39／5 | 13／0／0 |
| 2021 | 上市 | 945／8／10 | 27／21／2 | – |
| 2021 | 上櫃 | 750／0／0 | 31／30／0 | 13／0／2 |
| 2022 | 上市 | 969／8／10 | 20／15／4 | – |
| 2022 | 上櫃 | 777／0／0 | 27／26／1 | 10／0／2 |
| 2023 | 上市 | 997／8／10 | 11／6／0 | – |
| 2023 | 上櫃 | 794／0／0 | 22／21／2 | 7／0／0 |
| 2024 | 上市 | 1,033／8／10 | 9／4／2 | 1／1／0 |
| 2024 | 上櫃 | 824／0／0 | 15／14／2 | 4／0／1 |
| 2025 | 上市 | 1,068／8／10 | 6／2／6 | 1／1／1 |
| 2025 | 上櫃 | 866／0／0 | 9／8／9 | 3／0／3 |
| 2026 | 上市 | 1,098／8／10 | 3／1／3 | 1／1／1 |
| 2026 | 上櫃 | 896／0／0 | 5／5／4 | 2／0／1 |

合計（公司年）：active 23,142／112／140；delisted 1,118／1,022／59；transferred 198／15／17。

**季報 EPS 剩下的缺口**：
- **active**：上市每年缺的 8～10 檔都是存託憑證（`-DR`）。8 檔沒有月營收也沒有季報；泰金寶-DR、晨訊科-DR 有月營收，沒有季報。
- **delisted、transferred**：共 76 個公司年。
  - 34 個：當年的日線沒有跨過任何一個季底，例如 1 月就下市。
  - 26 個：缺的是 2024Q4 以後的季。整包只下載到 2024Q3，2025、2026 年的缺口大多是這個。
  - 16 個：日線跨過 Q1 季底，但 4、5 月就下市，整包裡沒有它們的 Q1：2013 年 3087、4801；2016 年 8053、6286；2017 年 1729；2019 年 2475、3519；2020 年 2499、1333、8287；2022 年 1507、2841、8406、4141；2024 年 2358、2443。推測是下市前沒有申報當季，沒有查證。

**月營收剩下的缺口**：下市股缺的幾乎都是這幾類。「缺的月份」是從 2013-01 或第一根日線的月份起、到最後一根日線的月份，沒有月營收列的月份。

| 類別 | 原因 | 公司 | 缺的月份 |
| --- | --- | --- | --- |
| `not_public` 130 檔 | 不繼續公開發行（破產、合併消滅等），單一公司查詢查不到 | 上市 54 檔、上櫃 76 檔，代號見下 | 2013-01～2026-09，共 9,382 個月 |
| `foreign_exempt` 18 檔 | 最後一個有日線的月份回「外國發行人免申報本項資訊」；`company-classify` 只問那個月，較早的月份沒問（[決定](https://github.com/YiCheng0608/stock-lab/issues/786#issuecomment-7023718411)） | 上櫃 1258、2928、4947、5281、6514、6554、8406、8418；上市 1262、2936、3638、3697、4141、4144、4984、5264、6422、8480 | 每檔是第一根日線（或 2013-01）到最後一根日線的整段，共 1,409 個月 |
| `no_data` 1 檔 | 最後一個月回「查無資料」 | 上櫃 5371 中光電（問的月 2026-08） | 2013-01～2026-08，164 個月 |
| `name_mismatch` 4 檔 | 查詢回的公司名稱和標的名稱不同，不寫 | 上櫃 4712 南璋；上市 2823 中壽、2833 台壽保、2837 萬泰銀 | 共 297 個月：4712 2013-01～2024-02、2823 2013-01～2021-12、2833 2013-01～2015-10、2837 2013-01～2014-09 |
| `delisted_notice` 2 檔 | 回「該 … 上市公司已下市！」 | 上市 3598 奕力、3682 亞太電 | 3598 2013-01～2016-05、3682 2013-08～2023-12，共 166 個月 |

`not_public` 的代號：
- 上市：1469、1507、1701、1704、1715、1724、1729、1902、2311、2315、2325、2358、2361、2437、2448、2456、2475、2499、2841、2847、2856、2888、3061、3080、3315、3383、3454、3474、3514、3519、3536、3559、3561、3573、3579、3584、3599、3698、4725、4733、5259、5280、5305、6131、6145、6172、6251、6286、6289、6702、8008、8078、8427、8497。
- 上櫃：1333、1566、1787、3068、3087、3089、3126、3144、3291、3299、3426、3428、3431、3452、3553、3562、3582、3642、3658、3662、4103、4130、4152、4180、4415、4429、4703、4762、4801、4803、4944、4945、4965、4987、5102、5255、5261、5266、5304、5317、5326、5349、5383、5384、5395、5466、5467、5480、5491、5505、5506、5820、6022、6105、6107、6135、6211、6238、6247、6250、6287、6298、6404、6457、6497、6594、6747、8053、8079、8082、8183、8266、8420、8913、8925、8934。

`found` 12 檔（上櫃 3202、6008、8287；上市 1592、1613、2384、2443、2809、2867、6288、6452、6806）從 2013-01 或第一根日線到最後一根日線都有月營收。1592、6452 上市前的月份回 `foreign_exempt`，不在日線範圍內。

**轉板（`revenue transfers`，run 8862）**：

- **名稱不同而略過，7 個**：轉板前後的公司名稱不同，不認作同一家，不複製。
  - 上櫃那段在 2013 年以後的有 4 檔：1256 F-鮮活→鮮活果汁-KY（缺 2013-01～2016-03）、2636 台驊→台驊控股（2013-01～2016-12）、4912 F-聯德→聯德控股-KY（2013-01～2015-05）、9946 三發→三發地產（2013-01～2013-09），共 125 個月。
  - 上市 6423 億而得-創轉回上櫃的億而得：上市那段 2024-05～2026-01 缺 21 個月。
  - 4104 東貿→佳醫、6230 超眾→尼得科超眾：上櫃那段在 2007～2010 年，早於月營收來源的起點 2013-01，不缺。
- **日線接不上而略過，7 個**：1408、1462、1807、2326、2396、2410、2479。兩段日線相隔 174～658 天；兩段都在 2013 年以前，不缺。
- **`twin_delisted`，15 家**：上櫃 `transferred`、上市 `delisted`。`transfers` 不複製，`company-backfill` 也只補 `found`。
  - 13 家（1107、1408、1462、1807、2326、2341、2381、2396、2410、2479、3053、3080、3142）兩段都在 2013 年以前。只有 3080 威力盟上市那段的 2013-01 缺 1 個月（`not_public`）。
  - 3454 晶睿、4733 上緯：上櫃那段（2007-04-23～2011-07-21、2009-01-15～2010-12-29）早於來源起點。上市那段是 `not_public`，沒有月營收：3454 是 2013-01～2026-03 共 159 個月（日線 2011-07-22～2026-03-18），4733 是 2013-01～2016-08 共 44 個月。這兩家已算在上面 `not_public` 的列裡。

上櫃轉板到上市、上市標的還在交易的 31 檔，上櫃那段的月營收都已複製（2,105 列）。

查詢腳本和輸出在 #786 的回報裡（[#781 AC-1](https://github.com/YiCheng0608/stock-lab/issues/781#issuecomment-6894356247) 的查詢加上 classify、transfers 的分類）。

## 回補怎麼跑

長工作一律用 `docker run -d` 的獨立容器跑，日誌寫在研究 volume 的 `/data/logs/`，不靠 session 的背景 shell：統籌或工程師換手、背景 shell 被收掉，都不會中斷它。每一段都可以中斷後重跑：`backfill` 從各段的 manifest 接續，已完成的日期不再請求；其他命令重跑冪等。

- **間隔**：`backfill`、`corporate-actions sync`、`trading-halts`、`revenue backfill`、`fundamentals backfill`、`events backfill`、`index-bars backfill`／`futures-history` 這些命令，對每個官方 host 至少間隔 3 秒（`worker.cli.BACKFILL_HOST_INTERVAL_SECONDS`）；daily 與它的 catchup 仍用各 host 自己的間隔。`revenue company-classify`／`company-backfill` 用自己的 5 秒（`monthly_revenue_company.INTERVAL_SECONDS`，#782）。
- **時段**：台北 21:15～23:30 不送請求（正式 daily 在跑）。日行情用 [`tools/research/history_backfill.py`](../../tools/research/history_backfill.py) 逐月跑：由新到舊，一個月一次 `backfill`（約 10 分鐘）；每個月開始前，台北時間落在 21:00～23:30 時，先等到 23:30。進度與每個月的結束碼記在 `/data/logs/history-backfill.jsonl`，重跑時跳過已完成的月份。其他命令都是幾分鐘到一小時，在 21:00 之前開始。
- **耗時**：副本實測每個交易日約 15～26 秒（2026-11-14，3 秒間隔；上市 3 個、上櫃 3 個請求，加上每批 1 個 MOPS 清單，2008 年以前每月多 1 個 `MI_5MINS_HIST`）：2012-04-25～05-08 九個交易日 152 秒、2004-02-11～02-20 八個交易日 153 秒、2014-11-24～12-05 十個交易日 258 秒。這些是短副本上的數字。[#715](https://github.com/YiCheng0608/stock-lab/issues/715) 之前，每個 collect 收尾都把 DB 裡全部的 Event 重新投影成新聞（每筆約 0.23 ms），所以每天會再多一段隨回補長度變長的時間：批 1 從 2024-09 的每天約 28 秒長到 2023-12 的 47 秒。修正後 collect 只投影自己寫入的 Event，收尾約 1 秒，不再隨歷史變長（同一天的重放，Event 2.3 萬／8.7 萬／17.5 萬筆時：改前 6.5／17.2／34.8 秒，改後 0.7／0.4／0.9 秒）。所以每個交易日約等於 collect 本身的 16～18 秒，加上約 1 秒的簿記。批 3～5 約 3,900 個平日，估計約 20 小時的請求時間，再加上每晚 21:00～23:30 的暫停。回補容器要用含 #715 修正的 image 才會變快。
- **每月的啟動段**：從程序開始到這個月的 backfill run 建立。[#722](https://github.com/YiCheng0608/stock-lab/issues/722) 之前，每個月的 `backfill` 都跑一次 `init_db`，即使 DB 已經在 head，也會對整個 DB 跑兩次 `PRAGMA integrity_check`。這段跟著 DB 大小變長：批 1 從 2024-09 的 80 秒長到 2023-07 的 147 秒；DB 到 4.8 GB 時，容器在 `--memory 3g` 下快取裝不下整個 DB，變成 360～470 秒。修正後，DB 已經在 head 就跳過 `init_db`（`app.db.ensure_schema`，daily 從 #150 起也是同一條規則），啟動段約 1～2 秒，不隨歷史變長。在 4.8 GB 的副本上重放同一天兩次：改前 320、398 秒，改後 1.3、1.5 秒。所以每個月只剩各交易日的時間。DB 落後 head 時，第一個月照舊跑完整的 migration 與整庫檢查。回補不再每月檢查整庫，改由 `history_backfill.py` 在每批結束時自動跑一次 `PRAGMA integrity_check` 與 `foreign_key_check`；最後一個月失敗了也照跑。結果寫成 `history-backfill.jsonl` 的一列 `integrity`（各自的結果與秒數），不是 `ok` 或有外鍵違反就以 exit 3 結束。4.8 GB 的 DB 在 `--memory 3g` 下約 6～7 分鐘。#702 的驗收表引用這一列。
- **舊版面**：實測過的三段（2004-02、2007-04、2012-04～05、2014-11～12）找出三個舊版面，已處理（[各來源最早可得](../DATA_SOURCES.md#各來源最早可得)）：2009 年以前 `MI_INDEX` 沒有指數表、T86 較舊版面的外資欄（2012-05 實測，改版日未確認）、TPEx 法人 2014-12 起的 16 欄版面。版面在實測日之間的其他改版沒有逐一確認，例如 TPEx 法人改成 24 欄的那天：parser 認不得的版面，可能讓那天法人欄是空值而沒有 warning（T86），或記核心 warning 讓那天變 `partial`（TPEx），所以每一批讀回時都要查各欄非空的比例（回補執行單的驗收）。
  - `MI_INDEX` 價格指數表的加權指數列名，2019-04-29 是「加權股價指數」，已存 raw 的其他日子都是「發行量加權股價指數」。兩個名稱都接受，完全比對（`sources.TWSE_INDEX_NAMES`，[#764](https://github.com/YiCheng0608/stock-lab/issues/764)）。研究 volume 已存的 2019-04-01～2024-09-27 有價格指數表的 1,340 天裡，只有這一天是舊名稱。名稱不在清單裡時，那天會因為找不到 TAIEX 列而整天失敗，錯誤是 `did not contain one finite positive price-index TAIEX row`。這時要看 raw 的列名，再決定要不要加進清單。

### 建研究 DB

由正式 DB 的唯讀副本開始（[取正式 DB 的唯讀副本](LOCAL.md#取正式-db-的唯讀副本)），複製進研究 volume；新建的 volume 是 root 擁有，先 chown 給容器使用者 1000：

```bash
# 換值：D＝副本目錄；IMG＝含 #692 的 backend image（正式在跑的 tag 或任務 image）
docker volume create stock-lab-research
MSYS_NO_PATHCONV=1 docker run --rm --network none -u 0 -v stock-lab-research:/data -v "$D":/src:ro "$IMG" \
  sh -c 'cp /src/stock.db /data/stock.db && mkdir -p /data/raw /data/locks /data/logs \
    && printf "{\"purpose\": \"research_history\", \"issue\": 692}\n" > /data/research-db.json \
    && chown -R 1000:1000 /data'
```

**研究標記 `research-db.json`**：容器裡研究 volume 與正式 volume 都是 `/data/stock.db`，路徑分不出來，所以建研究 DB 時在 `stock.db` 旁邊寫這個檔（內容的 `purpose` 是 `research_history`）。`history_backfill.py` 要它存在、而且有設 `STOCK_SESSION_BASIS_START` 才起跑，否則印 `refused`、exit 2。正式 volume 永遠不放這個檔。

**種子列的 raw 檔在正式 volume**：上面只複製 `stock.db`、`raw/` 是空的，所以研究 DB 從正式 DB 帶來的 `raw_payloads` 列（`collected_at` 早於建立研究 DB 的時間），檔案只在正式 volume `stock-lab_stock-data`，研究 volume 沒有副本。2026-11-15 有 11,780 列，檔案在正式 volume 都完整（[#772 回報](https://github.com/YiCheng0608/stock-lab/issues/772#issuecomment-6892968517)），統籌決定不補複製（[6893166947](https://github.com/YiCheng0608/stock-lab/issues/772#issuecomment-6893166947)）。稽核研究 DB 的 raw 時，這些列要對正式 volume 判讀：[`tools/audit/raw_files.py`](../../tools/audit/raw_files.py) 加上 `--fallback-raw-dir`，例如 `-v stock-lab-research:/data:ro -v stock-lab_stock-data:/prod:ro … --db /data/stock.db --fallback-raw-dir /prod/raw`，在正式 volume 完整的列記在 `whole_in_fallback`，不列為壞檔。

### 跑一批

```bash
# 共同的參數；換值：IMG 同上
R=(-v stock-lab-research:/data -e STOCK_DATA_DIR=/data \
   -e STOCK_SESSION_BASIS_START=2004-02-11 -e STOCK_INDEX_HISTORY_START=2004-02-01 \
   -e STOCK_HISTORY_CREATE_UNMATCHED=1)
# 日行情與籌碼，例如批 1（2019-01-02～2024-09-27）
MSYS_NO_PATHCONV=1 docker run -d --name research-bars-1 "${R[@]}" "$IMG" \
  sh -c 'python -B tools/research/history_backfill.py --from 2019-01-02 --to 2024-09-27 > /data/logs/bars-1.json 2> /data/logs/bars-1.err'
# 進度
MSYS_NO_PATHCONV=1 docker run --rm --network none -v stock-lab-research:/data "$IMG" tail -n 3 /data/logs/history-backfill.jsonl
```

其他命令接在同樣的 `docker run -d … "${R[@]}" "$IMG" sh -c 'python -B -m worker.cli <命令> > /data/logs/<名稱>.json 2>&1'` 後面：

| 資料 | 命令 | 備註 |
| --- | --- | --- |
| 除權息 | `corporate-actions sync --start-date 2004-01-01 --end-date 2024-09-30 --apply` | 每月 TWSE、TPEx 各 1 個請求，含權的列另查明細；TWT49U 的起日自動夾到 2003-05-05。民國 99 年（2010）以前 TWT49U 的資料日期寫成兩位數民國年（`93年02月11日`），[#818](https://github.com/YiCheng0608/stock-lab/issues/818) 起才讀得懂；之前的 image 在第一個月就以 `TWSE TWT49U row without a code or date` 失敗，要用含 #818 的 image 跑。早於 2005-01-25 的含權列沒有明細，要用含 [#821](https://github.com/YiCheng0608/stock-lab/issues/821) 的 image：之前的 image 會跳過這些列、run 以 `partial` 結束；#821 起寫成欄位空白、以參考價還原的列（輸出的 `reference_factor_rows`，見上面的[已知限制](#下市與轉板的標的)）。2009 年以前有員工紅利轉增資的除權列要用含 [#891](https://github.com/YiCheng0608/stock-lab/issues/891) 的 image，之前的 image 會把三欄寫成 null（同一節）。上櫃 2007-11 以前 `exDailyQ` 沒有列 |
| 指數日 K | `index-bars backfill --from-month 2004-02 --to-month 2007-12`，之後每 48 個月一段 | 一次最多 48 個月（`MAX_MONTHS`） |
| 月營收 | `revenue backfill --months 60 --end-month 2018-08`、`--end-month 2023-08`，再 `--months 8 --end-month 2013-08` | 從 2013-01 起（#692 D4） |
| 季報 | `fundamentals backfill --quarters 20 --end-quarter 2017Q4`，再 `--quarters 20 --end-quarter 2022Q4` | 從 2013Q1 起 |
| 季報（下市、轉板股） | `fundamentals xbrl-apply --start 2013Q1 --end 2024Q3 --dir /xbrl`（整包目錄唯讀掛到 `/xbrl`，由 `fundamentals xbrl-fetch` 在 09:00～20:30 下載；Git Bash 要 `MSYS_NO_PATHCONV=1`，否則 `/xbrl` 被改寫成 Windows 路徑） | **每一批建了新的下市標的之後都跑一次**：已寫的列 `unchanged`，只寫新標的；先和 `t163sb04` 核對，不同就停（#781）。約 1 小時，照上面以 `docker run -d` 跑、日誌寫 `/data/logs/`；沒有 `research-db.json` 時拒絕，批次持有維護模式時 exit 75 |
| 減資停止買賣 | `trading-halts --start 2011-01-01 --end 2024-09-30` | 起日夾到各來源的起始日（TWSE 2011、TPEx 2013），輸出 `not_published_before`。恢復日在 2015-04-16 以前的 89 列 TWSE 資料，最後交易日要用已存的日線推（[DATA_SOURCES](../DATA_SOURCES.md#減資停止買賣)，#776）：日線還沒補到的月份會拒絕（`no bar before the resumption`），所以要等那段日線補完再跑：批 4 後跑一次（2012-05～2015-04，含批 3 的 2015 年），批 5 後再跑一次（2011-01～2012-04）。推不出的列記在 `conflicts`（不是 `rejected`），每列記 warning `TWSE trading halts rejected: …`，run 是 `partial`。批 4 之後應看到 TWSE `inferred_from_bars` 65、`updated` 3（2408、2438、3536：日期不變，只有 `details_json` 多了晚列的 `same_resumption_rows`，2408 的 `last_trade_date_basis` 改成 `inferred_from_bars`）、`conflicts` 22（恢復日 2011-01～2012-01，`no bar before the resumption`）、`rejected` 0、`removed` 0，其他列 `unchanged`（2026-11-16 在批 4 後的副本實測，PR #789）。批 5 之後，那 22 列由 `conflicts` 轉成寫入 |
| 休市表 | `trading-calendar --year 2021 --year 2022` | 2020 年以前沒有內容 |
| 週末交易日（#790） | 三步，照順序跑：<br>1. `python -B tools/research/history_backfill.py --from 2004-02-11 --to 2018-12-31 --weekend-sessions`（用 `history_backfill.py` 的那行 `docker run -d`，不是 `worker.cli`）<br>2. 含週末交易日的每個月，各跑一次 `index-bars backfill --from-month <月> --to-month <月>`<br>3. `indicators --rebuild` | 補月份模式沒送的星期六、星期日（`OFFICIAL_WEEKEND_SESSIONS`，[DATA_SOURCES](../DATA_SOURCES.md#交易日的判定與週末交易日)）。<br>**為什麼要另跑**：已完成的月份，request key 是 success，不會再送；所以每個週末交易日各跑一個單日 backfill。progress 檔記 `weekend` 行，和 `month` 行分開，暫停與最後的整庫檢查和月份模式相同。<br>**第 2 步**：單日 backfill 從 `MI_INDEX` 寫 TAIEX 收盤；重跑 `index-bars` 後，那天的 `no_close_row` 會變成 `upgraded`。`index-bars` 不讀已存 raw，每月重發 4 個請求。<br>**請求數**：單日 backfill 每天約 11 個：上市 6（含 3 個名冊 OpenAPI）、上櫃 4、MOPS 1，是 2026-11-16 在副本上補 2012-12-22 的實測數；2012-05 以前沒有 T86，2009 年以前多 1 個 `MI_5MINS_HIST`。`index-bars` 每月 4 個。總數約為「天數 × 11 ＋ 月數 × 4」，清單的 23 天分在 22 個月，約 253 ＋ 88 ＝ 341 個請求。<br>**耗時**：副本上每天約 3.5 分鐘（這次為了不和批 5 疊加，請求間隔拉到 30 秒；照預設 3 秒會更短），加上最後一次整庫檢查約 14 分鐘（13.5 GB 的副本） |
| 上櫃舊版 `0.00` 價格的修正（#819） | 兩步：SQL 刪除＋`no-trade-days --start 2007-04-23 --end 2011-11-11`，命令全文見下節[上櫃舊版 0.00 價格的修正](#上櫃舊版-000-價格的修正819) | 只跑一次，跑完後才跑 `indicators --rebuild` |

回補日線或除權息之後，對研究 DB 跑 `indicators --rebuild`（研究工具自己算報酬，不讀指標；要用 API 或回測時才需要）。

### 上櫃舊版 0.00 價格的修正（#819）

2007-04-23～2011-11-11 的上櫃 `dailyQuotes` 在沒有一般交易時，四個價格都填 `0.00`（[DATA_SOURCES](../DATA_SOURCES.md#官方無成交日)）。#819 之前的 parser 把這種列寫成收盤價 0 的日線，研究 DB 有 14,121 根：234 檔，全部是 `source='tpex'`，各年 2007 年 1,351、2008 年 4,980、2009 年 3,158、2010 年 1,973、2011 年 2,659。正式 DB 從 2023-09 起，沒有這種列。

用含 #819 的 image 重跑 `backfill --force` 修不好，原因有兩個：

- collect 只 upsert 本次解析出的列，不刪已存的列。在副本上實測 2011-11-01，以 `overwrite=True` 寫入後，16 根照樣留著。
- `no-trade-days` 不替已有 bar 的那天寫無成交日。

所以先刪列，再從已存 raw 重建（統籌決定 [6915873985](https://github.com/YiCheng0608/stock-lab/issues/819#issuecomment-6915873985)）。不發請求。

1. **前提**：
   - 用含 #819 的 image（`IMG`）。修正之後研究 DB 的各批回補，包括 #790 的週末交易日，也都要用含 #819 的 image。區間內還有 6 個週末交易日沒補：2007-06-23、2007-09-29、2009-01-10、2009-01-17、2009-06-06、2010-02-06。用舊 image 補，0 價日線會悄悄回來；在修正之前補，第 2 步的數目會對不上。
   - 研究 DB 當下沒有寫入者：`docker ps` 沒有 `research-*`、`task-702-*` 的寫入容器，`maintenance status` 是 `off`。`/data/locks/` 裡的 `.lock` 是 flock 檔，持有者結束後檔案還在，不能拿來判斷。
   - 開維護模式。手動的 `on` 沒有心跳，`off` 之前 backfill 與 backtest 都拒絕起跑，`no-trade-days` 不受影響：

   ```bash
   MSYS_NO_PATHCONV=1 docker run --rm --network none -v stock-lab-research:/data "$IMG" python -B -m worker.cli maintenance status --data-dir /data
   MSYS_NO_PATHCONV=1 docker run --rm --network none -v stock-lab-research:/data "$IMG" python -B -m worker.cli maintenance on --reason "#819 0.00 price repair" --data-dir /data
   ```

2. **刪除**：在一個 transaction 裡做，條件寫死。DELETE 之前先在同一個 transaction 裡記下修正前的資料：
   - 這段日期兩個交易所的 `no_trade_days`（印出 `no_trade_before`）。
   - 要刪的（`instrument_id`、`trading_date`）。

   要刪的數目、刪除數或刪除後的數目不是 14,121／14,121／0 時，rollback 並以 exit 1 停下，印出各年的數目。數目都對時，才把修正前的資料寫進 `/data/logs/no-trade-819-before.json`，然後 commit。對不上時不要改常數重跑：把印出的 `no_trade_before`、`before` 與 `by_year` 貼在 Issue 問統籌。

   ```bash
   MSYS_NO_PATHCONV=1 docker run --rm -i --network none -v stock-lab-research:/data "$IMG" python -B - <<'PY'
   import json, sqlite3, sys
   SAVED = "/data/logs/no-trade-819-before.json"
   WHERE = """FROM market_bars WHERE source = 'tpex'
     AND open = 0 AND high = 0 AND low = 0 AND close = 0
     AND trading_date BETWEEN '2007-04-23' AND '2011-11-11'
     AND instrument_id IN (SELECT id FROM instruments WHERE exchange = 'TPEx')"""
   NO_TRADE = """SELECT i.exchange, n.instrument_id, n.trading_date
     FROM no_trade_days n JOIN instruments i ON i.id = n.instrument_id
     WHERE n.trading_date BETWEEN '2007-04-23' AND '2011-11-11'"""
   conn = sqlite3.connect("/data/stock.db", isolation_level=None)
   conn.execute("BEGIN IMMEDIATE")
   no_trade = conn.execute(NO_TRADE).fetchall()
   no_trade_before = {ex: sum(r[0] == ex for r in no_trade) for ex in ("TPEx", "TWSE")}
   keys = conn.execute("SELECT instrument_id, trading_date " + WHERE).fetchall()
   by_year = {}
   for _, day in keys:
       by_year[day[:4]] = by_year.get(day[:4], 0) + 1
   deleted = conn.execute("DELETE " + WHERE).rowcount
   after = conn.execute("SELECT count(*) " + WHERE).fetchone()[0]
   result = {"no_trade_before": no_trade_before, "before": len(keys),
             "by_year": by_year, "deleted": deleted, "after": after}
   if (len(keys), deleted, after) != (14121, 14121, 0):
       conn.execute("ROLLBACK")
       print(json.dumps({**result, "status": "rolled_back"}))
       sys.exit(1)
   with open(SAVED, "w") as out:
       json.dump({**result, "no_trade_keys": no_trade, "deleted_keys": keys}, out)
   conn.execute("COMMIT")
   print(json.dumps({**result, "status": "committed", "saved": SAVED}))
   PY
   ```

3. **重建**：照[跑一批](#跑一批)的 `docker run -d … "${R[@]}" "$IMG"` 跑 `python -B -m worker.cli no-trade-days --start 2007-04-23 --end 2011-11-11`，輸出寫 `/data/logs/no-trade-819.json`。
   - 預期 `status: success`、`missing: 0`、`unmatched: 0`。
   - 輸出的 `rows` 是這段日期兩個交易所現有的列數總和，不是新增數。新增數看第 4 步。
4. **讀回**：以唯讀連線（`mode=ro`）比對第 2 步存的修正前資料。volume 不加 `:ro`：`no-trade-days` 結束後 DB 是 WAL 模式、旁邊沒有 `-shm`，唯讀掛載時 `mode=ro` 開不了（[#486](https://github.com/YiCheng0608/stock-lab/issues/486)，副本演練實際遇到）。預期：
   - `no_trade_days` 新增 TPEx 14,121、TWSE 17，移除 0。
   - TPEx 新增的（標的、日期）和刪掉的完全相同。
   - 上櫃四價皆 0 的日線 0 根、部分價格為 0 的 0 根（不限日期）。

   TWSE 的 17 列是 2479 和立（2007-05-02～05-04）與 2494 廣業科（2008-10-01～10-21）。這兩檔的 instrument 是回補後段才建立的，當初那幾天的 collect 寫無成交日時還沒有。這和 #819 無關，統籌接受。不符預期時 exit 1。

   ```bash
   MSYS_NO_PATHCONV=1 docker run --rm -i --network none -v stock-lab-research:/data "$IMG" python -B - <<'PY'
   import json, sqlite3, sys
   saved = json.load(open("/data/logs/no-trade-819-before.json"))
   NO_TRADE = """SELECT i.exchange, n.instrument_id, n.trading_date
     FROM no_trade_days n JOIN instruments i ON i.id = n.instrument_id
     WHERE n.trading_date BETWEEN '2007-04-23' AND '2011-11-11'"""
   BARS = """SELECT count(*) FROM market_bars b JOIN instruments i ON i.id = b.instrument_id
     WHERE i.exchange = 'TPEx' AND """
   conn = sqlite3.connect("file:/data/stock.db?mode=ro", uri=True)
   before = {tuple(r) for r in saved["no_trade_keys"]}
   after = set(conn.execute(NO_TRADE).fetchall())
   added, removed = after - before, before - after
   added_by = {ex: sum(r[0] == ex for r in added) for ex in ("TPEx", "TWSE")}
   tpex_added = {(r[1], r[2]) for r in added if r[0] == "TPEx"}
   deleted = {tuple(r) for r in saved["deleted_keys"]}
   zero = conn.execute(BARS + "b.open = 0 AND b.high = 0 AND b.low = 0 AND b.close = 0").fetchone()[0]
   some = conn.execute(BARS + "(b.open = 0 OR b.high = 0 OR b.low = 0 OR b.close = 0)").fetchone()[0]
   result = {
       "no_trade_before": saved["no_trade_before"],
       "no_trade_after": {ex: sum(r[0] == ex for r in after) for ex in ("TPEx", "TWSE")},
       "added": added_by, "removed": len(removed),
       "tpex_added_equals_deleted": tpex_added == deleted,
       "tpex_zero_bars": zero, "tpex_some_zero_bars": some,
   }
   ok = (added_by == {"TPEx": 14121, "TWSE": 17} and not removed
         and tpex_added == deleted and zero == 0 and some == 0)
   print(json.dumps({**result, "status": "ok" if ok else "unexpected"}))
   sys.exit(0 if ok else 1)
   PY
   ```

   - 接著跑 `PRAGMA integrity_check`，結果要是 `ok`。17 GB 的副本在 `--memory 3g` 下約 22 分鐘，要在 21:00 之前開始。
   - 讀回的輸出與 integrity_check 的結果貼在 #702 的 AC-8。
   - 最後關維護模式：`… "$IMG" python -B -m worker.cli maintenance off --reason "#819 0.00 price repair done" --data-dir /data`（前綴同第 1 步；`off` 也要 `--reason`）。
5. 之後才跑 `indicators --rebuild`（[跑一批](#跑一批)表下的說明）。它也要等 [#821](https://github.com/YiCheng0608/stock-lab/issues/821) 的除權息。

**副本上的演練**（branch 上的新程式，只讀已存 raw）：

- **照本節命令逐字演練**（2026-11-16 20:43 取的研究副本，volume `task-819_rehearsal`；raw 以 `--mount …,volume-subpath=raw,readonly` 掛研究 volume 的 `raw/`）：
  - 第 1 步：`status` 是 `off`，`on` 之後是 `owner: manual`。
  - 第 2 步：`no_trade_before` 是 TPEx 0、TWSE 5,898，刪除 14,121，committed。
  - 第 3 步：`success`、`missing 0`、`unmatched 0`，約 3 分鐘。
  - 第 4 步讀回：TPEx +14,121、TWSE +17、移除 0，新增的鍵和刪掉的相同，0 價日線 0 根，`status: ok`；`integrity_check` ok（22 分鐘）；`maintenance off`。
  - 同一個副本再跑一次第 2 步：`before 0`，rolled_back，exit 1。
- **另一份副本的逐日比對**（19:44 取的研究副本，用 `replay819.py repair` 刪除並重建，不是本節的腳本）：用新程式重放這段 1,146 天已存的 TPEx `dailyQuotes` raw，比對剩下的 615,959 根 TPEx 日線：列數、開高低收、成交股數、成交金額與 `turnover_status` 逐列相同。沒有標的因此變成沒有日線。
- 腳本與輸出：`C:/Users/YiCheng/stock-lab-data/evidence/819/`（`SHA256SUMS`）。

### 舊日期 collect 不改寫標的類型與狀態（#838）

官方名單一律是今天抓的：上市、上櫃的公司主檔、ETF 清單，以及上市的 `company/newlisting`（保留 2011 年以來的每一筆上市）。[#838](https://github.com/YiCheng0608/stock-lab/issues/838) 之前，collect 用回補的那一天判斷「上市 60 天內」，再把結果寫回每個既有標的：

- 上市日在回補日前 60 天內的公司，被標成 `ipo`；回補越早的月份越後跑，類型停在最後一次被改的那天。
- 名單上的每個代號，包括 `newlisting` 有、主檔已經沒有的下市公司，狀態都被改回 `active`。

#702 批 5 因此把 8 檔 `ipo delisted` 改回 `active`，另有 23 檔的 `stock`／`ipo` 被翻過來，#786 少寫 194 列 EPS（[#702 提問](https://github.com/YiCheng0608/stock-lab/issues/702#issuecomment-6934972606)）。

**規則**：`pipeline.lists_are_current(score_date)`。

- collect 的日子早於 `latest_weekday(今天)`（台北日期；週末時是上一個星期五）時，名單只用來建新標的。既有標的不改 `instrument_type` 與 `status`；名稱、產業、上市日照舊更新。
- 「今天」在 collect 開始、送請求之前取一次。所以當天的 collect 拖過午夜才寫入，仍算當天。
- 舊日期 collect 建新標的時，`newlisting` 有、主檔沒有、上市日離今天超過 60 天的代號，已經不在今天的名單上。這種標的照 `create_history_instrument` 的規則建成 `transferred`（另一交易所有同代號）或 `delisted`，並寫一列 `instrument_status`；類型照那筆紀錄。
  - 這樣做是因為狀態同步（`plan_instrument_status`）只在 `snapshot_feeds` 的 collect 跑，回補與 catch-up 不跑，不然它們會一直停在 `active`（[#840 review](https://github.com/YiCheng0608/stock-lab/pull/840#issuecomment-7007687965)）。
  - 上市日在 60 天內的，是主檔還沒收錄的新上市，照舊建成 `active`。
- 每日 collect（今天，週末交易日也算）照舊改寫。
- 日線、籌碼的寫入不受影響。dormant 標的的恢復照 `reactivate_dormant` 自己的規則。

**修復已被改掉的列**：[`tools/research/restore_instruments.py`](../../tools/research/restore_instruments.py)。

- 狀態：照 `data_quality` 最新一列 `instrument_status`。每次狀態改變、每個回補建的標的都有這一列，舊的改寫沒有寫。
- 類型（只限 `stock`／`ipo`）：用 DB 裡最新一份名單 capture，以收到那天判斷 60 天內上市（`instrument_repair._latest_lists`，和那天的每日 collect 相同）。名單上沒有的標的不改類型。
- 只改這兩欄；沒有研究標記 `research-db.json` 時 exit 2，正式 DB 不能用它修。
- 預設 dry-run。`--apply --expect-changes N` 在一個 transaction 裡寫入，列數不是 N 就不寫、exit 1。
- `--reference <正式 DB 唯讀副本>` 在每一列附上正式 DB 的值，並列出修完後兩邊共有、類型或狀態仍不同的標的（`differs_from_reference_after`）。正式 DB 每天照今天的名單重寫類型，所以兩邊應該相同。
- 讀不到名單 capture、raw 檔或 reference 時，印 `error`、exit 3，不寫入；列數不符是 exit 1。
- 重跑冪等。
- **為什麼一定要看 reference**：有兩種情況，工具自己判斷不了，都要靠 reference 比對擋下。
  - **重新上市**：下市或轉板的代號重新上市時，狀態變回 `active`，但不會寫 `instrument_status` 列。工具照最新一列，會把它改回 `delisted`／`transferred`。
  - **名單 capture 舊了**：類型以最新一份名單 capture 的日子判斷。capture 比今天舊時，接近 60 天邊界的公司可能這邊是 `ipo`、正式 DB 是 `stock`。輸出的 `lists.<交易所>.age_days` 是 capture 距今的天數，超過 1 天時 `warnings` 會列出來。

**代跑步驟**（研究 DB 同時只有一個寫入者，由 #702 的工程師做；IMG＝含 #838 的 image）：

1. 前提同 [#819 第 1 步](#上櫃舊版-000-價格的修正819)：沒有其他寫入容器，開維護模式。
2. 取一份新的正式 DB 唯讀副本 `$D`（[LOCAL](LOCAL.md#取正式-db-的唯讀副本)），在 21:00 前開始。
3. dry-run：

   ```bash
   MSYS_NO_PATHCONV=1 docker run --rm --network none -v stock-lab-research:/data -v "$D":/prod:ro "$IMG" \
     sh -c 'python -B tools/research/restore_instruments.py --reference /prod/stock.db > /data/logs/restore-838-plan.json'
   ```

   - 預期 `differs_from_reference_after` 是空的，每一列的 `reference` 都等於修後的值。
   - 不是時不要 apply，把輸出貼在 #702 問統籌。
   - 有 `warnings`（名單 capture 超過 1 天）時，逐列看 `ipo`／`stock` 不同的是不是剛跨過 60 天。
   - exit 3（`error`）時不要重跑 apply，把輸出貼在 #702。
4. apply：同一行加 `--apply --expect-changes <第 3 步的 count>`，輸出寫 `/data/logs/restore-838-apply.json`。
5. 再跑第 3 步一次，預期 `count: 0`、`differs_from_reference_after` 空的，然後關維護模式。
6. 之後才補跑 #786 的 `xbrl-apply` 與 `company-classify`。

**副本演練**（2026-11-17）：

- 研究副本：09:56 用 `copy_db.py` 取的研究副本，volume `t838-research-copy`，2,838 檔；raw 以 `--mount …,volume-subpath=raw,readonly` 掛研究 volume 的 `raw/`；名單 capture 是 11/16 收的。
- 正式副本：AC-2 那份，2,450 檔，最新交易日 2026-11-16。
- 結果：
  - dry-run 53 列，apply 53 列，再跑 0 列。只動 `instrument_type`／`status`，其他欄位與檔數不變。
  - 兩邊共有的 2,450 檔：修前類型或狀態有 53 檔不同，修後 0 檔。
- 53 列的組成：
  - **批 5 的 32 列**：
    - 狀態都回到 #786 副本（批 5 之前）的值，8 檔 `ipo delisted` 都回到 `delisted`。
    - 類型有 23 列回到副本的值。另外 9 列，副本本身就是批 4 回補 2012 年留下的 `ipo`（2012-03～04 上市，例如 2727 王品）；研究 DB 現在的 `stock` 和正式 DB 相同，工具不動它們。
  - **批 1～4 留下的 30 列**：
    - 17 檔 2012～2021 年上市、已下市或轉板的公司被改回 `active`，例如 2867 三商壽、3682 亞太電。
    - 13 檔 2026-09～11 上市的 `ipo` 被改成 `stock`。

正式 DB 沒有這種殘留：比對 `instruments` 與 `data_quality` 最新狀態，0 列不一致（[#838 AC-2](https://github.com/YiCheng0608/stock-lab/issues/838#issuecomment-6935482280)）。每日 collect 每天都會改回類型；正式 DB 也沒有回補到會把下市公司改回 `active` 的日子。

### 研究工具的分段

研究工具預設的分段是探索段 2024-09-30～2025-12-31、驗證段 2026-01-01 起（`evidence_lib.SEGMENTS`）。要在研究 DB 上用回補的範圍，兩段都要以 `--segment` 給（`<exploration|validation>:<第一天>:[最後一天]`，探索段要在驗證段開始前結束）：

```bash
python -B tools/research/feature_evidence.py --db /data/stock.db --out /data/out/fe \
  --segment exploration:2019-01-02:2019-12-31 --segment validation:2020-01-02:2020-01-31
```

這裡的 `--segment` 只是讓既有的兩個工具能在研究 DB 上指定日期（例如確認工具讀得到回補的資料）。新策略探索的分段已在 [策略證據「分段」](../spec/evidence.md#分段) 寫死（探索段到 2019-12-31、驗證段 2020-01-02～2024-09-27，[#697](https://github.com/YiCheng0608/stock-lab/issues/697)），探索工具另開單，參數寫死在程式裡；回補完成前不要在回補的歷史上跑整段的特徵證據（#692 決定）。`portfolio_research.py --hypothesis` 的凍結假設不接受 `--segment`。

### 研究工具的日線排除清單

[`tools/research/bar_exclusions.json`](../../tools/research/bar_exclusions.json) 列出研究工具不讀的股票日線（[#839](https://github.com/YiCheng0608/stock-lab/issues/839)）。DB 不改，日線照樣存著。

**誰讀這份清單**：`research_report.benchmark_universe` 與 `benchmark_bars` 是 `stock`／`ipo` 日線的同一個查詢，兩個都跳過清單裡的列。用到它們的工具都不會讀到這些列：
- `evidence_lib.load_panel`：`feature_evidence`、`candidate_scorecard`。
- `portfolio_research.load_market`：`explore_research`、`mainstream_research`、`trade_research`、`portfolio_research`、經 `trade_research.load` 讀的 `round4_research`，以及經 `explore_research.load_context` 讀的 `round5_research`、`round6_research`。
- `research_report` 的基準一。
- 另外直接數 `market_bars` 的三處，也用 `research_report.excluded_bar_counts`／`last_kept_bars` 扣掉清單裡的列：`trade_research` 的 `bar_count`（起日前的日線數）與下市、轉板股的最後一根日線，以及 `explore_research.delisted_count`。研究 DB 上有 13 檔上櫃股的日線全在 2007-04-23～11-30，工具讀不到它們。

被排除的那幾天，這些標的就是沒有日線：前瞻報酬照「N 個交易日都要有日線」不可比；回看用的是剩下的日線根數。不讀這兩個函式的工具不受清單影響：
- `exit_research`、`backtest_research` 讀產品訊號的日線。
- `regime_report`、`index_condition_report` 只讀指數、台指期。
- `synthetic_history` 從正式副本產生合成 DB，只算日線列數。

**每一列**：
- 欄位：交易所、代號（`null`＝這個交易所的全部 `stock`／`ipo`）、`first`～`last`（`first` 是 `null` 時，從第一根日線算起）、原因、依據的 raw id 與決定連結。
- 原因只有兩種：
  - `code_reuse`：代號重用。
  - `no_corporate_actions`：這段沒有除權息來源。
- `code_reuse` 的列只在 DB 有舊公司時才排除，也就是這個代號在 `old_company_last` 以前有日線。正式 DB 副本只有新公司，不會被排除。

| 交易所 | 代號 | 排除 | 原因 |
|---|---|---|---|
| TWSE | 2432 | 第一根～2024-05-28 | 舊公司 2004-02-11～2008-08-25；倚天酷碁-創 2023-05-31 上市，前 240 根到 2024-05-28 |
| TPEx | 6130 | 第一根～2013-02-26 | 亞全 2007-04-23～2008-11-28；基因 2011-12-15 起，前 240 根到 2013-02-26 |
| TPEx | 4415 | 第一根～2016-05-19 | 美嘉電 2007-04-23～2011-11-07；台原藥 2015-04-14 起，前 240 根到 2016-05-19 |
| TPEx | 全部 | 2007-04-23～2007-11-30 | 沒有除權息事件（見[下市與轉板的標的](#下市與轉板的標的)的除權息） |

**代號重用為什麼多排除 240 根**（[6915138263](https://github.com/YiCheng0608/stock-lab/issues/702#issuecomment-6915138263)）：
- `indicators --rebuild` 與研究工具的回看都照日線根數算，不看日期。新公司的前 N 根，回看會接到舊公司的日線。
- 研究工具最長的回看是 240 根：`high_gap_240`、M1、M2 的 240 日報酬。
- 240 根的最後一天，是用研究 DB 2026-11-20 的日線數出來的，寫死在清單裡。

**改清單**：改 JSON，同一個 PR 改這一節與 `backend/tests/test_research_bar_exclusions.py` 的預期。

## 官方產業的逐月成員表

研究用的「T 日屬於哪個官方產業」，給第三輪 M1、M2（[策略證據「官方產業的成員」](../spec/evidence.md#第三輪m1m2)）與第四輪 C1（[第四輪：C1～C4](../spec/evidence.md#第四輪c1c4)）。由 [`tools/research/industry_members.py`](../../tools/research/industry_members.py) 從官方的分產業收盤行情產生，不寫進研究 DB（[#779](https://github.com/YiCheng0608/stock-lab/issues/779)）。

**來源**：每月最後一個交易日 D，兩個市場各取每個產業代號那一天的收盤行情。
- 上市：TWSE `MI_INDEX?date=<D>&type=<代號>`。
- 上櫃：TPEx 舊版 `stk_wn1430_result.php?d=<民國 D>&se=<代號>`。新版 `dailyQuotes` 不分產業，帶 `type` 也回全部。
- 表裡是當天掛牌的全部股票，含停牌、沒成交、之後下市的公司。
- 產業：上櫃是**當時**的分類；上市是**現在（或下市前最後）的分類回填**，見下面的限制。
- D 由 TWSE `type=01`（水泥）決定：從月底往前，第一個有列的平日。

**為什麼不用別的**：
- **`group_memberships`**：現行分類往回填（[下市與轉板的標的](#下市與轉板的標的)）。
- **MOPS 月營收頁（`t21sc03`）**：用今天的公司名單重新產生，舊頁沒有任何下市公司，產業也是現在的。2013-01～2024-09 的 563 頁裡，研究 DB 的 150 檔下市、19 檔轉板標的一檔都沒有（#779 [6894170671](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6894170671)）。
- **MOPS 公司基本資料（`t05st03`）**：下市公司只回舊大類或沒有資料。
- 2015-01-05 實測，TPEx 其他電子類 39 檔中，有 8 檔現在被分到別的產業，6 檔不在 MOPS 頁上（[6894326371](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6894326371)）。

**一列**：`snapshot_date`、`exchange`（`TWSE`／`TPEx`）、`industry_code`、`category`（回應的類別名稱原文）、`group_label`、`group_id`、`symbol`、`name`、`retroactive_category`。
- `retroactive_category` 是 `true` 的列：上市 35 綠能環保、36 數位雲端、37 運動休閒、38 居家生活，`snapshot_date` 在 2023-07-03 以前。這四類是那天才新增的，舊日子的成員是事後分類。manifest 的 `retroactive_rows` 是這種列的數量。
- `group_label` 是產品 `app.taxonomy` 的英文標籤，`group_id` 是 `canonical_group_id("industry", group_label)`。兩個市場同標籤的產業是同一個族群。
- 對照表寫死在工具的 `GROUP_LABELS`／`CATEGORY_NAMES`／`CODE_PERIODS`，三者都進 `definitions_sha256`。工具不 import 產品，`backend/tests/test_industry_members_tool.py` 會和產品的表比對。
- 上櫃 18 貿易百貨併入上市的 `Wholesale and Retail`。
- 上櫃 34 電子商務只在 2023-07-03 以前出現，產品沒有對應標籤，記成獨立族群 `E-commerce`。
- 存託憑證（上市 `type=9299`）、管理股票（上櫃 `se=80`）不是產業，不抓。
- 上櫃 33 農業科技、34 電子商務的回應有列，但 `category` 是空字串。`CATEGORY_NAMES` 只對這兩個代號寫成「空」，其他代號回空類別名照樣算失敗；主檔這兩類的 `category` 是空字串（[6904909658](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6904909658)、決定 [6904973827](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6904973827)）。

**各時期抓哪些代號**（`CODE_PERIODS`，決定 [6905102853](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6905102853)）：

| 期間 | 市場 | 代號 |
|---|---|---|
| 2013-01～2024-09 | 上市 | 01～06、08～12、14～18、20～31、35～38（32 個） |
| 2013-01～2013-12 | 上櫃 | 02～06、10、11、14～18、20～31（24 個） |
| 2014-01～2016-08 | 上櫃 | 加 32 |
| 2016-09～2018-02 | 上櫃 | 再加 33 |
| 2018-03～2022-06 | 上櫃 | 再加 34 |
| 2022-07～2023-06 | 上櫃 | 去掉 11 |
| 2023-07～2024-09 | 上櫃 | 去掉 18、34，加 35～38 |

- 怎麼來的：2013-01-31、2023-06-30、2024-09-30 三天全掃，再用 `bisect` 找上櫃 32、33、34 的起始月與 11 的結束月（[6904942765](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6904942765)、[6905069704](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6905069704)）。
- **二分的前提**：代號在出現之後一直存在、消失後不再出現。三天全掃與二分的每一步都沒有矛盾；上市的分類是回溯的，不二分。
- 上櫃 18、34 的結束與 35～38 的起始，照官方 2023-07-03 改代號放在 2023-06／2023-07 之間，沒有另外二分：2023-06 的 18、34 或 2023-07 的 35～38 沒有列，`build` 就會失敗。
- 上市 19 綜合、上櫃 08 玻璃陶瓷不抓：三天全掃加 2013～2024 每年 12 月（2024 用 9 月）都是 0 列。

**T 日用哪一份**：`snapshot_date ≤ T` 的最新一份（`industry_members.members_on`）。D 的收盤行情在 D 收盤後就公開，所以 T＝D 可以用。研究工具的 T 都是交易日的收盤後。

**限制**：
- **上市的分類是回溯的**（#779 [6904648128](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6904648128)、決定 [6904679034](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6904679034)）：
  - `MI_INDEX?type=` 在舊日子也用每檔股票現在（或下市前最後）的分類。2013-01-31 與 2023-06-30 都有的上市股票 736 檔，分類不同的 0 檔；2013-01-31 的 35～38 已有 18 檔，例如 9904 寶成、9921 巨大在 37 運動休閒，當時它們是「其他」。
  - 只有 35～38 標了 `retroactive_category`。其他改過分類的上市股，這份資料看不出來：同樣比，上櫃 547 檔裡有 65 檔改過，上市實際上應該也有。
  - 名單本身是當時的（含之後下市的，例如 2475 華映），只有類別是回溯的。
  - 上市當時分類的來源不在 #779 找，由 M1、M2 的研究工具單決定只用上櫃、接受回溯，還是先補對照。
- 一個月一份：月中改分類、新上市的股票，要到月底那一份才反映。新上市的股票在第一份快照前沒有族群，不能被選，但照樣在母體裡。
- 2023-07 以後上櫃 18、34 不抓，看不出它們之後還有沒有列，只在 2024-09-30 全掃確認過是 0 列。19、08 同理，只有檢查過的日子確定是 0 列。
- 代號重用：表只存代號，不存 `instrument_id`。研究工具在 T 日對到「代號相同、T 日有日線」的標的。[日線排除清單](#研究工具的日線排除清單)裡的舊公司那段沒有日線，所以對不到。
- 普通股是否都落在某個產業：產生時以研究 DB 已存的全市場行情（TWSE `ALLBUT0999`、TPEx `dailyQuotes`）核對。manifest 的 `completeness` 逐日記原因並分開計數：`checked`（核對過，`missing` 是不在任何產業的普通股）、`no_stored_answer`（研究 DB 沒有那一天的全市場行情）、`raw_missing`（有列但檔案找不到或 sha256 不符）。這也是唯一能看出「代號期間外其實有列」的檢查。

**檔案**：在研究 volume 的 `/data/research/industry_members/`。M1、M2 與 C1 的研究工具讀 `/data/research/industry_members/industry_members_v1.json`。
- 研究工具 [`tools/research/mainstream_research.py`](../../tools/research/mainstream_research.py)（#813）與 [`tools/research/round4_research.py`](../../tools/research/round4_research.py)（#878，C1）照研究工具的跑法把研究 volume 掛在 `/research`，所以預設讀 DB 旁的 `/research/research/industry_members/industry_members_v1.json`。對副本跑 `--coverage-only` 時，副本旁沒有這個目錄，研究 volume 另外唯讀掛載，用 `--members` 指到主檔。主檔的 sha256 寫死在工具裡（`MEMBERS_SHA256`，就是下面那一個），不同就拒絕。
- 2026-11-16 由統籌從產生它的 `task-779_members` volume 整包複製（8,317 個檔、92 MB，#779 決定 [6911923892](https://github.com/YiCheng0608/stock-lab/issues/779#issuecomment-6911923892)）。`task-779_members` 在 #779 結案時刪除。
- 主檔 sha256 `2a7e0bf4b36425896ba77cd253b936a430669d1e5754e71f50a72661ae651827`，manifest sha256 `03882bce1bfe0da71091fae37448a1bef06dd46869448bd94c75aa52a5dfdb03`（commit `0c8d1710`）。
- `industry_members_v1.json`：主檔。內容排好序，同一份 raw 重跑位元組相同。
- `industry_members_v1.manifest.json`：命令、commit、定義與其雜湊、每個回應的路徑與 sha256、每年列數、完整性檢查。
- `raw/<exchange>/<YYYYMMDD>/<代號>.json`：原始回應的位元組。
- `failed/<exchange>/<YYYYMMDD>/<代號>.<n>.body`：失敗回應的本文（有本文才存，第 n 次失敗），只用來判讀，`build` 不讀。
- `requests.jsonl`：每個請求的網址、狀態碼、sha256 與時間；失敗的列另有 `error` 與 `body`。
- `logs/`：#779 各次 `sweep`、`bisect`、`fetch` 的輸出，只用來判讀。

**怎麼重建**：
- 只從 raw 重建，不發請求。不要直接拿研究 volume 裡的那份當 `--out`：先整包複製到一個新的暫存 volume，再對它 `build`，最後比對主檔 sha256。

  ```bash
  docker volume create <暫存 volume>
  docker run --rm --network none -u 0 -v stock-lab-research:/data:ro -v <暫存 volume>:/out \
    --entrypoint sh stock-lab-backend:<tag> \
    -c 'cp -a /data/research/industry_members/. /out/ && chown -R 1000:1000 /out'
  docker run --rm --network none -v <暫存 volume>:/out \
    -v stock-lab-research:/data:ro -e STOCK_DATA_DIR=/data \
    -v stock-lab_stock-data:/prod:ro -e STOCK_STORED_RAW_DIR=/prod/raw \
    -v "$PWD:/w:ro" -w /w --entrypoint python stock-lab-backend:<tag> \
    tools/research/industry_members.py build --start 2013-01 --end 2024-09 --out /out \
    --research-db /data/stock.db
  docker run --rm --network none -v <暫存 volume>:/out:ro -v stock-lab-research:/data:ro \
    --entrypoint sha256sum stock-lab-backend:<tag> \
    /out/industry_members_v1.json /data/research/industry_members/industry_members_v1.json
  ```

  - 2026-11-16 照這組命令跑過一次（`stock-lab-backend:v1.2.57`、commit `0c8d1710`，`build` 10 秒），重建的主檔與 manifest 都和研究 volume 裡的那份逐位元組相同。manifest 記 commit，要它也相同就加 `-e STOCK_RESEARCH_COMMIT=<commit>`；主檔不受影響。
  - 研究 volume 要掛在 `/data`：研究 DB 的 `raw_payloads.payload_path` 是容器內寫的 `/data/raw/...`，掛在別處就一個檔案都找不到（PR #785 review [6905527404](https://github.com/YiCheng0608/stock-lab/pull/785#issuecomment-6905527404)），和 `tools/audit/raw_files.py` 的慣例一樣。
  - 種子列（id 很小的那些）是 Windows 舊路徑，`app.raw_paths.payload_file` 對到 `STOCK_STORED_RAW_DIR`；它們的檔案在正式 volume，所以唯讀另掛 `/prod`。不核對它們就拿掉這一行，那些日子會記成 `raw_missing`。
  - 有 `raw_missing` 的日子時，`build` 不寫任何檔案、以 1 結束；確定要寫才加 `--allow-raw-missing`。

- 重新抓：
  - 用 `fetch --start 2013-01 --end 2024-09 --out /out`，在 `docker run -d` 的容器裡跑；`/out` 同樣是新的暫存 volume，不要掛研究 volume 寫入。
  - 每個 host 間隔 ≥ 5 秒，兩個 host 並行。
  - 台北 20:30～23:30、08:00～09:00 不發。
  - 第一次被擋（封鎖頁、`查詢過於頻繁`、HTTP 403／429、連線被拒）就停下；同一個 host 連續 3 次失敗（其他非 200、空回應、不是 JSON、「網站維護中」）也停下。都是 exit 2，不自己重試。摘要的 `stopped` 是停下原因那個 host 的訊息（例如 `TPEx: blocked: …`），另一個 host 因此跟著停時，它的 `TWSE: stopped` 列在 `followed`。
  - `fetch` 對期間列出的代號回 0 列或沒有資料，也算失敗（`sweep`、`bisect` 不算）。
  - 失敗的回應本文存在 `failed/`，`requests.jsonl` 那一列記本文路徑。
  - 已存的 raw 不重抓，重跑就是續跑。
  - 各時期的代號清單是先用 `sweep`（指定月份全掃）與 `bisect`（找出代號開始或結束的月份）確認的。

## 研究工具的耗時與記憶體

`explore_research` 與 `trade_research` 的探索段要讀到 2019-12-31 以前的全部歷史，每個假設、每個工具版本只能跑一次，所以耗時與記憶體不能在研究 DB 上試。[#752](https://github.com/YiCheng0608/stock-lab/issues/752) 用一份**合成的長歷史 DB** 量（量測方式是統籌決定 [6885225362](https://github.com/YiCheng0608/stock-lab/issues/752#issuecomment-6885225362)）。

### 合成 DB

[`tools/research/synthetic_history.py`](../../tools/research/synthetic_history.py) 只讀正式 DB 的唯讀副本（[取正式 DB 的唯讀副本](LOCAL.md#取正式-db-的唯讀副本)），寫一份新的 `stock.db`：

- **日曆**：`--start`（預設 2004-02-11）～2024-09-27 的每個平日都當成交易日，不讀任何真實的歷史交易日。一年約 261 天，比真實的約 245 天多。2024-09-30 以後是副本原樣。
- **平移**：副本 2024-09-30 起的個股交易日當一塊，從 2024-09-27 往回一塊接一塊鋪。日線（所有類型）、籌碼、融資名單、除權息照同一張日期對照表；月營收以整塊的月數平移，季報以整年平移，MOPS 重大訊息以它的日曆天為一塊。接縫的價格會跳，報酬沒有意義，只能拿來量耗時與記憶體。
- **下市股**：`--delisted`（預設 1,000）檔現有股票的複本，代號 `X0001`…，每 33 檔一檔 `transferred`、其他 `delisted`；各自截來源的合成列 2～8 年，在 2024-09-27 以前結束。
- 研究工具不讀的表（`synthetic_history.EMPTY`）建成空表。
- `stock.db` 旁寫 `synthetic-db.json`（`purpose` 是 `synthetic_scale`），**不寫**研究標記 `research-db.json`，所以研究工具的驗證段 CLI 會拒絕它。
- 拒絕（exit 2，什麼都不寫）：來源是正式 DB（路徑在 `stock-lab-data` 或 `STOCK_DATA_DIR` 底下，或是正式檔的 hard link）、輸出目錄已有 `research-db.json` 或 `stock.db`、輸出在正式資料目錄底下。

```bash
# 換值：D＝正式副本目錄；IMG＝任務 image。大 SQLite 放 volume（bind mount 讀寫慢約 7 倍），新 volume 先 chown 1000
docker volume create task-<issue>_src; docker volume create task-<issue>_synth
MSYS_NO_PATHCONV=1 docker run --rm --network none -u 0 -v task-<issue>_src:/src -v "$D":/in:ro "$IMG" \
  sh -c 'cp /in/stock.db /src/stock.db && chown -R 1000:1000 /src'
MSYS_NO_PATHCONV=1 docker run --rm --network none -u 0 -v task-<issue>_synth:/synth "$IMG" chown -R 1000:1000 /synth
MSYS_NO_PATHCONV=1 docker run -d --name t<issue>-gen --network none --memory 1g --memory-swap 1g --oom-score-adj 1000 \
  -v task-<issue>_src:/src:ro -v task-<issue>_synth:/synth "$IMG" \
  sh -c 'python -B tools/research/synthetic_history.py --src /src/stock.db --out /synth/full > /synth/gen.json 2> /synth/gen.err'
```

2026-11-13 的副本（3.7 GB）產生 2004-02-11 起的全量：12.7 GB，9.4 分鐘（`--memory 1g`）；個股日線 1,434 萬列、籌碼 1,411 萬列、重大訊息 170 萬則，每天約 2,116 檔 `stock`／`ipo`（真實的檔數較少，所以下面的數字是上界）。

### 實測

2026-11-15 在合成全量 DB 上量，每次都和 #702 的回補容器（`--memory 3g`）同時跑，回補一直沒有被 OOM 殺掉。容器是 `--memory 4g --memory-swap 4g --oom-score-adj 1000`，每個工具、每一段都跑全部登記的假設；驗證段由量測 harness 直接呼叫 `run_validation`，讓全部假設都當成通過，連已用段一起跑（最壞情況）。表中的「峰值」是工具的 `peak_memory_gb`，也就是程序的峰值 RSS。cgroup 的 `memory.peak` 含 SQLite 讀檔的 page cache，可以回收，每次都頂到 4 GiB，不拿來判斷。

| 工具 | 段 | 讀的 bar 數 | 改前（#752 之前） | 改後 |
| --- | --- | --- | --- | --- |
| `explore_research` | 探索段（1990～2019-12-31） | 894 萬 | 載入 86 秒時 OOM（推估約 5.3 GB） | 1,221 秒，3.27 GB |
| `explore_research` | `--coverage-only` | 894 萬 | 沒有量（同一個載入，會 OOM） | 497 秒，2.57 GB |
| `explore_research` | 驗證段＋已用段 | 370 萬＋201 萬 | 992 秒，2.99 GB | 864 秒，1.87 GB |
| `trade_research` | 探索段（2012-12-01～2019-12-31） | 407 萬 | 436 秒，2.61 GB | 399 秒，1.34 GB |
| `trade_research` | 驗證段＋已用段 | 370 萬＋201 萬 | 659 秒，3.15 GB | 588 秒，1.95 GB |
| `round6_research` | 探索段（1990～2019-12-31，W1～W4） | 880 萬 | — | 753 秒，3.14 GB |
| `round6_research` | 驗證段＋已用段（兩段都從 1990 讀） | 1,136 萬＋1,234 萬 | 載入已用段時 OOM（`9384d7f1`，驗證段已到 3.38 GB） | 1,037 秒，3.85 GB |

`round6_research` 那兩列是 PR #905 review 在 2026-11-21 量的（同一份合成全量 DB 重產，容器 `--memory 4g --memory-swap 4g --oom-score-adj 1000`，沒有和回補同時跑）；「改前」是驗證段的資料沒放掉就載入已用段的 `9384d7f1`，「改後」是放掉之後（[第 2 步的工具](../spec/evidence.md#第-2-步的工具)本工具那段）。

改前的規模縮放（`explore_research` 探索段）：5 年（310 萬根）609 秒、1.86 GB；10 年（590 萬根）1,149 秒、3.51 GB。

**改了什麼**（[#752](https://github.com/YiCheng0608/stock-lab/issues/752) 決定 [6886660983](https://github.com/YiCheng0608/stock-lab/issues/752#issuecomment-6886660983)）：`portfolio_research.load_market` 不再先把全部日線建成 `Bar` 物件。它用 `research_report.benchmark_bars` 逐檔讀，這和 `benchmark_universe` 是同一條 SQL，只是在游標上依 id 分組；每檔建好 `Series` 與 `raw` 就丟掉那一檔的 `Bar`。`raw` 改成 `array`（停牌是 0／1），同一天的 bar 共用一個 `date` 物件。輸出逐位元組相同（`backend/tests/test_research_load_identical.py`），`VERSION` 與 `definitions_sha256` 不變。

**推估回補後的真實規模**：上市櫃每天約 1,150 檔（2004）到 1,700 檔（2019），`explore_research` 探索段約 550～600 萬根。照上表依 bar 數換算，約 2.1 GB、約 15 分鐘。`round6_research` 三段都從 1990 讀：研究 DB（2026-11-21）到 2019-12-31、2024-09-27、2026-11-13 的 `stock`／`ipo` 日線約 499 萬、701 萬、799 萬根（已扣排除清單），照上表換算探索段約 1.8 GB、驗證段＋已用段約 2.5 GB（峰值在已用段），比 `explore_research` 探索段大；其他各段都比 `explore_research` 探索段小。

**建議的跑法**：

- **都可以和回補同時跑**：起跑前在容器裡看 `grep MemAvailable /proc/meminfo` ≥ 5 GiB（看實際用量，不用各容器上限加總）。合成上界最大是 3.85 GB（`round6_research` 驗證段＋已用段），真實規模最大約 2.5 GB。
- **探索段與 `--coverage-only`**：`--memory 4g --memory-swap 4g --oom-score-adj 1000`。這兩種中途被殺不留紀錄檔，可以直接重跑，所以 VM 真的不夠時讓核心先殺它，不殺回補或正式容器。
- **驗證段**：`--memory 4g --memory-swap 4g`，**不加** `--oom-score-adj 1000`。驗證段讀資料前就寫「開始」紀錄，開始後被殺也算跑過一次、不能重跑（[第 2 步的工具](../spec/evidence.md#第-2-步的工具)）。不加時，VM 不夠時核心先殺用量最大的程序：驗證段約 1.9 GB（合成上界），回補約 2.4 GiB，被殺的會是可以從 manifest 接續的回補。`round6_research` 的驗證段例外：真實規模約 2.5 GB，比回補大，同時跑時被殺的可能是它。跑的期間不 build image、不部署（build 後的 SBOM 掃描約 5 GB）。真的因為技術原因被殺時，照[第 2 步的工具](../spec/evidence.md#第-2-步的工具)驗證段的規則，在 Issue 留言，由統籌處理那一筆紀錄。
- 單次都不到 25 分鐘，不碰台北 21:00～23:30。工具本身在 21:30～23:30 拒絕起跑，但不會中途停，所以 21:00 以後不要開始。
- **可用記憶體的檢查**：`backtest_research.free_memory_gb`（研究工具、`exit_research`、`audit.py` 共用）在 Linux 讀 `/proc/meminfo` 的 `MemAvailable`。#752 之前讀的是 `MemFree`，剛寫完大檔時 page cache 占滿，`MemFree` 只剩 0.6 GB（`MemAvailable` 6.9 GB），工具會誤拒。

## 已知的量

- **`instrument` 資料品質列**：每個 collect 對每個標的寫一列（現有規則，不是研究模式才有），一個交易日約 2,400 列；補到 2004 年約 1,200 萬列（約 3 GB）。研究工具不讀這張表。
- **大小**：估計研究 DB 約 14～16 GB、raw 約 8 GB（[#692 AC-1](https://github.com/YiCheng0608/stock-lab/issues/692#issuecomment-6873790108)）。
