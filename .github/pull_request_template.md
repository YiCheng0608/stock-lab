## 問題與結果

Refs #<issue-number>
<!-- 不用自動關單關鍵字；合併後檢查通過才由任務統籌關單。 -->
具體問題／完成後行為／不在範圍內的事項：

## 驗證版本與證據

正式 master base SHA：
candidate 完整 SHA／AC 修訂：
工程師自測與原始失敗：
獨立 QA session／逐 AC 結果／未驗及限制：
QA 服務版本收據：PID／啟動時間／來源 worktree／載入 SHA 或來源與 bundle 雜湊／UI-API 對應；不適用理由：
真實來源／數值／API／UI／磁碟跨程序證據或不適用理由：
文件 freeze 範圍／程式索引 project、絕對 root／scope、branch、內容版本依據、generation、coverage 限制與刷新者：
核准提交檔案／剩餘差異：

## CI 觀察與退修

任務統籌／CI 觀察 owner；離線時下一 owner 及接手確認：
最新 run URL／attempt、base／head／實際驗證 SHA、必要 checks 結果：
失敗 job／step／原錯誤與原 Issue 處置收據；未失敗填不適用：
修正留同 branch／PR，受影響 QA 後重跑；舊 head 成功不覆蓋新版本。暫態重試及釋放整合入口依工作手冊，不以刪除／略過檢查湊綠燈。

## 串行整合

整合治理 Issue／當前持有者：
最新 master 已在任務 branch 合入／衝突處理及重驗：
推 branch／開 PR／合併的授權收據與核准 SHA：
<!-- branch 或 master 改變後重新核准，不直接全選衝突一方。 -->

## 合併後檢查

檢查執行者／必要命令／通過條件：
被測服務對應合併版本的核對／正式 root 的受影響程式索引核對：
失敗處理、暫停整合及復原決策者：
合併後 master SHA／實際結果：待執行，回原 Issue 留收據
worktree／branch／session 清理：另行授權，不隨合併自動刪除
