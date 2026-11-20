# #868 review 必修 1：正式 DB 副本上 X4 的基本面覆蓋（2026-11-20）

依 [review 7035385605](https://github.com/YiCheng0608/stock-lab/pull/871#issuecomment-7035385605)。

- **副本**：`copy_db.py` 唯讀複製到 Docker volume `task-868_copy`（`copy_db.json`）。
  - 資料到 2026-11-19，alembic `0033_mainstream_lists`，quick_check ok。
  - 量完已刪副本並讀回。
- **腳本**：`x4_coverage.py`，唯讀。
  - 沿用 `explore_research.load_context`（暖機 730 日）、`value_of`、`passes`、`used_features`，以及 `feature_evidence._quarter_eps`。
  - 量副本最後 5 個交易日。
  - 命令：`docker run --rm --network none -v task-868_copy:/copy:ro -v <本目錄>:/out -v <worktree>:/app:ro stock-lab-backend:v1.2.71 python -B /out/x4_coverage.py /copy/stock.db /tmp`
- **輸出**：`coverage.json`。

## 2026-11-19（副本最新交易日）

| 量 | 檔數 | 缺值比例 |
| --- | ---: | ---: |
| 母體 | 582 | — |
| `revenue_yoy` 有值 | 578 | 0.7% |
| `eps_growth_yield` 有值（最新一季與去年同季都有） | 578 | 0.7% |
| `eps_yield_raw` 有值 | 579 | 0.5% |
| 兩個條件都 > 0（會進名單） | 337 | — |

- 母體成員最新已知的一季：568 檔是 2026Q3（2026-09-30），12 檔是 2026Q2。
- 11-13～11-19 這 5 天，會進名單的都是 336～340 檔，比 X4 的 N＝20 多得多。

## 對照 #867（`pr-assets/867@f924f6ee`，各報告「資料覆蓋」的缺值比例）

| 期間 | `revenue_yoy` | `eps_growth_yield` | `eps_yield_raw` |
| --- | ---: | ---: | ---: |
| 探索段 2019 年（`explore-x/X4/summary.md`） | 4.2% | 1.3% | 0.2% |
| 驗證段 2023 年（`validate-x4/X4/summary.md`） | 1.5% | 0.9% | 0.3% |
| 驗證段 2024 年 | 1.0% | 0.8% | 0.4% |
| **正式副本 2026-11-19** | **0.7%** | **0.7%** | **0.5%** |

#867 的報告只列缺值比例，沒有列「兩個條件都 > 0」的檔數，所以這一欄沒有對照。研究 DB（`stock-lab-research`）在 #864、#866 使用中，這次沒有讀。
