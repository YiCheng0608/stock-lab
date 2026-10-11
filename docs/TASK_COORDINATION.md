# GitHub 遷移入口與歷史協作紀錄

自 2026-10-09 起，即時任務、owner、依賴、狀態與交接只在 GitHub Issues／Projects 管理，流程見 [AGENTS](../AGENTS.md)，設定及模板見 [GitHub 工作手冊](GITHUB_WORKFLOW.md)。本檔只保留穩定入口與一次性遷移缺口，不再增加逐輪 roster 或派工狀態。

## 穩定入口

| 入口 | 位置與用法 |
| --- | --- |
| GitHub repository | [YiCheng0608/stock-lab](https://github.com/YiCheng0608/stock-lab)，依使用者決定維持 public；origin 指向此 repository。 |
| GitHub Project／治理 Issue | [產品開發看板](https://github.com/users/YiCheng0608/projects/1)；[治理 Issue #1](https://github.com/YiCheng0608/stock-lab/issues/1)管理 WIP、停滯計數、派工與整合收據。 |
| 正式 master／整合入口 | 正式 branch 為 origin/master；[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026)要求 PR、禁止強推／刪除。唯一整合持有者、排隊、授權及精確版本以治理 Issue 最新收據為準；協作串行不冒稱自動鎖。 |
| 導入完成界線 | 規則／模板、GitHub 設定與待辦匯入各有收據；產品試跑及並行驗收依[工作手冊](GITHUB_WORKFLOW.md#導入項目與驗收)另核，實際進度與缺口只查治理 Issue。 |

## 下一位接手者

接手先讀治理 Issue、Project 與原任務最新收據，核正式 master、未合併成果、owner、暫停與授權。歷史 NEXT／UNADMITTED 及未合併 checkpoint 先去重，不產生派工權；舊已驗能力不重開，「已 review」不直接轉 Done。即時交接留原 Issue，GitHub 不可用不另建任務台帳。本檔只更新穩定入口。

## 歷史紀錄的使用界線

下方 Git 原文是改造前快照。「目前」「下一輪」「正式接手」「待 merge」只代表當時敘述，最終版本應查 Git／原 task，不據此恢復或重派。歷史授權、私人資料保護、已用 quota、NO-RETRY 與未驗限制不因換流程失效；既有 session ID 不作現行 roster；現行處置記[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)及原 Issue。

改造前完整協作紀錄已移出現行檔：

```powershell
git show 46eb24474d7fa0254eb12079cb8a06754ac3e69e:docs/TASK_COORDINATION.md
```
