# Reviewer 記錄：intake 產出審查（spec-1）

- 對象：`intake-analysis.md` / `intake-tasks.md` / `intake-verification-map.md` / `intake-review-map.md`
- 對照事實來源：`orchestrator/requirement.md`、`docs/design.md`（§2/§3/§4/§5/§6/§7/§8/§11）
- framing：對抗式（假設此計畫已上線出事，反推失效點）

---

# 第三輪:結構修補審查（round 3）

**對象**:針對 blame(spec-2 focused review 指出 `backend/pyproject.toml` 依賴寫入權對平行 adapter 無下游合法路徑)的結構修補。只審此次修補(新增 spec-12＋依賴圖調整),非全面重審。逐項核對四份文件實際內容。

## 最終 Verdict

**pass**(可進人類 gate;附兩條非阻擋建議 R7/R8,見下)

修補達成目的:pyproject 依賴寫入權的 ownership 缺口已補實,DAG 仍成立,平行安全論證站得住,spec-2 已審過的實作未被動到。四份文件交叉引用一致(spec-7/8/9 的 `depends_on`、verification-map how、review-map trigger、analysis §5 Q1、§6 統計全部同步含 spec-12)。無 round-1 那種「拿去執行必爆」等級的確定性缺陷。

## 逐項核實

- **Q1 平行安全 — 成立**。`backend/pyproject.toml` 只出現在兩個節點的 `allowed_outputs`:spec-2(root)與 spec-12(`depends_on: [spec-2]`)。`allowed_outputs` 為白名單,spec-3/5/6/7/8/9/10/11 各自只列自己的檔,故無其他節點能合法寫 pyproject。spec-2→spec-12 為序列邊,兩個唯一寫者永不併發;spec-2 若被 cascade 重跑,spec-12 因依賴邊會被連帶重跑並排在其後,序列關係不破。**唯一之後還寫 pyproject 的節點確實只有 spec-12**。

- **Q2 spec-6 不需新依賴 — 判斷可信**。證交所/櫃買日價量 OpenAPI 回 JSON、每日收盤走 CSV,stdlib(json/csv)可解,無 HTML 解析需求。維持 `depends_on: [spec-3, spec-4]` 不含 spec-12 合理。

- **Q3 spec-7 保守序列化 — 合理且未犧牲有意義平行度**。spec-7 臨界路徑為 `max(spec-3, spec-4, spec-12)`;spec-12 tier-low、遠早於 tier-medium 的 schema(spec-3)完成,故加這條邊實際成本近乎零。籌碼源多半也是 JSON/CSV(可能根本不 import bs4),此序列化屬「若需 HTML 的備援」的無害保守,不阻擋。

- **Q4 spec-12 完成定義 — 部分可機器驗、關鍵半段偏弱(見 R7)**。test-12 客觀驗到:tomllib 解析成功、三新套件(ddddocr/bs4/lxml)在列、preflight 安裝後可 import。但「spec-2 原有依賴與其他區段未被刪改」這半段,完成定義以「diff 僅新增依賴行」表達——**未列舉 spec-2 基線套件清單,亦未驗既有版本約束**,且「diff」所需的基線來源(spec-2 產出的前一版 pyproject)在流程中未必有可靠的 per-node commit 可取。故此屬性作為**自足的機器斷言並不成立**(見 R7)。所幸 spec-12 為 focused review,upgrade_trigger 明列「增列以外動到既有依賴/build/metadata(越界)」,reviewer 看 diff 會抓到掉套件/改版本,構成 compensating control,故非阻擋。

- **Q5 DAG — 無環、無矛盾**。新增邊:spec-12→spec-2;spec-7/8/9 各加→spec-12。spec-12 只依賴 spec-2、不依賴任何 adapter;spec-11 經 spec-7/8/9→spec-12→spec-2 仍為單向。test-12→test-2 亦無環。圖仍為 DAG。

- **Q6 未動 spec-2 已審產出 — 確認未動**。spec-2 任務區塊(產出、worker 指示、完成定義)原封未改,pyproject 仍在其 `allowed_outputs`。spec-12 職責是**附加**三行依賴、`forbid_outputs` 擋掉其餘一切,worker 指示明令「不得刪改 spec-2 已寫的任何其他行」。無任何節點被要求重寫 spec-2 已完成的檔案。

## 新發現殘留項(非阻擋)

- **R7(建議,不阻擋)——test-12 的「未刪改 spec-2 既有內容」不是自足的機器斷言**。完成定義靠「diff 僅新增依賴行」,但(1)未列舉 spec-2 基線套件(fastapi/uvicorn/sqlalchemy/alembic/psycopg/apscheduler/httpx/pytest/pydantic-settings),故 test-12 現況只顯式驗三個「新」套件在列,**掉了 httpx 之類舊套件不會被 machine test 擋下**;(2)未驗既有版本約束是否被動;(3)「diff」預設有可靠基線,但流程未保證 per-node commit 能乾淨隔離 spec-12 的變更。**修法便宜且該做**:把 test-12 完成定義改為「斷言 spec-2 全部基線套件仍在列(列舉)＋三新套件在列」的自足子集檢查,不依賴 git diff。**判為非阻擋**:一因這正是 spec-12 focused review upgrade_trigger 顯式覆蓋的邊界,reviewer 看 diff 會抓到;二因 machine test 仍客觀守住「三套件增列且可安裝」半段。但因整個修補的存在理由就是護住 pyproject 完整性,強烈建議 gate 前或下次觸及時把此斷言釘成自足。

- **R8(觀察,不阻擋)——ownership 措辭與 spec-6/7 對稱性兩則小瑕**。(a)analysis §2 稱 spec-12「單一擁有 pyproject 依賴寫入權」,但 spec-2 的 `allowed_outputs` 仍含 pyproject——精確說法應是「spec-12 是**平行 adapter 節點之間**的單一依賴寫入者;spec-2 為其序列前手(建檔者)」。此為序列共享 ownership,平行安全不破,僅措辭略誇;**前提是引擎允許兩個序列節點共享同一 `allowed_output`(以租約非全域唯一性判非重疊)**——若引擎改採全域唯一 ownership,此解法需另議,建議凍結前確認引擎語意。(b)spec-6 未給 spec-12 依賴邊、spec-7 給了,兩者同源(TWSE/TPEx)且都多半 JSON/CSV,取捨略顯任意;因加邊成本近零、且 spec-6 有 upgrade_trigger「碰未預期依賴」的逃生口(觸發重 intake),不阻擋。若要對稱,更保守解是 spec-6 也掛 spec-12。

---

# 第二輪覆核（round 2）

**對象**：重讀 `intake-analysis.md` / `intake-tasks.md` / `intake-verification-map.md` / `intake-review-map.md` 修正後全文，逐項核對 R1~R5 與次要項是否真的落地，並查有無新矛盾／空話／隱性耦合。

## 最終 Verdict

**pass**（附一條非阻擋殘留項 R6，見下）

R1~R5 與全部次要項**都真的落地了，且不是嘴上補一句**——關鍵在於新增的約束同時被**下游 test 節點的完成定義**與 **review-map 的 upgrade_triggers** 承接，不是只塞進 worker 指示等 worker 自己記得。裝飾器方案未引入新的 `depends_on`／`allowed_outputs` 隱性耦合。R3 的「不改 depends_on」判斷站得住，且下游測試確有捕捉該順序。

## 逐項覆核

- **R1（市場／資料集覆蓋）— 已解決**。Q10 新增（analysis §5、附「先上市則觸發重 intake」的偏離處置）；analysis §1 已顯性承認倍增。spec-6/7/8/9 worker 指示與完成定義皆明講上市＋上櫃兩市場、且 spec-7 三類籌碼齊做、spec-9 三套頁面齊做。verification-map 各條 how 改為「上市＋上櫃各一 fixture」。review-map 對每支加「只做上市漏上櫃」為 upgrade_trigger。閉環完整。

- **R2（registry 佈線）— 已乾淨解決，無新耦合**。spec-4 registry 提供 `@register`＋`discover()`（pkgutil/importlib），完成定義改為只驗機制、明講「adapter 尚不存在故不要求列出真實來源」、且明令「不得手動維護清單」。spec-6~9 各在自己檔內 `@register` 自註冊。**耦合檢查**：自註冊只需 `import` registry（讀，非寫），不落新檔，故各 adapter 的 `allowed_outputs` 仍只含自己那支檔、無需擴權；spec-6~9 本就 `depends_on: [spec-3, spec-4]`，`@register` 走的正是這條既有依賴，**未新增任何 depends_on 邊**。review-map 對 spec-4 加「改回手動清單」、對各 adapter 加「未用 `@register` 自註冊」為 trigger。方案 (b) 佈線得乾淨。

- **R3（securities 先灌 / FK 順序）— 已解決，且判斷站得住**。spec-3 三張表對 `securities` 的 FK 明定於 model 說明與完成定義。spec-11 worker 指示捕捉「每次 run 先跑 spec-9 灌 securities 再跑其他源」，並明講此為 pipeline 執行層、不改 depends_on。**對設問的核實**：spec-11 本就 `depends_on` 全部四個 adapter（spec-6~9 為兄弟節點），FK 順序是「兄弟間的 run 內先後」，不影響**建置**順序，故不改 depends_on 正確；而「下游測試是否要注意此順序」——**已注意**：test-11 完成定義要求「驗 pipeline 先跑 securities 源再跑依賴 FK 的源」，test-integration 要求「斷言 securities 先落地使依 FK 的表插入成功」。順序不是只埋在 worker 指示，兩個下游 test 都當裁判。閉環完整。

- **R4（還原價回溯重算）— 已解決**。spec-11 指示明講「對每檔餵整段歷史日價序列並重寫全部還原列，而非只算當日新列」，並點出 spec-10 純函式簽名已容得下。test-11 與 test-integration 完成定義皆要求「還原價以整段歷史序列回填」。review-map spec-11 trigger 加「還原價只算當日新列未整段重算」。

- **R5（docker daemon 前提）— 已解決**。Q11 新增，附三節點（test-2/test-3/test-integration）的具體降級／blocked 方案。analysis §4 與 verification-map 皆立「環境前提」段對齊。review-map test-integration trigger 加「無法起 PG（無 docker daemon 見 Q11）」。

- **次要項 — 全部落地**。Q2 已移除自選清單、改「成交量前 N（可設定）」並明註「本期無此表」；spec-8 指示與 review-map trigger 同步。test-integration 的 depends_on 在 tasks 與 verification-map 已統一為 test-3/test-11。spec-11 補時區 Asia/Taipei 與「當日 23:59 截止、跨日視為新一輪」。

## 新發現的殘留項（非阻擋）

- **R6（建議，不阻擋）——分點 universe 的「成交量前 N」取數時點未定，埋著與 R3 同類的 run 內順序陷阱**。Q2/spec-8 將分點 universe 定為「成交量前 N（可設定）」，但**未指明 N 是依「當日」還是「前一交易日」成交量**。若依當日成交量，則同一 run 內 spec-6（daily_prices）必須先於 spec-8（broker_branch）跑完，否則 top-N 取到空／舊值→選錯 universe→分點當日缺洞（§3 全案最高成本失效）。spec-11 目前只捕捉了 securities 先灌一條執行順序，未捕捉這條。**判為非阻擋**：一因「可設定」措辭本就容得下「用前一交易日成交量（DB 既有、無序依賴）」或「靜態清單」的安全解讀，非必然失效（不同於 R3 的 FK 為確定性違反）；二因修法只需在 spec-8/spec-11 指示或 Q2 補一句釘死取數時點，無結構重炒。建議 intake 下次觸及時、或人類 gate 一併釘死；不擋本次凍結。

- 純美觀 nit（不影響凍結）：analysis §6 統計把 review depth 寫成「focused ×4（spec-2/6/7/9 ＋ test-integration）」，若把 test-integration 計入 focused 實為 5 個。不影響 manifest 收斂。

---

# 第一輪記錄（round 1）

## Verdict

**needs-rework**

整體品質高：範圍忠實、雙價格制拆解正確、驗證誠實邊界劃得清楚、依賴圖大致合理。但存在**三個會在下游實作/整合期真實爆掉的縫**（registry 佈線無主、securities/FK 灌入順序未捕捉、上市/上櫃雙格式未被承認），加上兩個應在人類 gate 前補的前提缺口。這些多屬「補指示 / 補開放問題 / 指派佈線 owner」，非結構重炒，但屬於「拿去執行後會出事」等級，故建議打回補正後再上人類 gate。

---

## 逐項檢查

### 1. 範圍忠實度 — 通過（但有一個範圍模糊未被承認，見 R1）

- requirement.md 明列四類資料源（日價量／籌碼／券商分點／除權息股本基本資料）→ 分別對應 spec-6 / spec-7 / spec-8 / spec-9，**無遺漏**。
- 明確排除項（K 線頁、指標、篩選引擎、分點 UI、策略掃描、Telegram 實際推播、前端、回測、異常掃描）**未被誤拆入**。spec-5 正確地只做 Notifier ABC＋log stub＋Telegram shell（requirement.md L14/L21、design §8）。
- Docker Compose、APScheduler、雙價格制、user 概念、部署搬遷均有對應任務。
- **但**：design §3 表列來源皆為「證交所/櫃買」兩市場，requirement.md 未排除上櫃 → 上市＋上櫃都在範圍內。intake 未在任何處承認「每個 adapter 實為兩市場兩格式」，也未列為開放問題（見 R1）。

### 2. 架構原則忠實度（§2）— 通過

- 原則 1（資料層/應用層分離）：spec-4 抽象契約＋spec-6~9 各自獨立 adapter 模組，落實於任務拆解與 ownership 邊界，非嘴上提到。
- 原則 2（user 不寫死）：spec-3 明列 `users` 表＋`user_id` FK 佔位、worker 指示「即使只有一筆 user 也不得寫死」（對應 design §2 原則 2）。
- 原則 3（thick server）：本期以後端 ingestion 為主，無前端邏輯下沉問題，符合。

### 3. §3 分點注意事項 — 通過

逐條對應到具體任務而非空泛帶過：只抓當日（spec-8 worker 指示「只抓當日」）、錯過即永久缺洞（spec-8/spec-11 均述及）、節流（spec-8 節流器＋Q5 預設 3–5s）、驗證碼 OCR（`CaptchaSolver`＋Q1 ddddocr）、FinMind 替換縫（`BrokerBranchSource` 於 spec-4 定義、spec-8 實作）。全案維運熱點正確升為 tier high＋full review。

### 4. §7 雙價格制 — 大致通過（但 spec-10↔spec-11 回溯重算語意未明，見 R4）

- schema 同存原始價與還原價：spec-3 `daily_prices`「同時容納原始價與還原價（雙欄或 raw+adj_factor）」符合 §7 L79。
- 還原係數計算獨立成可驗證任務：spec-10 從 spec-9（抓取）切開，明列為「純數學」、full review、對已知除權息事件做人工核算比對。切分理由（數學 vs 解析、fixture 不同）成立。
- **缺口**：§7 的還原價本質是「新除權息事件會回溯改寫該股全部歷史還原價」。spec-10 簽名（吃整段序列→回填）容得下，但 spec-11「算還原價」步驟未明講每次 run 要**餵整段歷史並重寫全部還原列**，而非只算新到的當日列。worker 若只對新列算還原，會得出錯誤還原線（見 R4）。

### 5. 驗證地圖誠實度 — 大致通過（一個環境前提未確認，見 R5）

- 誠實邊界劃得好：所有 adapter 的 machine 驗收只驗「對 fixture 的解析與正規化」，明確把「真打外站／真驗證碼辨識」排除在必要條件外（analysis §4、verification-map 共同前提、spec-8 reason）。這正確避免了 flaky／不可重現的外網依賴，是本計畫最強的一環。
- spec-10 純數學、spec-11 mock 時鐘重試狀態機——皆為可重現客觀裁判。
- **缺口**：spec-2（`docker compose config`）、spec-3 與 test-integration（testcontainers/compose 起真 PG）都**隱含測試環境有可用的 docker daemon**。這是非平凡前提，開放問題 Q3 只談「用 compose 內 PG」，未確認執行 machine test 的 runtime 是否有 docker daemon。若無，這三個 machine 節點根本跑不起來（見 R5）。

### 6. review map 合理性 — 通過

- 唯一的 `defer-until-signal`（spec-5）確實低風險、ownership 清楚（獨立通知模組）、有可靠 unit test、僅排程消費，且列了合理 upgrade_triggers。判斷成立。
- 高風險任務（spec-3/8/10/11）皆為 full，升級條件具體。無高風險被低估。

### 7. 依賴圖與平行度 — 大致通過（但漏一條跨 adapter 的資料先後依賴，見 R3）

- 檔案 ownership 不重疊：spec-6~9 各擁一支 adapter 檔、互列 forbid；spec-10 擁 `pricing/`、spec-11 擁 `ingestion/`。宣稱可平行成立。
- **缺口 A（registry 佈線無主，見 R2）**：spec-4 擁 `adapters/registry.py`、`__init__.py`，且**在具體 adapter 尚不存在時**就寫完 registry。spec-6~9 的 allowed_outputs 是白名單、**只含自己那支 adapter 檔**，無法寫 registry.py 也無法寫 adapters/`__init__`。於是「把四個 adapter 註冊進 registry」這件事**沒有任何任務擁有**。若 registry 是手動清單→永遠為空；spec-11 遍歷到空 registry，整合期才爆。intake 未指定自動發現（pkgutil/importlib 掃描）機制。
- **缺口 B（securities 先灌順序，見 R3）**:Q2 稱「universe 取 securities 表全上市櫃」、spec-8 universe 需查 securities；而 securities 由 spec-9 落地。若 `daily_prices`/`chips`/`broker_branch_trades` 對 `securities` 有 FK，則 pipeline 必須**先跑 spec-9 灌 securities 再跑其他源**，否則插入違反 FK。此跨源先後依賴未反映在 spec-11 指示，也未在 depends_on 表達（adapter 解析層無依賴，但 pipeline 執行層有）。

### 8. 開放問題品質 — 大致通過（但漏兩個關鍵未知）

- Q1~Q9 涵蓋了 OCR 方案、股票範圍、PG 來源、金鑰、節流、回補、Telegram 範圍、遷移工具、目錄佈局——多為會卡實作/驗收的真未知，建議答案合理。
- **遺漏**：
  - 上市/上櫃雙市場覆蓋與其倍增的 parser 工作量（R1）——這是應在人類 gate 前定案的範圍問題。
  - 執行 machine test 的環境是否具 docker daemon（R5）。
  - 次要：Q2 建議答案引用「自選清單」作 universe 來源，但自選股是 §6 第 4 項（後期）功能，本期無此資料/表；分點 universe 本期實際只能是「成交量前 N（可設定）」。建議修掉 Q2 對自選清單的引用以免 worker 去找不存在的表。

### 9. 任務粒度 — 有疑慮（worker 不得再拆，唯一退路是重 intake）

- spec-6/7/8/9 每支 adapter 皆隱含「上市（證交所）＋上櫃（櫃買）兩格式」，且 spec-7 內含三大法人/融資券/借券三套資料、spec-9 內含除權息/股本/基本資料三套頁面。design §3 把它們列為單列來源，但實作是多格式多 parser。worker 不能再拆，一旦某支 adapter 的實際格式差異超出單次容量，唯一退路是打回重 intake，成本高。
  - 這不必然是致命——一支模組寫多個 parse 純函式仍屬合理粒度；但 intake 未承認此倍增、也未在 worker 指示界定「本期上櫃是否納入 / 三套資料是否可分批」，把判斷風險推給 worker。至少應在 spec-6/7/8/9 指示明講市場與資料集覆蓋範圍（與 R1 同源）。

---

## 必須修正項（needs-rework 清單）

- **R1（範圍/粒度）**：明確定案並寫入 spec-6/7/8/9 指示——本期 adapter 是否含上櫃（櫃買）？每支的多資料集（籌碼三類、除權息/股本/基本資料）覆蓋範圍為何？並補一條開放問題交人類 gate 定奪。這同時消解第 1、9 項疑慮。
- **R2（registry 佈線無主）**：指定 adapter 註冊/發現機制。要嘛 spec-4 的 registry 用 pkgutil/importlib 對 `adapters` 套件**執行期自動發現**（並把此寫進 spec-4 worker 指示與完成定義，且完成定義不能再要求「列出已註冊來源」因當下為空），要嘛明確指派一個任務擁有「把四 adapter 掛進 registry」的佈線 output（例如允許各 adapter 在自己檔內用 `@register` 裝飾器，並讓 spec-4 的 registry 負責掃描觸發）。現況白名單使無人能佈線。
- **R3（securities 先灌 / FK 順序）**：在 spec-3 明確 `daily_prices`/`chips`/`broker_branch_trades` 對 `securities` 的關聯是否為 FK；若是，於 spec-11 指示與（必要時）depends_on 捕捉「pipeline 每次 run 需先跑基本資料源灌 securities，再跑其他源」的執行順序，否則整合期 FK 插入失敗。

## 建議修正項（不阻擋，但強烈建議一併補）

- **R4（還原價回溯重算）**：在 spec-11 指示明講「算還原價」時對每檔餵**整段歷史序列**並重寫全部還原列（新除權息事件會回溯改寫歷史還原價），避免 worker 只算當日新列而得出錯誤還原線。spec-10 純函式簽名已容得下，缺的是 pipeline 端的呼叫語意。
- **R5（docker daemon 前提）**:補開放問題確認執行 machine test 的 runtime 是否具可用 docker daemon（test-2 的 `docker compose config`、test-3 與 test-integration 的 testcontainers 皆依賴之）；若不保證，需給替代裁判或標記該節點在無 daemon 環境降級。
- 次要：修掉 Q2 建議答案對「自選清單」的引用（本期無此表）；統一 test-integration 的 depends_on 表述（tasks 寫 test-3/test-11，verification-map 寫 spec-3/spec-11）;spec-11 補「傍晚」的時區（Asia/Taipei）與當日重試截止條件。
