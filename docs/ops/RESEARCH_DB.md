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
- **耗時**：副本實測每個交易日約 15～26 秒（2026-11-14，3 秒間隔；上市 3 個、上櫃 3 個請求，加上每批 1 個 MOPS 清單，2008 年以前每月多 1 個 `MI_5MINS_HIST`）：2012-04-25～05-08 九個交易日 152 秒、2004-02-11～02-20 八個交易日 153 秒、2014-11-24～12-05 十個交易日 258 秒。
- **舊版面**：實測過的三段（2004-02、2007-04、2012-04～05、2014-11～12）找出三個舊版面，已處理（[各來源最早可得](../DATA_SOURCES.md#各來源最早可得)）：2009 年以前 `MI_INDEX` 沒有指數表、2014-12 以前 T86 的外資欄、TPEx 法人 2014-12 起的 16 欄版面。版面在實測日之間的其他改版沒有逐一確認，例如 TPEx 法人改成 24 欄的那天：parser 認不得的版面，可能讓那天法人欄是空值而沒有 warning（T86），或記核心 warning 讓那天變 `partial`（TPEx），所以每一批讀回時都要查各欄非空的比例（回補執行單的驗收）。

### 建研究 DB

由正式 DB 的唯讀副本開始（[取正式 DB 的唯讀副本](LOCAL.md#取正式-db-的唯讀副本)），複製進研究 volume；新建的 volume 是 root 擁有，先 chown 給容器使用者 1000：

```bash
# 換值：D＝副本目錄；IMG＝含 #692 的 backend image（正式在跑的 tag 或任務 image）
docker volume create stock-lab-research
MSYS_NO_PATHCONV=1 docker run --rm --network none -u 0 -v stock-lab-research:/data -v "$D":/src:ro "$IMG" \
  sh -c 'cp /src/stock.db /data/stock.db && mkdir -p /data/raw /data/locks /data/logs && chown -R 1000:1000 /data'
```

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

整段歷史要怎麼切成探索與驗證段，由 [#697](https://github.com/YiCheng0608/stock-lab/issues/697) 在看結果前先寫死；回補完成前不要在回補的歷史上跑整段的特徵證據（#692 決定）。

## 已知的量

- **`instrument` 資料品質列**：每個 collect 對每個標的寫一列（現有規則，不是研究模式才有），一個交易日約 2,400 列；補到 2004 年約 1,200 萬列（約 3 GB）。研究工具不讀這張表。
- **大小**：估計研究 DB 約 14～16 GB、raw 約 8 GB（[#692 AC-1](https://github.com/YiCheng0608/stock-lab/issues/692#issuecomment-6873790108)）。
