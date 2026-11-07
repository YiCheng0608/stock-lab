<!-- owns: 模板清單 -->
# 模板

協作用的模板都在這個目錄（#550 從 `.github/` 搬來）。GitHub 網頁不會自動帶入這裡的模板：建 Issue 與開 PR 一律複製模板填好，再用 `gh issue create --body-file`／`gh pr create --body-file`。

| 模板 | 用在 | 誰填 |
| --- | --- | --- |
| [issue-task.md](issue-task.md) | 可直接開工的任務 Issue（[任務流程](../WORKFLOW.md#任務流程)第 1 步） | 統籌 |
| [issue-feature.md](issue-feature.md) | 需要多個任務才能完成的功能母單 | 統籌 |
| [issue-candidate.md](issue-candidate.md) | 還沒排程的想法或缺陷 | 統籌 |
| [task-file.md](task-file.md) | 派工時給工程師的任務檔 `$HOME/t<issue>/task/task.md`（[任務流程](../WORKFLOW.md#任務流程)第 2 步） | 統籌 |
| [pull-request.md](pull-request.md) | PR 本文（[任務流程](../WORKFLOW.md#任務流程)第 5 步；CI 的 [PR 檢查規則](../WORKFLOW.md#review-與合併)會讀） | 工程師 |

模板首行的 owns 註解是文件檢查用的（`tools/ci/checks.py`），複製時可以留著。留言的格式不在這裡，見 [留言類型](../WORKFLOW.md#留言類型)。
