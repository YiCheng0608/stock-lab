# 協作與接手狀態

本文件只保存目前角色、接手與待辦。角色／freeze／索引／Git 流程及暫存政策以 [AGENTS](../AGENTS.md) 為準，產品狀態以 [ROADMAP](ROADMAP.md) 為準。

## 目前狀態（2026-09-14）

- R34 已完成有限 worker capture review，來源與文件提交為 `87b8429`。新暫存政策提交為 `69f62cf`；兩者不是 R0 或完整 B2 完成。
- R35 統籌已正式接手，使用者已指示開始；四個既有角色 ID 已核對並沿用，不重建角色。
- C035-A 已證明 member-return 的 symbol-only lookup 可錯綁；C035-B 的新 payload identity、worker lookup、legacy fail-closed 與 Signal evidence 已通過有限 review，程式來源已 freeze。
- D037 契約與交接已由統籌接受，程式與文件均 freeze；`candidate_symbols`／decision lookup 是下一個獨立缺口，本輪未改 API／decision／backfill。
- I074 依核定流程更新受影響索引、驗 coverage 並提交，統籌再核對 commit；目前尚未取得索引或 commit receipt。

| R35 角色 | 既有 task ID | 本次核對狀態 |
| --- | --- | --- |
| 統籌 | `01a0a016-ca13-7af0-9418-2ef10fd0a880` | 已接受有限功能與文件，核定程式／文件 freeze；待索引與 commit receipt。 |
| C035 程式 | `01a0a017-0004-7af2-8a0d-986e19e46c90` | C035-A／B 已有限接受；程式來源 freeze。 |
| D037 文件 | `01a0a017-38c1-7d30-a626-52ae5e99db3b` | 契約與交接已接受；文件 freeze。 |
| I074 索引／Git | `01a0a017-809c-7ba0-a6e5-280c5e96b389` | 輪末更新索引、驗 coverage 並提交；尚待 receipt。 |

R34 舊統籌為 `01a09aff-24b9-7f63-bca5-f2e4473c9759`，只補歷史資訊。

## 接續範圍

R35 已有限 review member-return producer、worker lookup、legacy ambiguity fail-closed 與 Signal identity evidence；新列以 `instrument_id` 精確連結，舊列只有 as-of 有效成員身分可唯一證明時才相容讀取。既有 rows 未批次回算，原 upsert 行為不變；`candidate_symbols` 及其 decision lookup 保留為下一個獨立缺口，詳細規則見[產業分類契約 §8](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。

- 統籌核定範圍、完成狀態與驗收；程式先交調查，實作前由統籌核定契約。
- 文件角色獨立核對身分、來源與版本相容性，並依統籌 review 結論維護受影響契約及本接手紀錄；索引角色等文件交付接受與 freeze 後工作。
- 證據直接回覆 task，必要長期契約更新既有文件；不延續舊 external-review、manifest 或 Temp 交接環境。

## 必須帶入的限制

R34 只在 explicit owned research DB 保存實際 legacy evaluator 輸入；default worker／backtest／API／UI 不啟用。SignalArtifact／來源／availability／decision-time bridge、完整 Signal replay、PIT 與 B7 仍缺；群組來源尚未證明 exchange-aware。契約見 [Worker capture](WORKER_ANALYSIS_CAPTURE.md)。

R34 final targeted 是 52 passed；2,436-pass full suite 對應較早 capture guard，不能互換。當輪正式 DB 被其他程序占用，未取得 byte hash，不能宣稱正式 DB bytes unchanged 已驗。這些是既有證據邊界，不是本次新測試結果。

## 歷史與維護

R01–R34 的原分派、role IDs、驗收矩陣、失敗修正史及索引 receipt 敘事，可用 `git show 69f62cf:docs/TASK_COORDINATION.md` 取閱。歷史禁止 commit、Temp 依賴或尚待 review 的指令不覆蓋現行 AGENTS；Git 也不恢復已刪除的外部附件。

後續每輪由文件角色更新本文件的現況與待辦，不重複追加整輪逐步紀錄。交接只寫已完成及驗收邊界、尚缺項目、下一步與其依賴／完成條件；詳細契約用連結。本次文件維護的 freeze、索引與 commit receipt 留在本 task 回覆。
