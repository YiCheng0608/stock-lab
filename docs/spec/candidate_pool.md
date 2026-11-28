<!-- owns: candidate_pool_v1、候選池的對答案 -->
# candidate_pool_v1

候選池：每個交易日 T 從多個來源取聯集，列出「今天值得 AI 看的」股票，每檔標出為什麼進池（`source`），交給早盤 AI 判讀（[#1041](https://github.com/YiCheng0608/stock-lab/issues/1041)）讀。候選池**不是買賣訊號**，也不是「規則選出可以買的」：今日名單（AI 名單，[#1142](https://github.com/YiCheng0608/stock-lab/issues/1142)，[ai_list_v1](ai_list.md)）只從候選池挑；背景的規則名單不讀它。依據是 [#1003 AC-3](https://github.com/YiCheng0608/stock-lab/issues/1003#issuecomment-7108004301) 第 2～4 節與 #1 的決定（[7114503228](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7114503228) Q3：晚上 40、早上最多補 10、同一題材最多 4；[7187528140](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7187528140)：AI 不從池外補股）。程式在 `backend/app/candidate_pool.py`，門檻是 `PoolConfig`，每個 run 存進 `config_json`；三個上限是設定值，改預設值要在 #1020 或後續單留 `決定：`。

## 兩輪

| 輪 | `phase` | 誰跑、何時 | 內容 |
| --- | --- | --- | --- |
| 晚上 | `evening` | daily 最後一步 `candidate_pool`（在 theme_discovery 之後，讀當天的分群、熱度、名單與今日名單） | 全部來源的聯集，上限 40（`evening_cap`） |
| 早上 | `morning` | 08:20 的 `preopen` job，寫完開盤前檢查之後 | 只補晚上 `computed_at` 之後收進來的新聞點到、晚上沒選入的股票，上限 10（`morning_cap`） |

- `trading_date` 兩輪都是晚上那輪的資料日 T（早上那輪是 T 的下一個交易日 08:20 跑的，但存在 T 底下）。
- **寫了不改**：每個 `trading_date`、版本、`phase` 一份（unique）。同一天同一輪重跑回傳已存的 run，不重算、不新增、不改寫（與 `candidate_runs` 相同）；手動重跑也一樣。沒有晚上那輪時早上那輪不寫，回 `skipped reason=no_evening_run`。
- `computed_at` 在讀任何輸入**之前**取（UTC-naive），所以晚上那輪計算期間收進來的新聞仍算在早上那輪。

## 來源

晚上那輪讀 T 已存的資料，不發網路。「流動」是 T 往前 20 個 TAIEX 交易日每天都有成交量、平均 ≥ 1,000 張的 active `stock`／`ipo`（同 `candidate_score_v6` 的門檻；沒有日線的日子不當 0，平均就沒有值）。價格在 T 的公司行動基準上（`worker.pipeline._action_factor_by_bar`，同 [theme_heat_v1](theme_heat.md)）。

| `source` | 層級 | 條件（預設值） | `value`（觸發值） | `data_date` | `source_ids` |
| --- | --- | --- | --- | --- | --- |
| `watchlist` | 1 | 自選（`instruments.is_watchlisted`），不看流動性 | — | T | `instrument:<id>` |
| `holding` | 1 | 持股（`portfolio_positions.shares > 0`），不看流動性 | `shares` | T | `portfolio_position:<id>` |
| `rule_signal` | 2 | T 的規則名單（`candidate_runs.read_run` 那份，#1142 起是背景名單）全收 | `rank`、`strategy`、`score_version`、`signal_id` | 名單的 `data_as_of` | `daily_candidate:<id>` |
| `hot_theme` | 3 | T 的 `theme_heat_v1` 前 5 名題材，加上新聞分項原值（3 日比 20 日）≥ 3 的題材；每題材最多 4 檔流動成員：龍頭 1 檔（近 20 日平均成交金額最大），其餘依「5 日超額＋法人 5 日比率」在題材流動成員內的百分位合計 | `theme_id`、`heat`、`theme_rank`、`reason`（`top`／`news_surge`）、`role`（`leader`／`second`）、`news_ratio` | 熱度的交易日 | `theme_heat_score:<id>` |
| `h2` | 4 | T 的 H2 名單前 10 | `rank`、`version` | 名單日 | `strategy_list_item:<id>` |
| `x4` | 4 | T 的 X4 名單前 10 | 同上 | 名單日 | `strategy_list_item:<id>` |
| `cluster` | 5 | T 的量價共振分群，依群號取前 2 群「還沒命名的」（沒有一個題材佔群內超過一半；候選題材不算題材），每群取 20 日超額最大的 3 檔 | `cluster_no`、`cluster_size`、`member_mean_corr`、`excess_return_20d` | 分群日 | `theme_cluster_member:<id>` |
| `news` | 5 | 媒體新聞（`source_kind=media`），台北日期在 T 與前一個交易日（含），規則關聯（`symbols_json`）點到流動股，**而且**有已完成的 AI 判讀（`news_v4` 與等價版本） | `news_count`、`directions`（AI 方向，推論） | 最新一則的台北日期 | `news_item:<id>`（新的先，最多 5 個） |
| `mops_event` | 5 | T 的 MOPS 重大訊息（`events.event_type=material_information`），而且當天漲跌 ≥ 3% 或量 ≥ 1.5 倍 | `title`、`return_1d`、`volume_ratio` | 事件日 | `event:<id>` |
| `revenue` | 5 | 最近 5 個交易日內公布（`announcement_date`）的月營收，年增 ≥ +30%，或前一個月年增為負、這個月轉正 | `yoy`、`prior_month_yoy`、`revenue_month`、`rule` | 公布日 | `monthly_revenue:<id>` |
| `chips` | 5 | 三大法人近 5 個交易日淨買超股數 ÷ 近 20 日成交量，前 30 名（> 0；5 天都要有外資值） | `institutional_ratio_5d`、`rank` | T | `chip_snapshot:<id>`（T 那列） |
| `volume` | 5 | T 的量 ÷ 前 20 日均量 ≥ 2.5，而且收紅（收盤 > 開盤） | `volume_ratio` | T | `market_bar:<id>` |
| `near_high_240` | 5 | 收盤距 240 個交易日最高價 ≤ 5%（至少 200 根） | `high_gap_240` | T | `market_bar:<id>` |
| `limit` | 5 | 漲 ≥ 9.5%；跌 ≤ −9.5% 只收自選與持股 | `return_1d`、`direction` | T | `market_bar:<id>` |
| `gap` | 5 | 開盤對前一日收盤跳空 ≥ 3% 而且沒有回補（向上：最低 > 前一日最高；向下：最高 < 前一日最低） | `gap`、`direction` | T | `market_bar:<id>` |
| `morning_news` | 5 | 早上那輪，見下 | `news_count`、`directions`、`via`（`symbol`／`theme`）、`theme_id`、`role` | 最新一則的台北日期 | `news_item:<id>` |

- 每檔至少一個 `source`；一檔同一來源只記一列（同一檔在兩個熱門題材時，第二個題材放進 `value.also`，`source_ids` 合併）。
- **缺資料**：當天沒有熱度、分群、今日名單、H2 或 X4 的 run 時，那個來源 0 檔，`summary_json.inputs` 記原因（`no_heat_run`、`no_cluster_run`、`no_candidate_run`、`no_list`），不拿別天的頂替。T 沒有 TAIEX 日線時整輪失敗、不寫。
- **觸發值**的數值四捨五入到 6 位小數；非有限值存 null。

## 層級與上限

- 一檔的層級是它各來源層級的最小值（表格「層級」欄，#1003 AC-3 第 3 節）。
- **順序**：層級小的先；同層級時來源多的先；層級 2～4 再比層級內自己的次序（今日名單、H2、X4 的名次，熱門題材的題材名次與龍頭先）；再比 5 日報酬的絕對值大的先；最後依 instrument id。層級 5 的各來源沒有共同的次序，不比次序，來源數同時直接比 5 日報酬的絕對值（#1003 AC-3 第 3 節）；早上那輪只有 `morning_news` 一個來源，以新聞則數多的先當次序（見下）。
- **取捨**：依順序走，已選滿上限的之後每檔記 `reject_reason=cap`；還沒滿、但它所屬的某個題材（題材表 active 題材、T 有效的 `member`）已有同題材上限（4）檔入選的，記 `theme_cap`，層級 1、2（自選、持股、今日名單）不受這條限制但照樣算進題材的檔數；其餘入選，`rank` 從 1 起。上限不分層級：層級 1、2 超過 40 檔時，40 名以後也是 `cap`。
- 沒選入的也存（`selected=false`、`rank` null），之後可以量「被上限擋掉的股票隔天表現」。

## 早上那輪

- **新聞窗口**（與 [#755 開盤前檢查](../ops/SCHEDULING.md#scheduler-容器的排程serve)相同，`app.preopen_news._in_window`）：`collected_at` 在晚上那輪的 `computed_at` 之後、檢查時刻之前（含），`status=active`、時間不衝突，發布時間在 T 的台北 00:00 到檢查時刻（只有日期的新聞用 `event_date`，T 到檢查的台北日）。不限來源種類、不要求 AI 判讀（08:00 那輪的判讀可能還沒跑完；有的話記在 `directions`，沒有記 `not_judged`）。
- **補進來的股票**（都要流動、晚上沒選入；晚上那輪 `cap`／`theme_cap` 的算沒選入）：
  - 規則關聯（`symbols_json`）點到的股票，`via=symbol`；
  - 新聞標題加摘要含題材表某題材的 `keywords`（同 theme_heat 的比對）時，該題材的龍頭與最強 2 檔（同 `hot_theme` 的挑法），`via=theme`。
- **取捨**：同上的規則，上限 10；先比新聞則數多的，再比 5 日報酬絕對值。同題材上限把晚上那輪已選入的檔數算進去。
- **檢查時點**：要晚於晚上那輪的 `computed_at`，否則整輪失敗、不寫（空的窗口寫了就改不回）。檢查時點是窗口的終點：晚於下一個交易日開盤時，開盤後的新聞也會收進來，所以手動補跑過去的日期會寫下一份和當天 08:20 不同、之後也改不了的池，不要這樣補。

## 存放與讀取

- **`candidate_pool_runs`**：`trading_date`、`version`、`phase`、`status`（`computed`／`zero`）、`cap`、`union_count`、`selected_count`、`source_counts_json`（聯集中每個來源的檔數）、`summary_json`（入選的來源組成 `selected_sources`、被 ≥ 2 個來源點到的檔數 `multi_source`、`by_source_count`、`rejected`、入選的層級分布 `tiers`、`inputs`、晚上的 `liquid_universe`、早上的 `window_start`／`checked_at`／`news_items`／`themes`）、`config_json`、`base_run_id`（早上那輪指向晚上那輪）、`computed_at`。
- **`candidate_pool_items`**：`run_id`、`trading_date`、`version`、`phase`、`instrument_id`、`rank`、`tier`、`selected`、`reject_reason`、`source_count`、`sources_json`（上表每個來源一列：`source`、`value`、`data_date`、`source_ids`）、`themes_json`（`theme_id`、`name`）、`features_json`（收盤、1／5／20 日報酬、5／20 日超額、20 日均量張數、量比、法人 5 日比率、`high_gap_240`、跳空）。#1041 的判讀用 `candidate_pool_items.id` 對回來。
- **API**：`GET /api/candidate-pool?date=YYYY-MM-DD[&include_rejected=true]`（沒有 `date` 時取最新一個有晚上那輪的日子）。`meta.phases.evening`／`meta.phases.morning` 是各輪的 run（沒有時 null）：**早上那輪還沒寫時 `morning` 是 null，不拿晚上那輪頂替**；寫了但沒有補股時是 `status=zero`。`items` 是入選的股票，晚上在前、早上在後，各依 `rank`；`include_rejected=true` 連沒選入的一起回。每檔有 `id`、`phase`、`instrument`（id、exchange、symbol、名稱、官方產業）、`rank`、`tier`、`selected`、`reject_reason`、`source_count`、`sources`、`themes`、`features`。`meta.not_a_signal` 是「不是買賣訊號」。價量籌碼的細節、規則價位與新聞內文由 #1041 組輸入時自己讀（#1020 [決定 7188059266](https://github.com/YiCheng0608/stock-lab/issues/1020#issuecomment-7188059266)）。

## 對答案

候選池每個來源入選的股票之後怎麼走（[#1069](https://github.com/YiCheng0608/stock-lab/issues/1069)，#1004 第 1 點；題材熱度用 `hot_theme` 這個來源量）。規則由統籌在第一次真跑前決定（[決定 7203530697](https://github.com/YiCheng0608/stock-lab/issues/1069#issuecomment-7203530697)），寫死在 `tools/research/candidate_pool_score.py` 的常數與函式，要改就加 `candidate_pool_score.VERSION`。只讀、不改池：`python tools/research/candidate_pool_score.py --db <副本> --out <目錄> [--end YYYY-MM-DD]`，每月檢討的子入口（[evidence 每月檢討](evidence.md#每月檢討)）；拒絕同 `exit_research`（正式 DB、台北 21:30～23:30、可用記憶體不足）。輸出 `summary.md` 與 `tables.json`（不含時間，同一份副本單獨跑和在每月檢討裡跑相同）。

- **對象**：`candidate_pool_v1` 晚上、早上兩輪的入選股（`selected=true`），池的交易日 T ≤ `--end`。早上那輪只有 `morning_news`，自成一組。T 沒有早盤判讀也照算。
- **D 與報酬**：D 是 T 之後的第一個台股交易日（`pipeline.taiwan_bar_dates`），也就是讀這個池的早盤判讀的 `session_date`。報酬與母體都直接用早盤 AI 對答案的函式（[premarket_ai 對答案](premarket_ai.md#對答案)），候選池和 AI 判讀對同一個母體：每檔 `pipeline._tracking_inputs`＋`app.premarket_score.open_hold`（D 開盤 +5 bps 買、T+N 收盤 −5 bps 賣、再扣 30 bps，除權息因子換回 T 的基準），母體 `worker.premarket_score.population`（D 有日 K、沒停牌的 `stock`／`ipo` 等權，沒有流動性門檻）。T+N 的日 K 還沒到的池日記「未到期」。
- **組**：16 個來源各一組，一檔有幾個來源就在每個來源各算一次（另列「只有這個來源」的檔數，不另判）。另列 11 組：全池、層級 1～5、來源數 1／2／≥3、被上限擋掉（`selected=false`，`cap` 與 `theme_cap` 合成一組、另列各自檔數）、AI 判 keep／reprice（以 `premarket_ai_stocks.pool_item_id` 對回，有效動作取 champion、當時的 `PROMPT_VERSION`、`done` 判讀的 stock 分數列的 `effective_action`；`reprice_deferred` 算 defer，不在這組；分數列還沒寫的那天不算）。
- **每日超額與判定**：每個 T，組內可比股票的 `open_hold` 平均減母體平均；組那天沒有可比的股票就不算那天。t 是 `evidence_lib.t_stat(values, overlap=N)`；判定 `portfolio_research.forward_judge`（`MIN_T` 2.0），滿 `MIN_DAYS` 60 日才判，從池的第一天起累積、不分月。T+5、T+20 各判，共比較 27 組 × 2 個期間＝54 組，報告寫明組數，並寫明「通過」與「輸給基準」各大約 1 組會純屬偶然（`MIN_T` 2.0 約是單邊 2.3%）。
- **核對**：AI 組每天的超額要等於 champion 那份判讀 `overall` 列的 `ai_version.excess`（`ai_check` 列比對天數與不同的天）；對不上先在 Issue 提問，不調成一樣。
- **對流動母體（參考）**：市場面的來源只收流動股，等權母體含非流動股。另列每組對流動母體的超額日均，只列出、不判定、不算進比較組數：流動母體是 T 晚上那輪 `config_json` 的 `liquidity_days`、`min_average_lots`（`app.candidate_pool.liquid_ids`，早上那輪也用同一個 T 的晚上那輪）下，D 有日 K、沒停牌的股票；那天沒有晚上那輪（或 `config_json` 沒有這兩個值）寫「無資料」，不改用預設值。`liquid_ids` 看的是 `instruments` 現在的 `status=active`，之後才下市的股票不在流動母體裡。
- **清單**（[evidence 每月檢討](evidence.md#每月檢討)，`monthly_review` 第 2 版）：16 個來源中任一期間判「輸給基準」的列進變差，動作「候選池只決定 AI 看哪些股票：統籌在 #1 提案調整來源或上限；改 `PoolConfig` 預設值要留 `決定：`」；判「通過」的列進變強，只當紀錄。另列的 11 組不進清單。

## 限制

- 晚上那輪寫了不改：daily 當晚某個輸入失敗（例如熱度步驟失敗）時，那天的池就少那個來源，之後補算熱度也不會改池；要重做只能刪掉那天的 run（正式資料，先問使用者）。
- 23:00 的法人重抓會改寫 T 的籌碼，晚上那輪讀的是 21:30 那時的值。
- 新聞來源只看規則關聯（`symbols_json`），AI 判讀列的標的不算（同個股頁與開盤前檢查）。
- T 日在晚上那輪 `computed_at` 之前收進來、但當時還沒有 AI 判讀的新聞，兩輪都不收：晚上那輪的 `news` 要有判讀，早上那輪只看 `computed_at` 之後收進來的。早盤 AI 判讀（#1041）要看這些新聞時得自己讀。
