# 協作與接手狀態

流程與角色配置由 [AGENTS](../AGENTS.md) 管理；能力與優先順序見 [ROADMAP](ROADMAP.md)，工作完成條件見 [執行清單](ROADMAP_EXECUTION.md)。

## 目前：M1-W5 法人窗口第五截止新產品輪

2026-10-04從已驗收master `b93c75954f0d954fec79e2f41ad21a0636b7cbe3` 建立獨立branch／Orca worktree及新四角色；2026-10-05正式可見接手通過。`BOOT-W5-ROSTER-1`／`DOC-W5-FORMAL-1`已接受，原task receipt覆蓋文書pending。**Root已有限接受M1-W5-B1真來源→計算→actual API→兩股五截止可信原生操作及owned服務清理；完整M1未完成。** `DOC-W5-FINAL-1`七文件交付待root review，產品freeze／索引／commit／master merge均pending，不由接手或功能接受代版本封存。

共同runtime／process cwd／Git根：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-fifth-cutoff-20261004`；branch `roadmap-m1-window-fifth-cutoff-20261004`；repo `C:/Users/YiCheng/Desktop/taiwan-stock-research`、common Git dir為其 `.git`。四者起始HEAD／master均為上述完整SHA、初始status乾淨；root及各child實際Rpc／Git自核一致，不由prompt／設定推定。

唯一visible terminal `term_c79ee606-9d28-4563-aa64-584e039dc4f8` 已核connected／writable／non-orphaned及正確cwd／branch／ultra；其他floating環境handle不作證。上一root在first turn completed及四runtime idle後實送 `/subagents`一次，source=screen正面Main [default] (current)與三child ID一致；No sub-agents running只代表idle，Esc一次回Main、未切child、未重送。

唯一start-coordinator首exit1／waiting terminal handle時未送task／無handle；原請求延遲產生同terminal，Trust Enter一次後核同root idle／turns=[]及runtime／Git／visible gate，structured UTF-8 turn/start唯一一次（`01a1078d-766e-7650-b1b9-821e65a35a65`）。首task16685 UTF-8 bytes／12025 chars，SHA256=`8a9dddb02ab4bb5061dd23abe3a1f7d25423e3ac8f1c49fb467b245ac98a3f7e`；全文與原錯留原task；沒有另launch／resume／繞gate。首次formalreceipt JS SyntaxError為0工具／0收據，修正後才首次送出。未用shell `term_a8095559-0828-4796-9ad7-dbc84661b0df` exact close --tab一次，ptyKilled=false、list=[]／orphaned=true／connected及writable=false、operator_close，不稱PTY已kill。

| 角色 | Thread ID／實際配置 | 本輪白名單與接手 |
| --- | --- | --- |
| 統籌 | `01a1078c-0146-76f1-86e7-ff735f67ba2e`；`gpt-6.1-sol`／`ultra` | 核定派工／來源／產品及數值驗收；已接受B1有限操作及owned服務清理，待文件接受後freeze；與原index承接W4外清，未通過移除gate則保留。 |
| 程式 | `01a1078f-ffa6-74e1-bab5-01a13ed65015`；`gpt-6.1-sol`／`xhigh` | B1 exact8：四backend／三frontend／preview已交付接受，停寫；未授權取得或實作W6。 |
| 文件 | `01a10790-8ab8-7730-8ff3-b7fd8b0d2f64`；`gpt-6.1-sol`／`xhigh` | FINAL-1 exact7：SOURCE_REGISTRY、DATA_SOURCES、ROADMAP、ROADMAP_EXECUTION、STOCK_RESEARCH_PAGE、development-baseline/README、TASK；交付即停寫待驗收。 |
| 索引與Git commit | `01a10791-1f50-78f1-9805-6ed32cec3ec3`；`gpt-6-luna`／`medium` | 來源寫入[]；W4指定close及封存接手已接受，rm ownergate停止／NO-RETRY。W5文件接受／freeze後才另准刷新及coverage，commit／本地merge各待核定。 |

四者forkedFromId=null、sessionId同root；root parent=null／source=vscode，三child parent及source.subAgent.thread_spawn parent同root、depth1、agent_path依序/root/program／/root/documents／/root/index_git。三次fork_turns=none與實際配置已核，同輪沿本組ID。B1檔案為backend/app的institutional_windows.py／stock_overview.py、backend/worker/tpex_institutional_window.py、backend/tests/test_institutional_windows.py、frontend/src的types.ts／components/StockOverview.tsx／components/StockOverview.test.tsx、tools/institutional-window-preview.cjs。

App MCP connected，仍master8＋W4舊根6區；W5未索引，舊docs coverage metadata_changed後採本根原文，不輪初／中途刷新或複製索引。FINAL-1僅七個既有正式文件、淨增≤80KiB；TASK有效上限19925B（HEAD15829B＋4096B，另須≤24576B），UTF-8無BOM／LF。GPG兩段與3713B尾逐byte保留，無新附件／backup／helper／manifest。繼承零新增測試／raw／ZIP／DB／tmp／cache／pycache／log／artifact限制；正式來源8＋docs7不當附件，不把附件0稱全cache0。

## W5成果、驗收邊界與停滯

| 接手項目 | 已接受範圍／剩餘缺口 |
| --- | --- |
| 核心操作增量 | 同TPEx3105／6488新增9/24並保留9/29／9/30／10/1／10/2，兩股各五個可信原生日期表單、60 DOM net及5／20日起迄／missing0；十組source outer SUMMARY日期／1800金融原字串及兩股390×844新8/28日列可信展開。6488原生9/28清舊值及9/24恢復、兩股BUTTON held27與TWSE route拒用已有限接受；route setup不稱native市場導航，全daily子表不稱全部原生展開。 |
| 真依賴解除 | 新8/28 daily917列／兩股44金融欄、三月43 full OHLC／完整24日曆及新policy／pins已核；probe4 GET／150072B與production27 GET／3485390B獨立。Production24daily共21680全列／48selected／1056金融欄、60獨立net及2250重疊API字串逐欄核通，19表不變／guards0。數值／版本／UTC與臺北觀測集中[來源 §16](SOURCE_REGISTRY.md#16-m1-w5五截止法人來源與完整有界日曆)。 |
| 實作／測試與服務 | Python11 worker／5 real-router mock、核定Node24.19.0 noEmit／62SSR／60mock exit0；原Node20.19.4不是核定收據，mock及actual Ctrl+C原exit1保留。Owned page／五PID及children／8781、8782 listeners後驗缺席；API shutdown19表preserved／guards0，Node finalguardcounter與esbuild exit未知。入口／原失敗見[開發文件](development-baseline/README.md#m1-w5-五截止法人窗口的零落盤驗證入口)。 |
| 操作邊界 | 390×844／375×844只核原生展開、DOM及auto溢出；未驗native橫向手勢／physical canvas／Vite／production build／pending導航race。實際missing0，缺／壞8/28局部失效只synthetic API／SSR；非actual缺日native。具名可信事件、setup原錯及未驗範圍見[個股頁 §21](STOCK_RESEARCH_PAGE.md#21-m1-w5五截止法人窗口與原件追溯)。 |
| 本批分報／停滯 | 核心操作＝兩股新增9/24與五截止；真依賴＝8/28daily／24日曆／新版本→API／UI。可靠性0，stall繼承0；P6d／P6e至少2批可靠性無核心進度、更早未知，W1真依賴及W2–W5真操作支持0。換round／session／worktree／bootstrap／文書／索引或提交不重置；bootstrap／docs不是實作批次。 |

完整M1、範圍外日期／證券／TWSE、PIT／修訂、研究條件、raw保存／跨程序讀回仍缺。原工具quote／connection／os206／snapshot截斷／unsupported日期setup等失敗不抹除，詳細命令／raw在原task；不把ack或讀回當可信輸入，也不把全部toolerrors稱0。

## 前輪版本與 W4 指定外清

W4的15檔FREEZE-W4-1／六區coverage／commit／master本地FF已接受，版本為本輪基底b93c759完整SHA；正式交接／原task最終receipt覆蓋歷史pending，不為hash反覆提交。W1–W4原值及有限原生邊界保留[來源 §13–15](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)、[個股頁 §18–20](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)及Git／原task，不列W5新增成果。

| W4指定資源 | 最後已知結果／限制 |
| --- | --- |
| 四角色／terminal | Root `01a10715-32d9-79c3-9aec-c94f60dc6dee`，child `01a10719-9960-7122-8b43-782950e629c3`／`01a1071a-1dfb-7af3-ae4e-a71adb58e662`／`01a1071a-a400-7542-a56e-75becdb0d472`；terminal `term_688fc1a0-b898-4d00-96c4-1a9f8e52678d`。Actual idle／cleanmerged／owned scope後exact close一次ptyKilled=true，post orphaned／connected及writable=false／list=[]；root一次archive四角色，archived／notLoaded、historyfiles保留。 |
| 未移除worktree／branch | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-earlier-cutoff-20261004`、branch同末段名稱；225 files／4199054B保留。CLEAN-W4-RM-1的root錯誤指示profile C:/Users/YiCheng owner應YiCheng，但先前actual為SYSTEM，index在exclusive／Orca rm前gate停止，0rm／0delete、NO-RETRY；不改owner條件／role／command重試。 |
| 保留六index／DB | 前綴 `taiwan-stock-research-roadmap-m1-window-earlier-cutoff-20261004-`，suffix backend-app／backend-worker／backend-tests／frontend-src／tools／docs；六DB合44171264B仍保留，六App index未delete，root未移除所以禁止delete；master8不動。18固定aux此前absent，其他aux unknown，不擴掃。 |

Root首次archive預核誤assert關閉後root仍idle，原exit1／零archive；actual notLoaded、child idle核實後修正讀取scope，唯一archive成功，原錯留task。清理與功能驗收分報，不因W4根殘留否定有效W5操作，不關active W5或掃GPG／其他舊資源。

W3版本c6018e3及指定外清已接受：舊四 archived／notLoaded、history保留，exact terminal／worktree／branch及六DB／18固定aux缺席；owner allowlist／path比較與只讀後驗原錯、Stage／其他aux／全cache未知不追認，詳原task。W1／W2版本f716526及指定外清已接受，其餘aux unknown／logs刪前gate缺口保留。P6d 0f8ac4a／P6e 5ae84d2、獨立文件1596fe1／7b3212a為歷史，不恢復角色；GPG1232B及原NO-RETRY保持下方原文。

## 下一單一核心與版本待辦

下一M1-W6擬同兩股新增2026-09-23、保留五cutoff，原生切六截止共72 net。免費可執行候選dataset11856 `d=115/08/27` 尚未實取／准入；8月index的8/27正面OHLC僅界線前已驗，不代daily或新policy。8/27～10/2候選25sessions／最多28 GET（3index＋25daily）／53MiB；9/23候選恰20、20日起8/27／5日起9/17，不需8/26。先真來源全列／兩股金融欄及完整有界日曆、新policy／pins gate，再exact實作、獨立72net與source→API→native。無positive可執行路徑時，依證改選來源／availability、decision／execution、版本、tick／費稅／合法時段及必要磁碟保存／跨程序讀回gate齊的最小M3；仍無可交付項則等待，不空轉或降gate。

目前待root接受七文件→freeze→index刷新／coverage→核准commit及核對→另准master本地merge，均未完成。下一branch候選 `roadmap-m1-window-sixth-cutoff-20261005`，新worktree／統籌可見啟動／三新角色／正式接手尚未執行；須master合併確認後再過獨立gate，不沿本輪session冒充新輪。最終版本receipt留原task，不回寫hash反覆索引／提交；文件交付即停寫。

### 新繼承的 GPG 殘留與簽章收據更正

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
