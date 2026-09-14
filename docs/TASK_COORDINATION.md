# 協作與接手狀態

本文件只保存目前角色、接手與待辦。角色／freeze／索引／Git 流程及暫存政策以 [AGENTS](../AGENTS.md) 為準，產品狀態以 [ROADMAP](ROADMAP.md) 為準。

## 目前狀態（2026-09-14）

- R35 的 member-return identity 已通過有限 review：新 payload 以 `instrument_id` 精確連結，舊列只在 as-of 有效成員身分唯一時相容；來源、文件、索引與本地提交 `d16ed43` 已由統籌接受。既有 rows 未回算，原 upsert 行為不變。
- R36 統籌已有限接受 candidate typed producer、decision lookup、新 focused suite 與五份受影響文件；程式與文件均已 freeze，待 I075 索引與 commit receipt。
- 有限驗收涵蓋 5 個有效成員的 top 4、同 symbol 跨市場、來源日歧義、後日退出／加入、正反插入順序、malformed／legacy、其他 action buckets 與六個既有 targeted regressions；不是 full backend、actions cursor／效能、PIT、backfill 或 API typed 驗收。詳細規則見[產業分類 §9](INDUSTRY_CLASSIFICATION.md#9-群組候選的身分契約)。

| R36 角色 | task ID | 本次核對狀態 |
| --- | --- | --- |
| 統籌 | `01a0a085-e043-7c92-bb0c-3075d9302860` | 已有限接受程式與文件並 freeze；待 I075 索引與 commit receipt。 |
| C036 程式 | `01a0a086-1ecc-7a70-82ae-8c2f75fc422f` | Producer、decision 與 candidate identity test 已有限接受；三個檔案 freeze。 |
| D038 文件 | `01a0a086-69ac-7ba0-815b-6428cd0769ed` | 五份文件已接受並 freeze；停止來源寫入。 |
| I075 索引／Git | `01a0a086-a18d-7050-8a77-9558defd37c6` | 等程式與文件交付接受、freeze 後更新索引、驗 coverage 並提交。 |

R35 舊統籌為 `01a0a016-ca13-7af0-9418-2ef10fd0a880`，只補歷史資訊。已停止的重複 task 不是 R36 角色，不列入維護清單。

## 接續範圍

R35 已有限 review member-return producer、worker lookup、legacy ambiguity fail-closed 與 Signal identity evidence，詳細規則見[產業分類契約 §8](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。R36 已有限 review `candidate_symbols`／decision lookup：producer 新增 typed top 4 與相容字串投影；decision 先在 score date 證明來源身分，再於 requested as-of 只保留仍有效的同一 ID。Malformed typed source 整個 score fail closed，legacy 以來源日唯一性保守相容；API／UI／backfill／schema／歷史批次回算不在本批。

- 文件交付由統籌接受並 freeze 後，索引角色更新受影響分區、驗 coverage 並只提交核准檔案；R36 在 receipt 前仍未結案。
- 下一輪先調查 backfill `_candidate_instrument_keys` 的 typed 相容、所有 consumer、source-date／inactive 與 ID 證明，調查後再核最小修正；legacy backfill 安全擴大 scope 不得混作 decision selection。API typed 輸出另列後續。
- 證據直接回覆 task，必要長期契約更新既有文件；不延續舊 external-review、manifest 或 Temp 交接環境。

## 必須帶入的限制

R34 只在 explicit owned research DB 保存實際 legacy evaluator 輸入；default worker／backtest／API／UI 不啟用。SignalArtifact／來源／availability／decision-time bridge、完整 Signal replay、PIT 與 B7 仍缺；群組來源尚未證明 exchange-aware。契約見 [Worker capture](WORKER_ANALYSIS_CAPTURE.md)。

R34 final targeted 是 52 passed；2,436-pass full suite 對應較早 capture guard，不能互換。當輪正式 DB 被其他程序占用，未取得 byte hash，不能宣稱正式 DB bytes unchanged 已驗。這些是既有證據邊界，不是本次新測試結果。

## 歷史與維護

R01–R34 的原分派、role IDs、驗收矩陣、失敗修正史及索引 receipt 敘事，可用 `git show 69f62cf:docs/TASK_COORDINATION.md` 取閱。歷史禁止 commit、Temp 依賴或尚待 review 的指令不覆蓋現行 AGENTS；Git 也不恢復已刪除的外部附件。

後續每輪由文件角色更新本文件的現況與待辦，不重複追加整輪逐步紀錄。交接只寫已完成及驗收邊界、尚缺項目、下一步與其依賴／完成條件；詳細契約用連結。本次文件維護的 freeze、索引與 commit receipt 留在本 task 回覆。
