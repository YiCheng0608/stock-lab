# R0 實作與驗收契約

更新：2026-09-14。本文件將 [ROADMAP](ROADMAP.md) 的 R0-1～R0-5 拆成可執行的小批工作與驗收證據；只維護實作細節，不另立優先順序或能力狀態。**ROADMAP 仍是狀態唯一權威**，本文件的批次標記不得被引用為 R0 已完成。

D-001 只建立文件契約；其後 C-001 已加入 R0-2 最小相容語意修正，D-002 收斂其文件與驗收證據。D-003 固定 B3 第一段純 ATR 計算核心的可驗證行為與手算案例；C-002 已加入對應純核心與測試，D-004a 的唯讀 review 再收緊公司行動 dependency、停牌矛盾與前收 precedence 邊界。統籌於 2026-09-12 完成 C-002 final review，D-004b 記錄實際介面、證據與未完成範圍。C-003 隨後完成 R0-5/B6 的正式 SQLite 唯讀現況查驗、外部一致副本／fresh DB 真 Alembic 升級及雙路徑測試 review；C003 當時沒有對正式 DB 執行 migration。Round10 C010 建立 synthetic migration／restore 回歸並揭露 News JSON server-default 差異；Round11 C011 已在明列的兩欄 parity 與 atomic migration 回歸範圍通過統籌 review，程式 head 前進至 `0006_news_json_defaults`，但 R11 當時正式 DB 仍未升級。R26 另觀察到其他使用者 preview task 的 lifespan log 對正式 DB 執行 `base→0001→…→0006`；這不回寫前述歷史，也不是 R26 migration／repair acceptance。Round 04 C-004 與 Round 06 C-006 已由統籌 review 明確 opt-in 的 schema 1 artifact store、`atr-provenance/v2` caller-provided strict 契約與離線雙唯讀比較，故 B3-persist 只按此有限範圍完成。Round07 C007 完成 `time-evidence/v1` 純契約、專用 schema 1 本地 store、exact reader 與 JSON export；Round08 C008 再完成分離的 `product-time/v1` News／signal／action／stock／dashboard／tracking API/UI read-time projection。這些工作仍不代表 C007 strict evidence 與產品／worker 已接線、官方來源 truth／B5b PIT gate 已完成、正式 artifact 已保存、R0-1／R0-4 整體已完成、正式分析或歷史資料已寫回。

Round27 C027-B 另把目前 checkout 的 API lifespan 從隱式 `init_db` 改為有限、唯讀的 `check_database_readiness`，並以 C027-A／D029-A 的歷史基線與 contract 補充、具名 saved-original／current snapshots 及外部 0001→0006 replay 收斂 R0-5 啟動邊界。這不回寫 R26 preview 的外部 migration 因果，也不接受正式 migration／restore／deployment、所有 historical／custom schema、非 SQLite、資料 truth 或 PIT。

Round30 C030-B 再補上該 startup gate 對 `signal_settlements` UNIQUE metadata 的有限檢查：至少一個 ordered full ordinary BINARY ASC `UNIQUE(signal_id, horizon)`，且所有 key parts 觸及 `signal_id`／`horizon` 的 UNIQUE 都必須是同一 canonical pair；expression UNIQUE 因 metadata 無法有限歸屬而保守拒絕。這只修補 R29 留下的 startup mixed-identity 候選，不回寫成 R29 已修改 readiness，也不是任意 CHECK／trigger／unrelated UNIQUE、任意 INSERT、row truth、migration 或 repair 驗證。

Round31 C031-B 再處理 R30 留下的 instruments startup 候選：canonical identity 仍是 ordered `(exchange, symbol)`；`market` 不是 identity，但因現行 writer 明確讀寫 `market`／`exchange`／`symbol`，三者都納入有限 target-key compatibility gate。mapped 三欄必須是 `table_xinfo.hidden=0`，只作非 hidden／generated 欄位相容檢查；key-unrelated named UNIQUE（包含 generated extra）仍屬 non-goal。這個 startup policy 可比 R28 recognized-current no-rebuild 判定更窄，不能反推 `init-db` 會修復所有被拒形狀。

Round32 C032-B 已把 R31 留下的 R0-B2 候選收斂為 `signal-comparison/v1` 有限離線 library：兩個 caller-provided external rollback-mode snapshots、expected SHA-256、opaque exact legacy key 與 conjunctive exact artifact selector，輸出 deterministic detached diagnostic report。它不做計算 replay、不證 shared inputs／PIT／truth、不接 CLI／API／UI／worker 或 default，也不完成 B2／B7；完整契約見 [Signal comparison 離線唯讀契約](SIGNAL_COMPARISON.md)。

Round33 C033-B 接著完成 caller-provided current pure-rule replay；Round34 C034-B 再以明確 opt-in、專案外 owned research DB 接到現行 analysis core，將 actual evaluator kwargs/result、R33 private bundle、subject/date/strategy 與 legacy Signal snapshot同 transaction保存。這只接受 worker evaluation capture；尚未接 `SignalArtifactStore`、官方 availability／decision time、legacy-v2 paired output、API/UI/default 或 B7。操作與完整邊界見 [Worker analysis capture 契約](WORKER_ANALYSIS_CAPTURE.md)。

## 1. 狀態語意與使用規則

每個批次必須明確使用下列其中一種狀態，不得只寫「完成」：

| 標記 | 意義 | 最低證據 |
| --- | --- | --- |
| 提案 | 契約已寫出，但對應程式／資料變更尚未存在。 | 本文件中的輸入、輸出、失敗行為及驗收案例。 |
| 已實作 | 變更已存在，但尚未完成獨立 review；不等於驗收通過或 ROADMAP 已完成。 | 變更路徑、版本識別、實際執行命令、日期及未通過／未執行項目。 |
| 已 review | reviewer 已依本文件重現關鍵案例並記錄結果。 | reviewer、日期、隔離環境、程式／資料版本、命令輸出及限制。 |

目前狀態：D-001 文件契約已 review；R0-2 的 C-001 最小相容修正、Round12 C012 signal artifact 本地 foundation、Round32 C032-B offline exact comparison、Round33 C033-B current pure-rule replay，以及 Round34 C034-B opt-in worker evaluation capture 已經統籌有限 review，但 artifact／source／availability／decision-time bridge、legacy-v2 paired replay、API／UI/default、PIT 與 B7 尚未完成，所以 B2 整體仍未完成。R0-1 的 B3 第一段純核心，以及 C-004＋C-006 涵蓋的有限 B3-persist，均已經統籌 review；後者已驗同日唯讀 legacy、Wilder v2 兩 as-of、完整 caller-provided strict provenance 與缺漏政策。另一路的正式 worker 仍走 legacy ATR，官方來源 truth／PIT execution gate、新 ATR worker 接線及 paired replay 未完成；它們屬 B3-wire／B5／B7，不是 B3-persist 結案的反向前提。因此 R0-1 整體仍未完成。R0-3 只有 C-005／B4a read-time 價位語意已 review，B4b 新交易計畫仍是提案；R0-4/B5 的 C007 本地 time-evidence foundation 與 C008 產品 read-time projection 均已有限 review，但兩者沒有持久化關聯，官方 truth、worker 接線與 B5b PIT gate 仍未完成。R0-5/B6 的正式庫現況查驗與隔離升級已 review；C011 在 News 兩個 JSON server-default 與 atomic migration regression 的明列範圍通過 review，R27 完成目前 checkout 的有限 API startup readiness，R30／R31 再分別有限補強 `signal_settlements` 與 `instruments` UNIQUE metadata gate。C003/R11/R25 時點的正式 DB 沒有 `alembic_version`、只有五筆 fallback markers；R26 外部 preview startup 後 current 為 0006／21 tables。R27／R30／R31 的 startup gate 與具名 snapshots／external synthetic 驗證，仍未把該外部變化接受為正式 migration／repair／restore／deployment，亦不宣稱所有 historical schema parity、任意 INSERT 或完整 schema／資料 truth。

實作者只能在保留證據後把批次改成「已實作」；reviewer 才能標「已 review」。能力狀態的最後更新仍回到 ROADMAP。

## 2. 靜態基線與共同不變條件

2026-09-11 D-001 在 C-001 前直接核對原始碼所得基線如下；這是歷史缺口定位，不是目前程式狀態：

- `backend/worker/pipeline.py::_calculate_features` 的 `atr14` 是最近最多 14 根 `high-low` 算術平均。
- 當時 `backend/worker/pipeline.py::_upsert_signal_for_strategy` 對 `conditional` 寫入 `confidence=0.75`；C-001 已修正新寫入行為，但 `data_cutoff` 仍寫 T 日 `13:30 Asia/Taipei`。
- `backend/worker/pipeline.py::_risk_levels` 以 `max(atr or entry×2%, entry×1%)` 作風險距離，產生 1.6R／3R 目標。
- `backend/app/models.py::Signal` 仍只有 nullable legacy `confidence`、字串 `data_cutoff` 與日期型 `earliest_execution_date`；C-001 沒有 migration，而是在 rule evidence 與 API 加入相容語意。
- `TechnicalFeature` 目前以 instrument＋trading_date 唯一，`features_json` 會被更新；因此新 ATR 不得在缺少版本隔離時原地覆寫舊特徵。
- Alembic 程式 revision 依序存在 0001～`0006_news_json_defaults`；此事不能證明任何實際 DB 已在 0006。

所有 R0 批次共同遵守：

1. 不改寫 `breakout_v1`、`pullback_v1`、`hot_group_v1` 或既有 run 的歷史語意與結果。
2. 公式、時間、價位、成本或輸出語意一旦改變，就使用對應的新 feature／strategy／execution／signal-output semantics 或 presentation contract version；舊、新輸出可同時查詢。規則 gate、價位或執行行為改變時必須升級 strategy／execution version；純輸出／寫入語意修正可使用獨立 signal-output semantics version，不必冒稱策略規則已改變。
3. 每筆輸出能回推到程式版本或工作樹檔案雜湊、設定快照、資料快照／as-of、公司行動版本及 run id。若 repository 尚無 HEAD，記錄實際檔案雜湊，不捏造 commit SHA。
4. 缺值、無法證明可得時間、公司行動無法重建、非有限價格及資料斷層都 fail-closed；不得補 0、沿用未標示的舊值或選擇對績效有利的解讀。
5. 正式 DB、正式輸出與舊 run 只讀。所有 migration、重算與比較先在具名隔離 DB 執行。

建議的新識別至少包含：

| 軸 | 用途 | 版本改變條件 |
| --- | --- | --- |
| `feature_version` | ATR、均線、公司行動調整與 warm-up。 | 公式、平滑、期間、缺值或價格基礎任一改變。 |
| `strategy_version` | gate、規則證據與訊號生命週期。 | 使用新 feature、門檻、價位規則或狀態轉移任一改變。 |
| `execution_version` | T+1、成交、成本、價格級距與不可比規則。 | 執行時間、費稅、滑價、撮合或優先序任一改變。 |
| `prediction_version` | 預測目標、模型、校準器與適用範圍。 | 目標／期間、模型、訓練集、校準器或門檻任一改變。 |
| `signal_output_semantics_version` | rule-only confidence、legacy 欄位與 API 寫入／輸出語意。 | 不改 gate／價位／執行，只改欄位產生、nullability 或解讀方式。 |
| `presentation_contract_version` | 欄位標籤及 legacy 相容解讀。 | 使用者可見語意改變；不應反向改寫研究資料。 |

C-002 純核心已實際使用 `technical_v2_atr14_wilder`；此名稱只識別純計算 artifact，不能冒充 worker 預設已切換或正式 feature 已持久化。其他尚未實作的版本軸仍須在對應批次前選定實際字串並寫入設定。C-001 已實際使用的 confidence semantics 名稱則以 5.2 節為準。

## 3. 小批交付順序

| 批次 | 狀態 | 範圍 | 完成邊界 |
| --- | --- | --- | --- |
| D-001 | 已 review | 本文件與文件索引。 | 契約已由統籌閱讀及 review；不宣稱 D-001 執行過程式測試。 |
| B1／C-001 | 已 review（最小相容範圍） | R0-2：新寫入 null、保留 legacy 數值、輸出非機率語意與安全 UI 標籤。 | 無 migration、不改策略 gate／價位／執行、不寫回歷史 DB；前端整套回歸未全綠。 |
| B2／C012＋C032-B＋C033-B＋C034-B | 四個有限 slices 已 review；B2 整體未完成 | 已有分離的 `signal-artifact/v1` local store、offline exact comparison、current pure-rule replay，以及 owned research DB 的 opt-in worker actual-input capture。 | Round34 只接 legacy analysis capture，仍不接 SignalArtifact、official time/source、legacy-v2 paired output、API/UI/default、PIT 或 B7；不得由 receipt、bundle或 observed date 冒充 B2 完成。 |
| B3／C-002 | 第一段純核心已 review；R0-1 未全完成 | R0-1 正確 ATR 純核心，版本為 `technical_v2_atr14_wilder`；後續再接 versioned feature artifact。 | 第一段只驗證新核心，不切換 worker／候選／追蹤；來源 truth、正式儲存與 replay 不由純核心測試冒充。 |
| B3-persist／C-004＋C-006 | 已 review（有限 persistence） | 明確 opt-in 的 schema 1 SQLite artifact store、`atr-provenance/v2` strict writer/reader、schema 1 compatibility 與同日 legacy＋兩 as-of 離線雙唯讀比較。 | 不註冊 legacy `Base`、不改既有 Alembic head／啟動流程；只驗 caller-provided 結構、隔離保存與比較，不接 worker／API／官方來源，也不因 persistence 通過就宣稱 B3-wire、B5、B7 或 R0 完成。 |
| B4a／C-005 | 已 review（read-time semantics） | R0-3 legacy 規則參考價標示。 | 只改 API／presentation 解讀，不改 v1 數值、worker、schema 或 legacy 列。 |
| B4b | 提案 | R0-3 新交易計畫資料契約。 | tick、gap、成本充分性、流動性與 lifecycle 使用新版本，不與 B4a 混成完成。 |
| B5a／C007 | 已 review（有限本地 foundation） | R0-4 的 `time-evidence/v1` 純契約、專用 schema 1 SQLite store、exact 讀取與 JSON export；不接來源、worker、News 或產品 API。 | 只保存／輸出 caller-provided 時間證據；以 C007 當時狀態，B5a 產品輸出尚未接，後由 C008 補 read-time projection；B5b replay／決策 PIT gate 仍未完成。 |
| B5a／C008 | 已 review（有限 product read-time projection） | R0-4 的 `product-time/v1` 角色投影與既有 News、signal、action、stock、dashboard、tracking API/UI 相容輸出。 | 不接 C007 store／worker、不保存新時間、不證來源 truth；B5b replay／決策 PIT gate 仍未完成。 |
| B6／C-003 | 已 review（現況查驗與隔離升級） | R0-5 程式 head、C003 當時的正式 DB fallback 現況、外部 consistent copy／fresh DB upgrade、row preservation 與雙路徑測試。 | C003 對正式 DB 保持只讀且未 upgrade；當時沒有 `alembic_version`。forward-only restore 方法已記錄但未實際演練。R26 外部 preview startup 後的 current 狀態另見 §8.5。 |
| R0-A2／C010＋C011 | 已 review（具名 migration regression 範圍） | synthetic restore mechanics，以及 News 兩欄 JSON server-default parity／SQLite atomic migration regression。 | 不宣稱完整 historical schema parity、非 SQLite、正式 DB upgrade、正式 restore／deployment 或整個 R0 完成。 |
| R0-A3／C027-B | 已 review（有限 API startup readiness） | lifespan 只讀 finite marker／mapped-schema gate；明確 schema mutation 留給 `worker.cli init-db` 與 worker。 | 具名 snapshots 的 full-row／integrity／FK preservation 與 replay parity、39-case startup review均已通過；readiness 本身不執行這些完整 scans，且不接受正式 migration／restore／deployment、所有 custom schema、非 SQLite、資料 truth／PIT 或 running service reload。 |
| R0-A6／C030-B | 已 review（有限 settlement startup UNIQUE gate） | R0-A3；R29 留下的 mixed settlement identity startup 候選；D032-A finite metadata contract。 | 唯讀 startup 要求 canonical ordered full ordinary BINARY ASC pair，並拒絕不符 canonical descriptor 的 target-key UNIQUE 與無法歸屬的 expression UNIQUE；不解析 partial predicate dependency、不 audit 任意 CHECK／trigger／unrelated UNIQUE，且不保證任意 INSERT。 |
| R0-A7／C031-B | 已 review（有限 instruments startup UNIQUE gate） | R0-A3／A4；R30 留下的 instruments mixed-identity候選；D033-A finite contract。 | 只對 `main.instruments` 驗 mapped `market`／`exchange`／`symbol` 非 hidden／generated及canonical `(exchange,symbol)` UNIQUE descriptor；key-unrelated UNIQUE／generated dependency、完整writability、任意寫入、migration／repair及完整custom schema不在本批。 |
| B7 | 提案 | 新舊版本隔離 replay、差異報告與 review。 | 通過後才能提議在 ROADMAP 更新狀態或切換預設版本。 |

B1／C-001 已先消除「75% 勝率」誤解；C012 建立分離的本地 artifact foundation，R32～R34 再依序補有限 comparison、pure replay與 opt-in worker capture。這些工作都沒有正式 DB 重算／migration／歷史寫回，也不代表 B2 或整個 R0 完成。

## 4. R0-1：ATR 定義、公司行動與 warm-up

### 4.1 B3 第一段範圍與目標公式

D-003 對 **B3 第一段的新版本純計算核心**選定 `n=14`、14 個 TR 的算術平均作 seed，之後逐根使用 Wilder recurrence。C-002 已在 `backend/app/atr.py` 以 `technical_v2_atr14_wilder` 實作，並於 D-004a 修正三項 cross-review 邊界後通過統籌 final review。這項 review 只涵蓋純核心；它不修改 legacy `backend/worker/pipeline.py::_calculate_features`，不代表 worker、API、資料庫或官方來源已接線，也不切換候選或追蹤。

對期間 `n=14`，所有價格先轉成**同一、可追溯且 point-in-time 可得的價格基礎**。第 t 根的 True Range 為：

```text
TR_t = max(
  high_t - low_t,
  abs(high_t - close_{t-1}),
  abs(low_t  - close_{t-1})
)
```

新核心固定使用：

```text
ATR_14(seed) = mean(TR_1 ... TR_14)
ATR_14(t)    = (ATR_14(t-1) * 13 + TR_t) / 14
```

`ATR_14(seed)` 出現在第 14 個**連續有效 TR** 所在位置；第 15 個起才套 recurrence。若後續研究需要 SMA，須另用不同欄位／`feature_version`；不得由設定靜默切換同一欄位的平滑方式。

### 4.2 序列、有效輸入與 fail-closed 狀態機

核心的輸入是按 instrument 與市場 session 遞增排列的 bar，加上呼叫端提供的序列邊界、預期 session、停牌／不交易狀態、價格基礎、公司行動 coverage 與 availability 判定。`expected_sessions` 與 `decision_at` 都是強制輸入：session 必須嚴格遞增且能與 bars 配對；timestamp 必須含 timezone，date／datetime 轉換以 `Asia/Taipei` 判定市場日期。核心只檢查這些 metadata 在同一已確認 basis 下是否互相一致、是否通過時間門檻，再依旗標計算；它不自行猜測外部事實，也不因一致性檢查通過就證明資料來自官方或內容為真。

- `open/high/low/close` 與所需前收盤均須為有限正數，並滿足 `low <= open <= high`、`low <= close <= high`。任一值無效、`high < low` 或關係不成立時，該位置 TR／ATR 為 `null`，目前 recurrence 失效。
- 只有呼叫端能以掛牌／資料契約證明是**該 instrument 在該價格基礎下的真正序列起點**，而且它是整次輸入的 first actual bar、此前沒有 missing／invalid continuity 時，才可令 `TR=high-low`。一般查詢截窗、分頁起點、任意 backfill 起點或中斷後恢復都不能假冒 IPO／序列起點。
- 前收選擇順序固定為：連續狀態中的 close；若是 first actual bar，再看 calculator-level external previous close；其後看該 bar 明示的 row-level previous close；只有前三者都**未提供**且符合上一項真正序列起點時，才 fallback 為 high-low。某個前收依此順位實際被選為必要輸入後，若值、basis、來源或 availability 不合法就必須 fail-closed，不能退回較低順位或 `true_sequence_start` 掩蓋；已有連續 state 時，不會使用多餘的 row-level previous close，也不因該附帶值單獨令當根失效。
- 一個連續有效 segment 需要每個預期有 bar 的 session 都存在、OHLC 有效、與前收同基礎、公司行動 coverage 足夠，且所有必要版本在本次 `decision_at`／as-of 可得。前 13 個有效 TR 的 ATR 為 `null` 並標示 warm-up；第 14 個產生 seed，第 15 個起逐根 recurrence。
- 若預期應有 bar 的 session 缺失，或某根因無效 OHLC、缺前收、row basis 不一致，或該 row／前收在 `decision_at` 尚不可得而被排除，該位置 fail-closed 並清除既有 ATR 與 TR 計數。OHLC／basis／availability 本身不合格的 bar 不得提供 recurrence，也不得成為下一根的可信前收。若不合格的是構成共同比價基礎的 action dependency／全域 coverage，則不是局部中斷，而是依 4.3 節讓整個 artifact 不可用。
- 中斷後第一根 bar 若 OHLC、basis、coverage 與 availability 本身都有效，而且帶有合法 row-level previous close，可立即產生第一個恢復 TR；若沒有合法 row-level previous close，該根只能建立新的 close anchor，TR／ATR 仍為 `null`，下一個連續預期 session 才能產生第一個恢復 TR。兩條路徑都從恢復後第 14 個連續有效 TR 才產生第一個 ATR；`true_sequence_start` 不得在中斷後 fallback。
- 呼叫端以停牌 assertion 表示「該 session 不應有可交易 bar」時，只有實際無 bar 或 bar 為全空價格 marker 才可跳過，不建立假 TR、不注入 `TR=0`，也不單因經過日數而重啟 warm-up。停牌 assertion 與任一 `open/high/low/close` 同時存在是矛盾 metadata，必須以 `suspension_price_conflict` fail-closed 並清空 recurrence，不能靜默忽略價格。合法復牌 bar 可與上一個實際可交易 bar 的 close 比較並延續 recurrence，但前提是跨停牌期間的價格基礎、公司行動與 availability 都可重建；否則仍按中斷處理。
- 實際輸出至少須可區分：warm-up 尚未完成、缺必要前收、缺預期 session、無效 OHLC、basis 不一致、公司行動證據不足、availability 在未來、停牌與價格衝突，以及呼叫端 assertion 所稱無 bar 的停牌／非交易 session。最後一類不是資料缺失原因，但純核心只能驗證 assertion 下的行為，不能證明真實市場確有停牌。
- rounding 只允許在持久化／呈現邊界進行；seed 與每一步 recurrence 都使用未四捨五入數值。測試以 exact fraction 或足以驗證 recurrence 的嚴格 tolerance 比較，不能把每根先 round 後的漂移當成正確。

### 4.3 公司行動與缺資料

- `high_t`、`low_t`、`close_{t-1}` 必須使用相同 adjustment basis。除權息、分割、合併等事件不能被誤算成市場跳空。
- 調整因子只能使用 `decision_at` 前已可得的公司行動版本；後來更正不得回填到舊 run。
- `corporate_actions` 明定為構成本 ATR artifact 共同 `price_basis` 所需的**完整 action dependency manifest**，不是只列在各 bar 當日以前生效的事件。全域 coverage、來源參照與可得時間均為強制證據；每個 dependency 也須有 complete coverage、相符 basis、來源參照及 `available_at <= decision_at`。
- 目前介面沒有 row／segment 到 action 的精確依賴映射，`action_date` 因此不能安全界定 backward-adjusted basis 的局部作用範圍。任一必要 dependency 為 partial／unsupported、缺來源或時間、尚未可得、basis 不一致，或上游因子為 0／非有限而無法宣告 complete 時，**整個 artifact 的共同 basis 都不可使用**：所有 observation 的 TR／ATR 為 `null`，不得讓事件前 adjusted bars 先進 warm-up。只有日後提供明確 per-row／segment dependency 關係，才可研究局部判定。
- 核心可接收「已同基礎／coverage 足夠」等明確輸入契約，但不能因此宣稱自行驗證了官方交易日曆、停牌或公司行動 truth。正式接線後，每筆 feature evidence 至少須保存 `price_basis`、完整 dependency manifest、因子來源／版本、`corporate_actions_applied_through`、必要 raw 參照及可得時間。
- 公司行動證據無法重建時，後續訊號須為 `data_incomplete` 或 tracking 為 `incomparable`；不得直接使用 raw gap 或 1.0 fallback。
- 新 ATR 寫入新 feature artifact／version。若沿用同一資料表，必須先加入能使 instrument＋date＋feature_version 共存的隔離方式；不得直接更新 legacy `features_json.atr14`。

### 4.4 獨立手算驗收矩陣

下列案例不依賴 legacy pipeline 或正式 DB，應由純核心單元測試逐項固定。`S1`、`S2`……代表該 instrument 的預期 session 順序；所有未特別標示的 OHLC、basis、coverage 與 availability 均有效。

| ID | 輸入與手算 | 精確期望 |
| --- | --- | --- |
| TR-01 無跳空 | `prev_close=102, high=105, low=100`。 | `max(5,3,2)=5`。 |
| TR-02 向上跳空 | `prev_close=100, high=110, low=108`。 | `max(2,10,8)=10`，不是 high-low 的 2。 |
| TR-03 向下跳空 | `prev_close=100, high=95, low=90`。 | `max(5,5,10)=10`，不是 high-low 的 5。 |
| ATR-01 seed 與逐根 Wilder | 真正序列起點 `S1` 無前收；令每根 `open=close=100.5`、第 k 根 `high=100.5+k/2`、`low=100.5-k/2`，故 `TR_k=k`，k=1…16。 | `S1` 可用 high-low。`S1…S13` ATR=`null`；`ATR_14=(1+...+14)/14=15/2=7.5`；`ATR_15=((15/2)*13+15)/14=225/28≈8.035714285714286`；`ATR_16=((225/28)*13+16)/14=3373/392≈8.604591836734693`。全程以未 round 值遞推。 |
| ATR-02 明確排除 rolling SMA | 沿用 ATR-01。14 根 rolling SMA 在 `S15` 為 `(2+...+15)/14=17/2=8.5`，在 `S16` 為 `(3+...+16)/14=19/2=9.5`。 | 新核心在 `S15` 必為 `225/28`、`S16` 必為 `3373/392`，兩者都不等於 rolling SMA；若得到 8.5／9.5 即失敗。 |
| GAP-01 一般截窗缺前收 | 查詢從既有標的 `S10` 開始且未供 `S9.close`；沒有「真正序列起點」證據。 | `S10` TR／ATR=`null`，不得用 high-low；若 `S10` 本身有效，其 close 只作 anchor，`S11` 才可能是第一個有效 TR。 |
| PREV-01 首根 row-level 前收 | first actual bar 沒有 calculator-level previous close，但自身帶合法 row-level previous close 100；當根 high=110、low=108。 | 當根立即計算 `TR=max(2,10,8)=10`。若明示的 row-level 前收任一證據不合法，則當根 fail-closed；即使 `true_sequence_start=true` 也不得改用 high-low=2。 |
| GAP-02 缺日後恢復位置 | 假設 `S20` 已有 ATR；預期有 bar 的 `S21` 缺失。`S22` 恢復且 OHLC 有效；`S23…S36` 各能產生 `TR=3`。 | `S21` 中斷並清空 recurrence；`S22` 因缺 `S21.close` 只能作 anchor，TR／ATR=`null`；第一個恢復 TR 在 `S23`；`S23…S35` 為 13 個 TR，ATR 仍 `null`；第 14 個恢復 TR 與第一個恢復 ATR 都在 `S36`，值為 3。 |
| GAP-03 缺日後明示 row-level 前收 | 同 GAP-02，但 `S22` 帶合法 previous close 100，且 high=103、low=100；其後每根 TR 也為 3。 | `S22` 可立即成為第一個恢復 TR，值為 3；第 14 個恢復 TR 與第一個恢復 ATR提前到 `S35`。`true_sequence_start` 不參與此恢復。 |
| HALT-01 caller-confirmed 停牌 | `S20.close=100`、既有 `ATR_20=4`；`S21` 由 caller assertion 表示不應有價格 bar；復牌 `S22 high=106, low=104`，且跨停牌 basis／action 可重建。 | `S21` 不產生 TR=0 且不重啟；`TR_22=max(2,6,4)=6`，`ATR_22=(4*13+6)/14=29/7≈4.142857142857143`。這只驗證 assertion 下的計算；若停牌證據或跨期 basis 不足，則改走 fail-closed 中斷。 |
| HALT-02 停牌與價格衝突 | 同一 `S21` 同時標 suspended，並帶任一非 null 的 open／high／low／close。 | `S21` TR／ATR=`null`、原因為 `suspension_price_conflict`，並清空 recurrence；不得忽略該價格後在 `S22` 延續舊 ATR。 |
| ACT-01 同基礎除權 | 合成測試 action ratio=0.9，且在 `decision_at` 前可得、coverage complete。原前收 100 轉為 ex-date 共同基礎 90；當日 `open=90, high=91, low=89, close=90`。 | `TR=max(2,1,1)=2`；不得把未調整前收 100 與 ex-date OHLC 混算成 11。evidence 能回查 ratio、版本、可得時間及共同 basis。 |
| ACT-02 future action 污染事件前 seed | `S1…S15` 已用 `S15` action 回溯轉為固定 adjusted basis；該 dependency 的 `available_at > decision_at`。 | 整個 artifact 的共同 basis 不可驗證，`S1…S15` 全部 TR／ATR=`null`；不得讓 `S1…S14` 先形成 seed，到 `S15` 才失效。較晚 as-of 可用新 snapshot 全窗重算。 |
| BAD-01 無效 OHLC | 例如 `open=100, high=99, low=98, close=100`，close 高於 high；或任一必要價格為 0、NaN、Infinity。 | 該根 TR／ATR=`null`、recurrence 清空；該根 close 不得當可信 predecessor。下一根至多重建 anchor，再下一個連續 session 才可能產生第一個恢復 TR。 |
| BASIS-01 row basis 不一致 | 某根前收為 raw、當日為 adjusted，或該 bar 宣告的 basis 與 artifact basis 不同；artifact-wide action dependencies 本身均合格。 | 該位置 TR／ATR=`null` 並重啟 warm-up；不得混算 raw gap。若問題其實是共同比價基礎所需 action dependency 不合格，則依 ACT-02 全 artifact 不可用，不作局部重啟。 |
| PIT-01 row availability 在未來 | `S8` bar，或在 state 缺失時依 precedence **實際被選為必要前收**的 row-level previous close，其 `available_at > decision_at`；artifact-wide action dependency manifest 全部合格。 | 此 as-of run 只在 `S8` fail-closed、清空 recurrence，後續依 row previous close／anchor 規則重啟。已有連續 state 而未被選用的附帶 row-level previous close 不單獨造成 null。若未來時間屬於必要 action dependency，則依 ACT-02 全 artifact 不可用。較晚 as-of 可用新 snapshot 另算，但不得回寫舊 run。 |

### 4.5 純核心輸出與 review 邊界

C-002 的實際入口為 `calculate_atr14(...) -> ATRArtifact`，並提供 `calculate_atr`／`compute_atr14` alias；主要輸入型別為 `OHLCBar` 與 `CorporateActionEvidence`，逐 session 輸出 `ATRObservation`。Artifact 固定帶 `feature_version=technical_v2_atr14_wilder`、`algorithm=wilder`、`period=14`、`input_snapshot_ref`、`price_basis`、UTC `decision_at`、observations、公司行動 dependency 與全域 coverage evidence；序列化另標 `provenance_validation=caller_supplied_only`。

除 `price_basis` 與 `input_snapshot_ref` 外，`expected_sessions`、含 timezone 的 `decision_at`、`corporate_action_coverage`、`corporate_action_source_ref`、含 timezone 的 `corporate_action_available_at` 都是強制輸入。calculator-level external previous close 或斷層後逐列 `previous_close` 若要使用，須同時有 finite positive 值、相符 basis、source ref 與不晚於 decision 的 availability；否則 fail-closed。首根 row-level previous close 在沒有 calculator-level 值時也必須可用；只有所有前收證據都未提供且 `true_sequence_start=true` 符合真正起點契約時，才允許 high-low fallback。

每一 observation 提供 TR 或 `null`、ATR 或 `null`、目前有效 TR 計數、bar／suspension 狀態與原因。OHLC 與前收需為 finite positive，TR／ATR 運算不逐根 rounding；seed 對大 finite 值避免中間加總 overflow，JSON 使用 `allow_nan=false`，非有限輸出不得序列化為研究 artifact。

只要結果要離開單元測試成為研究 artifact，就必須使用新的 `feature_version`，並可回查 period、smoothing、seed、精度政策、實作檔案雜湊／程式版本、設定快照、輸入 snapshot id／雜湊、ordered source row references、price basis、交易日曆／停牌版本、公司行動 coverage／版本與 availability evidence、`decision_at`／as-of、run id。相同 instrument＋date 的 legacy 與新版本不得互相 upsert；缺少可共存的儲存隔離時停止接線。

第一段 review 能證明的是：對**呼叫端提供的** session／basis／coverage／availability 判定，核心依本節公式可重現、遇缺口 fail-closed、且不使用逐根 rounding。它不能證明這些外部判定本身來自官方且正確，也不能以 mock metadata 冒充 point-in-time 來源系統、正式 DB 歷史 artifact 保存或完整 paired replay。這些是後續接線與 B7 的驗收範圍。

### 4.6 C-002 final review 證據與未完成邊界

C-002 新增 `backend/app/atr.py`、`backend/tests/test_atr.py`，並只修正 `frontend/src/presentation.test.ts` 的既存過時期待；沒有改實際產品文字。D-004a review 依序補上 artifact-wide action dependency、`suspension_price_conflict`，以及 first actual row 的 calculator／row-level previous close precedence；統籌於 2026-09-12 接受 final 純核心 review。

統籌使用 bundled Python 3.12.14、`PYTHONPATH=backend;backend/.deps` 與專案外隔離 Temp 資料環境執行 `python -m pytest backend/tests/test_atr.py -q`：28 passed、0.26 秒、exit 0。另以 bundled Node 將 `frontend/src/presentation.test.ts` 用 `tsc --module commonjs --target es2020 --skipLibCheck` 編譯至專案外 Temp，再執行 `node presentation.test.js`，編譯與執行皆 exit 0。前端與輪前備份精確比較只有測試期待從「回踩研究條件：已成立」改為目前產品文字「回踩條件：已成立」；`frontend/src/presentation.ts` 未改。這只證明該完整 presentation test 檔通過，不代表全 frontend suite 或瀏覽器 UI 驗收。

統籌另以獨立記憶體案例驗證：對稱 OHLC 的 `TR_1…TR_16`、seed `15/2`、後續 `225/28` 與 `3373/392` 在 `1e-14` tolerance 內成立；future action dependency 令全 artifact TR 為 null，較晚 as-of 可另算且舊 artifact 不變；首筆 row-level／calculator-level 前收 precedence 正確，invalid previous close 也不能以 IPO fallback 掩蓋。

final SHA256：`backend/app/atr.py` 為 `B74769A9C76AC30F9EA437B4124A8A0C964E32454129868B8EF756BDA523BD78`；`backend/tests/test_atr.py` 為 `E42099291783E4E324955B8F1BC2621C7451F50FACF58BDB8E23A1B442FF9722`；`frontend/src/presentation.test.ts` 為 `2ADD00B2A15F51FE29691BB321D67D103B1262B628CCF35BF34DCEDA37FF0E89`。統籌並以 hash 確認 `backend/worker/pipeline.py`、`backend/app/domain.py`、`models.py`、`api.py` 與 `frontend/src/presentation.ts` 均和本輪前相同。

程式 task 曾在三項 targeted 修正前執行完整 backend：153 passed、4417 warnings、23.92 秒；final review 沒有在最後修正後重跑完整 backend，因此不能宣稱 final full suite 156 passed 或等價結果。正式 worker 仍是 legacy ATR；官方 source truth、versioned persistence、完整 replay／B7 與瀏覽器驗收都未執行。

既有 `test_derived_features_use_score_date_corporate_action_basis_without_future_leak` 可作後續 worker 接線回歸入口；C-002 純核心測試不能取代正式 worker 的 legacy/new paired replay、versioned persistence、官方來源 truth 或 B7 驗收。

### 4.7 B3 持久化最小契約

B3 接線前須新增與 legacy `technical_features` 分離、可並存且預設不可變的 feature artifact 邊界。現表的 `uq_technical_feature_day(instrument_id, trading_date)` 與會更新的 `features_json` 保留作 legacy replay；不得只在同一 JSON 加 `feature_version` 後繼續 upsert，因為那不能證明同日舊、新值並存。

最小 artifact 每個 instrument＋market date＋feature observation 至少保存：

- 穩定 `artifact_key`、instrument identity、`market_date`、`feature_name`、`feature_version`、數值或 null、warm-up／reason code。
- 正規化為 UTC 的 `decision_at`、首次 artifact `generated_at`、input snapshot id／hash、ordered source row references；首次 `generated_at` 一旦寫入即不可變。retry／attempt 時間與 run 使用關係另表保存，不能為了重跑改寫 artifact。
- algorithm、period、smoothing、seed、precision policy、設定 snapshot、程式／檔案 hash。
- `price_basis`、交易 session／停牌版本、previous-close evidence，以及完整公司行動 dependency manifest、digest、coverage、來源與 availability。

identity 至少包含 instrument、market date、feature name/version、input snapshot、decision-at/as-of、price-basis digest、dependency digest、設定 digest 與實作 digest。若以固定 version registry 管理設定／實作 digest，則同一 `feature_version` 遇到不同 digest 必須先以 version conflict fail-closed，不能靜默產生同名不同義結果。

「相同 identity 的 payload 完全相同」只比較 canonical research payload；它包含研究數值／null、原因、來源／dependency、時間語意、設定與實作 digest，但排除本次 retry 產生的 attempt timestamp、attempt id 及 run 使用關係。相同 identity 重跑須回傳既有 artifact，沿用首次 `generated_at`，再另記 attempt／run relation；canonical payload 不同時 collision fail-closed。不同 as-of、snapshot、basis、dependency、設定或實作版本一律成為新 identity／明確版本，不可覆寫舊值。reader 必須以明確版本與 `decision_at` 選取，不得用未定義的「最新」自動替換歷史 run。

持久化驗收須證明 legacy table 的 row count／既有欄位 fingerprint 不變、新 artifact 的 unique／關聯／null policy 生效，以及同日 legacy、Wilder v2、兩個不同 as-of 可同時查詢。若 artifact 與 legacy 位於不同 SQLite 檔，跨庫關聯不得假裝由 FK 保證，必須改驗下節的自足 instrument identity 與 provenance。fixture 只驗 schema 與行為；worker 接線仍須另以官方 raw、session、公司行動與 availability 證據驗收。

#### 4.7.1 C-004 獨立 store 第一段契約（已 review：有限儲存段落）

C-004 是 B3-persist 的第一個儲存小批，不縮小前述父批驗收。採獨立 store 是為了隔離現有動態 0001／legacy `Base` 與 startup 自動初始化風險，不是重新定義整個 B3 已完成。統籌已 review 明確 opt-in 的獨立 SQLite artifact store；這個狀態只代表本節列出的本地 immutable 存取層，不代表來源與接線契約已通過。

1. **路徑與版本握手**：呼叫端每次都要傳入明確 artifact DB 路徑；不得回退到 `STOCK_DB_PATH`、`data/stock.db` 或其他預設值，也不得由 API lifespan、legacy `init_db` 或 worker 啟動隱式建立。新檔只能在這次明確 opt-in 下建立；既存檔必須先符合 artifact store 的固定識別與受支援 schema version，否則在任何 schema／資料變更前 fail-closed。未知或較新的 store version 同樣拒絕開啟。
2. **獨立 schema 語意**：artifact store 有自己的 schema/version marker；它不是 `alembic_version`，不得稱作 legacy 程式 head（目前為 `0006_news_json_defaults`），也不加入 legacy `Base.metadata`、Alembic revision chain 或 fallback `schema_migrations`。C-004 當時不改 `backend/app/models.py`、既有 migrations 或啟動流程。
3. **跨庫 instrument identity**：獨立 store 不建立指向 legacy `instruments.id` 的跨庫 FK，也不能只存一個在另一檔案中才有意義的整數 id。本段實作的 canonical instrument key 是 normalized exchange＋symbol；`market`／`instrument_type` 尚不是強制 identity 欄位。payload 另保存 instrument evidence 的 source ref、snapshot id/hash 與 `validation_status=caller_supplied_only`；這可稽核呼叫端聲明，但不能冒充官方驗證。nullable `legacy_reference` 只能作 link／診斷參考，不得當 referential-integrity 證明。
4. **完整 payload 與 provenance**：writer 保存完整 `ATRArtifact` 本體與所有 observations；previous-close、ordered source refs、instrument／source／calendar／halt 等是呼叫端另傳並保存的 evidence，不是 `ATRArtifact` 本身欄位。本段實作要求這些物件的最低非空結構並納入 canonical serialization。B3-persist 父批仍須驗完整 caller-provided 必需結構與缺漏政策；內容是否為官方 truth、manifest 是否逐筆對齊實際輸入、版本／availability 是否合格，則分屬 B3-wire／B5-time 後續，不反向成為 B3-persist 前提。不能在落庫時以空字串、當下環境或未版本化預設補齊必要欄位。
5. **UTC、identity 與 seal**：所有 timestamp 必須先驗證含 offset，再正規化為 UTC；例如合法的 `+08:00` 輸入須與對應 UTC 時刻等價，naive／date-only 才拒絕。研究 artifact 的 `decision_at` 不得為 null。canonical identity 明確含 feature version、instrument、observation market date/range、input snapshot id/hash、exact decision-at/as-of、basis/dependency/config/implementation digest；不同 digest 可直接形成不同 identity 並存。若實作另採固定 version registry，才要求同一 `feature_version` 遇不同設定／實作 digest 時 version conflict fail-closed，不能反向把 registry 變成 C-004 的強制設計。canonical payload 以 deterministic bytes 編碼並由 Python 計算／比對 SHA-256；SQLite 以 artifact key／identity unique、JSON-valid 等 check 與 immutable triggers 保護列。schema 1 沒有在 DB 內重算 SHA，也沒有獨立的 payload-hash unique／SHA check，不能把這層描述成資料庫自行驗 seal。
6. **不可變與 retry**：canonical artifact、observation、provenance 與實作若有的 version registry 寫入後，資料庫層必須阻擋 UPDATE／DELETE，且直接 SQL `INSERT OR REPLACE` 不能繞過；不能只依賴 Python frozen dataclass。相同 identity＋相同 canonical seal 回傳原 artifact 與首次 `generated_at`；相同 identity＋不同 seal 視為 collision。一次 `save_atr_artifact`／`save` 保存一個完整 ATRArtifact；parent、全部 observations、dependencies 與 attempt relation 任一失敗即同次交易回滾。這不要求通用多-artifact batch API，也不表示多次 save 共用交易。attempt id/timestamp、run id 與使用關係只追加到獨立關聯，不納入 canonical payload、identity 或 seal；retry 不得因此產生新 canonical artifact。
7. **精確 reader**：reader 至少要求 instrument identity、feature version、input snapshot id/hash 與 exact UTC `decision_at`／as-of；需要單日 observation 時再明確指定 market date。不得提供未定義的 latest fallback，也不得以 `<= as_of` 靜默挑一筆。零筆回傳明確 not-found；多筆或 selector 不完整須 fail-closed。

C-004 的最低 review 案例：新路徑建立及受支援版本重開；既存非 artifact／未知版本 DB 在 hash、mtime、schema 不變下被拒；legacy `stock.db`／`Base.metadata`／Alembic head 不變；完整 ATR 與 caller-supplied provenance round-trip；naive／date-only／缺最低結構拒絕，aware `+08:00` 正規化後可用等價 UTC selector 取回；同 identity retry 冪等、collision 令單次 save 全部 rows 回滾，若採固定 registry 才另驗 version conflict；兩個獨立連線競爭相同 identity 時仍只建立一個 canonical artifact；不同 config／implementation digest 可成為不同 identity 並存，reader selector 不完整或結果歧義時 fail-closed；兩個 snapshot／as-of 並存且 reader 只能精確取回；直接 SQL UPDATE／DELETE／`INSERT OR REPLACE` canonical rows 被 DB 拒絕；跨庫沒有 FK，仍可由 exchange＋symbol、identity source ref／snapshot hash 與 validation status 稽核 instrument 聲明。所有案例只算本地 schema／介面／失敗行為證據，不算官方來源、正式 DB、worker/API 接線、paired replay、策略切換或全 B3 完成。

### 4.8 C-004 final review 證據與未完成邊界

統籌於 2026-09-12 接受 C-004 的有限儲存段落。最終新增 `backend/app/artifact_store.py`，SHA-256 為 `40CEC8F0304E26456EC41C9C23DE03AE7ABE0F1B1145068508450430435DAC66`；`backend/tests/test_artifact_store.py` 為 `B519CF4FED6B45D46FAB8EA1590633F443630C9B7190ADFD7FFE3DE1D745CC7A`。程式 targeted ATR＋store 為 47 passed、exit 0。

統籌使用 bundled Python 3.12.14，`PYTHONPATH=C:/Users/YiCheng/AppData/Local/Temp/stock-r03-c003-alembic-deps-20260911-170100;backend;backend/.deps`，執行 `python -m pytest backend -q --disable-warnings`：176 passed、4486 warnings、26.84 秒、exit 0；包含真 Alembic 1.19.2，且 `conftest` 將 DB／raw 指到專案外 Temp。這是 final checkout 的完整 backend 證據，不是正式資料寫入或來源 coverage。

統籌的獨立 fixture／SQLite 報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-coordinator-5hv5_brl/review.json` 建於小修前 `artifact_store.py` hash `7593836d…`，驗證 empty／legacy／view DB 拒絕且 bytes＋mtime 不變、相同 attempt 與 `+08:00`／UTC 等價重播保留首次 seal、collision 後四表不變、parent／child `INSERT OR REPLACE` 與 child append 拒絕、含 `#` 檔名重開，以及 ThreadPool 雙連線同時保存相同 identity。最終 targeted／完整 backend 回歸覆蓋 final hash；另以 final source 建立 `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-final-review-c2_iri8g/review.json`，確認 ATR 為 null 卻無 reason、負 TR、負 ATR 都拒絕且 parent row count 維持 0，之後合法 ATR=5 可保存。這份獨立報告沒有 assert 四表全空或 persisted zero；0 只由程式非負規則允許，不能寫成已獨立驗證保存。程式測試另覆蓋未知 store version 在 bytes／mtime 不變下拒絕，以及 naive attempt timestamp 發生於 parent／observations／dependencies 插入後仍令四表整次回滾。

baseline `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-baseline-4fb9f0579d6141d295c3c0bcc9bc9e57.json` 記錄 `atr.py`、`models.py`、`db.py`、`migrations.py`、`api.py`、`worker/pipeline.py`、正式 `data/stock.db` 與 `.local/data/stock.db` 八個目標的 hash／size／mtime 均不變。artifact store schema 1 與 legacy Alembic head 0005 是兩套版本；沒有新 Alembic revision，也沒有 startup 或正式庫變更。

此 review 只證明 caller-supplied metadata 的最低結構、canonicalization、identity／seal、不可變 SQLite 保存、單一 ATRArtifact 交易、重試／衝突、精確 reader 與 ownership fail-closed。當時 B3-persist 尚待在同一證據範圍查詢／比較唯讀 legacy `technical_features`、Wilder v2 與兩個不同 as-of，並驗完整 caller-provided 必需 provenance 結構與缺漏政策；這個缺口已由下節 C-006 final review 補齊，不能反向把 C-004 單獨描述成整個 persistence 已完成。

另外，store 不查證來源是否官方／真實，不執行所有 `available_at <= decision_at` gate，也不接 worker、API 或來源 adapter；這些分別屬 B3-wire／B5-time 與 B7 後續，不是 B3-persist 結案前提。dependency manifest 與實際來源輸入的 truth／逐筆對齊會在來源接線時驗證；C-004 目前只保存並 canonicalize 呼叫端資料。故不得宣稱 B3、B2、B7、R0 或預設版本切換已完成。

### 4.9 C-006 provenance／compatibility final review 與完成邊界

C-006 只補 B3-persist 的剩餘儲存與本地比較邊界：嚴格驗證**呼叫端聲明的結構完整性**、隔離保存，以及同日唯讀 legacy＋Wilder v2＋兩個 as-of 的精確選取／比較。統籌於 2026-09-12 接受這個有限範圍，故 C-004＋C-006 涵蓋的 B3-persist 可標為已 review；它仍不驗證聲明是否符合官方 truth、不執行 PIT execution gate、不接 worker/API，也不取代 B7 paired replay。store schema 仍為 1；新契約固定為 name=`atr-provenance`、version=2、id=`atr-provenance/v2`、mode=`caller_provided_only`，instrument adapter 的 validation status 則沿用 `caller_supplied_only`。

#### 4.9.1 caller-provided strict provenance 的必要語意

strict write 必須帶顯式、可版本化且會進入 canonical payload、identity 與 seal 的 provenance profile discriminator；沒有 discriminator 的 schema 1 舊 payload 永遠只屬 legacy-compatible／minimal provenance，不能因 reader 升級或補一段新 metadata 就被宣告為 strict。嚴格 profile 至少完整涵蓋：

1. **輸入 snapshot 與 ordered rows**：snapshot id、snapshot hash、範圍／terminal market date，以及按計算順序保存的 row references。每個 row reference 至少能區分 sequence position、market session/date、來源 row identity 或不可變 digest、該列 snapshot 關聯、price basis、row status，及 timezone-aware availability；不得只存一組未排序 id 或只存總 hash。
2. **instrument mapping**：normalized exchange＋symbol 與呼叫端使用的 legacy／source identity 對應、mapping source ref、mapping snapshot id/hash、validation status。C-006 仍只驗結構並保存 `caller_supplied_only`，不把 nullable legacy id、名稱相似或自由文字當跨庫 referential integrity。
3. **method、config、implementation**：feature name/version、algorithm、period、smoothing、seed、precision policy、完整 config snapshot／digest，以及可重建的 implementation identity／digest。若實作採 registry，registry conflict 必須 fail-closed；若不採 registry，這些值仍須成為 artifact identity／seal 的一部分。
4. **共同 price basis**：basis 名稱、basis evidence/ref、適用 row/session 範圍與 digest；若需要公司行動轉換，必須回指實際 action manifest。row 與 artifact basis 衝突，或必要 basis 證據 unknown，不能產生被標為 verified-valid 的非 null 結果。
5. **calendar 與 halt**：calendar identity/version/snapshot、預期 sessions 或其 ordered reference/digest、coverage window；停牌／復牌 evidence 須能逐一說明預期 session 為有 bar、無 bar、停牌或 unknown，保存 source、snapshot、coverage、timezone-aware availability 與 reason。單純 `is_suspended=false` 不能證明整窗沒有停牌。
6. **previous close**：每個實際被 recurrence 選用的 external／row-level previous close，須保存 value 或 null、basis、對應 predecessor／current row、selection／not-used 狀態、source ref、snapshot id/hash、timezone-aware availability 與 reason。只要前收是必要輸入，空物件或無來源數值都不能通過；未被選用的候選亦不得冒充已使用證據。
7. **corporate-action manifest**：完整 manifest 必須有 canonical manifest digest、coverage window／expected scope、coverage status、missing/unknown 清單、source ref、source snapshot/version 與 timezone-aware availability；每個實際 action 至少帶穩定 row ref／digest、instrument、action/ex date、type、轉換參數、from/to basis、適用範圍與個別 availability。零 action 必須由明確 complete-none coverage 證明，不能以空陣列自行推論「沒有公司行動」。artifact 內既有 corporate-action 欄位、manifest、basis 與 ordered rows 的引用必須能一致交叉檢查。

store 本次實際收到完整結構的 manifest、config 與 basis 等 digest，必須由 deterministic canonical bytes 重算並核對，呼叫端不能只傳任意字串並跳過對應結構。外部原始檔、snapshot 或 implementation 若只提供 identity/hash 而沒有原 bytes，C-006 只驗其明確 algorithm、合法 shape 與 source identity 並原樣保存 caller-supplied digest，不能冒稱已重算或核真。所有 `*_at` 必須含 offset 並正規化為 UTC；date-only、naive timestamp、空字串、空物件及隱式環境預設都不是有效證據。這仍只證明送入 store 的 caller-provided 結構自洽，不證明來源為官方或時間聲明真實。

#### 4.9.2 unknown／null／reason 與有效性政策

- **結構缺失**：必要 evidence 類別、profile/version、selector、digest 所需結構、status、timezone-aware availability 或 required reason 缺失時，strict writer 在任何 canonical rows 寫入前 fail-closed；不得由 schema 1 預設、目前時間、空 manifest 或 legacy 欄位補值。
- **已明示 unknown/unavailable**：必要類別可用結構化 `unknown`／`unavailable` 表示，但必須有 machine reason code，必要時另有 human detail。這類 artifact 只允許保存受影響 observation 為 null、帶對應 null reason，並明示 evidence／result 不完整；不得同時保存受該證據影響的 non-null TR/ATR 並稱作 verified-valid。
- **不適用／未使用**：`not_applicable`／`not_used` 必須說明適用性與 reason，且與計算路徑一致；它不是 unknown 的別名。尤其 previous close 候選只有在 calculator 確實未選用時才能標 not-used。
- **完整聲明**：`complete`／`available` 只能表示 caller 的聲明通過本地結構與交叉一致性檢查，validation status 仍為 caller-supplied；C-006 不提升為 official-verified。缺必要 evidence 時可保存 fail-closed null 研究結果，但不能生成「已驗有效」結果。

#### 4.9.3 schema 1 相容與不可變政策

1. C-004 schema 1 的既有 payload、artifact key、research payload hash、首次 `generated_at`、observations、dependencies 與 attempts 全部原樣保留；不得 in-place backfill、重算 seal、UPDATE／DELETE 或以新 strict metadata 重分類。
2. 實作保留 store schema 1，透過新增的顯式 strict API 與 sealed `atr-provenance/v2` dependency manifest 區分能力；contract discriminator 與完整結構進入 canonical payload、dependency digest、artifact identity 與 seal。未知或較新的 store schema 仍由既有 opening handshake 在任何修改前拒絕，沒有 implicit migration。
3. 舊 schema 1 `save_atr_artifact`／`get_by_key` 只維持原本 minimal/caller-supplied 能力；普通 writer 可以保存舊契約允許的 caller metadata，即使含 strict-like marker 也不代表完成 strict 驗證。`save_atr_artifact_strict`、`get_strict_by_key`／`read_strict` 與 `get_strict_atr` 才能宣告 strict；strict writer 在 commit 前、strict reader 在每次讀取時都重驗完整 payload，矛盾或不完整 projection 必須拒絕，不能把欄位或 marker 恰好存在視為通過。
4. 不同 profile、snapshot、decision-at、basis、dependency、config 或 implementation 一律是不同 identity 或明確衝突；相同 identity 的 retry/collision 規則仍沿用 C-004。無 implicit migration、implicit latest 或以較新 metadata 覆蓋歷史 run。

#### 4.9.4 唯讀 legacy＋exact store 比較契約

比較入口必須由本地呼叫端顯式 opt in，並同時給出：(a) 明確 legacy SQLite 路徑、normalized instrument mapping、同一 market date、legacy snapshot/version 聲明與 `technical_features` 欄位；(b) 明確 artifact store 路徑，並以 `artifact_key` 精確選取後核對 instrument/date/feature/version，或以完整 feature version＋snapshot id/hash＋exact UTC `decision_at` 選取。caller 另提供的 selector 必須全部一致核對；不得以 `latest`、`<= as_of`、最大時間或第一筆代替，完整 selector 仍命中多筆時拒絕 ambiguity。legacy DB 以 SQLite read-only URI／`query_only` 開啟，並另列由 reader 實際核對的 legacy snapshot hash；任何需要建表、migration、journal-side effect 或寫鎖的情況都拒絕。零筆、重複 legacy row、mapping 不唯一或 store selector 不符都 fail-closed。

輸出以三個具名 operand 呈現同日 legacy、Wilder v2 as-of A、Wilder v2 as-of B，各自保留 value/null、reason、版本、decision-at/snapshot/basis/provenance level 與 exact key/ref，並對 legacy-vs-A、legacy-vs-B、A-vs-B 分別給 comparability、reasons 與 delta。差值只在該 pair 的 feature 語意、instrument、market date、price basis、snapshot、implementation 與非 null 結果明確相容時才可非 null；basis 或 snapshot 不同、任一 operand 為 null 或 strict profile 不足時，必須輸出 `incomparable`＋machine reasons 且該 pair delta 為 null。legacy row 沒有持久化的 algorithm/as-of/basis provenance，因此即使 caller 聲明與檔案 hash 字串吻合，legacy-vs-new 仍固定為 caller-declared-only／incomparable；legacy 缺值或缺聲明不能反向令證據完整的 v2 A-vs-B 變成不可比。比較不寫回任一 DB，也不能把一次本地結果當 B7 或正式 replay。

#### 4.9.5 C-006 已 review 驗收矩陣

| Case | 隔離輸入／動作 | 必須結果 |
| --- | --- | --- |
| PROV-01 | strict profile 提供完整 snapshot、ordered rows、instrument mapping、method/config/implementation、basis、calendar/halt、previous close 與 action manifest | round-trip 保留順序、UTC、canonical digests 與交叉引用；回傳仍標 caller-supplied，不稱 official truth。 |
| PROV-02 | 逐一省略必要 evidence 類別、ordered row 欄位、digest 結構、status 或 aware availability | 寫入前拒絕；canonical parent/children/attempt 均不增加。 |
| PROV-03 | 必要 evidence 明示 unknown/null 且帶 reason；另測 unknown 無 reason | 有 reason 時只允許對應 fail-closed null observation／result；無 reason 拒絕；兩者都不能產生 verified-valid 非 null 結果。 |
| PROV-04 | empty action list；一例有 complete-none coverage，一例無 coverage／source／aware availability | 前者可作 caller-supplied 零 action 聲明；後者拒絕，不能把空陣列當完整 manifest。 |
| PROV-05 | manifest／basis／artifact action、ordered rows 或 selected previous-close 引用互相矛盾 | fail-closed 且單次 save 全回滾。 |
| COMPAT-01 | 重開既有 schema 1 fixture，記錄 bytes/hash/mtime、舊 key/seal/payload | 舊 artifact 可按既有契約精確讀取且完全不變；strict reader 明確拒絕或標 non-strict，不能升格。 |
| COMPAT-02 | ordinary writer 保存帶 strict-like marker 但矛盾／不完整的 minimal projection；另以新 metadata 包裝舊 seal | ordinary schema 1 write 可依舊契約完成，但 strict reader 重驗後必須拒絕，不能升格；既有舊 payload 不寫回、不重算 seal、不重分類。strict writer 遇同類缺漏則在 commit 前拒絕。 |
| STORE-01 | 同 instrument＋market date 保存 Wilder v2 as-of A/B，snapshot／decision-at 不同 | 兩份 identity 並存；以 exact key，或完整 version/snapshot/exact decision-at 各自精確取回，錯 selector／implicit latest／ambiguity 拒絕。 |
| LEGACY-01 | 專案外 legacy fixture 先記 hash/size/mtime/table schema、row count 與既有欄位 fingerprint，再查同日 `technical_features` | 只讀取得 exact legacy row；比較前後所有 fingerprint 不變，沒有新 journal/schema/table/row。 |
| COMPARE-01 | 顯式傳 legacy selector；store A/B 分別用 exact key，或完整 version/snapshot/exact decision-at | 一份報告同時列 legacy/A/B 來源與選取依據；額外 selector 逐一核對，不寫 DB，不自動挑 latest。 |
| COMPARE-02 | store key 與 version／decision-at 不符、legacy 重複 row、instrument mapping 不唯一 | ambiguity/mismatch fail-closed，不回退第一筆或最近值。 |
| COMPARE-03 | A/B 的 basis、snapshot、version、implementation 不同或任一值為 null；另測 legacy caller 聲明恰好相同 | 每個 pair 分開標 comparable/reasons；不相容 pair 的 delta 為 null。legacy-vs-new 固定 caller-declared-only／incomparable，但 legacy 缺漏不反向阻塞相容且非 null 的 A-vs-B。 |
| SCOPE-01 | 僅使用 caller fixture／本地 Temp store 與 legacy fixture | 證據只可結論為 storage/provenance-shape/comparison 行為；官方 truth、PIT gate、worker/API、正式 DB、B7 均保持未驗。 |

#### 4.9.6 實際 API、證據與未完成範圍

`backend/app/artifact_provenance.py` 實作上述 `atr-provenance/v2` validator；固定頂層為 contract、feature、instrument、source、algorithm、basis、calendar、sessions、halts、previous_close、company_actions。ordered source rows 逐列保存 sequence position、row/session ref、snapshot、basis、status 與 aware availability；calendar/session/halt 保存 coverage window 及逐 session status。previous close 的 `selected` 是可含多筆的 list，每筆保存 current/predecessor ref；current 必須對齊 ordered source row，同 snapshot window 內 predecessor 也須對齊，window 外前收保留明確 snapshot reference。company-action manifest 的 item digest、instrument、from/to basis、scope、snapshot、source 與 availability 都必填，manifest digest、basis digest 與 config digest 由收到的 canonical 結構重算；外部 snapshot／implementation 的 SHA-256 或 SHA-512 只驗 algorithm/長度/hex shape，不冒稱已從原始 bytes 核真。

`ArtifactStore.save_atr_artifact_strict(..., provenance=...)` 是新增的顯式 strict writer，普通 `save_atr_artifact`／`save` 保持 schema 1 compatibility，仍可能依舊契約保存帶 marker 的 minimal caller metadata；marker 本身不會升格 artifact。strict save 在同一 transaction 內、attempt insert 後與 COMMIT 前呼叫完整 strict reader 驗證；失敗時 parent、observations、dependencies、attempts 四表全回滾。`get_strict_by_key`／`read_strict` 與 `get_strict_atr` 每次重新驗 contract 及 persisted payload/row identity，會拒絕 ordinary writer 產生的矛盾／不完整 strict projection；舊 C-004 payload 仍可由普通 reader 讀取，但 strict reader 明確拒絕，沒有重寫、升級或重算舊 seal。

`backend/app/artifact_comparison.py` 提供 `LegacyTechnicalFeaturesReader`、`ReadonlyArtifactReader` 與 `ArtifactComparisonReader`。兩個 SQLite 都以 URI `mode=ro` 與 `PRAGMA query_only=ON` 開啟；路徑含 `#` 可安全處理，缺檔、live WAL/SHM/journal sidecar、讀取期間檔案變更、ownership/schema 不符都拒絕，操作者須先提供 stable checkpoint file。legacy selector 明示 snapshot/version 並由 reader 核對實際檔案 SHA-256；artifact selector 使用 exact key，或完整 feature name/version＋snapshot id/hash＋exact aware decision-at。legacy exchange＋symbol 映射多個 instrument id、同日重複 row、strict selector 歧義或任何 cross-identity mismatch 均 fail-closed，沒有 implicit latest。

final source SHA-256：`artifact_store.py`=`0C0907289B66D3979C55232F46024DEB7B7EE7EFAC7FBF91EEC5FD020B849ED4`、`artifact_provenance.py`=`B28109D7218BD8FA2127DD9C6AAEFB60E210BE3C0A3B253744267EE97F3695D8`、`artifact_comparison.py`=`08BA9301FDFD73F91C571D1DA08697A1F8D720D7AF16D7593E4FC15D5D6441FA`；測試／fixture 分別為 `test_artifact_provenance.py`=`B940280A0C5846B037CE68DF5E908CC4CBAFB2C8CEB6BCA9557B6B42C38CFC2C`、`test_artifact_comparison.py`=`48B9025EC86DF8379BBB7BCA2F091A15EE12FA3C5E6A7B33F45AEF4273F711EE`、`strict_artifact_fixture.py`=`3D495A4EBF0B06AEAB6C8F18E794BF6BC972E07E0D059212EFD9B155E453D24B`。既有 `test_artifact_store.py` hash 仍為 C-004 的 `B519CF4F…`。

統籌以 bundled Python 3.12.14、`PYTHONPATH=C:/Users/YiCheng/AppData/Local/Temp/stock-r03-c003-alembic-deps-20260911-170100;backend;backend/.deps` 與外部真 Alembic 1.19.2 執行 `python -m pytest backend -q --disable-warnings`：200 passed、4592 warnings、25.72 秒、exit 0，並確認上列六個來源 hash 對 final checkout 一致。程式 task 另一次完整回歸也是 200 passed、4592 warnings、25.75 秒、exit 0；這是分開的作者證據，未與統籌時間混寫。

統籌 final 獨立報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r06-final-review-dg6tjhm9/review.json` 驗證：新 strict save 與 retry 在 pre-commit validator 注入失敗時四表完全不增加；同日兩 as-of 並存且相容 v2 pair delta=0；settings 不同時 pair-specific incomparable 且 delta=null；含 `#` 的 legacy fixture bytes/mtime 不變；原 C-004 payload/seal/DB bytes/mtime 保持且 strict reader 拒絕舊 artifact。反例報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r06-negative-review-j8lsx8pw/report.json` 的非法 hash／algorithm、row unknown＋non-null ATR、halt 矛盾、錯 expected legacy hash、缺檔、live WAL 與 duplicate identity 均通過；該報告對應中間 source hash，不能冒稱 final-hash 獨立報告，final 作者/統籌完整回歸只證明這些程式測試在 final checkout 通過。

`C:/Users/YiCheng/AppData/Local/Temp/stock-r06-coordinator-p5raawt4/protected-review.json` 確認 `atr.py`、`models.py`、`db.py`、`migrations.py`、`api.py`、`decision.py`、`domain.py`、`worker/pipeline.py`、`frontend/src/App.tsx`、正式 `data/stock.db` 與 `.local/data/stock.db` 的 hash/size/mtime 都不變。本輪沒有前端變更，也沒有重跑 UI/build；這不影響純離線 B3-persist 的有限 review，但不能宣稱前端、B3-wire、B5-time、官方 truth、正式 DB 接線、B7 或整體 R0 已完成。

## 5. R0-2：legacy confidence 與未校準預測邊界

### 5.1 欄位語意

四種概念必須分欄，任何一種都不得借用另一種數值：

| 概念 | 建議欄位 | 允許值與呈現 |
| --- | --- | --- |
| 資料是否足夠 | `data_quality`＋缺項原因 | complete／partial／missing；不是機率。 |
| 規則是否通過 | `status`／`rule_state` | observation／conditional／data_incomplete 等；不是機率。 |
| 來源／新聞關聯證據 | `relation_confidence` 或 evidence level | high／medium／low／unknown；只描述關聯證據。 |
| 經校準預測 | `prediction.probability` | 只有明確 target、horizon、模型及 calibration 通過時才可為 0～1。 |

legacy `Signal.confidence` 的相容契約：

- 只有同時符合已知 legacy strategy name allowlist、strategy version `1.0.0`，且原值確實為 `0.75` 的既有列，才能輸出實際 kind `legacy_fixed_value` 與 version `signal-confidence/v1-fixed`；不可稱勝率、成功率、上漲機率或模型信心。已知策略下的其他 non-null 值也不得套用此標籤。
- 舊欄位暫時保留供 client 相容與歷史重現，不批次改值、不複製到 `prediction.probability`、不參與排序、gate 或績效。
- 無法證明來源語意的其他 non-null 舊值輸出實際 kind `unknown_numeric`，同樣是 `is_calibrated=false`、`is_probability=false`，不得顯示百分比。
- 新建 rule-only signal 的 `confidence` 為 `null` 並保存 `signal-confidence/v2`／`not_calibrated`；同 key 已有 non-null legacy 值時原值保留，重跑只重建受信任的非機率 semantics，不洗掉原數值。這是 C-001 的最小相容行為，不等於同日新舊 artifact 已並存。

未校準預測的相容契約：

- 模型可保存 `raw_score` 供研究，但必須帶 `calibration_status=uncalibrated|failed|out_of_scope`，且 `probability=null`。
- UI 只顯示「預測尚未校準／不適用」，不得把 raw score 乘 100 加 `%`。
- 可顯示 probability 的輸出必須同時有 target event、horizon、as-of、model version、calibration version、校準樣本範圍及適用範圍；缺一即 fail-closed。

### 5.2 C-001 實際相容行為與驗證

C-001 沒有 schema migration，也沒有硬套先前提案的 prediction 欄位：

1. `backend/app/domain.py` 定義 `signal-confidence/v2`／`not_calibrated`、`signal-confidence/v1-fixed`／`legacy_fixed_value` 及 `unknown_numeric`；三者均為 `is_calibrated=false`、`is_probability=false`。
2. legacy 常數只在 strategy name 為 breakout_v1／pullback_v1、strategy version 為 1.0.0 且值為有限數字 0.75 時成立。helper 不信任 evidence 內自行宣告的 marker；偽造 `prediction`／`is_probability=true` 會被重建成 canonical 非機率語意。0.74、0.80、未知 strategy／version 皆 fail-closed 為 `unknown_numeric`。
3. `backend/worker/pipeline.py` 對新 rule-only signal 保持 nullable legacy `confidence=null`，並在 rule evidence 保存 `confidence_semantics`；同 key 既有 non-null 值原樣保留。backtest metadata 也保存新語意 marker。規則 gate、價位、執行及 strategy version 未改。
4. `backend/app/api.py` 在完整與 compact signal payload 都以實際 strategy name／version 重新計算 `confidence_semantics`；舊 `confidence` 欄位仍保留相容，但不映射成 prediction probability。
5. `frontend/src/types.ts` 接入 semantics type；行動卡技術資訊使用 `display_label_zh`，缺欄時 fallback 為「未校準；非預測勝率」，一般卡片不顯示 75%。

統籌獨立後端驗證使用 Python 3.12.14、`backend/.deps` 與隔離 DB `C:\Users\YiCheng\AppData\Local\Temp\stock-c001-review-c8a5806917ae49bfa563696f3897d31b`，完整 pytest 結果為 128 passed、4417 deprecation warnings、22.85 秒、exit 0。程式 task 另回報 targeted 4 tests 與 `pnpm build` 通過。

前端 baseline 由統籌在專案外 `C:\Users\YiCheng\AppData\Local\Temp\stock-c001-frontend-review-c99f472566834ffe8eb062920a03ed17` 以相同 `tsc --module commonjs --target es2020 --skipLibCheck` 流程比較 original／current：兩者都在同一 `passed pullback result must be shown as established` assertion exit 1，原版第 21 行、目前第 27 行；新增三個信心語意 assertions 在該失敗前已通過。這證明該 failure 為既存 baseline，不代表前端整套測試通過。

C-001 的最小相容範圍已 review；未執行正式 DB migration／歷史回寫、雙版本 artifact、全量新舊 replay、ATR、規則價位或時間修正。

### 5.3 B2：完整雙版本 artifact 與 replay

若規則 gate、價位與執行完全不變，writer 可用新的 `signal_output_semantics_version` 對 rule-only signal 寫 `confidence=null`，不必假裝 strategy 規則升版；若任一規則行為也改變，則必須建立新的 strategy／execution version。無論採哪個軸，新輸出都必須使用不同 version key、namespace 或實體 artifact，不能只在同一列補 metadata 冒充並存，也不能讓重跑洗掉既有 legacy row 的 0.75 與版本證據。

舊輸出須能與同日新輸出並列比較，或以保留原始輸入與版本的完整歷史 replay 重放；舊語意 replay 若仍產生原始常數，只能寫入隔離 legacy artifact。任何預設新 run 不得再產生固定常數。Round32 已提供 caller-selected 既存 legacy／new snapshots 的有限 exact 描述性比較；Round33 提供 caller-provided current pure-rule complete-argument replay；Round34 再把現行 legacy analysis 的 actual kwargs/result、subject/date/strategy、Signal snapshot 與 R33 private bundle保存到 owned research DB。R34 仍沒有 SignalArtifact bridge、official source/availability/decision-time或 legacy-v2 新輸出，因此三者都沒有證明完整 paired replay；B2 的全量雙版本邊界仍未完成，也不是 C-001 首批必須先完成的 schema 重構。

B2 全量驗收仍要求：同一 instrument＋market date 可同時查到舊、新 artifact，或以完整保存的舊輸入／版本重放舊輸出；舊列內容／雜湊不變且重跑不會洗掉 0.75；新列 confidence 為 null；規則 gate、價位與資料品質若輸入相同則僅有預期的 output-semantics 差異。Round32 report 的 top-level `comparable` 固定為 false；subject 與 status lexical observations 不證輸入相同。Round33 report 把 subject/time/historical/availability/PIT/full-signal 六項宣稱固定為 false；Round34 readback result 也固定 `historical_inputs_verified=false`、`availability_verified=false`、`pit_verified=false`。`arguments_digest`、actual capture 或 observed date都不得冒充完整 historical snapshot identity。完整測試仍須覆蓋 artifact create/upsert/replay、API list/detail、行動摘要及前端呈現。

### 5.4 B2 持久化最小契約

B2-persist 的實際 research-core lineage、含 revision 的 identity hash、version binding、transaction、exact reader 與驗收矩陣集中於 [Signal artifact 持久化契約](SIGNAL_ARTIFACTS.md)。Round12 C012 已按該文件的有限本地 foundation 通過統籌 review；Round32 comparison 見 [Signal comparison](SIGNAL_COMPARISON.md)；Round33 current pure-rule replay 見 [Rule replay](RULE_REPLAY.md)；Round34 actual worker caller 見 [Worker analysis capture](WORKER_ANALYSIS_CAPTURE.md)。四個 slices 都不改變 B2 整體未完成的狀態。

B2 須使用與 legacy `signals.signal_key` 分離的 immutable signal artifact 或等價的獨立 namespace；不能只改同一列的 `rule_evidence_json` marker 或擴充既有 `signal_key` 後讓 writer 更新舊列。legacy `signals`、其 evaluation／settlement 與原始 0.75 保持可重現。

每個新 signal artifact 至少保存：

- 穩定 `artifact_key`、instrument identity、`market_date`、strategy name/version、`signal_output_semantics_version`、status／rule state、nullable confidence 與 canonical confidence semantics。
- 所用 feature artifact keys、input snapshot id／hash、規則設定 snapshot、rule evidence、data quality／missing reasons、source／company-action dependency digest；run 使用關係與 retry attempt metadata 另存，不是 canonical research payload。
- `decision_at`、首次 artifact `generated_at`、nullable `earliest_execution_at`；legacy 相容日期／字串只能另列，不可取代新時間角色。缺少合法交易 session 或 availability 證據時，`earliest_execution_at=null` 並保存明確 reason code，不得因 schema 要求捏造時間。
- 建立、重放與 lifecycle 變更的不可變 revision／supersedes 關係；若需連 legacy，可用 nullable legacy reference，不得反向更新 legacy payload。

identity 至少區分 instrument、market date、strategy version、output-semantics version、input snapshot、必填 aware decision-at、nullable aware as-of、price-basis／dependency digest、規則設定 digest 與實作 digest。若固定 strategy／semantics version 對應到不同設定或實作 digest，writer 必須以 version binding collision（`SignalArtifactCollisionError`）fail-closed 並 rollback，不能把版本字串當無意義標籤或虛構未實作的 reason code。

canonical research payload 排除 retry 的 attempt timestamp、attempt id、run 使用關係，也不比較呼叫端在 retry 新傳入的候選 `generated_at`。首次 artifact `generated_at` 是不可變的封存 metadata；相同 identity 重跑回傳既有 artifact 與原首次值，並另記 attempt／run relation。真正 canonical research payload 不同時 collision fail-closed。不同版本、as-of、basis、dependency、設定或實作建立新 identity／明確版本。Round32 library 已能以 exact selector 同時取得 caller 指定的 legacy／new，但不接產品；API list/detail/action 仍必須回傳實際選取版本與 provenance，預設選擇政策須明示且在 B7 review 前不得自動切到新版本。

B2 的 schema／writer 驗收包括 create、同 identity replay、collision、legacy-preservation、API list/detail、DecisionSummary 與前端非機率呈現。C012 只結清其中的本地 pure/store foundation；輸入一致時，legacy 與 v2 的 strategy status／價位／quality 除預先列出的 output-semantics 差異外仍必須一致，若不一致即停止並查明，不得歸因為「新版本較好」。

### 5.5 Round12 C012 final review 證據與未完成邊界

C012 的 caller mapping 可省略 `contract` 或給 `null`，normalizer 會補 `signal-artifact/v1`；若提供 non-null 未知版本則拒絕。caller-facing dataclass 沒有 `contract` 欄。實作沒有 `revision_id`／`revision_kind` 或獨立 `levels` 欄：positive integer `revision`、`lifecycle_state` 與 `supersedes_artifact_key` 表達 root／withdrawal 關係；價位只有 caller 放進 `rule_evidence` 時才保存。`lineage_key` 由不含研究輸出的 research core 導出，`identity_hash` 則包含同一 core **與 revision**，不可把後者誤稱純 input hash。

統籌 final source SHA-256：`signal_artifact.py=F8B6B56853E08FF263498E96E12A402AEBB1500F5CC5847C9DDFAECEEF14A2D9`、`signal_artifact_store.py=DD3CF18C64A5B848F43110B32FA51CDA7517304E0D785DEA6B1876D2F635E620`、`test_signal_artifact.py=A821EDD0F0FF50204F6F38DA889A0DEF2F18C683A03905BA4AE1CDC4ADBC77E7`、`test_signal_artifact_store.py=C8EF20AB672AC7CF4896A1F902E627FB38C950B43D958C051FD57CD70E2BE319`。bundled Python 3.12.14、true Alembic `PYTHONPATH` 與專案外 Temp 環境下，統籌完整 backend 為 285 passed／4625 warnings／16.95 秒、exit 0，獨立矩陣 45／45；作者 targeted 為 26 passed／1.56 秒、完整 backend 285 passed／17.29 秒；文件角色重跑 targeted 為 26 passed／1.57 秒、exit 0。證據集中在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r12-coordinator-review/` 與 `C:/Users/YiCheng/AppData/Local/Temp/stock-r12-d014-review/crossreview.json`。

保護目標是 **40／41 unchanged**，不是 41／41。正式 `data/stock.db` 仍為 296,054,784 bytes、hash `74A34389…32D6` 且沒有本輪 migration。唯一例外 `.local/data/stock.db` 是另一個 `執行前後端專案` task（`01a0913c-797b-7863-a5a6-5f47f469bc9b`）依使用者另行要求於 09:27 啟動 lifespan `init_db` 所致：425,984 bytes／`306D9D81…E39A9` 變為 438,272 bytes／`87453D7B29954B6D506F8020B8987F321AA6749CE9BC24FBEF695DD3874B8D02`，mtime `2026-09-12T01:27:28.7179604Z`，其後唯讀查驗為 0006、兩個 News JSON defaults 均為 `[]` 且讀前後 hash 穩定。此可歸因外部變更不是 C012 寫入、部署或 migration 驗收，也不能據此宣稱 `.local` 所有歷史列由 C012 preservation test 證明。

C012 當時接受範圍只有 pure normalization、version binding、immutable local store、linear active→withdrawn lifecycle、attempt/run relation、exact／filtered reader 與 fail-closed ownership／integrity；當時 legacy／new 同日 exact comparison 仍待後續。Round32／33 分別補有限 exact comparison與 current pure-rule mechanics，Round34 再補 actual legacy worker evaluation capture；四者仍未建立 SignalArtifact與可證 source/availability/decision-time的 linkage或 legacy-v2 paired replay。API list/detail/action、DecisionSummary、前端、default、官方 availability／PIT、B7 paired replay 與預設版本切換仍待後續，B2 與 R0 整體均未完成。

### 5.6 Round32 C032-B offline exact comparison（有限 review）

`compare_signals` 要求兩個 caller-provided external absolute rollback-mode SQLite files、各自 expected SHA-256、opaque exact legacy key 與 exact artifact selector。legacy 以 BINARY query，不解析 key 或 fallback；artifact selector 只允許 key／identity hash／lineage＋positive nonbool revision，多條件 AND。zero row 是 structured missing；duplicate、schema、primitive、FK、evidence、ownership、selected/ancestor/binding/ref/lifecycle/attempt-run integrity 則 hard fail，malformed SQLite 可直接是 `sqlite3.DatabaseError`。

兩側 path/hash/sidecar/WAL-header 都在任一 SQLite-open 前 preflight；readonly factory 不走 writer constructor／DDL／`BEGIN IMMEDIATE`，而使用 `mode=ro`、`query_only`、deny-write authorizer、read `BEGIN` 與前後 fingerprint。read/write header byte 2 即使沒有 sidecar 仍拒絕，library 不做 checkpoint。這只偵測 observed change，不是 cross-file atomic、active-writer、hostile-race、crash 或 disk-full 保證。

report 固定 `signal-comparison/v1`／`comparable=false`。subject equal/different、raw status 與 linkage 都只描述 caller 所選 row；confidence、prices、evidence、quality、time、revision、inputs 保持 incomparable。new `legacy_reference` 對 requested legacy key byte-for-byte 比較；既有 artifact contract 會 trim optional reference，但 legacy key opaque，故空白差異會形成成功的 conflict report，不會 auto-trim 或 fallback。詳細 API/result/errors 見 [Signal comparison 離線唯讀契約](SIGNAL_COMPARISON.md)。

統籌 final matrix 58 cases／68 readonly connections／915 SQL statements、exit 0。作者 final targeted 129 passed／1 skipped；作者 full backend 2,264 passed／2 skipped／12,414 warnings、pytest 280.69 秒／process 283.578 秒、exit 0，162 guards unchanged；統籌 review raw full evidence，沒有冒稱重跑 full。D034 focused probes 11／11、exit 0。所有數字屬分開 run，不相加。三個 frozen source hashes 與完整失敗史見 comparison 契約；D034-B manifest 只封存 5 個 review artifacts 的 SHA／bytes，不含 mtime 或完整 raw fixture manifest。

本批只新增 library、readonly store entry 與 tests，不接 CLI／API／UI／worker/default，不開／改正式或 `.local` DB，不做 migration、backup、repair 或 replay。其後 Round33 另依 §5.7 完成 current pure-rule caller bundle 的有限 capture/replay，不回寫成 Round32 已具 replay；B2／B7／PIT／來源 truth／預設版本切換維持未完成。

### 5.7 Round33 C033-B caller-provided current pure-rule replay（有限 review）

Round33 新增 `backend/app/rule_replay.py` 與 `backend/tests/test_rule_replay.py`，public API 為 `capture_rule_inputs`、`rule_replay_json`、`replay_rule_inputs` 及 contract／binding／execution 三個 typed error families。支援範圍只有 `breakout_v1@1.0.0` 與 `pullback_v1@1.0.0`；bundle 保存 exact complete admitted arguments、ordered histories、explicit null、selected full config snapshot、原始 `RuleEvaluation`，以 `arguments_digest` 綁 evaluator＋arguments，再由 `bundle_digest` 覆蓋 implementation/config、arguments 與 recorded-result claim。

Local binding 固定完整 `domain.py` bytes SHA-256 `db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028`、兩個完整 config digests、CPython 3.12.14 與 binary64。每次 operation 對 fixed sibling path bounded-read/hash，同一批 bytes compile／exec 到 fresh private module，再驗 config；不使用 shared `app.domain`／cached pyc。Identity-guarded cleanup 移除自己註冊的 module，hostile host 替換的 unrelated entry 不刪；host/interpreter/registry manipulation 不在 sandbox 保證。`rule_replay_json` 不呼叫 evaluator，但會 compile／exec source 驗 binding。

Strict boundary 是 native JSON、raw/canonical UTF-8 各 1 MiB、container depth 16（root=1）、history 10,000、integer ±(2^53−1)、finite input float、duplicate key／cycle／surrogate／nonfinite literal 拒絕。Finite inputs 造成 evaluator intermediate infinity 時保留既有 v1 behavior。Replay report 只比較 recorded/replayed `passed`、`state`、ordered `reasons`；`historical_inputs_verified`、`subject_identity_present`、`market_time_present`、`availability_verified`、`pit_verified`、`signal_reconstructed` 全為 false。`arguments_digest` 是 content identity，不是 authentication、research-core 或 historical snapshot hash。

Frozen source SHA-256：`rule_replay.py=1f0e7dbd535bd4818e56eccfd08cd919e2e2bc4ce72bb64c352c22cec5e9602c`、`test_rule_replay.py=2127c1d1d255f0773709f129a89742b19e4732de8085102179bf186770727cac`；既有 `domain.py` 未改。作者 final targeted 為 151 passed＝141 new＋10 existing domain、pytest 2.38 秒／process 2.925512899993919 秒，早期 `139+12` 是作者訊息拆分錯誤；作者 final full 為 2405 passed／2 skipped／12414 warnings、pytest 355.05 秒／process 357.94884170001023 秒。兩者均 exit 0、165 guards unchanged。統籌另驗 caller-contract 82／82 與 binding/fault/concurrency/audit 25／25；D035 source review 無 in-scope blocker，小型 probe 最終 exit 0，沒有冒稱重跑上述 suites/matrices。所有 run 分開，不相加；failure history 與 API/error/schema 全文見 [Rule replay 契約](RULE_REPLAY.md)。

本批不改 evaluator、schema、store、worker、API、UI、DecisionSummary、default 或 DB。它也沒有 subject/time/source/availability、historical input recovery、SignalArtifact persistence/bridge 或 legacy evaluator，因此不滿足 §5.3／§5.4 的完整 B2、same-snapshot paired replay 或 B7；不得以 bundle 可重播、digest 相同或 `exact_match=true` 宣稱 PIT 或完整 Signal reconstruction。

### 5.8 Round34 C034-B opt-in worker evaluation capture（有限 review）

Round34 新增 `backend/worker/analysis_capture.py`，並只在 `pipeline.py` 抽出 caller-owned transaction 的 `_analyze_session(db, capture=None)` 與 optional collector callbacks；一般 `analyze()` 仍自行 init/Session、只在 success commit，default 不做 private replay。Caller 用 external stable rollback-mode source snapshot＋expected SHA exclusive 建立 owned research DB；同一 transaction 保存實際 analysis 產生的 legacy Signals、每個有 bar subject/day 的四次 actual evaluator kwargs/result、R33 private bundle與 sealed receipt。同 ID 只 strict readback原 attempt；新 ID 才需三個 external STOCK paths、lazy imports與完整 readiness。

Final source SHA-256 為 `pipeline.py=D6311842C2F7F73B8925439BC706B09BEAA191BD4CDD867C613AFD0212F55BB4`、`analysis_capture.py=3EF5F5C71FB5F9F51CE6043C7C7E1E1EDF2300924C588A7D61719FF178D7C980`、`test_worker_analysis_capture.py=111C880A0D79A0384FA6B80CD779362F0393560A46E384A9F2CA293576160409`。作者 final exact targeted為52 passed／8,929 warnings／12.88秒／exit0；作者 full 2,436 passed／2 skipped是較早 capture guard SHA，只能分開列為 default pipeline與較早guard回歸。統籌 final public/fault/six-negative/CLI四組probe及D036 owner/schema/env/same-ID/type-tamper probe均exit0，不與pytest case數相加。舊 `9B114967...` 的 `false==0` equality blocker經實際負例失敗後才改canonical JSON identity；Windows UTF-8與mtime JSON-safe harness失敗也保留在歷史。

本批沒有讀寫正式 DB；正式 DB 因另一process占用而無法取得byte hash，所以不宣稱 unchanged 已驗。Capture的 `observed_market_date`／`captured_at` 不證 decision/availability/PIT，legacy Signal snapshot不是SignalArtifact或校準prediction。上游 group member details仍只存symbol，現行 lookup也只按symbol，因此雙exchange同symbol只證subject capture分離，不證group-excess provenance已exchange-aware。完整可執行API/CLI、local schema、outcome/error與限制只在 [Worker analysis capture契約](WORKER_ANALYSIS_CAPTURE.md) 維護。

## 6. R0-3：規則參考價與新交易計畫

### 6.1 legacy 價位的強制標示

Round05 的 R0-C1／B4a（C-005 程式、D-007 文件）已通過統籌 review，範圍僅限 **read-time API／presentation 價位語意**。本批新增共用 `backend/app/level_semantics.py`，不改 worker、schema、legacy 列、v1 gate 或數值；B4b 新交易計畫與 B5 時間／PIT 仍未完成。

來源核對可證明的範圍如下：

| 面向 | 本批可證明 | 必須 fail-closed 的部分 |
| --- | --- | --- |
| strategy identity | `StrategyVersion.name/version`；只有 `breakout_v1@1.0.0`、`pullback_v1@1.0.0` 在 B4a allowlist。 | 名稱相同但 version 不同、缺 strategy relation 或其他 strategy 不得套 v1 標籤／公式；回傳 `kind=unknown` 與 reason。 |
| v1 數值 | `_risk_levels` 與呼叫端可重現既有 entry／invalid／1.6R／3R 及 pullback zone；本批不重算、不改值。 | 缺值或異常值維持原 API 相容值／null；presentation metadata 不替它捏造數值。 |
| price basis | 數值來自 legacy `MarketBar` 與 `TechnicalFeature` 路徑。 | Signal/evidence 沒有持久化、逐列可驗證的 basis identity，故 `price_basis.value=null`、`reason=legacy_price_basis_not_persisted`；不得僅由 `adj_close` 欄位、公司行動列或 feature 計算路徑宣稱 raw／adjusted。 |
| cost | `_risk_levels` 與 zone 算式沒有扣費稅或滑價。 | `cost_included=false` 只描述**規則價位公式**；evidence 的買賣 5 bps／round-trip 30 bps 是 execution/backtest 假設，不是 level 已含成本，也不是真實費率。 |
| time | legacy `signal_date` 是 market date；`data_cutoff` 是舊字串；API response 組裝時間可另以含 offset 的 `response_generated_at`（或等義欄位）呈現。 | historical signal-level `decision_at=null`＋machine reason；naive `Signal.created_at` 不提升成 historical `generated_at` 或 `decision_at`，date-only `signal_date`／`earliest_execution_date` 也不補午夜。historical signal-level `generated_at=null`＋machine reason；response now 必須是另一角色，不能放進 level semantics 冒充歷史生成時間。 |

目前 `_risk_levels` 的價位保留作 v1 可重現基準，但所有使用者可見位置及 API evidence 必須標為規則參考值：

| legacy 欄位 | 使用者標籤 | 禁止文字 |
| --- | --- | --- |
| `breakout_price` | 規則觸發價 | 精準買點、建議成交價。 |
| `pullback_low/high` | 規則回踩觀察區 | 保證承接區。 |
| `reference_entry` | 規則計算參考價 | 已成交價、預測買價。 |
| `invalid_price` | 規則失效參考價 | 保證停損成交價。 |
| `target_1/target_2` | 規則參考目標一／二 | AI 目標價、保證報酬。 |

API／evidence 至少能辨識 `level_semantics.kind=rule_reference`、strategy version、level formula/version、price basis、generated/decision time 及成本是否已納入。B4a 只改 presentation contract，可由既有 strategy allowlist 推導標籤，不能回寫研究列。

#### 6.1.1 read-time `level_semantics` 語意契約

full／compact signal、signal list/detail、action list/detail、stock detail 的 action projection、tracking list/detail 使用同一個 read-time helper；既有數值欄位仍是相容面。Final reviewed implementation 使用 nested `level_semantics`：

| 欄位 | 已知 v1 allowlist | 未知 strategy／version |
| --- | --- | --- |
| `version` | `signal-level-semantics/v1`。 | 同為 `signal-level-semantics/v1`，讓 consumer 能解析安全 fallback；不能把 strategy version 當 presentation version。 |
| `kind`／`reason` | `rule_reference`／`canonical_v1_allowlist`。 | `unknown`／`strategy_or_version_not_allowlisted`；不得僅看 evidence 自報 marker。 |
| `strategy.name/version` | 來自實際 `StrategyVersion` relation，且須與 allowlist 完整相符。 | 原值可供稽核；不能改標為 v1。 |
| `formula` | `version=legacy-risk-levels/v1`、`source=backend.worker.pipeline._risk_levels`，另帶現行 expression／rounding。 | `version/source=null`、`reason=strategy_or_version_not_allowlisted`。 |
| `fields` | 每個實際輸出欄位帶 `role`、`label_zh`、`source_field`；action rename 可追回 signal 欄位。 | `role=unknown`、`label_zh=價位（語意未確認）` 與相同 machine reason。 |
| `price_basis` | `{value:null, reason:legacy_price_basis_not_persisted}`。 | `{value:null, reason:strategy_or_version_not_allowlisted}`。 |
| `cost_included` | `{value:false, reason:legacy_level_formula_excludes_costs}`。 | `{value:null, reason:strategy_or_version_not_allowlisted}`。 |
| historical `decision_at` | `{value:null, reason:legacy_decision_at_not_persisted}`。 | value null 與 unknown identity reason；禁止由 `data_cutoff` 推導。 |
| historical signal `generated_at` | `{value:null, reason:legacy_generated_at_not_persisted_with_timezone}`。 | value null 與 unknown identity reason；禁止由 naive `created_at` 推導。 |
| `response_generated_at` | 含 offset 的 UTC response 組裝時間。 | 同角色；它不證明 historical signal 何時生成或決策。 |

reason 使用 machine-readable code。helper 對既有列只讀；API 只在 response 的 evidence copy 附上 semantics，不把推導結果寫回資料庫中的 `rule_evidence_json`、`StrategyVersion` 或 Signal。allowlist 同時比對 relation 的 name 與 version；evidence 內的 `strategy`／`strategy_version` 只能作稽核，不能凌駕 relation。缺 relation時也 fail-closed。

#### 6.1.2 v1 公式與欄位映射

`legacy-risk-levels/v1` 只描述目前程式的既有數值，並非新 trade plan：

- `risk=max(atr if truthy else entry×0.02, entry×0.01)`；`invalid=max(0.01, entry-risk)`；`target_1=entry+1.6×risk`；`target_2=entry+3×risk`；四個回傳值最後各 round 到小數二位。
- breakout 的 entry 是 `max(signal close, prior 20 highs 的最大值)` 後送入 `_risk_levels`；輸出 `breakout_price`。
- pullback 的 `reference_entry=round(close, 2)`；`support=ma20 if truthy else close`；`zone_width=max((atr if truthy else close×0.01)×0.5, close×0.005)`；`pullback_low=round(max(0.01, support-zone_width), 2)`、`pullback_high=round(support+zone_width, 2)`，再用 reference entry 產生 invalid／targets。
- 以上保留 Python 現行 truthy fallback 與 rounding 行為作 replay 基準；B4a 不「修正」零值、tick size、gap、成本或流動性。這些改動屬 B4b 新版本。

跨入口的欄位角色固定如下：

| signal source | action projection | `role` | `label_zh` |
| --- | --- | --- | --- |
| `breakout_price` | breakout `trigger_price` | `rule_trigger` | 規則觸發價 |
| `pullback_low/high` | `entry_low/high` | `rule_observation_zone` | 規則回踩觀察區下緣／上緣 |
| `reference_entry` | pullback `trigger_price` | `rule_calculation_reference` | 規則計算參考價 |
| `invalid_price` | `invalid_price`；未被使用者停損覆蓋時可能投影到 `stop_price` | `rule_invalidation_reference` | 規則失效參考價 |
| `target_1` | `target_1` | `rule_reference_target` | 規則參考目標一 |
| `target_2` | `target_2` | `rule_reference_target` | 規則參考目標二 |

`primary_levels`、compact action 與 UI 卡片不能因欄位 rename 把角色降回「觸發價／停損／目標價」的交易承諾。若 action 的 `stop_price` 來自 `PortfolioPosition.stop_price`，它必須另標 `user_position_risk_input` 並保留 origin；不能假裝是 `invalid_price`。若 top-level action 沒有唯一可證明的 selected strategy/version，整個 top-level `level_semantics` fail-closed，不能從策略名稱字串或第一筆 strategy 猜測。

#### 6.1.3 規則參考、持倉與成交的隔離

| 資料 | 正確語意 | 禁止混用 |
| --- | --- | --- |
| `breakout_price`、`pullback_low/high`、`reference_entry`、`invalid_price`、`target_1/2` | 固定規則的計算／觀察參考；不代表委託或成交。 | 不得稱「實際成本」「已成交」「保證停損」「AI 目標」。 |
| `PortfolioPosition.average_cost` | 使用者輸入的持倉平均成本／股；目前不含券商對帳 provenance。 | 不得拿來改寫 v1 reference entry 或推導 v1 公式。 |
| `PortfolioPosition.stop_price` | 使用者持倉風險輸入。 | 不得與規則 `invalid_price` 合併成無來源的單一 stop 語意。 |
| Signal/evaluation/settlement `execution_price` | 現行 tracking/execution policy 下記錄的填價；若沒有獨立 execution origin，不能宣稱券商真實成交。 | 不得倒灌成規則 entry，也不得稱使用者實際成交成本。 |
| execution evidence 的 slippage／round-trip cost | v1 執行與回測假設。 | 不得讓 `cost_included=false` 被讀成「系統沒有任何成本假設」，也不得說規則 target 已扣成本。 |

#### 6.1.4 B4a 入口與驗收矩陣（已 review）

| 入口／層 | 必須驗收 | 目前完成判定 |
| --- | --- | --- |
| `signal_dict(..., include_evidence=True/False)` | full 與 compact 都有相同 nested semantics；compact 不依賴被移除的 evidence 才能安全顯示。historical generated/decision 均 null+reason；response now 另列。 | backend/API assertions 通過；response evidence copy 附 semantics，DB 不回寫。 |
| `GET /signals`、`GET /signals/{id}`、stock detail 內 `signals` | 數值不變；known name+version 得 canonical v1；unknown strategy/version 與缺 relation fail-closed；legacy row/evidence 不變。 | API list／compact／detail／stock nested signal assertions 通過。 |
| `GET /tracking`、`GET /tracking/{signal_key}` | nested signal 契約與 signal list/detail 一致；evaluation／settlement 的 `execution_price` 不標為規則 entry 或券商真實成交。 | tracking API assertions 通過；前端 `/tracking` 是 redirect，未冒稱獨立 tracking 畫面瀏覽器驗收。 |
| DecisionSummary 的 `strategies[]` | 每筆 strategy result 帶自己的 relation name/version 與 semantics；只接受兩組完整 allowlist identity。 | known／unknown、spoofed evidence 與 field mapping assertions 通過。 |
| action/stock detail top-level levels、`primary_levels` | selected strategy 的 source-field mapping、role、label 一致；持倉 stop 的 origin 分開；無唯一來源就 unknown。 | rule fallback、`user_position_risk_input` 與 unknown stop assertions 通過。 |
| `GET /actions` compact 與 `GET /actions/{exchange}/{symbol}` detail | compact 保留完整安全 semantics；detail 與 stock detail 同 payload 規則。 | API assertions與外部 fixture 瀏覽器查驗通過。 |
| 前端 action list card、stock/action detail card | 實際呈現的價位使用規則觸發／回踩觀察／計算參考／失效參考標籤；nested fields 對 target 1／2 分別提供「規則參考目標一／二」，目前 card 實際呈現 target 1，不冒稱 target 2 畫面驗收；unknown 不信任 payload 自報 label。 | `presentation/routes/search/units` 四個 self-executing test 全通過，production build exit 0；外部 fixture 的 action list 與共用 stock detail 實驗通過。`/signals`、`/tracking` 是 redirect，不是獨立 UI 驗收。 |
| 非回歸 | v1 entry／invalid／1.6R／3R、status、risk reward、tracking result 不變；不得新增 migration、worker 改動、legacy backfill。 | 統籌 full backend 180 passed；保護的 worker/schema/DB 等九項 hash、size、mtime 均不變。 |

本矩陣只結清 B4a presentation semantics；不驗 tick-size、gap、cost sufficiency、liquidity、PIT availability 或新 trade-plan lifecycle，也不縮小 6.2、R0-C2／C3／C4／C5 的原驗收。

#### 6.1.5 C-005 final review 證據與限制

統籌使用 bundled Python 3.12.14、`PYTHONPATH=backend;backend/.deps` 與專案外真 Alembic 1.19.2 執行 `python -m pytest backend -q --disable-warnings`：**180 passed、4592 warnings、25.94 秒、exit 0**。程式 task 的 fallback 環境結果是 179 passed、1 skipped；它不是統籌 final full-suite 數字，不混同。統籌另以 1 與 5 個 instrument 查詢 fixture，各為 13 queries、0 筆單獨 `FROM strategy_versions`，確認批次 strategy metadata 修正沒有 N+1 回歸。

前端以 bundled Node 將 `presentation.test.ts`、`routes.test.ts`、`search.test.ts`、`units.test.ts` 編譯為 CommonJS 到專案外 Temp，再逐一執行，四檔皆 exit 0；`presentation.test.ts` final SHA-256 為 `945CFD9A…D31E0F1`。程式 task 的 final production `tsc + vite build` exit 0。

統籌只對專案外 fixture copy 做瀏覽器實驗，不是正式資料或真實市場驗證：action list 顯示使用者輸入平均成本 100／10 股；stock/action 共用 detail 將持倉 stop 101 與規則失效價來源分開；移除隔離副本持倉後，known breakout 仍為 entry 21.05、invalid 20.47、target 1 為 21.98；pullback fixture 顯示規則計算參考價 102、規則回踩觀察區 101～103、invalid 99、target 1 為 106.8；只把副本 StrategyVersion 改為 9.9.9 後，三組 numeric 與區間數值不變但 label 全部 fail-closed 為 unknown。signals/tracking 的獨立入口只有 API 測試，前端路由仍導向 action 頁。

final source SHA-256：`api.py=57DB381B…668EE6A`、`decision.py=C3EEC47C…0085201`、`level_semantics.py=057A0D6F…453FE76`、`App.tsx=53855F31…F46A0CA`、`presentation.ts=D7669D76…AF4BBA6`、`types.ts=73FEA3C9…393432E`；`presentation.test.ts=945CFD9A…D31E0F1`，三個 backend test 為 `test_api.py=A3340FB0…7CD180`、`test_product.py=E226F5F3…1CA57B`、`test_level_semantics.py=073CEED5…1B4B69D`。統籌 final 報告在專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r05-coordinator-ui/review.json`，SHA-256 `1689ED7B…CF74512`；九項保護報告 `protected-review.json` 的 SHA-256 為 `CB81F8B3…F9F92A`，`domain/models/db/migrations/pipeline/atr/artifact_store` 與 `data/stock.db`、`.local/data/stock.db` 的 hash／size／mtime 均不變。

這些證據只證明 read-time semantics 與對應 UI／API 非回歸。legacy price basis、historical `decision_at/generated_at` 仍為 unknown/null；沒有建立新 trade plan、改 execution、接 PIT truth、驗證 tick/gap/cost sufficiency/liquidity，亦未以 fixture 宣稱真市場結果或整個 R0 完成。

### 6.2 新交易計畫的隔離邊界

支撐壓力、跳空、不追價、價格級距、成本與流動性屬新的 trade-plan／execution version，不得悄悄改掉 legacy 1.6R／3R。新計畫至少保存：觸發／確認方式、進場區間、不追價上限、失效條件、參考目標、時間／事件失效、tick-size rounding、費稅／滑價、流動性 gate、最早執行與到期時間。

驗收至少包含：

- 所有 list/detail/action/tracking 畫面使用同一套規則參考價標籤，且不出現 AI／保證語意。
- tick size 前後及四捨五入後仍維持 `invalid < entry < target_1 < target_2`；不合法即拒絕輸出。
- T+1 跳空超過不追價上限時為 `rejected_gap`，不假設在參考價成交。
- 成本後空間不足、流動性不足、停牌或同日 stop／target 無順序資料時，分別拒絕或標 incomparable。
- legacy replay 的欄位與結果不變；新 trade plan 使用新 version 並能逐欄說明差異。

## 7. R0-4：時間欄位角色與 point-in-time gate

所有 timestamp 使用含 timezone 的 ISO 8601；台灣市場可顯示 Asia/Taipei，但持久化需有不歧義 offset／UTC。date 欄位不得假裝成 timestamp。

| 欄位 | 唯一角色 | 不可替代 |
| --- | --- | --- |
| `market_date`／legacy `signal_date` | 行情或訊號所描述的交易日 T。 | 不代表資料何時發布、取得或決策。 |
| `event_at`／`event_date` | 事件發生時間／日期。 | 不代表來源發布或系統取得。 |
| `published_at` | 來源聲明的發布時間。 | 來源未提供時不可由內容日期猜測。 |
| `first_available_at` | 有證據支持該來源版本第一次可取得的時間。 | 不得用 event date 或回補時間反推。 |
| `collected_at` | 本系統實際取得該版本的時間。 | 不代表歷史上其他使用者可取得。 |
| `revision_available_at` | 修訂版本開始可得的時間；連到 `supersedes`。 | 不可原地覆寫首次版本。 |
| `decision_at` | 規則／模型鎖定輸入並作出判斷的時間。 | 不等於 market close 或 artifact 建立時間。 |
| `generated_at` | 訊號、摘要、計畫或報告實際生成時間。 | 不得用來提前 decision time。 |
| `earliest_execution_at` | 在資料已可得、決策完成且市場可交易後的最早時點。 | legacy date 只能作日期相容顯示。 |
| legacy `data_cutoff` | 舊版字串稽核欄位。 | 不再宣稱它證明所有輸入在 T 日 13:30 可得。 |

### 7.1 Round07 C007／B5a final review（有限本地 foundation）

本批新增 `backend/app/time_evidence.py` 的 `time-evidence/v1` 純契約，以及 `backend/app/time_evidence_store.py` 的明確 opt-in 專用 schema 1 SQLite store。caller 明確提供 `subject_identity`、`source_identity`、`snapshot_identity`、`revision_identity` 與各時間角色；`source_identity` 是 caller 選定的穩定 lineage key，各 role 的 `source` 則是該項證據提供者，兩者可以不同。store 只驗 caller-provided 結構、正規化、不可變、relation 與 canonical digest，不查證來源是否官方、內容是否真實，也不證明兩層來源的同源關係；後者仍屬 B3-wire／G-SOURCE。

strict input 要求 `published_at`、`first_available_at`、`collected_at`、`revision_available_at`、`decision_at`、`generated_at`、`earliest_execution_at` 七個角色全數明示，另至少提供 `market_date`、`event_date`、`instant`、`event_at` 其中一個 anchor。每個角色都由 caller 明確提供，不從另一角色自動推論；角色物件必須含不矛盾的 `status`、`precision`、`value`、`source`、`evidence`、`ref`，unknown／unavailable 另須 machine reason。known datetime 只接受含 offset 的 ISO 8601 並 canonicalize 為 UTC `+00:00`；known date 只保存 `YYYY-MM-DD` 與 `precision=date`；unknown／unavailable 不帶值且為 `precision=none`。naive datetime、known＋none、known 無值、unknown 帶值、date-only 補午夜、缺 provenance 或矛盾 alias，均在寫入前 fail-closed。

每個 version＋subject＋source lineage 只允許一個 root；root 不指向 predecessor，且只有 root 的 `revision_available_at` 可為 not-applicable＋reason。更正以新 revision append，精確 `supersedes` 同 lineage 的既存 revision；真正修訂的 `revision_available_at` 可為 known date／datetime，或 unknown／unavailable＋reason，但不可標 not-applicable。舊 canonical revision 不 update／delete；跨 lineage、不存在／自身 predecessor、第二個 root、相同 stable identity 不同 snapshot／payload 都拒絕並整筆 rollback。相同 identity 與相同 canonical payload 可冪等回傳；完整 ancestor 在 read 時逐列核對存在、lineage 與 seal。availability 未知／不可用的修訂可以保存，但不能因此宣稱可供任何歷史 decision 使用。

`TimeEvidence.from_mapping(...)` 建立 contract；`to_dict()` 輸出 version、四類 identity、revision／supersedes、直接 role objects、`caller_provided_only=true` 與 `availability_truth=not_asserted`。`legacy_safe(...)` 及 aliases 深拷貝舊值，naive datetime 原樣轉成不加 offset 的 ISO text，只把合法 `signal_date` 投影成 date；`data_cutoff`、`created_at`、`earliest_execution_date` 不提升成 published／availability／decision／generated instant。現行 News 的 date-only midnight `display_time` 也只屬舊排序／展示相容值，不是新時間證據。

`TimeEvidenceStore(explicit_path)` 無預設 DB，會拒絕正式 `data/stock.db`、專案 `.local`、既有空 DB 與 foreign DB。`append(...)` 回傳 `created` 或 `idempotent_replay`；stable key 為 version＋subject＋source＋revision id。`read(evidence_key)`／`read_exact`、`read_revision(subject, source, revision_id, ...)` 與 `history(subject, source, ...)` 都使用明確 selector，history 只按 stable append order 回傳指定 lineage，沒有 implicit latest／`<= as_of`。`export_json(...)` 輸出完整 history／digests，拒絕既存、active store 或受保護 target，並以同目錄 temporary file＋hard link 實作 atomic no-clobber。

本批 final 驗收矩陣如下；通過只代表合成 caller evidence 的本地介面與失敗行為：

| 案例 | 必須證明 |
| --- | --- |
| aware offset／UTC | 同一 instant canonical UTC 相同且 exact round-trip；DST／offset 不改變時序。 |
| naive／矛盾 state | 寫入前拒絕，SQLite 沒有 header 或 role 部分列。 |
| date-only／unknown | date-only JSON 無午夜 instant；unknown／not-applicable 為 null＋machine reason。 |
| revision append | rev1、rev2 exact 可查，rev2 supersedes rev1，rev1 bytes／digest 不變。 |
| identity／supersedes 錯誤 | cross-root、missing predecessor 或同 identity 不同 payload 整筆 rollback。 |
| retry | 同 identity＋同 canonical payload 冪等，不改首次資料。 |
| provenance | 缺必要 caller evidence 拒絕；結構完整也只標 caller-provided，不升格 source truth。 |
| legacy projection | 保留原值與 limitation，所有無證據的 decision／availability role 維持 unknown。 |
| isolation／selector | caller 明示專案外測試 SQLite；exact selector 零筆拒絕，無 latest fallback；正式與 `.local` DB 不變。 |
| 完成邊界 | targeted／完整 backend 與四個新檔 hash 各自留證；未接 News/API/worker/UI、未執行 B5b/PIT 或官方 truth。 |

統籌 final 使用 bundled Python 3.12.14，並在 `PYTHONPATH` prepend Round03 外部真 Alembic 依賴，執行 `python -m pytest backend -q --disable-warnings`：215 passed、4592 warnings、24.03 秒、exit 0。作者 final targeted 是 15 passed、0.32 秒；作者 214 passed 與統籌較早 14-pass targeted 都是修正前歷史結果，不作 final 證據。統籌另在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r07-final-review-80ea2c0ab3bd4f9ea7f4eab4187a76aa/review.json` 完成 22 項獨立檢查，全數通過；涵蓋 UTC/date-only/unknown、provenance／alias／precision、single root、unknown revision availability、collision／rollback、commit 前重驗、SQL row-id replace、missing grandparent 拒絕、JSON hard-link atomic no-clobber 與 ownership。完整 ancestor 逐列 seal 重驗則由 final source 唯讀核對確認，未把所有 ancestor 損壞型態冒稱為注入測試。

final source SHA-256：`time_evidence.py`=`799D9B9BD51C284321059AC908AB1079A2E0D12E875861E0FA9CA4B54E4245E7`、`time_evidence_store.py`=`A454FA7A354DDE4E65A6F17D85188414A9930A6B3D4E1846E72FC6A547E92FC4`、`test_time_evidence.py`=`5CFD4AD8160B207ACDD850BCA3BB37087F594F7A0B03BAF90BFDA6775D4E4067`、`test_time_evidence_store.py`=`9FFF228814CAE8708D33B00C51369C6E68B3812D14D93FB49CF53DA51DE717EE`。同目錄 `protected-review.json` 證明 15 個保護目標的 hash／size／mtime 全不變，包括正式與 `.local` DB、既有 News/model/store/API/worker/frontend；本輪沒有前端變更，也未重跑 frontend build／UI。

因此，就 Round07 當時狀態，C007 只按 **B5a 本地核心／儲存 foundation** 通過 review。它沒有修改 `NewsItem`、API、worker、UI、legacy `Base`、migration 或正式 DB，也不執行下列 point-in-time gate。當時 B5a 的產品 API／UI 時間輸出與 legacy 相容接線、B5b／PIT、官方 availability truth、B2、B3-wire、B7 與 R0 整體均未完成；產品 read-time 缺口其後由 C008 補足，但其他缺口不受影響。

### 7.2 Round08 C008／B5a 產品 read-time projection（有限 review）

本批新增 `backend/app/product_time.py` 的 `product-time/v1` 純 read-time projection，並接到既有 News、signal、action、stock detail 與 tracking response；它與 C007 的 strict `time-evidence/v1`／專用 store 分離，不讀 store、不寫資料，也不從 `Event.details`、`rule_evidence` 或其他任意 JSON marker 猜時間。頂層固定包含 `version`、`scope`、`availability_truth=not_asserted`、`timezone_policy`、`roles`、`response_generated_at`、`legacy`、`limitations`。每個 role 有 `role`、`status`、`precision`、`value`、`utc`、`date`、`source`、`evidence`、`ref`、`reason`、`timezone_policy`；本輪產品 projection 的已知精度只有 `date` 或 `instant`，缺值、naive、不可信 basis／precision 與衝突都保持 `unknown`／`precision=none` 加 machine reason。

`roles` 明示 `market_date`、`event_date`、`event_at`、`published_at`、`first_available_at`、`collected_at`、`revision_available_at`、`decision_at`、`generated_at`、`earliest_execution_at`，並另加 legacy 相容用的 `earliest_execution_date`。含 offset 的已知 instant 只按來源／caller 已提供的 offset 正規化為 UTC，再以 Asia/Taipei 顯示；這不證明來源 truth。合法 date-only 只保存日曆日期，不轉換時區或補午夜。legacy `signal_date`／`data_cutoff`／`earliest_execution_date`／naive `created_at` 保留原值，但不能升格成 availability、decision、historical generation 或 execution instant；`earliest_execution_at` 因此仍 unknown，而 `earliest_execution_date` 可明示為規則日期。API 組裝時刻只放 `response_generated_at`；action 舊有 `generated_at` 另標 `legacy_response_assembly_time`，不冒充 persisted historical `generated_at`。

News 投影只在 `time_consistency` 非 conflict、`time_basis` 屬已知 allowlist 且 `time_precision` 為 `date`／`datetime` 時，才將對應 published／event／collected role 視為可表示的來源欄位；`unverified`、`none`、非法值或衝突均 fail-closed。即使儲存值字面為 aware midnight，precision=date 仍只顯示發布／事件日期。`collected_at` 可作獨立系統收錄 timestamp，但不代表 `first_available_at`；ingestion run `finished_at` 只保留在 action legacy 區，不升格成資料 `collected_at`。News 不適用規則執行日，action 若關聯多個事件則 event date 不選第一筆而保持 unknown。

入口與相容矩陣：

| 入口 | 新時間輸出 | 保持不變／失敗邊界 |
| --- | --- | --- |
| `/api/news`、`/api/news/{id}`、dashboard／stock detail nested news | 每筆 `product_time` 與 `response_generated_at`；compact／detail 共用相同角色語意。 | 原 `published_at`、`event_at`、`event_date`、`display_time`、`time_basis`、`time_precision`、`time_consistency`、sort／keyset／filters 保留；衝突與 unverified 不靠 legacy 日期 fallback 成已知時間。 |
| `/api/signals`、dashboard／stock detail nested signals | signal `market_date` 與規則 `earliest_execution_date` 可為 date；歷史 decision／generated 與 execution instant 未證實。 | `signal_date`、`data_cutoff`、`earliest_execution_date`、策略和值不改；不信任 `rule_evidence` 自報時間。 |
| `/api/actions`、`/api/actions/{exchange}/{symbol}`、dashboard actions | action／decision summary／各 strategy 投影 `product_time`；同一 `DecisionSummary` 及其 strategy 共用 request-generated time，同一 HTTP 批次的不同物件不保證相同組裝時刻。 | action state、legacy cutoff、價位／策略／狀態不改；run finished 不當 collected，非唯一 event fail-closed。 |
| `/api/stocks`、`/api/stocks/{exchange}/{symbol}`、`/api/tracking` | directory／stock、nested decision／strategy／signals，以及非空 tracking row 的 signal 都帶相同 signal projection；本次組裝時間可不同 response。 | 不新增查詢；同一 signal 的角色資料跨入口一致，tracking 成交／結果語意不改。 |
| `/news`、`/news/:id`、action list/detail、stock detail | 關鍵資料／事件日期、發布、決策與規則最早執行日使用固定 Asia/Taipei 或純日曆格式；unknown／conflict 顯示待核實。 | 沒有 product contract 時只允許合法 date fallback；已有 contract 但 role unknown 時不得退回舊日期。News 不顯示不適用的規則執行日。 |

統籌 final backend 使用 bundled Python 3.12.14 與外部真 Alembic 1.19.2，完整 `pytest backend` 為 221 passed、4603 warnings、24.55 秒、exit 0；先前 23.60 秒是 `compact_news_dict` 補漏前的歷史結果，不作 final 證據。獨立 `C:/Users/YiCheng/AppData/Local/Temp/stock-r08-coordinator-ui/independent-time-review.json` 的 16 個時間案例全過；`api-comparison.json` 比較 18 個 response，排除本次動態組裝的 `generated_at` 與 `response_generated_at` 後，legacy 欄位、排序與 keyset 無差異。`baseline-query-counts.json`／`current-query-counts.json` 的 17 個入口 query count 全相同，包含 dashboard compact news、stock directory、signal detail 與 tracking detail；統籌 fixture 的 tracking detail 有 signal、evaluation 列表為空，非空 tracking rows 則由作者新增 integration test 與 final 221-pass suite 覆蓋。`projection-consistency-review.json` 的三個 signal、五個 news subject group 在 full／compact／nested 入口也有相同 projection，僅排除 request-generated time。15 個保護目標的 hash／size／mtime 全不變，包含 C007 兩檔、既有 model/news/schema/worker 與正式、`.local` DB。

統籌編譯並執行四個 frontend self-test 全過；`presentation.test.ts` 另在 `TZ=UTC` 與 `TZ=America/Los_Angeles` 各通過，`tsc -b` 與 Vite production build 82 modules／1.08 秒皆 exit 0。隔離 CUA fixture 只驗證可見文字與值：aware UTC 新聞在台灣顯示 00:20、naive 顯示待核實、date-only 顯示「發布日期」且無午夜、conflict 詳情的 event／published 均待核實；action／stock 顯示資料日、決策待核實，以及規則最早執行日由 unknown 到 fixture 的 2026/09/09，legacy 102／101–103／99／106.8 價位仍在。這不是像素 layout 或收合 technical details 的瀏覽器驗收；收錄時間安全另由來源讀碼與純 formatter test 支持。CUA backend 啟動早於 final compact-news 欄位補漏，該 final 差異由 18-response API comparison 另行覆蓋，不能倒推成瀏覽器已觀察該欄位。

final changed-source SHA-256：`product_time.py=B47D6B6D…A02F5D`、`api.py=A361AC98…9613C4`、`decision.py=BC50F327…5D389D7`、`test_product_time.py=A0EA534C…368B14`、`test_product.py=6E0464D1…072EAA`、`App.tsx=4FFDA068…A5BC8`、`presentation.ts=E9A0539A…B25CA8`、`types.ts=78B753ED…EA964`、`presentation.test.ts=358A6603…E0AB2D`。同一 `final-source-hashes.json` 另列未改的 `test_api.py=A3340FB0…7CD180`，不能算成第十個 changed file。

因此 C008 只按 **B5a 產品 read-time projection** 的相容範圍通過 review。它沒有把 C007 strict evidence/store 接到產品或 worker，沒有保存新時間、修改 schema／migration／source／worker／正式 DB，也沒有執行 B5b as-of/PIT gate、核實官方 availability truth，或完成 B2、B3-wire、B7、B4b 與整個 R0。下列原 point-in-time gate 與驗收全部保留。

point-in-time gate：每一個必要輸入版本的 evidence 必須有 `available_at <= decision_at`；live run 還須 `collected_at <= decision_at`。修訂資料只有在 `revision_available_at <= decision_at` 時可用。來源可得時間未知時，歷史 replay 預設排除或套用事先版本化的保守延遲規則，不能只因 market_date <= T 就納入。

`earliest_execution_at` 必須不早於 `decision_at` 與所有必要輸入可得時間，並落在策略允許的下一可交易時段。盤後法人資料只能在實際可得後形成隔日計畫；`T_close` 只能描述市場觀察點，不能冒充牆上時鐘或 availability 證據。

驗收至少包含：

- T 日收盤資料在 13:30 後才 collected，decision 只能在 collected 後；最早執行仍是下一合法時段。
- 法人資料晚於 close 公布，13:30 replay 不得使用；盤後 decision 可使用並帶來源 availability evidence。
- T+2 修訂不改變 T+1 舊決策；T+2 as-of run 可選擇修訂版且保留 supersedes 關係。
- 回補資料只有 collected_at、無可信 first_available_at 時，不得被回填成歷史當時已知。
- DST／offset 不影響排序；null 精度與 date-only 來源不被補成午夜精確時間。
- API 同時維持 legacy `signal_date`／`data_cutoff` 相容與新欄位；前端不再顯示「收盤當下已知」的暗示。

## 8. R0-5：migration head 與實際 DB revision

R0-5 分開三個事實，不得互相推論：

1. **程式 head**：Alembic revisions 目前靜態可見到 `0006_news_json_defaults`，前置為 `0005_news_temporal_contract`。
2. **文件 head**：OPERATIONS／DATA_SOURCES 應與程式單一 head 一致。
3. **實際 DB revision／管理路徑**：只能對指定 DB 唯讀查 `alembic_version` 與 fallback markers 後判定。C-003 在其 2026-09-12 驗收時確認正式 `data/stock.db` 沒有 `alembic_version`，因此當時不能稱有 Alembic current；五筆 `schema_migrations` 只表示 fallback 已套用對應 marker。這是歷史時點證據，R26 current 狀態另見 §8.5。

B6 執行順序：

1. 記錄程式 revision graph 與 `alembic heads` 輸出，確認單一 head。
2. 建立正式 DB 的具名備份或測試 fixture 副本；解析並記錄其絕對路徑，確認不是正式 `data/stock.db`。
3. 對隔離副本記錄 `current`、schema／row-count 基線與檔案雜湊。
4. 只對隔離副本執行 upgrade；再記錄 `current`、必要 schema、既有 row preservation、API 啟動與 downgrade/restore 策略。
5. 若正式 DB 只做 read-only current 檢查，另列結果；不得因隔離 upgrade 成功就寫「正式 DB 已遷移」。

驗收證據必須含資料庫絕對路徑、執行前後 revision、命令 exit code、日期、程式／設定版本、schema 差異、資料保留檢查及失敗／warning。任何一項未執行就明列「未執行」，不能寫通過。

### 8.1 B6 review 驗收矩陣

| 項目 | 必要證據 | 通過條件 |
| --- | --- | --- |
| 程式 revision graph | `alembic heads`、`history` 或等價程式檢查的完整輸出、runtime／套件版本與 exit code。 | 唯一 head 與 revision chain 可重現；這只證明程式 head。 |
| 正式 DB 定位與唯讀 | runtime 實際解析的絕對路徑、SQLite URI `mode=ro`／`PRAGMA query_only` 證據、檢查前後 size／mtime／SHA-256。 | 路徑確為目標正式 DB，且檢查沒有改檔。不得靠預設路徑猜測。 |
| 實際 revision 判讀 | 唯讀列出 `alembic_version` 是否存在及內容；若只有 fallback `schema_migrations`，另列 marker。 | `schema_migrations` 只能證明 fallback marker，不等於 Alembic `current` 或 0005。沒有 `alembic_version` 時寫「沒有 Alembic revision／current；fallback markers 為……」，不可再泛稱未知，也不可由五筆 marker 推論正式 DB 已由 Alembic 升到 head。 |
| consistent backup | 使用 SQLite backup API 或等價一致性機制建立專案外具名 Temp DB，記錄來源／目的絕對路徑、時間、大小、hash 與 exit code；不能只在可能有 WAL 時裸複製主檔。 | 目的地不在 workspace／正式資料路徑；來源唯讀；backup 後 `quick_check`／`integrity_check` 與 `foreign_key_check` 通過。 |
| 副本 upgrade | 副本 before current／schema／row counts／既有欄位 deterministic fingerprints；upgrade 命令、依賴版本、exit code；after current／schema diff。 | 只改副本且到單一程式 head；schema diff 僅含預期 migration；warning／fallback 路徑明列。 |
| row preservation | 對 upgrade 前已存在的每個業務表比較 row count，並在共同欄位上做穩定排序的內容 fingerprint；新表另列預期初始列數。 | 無未預期刪列、改值、duplicate key 或 orphan；只報總列數不夠，無法 fingerprint 的欄位須說明替代檢查。 |
| fresh DB | 專案外另一個空 DB 從 base／init 升到 head，記錄命令、current、tables／indexes／constraints 與完整性檢查。 | fresh 與 upgraded-copy 的 head、必要 schema 契約一致；這不證明舊資料保存，故不能取代上一列。 |
| API／restore | 指向隔離 DB 的 API startup／最低 read smoke；另記 forward-only migration 的 restore 方法或實際 downgrade 結果。 | 不連正式 DB；startup 無 migration error。forward-only 時不得宣稱 downgrade 通過，應以丟棄副本／還原 consistent backup 作 recovery。 |
| 最終不變性 | 再取正式 DB size／mtime／SHA-256，以及所有 Temp／設定的實際路徑。 | 正式 DB 無非預期變更；任何差異都先停止，不標 B6 通過。 |

### 8.2 C-003 final review 證據與限制

統籌於 2026-09-12 接受 C-003/B6。程式 task 只修改 `backend/tests/test_schema.py`，SHA-256 為 `32BA427EA86E5E6905785CEF01848DE0E8B364214F48C5C19F1BDD3D27BE08B9`；production migrations 未改。測試明確分成真 Alembic 與強制 fallback：真 Alembic 要求唯一 `alembic_version=0005_news_temporal_contract` 且沒有 `schema_migrations`；fallback 以不存在的外部 Alembic config 強制走相容路徑，要求精確五筆 marker 且沒有 `alembic_version`。

程式 task 使用專案外 Alembic 1.19.2：schema＋API targeted 12 passed、55 warnings、4.09 秒、exit 0；fallback targeted 11 passed、1 skipped、44 warnings、3.62 秒、exit 0；完整 backend 157 passed、4486 warnings、24.34 秒、exit 0。統籌獨立重跑 Alembic schema＋API 為 12 passed、55 warnings、4.01 秒、exit 0；原 bundled、無 Alembic 環境的 schema-only 為 3 passed、1 skipped、1.19 秒、exit 0。這個 skip 是環境缺 Alembic 而明示未走真 Alembic 案例，不可算成該環境已驗真升級。

統籌另建立全新的專案外 Temp 驗證，JSON 為 `C:/Users/YiCheng/AppData/Local/Temp/stock-r03-coordinator-1gcowt5o/coordinator-review.json`，產生時間 `2026-09-11T17:13:34.754349Z`（Asia/Taipei 2026-09-12）。runtime 解析正式 DB 為 `C:/Users/YiCheng/Desktop/taiwan-stock-research/data/stock.db`；SQLite `mode=ro`＋`query_only` 查驗前後 SHA-256 均為 `74A34389DBFA65429D27EA41BC9DECA2A132808F10093E2FFDE98665D96232D6`，mtime／size 亦未變。正式庫沒有 `alembic_version`，只有五筆 fallback markers；這是已確認的管理路徑狀態，不是正式庫已由 Alembic 升到 0005。

SQLite backup API 建立的 `copy.db` 與獨立 `fresh.db` 都真正 upgrade 到單一 head `0005_news_temporal_contract`，integrity check 正常、foreign key violation 為 0。副本 upgrade 前後的 20 個既有表（含 fallback marker 表）、共同欄位集合、622,399 筆 row count 與完整內容 fingerprint 全部相同，唯一新增 schema object 為 `alembic_version`。程式 task 的外部報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r03-c003-report-20260911-171200/r03-c003-verification.json`（SHA-256 `677286E560E14AE88F96414D4B2068DA768D9F91A981C6A37C6C8444F2E9F4A8`）另含隔離 API startup 與 `/api/health` 200、copy／fresh schema、row 與 hash 證據。

限制：bundled `backend/.deps` 當時缺 requirements 已宣告的 Alembic，真 Alembic 驗證使用專案外 Temp 安裝；forward-only migrations 的 downgrade／restore 未實際執行，只記錄以丟棄隔離副本、從 consistent backup 還原的 recovery 方法。`0001_schema_v1.upgrade` 由當前 `Base.metadata.sorted_tables` 動態建表，不是凍結的歷史 schema；因此 future B2/B3 新 model 加入後，fresh DB 在 0001 可能提前出現新表。下一批 migration 驗收必須同時測真正 pre-head 副本 upgrade 與 fresh DB，不能只靠 fresh DB 宣稱後續 revision 正確。

### 8.3 Round10 C010 migration／restore regression assets（有限 review；R0-A2 未結清）

Round10 新增 `backend/tests/test_migration_recovery.py` 與 `backend/tests/fixtures/migrations/synthetic_prehead_0004_news_slice.{sql,json}`；production migrations、models、app、正式 `data/stock.db` 與 `.local` DB 都沒有修改。fixture 是固定、最小的六表 synthetic 0004 pre-head slice，不含正式資料或秘密，也不是完整 historical／production schema。測試在 upgrade 前要求 `alembic_version=0004_product_news_themes`，並確認 `news_items` 真正缺少 0005 的五個 target columns；之後以真 Alembic 升到唯一 head `0005_news_temporal_contract`，分開驗 common-column 全列 fingerprint 與新欄結果：`event_date`／`display_time` 為 null，`time_basis=unverified`、`time_precision=none`、`time_consistency=verified`。

已有限 review 的自動回歸另涵蓋必要 PK／FK／unique／0005 indexes、row counts、`integrity_check`／`foreign_key_check`、第二次真 Alembic `upgrade head` 後完整 schema＋rows fingerprint 不漂移，以及實際 recovery path：SQLite backup API 建立 consistent backup、另建並改壞隔離副本、偵測同筆數內容竄改與刪列，再從 backup 還原至全新 Temp 路徑並核對六表的完整 schema、所有 rows、revision、constraints、FK／integrity；不是以 downgrade、原檔複製或只測 helper 冒充 restore。這證明的是 synthetic SQLite recovery mechanics；Round03 §8.2 對正式庫副本 20 表／622,399 rows 的歷史 preservation 證據不變，當時「restore 未實跑」的紀錄也不被回寫。在 Round10 驗收時正式庫仍未升級，亦沒有正式 restore／deployment drill；其後外部變化見 §8.5。

同一 regression 明確揭露而非 normalize 掉 fresh parity 缺口：`0004_product_news_themes` 建立的 `news_items.symbols_json`／`theme_ids_json` 有 SQL server default `[]`，但 current `NewsItem` 只有 Python `default=list`；因此由動態 `0001`／current `Base.metadata` 建出的 fresh head，兩欄 server default 都是 null。raw SQL 省略兩欄或只省略 `theme_ids_json` 時，fresh head 會觸發 NOT NULL error，實際 0004→0005 路徑則成功並得到兩個 `[]`。所以 schema parity 為 false、known gap 恰為這兩個 JSON defaults；R0-A2 整體維持未完成，下一輪須另行界定 production 修正與回歸，不能縮小 parity 條件後宣稱通過。

統籌 final 使用 bundled Python 3.12.14、外部 Temp Alembic 1.19.2 與 SQLAlchemy 2.0.52；`python -m pytest backend -q --disable-warnings` 為 241 passed、4613 warnings、31.69 秒、exit 0。程式作者 final targeted 為 4 passed、10 warnings、1.49 秒、exit 0；文件角色以相同類型環境獨立重跑 `python -m pytest backend/tests/test_migration_recovery.py -q --disable-warnings`，為 4 passed、10 warnings、1.35 秒、exit 0。若只給 bundled Python＋`backend/.deps`＋`backend` 而沒有真 Alembic，會因專案 `backend/alembic` namespace 無 `command` 在 collection exit 1，不能把該環境算成已驗升級。統籌另以不依賴 C010 helper 的 SQL／SQLite 檢查完成 22／22，證據集中在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r10-coordinator-review/`：`backend-final.txt`、`recovery-review.json`、`default-drift.json`、`protected-review.json`、`final-source-hashes.json`。34 個 protected targets 的 hash／size／mtime 為 0 mismatch；本輪沒有 frontend 變更或驗收。

final SHA-256：`test_migration_recovery.py`=`CFD344807B0E9644E4C14E904342FD1CE36BC9781BD3254236D4F33C92C2175C`、fixture SQL=`BC5198C14BA2547D30529D3D335E79DE363022159B48D6C9442CFD643E3C42C1`、fixture manifest=`09DD1075D0EA1DB1B474639D6ECECDA5E710057EE439ADABE83C197EE64BC019`。

以上是 Round10 當時的差異與驗收結論；該兩欄缺口後續由 Round11 C011 處理，結果如下，不回寫 C010 的歷史證據。

### 8.4 Round11 C011：JSON server-default parity 與 atomic migration 回歸（有限 review）

Round10 已把差異限縮為 `news_items.symbols_json`／`theme_ids_json` 兩個資料庫端預設值：歷史 `0004_product_news_themes` 建表路徑是 SQL `[]`，但當時 current `NewsItem` 只有 Python `default=list`，使 dynamic `0001`／current metadata 的 fresh 路徑沒有 server default。Round11 以新的 `0006_news_json_defaults` 與對等 fallback 修正這項 production 契約；`0001`–`0005` 與 Round10 固定 fixture 必須維持原樣，不能回寫歷史 revision 或修改舊 fixture 來製造通過。

驗收矩陣如下；所有資料庫都是專案外 Temp SQLite，結果須分開列真 Alembic 1.19.2 與強制 fallback，不能以其中一路代替另一路：

| 案例 | 起始狀態 | 必要斷言 |
| --- | --- | --- |
| fresh | 空 DB；dynamic `0001`／current metadata 或 fallback fresh create。 | 到新 head；兩個 JSON 欄位的 SQL server default 都等價於空陣列；raw SQL 同時省略兩欄、以及只省略 `theme_ids_json` 都成功且讀回 `[]`／`[]`。 |
| old-fresh-005 | 固定、獨立於修後 current metadata 的 0005 schema。 | 真正從 0005 升到 0006；升級前 defaults 缺漏、升級後補齊，不能只改 revision marker。 |
| explicit 0004 | Round10 固定 0004 slice，升級前沒有五個 0005 temporal 欄。 | 真正執行 0005 再 0006；既有 temporal defaults、兩個 JSON defaults 與必要 indexes 同時成立；Round10 fixture bytes 不變。 |
| 資料保留 | 至少含非空 `symbols_json`／`theme_ids_json`、Event／raw payload 及實際 `supersedes_id` self-FK 關聯。 | 所有既有共同欄位與 rows 的 deterministic fingerprint 不變；非空 JSON 不被重設；row counts、PK、三組 FK、canonical unique 及必要／既有 indexes 保留，並以非法 INSERT 實際證明 PK／FK／unique 仍拒絕。 |
| 自訂 schema | 代表性的自訂 index，並依 fixture 實際存在情況涵蓋 trigger、view 與 sequence。 | 可安全保存者須保留 SQL／行為；若遇無法安全重建的 shape，必須在任何 mutation 前明確拒絕，且拒絕前後 schema／rows／revision 或 markers 完全相同。不得靜默遺失後才要求人工 repair。 |
| 故障注入 | 在會暴露部分重建的中段注入失敗；fresh、0005 與 0004 起點分別覆蓋適用路徑。 | 失敗後 schema、全部 rows、Alembic revision 或 fallback markers 與起始 fingerprint 相同；fresh 不留半套 DDL；`PRAGMA foreign_keys` 恢復且 `foreign_key_check` 為空。移除故障後同一 DB retry 成功。 |
| 冪等 | 已成功到 0006 的 DB 再執行相同 upgrade。 | schema、research rows 與 version set 不漂移，raw omission 行為仍相同；fallback 的既有 `INSERT OR REPLACE schema_migrations` 可更新 operational `applied_at`，不得把該時間戳冒充完全不變。 |

SQLite 風險界線：SQLite 不能用一般 `ALTER COLUMN` 就地補既有欄位 default，若採 table rebuild，不能只複製 columns／rows，還要處理 PK、FK、unique、named／custom indexes，以及存在時的 trigger、view、sequence。`PRAGMA foreign_keys` 在 active transaction 內切換不可靠；切換必須發生在 transaction 外並於成功或失敗後恢復。C011 的 Alembic env 對 SQLite 明確建立 driver transaction，外部 `Connection` 已在 active transaction 時則在任何 mutation 前拒絕；helper 單獨呼叫時仍由呼叫端負責 transaction。任何「atomic／rollback」主張都以實際注入失敗、前後完整 fingerprint 與 retry 證據成立，不能只由 transaction API 名稱推論。

統籌於 2026-09-12 接受 C011 的有限範圍：`NewsItem.symbols_json`／`theme_ids_json` 現有 ORM metadata 具有 SQL `[]` server default；`0006_news_json_defaults` 及 fallback 第六枚 marker 會在同一成功邊界補齊舊 schema。fresh、固定 old-005、explicit 0004→0005→0006、Alembic／fallback、FK 0／1與成功後重跑冪等均有成功路徑回歸；failure rollback 的主矩陣針對 fresh／old005，不把 explicit 0004 說成也完成全部故障交叉組合。失敗回滾要求 marker 全列與其餘 schema／rows 相同；成功後冪等則比較 schema、research rows 與 version set，明確排除 fallback `INSERT OR REPLACE` 可更新的 operational `applied_at`。支援的額外 index、owned trigger、字串 default literal 與實際 `supersedes_id` self-FK 會保留；inbound FK、view、external trigger、AUTOINCREMENT、generated column、未知非空 default 等無法安全重建的形狀會在 mutation 前 fail-closed。只有 SQLite 已測；非 SQLite 不在本次結論內。

統籌完整 backend 為 259 passed、4625 warnings、14.12 秒、exit 0；另以不依賴 test helper 的檢查通過 73／73，其中包含真正的 Round10 old-fresh-005 Temp DB copy。主 atomic 矩陣為 24／24，明列三個入口——Alembic engine、Alembic external `Connection`、fallback——並在 fresh／old005、FK 0／1、Alembic 或 fallback 各自 marker SQL 前／後故障時驗完整 schema、rows、revision／markers 回滾與 retry。Round10 原測試現在固定驗 005／current-metadata comparison，不再冒充 old-fresh-005；C011 自動測試的 fixed inline DDL 是小型 old005-like slice，真正 old full 005 copy 由統籌的獨立 73／73 檢查補證。程式作者完整 backend 為 259 passed、4625 warnings、13.44 秒，targeted 為 26 passed、26 warnings、2.39 秒；文件角色獨立重跑同一 targeted 三檔為 26 passed、26 warnings、2.54 秒、exit 0。32 個 protected targets 的 hash／size／mtime 無差異。統籌 final code hashes 保存於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r11-coordinator-review/final-source-hashes.json`。

本批因此只結清 R0-A2 中明列的 News JSON defaults parity 與 atomic migration regression 資產，不宣稱所有 historical schema 都已完整 parity。程式 head 現為 `0006_news_json_defaults`，fallback 具備第六枚 marker；在 Round11 驗收時，正式 `data/stock.db` 仍是沒有 `alembic_version`、只有五筆既有 fallback markers 的歷史實況，C011 沒有執行 0006、正式 restore 或 deployment drill。R0 其餘批次與整體 ROADMAP 仍未完成；後續外部 preview startup 變化另見 §8.5，不回寫本批歷史。

### 8.5 2026-09-13 外部 preview startup 後的正式 DB 現況（非 R26 migration 驗收）

R26 round baseline 的正式 `data/stock.db` 為 296,054,784 bytes、SHA-256 `74a34389dbfa65429d27ea41bc9deca2a132808f10093e2ffde98665d96232d6`；輪初沿用的已知歷史管理狀態是沒有 `alembic_version`、存在 fallback markers，不能寫成原先 Alembic current 為 0001。另一個使用者 preview task `01a0994a-f42c-7f40-9aef-218d01917dab` 啟動 `.venv` Uvicorn，其 lifespan log 顯示執行 `base→0001→…→0006`。這項寫入不屬 C026／D028，也不是 R26 核准的正式 migration、restore、分類或公司行動 repair。

統籌隨後只以 SQLite `mode=ro`／`query_only=1` 檢查，確認 current `alembic_version=0006_news_json_defaults`、21 tables；查驗前後 current file 均為 296,366,080 bytes、SHA-256 `3a21772050b3053557c0798876cc0aa1efe024fcbdce5ab44e35e6abf12da018`。這只能證目前 head 與該次唯讀查驗未再改檔，不能取代 C003 的 consistent-copy 20-table／622,399-row preservation 證據，也不能宣稱完整 historical/schema parity、所有資料轉換正確、正式 restore／deployment drill 或 migration acceptance。`.local/data/stock.db` 保持 438,272 bytes、SHA-256 `87453d7b29954b6d506f8020b8987f321aa6749ce9bc24fbef695dd3874b8d02`。

### 8.6 Round27 API startup readiness（有限 review）

歷史基線先被獨立固定：R27 輪初由統籌保存在 `stock-r27-coordinator-review/before/backend/app/main.py` 並由 `round-baseline.json` 指認的原件（SHA-256 `98d97f944edd015a5e93bb8d451f7f3d9ea0e389ae0b1032a21947ae9a553aff`）有唯一 `@asynccontextmanager` lifespan，依序呼叫 `init_db()` 再 bare `yield`，且 FastAPI 明確綁定該 lifespan。D029-A 的 corrected exact baseline SHA／AST oracle 由統籌另行複製重跑 10／10、exit 0。原 D029 六個 frozen artifacts 曾暫時被修改後恢復原 bytes／hash／size／mtime；原 28 pass／1 failure、後續 29-pass variant 及補充五檔都保存，故只能稱 restored equality，不能稱從未改動，也不能用寬鬆 variant 冒充歷史 shape 證據。

C027-B 只改啟動邊界：`app/main.py` 改呼叫新的 `app/database_readiness.py::check_database_readiness`，新增 `tests/test_database_readiness.py`，並只調整 `test_api.py`、`test_product.py`、`test_backfill.py` 內既有 main-module fixtures；`db`、`config`、`models`、`migrations`、Alembic revisions 與 worker 均未改。成功回傳 `None`，失敗拋出含操作說明的 `DatabaseReadinessError`；D029-A draft 的 proposed status／code 名稱不是 public interface。

readiness 對設定的 `DB_PATH` 先要求 regular nonempty file，再以解析後 file URI 的 SQLite `mode=ro`、`query_only=ON`、單一 read transaction 與一秒 busy timeout 檢查。版本狀態只接受：Alembic table 恰有唯一 current head `0006_news_json_defaults`，並可無 fallback，或與 0001 起算、長度 1–6 的非空完整已知 prefix 共存；若沒有 Alembic，fallback 必須恰有六枚 revisions。Alembic stale／unknown／multiple／malformed 不能由 fallback 覆蓋；marker view、empty／gap／duplicate／null／nonstring／unknown marker 都拒絕。

有限 schema gate 只要求 19 個 mapped objects 都是 real tables，並核 concrete mapped column names、ordered primary key、required unique column keys、foreign-key definitions 與 `news_items.symbols_json`／`theme_ids_json` 的 SQL empty-array literal defaults。唯一 partial-unique 相容例外是 canonical `ix_ingestion_runs_request_key` on `ingestion_runs(request_key)`，且完整保存 DDL 必須整體匹配 `request_key IS NOT NULL`；其他 partial shapes、較窄 subset 與 comment／string predicate spoof 都不能滿足 identity。額外且不破壞必要 identity 的 custom schema 可以存在。

這個 gate 不做完整 type、nullability、collation、FK action、CHECK、額外 schema 或 SQL-text parity 稽核，也不掃歷史 rows、資料 FK、`quick_check`／`integrity_check` 或 deep page corruption。`app.config` import 仍會建立設定的 data／raw directories，API request handlers 可以寫，worker 與明確 `worker.cli init-db` 仍可 migration；SQLite live WAL／SHM side effects 與 concurrent writers 不由 controlled-copy no-mutation 證據涵蓋。R27 沒有重啟使用者既有 service，running process 可能仍載入先前 lifespan。

統籌的 `startup_review.py`／JSON／calls／log 共 39 cases、41 subprocess calls、exit 0；兩個 subprocess 明確初始化 fresh Alembic／fallback seed DB，其餘真正 lifespan／TestClient health cases 都裝設 migration／repair／`create_all` bombs。案例涵蓋 historical current snapshot、pre-startup snapshot refusal、missing／empty／bad files、marker／schema defects、合法 prefixes、URI escaping、一秒 lock timeout、額外 schema 與 partial-index spoof，並逐案比較 SHA／size／mtime 或 absence；正式、`.local` 與兩個 coordinator snapshots 等四個 protected files unchanged。每個 child 都在 import 前收到外部 Temp 的三個 `STOCK_*` 環境值。

完整 backend 為 1,011 passed、1 skipped、9,089 warnings，pytest 74.68 秒、subprocess 80.203 秒、exit 0；skip 是既有 Windows symlink privilege case，133 個 protected paths unchanged。作者 final targeted 的 76 個新 cases 加 74 個既有 cases 共 150 passed／4,070 warnings、pytest 18.37 秒，另有三個 real subprocess 驗 historical replay 與 explicit CLI init-db 後 repeated readiness／health。C027 的六個 source 與 697 個 B artifacts、C027-A 的 16 個 artifacts 均由統籌逐一核對 freeze SHA／size／mtime；第一輪 wrapper propagation failure、137-pass partial-index rejection 與一個無 DB action 的 quoted Python parse failure都保留，沒有用 final success 覆寫。

historical preservation 只接受具名資料：外部 consistent snapshots 的 type-tagged full-row multiset hashes 顯示 R26 saved original→current 的 20 個歷史 tables／622,399 rows 全部保留，沒有舊 columns 增刪；schema 差異只有新 `alembic_version`／PK autoindex，以及兩個 News JSON `[]` defaults／identifier quoting。兩份 snapshot 的 integrity 為 ok、FK violations 為 0。C027-A 另以保存 baseline 實跑 0001→0006，21 個 table descriptors／typed rows／完整 `sqlite_schema` 均等於 current snapshot。原 R26 saved DB、current 正式 DB 與 `.local` fingerprints 在觀察期間不變；R27 沒有 migration／repair／restore 兩個來源 DB。

以上只解釋這組 saved-original／current／replay，不證所有 legacy migration branches 或 custom schemas，不接受正式 migration／deployment／restore，也不證介入期間因果、market truth、PIT、B3-wire、B5b、B7 或更廣 ROADMAP 已完成。統籌正式驗收在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r27-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`；完整啟動 JSON／logs、full backend guard 與 parity artifacts 位於同一外部目錄。

## 8.7 Round28 C028：canonical legacy instruments identity rebuild rollback／fail-closed（有限 review）

Round28 先以專案外 synthetic DB 固定舊 `0002_instrument_exchange_key` rebuild 的缺陷：C028 Phase A 共 57 cases／30 retries，統籌另跑 6-case probe。舊 revision 會在 env-owned migration boundary 內自行 commit；copy／drop／rename／index／marker fault 因而可能留下 scratch、缺 parent 或 schema／marker 分裂。舊固定 12 欄／3 indexes rebuild 也會遺失受測 extra column、index、trigger、default、CHECK、outbound FK 與 pre-existing scratch。顯式 `foreign_key_check` 在 FK 0 與 FK 1 的 after-DROP 案都發現 child orphan；FK pragma 恢復不能代替關聯完整性。四個 rename-failure aftermath retries 雖走到 head 0006，`instruments` 仍缺、scratch／orphan 仍在，屬 false recovery。以上是修正前證據，不是修後 pass；D030 Phase A 的契約 review 原始錯誤與後續 `A_CORRECTIONS.md` 都保留。

C028-B 將成功範圍收斂成有限、已知 SQLite grammar，不建立通用 SQL rewriter。canonical legacy 必須有唯一且 ordered full `UNIQUE(market, symbol)`、沒有 target identity，欄位定義、PK、constraints 與 indexes 都符合 allowlist；缺少 `exchange`／`industry` 時仍先走既有 additive path，rebuild 本身要求兩欄已存在。成功後只把 identity 換成 ordered full `UNIQUE(exchange, symbol)`，以已驗證的原 column definitions 複製所有有限欄位，保留 storage type、值與 `id`；既有 `is_watchlisted DEFAULT 0` 與 ORM 無 server-default 兩種已知形狀維持各自語意。

可保存的 inbound FK 只有現行九個 application child：`group_memberships`、`market_bars`、`chip_snapshots`、`technical_features`、`signals`、`portfolio_positions`、`corporate_actions`、`fundamental_snapshots`、`events`。支援的每組關聯都必須是 simple 單欄 `instrument_id → instruments.id`，action 必須是 `ON UPDATE NO ACTION`／`ON DELETE NO ACTION`、`MATCH NONE` 且 non-deferrable；不能泛稱其他 action 或任意 inbound FK 已支援。修後測試實際放入九表 mapped rows，成功 rebuild 保留 child rows／descriptor，且 whole-run `integrity_check=ok`、`foreign_key_check=[]`。

recognized current state 只要求 ordered full `UNIQUE(exchange, symbol)` 且沒有 legacy full identity，並走 no-rebuild；受測代表性 extra column／index／trigger 維持不變。這是有限 identity no-rebuild 判定，不是 current table 的完整 schema validator。mixed full keys、neither identity、partial／expression／reversed identity、duplicate target、noncanonical legacy column／default／nullability／PK、extra legacy object、CHECK、self／outbound 或未知 inbound FK、generated／hidden column、table option、既有 FK violation都在 destructive DDL 前 fail closed。任何 main scratch prefix、TEMP `instruments` 或 TEMP scratch shadow 也拒絕，不能先刪 scratch 再倚賴 rollback。

`alembic_version` 與 fallback `schema_migrations` 若宣稱已知 `0002`–`0006` 任一 revision，但 parent 狀態仍是 absent 或 legacy，會在 `create_all`／`0001` 前拒絕；呼叫前已缺 parent 且留 scratch／old artifact 的保存殘局同樣原樣 fail closed。本批不定義 auto salvage。這與完整 fixture 上由修後程式注入 fault 不同：96 個 fault cases 都必須 exact before==after，移除 injector 後在同一 DB retry 成功。

SQLite Alembic runner 現在擁有跨完整 revision chain、revision marker 與 pre／post health checks 的單一 explicit transaction／FK-state boundary；`0002` 與窄 helper 不再自行 commit、rollback 或切 pragma。fallback 保留 named savepoint並使用同一 preflight／health policy，使 schema、rows 與六枚 fallback markers落在同一成功邊界。已有 active transaction 的 supplied external `Connection` 會在 mutation 前拒絕。一般成功、失敗與 no-op 都恢復進入時 FK 0／1；刻意令 FK restore 本身失敗時，只接受原 migration exception 被保留、restore exception 成為 cause，不宣稱該注入案成功恢復 FK 或 connection 可重用。

production／test 實際只改六個 paths：新增 `backend/app/instrument_identity_migration.py`、`backend/tests/test_instrument_identity_migration.py`，並修改 `backend/app/migrations.py`、`backend/alembic/env.py`、`backend/alembic/versions/0002_instrument_exchange_key.py`、`backend/tests/test_news_json_defaults.py`。News 測試只調整 `_old_005_engine` 的 instruments `CREATE`／`INSERT` 兩個 SQL fixture expressions，將原 neither-identity 前置改成完整 current identity並保留 `id=1`／`symbol=2330`；AST 比對確認其餘 top-level nodes不變，News schema／rows／self-FK／defaults／trigger／index／fault assertions與 production helper都未改。因此不回寫或擴張 Round11 §8.4。

### 8.7.1 最終驗收證據

| 項目 | 實際結果 |
| --- | --- |
| source freeze | C028-B 六檔由 `source-freeze.json` 固定；manifest SHA-256 `3edb72132099cc746ea0309de1e9bbea62bf78f056ae0db123fd0906e877c0b5`。六檔依序為 helper `f2f7f945…`、migrations `37936752…`、Alembic env `05d3772d…`、0002 `92976ce5…`、new test `58e5e593…`、News test `1e691bb5…`；統籌逐檔核對完整 SHA／size／mtime。 |
| 作者實跑與修正史 | run01 `102 passed／93 warnings／10.47s／exit 0`；run02 `292 passed／1 failed／2,574 warnings／76.29s／exit 1`，唯一 failure 是 test observer 遮蔽刻意 FK-restore failure 的原 exception chain，後續只修 observer；run03 `440 passed／2,809 warnings／95.55s／exit 0`。run04 `464 passed／3,017 warnings／168.46s／exit 0` 發生在最後 known-marker patch 前，不能稱 final full 386；final source 的 run05 是 selected subset `249 passed／1,191 warnings／51.38s／exit 0`。作者未跑 final full backend。 |
| 統籌 independent matrix | frozen matrix `206／206`、`10.437s`、exit 0，加 special `16／16`、`1.515s`、exit 0，共 222 independent cases。主矩陣含 18 shapes × 3 entrances × FK 0／1、8 statement／check faults × before／after × 3 entrances × FK 0／1、2 active-caller cases；96 fault injections 都驗 exact rollback與 same-DB retry。special涵蓋 TEMP parent／scratch、錯誤 head stamp、兩 marker families 的 legacy／missing-parent fallback refusal。兩組各自回報 156 guarded paths unchanged。 |
| final full backend | 最終六 source hashes上 `1,397 passed／1 skipped／12,029 warnings`，pytest `163.09s`、wrapper `166.047s`、exit 0；新 instruments test 的 386 parameterized cases全由此 run走過，156 protected paths unchanged。此 run輸出只列 1 skipped，沒有要求或列出原因；R27 的 Windows symlink limitation是分開的歷史紀錄，不能當成本輪另驗 skip reason。 |
| artifacts與範圍 guard | `c028-b-review.json` 驗六個 frozen source paths及 4,800 個 Phase B artifact entries 的 SHA／size／mtime_ns 全相符；Phase A review另驗 395 artifacts、57 case classifications與四個 false recoveries。正式與 `.local` DB SHA／size／mtime均符合 R27 handoff／本輪 baseline；本批沒有對正式或 `.local` DB執行 migration、restore或repair，也沒有service restart、install、Git mutation或外部帳戶／交易動作。 |
| evidence roots | 統籌 final acceptance：`C:/Users/YiCheng/AppData/Local/Temp/stock-r28-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`；作者報告與 freeze：`C:/Users/YiCheng/AppData/Local/Temp/stock-r28-c028-implementation/REPORT.md`、`source-freeze.json`。matrix、special、full backend streams／receipts與 before／after case data均保存在上述外部 evidence roots。 |

因此只接受 canonical legacy instruments identity rebuild 的有限 SQLite preservation／rollback／fail-closed。沒有證明任意 custom 或所有 historical schema parity、non-SQLite、附加 schema、實體 corrupt-file recovery、真 disk-full／process-crash／commit-failure／concurrent writer、正式 migration／restore／deployment、auto salvage、資料 truth／PIT 或 R0 整體完成。本節當時尚未驗收的 `signal_settlements` 具名缺口由後續 §8.8 分開處理，不能倒寫成 Round28 已完成；whole-run atomicity／health guard 也不等於其他 rebuild 的 custom-schema preservation 已驗。R27 readiness仍只是 startup有限唯讀 gate。

## 8.8 Round29 C029：canonical legacy `signal_settlements` identity rebuild rollback／fail-closed（有限 review）

Round29 Phase A 先在專案外 synthetic DB 固定舊 `0001_schema_v1` rebuild 行為。舊固定 copy 會遺失受測 extra column／value、custom index、trigger、changed default、CHECK、noncanonical outbound action 與既有 scratch；mixed 或缺少完整 identity 時也可能成功寫入版本 marker，卻沒有取得正確 target identity，屬 false target claim。這些結果只是修正前缺陷調查，不是產品 pass。受測 fault 的既有外層 transaction rollback／retry 本身有成立，但不能拿來抵銷成功路徑的 lossy 或錯誤接受。D031-A 原始契約中的 legacy inbound 政策已由同目錄 `A_CORRECTIONS.md` 修正：所有 legacy inbound 一律拒絕；current no-rebuild 才可保留不破壞 essential semantics 的 extra inbound。

C029-B 新增 `backend/app/settlement_identity_migration.py`，並由 fallback、Alembic Engine／inactive external `Connection` 與 `0001_schema_v1` 共用。只有 unmarked、exact known 9-column legacy 或 known 14-column additive legacy，且具 simple full ordinary BINARY `UNIQUE(signal_id)` 與 exact sole outbound `signal_id → signals.id` FK（`NO ACTION／NO ACTION／MATCH NONE`、non-deferrable），才可 rebuild；`signals` parent 必須是真實可用 table。legacy nonunique index 可完全缺席，若存在則只接受兩個 known ordinary index shapes；rebuild 後建立這兩個 known indexes。成功 target 具有 ordered full `UNIQUE(signal_id, horizon)`。missing horizon 與 legacy nullable horizon 的 `NULL` 都刻意 normalize 成 integer `20`；missing execution fields 為 `NULL`，missing quality 為 `complete`，其餘 known typed payload 與 `id` 保留。這是有意的資料正規化，不可描述成所有欄位逐 byte 不變。

recognized current 只做 finite no-rebuild 判定：要求 14 個 known columns、`id` PK、essential `NOT NULL`／defaults、exact ordered pair identity、exact outbound FK，以及 identity／quality 非 NULL 且 pair 不重複。raw numeric `DEFAULT 20` 與 quoted `DEFAULT '20'` 可依 omission 後 typed semantic equivalence 接受，不宣稱 exact SQL-text parity。受測 current extra column／object、non-conflicting inbound FK 與 quoted default 在 no-rebuild 路徑保留；這不是任意 CHECK、trigger、extra object、secondary nonunique index existence、row 或整體 schema audit。

destructive DDL 前會拒絕 unsupported legacy extra column／default／CHECK／index／trigger／view／generated column／table option、任何 legacy inbound FK、noncanonical outbound／self FK，以及 mixed、neither、partial、expression、reversed 或 duplicate identity。任何 main scratch prefix、TEMP `signal_settlements` 或 TEMP scratch shadow 也拒絕，不能先刪 scratch 再假設 rollback。任一 marker family 宣稱 known `0001`–`0006` 時，settlement 必須已是 current；absent、legacy 或 invalid shape 都會在 `create_all`／0001 DDL 前 fail closed。只有 unmarked absent state 可走 fresh initialization，本批不定義 auto salvage。

helper 本身不 commit、rollback、切換 FK pragma 或寫 marker。fallback 既有 named SAVEPOINT 與 Alembic 既有 explicit transaction 仍擁有 revision chain、marker 與 health checks；postflight 在 commit 前執行，但不保證早於 marker DML，marker 仍受同一 transaction 包住。supplied external `Connection` 若已有 active transaction，會在 mutation 前拒絕。FK 0／1 的 ordinary success、failure 與 no-op 仍由 runner 恢復；本批沒有擴張既有 FK-restore exception 限制。

測試 fixture 只做必要前置：News old005 setup 加入 minimal real `signals` parent 與 empty canonical 14-column settlements；recovery loader 在讀入 immutable Round10 SQL 後追加相同兩個 empty prerequisite `CREATE`。第三個 direct-slice setup 改走該 supplemented loader。`source-review.json` 的 AST／hash 核對顯示 original assertions、既有 fault payload 與 fixed SQL／JSON bytes 不變，因此不回寫或擴張 Round10／11 的 News acceptance。

### 8.8.1 最終驗收證據

| 項目 | 實際結果 |
| --- | --- |
| source freeze | 僅七個 paths：new settlement helper、`migrations.py`、Alembic `env.py`、`0001_schema_v1.py`、new settlement test、News test、recovery test。`c029-b-review.json` 核對 7 source 與 8,214 artifacts；artifact manifest SHA-256 `1fad7cc5d1874050d50f8658a8c35bc02b954a51bce7e6afaecc8b863526acbf`。七檔 SHA-256 依序為 `dda14fdb…`、`f6ed0c9a…`、`b95fa563…`、`85bd90d9…`、`dd3106e8…`、`9d6b9b30…`、`f8e14f79…`。 |
| 作者修正與實跑史 | targeted01 `407 passed／1 failed／2,962 warnings／109.90s／exit 1`，唯一 failure 是 direct-slice 缺 settlements prerequisite；獲授權調整 fixture 後 targeted02 `428 passed／369 warnings／18.27s／exit 0`，targeted03 `462 passed／407 warnings／21.21s／exit 0`，含 final 440 個 new settlement tests，其中 96 個 fault 與 144 個 false-marker cases。作者 full01 為 `1,836 passed／1 failed／1 skipped／12,414 warnings／199.31s／exit 1`；唯一 failure 來自 launcher 只改 parent `sys.path`、未把 `PYTHONPATH` 傳給 child subprocess，造成 `ModuleNotFoundError: worker`，不能寫成 pass。修正外部 launcher 後 targeted04 對 `test_source_runtime.py` 為 `38 passed／1 skipped／1.16s／exit 0`，repository source 未因而改動。 |
| 統籌 independent matrix | matrix-01 `exit 1／1.25s`，因 review harness 用無 column list 的 `INSERT INTO signals VALUES(13)` 撞到實際 6 欄 table；158 guards unchanged，保留為 harness failure 史。修正 harness 後 matrix-02 `408／408`、23.609 秒、exit 0；special `14／14`、2.297 秒、exit 0，共 422 independent cases。special 含三入口 × FK 0／1 的 current inbound 與 quoted default 12 案，加 active caller 2 案。統籌主矩陣的 84 個 fault cases 皆驗 exact rollback 與 same-DB retry；matrix-02 與 special receipts 各為 158 guards changed=[]。 |
| final full backend | 統籌以完整 corrected environment 執行 final source：`1,837 passed／1 skipped／12,414 warnings`，pytest 185.52 秒、wrapper 188.562 秒、exit 0。skip 明列為 `test_source_runtime.py:238` Windows symlink privilege unavailable；158 protected paths changed=[]。 |
| artifacts 與操作界線 | 作者 B 的 8,214／8,214 artifacts 與七個 source fingerprints 均核對相符；source freeze 是 full01 執行中擷取，不能當成 run 前 baseline，統籌 final full 另有獨立 158-path before／after guards。所有 production imports 與測試 DB 都指向 fresh 外部 Temp；本批沒有 migration、repair 或 restore 正式／`.local` DB，也沒有 service、install、Git mutation、外部帳戶或交易動作。round-end codebase index 由 I068 在 source／docs freeze 後另行刷新。 |
| evidence roots | 統籌 final acceptance：`C:/Users/YiCheng/AppData/Local/Temp/stock-r29-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`；作者 freeze／logs：`C:/Users/YiCheng/AppData/Local/Temp/stock-r29-c029-implementation/`；D031-A 原始 19 artifacts manifest SHA-256 `683d4e93744b55b9e0d00a9add4ee5aa3f1cccef8a2add3fa9a5a6d6d4ef6534`，corrections 與 probe evidence 保存在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r29-d031-contract/`。 |

因此只接受 canonical legacy `signal_settlements` 的有限 SQLite preservation、identity 轉換、rollback／retry 與 fail-closed。non-SQLite、attached schema、任意 historical／custom schema、實體 crash／disk-full／commit failure／concurrent writer、正式 migration／restore／deployment、資料 truth／PIT 與 R0 整體完成都不在本批。R27 `check_database_readiness()` 也沒有在 R29 修改：統籌以一份保存的 external Phase A mixed-identity DB 唯讀重現 readiness 回 `None`，但在 memory copy 插入第二個不同 horizon 時仍被舊 `UNIQUE(signal_id)` 拒絕；來源為 430,080 bytes、SHA-256 `f06e4c48d24e98599d607f02c33d7b7b914b7aba10b458ced7cefae9b022f291` 且未變。這只是一個 next-round candidate，不代表正式 DB 受影響，也不削弱本輪 explicit migration acceptance。

## 8.9 Round30 C030：API startup `signal_settlements` UNIQUE metadata gate（有限 review）

R29 的最後一段是當輪歷史事實：它沒有修改 R27 readiness，保存的 external mixed-identity DB 可通過 startup，卻會因殘留 `UNIQUE(signal_id)` 阻擋第二個 horizon。Round30 才在 `backend/app/database_readiness.py` 新增 `_check_settlement_unique_indexes()`，並只於既有 `signal_settlements` mapped-table 檢查內呼叫；不改 migration helper、marker、lifespan mutation 邊界或其他 table gate。

有限 canonical 規則是：`main.index_list('signal_settlements')` 至少要有一個 UNIQUE，其 `index_xinfo` key parts 恰為 ordered `(signal_id, horizon)`，是 full／non-partial、ordinary real columns，所有 key parts 都是 ASC 且 collation 為 BINARY。可有重複的 canonical pair。每一個 key parts 含 `signal_id` 或 `horizon` 的其他 UNIQUE 都必須同樣是 canonical pair，因此 signal-only、horizon-only、reversed、superset、mixed、target partial、target DESC／non-BINARY 都 fail closed；這裡的 ASC／reversed 拒絕是 canonical compatibility policy，不是已證這些 shape 必然阻擋第二個 horizon。

檢查只看 `index_xinfo` 的 key parts，不解析 partial predicate 或 generated dependency；例如 `UNIQUE(source) WHERE horizon=20` 與 `UNIQUE(id) WHERE signal_id>0` 的 key parts 不觸及 target，仍屬可接受的 unrelated named-column UNIQUE。相同理由下，unrelated named-column UNIQUE 即使 partial、DESC 或非 BINARY，也不由本 gate 拒絕。任何 UNIQUE expression 的 key metadata 無法由有限檢查可靠歸屬，故不論表面上是否 unrelated 都保守拒絕；nonunique expression／target indexes不在這個 UNIQUE gate。任意 CHECK、trigger、unrelated UNIQUE 的實際寫入效果都不 audit，所以 readiness pass 不保證任意 INSERT 成功。

### 8.9.1 最終驗收證據

| 項目 | 實際結果 |
| --- | --- |
| source scope／review | production 只改 `backend/app/database_readiness.py`（SHA-256 `6082c987550d2b9254b4ddde7f3f48fcf1895dd0db531de675a4cb61d6ef8b09`），新增 `backend/tests/test_startup_settlement_identity.py`（SHA-256 `4e7c0d96e15e0458861fcf2b583d93577dd9e2d93d1bb18a697161ffad72d840`）。AST review 顯示既有 production AST 除新增 helper 與一個條件呼叫外保持不變。 |
| 作者 targeted | final source 為 `664 passed／474 warnings`，pytest 58.46 秒、wrapper 59.673 秒、exit 0；80 個 guards unchanged。新增 126 tests 是 40 個 metadata shapes × 3 個 marker families 共 120 cases，每案內再走 direct／repeat／actual lifespan，另加 6 個 memory INSERT semantics；後者固定「canonical second horizon 可寫、mixed 被擋」、「reversed／DESC 雖可能可寫仍按 policy 拒絕」，以及「unrelated UNIQUE／trigger 雖可能擋寫仍可通過」的有限邊界。此數字不與 R29 migration 或統籌 matrix cases 混算。 |
| 統籌 external matrix | 87 個 populated external DB，各走 direct／repeat／actual lifespan，合計 261 entries；另有 261 個 memory INSERT probes，5.078 秒、exit 0、mismatches `[]`。逐案使用 `mode=ro`、`query_only`、單一 `BEGIN`；`migrations.upgrade_database`、`_fallback_upgrade`、`Base.metadata.create_all` 及 settlement preflight／rebuild bombs 都未觸發，readonly trace 與 authorizer 證明沒有 business-row read。87 個 DB 與全體 guards 維持不變。 |
| final full backend | `1,963 passed／1 skipped／12,414 warnings`，pytest 226.12 秒、process 229.344 秒、exit 0。唯一 skip 是 `backend/tests/test_source_runtime.py:238: symlink privilege unavailable`；159 個 protected guards 的 SHA／size／exact mtime 均 unchanged。 |
| 操作與未完成 | 所有 synthetic DB、logs 與 probes 位於專案外 Temp；正式 DB 只受既有 protection fingerprint 守衛且未被開啟。本批沒有 migration／repair／restore 正式或 `.local` DB，沒有 service、install、Git mutation、deployment、外部帳戶或交易動作，也未驗 non-SQLite、attached schema、實體 crash／disk-full／concurrency、完整 historical／custom schema、資料 truth／PIT 或 R0 完成。下一個候選僅是一個 external instruments synthetic probe：current pair 加 legacy `UNIQUE(market, symbol)` 可能通過 readiness、卻阻擋同 symbol 的第二個 exchange；尚未形成矩陣、契約或產品結論。 |
| evidence roots | 統籌 final acceptance、source review、matrix、full streams／receipt：`C:/Users/YiCheng/AppData/Local/Temp/stock-r30-coordinator-review/`；D032-A contract／probe／freeze：`C:/Users/YiCheng/AppData/Local/Temp/stock-r30-d032-contract/`。 |

因此只接受 SQLite API startup 對 `signal_settlements` UNIQUE metadata 的有限 fail-closed 補強。它不掃 business rows、不做 DDL、migration、repair 或資料寫入；也不能由通過結果推論任意 CHECK／trigger／unrelated UNIQUE 不會妨礙寫入，或任意 INSERT、資料 truth／PIT、正式部署與 R0 整體已完成。

## 8.10 Round31 C031：API startup `instruments` UNIQUE metadata gate（有限 review）

R30 的最後候選是一個 current `(exchange,symbol)` pair 加 legacy `UNIQUE(market,symbol)` 的 external synthetic DB：舊 startup 可接受，但 `market="TW"` 時第二個 exchange 的同 symbol insert會衝突。Round31 才在 `backend/app/database_readiness.py` 新增 `_check_instrument_unique_indexes()`，並只於既有 `instruments` mapped-table檢查內呼叫；既有 settlement helper、generic schema gate、models、main與migration均未改。

有限規則是：mapped `market`、`exchange`、`symbol` 都必須有 `table_xinfo.hidden=0`；這只作三欄非 hidden／generated 的相容檢查，不證完整writability，也不是全表type／nullability／default或generated parity。至少一個 UNIQUE 必須是 full／non-partial、ordered `(exchange,symbol)`，其 named key parts均為 ASC／BINARY。每個 UNIQUE只要 key parts觸及 `{market,exchange,symbol}` 就必須同形，因此 single、legacy、reversed、superset／mixed、partial、target DESC／non-BINARY都拒絕；任意 UNIQUE expression因 `index_xinfo` 無法有限歸屬 dependency而保守拒絕。ASC、reversed、superset與partial中的部分拒絕是 descriptor policy，不表示每一形狀必然造成所測 INSERT collision。

`index_xinfo.cid>=0` 只證 named-column key，不能單獨證明 nongenerated；canonical target另由上述 `table_xinfo` 檢查證成。key parts不含三個 target名稱的 named-column UNIQUE仍可存在，包含 partial／DESC／non-BINARY或 generated extra；本批不解析其 predicate或generated expression，所以它們仍可能依賴 symbol並妨礙某些寫入。CHECK、trigger、nonunique index及其他欄位 descriptor同樣不在 audit，readiness pass不保證任意 INSERT。這個 startup contract刻意可比R28 current-identity no-rebuild recognition更窄；明確 `worker.cli init-db` 不會自動修復或移除所有 startup拒絕的custom shape。

### 8.10.1 最終驗收證據

| 項目 | 實際結果 |
| --- | --- |
| source scope／review | production只改 `backend/app/database_readiness.py`（SHA-256 `ff1a26d5a78f35aa083bc02b08965bcc29435eb4f41a418f34ba7a696bf82fd4`），新增 `backend/tests/test_startup_instrument_identity.py`（SHA-256 `426868ff95520621e8094d4a845ca24377e0f54a677f73e44b0a14257a804940`）。移除一個新helper與一處conditional call後，readiness其餘AST與舊版相同。 |
| 作者 targeted | `786 passed／3,007 warnings`，pytest 202.35秒、process 203.427秒、exit 0；15 guards unchanged，無fail／skip。198個新tests為60 shapes×3 marker families、12 semantics及6個mapped generated explicit-write cases，已包含於單次run，不與full數相加。 |
| 統籌 external matrix | 41 shapes×3 marker families＝123個populated external DB；369個direct／repeat／actual lifespan entries與492個readonly-backup memory probes，7.172秒、exit 0、mismatches `[]`。`mode=ro`、`query_only`、單一`BEGIN`與authorizer無business-row read均通過；具名migration／helper／`create_all`禁止呼叫均未觸發，123 DB與160 guards unchanged。 |
| final full backend | `2,161 passed／1 skipped／12,414 warnings`，pytest 273.99秒、process 277.218秒、exit 0；唯一skip是 `backend/tests/test_source_runtime.py:238: symlink privilege unavailable`，160 guards的SHA／size／exact Unix mtime均未變。 |
| 操作與限制 | synthetic seed建立與backend migration tests有明確執行，但正式／`.local` DB只受byte fingerprint保護，未被本批SQLite-open、migration、repair或restore。沒有service restart、install、Git mutation、deployment、帳戶或交易。non-SQLite、attached schema、任意 historical／custom schema、實體crash／disk-full／concurrency、資料truth／PIT與R0整體仍未完成；輪末I070索引另在source/docs freeze後驗證。 |
| evidence roots | 統籌 acceptance／matrix／full logs在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r31-coordinator-review/`；C031 artifacts在 `stock-r31-c031-investigation/`、`stock-r31-c031-implementation/`；D033-A contract／probe在 `stock-r31-d033-contract/`。 |

因此 R31 只接受目前 checkout 的 SQLite API startup `instruments` 有限 metadata補強，不回寫成R28 migration已含此gate或正式部署已完成。該輪交出的 R0-B2 comparison 候選已在 Round32 依 §5.6 完成有限 library review；這不回寫 R31 成果，也不表示B2、B7、PIT或預設版本切換完成。下一候選只到完整保存輸入 replay 可行性調查，尚未核定實作。

## 9. B7：新舊版本隔離驗證與 review gate

每一個會產生研究結果的 R0 修正最後都用同一份唯讀輸入快照做 paired replay：legacy 走原版本，新計算走新版本；輸出至不同 DB、namespace 或 version key。不得讓兩個 run 互相 upsert。

差異報告至少包含：

- 輸入 snapshot id／雜湊、日期範圍、instrument universe、公司行動與來源版本。
- legacy／new feature、strategy、execution、prediction、signal-output semantics 及 presentation versions。
- ATR 有值／warm-up／缺值筆數、gap 與公司行動案例逐筆差異。
- conditional／observation／data_incomplete 數量變化與原因碼；confidence legacy／null 分布。
- 規則參考價與新交易計畫分開的差異，invalid levels、gap reject、incomparable 數量。
- availability gate 排除的資料與最早執行時間變化。
- migration revision、命令、exit code、測試通過／失敗／跳過數；不可只貼最後一行「passed」。
- 未預期差異、已知限制及是否建議切換預設版本。

reviewer 應重現至少一個成功、缺資料、跳空、公司行動、legacy confidence、盤後可得與修訂案例。只有 reviewer 記錄完成後，批次才可標「已 review」；是否更新 ROADMAP 或切換預設版本由統籌另行決定。

## 10. 非目標與停止條件

- 本契約不選股票、不評估策略績效、不設定個人風險預算，也不授權自動交易。
- 不因 R0 修正而擴大收集期間、採購來源、執行正式 migration 或回填正式資料。
- 若實作需要原地覆寫舊列、無法隔離正式 DB、無法辨識相應 feature／strategy／execution／output-semantics version、或公司行動／時間來源無法重建，立即停止該批並記錄 blocker；不得以「先跑再說」繞過版本與 point-in-time 邊界。
