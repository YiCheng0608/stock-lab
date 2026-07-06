# Intake 分析：stock-lab 第一期 Ingestion Pipeline

## 1. 需求理解

本次只動工 `docs/design.md` §6「第一期」項目 1「**Ingestion pipeline**」——每天傍晚跑一次的盤後 batch：把四類台股資料擷取、清洗、入庫、算還原價、排程重試、失敗告警的**介面**做完。K 線頁、指標、篩選引擎、分點功能 UI、策略掃描、Telegram 實際推播內容、React 前端、回測、異常掃描一律**不在本期**（requirement.md「明確排除」）。

專案現況：全新 greenfield，`git ls-files` 只有 `README.md`、`docs/design.md`、`docs/design-system/DESIGN.md`、`.gitignore`，**無任何程式碼**，一切從零建。

### 本期要落地的能力（依 requirement.md 範圍界定）

- 四類資料源，每源一個獨立 **adapter**（design §2 原則 1）：
  1. 日價量（K 線）— 證交所/櫃買官方 OpenAPI 與每日收盤行情。
  2. 籌碼 — 三大法人 / 融資券 / 借券，證交所/櫃買每日統計。
  3. **券商分點**（買賣日報表）— 自爬 `bsr.twse.com.tw` ＋櫃買對應頁；只能抓當日、需節流、帶驗證碼；預留 `BrokerBranchSource` 介面供日後換 FinMind 付費方案。
  4. 除權息 / 股本 / 基本資料 — 公開資訊觀測站。

**市場覆蓋（範圍倍增，待人類 gate 定案，見 Q10）**：design §3 每一類來源都是「證交所（上市）/櫃買（上櫃）」並列，requirement.md 未排除上櫃，故本規劃預設**上市＋上櫃兩市場都要**。這代表每支 adapter 內部實為「兩市場、可能兩套頁面格式」的多 parser 工作；且 spec-7（籌碼）內含三大法人/融資券/借券三套資料、spec-9（除權息/股本/基本資料）內含三套頁面。worker 不得再拆，故各 adapter 的 worker 指示已明講本期市場與資料集覆蓋範圍（上市＋上櫃、各自的多套資料齊做），把倍增顯性化交 gate 定奪（Q10 若答「先上市」則各 adapter 指示需相應縮減、觸發重 intake）。
- **雙價格制**（design §7）：DB 同存**原始價**與**除權息還原價**，還原係數自算，ingestion 階段就落地。
- **PostgreSQL 單庫**：分點表按月分區 ＋ (股票, 分點, 日期) 索引；schema 不寫死單一使用者（design §2 原則 2，掛 user 概念）。
- **APScheduler 排程**（design §5）：每日傍晚起**每小時重試直到成功**，不依賴 OS 排程器；失敗當天觸發告警。
- **失敗通知 adapter**：Notifier 介面 ＋ 最小可用 stub（log）＋ Telegram adapter shell（讀 token env，本期不驗真推播）。
- **Docker Compose**：postgres + fastapi + ingestion service，`restart: unless-stopped`；Mac 開發、可搬 Windows WSL2，同一份 compose。

## 2. 架構判斷與拆解邏輯

以「**輸出 ownership 是否重疊**」與「**失敗根因是否相同**」為主軸拆成扁平清單：

- **基礎層先行**：專案骨架＋Docker Compose（spec-2）→ DB schema/models/migration（spec-3）→ adapter 契約 ABC（spec-4，含 `BrokerBranchSource` 這個 design 明列的未來 FinMind 替換縫）→ 通知 adapter（spec-5）。四者是下游共同依賴。
- **四個資料源 adapter 各自獨立**（spec-6~9）：各自擁有不同的 parser 模組與不同的目標資料表，失敗根因、fixture、維運風險都不同 → 分開且可平行。**券商分點（spec-8）是全案維運熱點**（驗證碼、節流、官方改版），單獨拆並上 full review。
- **除權息還原價計算（spec-10）** 與**除權息抓取 adapter（spec-9）** 分開：前者是「還原係數往前串接」的**數學**、後者是「解析公開資訊觀測站頁面」的**爬蟲解析**，失敗根因與 fixture 完全不同。
- **排程協調器（spec-11）** 依賴全部 adapter＋通知，負責串接、每小時重試、記錄各源成功狀態、失敗觸發通知。
- **整合驗證**以獨立 **test 節點 `test-integration`** 表達（端到端跑管線、資料落 DB、重試/通知可驗），不是 worker spec。

**兩個佈線 / 執行順序決策（避免整合期爆縫）**：

- **adapter 註冊採「裝飾器自註冊 ＋ registry 掃描觸發」**：spec-4 的 `registry.py` 提供 `@register` 裝飾器與 `discover()`（用 `pkgutil`/`importlib` 掃 `adapters` 套件、import 各模組觸發註冊）。各具體 adapter（spec-6~9）在自己檔案內 `@register` 自行註冊——這仍落在各自的 `allowed_outputs`（只寫自己那支檔），不需碰 spec-4 的檔案。如此「把四個 adapter 掛進 registry」這件事由各 adapter 自己擁有，spec-4 只負責掃描觸發；spec-4 完成定義因此**不要求當下列出具體來源**（此時 adapter 尚不存在），只驗裝飾器與掃描機制本身。
- **pipeline 執行順序：securities 先灌**：`daily_prices`/`chips`/`broker_branch_trades` 對 `securities` 為 FK（spec-3 明定）。adapter 的**解析層**彼此無依賴（故 depends_on 圖不變），但 pipeline **執行層**每次 run 必須先跑 spec-9（落地 `securities`）再跑其他源，否則其他表插入違反 FK。此順序限制寫進 spec-11 的 worker 指示，不改 depends_on 圖。

- **依賴清單寫入權集中（spec-12，結構修補）**：spec-2 的 `allowed_outputs` 把 `backend/pyproject.toml` 的寫入權獨占鎖給自己一站，但 spec-8（依 Q1 需 `ddddocr` 做驗證碼辨識）與 spec-9（公開資訊觀測站「格式雜」，需 `beautifulsoup4`/`lxml` 解析 HTML/XML）這兩個**與 spec-6/7 平行**的 adapter 節點，原本沒有任何合法路徑新增依賴——這是 ownership 規劃的缺口。若改讓平行的 spec-8/9 各自取得 pyproject 寫入權，平行執行會撞寫同一檔、破壞平行安全。故新增 **spec-12**（`depends_on: [spec-2]`）**單一擁有** `pyproject.toml` 依賴清單的寫入權（**僅增列依賴、不動 spec-2 已寫的其他區段**），集中把 `ddddocr`＋`beautifulsoup4`＋`lxml` 加齊；spec-8/spec-9（必需）與 spec-7（籌碼 TPEx 頁若需 HTML 解析的備援，保守序列化，成本可忽略）改成 `depends_on` 含 spec-12，序列化在其後才跑。因 spec-2→spec-12 為序列邊、且除 spec-2/spec-12 外無任一節點寫 pyproject，任兩個可平行節點都不會同時持有 pyproject 寫入權，平行安全不破。spec-6（證交所/櫃買 OpenAPI JSON ＋每日收盤 CSV，stdlib 可解）判定不需新依賴，維持原 `depends_on: [spec-3, spec-4]` 不動。此修補只調整 ownership/依賴圖，**不推翻 spec-2 已通過 focused review 的實作內容本身**（review-spec-2.md 有記錄）。

各 adapter 的**單元測試與 fixture 歸屬於對應 test 節點**（worker spec 只寫生產程式、`forbid_outputs` 測試檔）。專案採 `backend/`（Python）子目錄，替日後 `frontend/` 留位（見開放問題 Q9）。

## 3. 關鍵風險

1. **券商分點爬蟲是最大維運熱點**（design §3、§11）：頁面帶驗證碼、只能抓當日、錯過一天永久缺洞、官方可能改版、高頻/海外 IP 被擋。
   - 緩解：`BrokerBranchSource` 介面把驗證碼求解、節流、來源三者抽象化，日後可整段換 FinMind；本期用保守單線程 + 可設定間隔節流；失敗上 Telegram 告警 ＋ 每小時重試。
   - **驗收誠實面**：驗證碼 OCR 與「真的打外部網站」屬外部網路依賴，**不當作機器驗收的必要條件**（見第 4 點）。
2. **雙價格制正確性**：還原係數算錯會讓日後所有指標/回測產生假訊號（design §7 特別點名六到九月除息旺季）。→ spec-10 上 full review ＋ 針對已知除權息事件的數學單元測試。
3. **重試語意**：「每小時重試直到成功」若記帳錯誤，會漏抓（永久缺洞）或重複灌資料。→ spec-11 上 full review ＋ 可控時鐘的重試單元測試。
4. **schema 一次到位**：分區、雙價欄位、user FK、(股票,分點,日期) 索引若設計錯，遷移成本高。→ spec-3 上 full review。
5. **對外網路不可重現**：官方頁面格式會變、可能擋 IP，CI/本機測試不該依賴外網。→ 所有 adapter 的機器驗收一律打 **fixture / mock HTML**，只驗解析與正規化邏輯。

## 4. 測試策略的誠實邊界（重要）

台灣證交所 / 櫃買 / 公開資訊觀測站 / 分點頁面的**實際爬蟲行為屬外部網路依賴**，具不可重現性（格式漂移、限流、驗證碼、海外 IP）。因此：

- **機器驗收（machine）只驗「對固定樣本 / mock HTML fixture 的解析與正規化邏輯」**：給定一段已知回應 → parser 產出預期的正規化資料列。這是可重現、可進 CI 的客觀裁判。
- **「真的打外部網站成功抓到今天的資料」不列為機器驗收的必要條件**。它是營運期的行為，靠 Telegram 告警 ＋ 每小時重試 ＋ 改版監控在正式環境守住，而非用測試保證。
- 整合驗收（`test-integration`）用 **fixture-backed 的 adapter**（不打外網）灌進**真的 postgres**（compose/testcontainers），驗「資料確實落進各表、還原價確有計算、模擬某源失敗會觸發重試與通知」。

此判斷寫入 verification map 每一條 adapter 的 reason，供人類 gate 與 reviewer 對照。

**環境前提（Q11）**：需要真 PG 的節點（spec-3、test-integration）與 spec-2 的 `docker compose config` 都**隱含執行 machine test 的 runtime 具備可用 docker daemon**。這是非平凡前提，已列為 Q11 交 gate 確認；若不保證 daemon 可用，這三個節點需依 Q11 建議答案降級（test-2 退化為只驗匯入＋health、test-3/test-integration 無 PG 時標記 blocked 而非判過）。

## 5. 待人類確認的開放問題

（每題已附建議答案；整份計畫已照建議答案排，全數接受即可原樣凍結。偏離建議會以問答紀錄觸發重 intake。）

| # | 問題 | 建議答案 | 影響 |
|---|---|---|---|
| Q1 | 券商分點驗證碼要用哪種 OCR 方案？ | 先用開源 **ddddocr**（社群成熟、離線、免費），在 spec-4 留 `CaptchaSolver` 介面，日後可換付費 OCR 或改用 FinMind 整段繞過。 | spec-8 的依賴與實作；`ddddocr` 依賴由 **spec-12** 集中增列於 pyproject（spec-8 只 import），spec-8 `depends_on` 含 spec-12；若改選付費 OCR 服務，spec-8 需新增外部憑證/金鑰設定。 |
| Q2 | 初期支援的股票範圍？全市場還是少數樣本？ | 價量/籌碼/除權息 adapter 支援**全市場**（universe 取 securities 表全上市櫃）；**分點因節流每日只能抓有限檔**，初期分點 universe 取「**成交量前 N（可設定）**」子集（自選股是 §6 第 4 項後期功能、本期無此表，不列為 universe 來源）。 | spec-8 抓取 universe 策略、spec-11 排程時長。 |
| Q3 | 開發機是否已有可用 PostgreSQL，還是一律走 compose 內 postgres？ | 一律用 **compose 內 postgres**，不假設本機已裝；schema/整合測試用 compose db 或 testcontainers 起臨時 PG。 | spec-3 / test-3 / test-integration 的 test runner 環境。 |
| Q4 | 證交所/櫃買 OpenAPI 是否已申請金鑰？ | 優先用**免登入公開端點與每日收盤 CSV**，本期不需金鑰；若某端點需金鑰則以 env 設定、缺金鑰時該源標記 skip 而非失敗。 | spec-6 / spec-7 的來源設定與 config。 |
| Q5 | 分點抓取的節流參數（每檔間隔、並發）？ | 保守**單線程 ＋ 每檔間隔可設定（預設 3–5s）**，盤後 batch。 | spec-8 節流實作、spec-11 排程時長估算。 |
| Q6 | 本期是否要跑十年價量歷史回補，還是先建管線、回補另跑？ | 本期**建立回補能力**（daily price adapter 支援 date range），但實際十年回補當一次性營運任務、**不阻塞本期驗收**；分點無歷史（從上線起累積）。 | spec-6 是否含 range 回補；test-integration 驗收是否含回補。 |
| Q7 | Telegram 本期確認只做 adapter + stub、不接真 bot？ | 是。只做 Notifier ABC ＋ log stub ＋ **Telegram adapter shell**（讀 env token，本期不驗真推播內容）。 | spec-5 範圍。 |
| Q8 | schema 用 Alembic 遷移還是直接建表？ | 用 **Alembic**（schema 會持續演進）；分區與索引寫進 migration。 | spec-3 outputs 與 test-3 驗收方式。 |
| Q9 | 專案目錄佈局？後端放 repo 根還是子目錄？ | 後端放 **`backend/`** 子目錄（package 名 `app`），替日後 `frontend/` 留位；`docker-compose.yml` 放 repo 根。 | 所有 spec 的 output 路徑 ownership。 |
| Q10 | 本期 adapter 是否含上櫃（櫃買），還是先只做上市？ | **上市＋上櫃兩市場都做**。requirement.md 未排除上櫃，design §3 每一類來源本就「證交所/櫃買」並列，先只做上市會留半套缺口。各 adapter 內以「兩市場、可能兩套頁面格式」的多 parse 純函式表達；若 gate 決議「先上市」，spec-6~9 的市場覆蓋指示需相應縮減，屬範圍變更、觸發重 intake。 | spec-6/7/8/9 的解析工作量與 fixture 數量（每支 adapter 的 parser 從一套變兩套）、spec-11 分點排程時長。 |
| Q11 | 執行 machine test 的 runtime 是否具備可用的 docker daemon？ | **假設有可用 docker daemon**。test-2 的 `docker compose config`、test-3 與 test-integration 的 testcontainers/compose 起真 PG 皆依賴之。若執行環境無 daemon，這三個節點無法跑，需降級處理：test-2 退化為只驗 `from app.main import app` ＋ TestClient `GET /health`（跳過 compose config 或改用 YAML 靜態解析），test-3/test-integration 若無 PG 則標記為 blocked（無替代客觀裁判、不得判過）。建議 gate 先確認 daemon 可用性再凍結。 | test-2/test-3/test-integration 的 runner 能否成立；無 daemon 時的降級與 blocked 標記。 |

## 6. 統計

- 待人類確認開放問題：**11**（Q1 ~ Q11，含新增 Q10 市場覆蓋、Q11 docker daemon 前提）。
- Worker specs：**11**（spec-2 ~ spec-12；含結構修補新增的 spec-12 依賴清單擴充）。
- Test 節點：**12**（test-2 ~ test-12 各一，＋ test-integration 端到端）。
- 全數 `machine` 驗收（皆有可重現的客觀裁判：解析對 fixture、schema 斷言、重試邏輯對 mock 時鐘、整合對真 PG、依賴增列對 pyproject 解析/安裝）；無純 `no-judge` 任務。
- Review depth 分佈：full ×5（spec-3/4/8/10/11）、focused ×6（spec-2/6/7/9/12 ＋ test-integration）、defer-until-signal ×1（spec-5）。
