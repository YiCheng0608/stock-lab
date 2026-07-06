# Intake 驗證地圖：stock-lab 第一期 Ingestion Pipeline

**共同誠實前提**：台灣證交所/櫃買/公開資訊觀測站/分點頁面的實際爬蟲行為屬外部網路依賴、不可重現（格式漂移、限流、驗證碼、海外 IP）。因此所有 adapter 的機器驗收**只驗「對固定樣本 / mock HTML fixture 的解析與正規化邏輯」**；「真的打外部網站抓到今天的資料」不列為機器驗收必要條件，由正式環境的每小時重試 ＋ Telegram 告警 ＋ 改版監控守住。整合驗收用 fixture-backed adapter 灌進真 PostgreSQL，不打外網。

**環境前提（Q11，待 gate 確認）**：spec-2 的 `docker compose config`、spec-3 與 test-integration 的 testcontainers/compose 起真 PG 都**依賴執行 runtime 具備可用 docker daemon**。若不保證：spec-2 退化為只驗匯入＋`GET /health`（跳過 compose config 或改 YAML 靜態解析），spec-3/test-integration 無 PG 時標記 **blocked**（無替代客觀裁判、不得判過）。

| task | verdict | how | runner | depends_on | reason |
|---|---|---|---|---|---|
| spec-2 | machine | `docker compose config` 通過 ＋ `from app.main import app` 匯入 ＋ TestClient `GET /health`=200 | smoke (pytest + docker CLI) | [] | boot 與 compose 設定是客觀可重現的裁判 |
| spec-12 | machine | `backend/pyproject.toml` 以 tomllib 解析成功、依賴清單含 `ddddocr`/`beautifulsoup4`/`lxml`、spec-2 原依賴與其他區段未被刪改；preflight 安裝後 `import ddddocr, bs4, lxml` 成功 | smoke/unit (pytest + preflight install) | [spec-2] | 「依賴是否增列且可安裝、且未動 spec-2 既有內容」是可程式化斷言的客觀事實；集中擁有 pyproject 依賴寫入權，補 spec-8/9 平行節點無合法路徑加依賴的缺口 |
| spec-3 | machine | 空 PG 跑 `alembic upgrade head`，斷言各表存在、`broker_branch_trades` 有月分區、(security,broker_branch,date) 索引、`daily_prices` 有原始＋還原欄位、掛 user 的表有 user_id FK、`daily_prices`·`chips`·`broker_branch_trades` 對 `securities` 有 FK | integration (pytest + postgres) | [spec-2] | schema 存在性與結構是可查詢的客觀事實；需真 PG（分區為 PG 原生特性，Q3 建議用 compose/testcontainers 起臨時 PG，需 docker daemon 見 Q11） |
| spec-4 | machine | 匯入模組；未實作抽象方法無法實體化（抽象方法/`issubclass` 檢查）；`@register` 可註冊一個假來源並被列舉、`discover()` 對 `adapters` 套件可執行（驗註冊/掃描機制，非真實來源清單——此時具體 adapter 尚不存在） | unit | [spec-2] | ABC 契約的可實體化性與註冊/發現機制可程式化斷言（介面**設計是否恰當**屬主觀，交 full review） |
| spec-5 | machine | 三通知器可匯入；`LogNotifier.notify` 不拋且可觀察輸出；`TelegramNotifier` 為 `Notifier` 子類、無 token 時不拋亦不發網路請求 | unit | [spec-2] | 通知器的可呼叫性與 no-op 降級是客觀行為；不需真打 Telegram |
| spec-6 | machine | 對上市＋上櫃兩市場各一段固定 daily-price 樣本回應，各純解析函式輸出預期正規化 OHLCV 列（欄位/型別/日期/代號） | unit | [spec-3, spec-4] | 解析邏輯對固定樣本可重現；兩市場覆蓋依 Q10；**不含真外站抓取**（外部網路依賴不可重現，見共同前提） |
| spec-7 | machine | 對三類籌碼（三大法人/融資券/借券）、上市＋上櫃兩市場的固定樣本回應，各解析函式輸出預期正規化列（鍵與數值） | unit | [spec-3, spec-4, spec-12] | 同上：解析對 fixture 可驗，三類×兩市場覆蓋依 Q10，真外站抓取不列為必要條件；`depends_on` 含 spec-12（籌碼頁若需 HTML 解析，bs4/lxml 已備妥） |
| spec-8 | machine | 對上市＋上櫃兩市場的固定分點頁 HTML fixture，解析輸出正規化 (security,broker_branch,date,買量,賣量) 列；mock 時鐘驗節流間隔 ≥ 設定值；假 `CaptchaSolver` 可注入 | unit | [spec-3, spec-4, spec-12] | 解析與節流邏輯可對 fixture/mock 重現；兩市場覆蓋依 Q10；**真外站抓取與真驗證碼辨識明確不列入機器驗收**（維運熱點，靠告警/重試守）；`depends_on` 含 spec-12（ddddocr 已備妥） |
| spec-9 | machine | 對三套頁面（除權息/股本/基本資料）、涵蓋上市＋上櫃的固定公開資訊觀測站樣本，各解析輸出預期的正規化列，欄位足以支撐還原係數計算 | unit | [spec-3, spec-4, spec-12] | 解析對 fixture 可驗；三套頁面×兩市場覆蓋依 Q10；真外站抓取不列為必要條件；`depends_on` 含 spec-12（bs4/lxml 已備妥） |
| spec-10 | machine | 對「已知除權息事件＋原始價序列」樣本，輸出還原係數/還原價等於人工核算預期（含連乘、除息除權混合） | unit | [spec-3, spec-9] | 純數學、輸入輸出明確，是可重現的客觀裁判 |
| spec-11 | machine | mock 時鐘＋mock adapter（先失敗後成功）：驗未成功源下一小時重試、成功源不重抓、全綠停止、失敗時 Notifier 被呼叫 | unit | [spec-4, spec-5, spec-6, spec-7, spec-8, spec-9, spec-10] | 重試狀態機用可控時鐘可完全確定性地驗證 |
| test-integration | machine | fixture-backed adapter 灌進真 postgres：斷言各表有資料、securities 先落地使依 FK 的表插入成功、還原價已算（整段序列回填）、模擬某源失敗會重試並觸發通知 | integration/e2e (pytest + postgres) | [test-3, test-11] | 端到端資料落地與重試/通知是客觀可查事實；用 fixture 來源、**不打外網**（需 docker daemon，見 Q11） |

> 收斂進 manifest `planning.verification_map` 時取 `{task, verdict, how, reason}`。每個 `machine` 任務對應一個 test 節點（test-2..test-11 ＋ test-integration，見 intake-tasks.md「Test 節點」）；worker spec `forbid_outputs` 測試檔，fixture 與測試由 test 節點撰寫。
