# GitHub 工作手冊

權責與驗收以 [AGENTS](../AGENTS.md) 為準。本文是設定及操作契約，不代表 GitHub 已配置；實際連結與導入缺口見[遷移入口](TASK_COORDINATION.md)。產品方向留 [ROADMAP](ROADMAP.md)，逐張任務在 GitHub 管理。

## 欄位與唯一來源

| 資訊 | 唯一位置 | 維護者／用法 |
| --- | --- | --- |
| 目標、範圍、AC、來源版本、決策、驗收收據 | Issue 本文與留言 | 全局統籌建單，任務統籌維護；AC 用 AC-1 等穩定編號，改動保留修訂及理由。 |
| 母子關係 | GitHub 原生 parent／sub-issue | 全局統籌；純容器母單不開工作區。 |
| 阻擋關係 | GitHub 原生 blocked-by／blocking | 全局統籌；可跨母單，與 parent 分開，派工前查循環與可用版本。 |
| 狀態 | Project 的 Status 單選 | 待辦、開發中、測試中、待整合、完成；任務統籌依轉移 gate 更新。 |
| 優先級 | Project 的 Priority 單選 | P0 阻止現行核心使用／整合，P1 近期核心，P2 後續核心，P3 候選／改善；全局統籌排序。 |
| 工作種類 | Project 的 Kind 單選 | 功能母單、執行任務、候選；小功能選執行任務，不強造母單。 |
| 可開工 | Project 的 Ready 單選 | 是／否；全局統籌核依賴證據後設是。候選、容器、阻塞、暫停為否。 |
| 阻塞與暫停 | Project 的 Blocked、Paused 單選 | 各為是／否；原因、決策者、解除條件、原階段、檢查事件／時間留原 Issue。 |
| 當前 owner／下一角色 | Issue 最新交接留言 | 記 session 及版本，接收者確認；assignee 是可接收通知的 GitHub 帳號，不假裝每個 agent 都有獨立帳號。 |
| 整合排隊與持有者 | 一張治理 Issue 的最新整合收據 | 全局統籌唯一更新；列有序候選及最多一個持有者，不另建本機鎖表。 |
| 同時開發上限、全局停滯計數 | 同一治理 Issue | 初始上限 1；按批次驗收順序更新計數，產品母單連結該次收據。 |
| Repo／Project／整合入口 URL | 本文連結的遷移入口 | 設定完成後只留穩定入口；不抄即時狀態或 roster。 |

若 GitHub 實例不支援原生關係，在 Issue 本文固定「母單／子單」及「Blocked by／Blocking」兩欄使用完整連結，由全局統籌維護雙向一致；不得同時維護兩套權威關係。只有權限／功能確認後才選 fallback。新標籤不是 Ready 或 Status 的第二份副本。

建議看板視圖：產品母單排序、Ready 執行待辦、進行中工作（含阻塞）、待整合、候選待辦。Project 以 Issue 為任務卡；PR 連在 Issue，避免把 PR 和 Issue 算成兩張工作。WIP 是治理規則，未裝自動化不聲稱系統會強制上限。Blocked 不自動釋放名額；全局統籌依 AGENTS 明確掛起並確認停寫後，才可安排前置任務，恢復也須重新排程。

## Projects 與關單自動化

導入時逐項核對並記設定收據：

- Status 只保留五個約定值；阻塞與暫停使用獨立欄位。
- 關閉會把 PR merged／Issue closed 直接轉 Done 的 automation，以及 Status Done 自動 close Issue 的 workflow；取消／重複單不能被轉成成功完成。
- PR 本文及 commit 不使用 `Closes`、`Fixes`、`Resolves` 加 Issue 編號的關單語法，使用 `Refs #<number>`；人工也不提前關單。
- 任務統籌確認合併後檢查通過後才手動關 Issue、更新 Status；若其中一步失敗，記已完成動作與待同步欄位，重試前讀回，避免重複操作。
- 依核准權限配置 master 的 PR review／必要 checks、禁止直接推送／強推／刪除及可寫入主線的整合者；必要 checks 依變更類型選定，不杜撰尚不存在的 CI。設定未驗證就記未設，不能把程序規則說成技術保護。

GitHub 支援自動關單關鍵字，Projects 也有關閉／合併時改狀態的內建 automation，故必須核對這些設定：[連結 PR 與 Issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)、[Projects 內建自動化](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)。

## 模板入口

- [產品功能母單](../.github/ISSUE_TEMPLATE/feature.md)：功能及整體 AC，不自動派工。
- [執行任務](../.github/ISSUE_TEMPLATE/task.md)：子單或獨立小功能，派工前完成全部必要欄位。
- [候選 bug／想法](../.github/ISSUE_TEMPLATE/candidate.md)：先分流；違反當前任務 AC 的問題仍回原單退修。
- [PR](../.github/pull_request_template.md)：指定版本、證據、整合授權及合併後檢查；不自動關單。

以下文字直接貼原 Issue 留言，不另建交接附件。每次填實值、完整 SHA 和可定位證據，未驗寫未驗，不以空白勾選當通過。

### 派工與接手

```text
事件：派工／交接／接手確認；時間：
Issue／AC 修訂：
目前核心缺口／新增操作／必要依賴與可用證據：
交付者 → 接收者角色／session：
下一動作／完成條件：
repo／worktree／branch／base SHA／candidate SHA：
Orca terminal handle／實際 session／模型／reasoning／cwd 核對：
寫入白名單／共用檔案協調／原 owner 停寫：
資料與測試授權／產物數量大小／建立及清理方法：
既有驗收／失敗／未驗／不可重建證據位置：
freeze／索引與 coverage／commit／PR／merge：
全局停滯收據／計數：
接收者讀回版本並確認／未接手原因：
```

### QA 與退修

```text
事件：QA 結果；QA session（不同於工程師）：
Issue／原始 AC 修訂／candidate 完整 SHA／工作樹乾淨：
資料版本／日期／市場標的／用途／授權：
AC-1：通過／退回／未驗；操作或命令；版本／原 exit；證據：
AC-2：通過／退回／未驗；實際與預期；復現：
真實數值／API／可信 UI／磁碟跨程序：適用項與證據，不適用理由：
沿用證據與差異分析／未驗與限制：
產物／清理結果／殘留路徑大小與原因：
結論：通過或退回（必要 AC 未驗不能通過）
下一角色／動作／版本／接手確認：
```

### 阻塞與決策

```text
Issue／原階段／Blocked 或 Paused：
原因／阻擋 Issue／實際證據：
決策者／需決定事項／影響：
解除條件／重新檢查事件或時間：
下一角色／動作：
AC 是否變更／核准者與修訂／需重驗項：
```

### 整合與結案

```text
事件：排隊／取得整合權／合併／檢查／釋放整合權
Issue／PR／整合執行者／使用者授權收據／開始時間：
正式 remote／master base SHA／candidate SHA：
最新 master 合入任務 branch／衝突處理者／差異與 QA：
文件 freeze／索引 project 與 generation／coverage 限制：
核准者／核准 SHA／合併前 base 再核：
合併後 master SHA／必要檢查命令、原 exit、證據：
新增能力／實際解除依賴／可靠性改善／剩餘缺口：
全局停滯計數前後／下一步理由：
Issue 關閉與 Project 狀態同步：
清理另行授權／執行或未執行／殘留：
整合權釋放／失敗時暫停及接管安排：
```

## 導入順序與驗收

1. **本機流程改造**：讀 AGENTS、ROADMAP、Git 狀態及模型配置；保留既有修改。完成規則、模板、歷史狀態交接與文件一致性，存本機流程 branch／commit。這不算產品試跑。
2. **GitHub 設定**：確認 repository／Project 所屬、可見性、現有帳號及登入授權，先唯讀盤點現有 Issues／PR／Project。取得外部寫入、必要 repo 設定的授權後，配置欄位、關係、治理 Issue 及整合入口，核對 automation／權限。不得把內含本機路徑或 session 資訊的歷史 repo 未經檢查發布到公開 repository。
3. **狀態遷移**：全局統籌以 ROADMAP 與歷史契約逐項對照 Issues 去重。近期可交付工作拆細、遠期粗分，保留來源與 AC；舊「已 review」不直接換 Done，須核正式主線、原始證據及剩餘缺口。既有已驗能力只在有用時建立已完成參照，避免重開已做工作。舊暫停／NO-RETRY／私人資料保護保持，沒有新授權不恢復。
4. **停滯與 owner 交接**：核最近兩個實作批次及 Git／原 task，確認全局計數，不因流程改造歸零。GitHub 明確指定新 owner；舊 session 不再有自動接續權，不必為遷移關閉／刪除它們。將實際 Repo／Project／治理 Issue URL 回寫遷移入口後，不再於 repo 更新任務狀態。
5. **單任務試跑**：選一張依賴可用、有實際能力增量的近期 Issue。跑完派工、Orca 工作區、實作、自測、獨立 QA、文件、freeze、coverage、commit、經授權推送／PR／串行整合、合併後檢查、任務統籌關單；確認版本與下一角色均可追溯。退修／阻塞若未實際發生，以桌上情境核規則並標非實測，不刻意造產品缺陷。
6. **開放最多兩張**：全局統籌確認試跑沒有 owner、版本、狀態同步或權限缺口後，在治理 Issue 記證據並調 WIP 1 → 2；檢查共用檔案／依賴衝突。尚未完整試跑就維持 1。不自動部署或清理。

授權可一次明確涵蓋指定 repo／branch／任務範圍，記錄後沿用；「同意流程」本身不等於同意登入、推送、PR、合併、部署或刪除。要詢問時先備妥確切對象、版本、檔案及預計動作，讓使用者核准具體結果。
