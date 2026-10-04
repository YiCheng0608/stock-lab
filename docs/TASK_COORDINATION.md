# 協作與接手狀態

流程與角色配置由 [AGENTS](../AGENTS.md) 管理；能力與優先順序見 [ROADMAP](ROADMAP.md)，工作完成條件見 [執行清單](ROADMAP_EXECUTION.md)。

## 目前：M1-W8 法人窗口第八截止新產品輪

2026-10-05從已驗收master `b6359f9d1149345a27d739a1fb8a2bb33baaaba0`建立獨立branch／Orca worktree。BOOT-W8-ROSTER-1／ROOT-BOOT-W8-DOC-1／FORMAL-W8-RECEIPT-1已接受；上一root實核first turn `01a108f7-5c6d-7212-8c64-8fceb010a2eb` task_complete／四idle後，在唯一visible terminal `term_ececc12a-0eb3-40be-8040-3c80fba5dd92`實送/subagents一次，source=screen同四ID／Main default current，No sub-agents running為idle；menu warning不重送、Esc一次回Main、不選child。Helper唯一call rawexit0／startup_verified／surface visible，runtime／Git／可見gate先核才structured UTF-8派送，無timeout／重建／重啟／resume。首次task plain UTF-8讀回19107B／15428chars，SHA `8ba1289179c414c6cda274d48072c2583d381c31550fcdb6aeaed1c4b7c5a348`、turn `01a108f7-5c6d-7212-8c64-8fceb010a2eb`；exact initial task1／user items2／validator首exit0。完整啟動命令／收據留原task。

共同runtime／environment cwd與Git根 `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-eighth-cutoff-20261005`，branch同末段；repo `C:/Users/YiCheng/Desktop/taiwan-stock-research`、common Git dir為其 `.git`。四者起始HEAD／master為上述完整SHA、初始clean；root parent=null，三child由本root fork_turns=none新建、actual parent／sessionId／source.thread_spawn parent同root、depth1、forkedFromId=null。沿用此組ID／實際配置，不恢復W7角色或另開角色。

| 角色 | Thread ID／實際配置 | 本輪白名單與接手 |
| --- | --- | --- |
| 統籌 | `01a108f7-559e-7290-b46a-f266e5dd2a0a`；`gpt-6.1-sol`／`ultra`；/root | 已接受M1-W8-B1有限來源／API／native及owned服務清理；source mutation=[]。文件接受後才freeze。 |
| 程式 | `01a108f9-7012-7c72-9466-f1ef075cb3aa`；`gpt-6.1-sol`／`xhigh`；/root/program | Source6已交付／root review通過；backend/app institutional_windows.py／stock_overview.py、backend/worker tpex_institutional_window.py、backend/tests test_institutional_windows.py、frontend/src/components StockOverview.test.tsx、tools institutional-window-preview.cjs。交付後停寫。 |
| 文件 | `01a108f9-f224-7373-a1f0-e6d158f3d850`；`gpt-6.1-sol`／`xhigh`；/root/documents | DOC-M1-W8-B1僅docs/SOURCE_REGISTRY.md、STOCK_RESEARCH_PAGE.md、DATA_SOURCES.md、ROADMAP.md、ROADMAP_EXECUTION.md、development-baseline/README.md、TASK_COORDINATION.md七既有文件；交付後停寫。 |
| 索引與Git commit | `01a108fa-7d00-7050-8c34-9784f7c7ffcf`；`gpt-6-luna`／`medium`；/root/index_git | Source=[]；W8 index／commit／merge尚未授權。已承接W7外owner，但其整序因前檢SyntaxError永久NO-RETRY停止，所有指定資源仍保留。 |

App MCP connected／list32／has_more=false，master8與W4／W5／W6／W7各6仍原根，W8未索引；master／W7七docs metadata_changed後讀W8 exact source，coverage為best effort，不稱MCP阻擋。CLI／reload／refresh0，不輪初或中途刷新／clone／改ACL或cache／終止其他session。TASK≤24576B且net起始HEAD22917B≤4096B、UTF-8無BOM／LF；W6 heading到EOF14261B／protected尾3713B／GPG1040B及565B含末LF原byte保留。SOURCE原94062B、個股頁原105376B與W7驗證入口保留，不覆寫歷史候選。文件外網／backend tests／DB／index及Git mutation／清理0；不新增附件／backup／helper／manifest。既有零新增測試／raw／ZIP／DB／tmp／cache／pycache／log／artifact限制不因新session重置。

## 本輪核心成果、剩餘缺口與停滯

| 項目 | 已接受有限範圍／未完成 |
| --- | --- |
| 單一核心M1-W8-B1 | TPEx3105／6488新增2026-09-21並保9/22／9/23／9/24／9/29／9/30／10/1／10/2；八截止96 net／actual API／16組具名可信native、來源／新原列／拒用及owned清理已接受，完整M1未完成。 |
| 真依賴解除 | 真8/25 dataset11856 dated CSV898全列25欄／兩股44金融欄／七組及全部關係，三月43全OHLC先驗、採27／pre16（Aug21／5／16）；完整8/25～10/2日曆、新policy3613B／external pins核通，來源gate正面後才實作。Observed版本依actual Asia/Taipei2026-10-05，UTC取得時間另記。 |
| 計算／API／觀測 | Probe4GET146055B與production30GET3917863B為獨立觀測；27daily24383fullrows／54selected／1188金融欄、96 raw buy－sell net、W7全部84一致、3600重疊API原字串及ALL30 body／canonical receipt SHA獨算已核。Held30／普通GET及import外網0，19memory表全欄／typeof不變、guards0；唯一數值、版本及逐次UTC見[來源 §19](SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)。 |
| 具名產品操作 | 各股8unique可信方向鍵＋FORM submit，共16explicit390×844日期組／96 DOM net／起迄／actual missing0；16 outerSUMMARY的2880金融textContent對held30，非1188 distinct或3600 API overlap，不稱全部nested曾native開。兩股9/21新8/25 nested原列、可信repeat讀取、6488 unsupported9/28／9/21恢復與TWSE route拒用通；見[個股頁 §24](STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯)。 |
| 測試與owned清理 | Python8worker／5API首exit0；explicit Node24.19.0 full-src noEmit／104SSR exit0，mock Node HTTP未跑、actual App fetch／Response.json由native覆蓋。本輪1個owned page唯一close／tabs=[]；Node／API Ctrl+C各一次，finalguard0正面、兩PTY rawexit1，API19表preserved。Fresh六PID／children及8781／82 listeners absent，esbuild exit code未知、無Stop-Process／第二signal。細節見[開發入口](development-baseline/README.md#m1-w8-八截止法人窗口的零落盤驗證入口)。 |
| 未完成邊界 | 非PIT／修訂、trend／研究條件／Signal、raw保存／跨程序讀回／正式DB；突破／回踩gate不由補資料解除。缺／壞8/25只synthetic API／SSR，actual missing0；catalog／price seed不證真行情。新375viewport／水平手勢／physical canvas／Vite production build／nav race、legacy／ZIP／old live／full suite及範圍外仍未驗。 |
| 分報／停滯 | 核心操作+1＝新增9/21並保七cutoff；真dependency+1＝真8/25／完整27日曆／新pins；reliability0、stall0。W7原core+1／dep+1／reliability0；P6d／P6e歷史至少2可靠性batch無核心、更早unknown。Bootstrap／planning／fixture／docs／index／Git不算product batch；前兩項皆無則+1，連續兩批須重選。 |

原JS const reassign、historical parser assert0、PS §18多行$n op_Subtraction及browser focus／quote／viewport原錯留原task／開發入口；歷史parser修正只2GET／0POST／source0核全部84及ALL30 hashes exit0，未重取來源／重跑已通驗收，不改原exit。服務清理後／文件更新前225files（224tracked＋.git111B）／14dirs／4366028B、extra ignored／untracked新增0；不稱全profile／cache0。

下一單一核心候選M1-W9：同兩股新增2026-09-18、保八cutoff，形成九截止108 net／來源／缺日／可信native操作。新free可執行候選dataset11856 `d=115/08/24` daily尚未取得／驗證／准入；8/24全OHLC已驗未採不代daily，不需8/21。28sessions／31GET／59MiB、9/18應恰20／5start9/14／20start8/24僅候選，須下一新root核真來源、完整8/24～10/2 bounded日曆／新policy及pins再實作，不預先取8/24。無positive取得路徑，在implementation前依證改必要gate全齊最小M3具名Plan或waiting，不空轉reliability／降gate。W8待七文件接受→freeze→index／coverage→核准commit→root核後另准master合併；最終receipt留原task，不為回寫hash重刷／提交。

## W7已接受版本與外清永久NO-RETRY

W7 source6／docs7共13files621798B、net+46473B，freeze／六index與root App・File・SQLite核對已接受。正式SHA `b6359f9d1149345a27d739a1fb8a2bb33baaaba0`、parent `67e032f7e73b93a0f56196836d946502a6deed84` commit rawexit0；另准master FF rawexit0、root兩根13blobs／bytes及clean已核。原task最終receipt覆蓋舊pending，不為hash重刷。有限真來源／84 net／API及native仍有效，歷史來源與操作見[來源 §18](SOURCE_REGISTRY.md#18-m1-w7七截止法人來源與完整有界日曆)／[個股頁 §23](STOCK_RESEARCH_PAGE.md#23-m1-w7七截止法人窗口與原件追溯)，不外推完整M1。

新W8 index_git已承接W7 worktree外owner；CLEAN-W7-TERMINAL-1在四thread只讀前檢因literal `\n` SyntaxError／rawexit1停止，0RPC／0close／0archive／0rm／0delete，root正式永久NO-RETRY整序，不修字串、改stdin或換root／角色／工具／命令補做；非automatic approval拒絕。Terminal `term_7038dae6-664a-49e3-b06a-ce99aab4345e`仍connected；root `01a10866-06f5-7f50-a024-c7ff6bc9b367`、三child `01a1086a-7fa1-7470-b1e6-cadce4f53011`／`01a1086b-0759-7093-9f59-7045a9aaf6cb`／`01a1086b-9498-7203-9d66-9755a12a89ca`四history未封存保留。Worktree `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-seventh-cutoff-20261005`／同名branch、225files／14dirs／4340713B（.git112B）保留；六App index／DB44826624B保留，根未移除禁止delete，18fixed aux／stage等未作新清理。兩returned logs693B此前已刪／post absent，不rescan或retouch。失敗不否定W7有效合併或W8產品驗收；W6／W5／W4／GPG及更早NO-RETRY原文繼承下方。

## W6已接受版本與指定外清結果

W6 FREEZE-W6-1 source6／docs7共13files575325B、net+49586B（source27035／docs22551），13blob逐byte／hash、六coverage／root複核、本地commit與另准master FF均完成；正式SHA `67e032f7e73b93a0f56196836d946502a6deed84`、唯一parent `56c745861e1d96a88fb179561165a4dd3d81725a`。原task正式receipt覆蓋舊doc pending、不為hash重刷。W6來源／72 net／API／native／owned服務清理有限接受仍有效，權威在[來源 §17](SOURCE_REGISTRY.md#17-m1-w6六截止法人來源與完整有界日曆)／[個股頁 §22](STOCK_RESEARCH_PAGE.md#22-m1-w6六截止法人窗口與原件追溯)，不外推完整M1。

新index_git已承接W6外owner；exact terminal唯一close exit0／ptyKilled=true、post operator_close／list=[]；root一次set_thread_archived exact4，post四notLoaded／historyexists，保留歷史不永久刪除。根移除在parse階段失敗，永久NO-RETRY，清理失敗不否定有效W6合併或W7驗收。

| W6指定資源 | Exact結果／殘留與NO-RETRY |
| --- | --- |
| 四角色／terminal | Root `01a10803-5b84-7e92-b252-bdf48a8b51d5`；child `01a10807-ac3a-7c21-8613-05dcf1665e84`／`01a10808-2845-7212-a762-ee78399a701f`／`01a10808-b97a-7720-986f-3814e64af40f`；terminal `term_55fa5540-b620-4228-b784-2070e6b4c4d9`已close／absent。四history保留，最後bytes依序8821563／2360953／2076631／2270827；archive／notLoaded已核，不恢復角色。 |
| Worktree／branch | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-sixth-cutoff-20261005`、branch同末段保留；225files（224tracked＋.git110B）／14subdirs／4294238B。CLEAN-W6-PREFLIGHT-1A all-ancestor actual owner含profile SYSTEM／canonical／nonreparse／fresh Git只讀gate核通，owner SID首格式錯補正、原錯保留。CLEAN-W6-RM-1 inline Python -c引號剝除SyntaxError／exit1在parse階段，CreateFileW0、exclusive未執行、Orca rm0／delete0；root正式永久NO-RETRY，不修引號／stdin或換root／角色／工具／指令再做，不kill。此非sharing violation或approval review。 |
| 六App index／DB | 前綴 `taiwan-stock-research-roadmap-m1-window-sixth-cutoff-20261005-`；suffix backend-app／backend-worker／backend-tests／frontend-src／tools／docs；六DB bytes依序9633792／7143424／16842752／5046272／3145728／2490368，共44302336B retained。根未移除，禁止App delete／DB delete；18fixed aux此前absent、stage／其他aux未知，不掃cache。 |
| Returned logs另案NO-RETRY | `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m1-window-sixth-cutoff-20261005-backend-tests-1791141319.log`281B及`C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m1-window-sixth-cutoff-20261005-tools-1791141327.log`408B，共689B retained。CLEAN-W6-LOG-1 strict slash／backslash比較實作canonical=false、0delete／exclusive及predelete未做；root正式NO-RETRY，不normalization／換roletoolcommand補刪，非approval blocked。與根移除parse失敗及六DB保留分開。 |

## W5已接受成果與版本封存

W5 `FREEZE-W5-1` source8／docs7共15檔逐byte／hash、六區coverage、本地commit、root核對及另准master FF均完成；W6起始基底 `56c745861e1d96a88fb179561165a4dd3d81725a`，parent `b93c75954f0d954fec79e2f41ad21a0636b7cbe3`。原task正式receipt覆蓋舊文書pending，不為hash重刷／提交。W5新8/28／24日曆、五截止60net／actual API、具名可信native與owned服務清理已有限接受；歷史數值／版本見[來源 §16](SOURCE_REGISTRY.md#16-m1-w5五截止法人來源與完整有界日曆)，10表單、來源外層／窄版原列／拒用及未驗邊界見[個股頁 §21](STOCK_RESEARCH_PAGE.md#21-m1-w5五截止法人窗口與原件追溯)。不外推範圍外／PIT／保存／研究條件；原quote／connection／os206／snapshot截斷／unsupported setup等失敗及完整測試／退出留W5原task／Git。

## 指定W5外清：四history已封存，根被占用NO-RETRY

W6 index_git已承接W5 worktree外owner。Root新鮮核old root notLoaded／last task completed、三old child idle、exact terminal operator_close absence／exitCause與Git兩根clean／merged後，單次exact set_thread_archived將W5root archived=true；獨立後驗四ID全notLoaded／archived_sessions path／historyexists。Terminal actor／close command／ptyKilled仍未觀測，不重送close、不追認本owner執行close。CLEAN-W5-PREFLIGHT-1完整只讀gate後exact根share-none readonly open因WinError32停止，0rm／0delete、NO-RETRY；清理失敗不否定W5合併或W6有效產品驗收。

| W5指定資源 | Exact範圍／順序與目前限制 |
| --- | --- |
| 四角色／terminal | Root `01a1078c-0146-76f1-86e7-ff735f67ba2e`，child `01a1078f-ffa6-74e1-bab5-01a13ed65015`／`01a10790-8ab8-7730-8ff3-b7fd8b0d2f64`／`01a10791-1f50-78f1-9805-6ed32cec3ec3`；terminal `term_c79ee606-9d28-4563-aa64-584e039dc4f8`。已觀測operator_close／orphaned=true／connected及writable=false／list=[]，actor／command／ptyKilled未知、不再close。四history已封存保留，後驗四ID notLoaded／archived_sessions，未永久刪歷史。 |
| Worktree／branch | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-fifth-cutoff-20261004`，branch同末段名稱；225files／15dirs（含root，14subdirs）／4244652B保留；exact directory share-none readonly open FAILED WinError32／sharing violation，0rm／0delete。此根NO-RETRY，不換role／API／tool／command再exclusive或Orca rm；branch同留。 |
| 六App index／DB | 根未移除，禁止App delete前綴 `taiwan-stock-research-roadmap-m1-window-fifth-cutoff-20261004-` 的backend-app／backend-worker／backend-tests／frontend-src／tools／docs分區及exact DB。六DB最後sizes依序9633792／7143424／16646144／5046272／3145728／2490368B，共44105728B；現仍保留。18fixed aux此前absent，stage／其他aux未知，不稱cache0。 |
| Returned logs NO-RETRY | `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m1-window-fifth-cutoff-20261004-backend-tests-1791134983.log` 281B；`C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m1-window-fifth-cutoff-20261004-tools-1791134992.log` 408B，仍在。原automatic approval在CreateProcess前以blocked by policy拒絕，0process／0delete；exclusive／predelete未跑。NO-RETRY，不換root／role／tool／command刪，不混入W5根及DB外清。 |

清理與產品驗收分報。未執行或失敗明列exact殘留、大小及原因；W5 exact根占用NO-RETRY且未移除，六App index／DB全保留禁止delete；不因殘留否定有效W5版本，也不掃profile／Temp／其他cache或被拒資源。

## 更早版本與指定外清限制

W4的15檔freeze／六區coverage／commit／master本地FF已接受，版本為W5基底b93c759完整SHA；原task正式receipt覆蓋歷史pending。W1–W4原值及有限原生邊界保留[來源 §13–15](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)、[個股頁 §18–20](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)及Git／原task，不列本輪新增成果。

| W4指定資源 | 最後已知結果／NO-RETRY |
| --- | --- |
| 四角色／terminal | W4 exact close一次ptyKilled=true，post orphaned／connected及writable=false／list=[]；四ID archived／notLoaded、history保留。首archive預核誤assert關閉後root仍idle，exit1／零archive；核actual notLoaded／child idle修scope後唯一archive成功，exact IDs／handle及原錯留原task／Git。 |
| 未移除worktree／branch | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-earlier-cutoff-20261004`，branch同末段名稱；225files／14dirs／4199054B保留。CLEAN-W4-RM-1在exclusive／Orca rm前因owner gate停止，0rm／0delete、NO-RETRY；profile ancestor `C:/Users/YiCheng` actual SYSTEM，不符原root指示YiCheng，不改owner條件／role／command補刪。 |
| 六index／DB | 前綴 `taiwan-stock-research-roadmap-m1-window-earlier-cutoff-20261004-`，suffix backend-app／backend-worker／backend-tests／frontend-src／tools／docs；六DB共44171264B及六App index保留，根未移除禁止delete。18fixed aux此前absent，其他aux未知，不擴掃；master8不動。 |

W3版本c6018e3及指定外清已接受：舊四archived／notLoaded、history保留，exact terminal／worktree／branch及六DB／18fixed aux缺席；owner allowlist／path比較與只讀後驗原錯、stage／其他aux／全cache未知不追認。W1／W2版本f716526及指定外清已接受，其餘aux unknown／logs刪前gate缺口保留。P6d 0f8ac4a／P6e 5ae84d2、獨立文件1596fe1／7b3212a為歷史，不恢復角色或納入本輪清理；各receipt留原task。GPG1232B及更早NO-RETRY繼承下方原文。

### 繼承的GPG殘留與簽章收據更正（原文保留）

本輪新NO-RETRY殘留/流程錯誤：Git提交前索引角色未預先核落盤即跑C:/Program Files/Git/usr/bin/gpg.exe --list-secret-keys --with-colons，merged診斷明示directory/keybox/trustdb created、exit0無secretrecords，但未分stdout/stderr/未先核absent/無ownedPID證明。新C:/Users/YiCheng/.gnupg/pubring.kbx32B與trustdb.gpg1200B、父.gnupg目錄仍存在；root限定目录只读核仅2子、所有祖先owner/nonreparse。CLEAN-GPG-W3-1 exact2files1232B+新空目錄清理被automatic approval review於CreateProcess前拒，理由只有blocked by policy，0程序/0刪；被拒腳本exclusive/predelete checks未執行，不補通過。NO-RETRY不換root/角色/命令重試，不掃profile或killgpgdaemon；功能/索引有效、不重跑。根據既有本地commit授權，root僅批准單命令git -c commit.gpgsign=false commit，不改repo/global簽章設定、不再gpg。此新未核落盤錯誤/拒絕殘留須在你初始TASK接手狀態原文如實納入，原歷史NO-RETRY尾段仍逐字保留。

簽章需求收據更正：C1原git config --show-origin --get commit.gpgsign實際stdout空、exit1；filtered gpg/signing讀取也空，沒有true/origin/scope。索引角色先前聲稱repo commit.gpgsign=true是誤判，已撤回。GPG查詢本不必要；root一度依錯回報加asserttrue只讀核末尾exit1，已修正為實際local/global unset收據exit0，不稱config曾true或C2改了設定。C2唯一命令-c commit.gpgsign=false未寫repo/globalconfig，commit有效。新NO-RETRY1232B/profile殘留與未預核落盤/自動拒絕仍原樣繼承。

## 未解驗證與資源限制

下表沿用整理前最後已知收據；本次未重新盤點或清理，不作即時刪除 gate。已刪除項不重做；審核拒絕項不得重試、換工具、掃共享目錄或刪父目錄。精確歷史收據由 Git `5ae84d2:docs/TASK_COORDINATION.md` 與對應原 task 查閱。

| 項目 | 最後已知結果／後續限制 |
| --- | --- |
| R0-B2 verifier | 完整 snapshot／body／receipt／registry pins tuple 未齊，真實檔案／snapshot 整合待驗，70個既有案例未跑；不重複搜尋或建 fixture 冒稱來源接入。 |
| P6d 五 DB 刪前流程 | 五 DB／十五 aux 與兩 logs 刪後缺席已驗；刪前只核 leaf／exclusive open，未核 all ancestors 與十五 aux。不得追認完整刪前 gate；不補刪除或重試。 |
| P6c blocked logs | 兩個 logs 共717 bytes（295／422 bytes）；immediate gate／刪除均在 CreateProcess 前被拒，未執行，NO-RETRY。兩完整路徑見下方。 |
| P4 blocked logs | 兩個 logs 共713 bytes（293／420 bytes）；刪除被拒，未執行，NO-RETRY。兩完整路徑見下方。 |
| P2 HAR | `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har`，64,885 bytes；清理遭審核拒絕，未執行，NO-RETRY。 |
| P1 index logs | 3個共1,139 bytes；295 bytes 項刪除被拒，另兩個各422 bytes未嘗試。精確路徑留原 storage task；未清，不得推定全清。 |
| M1 成交量舊 worktree | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-volume-exact-presentation-20261003`，最後3,528,690 bytes；worktree／branch移除被拒，NO-RETRY。索引／logs已清不代表該根已清。 |
| legacy volume 整合空根 | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-legacy-volume-integration-20261003`，最後0 bytes；空目錄被占用，刪除失敗，不重試。PTY終止未核。 |
| selected-invalid 空根／logs | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-selected-invalid-20261003`，最後0 bytes；空根被占用，刪除失敗。兩logs共628 bytes被拒，未刪；更早兩logs共545 bytes亦被拒。路徑留原task，NO-RETRY。 |
| M1-P2a 測試根 | `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m1p2a-01a0fe7e`，243 entries／11 files／993,443 bytes，已超原entries上限；code-tests／live清理被拒，未執行。conftest另建的default Temp _TEST_ROOT名稱／大小未知，不掃Temp猜測。 |
| 更早 M1 測試根 | `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m1-01a0fe5a`，118 entries／105 files／17,319,956 bytes；UI／code-tests清理被拒，未執行。 |
| 後續落盤 | 繼承原零新增測試／附件／暫存／殘留限制。必要磁碟驗收保持待驗；不得換session、根目錄或改名重置上限。 |

四個已知 blocked log 的完整路徑：

- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-stock-detail-quote-read-isolation-20261004-backend-tests-1791076431.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-stock-detail-quote-read-isolation-20261004-tools-1791076500.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-backend-tests-1791054858.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-tools-1791054866.log`

## 歷史與維護

只更新現況、下一核心交接與未解限制，不追加逐輪流水。歷史 roster／實際模型、首跑失敗／補驗、freeze／索引／commit／merge 及清理收據留 Git／原 task；舊分派不恢復派工權。查閱方式見[文件索引](README.md#歷史查閱)。
