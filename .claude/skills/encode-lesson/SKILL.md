---
name: encode-lesson
description: 同類錯誤第二次發生時，把它編成會失敗的檢查（架構、型別、lint／CI、測試，最後才是文件），並更新 AGENTS「規則與強制手段」對照表。輸入一個 Issue／PR 連結與錯誤描述。
---

# encode-lesson

用在[工作手冊](../../../docs/GITHUB_WORKFLOW.md#任務流程)第 6 步：同類錯誤第二次發生時另建一張 `[任務]`，照下列五步處理。輸入是一個 Issue／PR 連結與一句錯誤描述，例如「#37：`checks.py repository` 在 `--no-commit` 合併時檢查合併前的 HEAD」。

五步的產出都寫進 PR 本文的「先例」「選層」「紅／綠」三節與 AGENTS 對照表；Issue 只留連結。

## 1. 找同類先例

在 repo 根目錄查 commit、Issue 與留言，把關鍵字換成這次錯誤的指令、檔名或錯誤訊息：

```bash
git log --all --oneline -i --grep="<關鍵字>"
gh issue list --state all --search "<關鍵字>" --limit 30 --json number,title
gh api --paginate "repos/YiCheng0608/stock-lab/issues/comments?per_page=100" \
  --jq '.[] | select(.body | test("<正規式>")) | "\(.html_url) \(.created_at)"'
```

再查使用者記憶檔（`~/.claude/projects/*/memory/`）有沒有同一件事。只出現一次就停：在原 Issue 留言記下「第一次」與連結，不寫檢查。

產出：先例清單，每列一次發生，連結要能點開。

```markdown
| 日期 | 連結 | 發生了什麼 | 當時怎麼處理 |
| --- | --- | --- | --- |
| 2026-10-13 | #9 issuecomment-6139175394 | `--no-commit` 合併後無法用 `checks.py repository` 驗合併結果 | 手動跑 `git diff --cached --check`，repository 延到 commit 後 |
| 2026-10-15 | #37 issuecomment-6196958520 | `repository` exit 0，但它比的是合併前的 HEAD | 匯入 `markdown_errors` 手寫補驗 |
```

## 2. 選層

由上往下問，第一個做得到的層就是答案：

1. **架構**：改設計讓錯誤無法發生（例：`backend/tests/conftest.py` 讓測試不可能寫進正式目錄）。
2. **型別**：用型別或資料結構讓錯誤無法表達。
3. **lint／CI**：在 `tools/ci/checks.py` 或 CI 加一條會失敗的規則。
4. **測試**：寫一個錯誤重現就會紅的測試。
5. **文件**：只能靠人遵守，強制手段寫「無」。

選到第 N 層時，第 1 到 N−1 層每一層都要寫一句為何做不到。要的是「壞了就失敗」的檢查，不是產生報告給人看。架構層的修正也要配一個測試，否則日後被改回去不會有人發現。

產出：選層表。

```markdown
| 層 | 可行？ | 理由 |
| --- | --- | --- |
| 架構 | 採用 | `repository` 改比 base 與工作樹，讀檔與比較的是同一份狀態；CI 的工作樹就是 HEAD，結果不變 |
| 測試 | 一併採用 | 架構修正被改回時要有測試會紅：`RepositoryWorkingTree` 三項 |
```

## 3. 寫檢查

- 檢查放在 CI 會跑的地方（`tools/ci/test_*.py`、`backend/tests/`、`tools/ci/checks.py` 的模式），本機與 CI 用同一個命令。
- 測試在隔離的暫存目錄或記憶體中重現錯誤狀態，不碰正式資料與共用 git 設定。
- 失敗訊息要指出哪個檔、哪條規則，讓人不必讀測試就知道怎麼修。
- 註解寫來源 Issue 編號，例如 `(#228)`。

產出：diff 與測試名稱，寫在 PR「做了什麼」。

```markdown
- `tools/ci/checks.py`：`repository` 模式的 `changed_paths` 與 `git diff --check` 改比 base 與工作樹。
- `tools/ci/test_checks.py`：`RepositoryWorkingTree`（未 commit 的合併結果有空白錯誤、壞連結時失敗；乾淨時只列 branch 的變更）。
```

## 4. 證明：先紅後綠

對犯錯的狀態跑新檢查必須失敗，修正後必須通過。犯錯的狀態用以下其中一種取得：

- 檢查的是程式行為：把被修的檔換回修正前的版本（`git show <base>:<path> > <備份>` 再複製過去），跑完用備份還原並 `cmp` 確認。
- 檢查的是資料或文件：在暫存目錄重建犯錯的 commit 或狀態。

不要用 `git checkout` 還原：它會把還沒 commit 的修改一起退回。

產出：兩段輸出原文貼進 PR「紅／綠」一節，各附命令與 exit。

````markdown
紅（`tools/ci/checks.py` 換回 master `c8041b8` 版本）：

```text
$ python -B -m unittest -v test_checks.RepositoryWorkingTree   # cwd tools/ci
test_clean_merge_result_has_only_the_branch_change ... FAIL
test_file_only_the_merge_touched_is_read ... FAIL
test_whitespace_in_the_merge_result_fails ... FAIL
FAILED (failures=3)   exit 1
```

綠（還原修正版，`cmp` 一致）：

```text
Ran 3 tests ... OK   exit 0
```
````

## 5. 更新 AGENTS 對照表

在 [AGENTS.md「規則與強制手段」](../../../AGENTS.md#規則與強制手段)新增一列；規則原本有一列寫「無」就改那一列，不另加。強制手段寫會失敗的那個檢查，檔案欄附路徑與函式或測試名稱，規則欄附來源 Issue 編號。同一個 PR 更新寫到這條規則的文件。

產出：對照表的 diff。

```markdown
| `checks.py repository` 檢查工作樹（含未 commit 的合併結果）（#228） | CI `repository` job 的 unittest `RepositoryWorkingTree` | `tools/ci/checks.py`（`repository_checks`、`changed_paths`）、`tools/ci/test_checks.py` |
```

最後在來源 Issue 留言：PR 連結、選了哪一層，以及沒處理的同類案例（留作下一次的輸入）。
