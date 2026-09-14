# 協作與接手狀態

本文件只保存目前角色、接手與待辦。角色／freeze／索引／Git 流程及暫存政策以 [AGENTS](../AGENTS.md) 為準，產品狀態以 [ROADMAP](ROADMAP.md) 為準。

## 目前狀態（2026-09-14）

- R34 已完成有限 worker capture review，來源與文件提交為 `87b8429`。新暫存政策提交為 `69f62cf`；兩者不是 R0 或完整 B2 完成。
- R35 統籌已正式 ACK 接手；本次 task readback 顯示其最新 turn 中斷、目前 idle，三個角色仍只有初始化 ACK，未取得調查交付。
- 本次只依使用者要求精簡文件，不恢復、派工或替 R35 宣稱執行完成。恢復時先核對下列四個既有 ID 與最新使用者指示，不重建角色，也不讓已交接的 R34 重新派工。

| R35 角色 | 既有 task ID | 本次核對狀態 |
| --- | --- | --- |
| 統籌 | `01a0a016-ca13-7af0-9418-2ef10fd0a880` | 接手 ACK 已完成；最新 turn interrupted，idle。 |
| C035 程式 | `01a0a017-0004-7af2-8a0d-986e19e46c90` | 初始化 ACK，等待正式分派。 |
| D037 文件 | `01a0a017-38c1-7d30-a626-52ae5e99db3b` | 初始化 ACK，等待正式分派。 |
| I074 索引／Git | `01a0a017-809c-7ba0-a6e5-280c5e96b389` | 初始化 ACK，等待輪末 freeze。 |

R34 舊統籌為 `01a09aff-24b9-7f63-bca5-f2e4473c9759`，只補歷史資訊。

## 接續範圍

R35 候選是群組成員 canonical identity：目前內部 member metrics 有 `instrument_id`，保存的 `member_returns` 與 signal lookup 卻以 symbol 關聯。先用達 `MIN_GROUP_MEMBERS` 的跨市場同 symbol 案例，經實際群組計算確認可達歧義及相容性，再決定最小修正；不能把候選當成已證缺陷或已修復。

- 統籌核定範圍、完成狀態與驗收；程式先交調查，實作前由統籌核定契約。
- 文件角色獨立核對身分、來源與版本相容性，並依統籌 review 結論維護受影響契約及本接手紀錄；索引角色等文件交付接受與 freeze 後工作。
- 證據直接回覆 task，必要長期契約更新既有文件；不延續舊 external-review、manifest 或 Temp 交接環境。

## 必須帶入的限制

R34 只在 explicit owned research DB 保存實際 legacy evaluator 輸入；default worker／backtest／API／UI 不啟用。SignalArtifact／來源／availability／decision-time bridge、完整 Signal replay、PIT 與 B7 仍缺；群組來源尚未證明 exchange-aware。契約見 [Worker capture](WORKER_ANALYSIS_CAPTURE.md)。

R34 final targeted 是 52 passed；2,436-pass full suite 對應較早 capture guard，不能互換。當輪正式 DB 被其他程序占用，未取得 byte hash，不能宣稱正式 DB bytes unchanged 已驗。這些是既有證據邊界，不是本次新測試結果。

## 歷史與維護

R01–R34 的原分派、role IDs、驗收矩陣、失敗修正史及索引 receipt 敘事，可用 `git show 69f62cf:docs/TASK_COORDINATION.md` 取閱。歷史禁止 commit、Temp 依賴或尚待 review 的指令不覆蓋現行 AGENTS；Git 也不恢復已刪除的外部附件。

後續每輪由文件角色更新本文件的現況與待辦，不重複追加整輪逐步紀錄。交接只寫已完成及驗收邊界、尚缺項目、下一步與其依賴／完成條件；詳細契約用連結。本次文件維護的 freeze、索引與 commit receipt 留在本 task 回覆。
