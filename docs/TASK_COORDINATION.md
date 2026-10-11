# GitHub 遷移入口與歷史協作紀錄

自 2026-10-09 起，即時任務、owner、依賴、狀態與交接只在 GitHub Issues／Projects 管理，流程見 [AGENTS](../AGENTS.md)，設定及模板見 [GitHub 工作手冊](GITHUB_WORKFLOW.md)。本檔只保留穩定入口與一次性遷移缺口，不再增加逐輪 roster 或派工狀態。

## 導入基線

以下為 2026-10-09 初次 GitHub 導入快照，非即時狀態。使用者已授流程改造／GitHub 導入，規則與獨立 review 修正已合併；依使用者指定，以本機歷史取代舊測試 remote/master，導入版本為 `ecf6d4479ddda26d68669d285256eb4f2473bdde`。後續版本查 Git／PR，狀態查治理 Issue。

| 入口／項目 | 導入時確認／後續查閱 |
| --- | --- |
| GitHub repository | [YiCheng0608/stock-lab](https://github.com/YiCheng0608/stock-lab)，依使用者決定維持 public；origin 指向此 repository。 |
| GitHub Project／治理 Issue | [產品開發看板](https://github.com/users/YiCheng0608/projects/1)；[治理 Issue #1](https://github.com/YiCheng0608/stock-lab/issues/1)管理 WIP、停滯計數、派工與整合收據。 |
| 正式 master／整合入口 | 正式 branch 為 origin/master；[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026)要求 PR、禁止強推／刪除。唯一整合持有者、排隊、授權及精確版本以治理 Issue 最新收據為準；協作串行不冒稱自動鎖。 |
| 模型配置 | 導入時 config.toml 為 gpt-6-astra／high，未改全域配置或重啟角色；配置不證實際 runtime。新角色預設見 AGENTS，實際配置查接手收據。 |
| 文件索引 | codebase-memory 查程式／文件，不管理任務。導入時 App MCP 可連，但 docs 為 metadata_changed，已核原檔；刷新／coverage／commit 收據留治理 Issue／原對話，連線不證完整 coverage。 |
| 產品能力 | 完整 M1／M2／M3 仍未完成；有限能力與缺口見 ROADMAP／主題契約，不因流程改造提升。 |
| 全局停滯計數 | 遷移查到較晚的未整合暫停 checkpoint；計數依治理 Issue 原證據、待核項與接受順序，不由 master 摘要預設零。遷移不是產品實作批次。 |
| session／worktree／私人資源 | 導入時未啟動、恢復、關閉或清理；歷史暫停、交接、NO-RETRY 與私人資源保護保留，無新授權不動。 |
| 導入完成界線 | 規則／模板、GitHub 設定與待辦匯入各有收據；產品試跑及並行驗收依[工作手冊](GITHUB_WORKFLOW.md#導入項目與驗收)另核，實際進度與缺口只查治理 Issue。 |

## 下一位接手者

接手先讀治理 Issue、Project 與原任務最新收據，核正式 master、未合併成果、owner、暫停與授權。歷史 NEXT／UNADMITTED 及未合併 checkpoint 先去重，不產生派工權；舊已驗能力不重開，「已 review」不直接轉 Done。即時交接留原 Issue，GitHub 不可用不另建任務台帳；本檔只更新穩定入口與規則變更。

派工以[現行 WIP 規則](../AGENTS.md#建立任務與派工)及[平行補位流程](GITHUB_WORKFLOW.md#平行派工與補位)為準；本檔歷史的一張試跑、容量與逐輪 ACK 不構成全專案串行條件。規則未整合的適用差異由全局在治理 Issue 交接，不改被測工作樹或升格管理候選為產品 base。

## 歷史紀錄的使用界線

下方 Git 原文是改造前快照。「目前」「下一輪」「正式接手」「待 merge」只代表當時敘述，最終版本應查 Git／原 task，不據此恢復或重派。歷史來源授權、私人資料保護、已用 quota、拒絕重試與未驗限制不因換流程失效。既有 session ID 不作現行 roster。現行殘留、NO-RETRY、私人資源與清理處置記[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)及原 Issue。

改造前完整協作紀錄已移出現行檔：

```powershell
git show 46eb24474d7fa0254eb12079cb8a06754ac3e69e:docs/TASK_COORDINATION.md
```
