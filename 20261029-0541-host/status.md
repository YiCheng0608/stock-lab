## verify 檢查結果（2026-10-29 05:41 台北）

- 程式：`task/339-docker-local-checks` @ `612cfe4`（未 commit：.claude/skills/verify-stock-lab/SKILL.md、AGENTS.md、backend/Dockerfile、backend/tests/test_coordinator_scripts.py、docs/GITHUB_WORKFLOW.md、docs/OPERATIONS.md、tools/ci/test_checks.py、tools/ops/dispatch.sh）
- API `http://127.0.0.1:56038`、前端 `http://127.0.0.1:56039`、DB `stock.db`
- 個股 E／S：TWSE 2468，今日榜 #1 族群「資訊服務」的第一個成員
- 48 項：通過 45、失敗 0、無法判定 3、已知失敗 0；耗時 117 秒

### 人工檢查樣本（依 features 規則抽樣，判讀見 SKILL 真資料模式第 3 步）

| 檢查 | 樣本 |
| --- | --- |
| T10 | 3 筆，`manual/T10.json` |
| N7 | 5 筆，`manual/N7.json` |
| N8 | 5 筆，`manual/N8.json` |

### 今日 `/`：通過

| 檢查 | 結果 |
| --- | --- |
| T1 | 通過 |
| T2 | 通過 |
| T3 | 通過 |
| T4 | 通過 |
| T5 | 通過 |
| T6 | 通過 |
| T7 | 通過 |
| T8 | 通過 |
| T9 | 通過 |
| T11 | 通過 |
| T12 | 通過 |

### 新聞 `/news`：通過

| 檢查 | 結果 |
| --- | --- |
| N1 | 通過 |
| N2 | 通過 |
| N3 | 通過 |
| N4 | 通過 |
| N5 | 通過 |
| N6 | 通過 |

### 族群 `/themes`：通過

| 檢查 | 結果 |
| --- | --- |
| G1 | 通過 |
| G2 | 通過 |
| G3 | 通過 |
| G4 | 通過 |
| G5 | 通過 |
| G6 | 通過 |
| G7 | 通過 |
| G8 | 通過 |

### 個股 `/stocks`：通過

| 檢查 | 結果 |
| --- | --- |
| S1 | 通過 |
| S2 | 通過 |
| S3 | 通過 |
| S4 | 通過 |
| S5 | 通過 |
| S10 | 通過 |
| S6 | 通過 |
| S7 | 通過 |
| S8 | 通過 |
| S9 | 通過 |

### 行動 `/actions`：無法判定

| 檢查 | 結果 |
| --- | --- |
| A1 | 通過 |
| A2 | 通過 |
| A3 | 通過 |
| A4 | 通過 |
| A5 | 通過 |
| A6 | 通過 |
| A7 | 通過 |
| A8 | 通過 |
| A9 | 通過 |
| A10 | 通過 |
| A11 | 無法判定 |
| A12 | 無法判定 |
| A13 | 無法判定 |
