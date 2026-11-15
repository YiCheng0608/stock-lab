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

- **代號重用**：一個代號下市多年後分配給別家公司時，兩家的日線會接在同一個標的上，這裡分不出來。回補完成後要依名稱變化稽核一次（回補執行單處理）。
- **產業與族群成員**：新建的標的沒有產業成員列，族群相關的研究不含它們。

## 回補怎麼跑

長工作一律用 `docker run -d` 的獨立容器跑，日誌寫在研究 volume 的 `/data/logs/`，不靠 session 的背景 shell：統籌或工程師換手、背景 shell 被收掉，都不會中斷它。每一段都可以中斷後重跑：`backfill` 從各段的 manifest 接續，已完成的日期不再請求；其他命令重跑冪等。

- **間隔**：`backfill`、`corporate-actions sync`、`trading-halts`、`revenue backfill`、`fundamentals backfill`、`events backfill`、`index-bars backfill`／`futures-history` 這些命令，對每個官方 host 至少間隔 3 秒（`worker.cli.BACKFILL_HOST_INTERVAL_SECONDS`）；daily 與它的 catchup 仍用各 host 自己的間隔。
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
| 除權息 | `corporate-actions sync --start-date 2004-01-01 --end-date 2024-09-30 --apply` | 每月 TWSE、TPEx 各 1 個請求，含權的列另查明細；TWT49U 的起日自動夾到 2003-05-05 |
| 指數日 K | `index-bars backfill --from-month 2004-02 --to-month 2007-12`，之後每 48 個月一段 | 一次最多 48 個月（`MAX_MONTHS`） |
| 月營收 | `revenue backfill --months 60 --end-month 2018-08`、`--end-month 2023-08`，再 `--months 8 --end-month 2013-08` | 從 2013-01 起（#692 D4） |
| 季報 | `fundamentals backfill --quarters 20 --end-quarter 2017Q4`，再 `--quarters 20 --end-quarter 2022Q4` | 從 2013Q1 起 |
| 減資停止買賣 | `trading-halts --start 2011-01-01 --end 2024-09-30` | 起日夾到各來源的起始日（TWSE 2011、TPEx 2013），輸出 `not_published_before` |
| 休市表 | `trading-calendar --year 2021 --year 2022` | 2020 年以前沒有內容 |

回補日線或除權息之後，對研究 DB 跑 `indicators --rebuild`（研究工具自己算報酬，不讀指標；要用 API 或回測時才需要）。

### 研究工具的分段

研究工具預設的分段是探索段 2024-09-30～2025-12-31、驗證段 2026-01-01 起（`evidence_lib.SEGMENTS`）。要在研究 DB 上用回補的範圍，兩段都要以 `--segment` 給（`<exploration|validation>:<第一天>:[最後一天]`，探索段要在驗證段開始前結束）：

```bash
python -B tools/research/feature_evidence.py --db /data/stock.db --out /data/out/fe \
  --segment exploration:2019-01-02:2019-12-31 --segment validation:2020-01-02:2020-01-31
```

這裡的 `--segment` 只是讓既有的兩個工具能在研究 DB 上指定日期（例如確認工具讀得到回補的資料）。新策略探索的分段已在 [策略證據「分段」](../spec/evidence.md#分段) 寫死（探索段到 2019-12-31、驗證段 2020-01-02～2024-09-27，[#697](https://github.com/YiCheng0608/stock-lab/issues/697)），探索工具另開單，參數寫死在程式裡；回補完成前不要在回補的歷史上跑整段的特徵證據（#692 決定）。`portfolio_research.py --hypothesis` 的凍結假設不接受 `--segment`。

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

改前的規模縮放（`explore_research` 探索段）：5 年（310 萬根）609 秒、1.86 GB；10 年（590 萬根）1,149 秒、3.51 GB。

**改了什麼**（[#752](https://github.com/YiCheng0608/stock-lab/issues/752) 決定 [6886660983](https://github.com/YiCheng0608/stock-lab/issues/752#issuecomment-6886660983)）：`portfolio_research.load_market` 不再先把全部日線建成 `Bar` 物件。它用 `research_report.benchmark_bars` 逐檔讀，這和 `benchmark_universe` 是同一條 SQL，只是在游標上依 id 分組；每檔建好 `Series` 與 `raw` 就丟掉那一檔的 `Bar`。`raw` 改成 `array`（停牌是 0／1），同一天的 bar 共用一個 `date` 物件。輸出逐位元組相同（`backend/tests/test_research_load_identical.py`），`VERSION` 與 `definitions_sha256` 不變。

**推估回補後的真實規模**：上市櫃每天約 1,150 檔（2004）到 1,700 檔（2019），`explore_research` 探索段約 550～600 萬根。照上表依 bar 數換算，約 2.1 GB、約 15 分鐘。其他各段都比它小。

**建議的跑法**：

- **都可以和回補同時跑**：起跑前在容器裡看 `grep MemAvailable /proc/meminfo` ≥ 5 GiB（看實際用量，不用各容器上限加總）。合成上界最大是 3.27 GB，真實規模約 2.1 GB。
- **探索段與 `--coverage-only`**：`--memory 4g --memory-swap 4g --oom-score-adj 1000`。這兩種中途被殺不留紀錄檔，可以直接重跑，所以 VM 真的不夠時讓核心先殺它，不殺回補或正式容器。
- **驗證段**：`--memory 4g --memory-swap 4g`，**不加** `--oom-score-adj 1000`。驗證段讀資料前就寫「開始」紀錄，開始後被殺也算跑過一次、不能重跑（[第 2 步的工具](../spec/evidence.md#第-2-步的工具)）。不加時，VM 不夠時核心先殺用量最大的程序：驗證段約 1.9 GB（合成上界），回補約 2.4 GiB，被殺的會是可以從 manifest 接續的回補。跑的期間不 build image、不部署（build 後的 SBOM 掃描約 5 GB）。真的因為技術原因被殺時，照[第 2 步的工具](../spec/evidence.md#第-2-步的工具)驗證段的規則，在 Issue 留言，由統籌處理那一筆紀錄。
- 單次都不到 25 分鐘，不碰台北 21:00～23:30。工具本身在 21:30～23:30 拒絕起跑，但不會中途停，所以 21:00 以後不要開始。
- **可用記憶體的檢查**：`backtest_research.free_memory_gb`（研究工具、`exit_research`、`audit.py` 共用）在 Linux 讀 `/proc/meminfo` 的 `MemAvailable`。#752 之前讀的是 `MemFree`，剛寫完大檔時 page cache 占滿，`MemFree` 只剩 0.6 GB（`MemAvailable` 6.9 GB），工具會誤拒。

## 已知的量

- **`instrument` 資料品質列**：每個 collect 對每個標的寫一列（現有規則，不是研究模式才有），一個交易日約 2,400 列；補到 2004 年約 1,200 萬列（約 3 GB）。研究工具不讀這張表。
- **大小**：估計研究 DB 約 14～16 GB、raw 約 8 GB（[#692 AC-1](https://github.com/YiCheng0608/stock-lab/issues/692#issuecomment-6873790108)）。
