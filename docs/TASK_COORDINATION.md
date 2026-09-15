# 協作與接手狀態

本文件只保存目前角色、接手與待辦。角色／freeze／索引／Git 流程及暫存政策以 [AGENTS](../AGENTS.md) 為準，產品狀態以 [ROADMAP](ROADMAP.md) 為準。

## 目前狀態（2026-09-15）

- R37 統籌已接受 candidate backfill／coverage typed scope、文件、索引與本地提交 `14b267662fdb207c10f003b7976c7a55f06c5045`；七個核准檔案已提交，提交後工作樹為 clean。Typed 以 DB-local ID＋pair 精確納入 active 列，legacy 保留 active 同 symbol exchange 的安全擴大；這不是 decision selection。詳細規則見[產業分類 §9.5](INDUSTRY_CLASSIFICATION.md#95-backfillcoverage-的候選納入契約)。
- R38 統籌已有限接受 public score-source typed candidate 的 API／UI、文件與索引，並完成本地提交 `f0f09b83fd26cdb0d90da5ac70d76f4282916a3a`；提交後工作樹為 clean。Typed public ID 使用十進位字串與 exact exchange＋symbol，來源日與目前 member 日期分開，legacy 只留無連結文字；詳細規則見[產業分類 §9.6](INDUSTRY_CLASSIFICATION.md#96-public-candidate-的-source-day-身分展示契約)。
- R39 統籌已有限接受 R0-B2 SignalArtifact bridge A 的 source／graph 缺口 review；本輪沒有程式變更。下一個 B 窄 adapter 仍是提案，待後續統籌核 I/O、time、binding 與磁碟驗收；未授權 consumer 或預設切換。
- R36 有限驗收涵蓋 5 個有效成員的 top 4、同 symbol 跨市場、來源日歧義、後日退出／加入、正反插入順序、malformed／legacy、其他 action buckets 與六個既有 targeted regressions；不是 full backend、actions cursor／效能、PIT、backfill 或 API typed 驗收。詳細規則見[產業分類 §9](INDUSTRY_CLASSIFICATION.md#9-群組候選的身分契約)。

### R39 後的獨立 UI 文案維護（非 ROADMAP round）

這項下一輪前的維護只處理日常繁中文案、ETF／族群代碼中文顯示、空數值、法人命名、表外單位、未知幣別及官方券商分點查詢入口；不改 R39 驗收，不恢復或啟動下一個 ROADMAP round。統籌已有限接受實作與文件並確認 freeze；最終索引與本地提交 receipt 以本 task 回覆為準，不回寫 commit hash。

| 角色 | task ID | 本次核對狀態 |
| --- | --- | --- |
| 統籌 | `01a0a59b-e010-7af1-955c-3ba6fbbdf247`（`/root`） | 已有限接受實作、具名唯讀 browser review 與文件，並核定 freeze；交索引／Git 結案。 |
| 程式 | `/root/ui_implementation` | 6 份記憶體前端測試、final build 與 diff check 均 exit 0；11 個前端檔已 freeze 並獲統籌接受，未改 API、DB 或 collector。 |
| 文件 | `/root/ui_docs` | 七份受影響契約、驗收邊界與交接已獲統籌接受並 freeze。 |
| 索引／Git | `/root/ui_index_git` | 輪初唯讀盤點已交付；依 freeze 更新受影響分區、驗 coverage 並提交核准檔案，最終 receipt 留在 task 回覆。 |

| R39 角色 | task ID | 本次核對狀態 |
| --- | --- | --- |
| 統籌 | `01a0a0c9-735d-79a3-b7ce-89b13400fb24` | 已有限接受 C039 的 A 調查；待文件交付後核整輪 freeze。 |
| C039 程式 | `01a0a0ca-274b-7a41-bbf2-7a42e806c792` | Source／graph 有限調查已接受並 freeze；沒有程式或 runtime/store 驗收。 |
| D041 文件 | `01a0a0ca-30d3-7371-ad32-c4e99c5463b5` | 收斂五份受影響契約與接手；待統籌接受並 freeze。 |
| I078 索引／Git | `01a0a0ca-3a87-7193-b8f2-c3c692cee286` | 輪末才更新受影響分區、驗 coverage 並提交統籌核准檔案。 |

R38 舊統籌為 `01a0a0b1-7027-7441-b388-68a167d0bafd`，只補歷史資訊。I078 誤建且已停止的 child 不是 R39 角色，不派工，也不列入維護清單。

## 接續範圍

R35 已有限 review member-return，R36 已有限 review candidate producer／decision lookup，R37 已有限 review backfill／coverage inclusion，R38 已有限 review public score-source display。四者語意與驗收邊界不可互換，完整規則見[產業分類契約 §8–9.6](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)；schema／歷史批次回算仍未完成。

- R37 有限 review 只涵蓋記憶體 ORM readback 後的 resolver → plan → scoped adapter 與 direct coverage function；不是 HTTP、完整 targeted backfill、磁碟持久化、全 backend、效能、正式 DB、availability 或 PIT 驗收。既有 run 的 `metadata.target_instruments` snapshot 不重算。
- R38 有限 review 只接受 public score-source typed projection、exact market link、來源日／member 日期分離及具名記憶體／in-process／React SSR 驗證；不是 browser、full backend、正式 DB、效能、PIT 或歷史回算，其他 `instrument.id` 的 numeric API 也未改。
- Bridge A 已有限 review；下一步只核 explicit stable current capture path／hash＋attempt／selected ordinal＋new aware research decision→candidate 的窄 adapter。Candidate 與 caller save 分離；B 未實作，不預核 consumer、paired replay 或預設切換。依賴與完成條件見[執行清單 R0-B2](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr)。
- 文件交付由統籌接受並 freeze 後，索引角色更新受影響分區、驗 coverage 並只提交核准檔案。
- 證據直接回覆 task，必要長期契約更新既有文件；不延續舊 external-review、manifest 或 Temp 交接環境。

## 必須帶入的限制

R34 只在 explicit owned research DB 保存實際 legacy evaluator 輸入；default worker／backtest／API／UI 不啟用。Owner source SHA 不等於 attempt 後 research DB 或 exact input；R39 A 只核出候選映射與缺口，adapter、來源／availability、歷史 decision、完整 Signal replay、PIT 與 B7 仍缺。契約見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選)。

R34 final targeted 是 52 passed；2,436-pass full suite 對應較早 capture guard，不能互換。當輪正式 DB 被其他程序占用，未取得 byte hash，不能宣稱正式 DB bytes unchanged 已驗。這些是既有證據邊界，不是本次新測試結果。

## 歷史與維護

R01–R34 的原分派、role IDs、驗收矩陣、失敗修正史及索引 receipt 敘事，可用 `git show 69f62cf:docs/TASK_COORDINATION.md` 取閱。歷史禁止 commit、Temp 依賴或尚待 review 的指令不覆蓋現行 AGENTS；Git 也不恢復已刪除的外部附件。

後續每輪由文件角色更新本文件的現況與待辦，不重複追加整輪逐步紀錄。交接只寫已完成及驗收邊界、尚缺項目、下一步與其依賴／完成條件；詳細契約用連結。本次文件維護的 freeze、索引與 commit receipt 留在本 task 回覆。
