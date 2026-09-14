# 各輪 task 協作紀錄

## 目前狀態（2026-09-14）

R33 功能、文件與輪末索引已接受。2026-09-14 使用者明確要求繼續 ROADMAP，已解除 R34 暫停；既有四個 task 已核對，待本次角色規則整理提交後，由 R34 新統籌確認接手並派工，不重複建立角色。

| R34 角色 | 已存在的 task ID | 狀態 |
| --- | --- | --- |
| 統籌 | 01a09aff-24b9-7f63-bca5-f2e4473c9759 | 已獲使用者恢復授權；待維護提交後確認接手。 |
| C034 程式 | 01a09aff-5eb3-7312-a0b7-d2435f80044b | 等待統籌分派。 |
| D036 文件 | 01a09aff-976e-7161-9226-6c09a4a94a20 | 等待統籌分派。 |
| I073 索引／Git commit | 01a09aff-dcf2-7e30-89b8-554677000732 | 等待統籌輪末分派；依 AGENTS 負責索引與提交。 |

恢復時先核對這四個 ID 的狀態，不重複建立角色。四角色模型、review、freeze、輪末索引及交接責任以 [AGENTS](../AGENTS.md) 為準；能力與優先順序以 [ROADMAP](ROADMAP.md) 為準。

下一候選是 R0-B2 的 worker 實際 evaluator 輸入 capture／保存：現有 evidence.inputs 沒有完整 close/volume，且同 key upsert 可更新內容；SignalArtifact 尚未保存 replay body。先調查轉換後完整參數、標的／市場時間、版本／結果一致性、交易與失敗語意，再決定明確 opt-in 契約。不可把 caller 提供的資料或 private evaluator 結果直接當成歷史真相。worker/API/UI/DecisionSummary、historical availability、PIT、完整 B2/B7 仍未完成；具體實作範圍由 R34 統籌調查後核定。

### 2026-09-14 索引角色 Git commit 責任補正

使用者重申「codebase 索引更新後由索引角色執行 Git commit」。核對時現行角色規則只列索引／coverage，未列 commit；R33 等歷史分派更明寫禁止 Git mutation。`git rev-list --all --count` 為 1，唯一提交 `86ee317`（2026-09-14 00:57:17 +0800）沒有 parent；本次 ROADMAP 兩份文件更新仍是工作樹差異。因此可確認先前流程沒有落實逐輪 commit，不能把索引成功或外部 manifest 當成 Git 提交。

現已在 [AGENTS](../AGENTS.md#git-結案) 補上「統籌驗收／freeze → 索引更新 → 統籌複核並核定提交清單 → 索引角色 commit → 統籌核對 hash／剩餘差異」及 receipt 要求；獨立維護亦適用。本次提交範圍為已驗收的 ROADMAP／執行清單與本次角色規則文件，最終 commit receipt 留在 task 回覆。R34 保持暫停；恢復時沿用既有 I073，分派必須帶入新責任，不沿用舊禁止 commit 的指令，也不補造 R01–R33 的逐輪提交歷史。

## 如何使用以下歷史紀錄

以下各輪保留 task 身分、已接受範圍及驗收背景。其「尚待 review」「下一輪」「禁止 Git mutation」等是當時狀態，不覆蓋上述現況或本次使用者明確授權。Temp 歸檔已清除，external 路徑與 manifest 不再保證可讀。新開發使用 [開發入口](development-baseline/README.md) 與現行測試／Git 基準，不再複製舊 Temp 環境。

## Round 33 有限 pure-rule 完整參數 capture/replay（2026-09-13，功能／文件／輪末索引已接受）

統籌已讀 R32 external `stock-r32-coordinator-review/R33_HANDOFF.md`、`FINAL_REVIEW.md`、`NEXT_CANDIDATE.md` 與 `R33_ENVIRONMENT.md`，以 task readback 核對四個正式 saved local ID，向 R32 ACK 接手；R32 已停止派工與 source 寫入。獨立 baseline 的 163 current guards 與 13 source-freeze entries，SHA256／size／Python stat.st_mtime_ns 全同。兩 protected DB 僅 bytehash。App codebase-memory inventory、status、exact coverage 與 evaluator graph/snippets 可用；metadata_changed 路徑另讀 source，累積輪末刷新。root AGENTS 無 root index。

| 角色 | Task ID | 模型／Reasoning | 寫入範圍與依賴 |
| --- | --- | --- | --- |
| 統籌／review | 01a09ab1-27d9-7de0-bce9-c1dd5266ff4f | gpt-6-astra／high | 本紀錄、external `stock-r33-coordinator-review`；獨立 baseline、scope、契約與證據 review、freeze、交接。 |
| C033 程式 | 01a09ab1-7071-7402-b4aa-d8c42f1a33be | gpt-6-astra／medium | A external 調查；B 僅新增 rule_replay.py／test_rule_replay.py；功能已主 review 接受並 freeze，外部證據 `stock-r33-c033-implementation`。 |
| D035 文件 | 01a09ab1-b90f-7c00-9d0a-5cf19afacc48 | gpt-5.6-sol／xhigh | A/B external 契約／source review 已接受；C 僅 RULE_REPLAY、docs/README、SIGNAL_ARTIFACTS、R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION 六 docs；不改 code／本紀錄。 |
| I072 索引 | 01a09ab2-0687-7f80-bd29-357ce3c59f5a | gpt-5.6-luna／medium | external `stock-r33-i072-index` 與輪末指定索引；只在 source/docs review 與 freeze 後執行，無 source 寫入。 |

初始化偏差：正式 I072 誤建 duplicate `01a09ab2-4f2c-7a40-8842-2123dcf32591`，該 duplicate 又誤建 `01a09ab2-a076-7032-a0dc-cf5d1a9def0a`。統籌 readback 已確認此鏈的兩個 duplicate 均 idle、只保留歷史待命；它們的初始化／更正曾呼叫 task 管理工具，但沒有來源／索引工作。原正式 I072 已確認本人是唯一索引角色。四個正式 ID 不變，未刪除／封存任何歷史 task。

候選為 ROADMAP R0-B2 的完整 caller-input pure-evaluator replay 可行性；先核對 evaluator 真正 keyword arguments、完整序列、missing／nonfinite、配置與 implementation binding，再由統籌決定可審查契約與後續實作範圍。既有 legacy evidence／caller refs 與 digests 不自動成為完整歷史輸入。B2 整體、B7、PIT、worker／API／UI／DecisionSummary、default 與來源 truth 仍未完成。

各角色交付 files、實際驗證 logs／exit／失敗史／限制與 freeze，由統籌 review 接受或退回同 task；不自結案／建立下一任務。所有 shell 指定 repo workdir／絕對路徑；production imports 前設定 handoff 三 STOCK 外部路徑、environment PYTHONPATH 三路徑及 PYTHONDONTWRITEBYTECODE=1，使用 bundled Python。保留既有修改；禁止 Git mutation、protected DB SQLite-open／寫入、安裝、服務／global settings、付費／帳戶／交易。

### R33 A 主 review 與 B 實作核定

C033-A 全文與 15 項 manifest 的 SHA／size／stat ns 已主核對相符（manifest `bea872408e56f9439883540a4a24ca79a58f3ad799da83c75a5c60cf5d1a7d4a`）。209 是記錄的 evaluator observations，含已設定 assertions 與探索例外，不稱 209 asserted tests；process exit 0／0.1951104000036139 秒，兩 DB 與五來源 guards 同。主獨立 37 案有預期 assertions，exit 0／0.08622710002237 秒；另三次 verified source bytes 載入私有 module 的隔離 probe，exit 0／0.11247899997397326 秒。兩個主 probe 都只驗原評估器／候選載入機制，尚非 replay 產品測試。

主核定 external `stock-r33-coordinator-review/B_CONTRACT.md`：有限 complete-argument capture/replay library，只新增 `backend/app/rule_replay.py` 與 `backend/tests/test_rule_replay.py`。固定 domain.py SHA、兩 config digest 與 CPython 3.12.14；同次驗證 bytes 編譯到每次全新 private namespace，保留完整 JSON 參數與 rule result，再做 exact rule-result 比較。嚴格格式／型別／大小／深度、null vs absent、finite arithmetic、錯誤分類與清理界線見該契約；不改舊 domain、artifact/store、worker 或資料。D035-A 獨立契約 review 仍進行，可能導致同 task 實作修正，未被提前宣稱接受；D035 尚未獲 repo 文件寫入權限，I072 繼續等待輪末 freeze。

### R33 功能接受與文件分派

主已接受 external `stock-r33-coordinator-review/FUNCTIONAL_ACCEPTANCE.md` 的有限功能，完整讀新 code/test 並核對 B_CONTRACT。三個 library API 是 `capture_rule_inputs`、`rule_replay_json`、`replay_rule_inputs`；arguments_digest 僅綁 evaluator＋arguments，bundle_digest 另含 configuration／implementation／recorded result，不能充作 input snapshot hash。report 固定六個 subject/time/history/availability/PIT/signal false flags；recorded result 是 caller claim，重封不同結果仍需實算且 exact_match=false。serialization 不呼叫 evaluator，但會 compile/exec 已驗本地 source 以核 binding。

兩新來源 SHA256：rule_replay.py `1f0e7dbd535bd4818e56eccfd08cd919e2e2bc4ce72bb64c352c22cec5e9602c`；test_rule_replay.py `2127c1d1d255f0773709f129a89742b19e4732de8085102179bf186770727cac`。舊 domain 與所有既有 code／store／worker／schema／default 不變。C033-B16 artifacts 的 SHA／size／true ns 主全核同，manifest `a3f05c4f97f3b2ff3af2017a11eac260dde46ee1e5aa5a34d708dc125f4f287e`；test-generated data/tmp 與 self 明示排除，不是全部檔案覆蓋宣稱。

- 作者 final targeted151passed＝141 新 replay cases＋10 既有 domain tests，pytest2.38s／process2.925512899993919s／exit0，165guards前後同。早期139＋12拆數來自 C033 把 graph symbol count 當 test count 的誤報，主 draft 曾沿用；此處依實際10個非參數化 domain tests及full增量更正，沒有因此改 source 或重跑。
- 作者一次 full-1：2405passed／2skipped／12414warnings，pytest355.05s／process357.94884170001023s／exit0，165guards前後同，stderr空。主核原始argv/cwd/三STOCK/三PYTHONPATH、完整logs及review當時165current SHA/size/ns全同，未重複full；未要求 -rs，所以不臆測兩個skip的細節。
- 主獨立 replay_matrix82/82（main-pure-278gs0du），exit0／1.3141427999944426s；binding_matrix25/25含12次正常並行capture（main-pure-od7z96a9），exit0／0.2700919999915641s。各自164guards同，當時new test檔尚未建立，code SHA與final相同。含外部JSON真正保存／重讀、三態及ordered reasons、完整prefix、有限中間overflow、digest/claimed result、native JSON限制、source/runtime/config拒絕、故障cleanup、shared module隔離及scoped DB/network audit。
- D035-B 對相同兩source SHA無in-scopeblocker；edge-probe03的happy/六falseflags/duplicate/nativebool/depth/success與active-context-error清理通過，5guards含兩DB不變。D035只做此獨立小probe；作者full與主82/25均保留原證據歸屬。修正後25artifacts manifest `8ab25f6a252e50782195f7d8c9023b466a59fab5b7abf4cf23d457a65a2242db` 的SHA/size/true ns已主核同。

失敗／偏差不刪除：D035-A inherited baseline因主已授權改本紀錄而exit1、pure probe首輪nested config alias回復失敗後原位修正；D035-B probe01錯report key、probe02錯expected error code，probe03修harness後pass，產品未改。主binding初次同名concurrent函式遮蔽module而exit1（24pass/1harness錯），改名後25pass；主初次D035-A manifest checker鍵名錯而KeyError，支援artifact_files後8列pass。D035 B交付曾誤寫I033與count歸屬，已改I072/C033；另傳訊單檔hash誤抄已由manifest實值更正，未影響artifact。這些不是新增產品failure或全綠attempt宣稱。

本輪後段D035與主App MCP皆回Transport closed；同引擎CLI coverage成功、原始stdout/stderr/process和App失敗分開保存，沒有重啟程序／服務／global設定。I072仍只在六docs及本紀錄review/freeze後統一更新四分區，保留metadata_changed、SQLpartial、root無index與worker舊generation限制。hostile interpreter／OS／sys.modules替換不在本功能保證內；identityguard不刪被外部替換的 unrelated entry。B2整體／歷史輸入／worker／artifact bridge／API/UI/DecisionSummary／PIT／B7仍未完成。

### R33 文件接受、freeze 與輪末索引安排

主已逐份 review D035 六檔全文／差異，接受 RULE_REPLAY 的有限 native JSON 輸入域、實際 trailing20／完整 prefix 保存、mutable detached 物件、claimed result、runtime/source 順序與不證來源的描述；ROADMAP 與執行清單的作者165／主matrix164 guards歸屬已分清。C012歷史40／41例外及原B2/B7完成條件保留，未縮小原驗收範圍。

D035 final docs-validation-06：39static checks／0fail、21新增local links/anchors、兩Python原文blocks實際外部JSONwrite/read通過、12guards前後與主review時同，兩child exit0/stderr空。74artifacts manifest `38b47331593c9d4ef41e757063cbcd7548574e8f014e7df6dc4442db7cf81050` 已主核SHA/size/true ns全同；D的manifest獨立verifier首輪誤解freeze schema而exit1，修正讀法後exit0，保留失敗史。主另於main-pure-4wnbx6pr執行最終文件兩blocks，exit0／0.12830290000420064s、165guards同，實際外部保存／重讀／cleanup、六false flags、DBabsent皆驗；不重跑backend full。

本紀錄與六docs在主final review後freeze；最終source13項與current166項SHA/size/stat ns清單、DOC_REVIEW及功能接受證據保存在external `stock-r33-coordinator-review`。I072僅在主正式freeze授權後，對app/tests/docs/worker四既有分區各一次full/persistent更新，核22exact paths、status、graph／bounded snippets及前後guards；主再独立複核才接受索引。最終index receipt、下一輪四ID與交接留在external `FINAL_REVIEW.md`／`R34_HANDOFF.md`及task回覆，不為寫回receipt反覆刷新來源。

下一輪候選是實際worker evaluator arguments的明確opt-in研究保存接點調查；需先核轉換後參數、subject/time、selection/transaction與結果一致性，不能把mutable legacy evidence或shared domain結果直接標成private pinned replay。這是有依據的工程候選，不預先核定實作。完成本輪索引review後才建立四個fresh R34角色，新統籌核ID及ACK接手；舊R33停止派工，保留所有歷史對話。

## Round 32 offline exact signal comparison（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

R32 已讀 R31 external `stock-r31-coordinator-review/R32_HANDOFF.md` 與 `FINAL_REVIEW.md`，核對四個 saved local task ID 並向 R31 ACK；R31 已確認停止派工，只補交接。R31 功能、文件與五分區索引接受 receipt 保留於 external，metadata_changed／SQL partial／舊 timestamp 限制不改寫為全域 fresh。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a09a70-69b0-7542-8787-716dda8f3558 | gpt-6-astra／high | 本紀錄與 external `stock-r32-coordinator-review`；契約、review、freeze、接棒。 |
| C032 程式 | 01a09a70-ede5-74b2-ae73-637bf6dea4cf | gpt-6-astra／medium | A external investigation、B 僅 store／新 comparison／新 test；功能接受且 freeze。 |
| D034 文件 | 01a09a70-f1a8-7f61-80a5-ef5368bb073c | gpt-5.6-sol／xhigh | A/B external契約與source review；C僅六docs（SIGNAL_COMPARISON、SIGNAL_ARTIFACTS、R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、README），不改code／本紀錄。 |
| I071 索引 | 01a09a70-f688-7642-9caf-7fc13f945bdc | gpt-5.6-luna／medium | 待主 review/freeze 後輪末索引；不做輪初／中途刷新或 source 修改。 |

主 baseline 160 paths 的 SHA256／size／Python stat.st_mtime_ns 全與 R31 相同；來源另存 external before 副本，兩 protected DB 只 bytehash。App inventory／status／exactcoverage／graph／snippet 可用；已查 docs/app 為 metadata_changed，依規則核原始來源，累積輪末刷新清單。root AGENTS 無 root index，直接讀取。

本輪候選是 ROADMAP R0-B2 opt-in offline legacy/new exact signal comparison，先獨立調查 selector、identity/date/revision、missing/ambiguity/incomparable 與 legacy confidence/time 邊界，尚未核定實作。不得預設數值或時間可比，不自動選 latest，不改 default/API/UI/worker/PIT，也不宣稱 B2/B7 或 ROADMAP 完成。

每 shell explicit repo workdir／absolute paths；production imports 前三 STOCK 外部隔離及 environment PYTHONPATH 三路徑依正式 handoff，PYTHONDONTWRITEBYTECODE=1。保留既有修改／歷史；禁 Git mutation、正式/.local DB SQLite-open 或寫入／repair／migrate／restore、服務／安裝／global settings／付費／帳戶／交易。各角色回報 files、實際 commands/logs/exits、失敗史、限制與 hash/freeze，由統籌 review 後接受或原 task 退修，角色不自行結案或開下一輪。

### R32 A review 與 B 核定

C032-A proposal/probe 已主全文 review，12 artifacts SHA/size/nsmtime 全同（manifest `7243f50c65e484df99a84d80bb0b3c5bafa44b2622bdab23d2db1592b9108d94`）；作者22checks/exit0只證 exact reader 可在合成唯讀連線工作，其研究用 private adapter不是產品實作或path/ownership驗收。首次generated-time alias fixture錯誤exit1保留。主另五種confidence分類、canonical時間／marker隔離與exact lineage probe通過，首兩次主harness錯誤（SQL欄數、缺required reason）保留；160guards只有主本紀錄改動。

主已全文 review D034-A 獨立來源契約，採兩側expected SHA必填與zero-row structured missing；不採required共用subject、missingFK寬鬆投影。核定external `stock-r32-coordinator-review/B_CONTRACT.md`：獨立library／JSON，兩個explicit external stable checkpoint與exact selectors；無numeric delta，overall固定不可比，subject/status只描述觀察。legacy缺／歧義FK、identity evidence衝突與malformed JSON hard fail；NULL evidence可unknown。所有path/alias/sidecar/hash檢查先於任一SQLite-open；new supported readonly entry重用strict validators，不走writer init／DDL／BEGIN IMMEDIATE。

C032-B寫入僅`backend/app/signal_artifact_store.py`、新`backend/app/signal_comparison.py`與新`backend/tests/test_signal_comparison.py`；D034-B先external review，不改repo docs；I071仍待輪末freeze。保留舊store writer/schema／API/UI/worker/default與正式資料，B2／B7／PIT與完整replay仍未完成。B交付待主獨立review，不以調查通過宣告產品完成。

### R32 功能接受

主已接受external `stock-r32-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`的有限功能。三source freeze：store `8efd349ada7cc1937e83a7e9f65720795216bb035c604a529d73ae436e480a91`、comparison `1f029cb8b5560cfecada8fba5f68d146fe7ce024b7875a34ec6a0e6df691282f`、test `d23336ce8fb04cdb139430e8618461c97230fbea461cdd39907bb304c87c9437`。主AST核對所有舊definition及store方法不變，僅新增readonly helper/subclass與open_readonly classmethod。104新tests，作者final targeted129pass/1skip含103新pass、1新skip與26既有pure/storepass。

作者full `test-run-digexxu3`為2,264passed/2skipped/12,414warnings，pytest280.69s/process283.578s/exit0。主未重複此full，而是核原始argv/cwd/三STOCK與三PYTHONPATH/stdout/stderr/162guards beforeafter及全部當前SHA/size/nsmtime；全部相符，stderr空，三freeze來源與該run一致。作者6,943個external artifacts主核全同，manifest `0de691d94696cb58c2245a6a9d71fe574a47f3aab20dab3b4c458357805932e6`；各run不得混加計數。

主獨立matrix-final58cases/68mode=ro connections/915SQL/exit0/process1.795605s，writer constructor/init/save bombs未觸發，per-case来源SHA/size/Unixmtime全同；涵exact roots/hash/lineage/withdrawn、同subject多root、missing/AND矛盾、detached JSON、protected/alias/sidecar/WALheader開啟前拒絕、legacy型別/FK/evidence及artifact/ancestor/binding/ref/lifecycle/attempt/run corruption。獨立fixture不import repo testhelper；沒有app.db/models/worker/default DB建立。matrix01的57pass為較早run，final新增WALheader及強化語意assertions，不跨run相加。

D034 source review的11/11 external probes無blocker，主全文核source_probe/results；含NOCASE欄位上的BINARY exact key、opaque空白key與artifact reference既有trim差異、duplicate signal/strategy、calendar/BLOB、額外PRAGMA/REINDEX/ANALYZE防寫及artifact mtime drift。只對防寫組明列store前後fingerprint，drift組刻意改external副本mtime，不宣稱全部fixture不變。A四artifact manifest主核全同（`d55f17fdc8251b2d4868e5a7f655897ab349d966c6c5d55e2b22516d43a78005`）；B五review artifacts及四frozen inputs SHA全同，manifest `4c960ae1215b5bccbad5059a769942733e9c13918d3eb5d1fe93c8df2438c58c`只涵SHA/bytes、不含mtime或完整runtime fixtures。主另核四次raw command的實際環境及exits 1/1/1/0；首次錯Python、backend-only PYTHONPATH且漏STOCK_RAW_DIR屬流程偏差，後三次已用完整隔離環境。毫秒乘一百萬不作exact nanosecond證據，主guards用Python stat.st_mtime_ns。

失敗史保留：主Phase A兩個fixture錯誤；C032-A generated alias；C032-B首輪3fail（2個CHECK擋住corruption setup、1個readonly append繼承writer alias），final前已修正。D034三次probe校正為缺tzdata、spaced reference預期與TEXT affinity預期錯誤；不是產品bug。主一次本紀錄apply_patch的ID context誤植拒絕後更正、作者apply_patch/diff組裝錯誤均保留工具history，不冒稱product failure或抹去。

本功能只讀external rollback-mode stable snapshot；任一sidecar或WALheader皆開啟前拒絕，不auto checkpoint/repair。expected SHA必填，zero-row structured missing；schema/data/FK/evidence/integrity hard fail（malformed SQL可回sqlite3.DatabaseError），不得降格missing。subject/status/linkage只描述觀察，overall comparable固定false，未算numeric delta／probability／winner／default。legacy date/text不推instant；new decision/asof caller角色與store first-generated/created metadata分開。正式/.local DB僅bytehash未SQLiteopen，無Gitmutation／服務／安裝／帳戶／交易。

C032 source/A/B全部freeze；D034-C六docs內容已主review接受，final receipt/freeze後交I071輪末索引。完整輸入replay、API/DecisionSummary/UI/worker選版、官方availability/PIT與B7仍未完成；下一候選為完整輸入replay有限契約的獨立調查，尚非實作核定。舊輪task保留；本輪結案仍須輪末索引review，不提前接棒。

### R32 文件接受與輪末 freeze

D034-C六檔完整diff已主review：新SIGNAL_COMPARISON +243行、SIGNAL_ARTIFACTS +15/-5、R0_IMPLEMENTATION +23/-9、ROADMAP +6/-4、ROADMAP_EXECUTION +9/-6、root README +3；保留C012 hash／40/41外部例外與原completion anchor。契約集中actual API／selectors／missing與hard error／rollback snapshot／confidence三分類／time roles／reason codes，不把有限comparison提升為replay、PIT或B2完成。作者final41/41檢查、144local links，主七檔147links均0bad；沒有文件階段production import或重跑產品full。

D034-C manifest `e5849f12804cee5865f3ab1f3cbd1325dd7d0b1474d30f7b85f9aa2acb00b895`的19entries（六repo docs、七external artifacts、六accepted inputs）主核SHA/bytes/Python exactmtime全部相同。主manifest helper首次只支援files/artifacts而未讀分組schema，exit1後更正；不是交付不一致。主早期link helper誤掃docs/README而非root README，160links為preliminary，已在final review與freeze清單更正；D034-C external lint的docstring import及inline reason偵測誤判也保留失敗史。

本輪10sourcepaths（三code/test、六docs、本紀錄）停止寫入。external `round-source-freeze.json`涵10source＋AGENTS＋兩protected DB；`round-current-guards.json`保留163paths供下一輪baseline，正式與.local DB只bytehash。I071在本次freeze後授權一次full persistent更新app/tests/docs/worker四既有分區，23exact partition paths及新增definitions／R32 sections需讀回；root README與AGENTS無root index，單獨保留coverage限制，不誤稱docs/README等同root README。SQL fixture已知partial ranges、metadata_changed與舊generation等限制照實保留，不做cosmetic循環刷新。最終索引receipt與下一輪四ID交接另存external，由新統籌確認後接棒，避免反覆改source造成索引循環。

## Round 31 唯讀 startup instruments identity（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

R31 已讀 R30 external `stock-r30-coordinator-review/R31_HANDOFF.md`、`FINAL_REVIEW.md`，核對四個 saved local task ID 並向 R30 ACK 接手；R30 已停止派工，只補交接資訊。R30 最終驗收與索引 receipt 保留於其 external 文件，不將歷史 App Transport closed 改寫為成功。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a09a40-e434-7463-b061-c5b3ec0f42e2 | gpt-6-astra／high | 本紀錄與 external `stock-r31-coordinator-review`；分派、契約核定、獨立驗收與接棒。 |
| C031 程式 | 01a09a41-09ef-7330-b8ac-9c7caf35be5e | gpt-6-astra／medium | A external調查；B僅readiness與新startup instrument test，主已接受並freeze。 |
| D033 文件 | 01a09a41-393b-7f71-ba4a-667ff4dacb27 | gpt-5.6-sol／xhigh | A external契約；B僅R0_IMPLEMENTATION／OPERATIONS／ROADMAP／ROADMAP_EXECUTION，主已接受並freeze；不改code／本紀錄。 |
| I070 索引 | 01a09a41-7c05-7da0-973e-4459193bab05 | gpt-5.6-luna／medium | 輪末 review/freeze 後才更新指定分區；不輪初或中途刷新，不改 source。 |

本輪 baseline 保存 159 paths 的 SHA256、size 與 Python `stat.st_mtime_ns`，來源另存 before 備份，兩個 protected DB 僅 hash 且與 R30 相符。App inventory/status/coverage/graph/snippet 本次成功；一個誤用 singular `path` 的 coverage 呼叫回傳參數錯誤，已以 `paths` 更正。app/docs exact paths 為 no_recorded_issue、metadata_changed，故核對來源；不宣稱 freshness 或全解析。待刷 app/tests/docs 路徑統一留 I070 輪末處理。

候選為 current `UNIQUE(exchange,symbol)` 混入 legacy `UNIQUE(market,symbol)`；R30 僅單一 synthetic reproduction，本輪先由 C031 independent matrix 與 D033 independent contract review 界定有限 metadata 政策。維持唯讀、單 transaction、不掃 historical business rows、不呼叫 migration row-scan helper。正式/.local DB 禁寫／repair／migrate／restore，production imports 三 STOCK 環境及 PYTHONPATH 依 handoff 隔離至新外部 Temp；無 Git mutation、安裝、服務或交易。交付須含 actual commands/logs/exits、失敗史、限制及 hash/freeze，由統籌接受或退修；角色不得自行結案或開下一輪。ROADMAP 尚未完成。

### R31 A review 與 C031-B 核定

主已 review C031-A 完整腳本／REPORT：54 shapes × 3 markers = 162 populated DB、486 direct/repeat/actual lifespan entries、1,296 memory probes，另六個 generated target explicit-write probes；完整 run03 exit0。舊 gate 150 DB接受、12拒絕，這是修改前調查，不是新功能通過。11個作者guards與162 fixtures SHA/size/Unixmtime不變，no business rows、具名migration/create_all bombs未觸發。保留run01匯入前路徑separator assertion及run02 generated fixture欄位順序SQL錯誤兩次exit1，run03才完整；不混加partial runs。

主另獨立41 shapes × 3 markers = 123 populated DB、369 entries、492 memory probes，與候選policy有216 entry差異；159主guards只有本紀錄由主修改。D033獨立25 pure-SQLite shapes/100 write probes已由主重跑，raw JSON相同、exit0，並獨立接受有限契約。正式核定為external `stock-r31-coordinator-review/B_CONTRACT.md`，C031-B僅可改readiness與新增`test_startup_instrument_identity.py`，A artifacts freeze後在新external implementation目錄工作。

核定：三個mapped欄market/exchange/symbol須table_xinfo.hidden=0；至少一個full ordered ASC/BINARY UNIQUE(exchange,symbol)，所有keyparts涉及三欄的UNIQUE都必須同canonical pair；任何UNIQUE expression保守拒絕。key-unrelated named-column UNIQUE允許（含generated extra、partial、DESC/collation），不解析predicate/generateddependency；CHECK/trigger/type/nullability/default等仍非audit。這是有限descriptor相容政策，不保證任意INSERT，也可能比R28migration recognized-current更窄。既有settlement helper、generic gate、main/models/migrations不改；B待主功能review後才文件收斂與I070輪末索引。

### R31 功能接受

主完整backend final：2,161 passed、1 skipped、12,414 warnings，pytest273.99秒／process277.218秒／exit0；唯一skip為`test_source_runtime.py:238` symlink privilege unavailable。160 guard paths之SHA/size/exactUnixmtime前後全同。主獨立matrix-final 41 shapes × 3markers = 123 populated external DB、369 direct/repeat/actual lifespan entries、492memoryprobes，zero mismatch、process7.172秒／exit0；123fixtures與160guards全同，no business-row reads，mode=ro/query_only/單BEGIN與具名migration/create_all bombs驗證通過。主seed有明確external fresh初始化；正式/.local DB只bytehash，不SQLiteopen。

作者targeted786passed/3,007warnings/pytest202.35秒／process203.427秒／exit0，15guards全同、無fail/skip。198新tests為60shapes×3markers的180policytests、12semantics與6generatedexplicitwrite，已包含單次full，不與各runs相加。主AST確認舊readiness只有新helper+singlecall；final hashes為readiness `ff1a26d5a78f35aa083bc02b08965bcc29435eb4f41a418f34ba7a696bf82fd4`、newtest `426868ff95520621e8094d4a845ca24377e0f54a677f73e44b0a14257a804940`。C031-A623與B1798artifacts均主核SHA/size/exactmtime全同，manifest分別`64f8b352f4125e319ba641e2126da9267f41d3ef445a1b8e3a5c86d632645ba1`、`919f55d73aaa7d76d9eafb055f1aab424c6213334a6f54847c42ecfe050d148e`。

D033-A四個frozenartifacts主核全同、manifest `d4b7b01fb694bb90e8de3ab8de1f368f87b456408480bc9d2ed30f3edefdf439`；25case/100writepureSQLite主重跑JSON相同。保留兩次PowerShell parser exit1、formal bytehash sharing error/secondarynull（該process雖exit0但hash不採用），其後sharedreadonlystream成功；均非產品testfailure。主誤用singularcoverage/pre-directorylisting及216mismatch訊息更正也保留。C031-B無功能或測試failure。

功能接受見external `stock-r31-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`與rawreceipts。C031已停止寫入；D033-B只四docs，本紀錄主專有；I070仍待文件review/freeze。下一具名候選依ROADMAP之R0-B2，調查opt-in離線legacy/new exact signal comparison，尚未核定實作、不代表B2/B7/PIT或ROADMAP完成；不為續輪任意增加startup custom-schema cases。保留現有使用者服務與兩DB，無重啟／安裝／Gitmutation／正式migration／restore／部署／交易。

### R31 文件接受與輪末 freeze

D033-B四docs完整124行diff已review；兩項精度修正已接受：hidden=0只證非hidden/generated相容，不保證完整writability；具名migration/helper/create_all禁止呼叫未觸發，不寫成SQL DML/commit fault injection。作者150local links／117anchors、R30/R31各3crossrefs，主含本紀錄153local links均0bad。最終18項manifest SHA/size/exactUnixmtime主核全同，SHA `d8aa386be73382eb2007f8260c09ed466d1abd869a383daff33e98338b787f54`；四repo current與after副本及兩functional sources核同。主在正式交付前並行預檢時，RUN_LOG收尾修改造成一次暫時manifest不一致，保留於`d033-b-preliminary-artifact-review.json`；最終manifest核對通過，不冒稱該預檢為產品或final交付失敗。

本輪7sourcepaths（兩code/test＋四docs＋本紀錄）停止寫入；external `round-source-freeze.json`涵7source＋AGENTS＋兩protectedDB，`round-current-guards.json`保留160paths供下一輪baseline。索引授權於freeze後交I070：app/tests/docs變更分區，以及D033 source fallback所記worker/alembic待刷路徑，合計五分區一次full persistent更新；26exactpaths與新helper/newtest/R31sections讀回。App本轮至此成功；如失效走同引擎CLI，不殺程序或修改global設定。SQL已知partial、rootAGENTS無index與metadata_changed限制均須保留，不為cosmetic freshness循環重刷。

I070完成不直接代表整輪結案；主尚須raw index receipt／coverage／snippet与freeze複核，再於external FINAL_REVIEW及正式R32_HANDOFF记录接受與四新task IDs。索引後不回寫source receipt，避免刷新循環。下一輪新統籌ACK後R31停止派工只補交接；舊task保留，不封存或刪除。

## Round 30 唯讀 startup settlement identity（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

R30 已讀 external `stock-r29-coordinator-review/R30_HANDOFF.md` 與 `FINAL_REVIEW.md`，核對四個已存在新 task ID 並向 R29 明確 ACK。R29 已確認停止派工；本輪由新統籌負責。R29 12 個變更來源與 15 個 freeze paths 的驗收／輪末索引已接受；本輪 baseline 複核 15/15 SHA、size、exact mtime 不變，不重跑歷史索引。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a09a14-9d2a-75c0-8daf-edee29517cf1 | gpt-6-astra／high | 本紀錄；external `stock-r30-coordinator-review` baseline、review 與交接。 |
| C030 程式 | 01a09a14-f6cd-73a2-8a3b-8e950542ca85 | gpt-6-astra／medium | A 僅 external `stock-r30-c030-investigation`，獨立 synthetic DB 調查；來源寫入待統籌明確核定。 |
| D032 文件 | 01a09a14-fabe-7f11-be3d-91f56a6f58af | gpt-5.6-sol／xhigh | A 僅 external `stock-r30-d032-contract`，獨立 finite startup 契約；不改程式或本紀錄。 |
| I069 索引 | 01a09a14-fffb-7eb2-a86e-f507297dcc28 | gpt-5.6-luna／medium | 只在輪末 review/freeze 後更新指定分區；現在待命，不做 baseline 或中途刷新。 |

輪初 App MCP inventory 為八區；app/tests/docs ready。exact readiness/main/settlement helper/test 與五份文件 coverage 為 no_recorded_issue、metadata_changed，故依規則直接核來源；graph/snippet 已定位 readiness 入口。tests 仍有既知 SQL fixture partial（4、50–51、70、105），root AGENTS 無 root index；不宣稱完全 coverage。待刷新 app/tests/docs，統一由 I069 輪末處理，不做 cosmetic refresh loop。

外部 `round-baseline.json` 保留 158 個 guard paths，originals 只備份來源、不複製正式資料庫。免費公開資料與本地測試；production imports 前三個 STOCK 路徑及環境 PYTHONPATH 隔離至新外部 Temp，shell explicit repo workdir。正式/.local DB 禁寫、禁 repair/migrate/restore；保留既有修改與歷史資料，無 Git mutations、服務或安裝。

本輪先獨立調查 mixed/noncanonical settlement unique 與真實 lifespan；R29 的單一 inherited fixture 不作完整證明。維持 mode=ro、query_only、一致 transaction、不掃描歷史 rows、不執行 DDL/repair；不能直接呼叫 migration helper 的 row-scan。C030/D032 交付檔案、實際命令／日誌／exit、失敗、限制及 hash/freeze 後由統籌接受或退修；角色不得自行結案或啟動下一任務。ROADMAP 尚未完成。

### R30 A 接受與 C030-B 核定

C030-A 獨立 75 synthetic DB（25 shapes × 三 marker families）、150 direct／actual main.lifespan 與 450 fresh-memory INSERT probes，exit 0；79 個明列 guards及各case DB不變。主已全文review報告／腳本並核159/159 artifacts SHA、size、exactmtime，manifest SHA `2662e0ca3402ee94bfff3750dff205cb267319fc39aef7cdf28b39213f905ee6`。調查未有測試失敗；coverage呼叫一次singular path schema error後改paths成功，沒有Transport closed或索引刷新。主另獨立87 DB／261 direct-repeat-lifespan檢查重現現行gate缺口，authorizer禁止business rows；158個輪初guard只本紀錄變更。A是既有行為調查，不是新功能通過。

D032獨立review接受finite範圍後，主核定 `stock-r30-coordinator-review/B_CONTRACT.md`。C030-B只可改 `backend/app/database_readiness.py` 與新增 `backend/tests/test_startup_settlement_identity.py`；既有tests、main、migration helpers與其他table generic gate不改。只要求settlement至少一個full ordered real-column ASC/BINARY pair；所有touch signal_id/horizon的unique都必須同canonical pair，任何unique expression保守拒絕。允許duplicate canonical pair、無關ordinary unique（含partial）及nonunique extras。

此為有限結構相容性政策；DESC/reversed並非一概會阻擋第二horizon。任意CHECK／trigger、無關unique語意、generated dependencies不在gate，不保證任意INSERT成功。維持readonly metadata、單transaction、no historical row scan／DDL／repair，不呼叫migration row-scan helper。B另存 `stock-r30-c030-implementation`，A維持freeze；功能待主diff／matrix／完整backend驗收，D032文件收斂與I069索引尚未分派。

### R30 功能接受與文件收斂

主已接受C030-B兩檔，完整diff與AST確認既有readiness除新helper及單一conditional call外語意不變。最終source SHA：database_readiness `6082c987550d2b9254b4ddde7f3f48fcf1895dd0db531de675a4cb61d6ef8b09`；新test_startup_settlement_identity `4e7c0d96e15e0458861fcf2b583d93577dd9e2d93d1bb18a697161ffad72d840`。687/687 B artifacts SHA/size/exactmtime核同，manifest SHA `aff342af18243b6dc672a7d8dd75c3d0c3fbf2f5fe1325e2d221b5cc38dbfa8d`。

主full-final為1963 passed、1 skipped、12414 warnings、pytest226.12秒／process229.344秒、exit0；唯一skip `test_source_runtime.py:238` symlink privilege unavailable。159guards前後SHA/size/exactmtime全不變。主matrix-final為87 populated DB／261 direct-repeat-lifespan／261 memory INSERT probes、5.078秒、exit0，159guards及87case DB不變。authorizer禁止business rows，readonly/單BEGIN及migration bombs通過；memory FK刻意off，只驗unique行為。126新tests包含在full內，不與其他runs混加。

作者targeted01為664 passed／474warnings／58.46秒（process59.673秒）、exit0、80guards不變，無fail/skip；新126tests由120policycases（40shapes×3markers）與6memorysemantics組成。A與B均未有產品測試失敗；A一個coverage參數schema error修正已保留。主初次列D032外部目錄時尚未建立，該command exit1不是產品失敗。主probe-01的mismatches是修改前與待核契約差距，matrix-final才是最終驗收。

D032-A完整契約review接受；9個artifacts SHA/size核同，主重跑20case pureSQLiteprobe與rawJSON完整相等，manifest SHA `0aaf8084d088a15ec0ed5dade6093ec17302b8031a6b5876bd88c5f2e9ded2c8`。已修正87/261歸屬及final20數字；其11path readback只有10unchanged，主專有本紀錄並行變更已明示，不取代主159guards。D032-B僅四docs R0_IMPLEMENTATION／OPERATIONS／ROADMAP／ROADMAP_EXECUTION，本紀錄仍主專有；程式freeze，I069待最終文件review/freeze。

精確key關聯只看index_xinfo key parts；unrelated unique之partial predicate即使提及signal_id/horizon也不解析，generated dependency不解析。任意CHECK/trigger/unrelatedunique不在audit，readiness成功不保證任意INSERT。三STOCK環境與PYTHONPATH隔離，正式/.local DB僅hash保護、不SQLite-open；未有服務/安裝/Git mutations/部署/PIT/truth或完整ROADMAP驗收。完整接受與限制在external `stock-r30-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`。

下一候選是instruments startup mixed identity：主one synthetic current pair+UNIQUE(market,symbol)被readiness放行，memory第二exchange同symbol遭unique拒絕；原DBSHA `e5a2a48c9d7004db361381977c0b4533c679dce5ff1bc08c2d9ce0d5b9318e79`／size430080／mtime_ns1789292143806536600不變。只有一個externalprobe，非正式DB診斷或完整matrix；本輪不擴code範圍。待本輪索引接受後由下一輪新統籌自行調查與界定。

### R30 文件接受與輪末 freeze

主已完整review四docs差異並接受D032-B；修正五項精度：120=40shapes×3markerfamilies，每案內另走三entries；作者6memorytests擁有trigger/unrelatedunique寫入對照；主matrix只設具名migration/helper/create_all bombs，非DDL/DML/commit注入；identity只看keyparts、不解析predicate；noncanonical拒絕是descriptor政策而非所有shape皆有實際衝突。R27/R29歷史保留，R30目前狀態與instruments單一候選分開。

四source＋各before/after與13artifacts共25fingerprints SHA/size/exactmtime核同；D032 manifest SHA `53a7f1da29abc12be1e4f4f74b9a1d5a738abc5e59d843e1fdd905b8af40cae4`，完整DOCS.diff SHA `8f0a3db5ba4360910824d0ccbb4771484e3dbe7b1f07f6efd99e39f0899df816`。作者四docs驗147local links／114anchors／3R30crossrefs，0bad，pwsh child final exit0。保留兩次atomic patch context mismatch、same-process exitreceipt空白、WindowsPS5 UTF8解析exit1的wrapper失敗；皆未改功能source，最終pwsh驗證通過。no-index diff exit1是expected差異，不冒稱testfailure。

本輪共7個source paths變更：readiness、新startup專用test、D032四docs與本紀錄。此處停止來源寫入並freeze；exactmanifest與主scope/link review在external `stock-r30-coordinator-review`。I069只准輪末對index-plan指定app/tests/docs三分區各一次full persistent更新，16exactcoveragepaths含knownSQLpartial；rootAGENTS無index。metadata_changed不做cosmeticrefreshloop，工具freshness與解析限制須保留。輪末索引最終receipt及新四taskIDs放external FINAL_REVIEW/R31_HANDOFF，避免為回寫來源造成重刷循環。

本輪接受功能與文件，不預先宣稱索引成功或R31已建立。待主複核索引、freeze不變後才依AGENTS建立四個全新角色，正式handoff由新統籌ACK後接手；舊R30停止派工。ROADMAP未完成，下一候選須獨立調查，無跨輪固定統籌或空轉輪次。

## Round 29 legacy signal_settlements 身分重建（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

新統籌已讀 R28 external `stock-r28-coordinator-review/R29_HANDOFF.md` 與 `FINAL_REVIEW.md`，核對以下四個已存在新 task ID，並向 R28 明確 ACK 接手。R28 功能、文件與 I067 四分區 App 索引已接受；14/14 freeze 指紋不變。R28 自此停止派工；不重建或 fork 角色。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a099df-d436-7ab1-a427-46c73426f75d | gpt-6-astra／high | 本紀錄與 external `stock-r29-coordinator-review` baseline/review/handoff。 |
| C029 程式 | 01a099e0-2570-76d2-913a-d0cb343a624c | gpt-6-astra／medium | A 僅 external `stock-r29-c029-investigation` 合成調查；程式／測試寫入待主 review 後界定。 |
| D031 文件 | 01a099e0-28b4-7b81-b649-3d5d35cc494b | gpt-5.6-sol／xhigh | A 僅 external `stock-r29-d031-contract` 獨立契約；不改 code 或本紀錄。 |
| I068 索引 | 01a099e0-2cda-7d92-b56a-ed050bbd1b0a | gpt-5.6-luna／medium | 待輪末來源與文件 review/freeze 後更新指定分區；不做輪初或中途刷新、不改來源。 |

輪初 App MCP inventory 八區可用，app/docs ready；本輪已查 docs/TASK_COORDINATION、ROADMAP、app/migrations、alembic/env、0001 的 coverage，皆 no_recorded_issue／metadata_changed，故依規則直接核來源並累積輪末刷新。graph 已定位兩份 settlement rebuild。根 AGENTS 無 root index，直接讀取。索引沒有 refresh loop；R28 的已知 SQL partial 與 metadata freshness 限制仍保留。

主 baseline 保存 156 paths（154 source/config/doc 與兩 DB），before/ 僅複製來源；排除 67 個歷史 data/backups。正式與 .local DB 的 SHA／size／exact Python integer mtime_ns 均與 R28 交接一致。全部 shell explicit workdir `C:/Users/YiCheng/Desktop/taiwan-stock-research` 且 absolute paths；production import 前三 STOCK 路徑隔離至 fresh external Temp。禁止正式/.local DB migration/repair/restore、服務重啟、依賴安裝或 Git mutations，保留既有修改與歷史資料。

依 R0-5 候選先調查 legacy signal-only → ordered `(signal_id, horizon)` identity，C029 以手建合成 DB 驗真實 fallback/Alembic Engine/inactive Connection 入口之 schema/data/default/FK/index、custom／scratch/TEMP、DDL/marker fault rollback/retry；D031 獨立 review canonical preservation 與 fail-closed 邊界。R28 未重現此分支缺陷，不能由 instruments 證據外推。本階段未授權 repo 程式／規格寫入，待兩份 A 證據 review 後才定 B 範圍。

各角色須交付檔案、實際 command/log/exit、失敗史、限制、hash 與 freeze，回報現任統籌接受或退回同 task；不得自行結案或啟動下一任務。ROADMAP 未完，免费公開資料與本地工程持續授權；不外推正式部署、任意歷史/custom schema、PIT 或資料 truth。

### R29 A 調查接受與 C029-B 核定

C029-A 222 cases（3入口×FK0/1×25 shapes及12 before/after faults）已由主接受為有限調查。72故障全命中、完整main/TEMP schema/rows/FK snapshots回滾並sameDBretry成功；既有R28交易邊界已保護這些路徑，未重現rollback缺陷。成功路徑則實證custom欄位/default/CHECK/index/trigger/outbound/action與single main或TEMP scratch資料遺失；mixed identity、Alembic0001/0006假claim可成功返回但仍阻擋第二horizon。simultaneous main+TEMP scratch與受測TEMPshadow為拒絕且回滾，不一概稱資料損毀。

主review investigate.py/verify.py、全72fault snapshots/retries及1,347/1,347 artifacts SHA/size/exactmtime，manifest SHA `f12dee40fc218d5e09f719226c46f9e3e4cfffe1b8fc8666594eb15b2ff63947`。作者1,668 observation assertions含驗證缺陷，並非產品全部通過。主另獨立20案覆蓋canonical、extra、scratch、mixed、afterDROP×兩入口×FK0/1，結果相符；156paths比對僅本紀錄改變，兩DB不變。A receipt、原始腳本/streams/snapshots外存`stock-r29-coordinator-review`及`stock-r29-c029-investigation`。

D031獨立核心契約已review接受；C029-B限七檔：新app/settlement_identity_migration.py、app/migrations.py、alembic/env.py、alembic/versions/0001_schema_v1.py、新tests/test_settlement_identity_migration.py、tests/test_news_json_defaults.py、tests/test_migration_recovery.py（均在backend）。後兩僅補news old005與fixedSQL loader的empty current settlement prerequisite；原SQL/JSON fixture、six-table manifest、news payload/斷言不改。A原證據freeze，B另存`stock-r29-c029-implementation`。

採finite known9/14欄legacy signal-only成功轉ordered pair，missing/NULL horizon→20為明確轉換，其餘known payload/id保留；unsupported custom與任何legacy inboundFK拒絕。current no-rebuild驗required14欄、identity/PK/essential NOTNULL/default/exactoutboundFK/NULL/duplicate等有限target，允許不破壞essential語意的extra current objects；非完整custom-schema audit。scratch/TEMP與任一markerfamily known0001–0006搭配absent/legacy/invalid在create_all前拒絕；unmarked absent可fresh。shared helper不擁有transaction，保留R28 runner boundaries，postflight在commit前；markers仍在同transaction，不誤稱全部postflight先於markerDML。完整contract在external B_CONTRACT.md。

功能尚未接受；待三入口/FK0/1有限矩陣、故障rollback/retry、必要回歸與主獨立review。D031 final A artifact後仍待B文件分派；I068仍只輪末。

### R29 C029-B 功能接受

主已接受七個程式／測試檔，全文review helper、新tests與其餘diff；7source freeze及8,214/8,214 B artifacts SHA/size/exactmtime核同，manifest SHA `1fad7cc5d1874050d50f8658a8c35bc02b954a51bce7e6afaecc8b863526acbf`。fixture AST核對只有兩helper各新增兩個empty prerequisite CREATE，以及第三news direct-slice setup改走補齊loader；原assertions與R10固定SQL/JSON不變。Git/source inventory只有兩個授權新檔，文件收斂前僅七code/test加本紀錄變動。

主final full backend：`1,837 passed／1 skipped／12,414 warnings`，pytest185.52秒、wrapper188.562秒、exit0；skip明列`test_source_runtime.py:238`的symlink privilege unavailable。158個保護路徑前後SHA/size/exactmtime不變，final440個新settlement tests均包含在此單次full。主matrix-02為408/408、23.609秒、exit0；special-01為14/14、2.297秒、exit0，共422獨立cases。主84個before/after create/copy/drop/rename/兩index/firstmarker fault全部exact rollback及sameDBretry；special補current inbound、quoted default與FK0/1 activecaller。兩run各158guards亦不變。

失敗史保留：作者targeted01 407pass/1fail，第三news setup漏前提，主授權同檔最小適配後修正；targeted02 428pass為追加12latefault前；targeted03 462pass/407warnings/21.21秒包括final440新tests（其中96fault、144falsemarker）與news/recovery。作者full01 1836pass/1fail/1skip/12414warnings/199.31秒，因external launcher只sys.path未設PYTHONPATH，子程序找不到worker；v2 corrected targeted04為38pass/1skip/1.16秒。作者未再跑full，不把subset合併成fullpass；最後單次完整通過來自主full-final。主matrix-01則是外部harness新增signal漏列名遇additive欄數變動，修成explicitid後matrix-02通過，非production缺陷。

成功限known9/14legacy、canonical target列序、known typedpayload/id保留、missing/NULL horizon→20的有意轉換及指定預設值／identity/FK。unsupported legacy custom或依賴、scratch/TEMP及known0001–0006假claim在修改前拒絕。current只驗finite essential結構/types/defaults/identity/FK/rowconditions；保留具名extra objects，不驗任意CHECK/trigger語意或完整secondaryindex存在。helper不接管transaction，R28 runner boundaries保留。普通FKrestore與activecaller保全已回歸，無crash/diskfull/commitfailure/concurrency/attached/nonSQLite/PIT/truth或正式DB操作驗收。

D031-A 19個artifact與9probechecks已review，兩處不覆寫A_CORRECTIONS澄清legacy inbound拒絕範圍與helper最終檔名。D031-B現在僅准R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS四docs；本紀錄仍主專有，七source freeze，I068等文件review/freeze後才刷新。完整接受與失敗證據在external `stock-r29-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`。

下一輪具名候選為read-only startup settlement mixed identity gate。主對D031 frozen A的`fallback-mixed.db`呼叫readiness得到None，而唯讀backup到memory後第二horizon被signal-only UNIQUE拒絕；原檔430080bytes、SHA `f06e4c48d24e98599d607f02c33d7b7b914b7aba10b458ced7cefae9b022f291`、mtime_ns1789288706145483100全不變。此為一個external fixture觀測，非正式DB診斷；R29未改startupreadiness，不外推本輪explicit migration驗收。需待本輪文件/索引接受後交下一輪新統籌界定範圍，保留R27唯讀／不掃歷史rows契約。

### R29 文件接受與輪末 freeze

主已全文review D031-B四文件diff，退回兩項精度後接受：Phase A為寫入marker卻未取得正確target identity，不是已轉為target；legacy nonunique indexes可缺席，存在時才限known ordinary shapes，重建後建立兩known indexes。D031保留初稿與review-1，只修R0／OPERATIONS指定三處，ROADMAP與ROADMAP_EXECUTION freeze hash不变。主核四docs與diff manifest相符，記錄11個external artifacts；DOCS_MANIFEST SHA `a15f550669b60b25855972f6992cc99cb45a7298a9f44ef1a0c591cdda1ae6d0`，diff SHA `2fe5c2163fe61029f0abf5c384c10137ca6ab64cecdffdaf3ba1b57617ea95b8`。五份含本紀錄文件之147local links與3newanchors通過，0bad。程式未改，不重跑已接受full。

最終source scope為10個既有檔變動與2個授權新檔，共12檔（7code/test、4D031 docs及本紀錄）；所有其餘baseline source／config與兩DB指紋保留。七code/test及四docs已freeze，本紀錄現在一起freeze。I068僅更新app、alembic、tests、docs四canonical partitions與指定23paths coverage；knownSQLpartial及metadata_changed限制照實保留，不擴root/frontend/worker、不作cosmetic refresh loop。

15-path source／doc／AGENTS／兩DB freeze manifest、I068原始mutation outputs、主readback及最終驗收receipt外存`stock-r29-coordinator-review`與`stock-r29-i068-index`，不為回寫receipt反覆改repo造成索引循環。索引不取代功能驗收。待索引／freeze複核接受後，才建立Round30四個全新task，由新統籌ACK四ID並接手startup mixed-settlement identity候選；R29屆時停止派工，只補交接事實，不自行封存舊輪。

## Round 28 legacy instruments 重建與失敗保全（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

R28 已讀取 R27 external `R28_HANDOFF.md`／`FINAL_REVIEW.md`、核對以下四個新 task ID 與三角色待命，並明確向 R27 確認接手；R27 已回覆停止派工。R27 功能、文件、I066 五分區 CLI 索引及 17/17 freeze 複核已接受，具體限制仍依其外部 FINAL_REVIEW，不把索引成功當全域 freshness。沒有重建或 fork 本輪角色。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a0999e-1dc3-71c3-8d94-9d9d254eb082 | gpt-6-astra／high | 本紀錄與 external baseline/review/handoff。 |
| C028 程式 | 01a0999e-968b-7911-97b2-be003e95687b | gpt-6-astra／medium | A 僅 external `stock-r28-c028-investigation` 合成調查；B 待契約 review 後明列程式及測試範圍。 |
| D030 文件 | 01a0999e-9a3e-71f2-9190-480991788cd3 | gpt-5.6-sol／xhigh | A 僅 external `stock-r28-d030-contract` 獨立契約；B 待明列文件，不改 code 或本紀錄。 |
| I067 索引 | 01a0999e-9fbf-7c13-9a6f-945d4d113734 | gpt-5.6-luna／medium | 僅輪末 review/freeze 後更新指定分區及 external receipt；不改專案來源。 |

R27 起初觀測統籌 App cwd metadata 異常；本 task 的預設／顯式 Get-Location 與 git 根目錄核對均為正確專案路徑、exit 0，後續 read_thread 亦正確。不宣稱修改或修復 App 設定；每次 shell 仍顯式指定專案 workdir、讀寫與 patch 用絕對路徑。輪初 App MCP 八區 inventory 可用，docs/app/alembic ready，相關 docs、migrations/config/db、0002/env coverage 為 no_recorded_issue／metadata_changed；故直接核來源並累積輪末刷新。AGENTS 無 root index，直接讀取；I067 不作輪初或中途刷新。

依 ROADMAP R0-5，先以外部手建 legacy market/symbol schema 真正進入 instruments rebuild，調查成功保全、copy/drop/rename/index/marker 故障回滾、FK 狀態、custom schema 與 scratch-name collision；D030 獨立提出 preservation／pre-mutation fail-closed 邊界，待主 review 才決定最小修正。R27 saved-original 已是 exchange/symbol，不能將其 replay parity 或 R11 news-only atomic 證據外推本分支。本階段不宣稱已重現缺陷或接受程式修正。

主 external `stock-r28-coordinator-review/round-baseline.json` 保存 154 paths 指紋（152 source/config/doc 與兩 DB），before/ 只複製來源，另排除 67 個歷史 data/backups；正式與 .local DB 的 SHA/size/mtime_ns 與交接一致，沒有複製或操作歷史 DB。各 production import 前須設三 STOCK 路徑到全新 external Temp；禁止正式/.local DB 寫入、migration、repair、restore、服務重啟、安裝、git stage/commit/reset/clean，保留全部既有修改與歷史資料。

各角色須回報交付檔案、實際 command/log/exit、所有失敗與修正、限制及 freeze，由現任統籌 review 接受或退回同 task；不得自行結案、派工或啟動下一任務。免費公開資料與本地測試持續授權；正式部署、完整 historical/custom schema、PIT、來源 truth 及 ROADMAP 整體未接受。

### R28 A 調查接受與 C028-B 核定

C028-A 的 57 個手建 mixed-era legacy cases、30 個保留失敗 DB 後的副本 retry 已交付；主獨立核對 395/395 artifacts SHA/size/mtime、各案完整 schema/typed rows equality 與 4 個 false-recovery 結果。Alembic Engine／inactive Connection 共 20 個受測故障都留下差異，fallback 10 個故障完整回復；21 個 custom success 分別丟失受測欄位、index、trigger、default、CHECK、outbound FK 或同名 scratch 資料。四個 rename fault retry 未報錯且 marker 到 head，但 instruments 仍缺失、scratch 與 child FK violations 留存。作者 202 個 recorded-evidence assertions 通過；不是修正後測試。主另以獨立手建表、實際 Alembic 0001→0002、FK 0/1 的六案重現 custom loss、after-drop 與 after-marker rollback 失敗，命令 exit 0 只代表觀測腳本完成。

D030-A 獨立來源及 probe 契約已 review，採 finite canonical legacy 成功、unsupported custom preflight fail-closed。主退回兩處文字精度：FKcheck 不受 enforcement 0/1 影響，及修後故障 retry成功與歷史殘破狀態拒絕須分開；不改已重現結論。R11 news-only atomic 與 R27 具名歷史 replay 保持原驗收邊界。

C028-B 只准新 `backend/app/instrument_identity_migration.py`、`backend/app/migrations.py`、`backend/alembic/env.py`、`backend/alembic/versions/0002_instrument_exchange_key.py`、新 `backend/tests/test_instrument_identity_migration.py`；不改 0001／其他 revisions／news helper／models／db／config／舊 tests／docs。B 證據另存 `stock-r28-c028-implementation`，A 原 artifacts freeze 不覆寫。

成功範圍是 exact known legacy 欄位／defaults／PK／full market+symbol unique 與已知 ordinary indexes，保留現行九類 application inbound FK 中當時存在者的 rows、definitions 與 instrument IDs；缺 exchange/industry 仍由既有 additive path 補齊。額外 custom／混合或缺失 identity／partial 或 expression unique／scratch collision 均拒絕；current full target且無legacy為 no-rebuild，extra objects不被重建。missing instruments＋scratch 必須在 create_all／0001 之前拒絕，不自動 salvage。0002/helper 不得 commit/rollback/切 pragma；runner 擁有完整 chain與marker transaction，FK OFF 在 transaction前，whole-run FKcheck前後驗證並恢復原0/1。active external transaction拒絕且caller持有權不變。

驗收要求三入口／FK0/1、真實 known child、key enforcement、missing欄位、custom拒絕、before/after DDL/marker與later-revision故障、完整rollback與same-DB retry，另回歸news/schema/readiness及全backend。此時尚未接受程式修正；D030未獲repo文件寫入，I067仍待輪末。

主另經 index/coverage/snippet 核實 `test_news_json_defaults.py::_old_005_engine` 的 instruments 只有 id/symbol、沒有 identity，是 news 專用合成 slice。核准 C028 第六路徑的最小 fixture prerequisite 適配：只改該函式 instruments CREATE/INSERT 為完整 canonical current 身分，保留 id1/symbol2330，所有 news schema/rows/self-FK/custom objects/fault/assertions 不改。不為讓旧fixture通過而豁免 neither-identity gate，也不回寫 R11 歷史驗收。

### R28 C028-B 功能接受

主已完成六檔來源/diff review，獨立核六份source及4,800個B artifacts SHA/size/mtime全部一致；source-freeze manifest SHA為 `3edb72132099cc746ea0309de1e9bbea62bf78f056ae0db123fd0906e877c0b5`。News舊fixture獨立AST核對只變兩個instruments CREATE/INSERT expressions，其餘AST相同。全部386個新parameterized cases已納入最終完整backend驗收。

主 `full-final`：1,397 passed、1 skipped、12,029 warnings，pytest163.09秒／process166.047秒／exit0；156個保護路徑測試前後指紋相同。該次輸出未要求skip原因，不冒稱另有skip-specific驗證。主 `matrix-frozen` 206案及 `special-frozen` 16案共222個獨立手建DB/public-entry案例全通過，分別10.437秒／1.515秒／exit0，各156個保護路徑亦不變。前206為18shape×三入口×FK0/1、8fault×before/after×三入口×FK0/1及2active-caller；96fault均確認命中、完整schema/typed rows rollback及same-DB retry成功。後16補TEMP parent/scratch、錯誤head＋legacy/missing，以及fallback兩markerfamily的拒絕。完整接受檔與原始streams/receipts/snapshots外存 `stock-r28-coordinator-review/FUNCTIONAL_ACCEPTANCE.md` 及上述目錄。

既有FK原值在普通成功/故障恢復；刻意使restore本身失敗時保留original exception與restore cause，不宣稱該案恢復成功。known inbound成功範圍僅九個application table中實際存在的simple instrument_id→instruments.id、NO ACTION/NO ACTION/MATCH NONE、非deferrable；作者以九表實際mapped rows/descriptors驗證。known watchlist DEFAULT0及ORM無server-default各自保留；current fullidentity不重建並保留受測extra column/index/ownedtrigger。TEMP shadow、occupied scratch prefix、reversed/mixed/partial/expression identity與unsupported custom均拒絕；兩markerfamily內已知0002–0006 claim搭配absent/legacy，在create_all前拒絕，不自動salvage。這不是完整任意marker或schema readiness驗證。

作者歷史：run01 102pass；run02 292pass/1fail，原因是測試helper在刻意restore失敗案的無條件inactive斷言遮住原例外，後只調整該案直接驗exception chain，普通故障connection-reuse斷言保留。run03 440pass；run04 464pass/3017warnings/168.46秒在最後marker修正前；run05最終hash的249pass/1191warnings/51.38秒是subset，沒有宣稱作者最後重跑全部386。全部原始失敗/中間結果保留，不能把命名matrix-final的中間目錄當最終驗收。D030原兩處契約文字錯誤已以不覆寫A_CORRECTIONS補充接受，七個manifest所列entries核同。

C028-B功能接受並保持六source freeze。D030-B現在僅准R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS四文件；既有external draft不覆寫，交付另存delivery子目錄。本紀錄仍主專有，I067仍等待文件review/freeze。沒有正式/.local DB migration/repair/restore、服務重啟、安裝或Git mutation。SQLite有限schema之外、真crash/disk-full/commit failure/concurrent writer、attached schemas、其他legacy rebuild（包括signal_settlements）的成功custom保全、正式部署/PIT/ROADMAP整體均未接受。

### R28 文件接受與來源 freeze

主已全文review D030-B四文件diff，退回R0 §8.7三處精度：57/30調查作者應C028、未migration須限定正式/.local DB、逐組FK shape驗證不能寫成每table恰一組的count gate。D030將第一版保存delivery/review-1後只改指定三行；其餘三docs freeze hash不變。主複核修正diff及五份含本紀錄文件的144local links、3newanchors，0bad／exit0。程式未變，不因純文字修正重跑已通過backend。

六code/test與四D030 docs內容均接受並停止來源寫入，本紀錄現在一併freeze。I067只在輪末更新canonical app/alembic/tests/docs四分區，包含本輪metadata_changed後直接讀取路徑；既有SQLfixture partial ranges與root AGENTS無root index限制保留，不擴root/frontend/worker index。D030完整外部receipt、I067 actual mutation/raw outputs/status/coverage與主最後14-path freeze複核另存外部evidence／task回覆，不再反覆修改來源造成索引循環。索引成功不替代功能驗收。

ROADMAP仍有獨立工程。下一輪候選為signal_settlements legacy signal-only→signal/horizon重建之成功custom保全及failure邊界；現有app fallback與Alembic0001 graph/source仍見固定columns、scratch DROP IF EXISTS與有限index重建。本輪未做該分支缺陷重現，不將R28 instruments或whole-run health evidence外推。待本輪最後索引/receipt/freeze複核接受後才建立R29四個全新task，由新統籌先外部合成調查與獨立契約review；正式DB/服務仍不操作。

## Round 27 啟動資料庫邊界與歷史資料保全（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

R27 已讀 R26 external `R27_HANDOFF.md`／`FINAL_REVIEW.md`，逐一核對以下四個新 task 的 ID、cwd 與待命回覆，並向 R26 統籌明確回報接手。R26 功能、文件與 I065 輪末索引已接受，12-path freeze 另有獨立核同；R26 舊統籌停止派工，只補交接資訊。本輪不重建角色。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a0996c-ea7c-7933-8ba0-22fc296c22d0 | gpt-6-astra／high | 本紀錄與 external baseline/review/handoff。 |
| C027 程式 | 01a0996d-b6d1-7a23-af2a-35f1d126f249 | gpt-6-astra／medium | A 僅 external temp 調查／副本；待 review 後明列允許程式及測試路徑。 |
| D029 文件 | 01a0996d-bbc5-7170-83d8-4800e40122d4 | gpt-5.6-sol／xhigh | A 僅 external temp 契約；待 review 後明列文件路徑，不改 code 或本紀錄。 |
| I066 索引 | 01a0996d-c22f-7fe3-a5ae-8f4b98e9bc77 | gpt-5.6-luna／medium | 輪末 review/freeze 後更新指定 canonical store 及 external receipt，不改來源。 |

輪初 App MCP inventory 八區可用，app/docs ready；docs 指定四路徑、main/config 皆 no_recorded_issue／metadata_changed，直接核來源並累積輪末 refresh。候選 database.py 為 missing，graph 已定位實際 db.py 的 init_db → upgrade_database 與 main.lifespan。tests 既有 SQL partial ranges 4-4、50-51、70-70、105-105 保留。沒有輪初 index mutation；根 AGENTS 無 root index，直接讀取。

依 ROADMAP R0-5，先調查外部 preview startup 從無 Alembic version 到 0006 的實際歷史資料／schema 差異，再定最小 startup 契約和修正。C027-A 取得唯讀來源的一致外部 snapshot、比對 R26 before/data/stock.db；D029-A 獨立界定 empty／legacy／stale／head／invalid 等 startup 邊界。正式 DB 與 .local DB 禁寫，不 migration、repair、restore 或重啟使用者服務。R26 原 baseline 不覆寫；本輪 observed baseline 分開保存。production import 前核 config 並設 STOCK_DATA_DIR、STOCK_DB_PATH、STOCK_RAW_DIR 到全新 external temp；只用既有依賴，不 install/global/account/purchase/trade/deploy/git stage/commit/reset/clean。

各角色必須回報交付檔案、diff、實際 command/log/exit、失敗、限制與 freeze，由現任統籌 review 接受或退回同 task；不得自行結案、派工或啟動下一任務。本轮尚未接受功能修正，不宣稱全面 historical/schema parity、正式 migration/restore、B6、PIT 或 ROADMAP 完成。

### R27 A 調查接受與 C027-B 核定

統籌已獨立以 stdlib SQLite mode=ro/query_only backup API 取得外部 old/current snapshots，20 個既有表、622,399 列 typed multiset（含重複數）全部相同，無舊欄位移除。schema 差異只有 Alembic version table/PK 新增與 news_items 雙 JSON SQL `[]` defaults／DDL quoting；兩副本 integrity ok、FK violations 0。原件/current/.local 三來源查驗前後 SHA/size/mtime_ns 相同。C027-A 再把原 baseline 外部副本真正 replay 0001→0006，21 表完整 typed rows、sqlite_schema 與 PRAGMA descriptors 等於 current snapshot。主 review 腳本／隔離命令，16 個 A artifacts 指紋核同；`c027-a-review.json` 與主 `independent-parity.json` 外存於 stock-r27-coordinator-review。這僅接受具名保存原件的 recorded SQLite parity，不是正式 migration/restore/deployment 或市場/PIT 驗收。

D029-A 決策表已由主接受。C027-B 僅准 main.py、新 database_readiness.py、新 test_database_readiness.py，及 test_api.py/test_product.py/test_backfill.py 內五處 lifespan fixture 適配；不改 db/config/models/migrations/worker/revisions。API lifespan 改做 mode=ro/query_only、一致 transaction 的有限 structural readiness：缺檔、empty、無版本、舊/未知/多列/畸形 markers、不可讀 SQLite 或 schema mismatch 均拒絕，不自動 create/migrate/repair。明確 init-db 及既有 worker 路徑保留。

有 Alembic table 時須恰一列 current head，fallback 不得覆蓋 stale/malformed Alembic；無 Alembic 時須 exact distinct 六枚 known fallback。兩者並存可為 valid head 加從 0001 開始的 intact known prefix（長 1–6，實測 current 五枚）；存在但空、缺口、未知或畸形 fallback 拒絕。markers 仍不足以通過：另驗全部 ORM mapped real tables/columns、required PK/非 partial unique/FK identities 與雙 news JSON defaults，允許不破壞必要契約的額外 schema。本輪不做完整 SQL equality、row/deep-integrity scan 或修復探測，不把有限 readiness 當全面 schema/資料有效性證明。config import 的 mkdir、API request handlers 的既有寫入與 SQLite WAL sidecar 限制均保留。

驗收須有隔離實際 lifespan/health、marker/schema 故障矩陣、missing 保持缺席、受控副本成功/拒絕前後指紋不變、fresh Alembic/fallback6/current-prefix 成功、明確 CLI init-db 真執行與既有 migration 回歸。此時 B 尚在實作，未作功能接受；D029-A 完整外部交付後等文件分派，I066 仍待輪末。

### R27 C027-B 最終功能接受

主完整 review 六路徑 diff 與新測試，C027-B 已接受。API lifespan 改呼叫 check_database_readiness；成功為 None，失敗為 DatabaseReadinessError 與具體文字，沒有新增 A 草案提案中的 public status/code。其他 db/config/models/migrations/revisions/worker 未改。既有五處 HTTP fixture 只換 readiness bypass，專屬 startup tests 真正驗邊界。

原「所有 partial unique 皆拒絕」在 historical replay 造成已知合法庫拒絕。主已 graph 核 app/alembic0001 的 _ensure_request_key_index，並獨立 SQL 證明 nullable full UNIQUE 與 request_key IS NOT NULL partial 都允許多 NULL、拒絕重複非 NULL；較窄 subset 則漏放。只核准 canonical ix_ingestion_runs_request_key、ingestion_runs 單欄 request_key、完整 stored CREATE UNIQUE INDEX DDL 及精確 IS NOT NULL predicate 的窄例外，whole anchored match 不能被 comment/string 偽造；其餘 partial 仍拒絕。不改既有 DB 或 migrations，原 historical 拒絕與137pass證據保留。

主 startup_review.py 為39cases／41subprocess calls（含兩個 explicit seed initialization）exit0；真正 lifespan/health 加 migration/repair/create_all bombs，涵蓋 historical current 成功、pre-startup copy 拒絕、marker/schema faults、prefix、URI、lock、custom extra schema及partial spoof。每案SHA/size/mtime或不存在狀態相同，另四保護檔不變。主 full backend：1011passed／1既有Windows symlink privilege skip／9089warnings，pytest74.68秒／process80.203秒／exit0；133paths（docs/子樹排除）測試前後指紋不變。沒有 frontend 或已運行服務重啟驗收。

作者 final targeted150passed／4070warnings／exit0，76newcases＋74existing；三個實際獨立subprocess驗A historical replay的新副本和explicit worker.cli init-db後repeat readiness/health。主核6source＋697B artifacts、A16artifacts frozen指紋相同。首61pass/1observer參數錯誤、outer harness曾exit0但actual pytest exit1、137pass後historical拒絕與一次shell quoting parse失敗皆保留。完整證據外存 stock-r27-coordinator-review/FUNCTIONAL_ACCEPTANCE.md，不抹去初次失敗。

D029-A 原oracle28pass/1fail因讀取正在變更的current main；後29pass版容許baseline或candidate，不用來證historical startup。另exact saved baseline SHA/AST oracle主獨立10/10、exit0。D029曾短暫改原frozen六檔，後恢復原bytes/hash/size/mtime；主核復原六檔與supplement五entries相同，這是恢復狀態、不稱從未變更。supplement記明實際finite schema scope、不假造statuses及partial窄例外。

D029-B已核定七文件：OPERATIONS、ROADMAP、ROADMAP_EXECUTION、R0_IMPLEMENTATION、DATA_SOURCES、backend/README及root README；後三僅更正head/current DB/startup過時口徑，歷史驗收不改寫。本紀錄仍統籌專有。主功能接受不等於文件與輪末索引完成，I066仍待全部review/freeze。正式庫、本地庫未被本輪migration/repair/restore；現有preview服務未重啟，不能稱其已載入新startup gate。

### R27 文件接受與來源 freeze

主已全文 review D029-B 七文件 diff，退回四處來源輪次、migration 執行範圍、Sep11 原靜態盤點歷史與 readiness scan 限定措辭；修後核對原件為 R27 before/main，R26 保存的是舊 DB，並保留已完成的具名全列／integrity／FK 證據。D029 final60checks／0fail／exit0；七repo docs＋before/diff/verification/review-1 receipts共27files指紋主核相同。主另驗8份含本紀錄文件的171個local links、3個新Round27 anchors，0bad。最初receipt保存的PowerShell New-Item參數失敗及後續成功保留；沒有程式變動，不因純文件校正重跑已通過的backend。

程式與文件均已接受並停止寫入；本紀錄現在一併freeze。I066接手輪末canonical app/tests/docs更新，並統一刷新本輪metadata_changed後直接讀取的alembic/worker分區；root/backend README與AGENTS沒有對應root index，限制須明列，不以新rootindex擴scope。最終receipt、統籌freeze複核與下一輪四ID外存task回覆／交接檔，避免為索引結果反覆改來源。

ROADMAP仍有可做工程。下一輪候選是legacy instruments重建分支的failure rollback與歷史/custom schema保全：R27 graph觀測0002 upgrade有重建前／finally commit，固定欄位copy與scratch table drop，fallback也有對應分支；尚未做故障重現，不稱已證缺陷。R27具名舊庫已是exchange/symbol identity，replay並未走market/symbol legacy重建，不能外推本輪parity或C011 atomic evidence。待本輪輪末索引複核接受後，才建R28四個新task，由新統籌先外部隔離調查／契約再決定最小修正；正式DB/服務仍不操作。

## Round 26 TWSE 公司行動身分相容（2026-09-13，功能／文件已接受並 freeze；輪末索引另核）

R26 已核對 R25 external R26_HANDOFF、FINAL_REVIEW（SHA ca5a6d6213cbce007b0975ed7aed6ce5152e346d29a2482c60a9fc74d16d9c87）及四個 task ID/title/cwd/待命狀態，向 R25 明確確認接手。R25 C025-B/D027-B/I064 已接受，舊統籌停止派工及來源／索引寫入；R26 不重建角色，沿用使用者指定 local 共用目錄。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a09820-168b-74b0-8d9b-5b616eccdc53 | gpt-6-astra／high | 本紀錄與 external baseline/review/handoff。 |
| C026 程式 | 01a09820-65d1-7190-89b9-af7d4a52054f | gpt-6-astra／medium | B api.py、新 test_twse_action_classification.py；已接受並 freeze。 |
| D028 文件 | 01a09820-6add-7791-a8d9-3b6291dc248a | gpt-5.6-sol／xhigh | B SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION、R0_IMPLEMENTATION；不改 code。 |
| I065 索引 | 01a09820-701f-7882-9095-63c705573a5d | gpt-5.6-luna／medium | 待輪末 review/freeze 後更新 store 與 external 完整收據，不改來源。 |

輪初先查 App MCP inventory 8、docs/worker ready、五份 docs 與 sources.py/pipeline.py coverage，均 no_recorded_issue/metadata_changed，故直接核來源並累積輪末刷新。根 AGENTS 無 root index，直接讀取。一次候選 price_adjustments.py coverage 為 missing，未據此宣稱有該來源。沒有輪初 index mutation。

統籌獨立保存 Temp/stock-r26-coordinator-review/round-baseline.json 與 before/：151 TOTAL＝149 source/config/docs＋2 DB；沿前輪 manifest 加 cached/untracked inventory，67 historical data/backups 排除未操作。正式與 .local DB 的 SHA/size/mtime_ns 與 R25 一致。保留全部既有修改。

依 ROADMAP 資料正確性優先，本輪先處理 TWSE type-only 修正會改 action identity、造成雙列及 factor 平方的具體缺口。先確認官方 type 語意、來源事件身分相容、同日多列／衝突／重跑／歷史保留規則，再以 actual consumer 隔離實證界定最小修正；不把候選直接當已准修法。不重做 R21–25 已接受項目，不將 paid assumed Rp、quote/P 或 fixture 宣称完整公司行動／PIT。

各角色須向現任統籌交 files/diff/commands/rawlogs/exits/失敗/限制/freeze，由統籌 review 接受或同 task 退修，不自行結案、派工或啟下一輪。正式／.local DB 禁寫；production import 前三 STOCK env 設全新 externalTemp；只使用既有依賴。不得 install、global/service、account/purchase/trade/deploy、git stage/commit/reset/clean。程式與文件 A 暫不寫專案來源，索引僅輪末。

### C026-A review 與 C026-B 核定（尚非功能接受）

統籌全文讀 A investigate/revision/isolation/harness 與報告，確認 actual collect 的 naive type-only refetch 將一列變兩列、兩 consumer 因子 .99875→.9975015625000001；維持 identity 則一列不變。synthetic cash revision .125→.25 的成功 reuse 零 fetch、flush 後故障 rollback、force 同 action ID/new raw ID、舊 raw/evaluation 保留均已隔離實證。harness 沿用 C025 標籤／Sept4 過時註解，actual DAY 已依保存列 remap，assert 不是 Sept4 gate；不稱 PIT。A 正式來源未改，final guard 與 freeze 外存。首輪讀取與 fixture selection 失敗保留。

主另以 standard-library oracle 驗 R24 保存 TWSE body 與 Swagger SHA/size：68 列為息63／權息3／權2，當次 Code+Date duplicate0；12 個官方欄位沒有穩定 event ID，單次無重複不證跨快照唯一性。因此不准 type-only、更名舊列或按同日合併。

C026-B 僅准 backend/app/api.py 內小型唯讀 helper 與 instrument_detail corporate_actions 投影，以及新增 backend/tests/test_twse_action_classification.py。每列 additive source_action_classification 固定 kind/label/raw(field=Exdividend,value=原string或null)/reason；known map 息→ex_dividend/除息，權→ex_right/除權，權息→ex_right_and_dividend/除權息，否則 unknown/未知。source exact twse、instrument exchange exact TWSE、nonempty mapping details、exact Code/Date/Exdividend nonblank strings、Code.trim=instrument.symbol、Date.trim 嚴格ASCII ROC7合法日且=action_date才准。只以 trim 三 exact enum 判斷，raw.value不trim。known reason trusted_twse_exact_fields 只代表本地details語意一致，並非raw authenticity。

reason precedence：unsupported_source → invalid_details → missing_official_field → alias_conflict → identity_mismatch → unknown_raw_value → trusted_twse_exact_fields。股票代號／證券代號、除權息日期、除權息 aliases僅驗衝突，不作fallback；None或blank string忽略，其他非string拒絕。別名採同一strict Code字串／ROC7日期／三exact enum，trim後與官方值一致才相容；不另擴展ISO日期或除息等文字alias。未知extra keys忽略。保持 action_type/DB唯一鍵、raw/details、worker/factor/schema/version/frontend不變，不新增DBquery/raw檔IO、不dedupe、不修正式庫或聲稱UI已接線。

作者需測 exact/unknown/priority/alias/date/source與交易所symbol隔離、actual API legacy payload除新欄位外一致、同日多列保留、沒有ORM mutation或N+1、wholecollect兩consumer仍不變。主獨立review及完整backend通過後才接受；D028完成契約提案後等待B文件分派，I065仍待輪末freeze。

### C026-B 接受與 D028-B 收斂

主已全文review api.py helper、additive欄位與新test，接受API-only具名範圍。作者149passed/335warnings/pytest2.19s/process3.171s/exit0，新module104cases；初次103passed/1failed是同Session decision cache的18/10比較，改fresh Session後通過，production不為此更動。wholecollect/reuse0fetch/force同action/raw、score/tracking .99875、old evaluation保留與integrity/FK已驗。saved actual adapter+helper Sep13得6列(4息1權1權息)，Dec31離線future replay68列(63/2/3)，不稱PIT。

主129checks exit0：35boundary完整shape/raw/priority/Mapping/ASCII日期/alias、68savedrows、baseline AST舊instrument_detail對新API、3instrument各old/new19queries、同日三type/交易所symbol隔離、50筆cap/排序、持久化全欄不變、duplicate既有平方factor未變與7pathguard。此主測試是direct migrated fixture API，wholecollect證據歸作者integration。主完整backend935passed/1既有Windows symlinkskip/9024warnings/pytest54.31s/process55.453s/exit0，測试期間111TOTAL=109code/tests/frontend來源+2DB guard全不變，docs排除。C026-B 2source+268artifacts、A107artifacts已主核指紋相同並freeze。

D028-A 18artifact指紋主驗相同，獨立標準函式庫oracle26/26完整object equality經主另跑exit0。初版oracle精度/alias/raw等缺口修正與初始檔保留。B五doc分派為SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION及R0_IMPLEMENTATION（後者僅正式DB現況更正），不改code/本紀錄；收斂API契約、功能證據及下述外部DB狀態，歷史驗收不改寫。

### 外部預覽 task 造成的正式DB狀態變化（不算R26驗收成果）

用量中斷後使用者明確要求繼續，C026/D028均在原task恢復。D028與C026的guard捕捉正式data/stock.db由輪初SHA74a34389dbfa65429d27ea41bc9deca2a132808f10093e2ffde98665d96232d6／296054784bytes，變為SHA3a21772050b3053557c0798876cc0aa1efe024fcbdce5ab44e35e6abf12da018／296366080bytes／mtime_ns1789278339459271200；.local原SHA不變。原baseline保留，不能稱整輪DB unchanged。

主read_thread核對另一task「啟動專案預覽目前畫面」01a0994a-f42c-7f40-9aef-218d01917dab：使用者要求開畫面，該task於13:45:33以.venv啟uvicorn pid32440/29720，startup log實際執行0001→0006。main.lifespan→init_db→upgrade_database/defaultdata路徑與source相符，早於C026首pytest約103秒；C026所有productionimport三STOCK環境都在externalTemp。主mode=ro/query_only=1只讀核正式head0006_news_json_defaults與21tables，讀前後SHA/size/mtime不變。external-startup-task-evidence.json與external-db-observation.json保存證據，不宣稱全面歷史row/schema parity或正式migration/repair已驗。

本輪不恢復／寫入正式DB，不停止使用者服務。外部startup亦產生root UI logs，保留且另列，非R26程式來源。作者finalizer與D028verification初exit1如實保留；接受本輪隔離功能不把外部migration納入成果。之後測試期guard使用各自測前觀測值，與輪初baseline分開。

AppMCP恢復後check_index_coverage回Transport closed，主依AGENTS使用同引擎CLI唯讀coverage成功(exit0)，新test not_tracked依fallback直接讀；無kill/restart/global設定及中途刷新。I065尚待所有來源freeze，再更新app/tests/docs涉及分區、核extra已讀路徑及既有SQLpartial/rootmissing/metadata_changed限制。

### D028-B 接受與輪末來源 freeze

五doc完整差異與worddelta已主review；退回的saved adapter/helper與wholecollect混称、D028-A/C026-B證據歸屬及正式prior current不是0001均修正。主139localfilelinks/6newanchors通過；作者136links/6newanchors/0bad/0trailing，validator與各檔diff --check exit0。5source+6external artifacts共11件SHA/size/mtime_ns主驗相同，接受並freeze。作者WindowsApps python shim exit1、JS backtick SyntaxError及rg quoting exit1均披露，沒有為此改production或重跑full。

最終scope為151TOTAL輪初→152TOTAL現況：143原件不變，7授權既有source變更（api.py、五docs、本紀錄）、1新增test及1已歸因外部正式DB變化；67歷史backups排除未操作。root UI logs為另一preview task產物，保留但不計入source。現在停止所有專案來源寫入，12個changed/root/DB關鍵路徑的freeze另外保存；正式DBfreeze採升級後觀測值，原baseline不改。

I065只在此freeze後更新canonical backend-app-dacl-test、backend-tests、docs三分區，核8個變動來源及其餘已讀路徑。worker與frontend未改，只核coverage/graph相符；如發現實際source/index不同再回報，不為metadata_changed單獨擴張來源修改。保留既有SQLpartial、rootREADME/AGENTS無index及metadata_changed best-effort限制；App若仍closed用同引擎CLI，保存完整args/stdout/stderr/exit，無重啟或global變更。主複核index與12pathfreeze後才接受本輪並建R27四新tasks。

ROADMAP未完成。下輪可優先以本輪migration前完整baseline DB原件與外部current一致副本，唯讀查資料保全／schema差異，並核API startup自動migration邊界後決定最小安全工程；不因preview啟動就當正式migration已驗，也不自動准正式repair/restore或停止使用者服務。paid/fullcapture/PIT與其他既有待辦保留。最終索引／交接收據外存，避免回寫本紀錄形成刷新循環；R27新統籌核四ID確認接手後R26停止派工，只補交接。

## Round 25 TPEx 現金股利精度（2026-09-13，程式／文件已接受並 freeze；輪末索引另核）

R25 統籌已核對 external R25_HANDOFF.md、FINAL_REVIEW.md、R25-task-ids.json，並逐一 read_thread 核對以下四個 ID/title/cwd/待命，向 R24 明確確認接手。R24 C024-B/D026-B/I063 已接受，11/11 freeze 檔案 SHA/size/mtime_ns 接手前一致；R24 停止派工與來源寫入。沿用使用者指定的現有 local 共用目錄，不重建角色、不 fork/worktree。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a097fc-5345-7072-946d-ced978c7ce19 | gpt-6-astra／high | 本紀錄、external baseline/review/handoff。 |
| C025 程式 | 01a097fc-a4e6-7bd0-b2ea-19efc44d6a6d | gpt-6-astra／medium | B：sources.py Tpex cash slot、既有 mapping test 期待、新 precision test；已接受並 freeze。 |
| D027 文件 | 01a097fc-a9e6-7823-a669-59666733121c | gpt-5.6-sol／xhigh | B：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION 四文件；不改 code。 |
| I064 索引 | 01a097fc-af87-7282-a2c1-5c3dd5441a70 | gpt-5.6-luna／medium | 只在輪末 review/freeze 後更新索引與 external receipt，不改來源。 |

輪初 App MCP inventory 8、docs/worker ready；五份 docs 及 worker sources.py/pipeline.py coverage no_recorded_issue/metadata_changed，按建議直接核來源，輪末累積刷新。一次 coverage 呼叫缺 paths/scopes 已修正，未做輪初 index mutation。根 AGENTS 無 root index，直接讀取。

完整 external baseline 為 Temp/stock-r25-coordinator-review/round-baseline.json + before/，包含150 TOTAL=148 source/config/docs +2 DB，從 R24 manifest 加 cached/untracked inventory 保存，67 historical data/backups 排除且未操作。正式 data/stock.db SHA 74a34389dbfa65429d27ea41bc9deca2a132808f10093e2ffde98665d96232d6、.local/data/stock.db SHA 87453d7b29954b6d506f8020b8987f321aa6749ce9bc24fbef695dd3874b8d02，與交接一致。

依 ROADMAP 資料正確性優先，A 階段調查 R24 未結的公司行動 paid/precision 與 TWSE source semantics，需真實欄位契約及 actual consumer 隔離重現後才核准最小有用修正。不得重複 R24 mapping 或擴充無證据 capture；若 paid 缺資訊，照實保留，不憑 fixture 宣稱完成。所有角色交 files/diff/commands/logs/exits/失敗/限制/freeze，回報現任統籌 review 接受或同 task 退修，不自行結案或啟下一任務。

正式與 .local DB 禁寫；production import 前三 STOCK 環境變數設全新 externalTemp。保留既有修改；不得 stage/commit/reset/clean、install、服務/global/帳戶/採購/交易/部署。來源修改範圍待 B 明確分派，索引僅輪末更新。

### C025-A review 與 C025-B 核定範圍

主已閱讀 C025-A 外部六案例 whole collect/migrated SQLite/two-consumer script、results 與報告，以及 D027 cash-contract-proposal.json。saved TPEx 5278 現金股利0.26618165與息值0.266182有差，兩controls等值；cash一slot修正保留同action身份。TWSE type-only counterfactual會新增corporate_action/ex_dividend兩列並把.99875平方成.9975015625，故不核准該簡單修法。paid反例只證缺口，不採external注入price_factor為正式實作。

C025-B只准sources.py TpexAdapter.fetch_actions cash slot：CashDivdend → CashDividend → 現金股利 → 息值，沿用_text first-nonblank及parse_number一次；空值可fallback，非空invalid不換低順位值。既有test_tpex_corporate_action_mapping.py只更新被取代的cash期待/註解，另加test_tpex_cash_dividend_precision.py。raw/details/order/count/date/type及R24ratio/reference不變；TWSE/sharedfactor/schema/version/capture/正式DB不改。此為normalized每股現金股利來源優先修正，不證官方quote/tick進位完全一致。作者targeted及主独立review後才可接受；D027文件B尚待功能證據，I064仍待輪末freeze。

### C025-B 功能 review（已接受並 freeze）

production diff只有一行cash鍵順序；R24test只更新5278期待及說明，另有檔尾空白行移除；新precision test22cases。主全文review diff及新test，first-nonblank/singleparse、R24ratio/reference、identity/raw等保留。作者四模組final101passed/1236warnings/pytest3.88s/process4.824s/exit0；初次2failed99passed保留，原因是synthetic leading-dot不符合既有parser及trackingclose原本round8。修正測試期待，production parser不改，factor仍rel0/abs1e-12。

主full backend831passed/1skipped/8873warnings/pytest57.19s/process58.391s/exit0；skip為既有Windows symlink privilege。110TOTALguard=108 code/tests/frontend sources+2DB，SHA/size/mtime_ns全部unchanged，docs不在guard。Python3.12.14/Alembic1.19.2既有安裝，無新增依賴。

主29checks exit0：baselineAST旧method對actualnewparser12selection、saved3rows正反序/cutoff/Fraction、新migration0006SQLite同actionkey更新、two consumers精度、舊evaluation在direct action update/newsignal evaluation後保留、exchange/symbol隔離、previousbarfallback、integrity/FK與6pathguard。主是direct_upsert_action(rawFKNone)，actualwholecollect/rawFK/rawbytes/successzero-fetchreuse/force同action/rawID/twoconsumer證據歸作者B。均非PIT或evaluation immutable。

D027-A六savedofficialbodySHA/size與14checks由主獨立重跑exit0；actualstdout在external stock-r25-coordinator-review/d027-oracle-actual.json，作者oracle-result.json為summary。D0276artifactfreeze+B3sourcefreeze由主核9/9unchanged。R25無newnetwork；daily實際07:01:09+08觀測與彙總receiptgeneration分開。C025-B功能驗收在external FUNCTIONAL_ACCEPTANCE.md，文件/輪末索引仍待review。

cash修正不證官方Q/tickrounding完全相同；paid4541 .07391303不等pro-rata/1000 .05913042676，A assumedRp synthetic僅機制演示。TWSE type-only會雙算；previousbar只是既有MarketBar close。paid需明確資料/品質/版本/持久化策略，schema migration為可能方案而非唯一機械必需。正式舊資料repair、歷史artifact可重現、capture/registry/PIT及整體ROADMAP仍未完成。

### D027-B 文件接受與輪末 freeze

主已核四文件完整diff與131localfilelinks/6新增anchors，全部通過；D027作者128local links/97anchors/0broken/0requiredmissing/0trailingwhitespace，exit0。作者SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION四檔SHA/size/mtime_ns與主review snapshot4/4相同，接受並freeze。原R24cash precedence保留歷史，新增R25取代關係；SOURCE_REGISTRY集中契約/證據，操作及ROADMAP記摘要，不擴大ROADMAP完成範圍。

D027-B evidence在external Temp/stock-r25-d027-docs/D027-B-REPORT.md、doc-review.json、D027-B.diff、freeze.json；四doc+三externalcontentartifact作者驗7/7freeze，manifest selfexcluded。作者曾兩次apply_patch context mismatch，均atomic/no partialsourcewrite；一次唯讀PowerShellfingerprint formatting parser error；後續修正成功。四個git diff --no-index exit1代表有差異非失敗。C025 initial2test failures及主初次coverage參數/外部目錄讀取問題已保留，不把最終通過冒稱零嘗試失敗。

最終scope baseline150TOTAL=148sources+2DB；143originalpathsunchanged，7authorizedexistingchanges+1newtest，current151TOTAL=149sources+2DB。正式與.localDB均SHA/size/mtime_ns未變；67historicaldata/backups排除未操作。八個改動來源為sources.py、兩tests、D027四docs與本協作紀錄。來源與README/AGENTS/兩DB共12個關鍵路徑由主freeze，後續不再回寫來源。

I064只在本freeze後更新canonical worker/tests/docs三分區，覆核本輪8source paths及其他已讀/metadatachanged paths；rootREADME/AGENTS無rootindex照實保留，不另建rootindex或修改ignore。app/models.py等未改source只作coverage/graph相符複核，有真實過時再報主。原SQLpartial範圍、metadata_changed best-effort限制不抹除。index結果最後存externalreceipt及主finalreview，避免為回寫本段再次改snapshot。主接受I064後才建立R26四新tasks/完整交接；R26新統籌確認接手前不讓新角色開工，R25交接後停止派工與source寫入。

## Round 24 公司行動資料品質與後續工程（2026-09-13，程式／文件已接受並 freeze；輪末索引另核）

R24 已讀 R23 external R24_HANDOFF.md／FINAL_REVIEW.md／R24-task-ids.json，逐一 read_thread 核四個既有新 task ID/title/cwd 並向 R23 確認接手；R23 C023-B、D025-B、I062-B 已接受及 freeze，舊統籌停止派工。共用既有 local root，不重建角色、fork 或 worktree。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a097d2-3661-71a2-9366-cc80177a0d0f | gpt-6-astra／high | 本紀錄與外部 baseline／review／handoff。 |
| C024 程式 | 01a097d2-7542-7480-a39d-8f999cd10b87 | gpt-6-astra／medium | C024-B：sources.py 的 Tpex.fetch_actions 兩 mapping 與新 test_tpex_corporate_action_mapping.py。 |
| D026 文件 | 01a097d2-7a14-7fa0-ad79-e10faf39057b | gpt-5.6-sol／xhigh | D026-B：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION。 |
| I063 索引 | 01a097d2-7f6b-7343-80a2-5f193d7225d7 | gpt-5.6-luna／medium | 僅輪末 review／freeze 後刷新及 coverage；不改來源。 |

輪初先查 App codebase-memory inventory 8、docs status ready、ROADMAP／ROADMAP_EXECUTION／TASK_COORDINATION／SOURCE_REGISTRY 與 worker sources／pipeline coverage；皆 no_recorded_issue／metadata_changed，按建議直接核來源，輪初不刷新。外部 Temp/stock-r24-coordinator-review/round-baseline.json 與 before/ 以 R23 兩份 manifests 加 cached/untracked inventory 保存149個原件總數（147來源＋2DB），含根/backend/frontend設定；67歷史 data/backups paths排除且不操作。兩DB SHA與R23一致。R23交接口頭「149source+2DB」與實際manifest計數不同，本輪使用實際149TOTAL，不外加兩DB。

依ROADMAP資料正確性優先，先調查既有公司行動來源的ratio／paid-subscription／reference-price欄位及實際consumer，據具體官方證據與隔離重現選最小有用工程，不預先核准修法，不重開R21–23、不預設generic capture。角色需交files/diff/實際commands/logs/exits/失敗/限制/freeze，由當輪統籌review接受或同task退修；不自行結案或啟下一任務。正式/.local DB禁寫；任何worker/app import前三STOCK環境設新externalTemp、使用既有bundledPython與Alembic。保留既有修改，不stage/commit/reset/clean，不改服務/依賴/global/帳戶/採購/交易/部署。


### C024-A 調查與 C024-B 核定範圍（尚非功能接受）

官方TPEx Swagger明確StockDividend為貨幣權值，StockDivdendThousandShares為每仟股無償配股；ClosePriceBeforeExRightsDiviend是除權息前收盤價，OpeningReferencePrice是開始交易基準價。D026保存官方原bytes/headers/receipt；主已獨立讀schema與3列body，actualTpexAdapter/factor加Fraction oracle重現前收誤用。3列皆2026-09-14，9/13 as-of零列，9/14屬synthetic future-asof離線重播；不可冒稱已觀測未來交易。原HTTP SHA db1f6e359e2bf39dd2d202e35da147c6d44c5b3585ae5d41dbcbe80ceb190975與adapter重序列JSON SHA b3e002141f371728568a5e4d4f3a736999ad8ab9039f60b85962b7379e8b78dd分開。

C024 external actualcollect/fresh0006migration/rawFK/successreuse零call/samekeyforceupdate及tracking與scorehistory兩consumer，savedcash與schema非零配股證據已由主讀script/log；非零配股不是live樣本。TWSE既有小數ratio對照不支持除100猜測，保持不改；有償認購仍缺engine，不用窄mapping冒充完成。quote/P候選涉及進位及有償價位語意，不採用。

核定C024-B僅sources.py中TpexAdapter.fetch_actions及新test_tpex_corporate_action_mapping.py：ratio以StockDivdendThousandShares／本地中文alias每仟股無償配股parse_number後非None除1000；reference以ClosePriceBeforeExRightsDiviend／本地中文alias除權息前收盤價parse_number。移除StockDividend／權值／無償配股率當ratio，以及OpeningReferencePrice／開始交易基準價當前收的fallback。其他cash優先序、identity/date/asof/actiontype、numberparser、raw details/provenance/order/count不變；缺reference沿用既有previousbarfallback。不新增explicit factor、paid公式、strict解析、TWSE、共用factor、schema/version/capture或正式修復。程式交實際候選parser及隔離integration/failures/guard/freeze後由主獨立review，現在未宣告功能完成。


### C024-B 功能 review（已接受，程式 freeze）

主全文review對輪前原件diff與34cases專用test：production僅Tpex.fetch_actions三行net新增及兩mapping replacement，沒有其他程式改動。作者dedicated34passed/389warnings/pytest1.62s、final3modules79passed/1094warnings/pytest3.32s/process5.738915s/shellwall5.962533s/exit0，B無failedattempt；128TOTALguard=126source/config+2DB，127精確不變且僅sources.py授權改動，新test另計。A階段兩fixture前置失敗(非numericindustry、todaywarning導致partial)、D026目錄未建立及初版script未另保存限制詳外部C024-A.md，未冒充B失敗。

主full backend809passed/1skipped/8731warnings/pytest56.26s/process57.5s/exit0，Python3.12.14、existingAlembic1.19.2；109TOTALguard=107code/tests/frontend來源+2DB SHA/size/mtime_ns全相同，docs不在此guard，無安裝及主full失敗。主獨立26checks exit0：baseline AST取真舊Tpex.fetch_actions與currentmethod對照，11mapping cases僅兩normalized欄位差異；保存full3rows原序與反序各3個Fraction現金因子oracle，另9/13futurecutoff；fresh0006 migratedSQLite含TPEx6204/TWSE6204/TPEx6205，direct_upsert_action(rawFK=None)驗sameactionid/old evaluation保留、新signal兩consumer19/22因子/身分隔離/缺前收既有barfallback；paid仍缺、integrity/FK及5pathguard。此independent不是wholecollect/rawFK測試，作者B三integration及主full另提供actualwholecollect/migration/rawFK/reuseforce證據。主獨立無failedattempt。

成功forceFalse零fetch保留舊normalized值；valid same-key forceTrue可更新同CorporateAction/rawFK重用。collect不重算舊evaluation，但顯式evaluate同signal可upsert，不能宣稱評估永久不可變。非零free/paid是schema synthetic，3savedcash皆9/14future-asof；cash精度/quote進位/paid/fullcoverage/PIT/正式repair保留。主另外核7savedHTTPbody尺寸與SHA全部一致；D026共7directGET與webdiscovery讀取分開記，非7次全部網路活動。

sourceSHA8381ab59b4ddc462f354ccbab5642f2dd2c84b2b4b3a3cdf8f45a7886c0e0211；newtestSHAbe1fd88112b560a17408693edc7b7e33ecd82869a9d5ca76ea87db05db2cb9a8，主full後與作者freeze相同。證據位於Temp/stock-r24-coordinator-review及stock-r24-c024-investigation。程式已接受且停止寫入；D026-B只四docs收斂，待主finalreview後整輪freeze及I063更新。


### D026-B 接受與輪末 source freeze

主已完整review四docs對自己的輪前原件diff，並核D026-B-REPORT.md、doc-review.json及D026-B-freeze.json。文件147checks全部通過；主另驗五docs共125本地檔案links及6新增anchorlinks，全部存在/resolve。已修正等價條件過廣（限具名finite P>C≥0、Rf≥0、無paid及其他調整）、舊action可samekeyforce更新與evaluate upsert邊界，以及主directupsert/rawFKNone和作者wholecollect證據歸屬；官方來源有直接links，109TOTALguard明列不含docs。接受D026-B，四docs停止寫入。

D026-B保存34files的bytes/SHA freeze（manifest SHA dbbf5d803a8b3e96e395de07e671010e51f1636e689afe89c2737123b25817b9），作者34/34核對。B曾有externalreportpath打錯而在寫前失敗，修正後成功；A有兩search exit1及兩JSwrapper語法錯誤，7directGET/17oracle/docvalidators無失敗。詳外部報告，不把非功能失敗藏起或誤歸主測試。

主scope-review對149TOTAL輪前原件：143精確不變、6個授權既有來源修改，另新增1test，共7變更paths；67historicaldata/backups排除且不操作。主將這7paths加README/AGENTS/2DB保存11path實際SHA/size/mtime_ns於external round-source-freeze.json；本紀錄亦停止写入後才交I063。兩DB及rootREADME/AGENTS維持原件。未stage/commit/reset/clean或正式DB/服務/global變更。

輪初App codebase-memory正常；主後續search_code回Transport closed，依AGENTS使用相同exe CLI help/list/search/coverage/snippet全部exit0，未重啟或終止任何App/MCP或改全域設定。newtest目前not_tracked；既有sources/docs metadata_changed，歷史SQLpartial及rootREADME/AGENTS無rootindex限制保留。I063現在僅輪末統一更新canonical worker/tests/docs，必先list/明示name，保存rawtooloutputs並驗本輪7paths及11paths實際指紋；App故障與CLI更新結果分開報。最終receipt/主接受與R25四新taskID留externalfinal/handoff及task訊息，不為回寫索引結果造成刷新循環。ROADMAP仍有獨立工程；R25由新統籌核最新證據界定，不預設genericcapture/paid方案為唯一下一項。

## Round 23 TPEx 唯一停復牌分列配對（2026-09-13，程式／文件已接受並 freeze；輪末索引另核）

R23 已逐一 read_thread 核對四個既有新 task 的 ID、title、cwd，均為共用專案 root；已完整讀 R22 外部 R23_HANDOFF.md、FINAL_REVIEW.md、R23-task-ids.json 並向 R22 確認接手。R22 C022-B／D024-B／I061-B 已接受，舊統籌停止派工與來源寫入，只補交接；舊 task 保留。未重建、fork 或使用 worktree。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a097ab-4050-7742-a398-9b9259fee39f | gpt-6-astra／high | 本紀錄與外部 baseline／review／handoff。 |
| C023 程式 | 01a097ab-9a13-78d0-a0b1-2e082e09858d | gpt-6-astra／medium | C023-B：sources.py 局部 parser 與新 test_tpex_suspension_intervals.py；不改其他來源。 |
| D025 文件 | 01a097ab-9ed4-74d1-9f3d-4bf0c497367a | gpt-5.6-sol／xhigh | D025-B：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION；不改程式或本紀錄。 |
| I062 索引 | 01a097ab-a41d-7620-ad6d-cc2eac68cd02 | gpt-5.6-luna／medium | 僅輪末 review／freeze 後更新與 coverage，不改專案來源。 |

本統籌先查 App codebase-memory list/status/coverage/graph：inventory 8，docs ready 432／431；ROADMAP、ROADMAP_EXECUTION、TASK_COORDINATION、SOURCE_REGISTRY 及 worker sources/pipeline 均 no_recorded_issue／metadata_changed，依建議核來源。輪初不刷新。外部 Temp/stock-r23-coordinator-review/round-baseline.json 與 before/ 保存 130 完整原件（包含 untracked、兩 DB）的 SHA256／size／mtime_ns；兩 DB 與 R22 交接相同。保存既有修改，不 stage/commit/reset/clean。

依最新 ROADMAP 的資料正確性優先，先檢查停復牌 history 日期與實際 consumer 的契約和行為，尚未預認定 bug 或修法，不重開已接受的 Serial identity 修正。程式與文件各自外部調查，統籌依具體證據選定最小有用範圍；若候選不成立則另選已有依賴的工程。所有角色必交 files/diff/實際驗證 logs/限制/freeze，由統籌 review 接受或同 task 退修，不自行结案／下一任務。正式與 .local DB 禁寫；任何 worker/app import 前三 STOCK 環境指向新外部 Temp，不改服務、依賴、全域設定、外部帳戶、採購、交易或部署。

R22 I061-B receipt SHA256 6888442409c20d5e8d696e5781433e63727f873800409054f17164797f5f6b7f；worker407／1962、tests666／3135、docs432／431，7paths tracked 且 metadata_changed。metadata complete/hash complete/generation matches 與11paths實際 fingerprints 精確不變已由 R22 複核；不是以 manifest hash 取代 source guard。歷史 SQL partial、root README/AGENTS 無 root index 限制保留。R22 full backend730passed／1skipped、15獨立 checks 與正式DB不變證據承接，不能外推到本輪。force refetch 不清舊錯Event，舊SignalEvaluation不重算與新tracking仍受舊Event影響的限制保留。

baseline-supplement.json 另保存 18 份根目錄／backend／frontend 設定與文件原件；合計 148 份來源及兩 DB。以 git ls-files 的 cached＋untracked inventory 對照補齊；67 份 data/backups 歷史資料不在來源備份集合，也不操作。這是來源與兩 DB 的具名保護範圍，不宣稱整個資料目錄全量備份。

### C023-A／D025-A 調查與範圍收斂

C023-A 外部實驗以 actual TPEx adapter、committed file SQLite 與 fresh Session 重現 17cases／34DB／68evaluations，另 2DB／4evaluations 核舊 Event 更新邊界；全部 child/shell0，78 code/app/tests/兩DB 精確 guard 不變。非法非空 resume 會變 null 並持續推定停牌；拒絕整列卻會讓正常 OHLC 恢復 comparable/trigger，因此這不是普遍保守的交易處理，也不是市場開市真值。外部 counterfactual 的倒置拒絕未接受；尚未授權 project patch。

D025-A 的一次免費官方唯讀回應提供更直接候選：保存 body 79,602bytes／SHA256 4e3747a4a27c1e45542ce476ff7ccd0384e5c420e9f2d5bbfd9257b9cc48e6a2，362列由181組同code start-only／resume-only構成，每code各一列且start<resume，沒有同列兩日期。主已用獨立 offline oracle 全量驗shape/hash與兩time皆080000（live-shape-review.json），不把這個snapshot外推成永久schema／完整歷史／PIT。現行逐列parser讓所有suspension end留空，下游又不連結resumption Event。故派 C023-A2 優先重現此實際形狀與有限配對counterfactual，暫不採前述malformed窄patch。

候選限同payload／同security／唯一start-only及較晚resume-only，不以Serial或相鄰排序猜pair；多marker、同日、倒置、同列既有完整interval與解析政策分開處理。兩audit Events/raw須保留，舊Event valid same-key update與empty rejection、舊evaluation保留的界線須實測。

### C023-B 核定契約（尚非 final 功能驗收）

C023-A2 已用保存body中的真實1788／2026-06-18停牌、06-22復牌對，透過 actual OfficialMarketDataAdapter／TpexAdapter／collect／fresh migration SQLite 重現09-03到09-04仍被錯誤無界停牌標記。外部候選在force=False成功重用時零fetch、不改舊null；force=True則同Event id補finite end，新評估active／triggerTrue而舊評估仍suspended，raw同內容去重仍同id，兩history Events保留；14項bounded parser checks通過，wholebody181組null→finite是parser-only證據。主已全文review報告與外部wrapper，確認具名最小修正依賴。

只核定history parser與新專用test：同selected symbol的原input row數必為2（invalid／empty／duplicate也計數），既有_text／parse_roc_date選出的1個valid start-only與1個valid resume-only，對側selected raw date text為空且start<resume才配對。只補suspension details的resumed_date／interval_end／resumption_source_row；source_row保留原start，另筆resumption Event、輸出order/count/identity/date/source/endpoint/hash/data_as_of維持原樣。時間欄只原樣保留raw，不參與跨日排序；不新增time解析／gate，不宣稱盤中或復牌日整日開市。非合格形狀全部保留舊行為，包括已知仍可能無界推定的ambiguous／malformed／same-day等缺口。沒有採用C023-A拒絕策略，也不改共用解析器、pipeline/gap、版本、schema或collector政策。

程式須交actual adapters／完整collect／migration SQLite／raw FK／force reuse-update與舊評估保留證據及freeze，統籌獨立review後才接受。測試及live-shaped資料不能外推為完整全市場halt、PIT或正式修復。

D025-A final request metadata 更正早期「一次」口頭回報：實際2次成功direct GET（第一次記憶體shape、第二次保存原bytes）與1次web-open 502；兩成功回應200／79,602bytes／同SHA。不以失敗502作來源truth；原response headers未完整保存的限制照實保留。D025-A 9case oracle與181延長predicate是獨立重寫的來源契約驗證，非actual consumer；主offline181shape oracle與作者actualcollect證據分開。§4.3對malformed/inverted/sameday較大政策只是未接受提案，B只採上述unique split-pair scope，不新增strict date parser／品質reason。四文件已具名授權D025-B更新，待主final證據後收斂。

### C023-B 統籌 final 功能 review（已接受／程式 freeze）

主已全文review來源baseline diff與新test45cases，接受僅history parser34行net新增及新專用test。作者5modules142passed／1846warnings／pytest5.24s／child6.375s／shellwall6.82s，child/shell0；首次argv誤寫不存在test_pipeline.py導致pytest4／shell4／no tests ran，完整failed log/json/runner保存，之後無功能失敗。作者baseline78是TOTAL（76source+2DB），既有僅sources改、其餘77精確不變；早期A2回報78source+2DB口誤已澄清。sources SHA04872eb7ab86efdfadf80459bffc9a09db7a40aa358eae8b08e64ba5a731a178，test SHA3a847b82ca7e52d19c478a261b0c08759b565c4309e86acd90253788f5344234，freeze在Temp/stock-r23-c023-b/freeze.json。

主final完整backend775passed／1skipped／8342warnings，pytest55.09s／process56.281s／exit0；Python3.12.14與既有Alembic1.19.2。108個code/tests/frontend及兩DB之SHA／size／mtime_ns精確不變，docs不在fullguard。skip沿用R18 Windows symlink privilege，沒有依賴安裝；主full無失敗。

主independent19checks亦exit0：保存body181pair在原序／反序／seed23亂序各保留362audit Events，逐欄僅三個指定details變化；12個不合格shape與舊parser等價、Serial/time raw-only兩案例、actualTpexAdapter全保存body經fixture universe只取1788兩events且OHLC/warnings/coverage不變、committed SQLite含TPEx1788／同symbol TWSE1788／TPEx1799三instrument，確認sameEventid finite update、舊評估suspended保留與新評估active、integrity/FK。7path精確guard不變。此independent不是wholecollect或migration驗證（Base.metadata建DB／event rawFK=None）；45個作者tests及主full才供actualcollect/migration/rawFK/forceFalse-forceTrue證據。原HTTP body SHA與adapter重序列JSON capture SHA分別记录，不冒称bytes直接穿透。

成功force=False零fetch重用仍不修舊null；force=True有限pair同key upsert可改同一Event的end，raw同內容可去重，舊SignalEvaluation不重算。這不刪Round22 wrongidentity舊Event，不代表正式修復或市場開市/完整halt/PIT；不合格形狀仍可能保留無界推定，已列後續限制。主證據在Temp/stock-r23-coordinator-review/完整baseline、live-shape-review、independent-review、full-backend-review及完整logs；程式與tests停止寫入，等待文件收斂與輪末索引。

### D025-B 文件接受與輪末 freeze

主已完整review四文件對自己before/原件的diff及D025-B-REPORT／doc-review／freeze，接受有限契約與已驗證範圍。修正草稿中的108再加2DB、shape oracle混稱parser、A2 fullbody混稱subset、把舊日期欄稱新增等問題；嚴格跨日僅指日期排序，不是新增strict parser。只新增resumption_source_row，resumed_date/interval_end由null補值；exact2包含invalid/empty/duplicate、對側selectedrawtext空白、time raw-only及不合格shape舊行為保留均明確。D025-A的較大invalid/sameday政策不採用。samekey Event可更新、wrongidentity Event不刪、舊evaluation不重算及local既有授權/正式DB限制分開。

文件角色的新anchors／相對連結／status／implementation hashes檢查通過；最初WindowsApps python.exe回exit0卻無產物，不算成功，改用既有bundled Python後執行通過，紀錄保留。D025-B外部diff/報告/freeze在Temp/stock-r23-d025-contract；主另外驗五份docs共119個本地檔案連結，全部存在。

主148份輪前來源與兩DB原件中142份SHA/size/mtime_ns精確不變、6個具名既有來源修改，另新增1個test；總計7個本輪source paths。scope-review.json與逐檔diff保存證據。四docs與code/test已freeze，本紀錄一併freeze後，round-source-freeze.json保存7paths加README/AGENTS/兩DB共11paths的實際指紋。歷史資料備份67paths不在來源guard範圍且不操作。主未執行git stage/commit/reset/clean、正式DB寫入、依賴/服務/global更動、帳戶/採購/交易/部署。

I062僅現在輪末統一更新既有canonical worker/tests/docs，必先list與顯式name，核7paths relative-root coverage、metadata精確時間與11paths真實fingerprints。來源不再改；最終索引receipt、主接受及R24四新task ID以外部final/handoff與task訊息保存，不為回寫索引結果形成刷新循環。仍有可獨立工程的ROADMAP項目，R24由下一任新統籌核最新ROADMAP自行界定，不預设多cycle/hardening/capture為唯一下一項；不建空轉輪次。

## Round 22 TPEx 停復牌歷史身分驗證（2026-09-13，程式／文件已接受並 freeze；輪末索引另核）

R22 已逐一 read_thread 核四個既有 task 的 ID、title、cwd，完整讀 R21 外部交接並向舊統籌確認接手；R21 已接受 C021-C／D023-C／I060-B，停止派工與來源寫入。四 task 最新 cwd 均為共用專案 root；文件 task 初始 App-bin metadata 異常及 explicit-workdir probe 證據保留，後續各 shell call 顯式指定 root、檔案讀寫用完整絕對路徑。不重建、fork 或 worktree。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a0978d-6ff2-74b0-8fac-41f59eb14c85 | gpt-6-astra／high | 本紀錄、外部 baseline／review／handoff。 |
| C022 程式 | 01a0978d-efb5-7781-9aef-8ec851560a05 | gpt-6-astra／medium | C022-B：sources.py 的 history Serial fallback 與新 test_tpex_suspension_identity.py；其他來源不得改。 |
| D024 文件 | 01a0978d-f473-76c0-9a80-9ebbb22dade7 | gpt-5.6-sol／xhigh | D024-B：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION；不改程式或本紀錄。 |
| I061 索引 | 01a0978d-f9a7-7762-88f7-68e1b74edaa4 | gpt-5.6-luna／medium | 僅輪末 review／freeze 後統一更新及 coverage，不改來源。 |

本統籌已先查 App codebase-memory list/status/coverage/graph：8 projects、docs ready，相關 docs／worker 路徑 no_recorded_issue、metadata_changed，依建議核原始來源。external `Temp/stock-r22-coordinator-review/round-baseline.json`／`before/` 保存129完整原件（含 untracked、兩 DB）、SHA／size／mtime_ns；兩 DB 與交接一致。輪初不刷新，來源變更累積交 I061 輪末處理。

依 ROADMAP 資料正確性優先，先驗 `parse_tpex_suspension_history_rows` 的 Serial fallback 是否導致錯誤證券 Event 及真 SQLite tracking 行為；不是预先接受 bug，倒置日期／intraday／future resumed_date 暫不納本批。各角色交 files/diff/logs/限制/freeze，由統籌 review 接受或同 task 退修，不自行結案／啟下一輪。正式與 .local DB 禁寫；測試設三 STOCK 環境指向新外部 Temp；不改依賴、既有服務、外部帳戶或交易、部署，不 stage/commit/reset/clean。R21 I060-B canonical name 修正與10paths tracked 的 receipt SHA f7370b94f16acdf2d52f332b11a494b44fd00e8385bf2cd1ed0e3fc98261c0eb 已承接；錯 alias receipt 不接受，歷史 SQL partial/root 無索引及 metadata_changed 限制保留。

### C022-B 核定範圍

C022-A 在外部以 actual parser→_upsert_event→committed SQLite Event→gap/tracking 重現6案例、12DB、24evaluations：Serial-only誤停牌、Serial遮蔽Code漏停牌、與雙股票錯配。首跑fixture缺必填adj_close的child exit1保留，修fixture後child exit0；77paths精確guard不變。官方R21 bounded schema把Serial標為「編號」、SecuritiesCompanyCode標為「證券代號」，沒有新live證據。主已核parser、實際adapter/upsert/tracking與官方欄位證據，准進具名實作，尚非功能驗收。

最小修法只移除history parser的Serial fallback，保留既有SecuritiesCompanyCode→Code→證券代號→代號first-nonblank/allowed_symbols。後三者是既有本地相容aliases，非本輪查證之官方schema；不新增衝突、型別或日期政策。新增專用pure/actualadapter/collect/真SQLite regressions，驗raw/source_row、market identity、successful reuse及force refetch邊界。舊錯Event不因新empty結果自動刪除；正式修復、完整halt/PIT與其他ROADMAP項目仍未完成。

### C022-B 統籌 final review

主已全文review sources.py差異與新test，接受移除Serial及註解的兩行變更，新增34案例：20pure identity/audit、8 actual TPEx／both-market Official adapter、3完整collect/raw linkage/真SQLite gap/tracking、3既有錯Event的successful reuse/force refetch邊界。作者四模組targeted為97passed／1597warnings／pytest4.71s／wrapper5.5s／child與shell exit0，B無失敗attempt；A初次fixture缺adj_close失敗另保留。兩個交付來源已freeze，其他程式／tests／日期／tracking版本不改。

主 final完整backend：730passed／1skipped／8093warnings，pytest55.53s／process56.688s／exit0，Python3.12.14與既有Alembic1.19.2。107個code/tests/frontend及兩DB guard的SHA／size／mtime_ns精確不變；docs未納full guard。skip沿用R18 Windows symlink privilege。主外部獨立15checks亦exit0：10種實際TPEx adapter舊新比較、raw bytes/SHA與OHLC保留；4組舊新真SQLite upsert/gap/tracking比較，每組含TPEx兩標的及同symbol TWSE控制；1項確認舊錯Event不因新empty結果刪除。此15checks使用pre-round FixtureFetcher，SQLite以Base.metadata建表，非完整collect或migration驗證；both-market完整collect/raw FK/reuse/refetch範圍歸作者新tests及主full實跑。

successful force=False zero-call reuse；force=True empty、Serial-only或corrected-other-security重新抓取都不刪既有錯配Event，新正確別股票事件可與旧錯Event共存，舊SignalEvaluation不自動重算，重新評估仍會受舊Event影響。無正式DB修復。identity rejection只是不生成錯誤新事件，不能證明市場開市、完整halt coverage或PIT。全R1-A1/A3、capture history consumer、日期與其他ROADMAP缺口保留。

主證據 `Temp/stock-r22-coordinator-review/`：完整129原件baseline/before、independent_review.py／independent-review.json/log、full_backend_review.py／full-backend-review.json/log。作者 `Temp/stock-r22-c022-investigation/`：C022-A/B-REPORT、B-sources-before／diff、B-test.diff、B-targeted-1.log／B-targeted-ur9_tass/receipt.json及C022-B-freeze。source SHA4a94533a34f8e0433b7fced78fdc5bab33b53c970faadd43f40ba3651c43bc51；test SHA0b1881cdfc8bbdab5f23fc741d74ebdb916b67bfa3c484e4e8ac69fcbb01182a。

D024-A已核官方bounded path/schema原bytes與hash，收斂為只移除Serial；初稿曾擴提alias conflict/type政策，主退回，原broad draft留外部不接受。未新增web/live或權利證據；官方資料只支持SecuritiesCompanyCode為證券代號，其他aliases仍是本地相容。

### D024-B 文件接受與輪末 freeze

主已讀四份文件完整baseline diff、D024-B報告與最後修正，接受本輪有限文字收斂。明確保留raw可能去重、外部本地diagnostic/repair設計/replay既有授權、只有正式DB寫入另需授權；同symbol TWSE/TPEx隔離歸主15checks，作者完整collect/raw FK等證據分開。作者109個相對連結、trailing whitespace0、兩新heading/anchors及source/test hashes驗證通過；主另核五份docs共112個本地檔案連結。沒有修改歷史輪次成果範圍。

129個輪前原件中123個精確不變、6個授權既有來源修改，另新增1個test；總計7個本輪source paths。主外部scope-review.json及逐檔diff保存完整對照。source/test與四文件freeze；本紀錄一併freeze後，round-source-freeze.json保留上述7paths加README、AGENTS、兩DB共11paths的精確SHA/size/mtime_ns。D024-B完整備份、報告與VERIFY在Temp/stock-r22-d024-contract。

I061只輪末更新既有canonical worker/tests/docs並確認7paths coverage、各root與既有SQLpartial/root無索引限制；主另獨立核對新symbol、內容、inventory及11pathfreeze。不得漏顯式name或用workspace-relative路徑。I061 receipt及主final acceptance/下一輪4個新task ID以外部handoff/task回覆保存，避免來源反覆寫入造成刷新循環。此索引前狀態不預稱I061已接受；R23待主輪末驗收後建立。

## Round 21 TPEx 當日停復牌公告誤標修正（2026-09-13，程式／文件已接受並 freeze；輪末索引另核）

R21 統籌已逐一 read_thread 核對以下四個既有 local task 的 ID、title、cwd，向 R20 確認接手。共用現有 workspace；三角色此前均只待命，未重建、fork 或 worktree。R20 已接受 C020-B／D022-C／I059，停止派工及來源寫入，只補交接。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a0976a-d2e9-7592-a150-dfc86deca220 | gpt-6-astra／high | 本紀錄；外部 baseline、review、handoff。 |
| C021 程式 | 01a0976a-d889-7d22-9e55-f7012c756507 | gpt-6-astra／medium | C021-C：sources.py、test_sources.py、新 test_tpex_suspension_announcements.py；另 test_stock_day_capture.py／test_holiday_capture.py 各局部 fixture 3 行；五檔已接受並 freeze。 |
| D023 文件 | 01a0976a-ddb2-7c80-a50e-0d1cb4ea73f0 | gpt-5.6-sol／xhigh | D023-C：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION；不改程式或本紀錄。 |
| I060 索引 | 01a0976a-e3b3-7710-9bcf-720397211275 | gpt-5.6-luna／medium | 只輪末 source review／freeze 後統一索引與 coverage，不改來源。 |

主已先查 App codebase-memory list／status／coverage／graph；docs、worker ready，相關路徑 no_recorded_issue、metadata_changed／best_effort，故直接核來源並累積輪末刷新路徑。外部 `Temp/stock-r21-coordinator-review/round-baseline.json` 與 `before/` 保存 128 完整原件及 SHA／size／mtime_ns，包含兩個 DB；兩 DB hashes 與 R20 交接一致。既有檔首次修改前均須外部完整備份，包含 untracked。根 README 歷史變更保留，不 commit／stage／reset／clean。

本輪先按 ROADMAP 追蹤既有停復牌 parser→consumer，選一個最小有用資料品質修正；不預設必須新增剩餘兩域 capture foundation，不擴大已接受 R18–R20。角色交 files／diff／實際 logs／限制／freeze，由主獨立 review 接受或同 task 退修；不得自行結案、啟下一任務或新建角色。正式與 `.local` DB 禁寫，測試及產物限外部 Temp；不啟停既有服務、不改依賴、不採購、不操作外部帳戶／自動交易／部署。

R20 最終證據承接：主 full backend 678 passed／1 skipped／7201 warnings／53.89 秒；主 guarded holiday 17 checks 通過。I059 worker 407／1958、tests 633／2923、docs 414／413，8 paths tracked，metadata_changed 與既有 SQL partial、root 無索引限制保留；App 後段 Transport closed、同引擎 CLI full 成功。最終 receipt 與完整交接見外部 `Temp/stock-r20-coordinator-review/I059-index-receipt.json`／`R21_HANDOFF.md`。索引成功不是功能驗收；R1-A1、C007／PIT、正式分類及其餘 ROADMAP 缺口仍未完成。

### C021-B／D023-B 核定範圍

官方 Swagger 的 today endpoint 是「上櫃當日公布暫停／恢復交易股票」，schema 包含暫停與恢復欄位；identifier 出現不等於該日仍停牌。主單次官方 Swagger 擷取保存 114,176 bytes，但完整 JSON 截斷不可解析；只對其中兩個 path 與兩個 schema 的完整 bounded JSON objects 獨立解碼，不宣稱完整 catalog 或 live 市場資料。外部 `official-catalog-evidence.json`／原 `tpex-swagger.json` 保存 SHA、offset、length 與限制。

C021-A 在外部 `Temp/stock-r21-c021-investigation/` 使用真 TpexAdapter、bar upsert 與 tracking 函式，搭配 memory／DB read doubles，重現相同歷史日期及有效 OHLC 下，today feed 只增加代碼就把 bar.is_suspended False→True、tracking active→suspended、breakout trigger True→False；8 檔 source／DB guard 不變。這是隔離 fixture 實證，尚非真 SQLite collect 或 live truth。future resumed_date 留於較早 event details 已觀察，但目前 early-cutoff gap 與 open interval 結果相同，未證該欄造成判定差異，不在本批修正。

C021-C 只移除 today code-only 的 bar 停牌覆寫；保留 raw 與非空回應 warnings list 純文字警告，空清單不證開市，其他輸入 bar flag 不清除。history parser、future details、tracking 演算法／版本不改；沒有正式 DB 寫入。成功 request key 的 force=False 會 zero-call reuse、不自動修舊 flag；force=True 實際收集可更新同日 bar，既存 SignalEvaluation 與其他日期不自動重算／修復。partial run 的 force=False 仍會重抓。完整停復牌時間／coverage、capture consumer、PIT 和正式資料修復仍未完成。

### C021-C 統籌 final review

主已接受五個 source/test 的具名修正。主完整 backend：696 passed／1 skipped／7432 warnings，pytest 53.56 秒、process 54.610 秒、exit 0；Python 3.12.14、既有 Alembic 1.19.2。106 個 code/tests／兩 DB guard paths 的 SHA／size／mtime_ns 精確不變；docs 不在 full guard。唯一 skip 沿用 R18 Windows symlink privilege，未新增 skip、未安裝依賴。

主外部 9 checks：以 round baseline 完整 sources 與目前版本比較 6 種公告輸入，actual TpexAdapter、raw bytes／SHA／OHLC 不變；兩種恢復／未來停牌公告各走真 SQLite upsert／tracking，舊版 suspended／trigger=False → 新版 active／trigger=True；另驗輸入 true bar 仍停牌。6 個 source/test／兩 DB guard 精確不變，network 禁止。這九項使用保存的原 fixture fetcher，並非完整 collect 或 live；真 TWSE＋TPEx＋Official＋collect／force／reuse／failed-path raw／history 的完整 local fixture 範圍由作者 targeted 與主 full 實跑。

作者 C021-B targeted 為 42 passed／297 warnings／1.70 秒；首跑 40 passed／2 failed 為新測試對 unavailable 包裝文字及舊 fixture 非數字產業碼的預期問題，修正僅在新 tests。主第一次 full 為 3 failed／693 passed／1 skipped／6134 warnings／55.95 秒：R19/R20 capture success/reuse fixtures 帶入無關非空 today 公告，正確產生 partial。C021-C 只在兩個專用 fetcher 各加三行 today→empty，保留 super call recording、全部舊 assertions 與全域 FixtureFetcher；新 notice tests 持續驗 nonempty→partial。作者 final 三完整 targeted 模組為 177 passed／2366 warnings／10.83 秒、process 11.938 秒。首次失敗完整 logs 保留，不能當作通過證據。

主 evidence root：`C:/Users/YiCheng/AppData/Local/Temp/stock-r21-coordinator-review/`，含 baseline／before、official-catalog-evidence.json、independent-review.json／log、full-backend.log／full-backend-review.json、full-backend-first-failed.log／json、scope-review.json 與逐檔 diff。作者外部 `Temp/stock-r21-c021-investigation/C021-C-REPORT.md`／`C021-C-freeze.json`、B/C targeted logs 保存完整範圍／環境／原件與限制。沒有新的市場 payload live，只有上述截斷 Swagger 文件擷取。

### D023-C 文件接受與輪末 freeze

主已 review 四份文件完整 diff、最終範圍／時間語意／force 邊界與測試數字，並退修、核對 independent 9 checks 不含 whole collect／ingestion-run linkage 的證據歸屬；完整 collect 範圍明確歸作者測試及主 full suite。D023-C 已接受，四檔 freeze。作者 final 102 個相對連結、無殘留進行中狀態／行尾空白與 diff check 通過；主另核五份 docs 本地連結與九個既有修改檔的完整外部 baseline diff，無超範圍原件變更。128 個原件中 119 精確不變、9 授權修改，另新建一個 test，共10個本輪 source paths。

本紀錄一併 freeze 後，以外部 `round-source-freeze.json` 保存10個本輪來源、兩 DB、README／AGENTS 共14個精確 SHA／size／mtime_ns。I060 僅更新 worker／tests／docs 涉及分區、查10paths coverage及既有 SQL partial／root 無索引限制；主再獨立複核。I060 final receipt、主複核與 R22 四新 task IDs 保存外部 handoff 及 task 回覆，避免索引後反覆回寫本紀錄。索引前本段不宣稱 I060 已接受，下一輪須待主 final acceptance 後建立。

## Round 20 holidaySchedule 休市日排除（2026-09-13，程式／文件已接受並 freeze；輪末索引另核）

R20 統籌已逐一 `read_thread` 核對四個既有 local task 的 ID、title 與 cwd，並向 R19 確認接手；共用現有 workspace。R19 已接受 C019-B／D021-C／I058，停止派工及來源寫入，只補交接。不得重建、fork 或沿用舊輪角色。

| 角色 | Task ID | 模型／Reasoning | 寫入責任 |
| --- | --- | --- | --- |
| 統籌／review | 01a09745-4071-7640-a1a8-935e33a3228a | gpt-6-astra／high | 本紀錄；外部 review／handoff 證據。 |
| C020 程式 | 01a09745-9897-7002-90ac-ec53cb857fde | gpt-6-astra／medium | C020-B：新 worker/holiday_capture.py、新 tests/test_holiday_capture.py、既有 worker/sources.py；其他程式不改。 |
| D022 文件 | 01a09745-9dc9-7020-b903-656d06b4bc95 | gpt-5.6-sol／xhigh | D022-B：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION；先外部草案，依實際證據收斂。 |
| I059 索引 | 01a09745-a3ec-71a2-bcfa-f236537434db | gpt-5.6-luna／medium | 輪末 source review／freeze 後統一索引與 coverage；目前待命。 |

主先查 App codebase-memory list／status／coverage／graph：通道可用，相關 docs／worker 路徑 no_recorded_issue、metadata_changed／best_effort，故直接核來源；不在輪初刷新。外部 `Temp/stock-r20-coordinator-review/round-baseline.json` 與 `before/` 完整備份 126 個來源／文件／保護檔，包含正式與 `.local` DB，兩 DB SHA 與 R19 交接一致。既有檔首次改前均須保留完整外部原件，untracked 同樣適用。

R19 已接受範圍為單日 STOCK_DAY_ALL bundle 的 selected-security library opt-in；主 full backend 590 passed／1 skipped／5198 warnings／47.27 秒、capture 30 checks、consumer 7 checks 及 Decimal precision probe；無新 live。I058 worker 384／1813、tests 603／2776、docs 406／405，8paths tracked；metadata_changed、root 無索引及既有 SQL partial 限制保留。完整交接與索引 receipt 位於外部 `Temp/stock-r19-coordinator-review/R20_HANDOFF.md`／`I058-index-receipt.json`，不重開已接受的 R18／R19。

本輪依 ROADMAP 選一個最小且有既有 consumer 的下一範圍，不一次接剩餘三域，不新增沒有 consumer 的通用 foundation。正式分類修復不以四來源全接完為新增前置。正式 DB、採購、外部帳戶、自動交易、部署及既有服務仍未授權變動；測試限全新 Temp。角色交付檔案／diff／實際 logs／限制／freeze，由現任統籌接受或退回同 task 修正；收到完成不等於驗收通過。

### C020-B／D022-B 範圍

本輪選 `holidaySchedule` → 既有 `TwseAdapter.fetch_bars` 多日查詢的正面休市排除：新增外部 pinned bundle loader 與 keyword opt-in。全體 row/date/year/weekday 一致性先驗；僅可核對的完整文字規則形成 closed dates，未知、否定、缺列不推休市／開市；不得單獨建立 session／TAIEX 或宣稱全年 coverage。實際 price/index 與 closed 日期衝突須明確處理。單日及無 capture 的 legacy 分支保持既有行為；其他 endpoint 不因此受 runtime gate。R0-B5／B5b／PIT、完整 R1-A1／R1-A2、action／suspension、正式分類及兩 DB 均保留未完成。

主已用 R18 runtime CLI 執行一次 holiday exact GET，HTTP200、3,774 bytes、27 rows，SHA256 `7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`，capture UTC `2026-09-12T20:24:29.169003+00:00`；artifact 在外部 `Temp/stock-r20-holiday-live-8a_frrvt/capture/capture.zip`，命令及 receipt 在主 review 根 `holiday-live-capture.json`。這是本輪單次 transport／保存內容證據，非歷年可用性、內容 authenticity 或 first availability。後續使用保存 bundle／本地 fixtures，不重複發 live。

### C020-B 統籌 final review

主已接受 C020-B 的具名 holiday consumer 範圍，三檔 freeze：sources `d05f2aec36c536a216d6cfb9212b8d51336192f29cdebe635a7fccab132065a6`、holiday_capture `f209f557b24777ddacba2e27d17c224d26ff7b9a56e84aa470bdd25e5bde640e`、test_holiday_capture `abb2f8abf71ae734ca021be357597193a1fbf8bc95acd8e3035ff36a8e208237`。主完整 backend 678 passed／1 skipped／7,201 warnings，pytest 53.89 秒、process 55.016 秒、exit 0；Python 3.12.14／Alembic 1.19.2。105 個 code／tests／兩 DB guard paths 的 SHA／size／mtime_ns 全不變，docs 不在 full guard。唯一 skip 沿用 R18 Windows symlink 權限案例；未安裝依賴。

主 final guarded independent 17 checks：保存 live bundle 對人工 oracle 24 closed（18 weekdays）／3 nonclosure，補到 legacy substring 漏掉的五個補假日；全域 year／weekday／duplicate、否定及矛盾文字、capture object timestamp drift；2/26–3/2 只送2/26與3/2 MI_INDEX；真實 TWSE／Official adapter→collect、TWSE ancillary 本地 fixtures、TPEx empty stub、HTTP 全禁。結果 partial／26 records／13 TAIEX／48 raw；raw SHA／UTC／same-run reuse、closed 不新增 sessions、integrity／FK 通過。這不是完整雙市場 live parser 或歷史 availability。final 17-check 前後三 frozen source 與兩 DB guard 一致。

作者 full 676 passed／1 skipped／7,119 warnings／53.38 秒早於最後新增兩項 tests；final holiday 88 passed／2,003 warnings／6.84 秒。主 final full 已含這兩項。作者 tests 的完整兩市場本地 fixture→Official adapter→collect 覆蓋 success／forceFalse reuse／forceTrue、preexisting closed bar／session 保留、跨年未列日期仍請求及 current index conflict 失敗保存 raw；不把這些全列為主17checks。首次單Twse繞過combined去重造成UNIQUE的失敗與缺Alembic PYTHONPATH的collection失敗均保留，修正後上述 final 測試通過。

限定新的 opt-in 只改多日 holiday GET；可合用 R19 stock capture。未知名稱／文字不排除並留 machine reasons，warnings 可使run partial；單日不消費holiday；未提供capture的legacy substring不改。可見有效daily/security（含未選symbol）及full fetch獨立current index與closed衝突failclosed，未抓的MI_INDEX不冒稱已驗。calendar不建立no_data/session；既有DB舊closed rows因upsert-only保留。原raw.capture UTC不是published／firstavailable；local unsigned一致性非authenticity，plain output非雙檔atomic／永久immutable。action／suspension、R1-A1／R1-A2／R1-A3整體、C007／B3-wire／B5b／B7、正式分類及兩DB不因本輪結清。

主證據根 `Temp/stock-r20-coordinator-review/`：program-freeze.json、full-backend.log／full-backend-review.json、holiday-live-capture.json／holiday-live-oracle.json、independent-holiday-review.json／independent-final-guard.json、scope-review.json。baseline範圍內120 unchanged／6授權既有改（sources與5docs），2新source；正式與.local DB hash承接R19且未變。作者原件／diff／SHA在 `Temp/stock-r20-code-d1c797f46b264978be4a70de5383468d/`。

App codebase-memory 輪初正常，之後 check_index_coverage 回 Transport closed；主改同引擎CLI只讀成功，new holiday／test仍 not_tracked，等待I059輪末刷新。未殺程序或更改global設定。D022-C 四docs final review 已接受，主獨立核對95個local links、6個新增Round20錨點、空白及四份SHA通過。四文件與本協作紀錄全部 freeze 後開I059 gate；索引不替代功能驗收。


D022-C 最終 SHA：SOURCE_REGISTRY `37e22a5b02451b1631435c33dbfebb6462f440db58a1e49ea21e278d0af7b050`；OPERATIONS `b9f2a50e3f1a8c5dff414390219e9d4f7ed9fae61fb7cd40b36b443d1a20a195`；ROADMAP `7537318d5b66aaa4928f83e14e70ac3a30c2183acaddc757251f4246429ba913`；ROADMAP_EXECUTION `4c7e7fd2f05ae0591a7fddd240682bfb30a7cd61b1f957bb9443ad2497dcf603`。主曾退修文稿加上的跨年拒絕／exact keys／只7位日期等超出分派規則，D022-C 已對齊實作，並區分 object timestamp drift、作者兩市場矩陣与主17檢查。完整diff與驗證位於主外部 final-docs.diff／final-docs-hashes.json／final-docs-validation.json。

I059 本輪 gate：只刷新 worker／tests／docs full，核8個變更來源、symbols與文字搜尋、coverage及已知SQL partial；不改專案來源、不負責輪初baseline、不為metadata_changed無限重刷。最終receipt與統籌獨立複核保存在外部主review根與索引task回覆，避免為回寫receipt造成source-refresh循環。接受後才建立R21四個新local task，由新統籌核ID／接手並保存新baseline、更新本紀錄；R20交接後停止派工，只補交接。下一輪依ROADMAP與既有consumer選最小有用scope，不先一次接action+suspension，亦不以四域全完成綁定正式分類修復。

## Round 19 來源內容接線（2026-09-13，程式／文件有限 review 並 freeze；輪末索引另核）

R19 統籌已逐一 read_thread 核對以下四個既有 local task 的 ID、title、cwd，並向 R18 確認接手。R18 已停止派工及來源寫入，只补交接；共用既有 workspace，不 fork／worktree／重建角色。

| 角色 | Task ID | 模型／Reasoning | 寫入範圍 |
| --- | --- | --- | --- |
| 統籌／review | 01a0971a-5910-7201-8a0f-17dce60cc86a | gpt-6-astra／high | TASK_COORDINATION、必要 HANDOFF／AGENTS；review 證據存專案外。 |
| C019 程式 | 01a0971a-cd47-7df3-902b-b1a90df14f30 | gpt-6-astra／medium | C019-A 先唯讀盤點；implementation／tests 待主具名定界。 |
| D021 文件 | 01a0971a-d27d-7900-a7da-29693ca32526 | gpt-5.6-sol／xhigh | D021-A 先唯讀契約盤點；指定 docs 待主核定。 |
| I058 索引 | 01a0971a-d91c-7b90-9e62-ccd2428b40cc | gpt-5.6-luna／medium | 輪末 review／freeze 後統一索引與 coverage；現在待命。 |

原指定索引角色曾誤建額外 task 01a0971b-1640-7820-8693-4e3b1904db93，主已重申由原指定 task 本人履職，額外 task 只待命，不納入派工、不刪除或封存；本輪四 ID 不變。

承接 R18 已接受 C018-B／D020-C／I057：standalone capture 四 exact GET allowlist，完整 backend 主 519 passed／1 skipped／5066 warnings／57.36 秒，獨立 33checks，以及一次 STOCK_DAY_ALL HTTP200、319396 bytes／1379 rows。僅此當次 transport／bundle 證據，不代表內容 truth、四域 live、strict time／PIT 或完整 legacy gate。I057 worker367/1644、tests579/2628、docs400/399；7paths tracked/no_recorded_issue，metadata_changed/best_effort 與 root 無索引、既有 SQL partial 限制保留。完整 R18 receipt 由前任外部 stock-r18-coordinator-review 傳承；下方 R18 pre-index 文字為歷史 freeze，不重開已接受工作。

本輪先查 App codebase-memory list/status/coverage/graph，worker/docs ready；相關路徑 metadata_changed，故直接核來源，待 I058 輪末集中刷新。主 stock-r19-coordinator-review/round-baseline.json 與 before/ 已保存 140 個來源完整原件，guards.json 保存兩 DB 與根 README 的 SHA/size/mtime，皆與交接一致。各角色既有檔首次修改前仍需完整外部備份，untracked 亦同。

C019-A／D021-A 只讀盤點 source-capture/v1 bundle 至既有 consumer，優先檢查 STOCK_DAY_ALL bars/session 的最小內容驗證與證據接線；主核依賴後選單一 domain。不重造無消費者 foundation，不一次四域，不新增正式分類修復前置，不假造官方 first availability。各角色交來源、實際驗證、限制及 freeze，由主接受或退同 task 修正後才進下一步。正式／.local DB、根 README、既有服務保留，未授權採購／外部帳戶／交易／部署。

C019-A 盤點已接受，C019-B 定界為 STOCK_DAY_ALL bundle → 既有 TwseAdapter 的明確 daily_capture 參數 → OfficialMarketDataAdapter → collect(force=True) → MarketBar。程式僅新 worker/stock_day_capture.py、sources.py 與新 tests/test_stock_day_capture.py；不建 offline universe／新 CLI，也不改 pipeline、schema 或 runtime／registry。loader 驗外部 pins、bounded ZIP、原 body hash 與 aware capture 時間；selected symbol 缺漏／非法 OHLCV 或成交金額須 unavailable+reason，不補零、不推停牌。當日 MI_INDEX 不得覆蓋有效 bundle row 或補回 rejected symbol；TAIEX 仍由自身證據驗證，bundle 不證 session。原 collect 同日已成功的 idempotency 可能不讀 adapter，因此本輪接線呼叫明確要求 force=True，無新 request namespace。其他 endpoint 仍走 legacy，不宣稱整 collector gate。D021-B 先只寫 SOURCE_REGISTRY 提案契約，程式驗收後才收斂狀態與其他 docs。

主已唯讀檢查 R18 saved live bundle：1379 列皆 Date=1150911，其中12列缺 OHLC、9列缺 TradeVolume／TradeValue；Code 含字母。檢查報告在 stock-r19-coordinator-review/live-bundle-shape.json，不是新 live 證據。內容驗收只聲稱 bundle 內一致性及既有 consumer 接線；C007 strict time store、官方 first availability、PIT、完整 session 與正式 DB 仍未完成。

C019-B 三來源已主有限 review 接受並 freeze。主完整 backend：590 passed／1 skipped／5198 warnings／pytest47.27秒（process48.344秒）／exit0，Python3.12.14、既有 Alembic1.19.2；code／tests／alembic／frontend-src 與兩保護 DB 在 full 前後 SHA/size/mtime_ns 一致，docs 不在此測試 guard。作者 final full 同590／1skip／5198／47.96秒另列；targeted69是新增2測試前結果，不冒稱最後 targeted71已獨立跑過。唯一 skip 為沿用 runtime Windows symlink 權限限制。

主提前 review 實證 numeric JSON `9007199254740993.0` 被 float 捨入，退回 C019-B 在同 task 修為 Decimal；同一 precision probe 從 false 轉 true。loader 增加 expected_market_date 在 publication 前核對，以及 select 時重驗物件時間/hash與 materialized body/receipt。不是改寫驗收接受錯值。主獨立30checks通過：R18 saved live bundle1379列中1367有效逐值一致、12不可用；原 bytes/hash/UTC、選列與 malformed ZIP/JSON/pins/date/time/數值反例、物件漂移及既有輸出拒絕。另7checks以 saved bundle→真正 TwseAdapter／OfficialMarketDataAdapter／collect→隔離 MarketBar／RawPayload，輔助 TWSE endpoint 是本地 fixtures、TPEx 是 empty-batch stub、所有 live HTTP 禁止；驗2330值與raw link、1472／999999缺漏warn+舊bar保留、同run raw重用、原獨立指數session不增加、integrity/FK。這不是兩市場 live 或官方 truth。

完整主證據在 stock-r19-coordinator-review：full-backend-review.json/log、independent-capture-review.json、independent-consumer-review.json、volume-precision-probe-before.json／volume-precision-probe.json、live-content-oracle.json、scope-review.json及對應runner。作者完整備份／diff／delivered snapshots與logs在stock-r19-implementation。sources.py SHA FC032D0079803095B29D44570174DA36B4EEBA58C533214D7D3D465631E25F59；stock_day_capture.py SHA 4CACA05D473AE18F8695859FC915C497D3E051AB1AB864E6F35ABD9022A80132；test_stock_day_capture.py SHA 18297BAE99CCB8A4609C37549105303A2D9C2176AD463F23AE602002CB2591B2。

現有狀態限制不擴寫：缺漏與其他條件可能 partial 或 failed，空index原gate仍failed且raw保留；force=True不刪舊bar。原始body/receipt是外部plain files，exclusive xb+lock不覆寫，並非雙檔atomic或永久immutable store；select重驗內容。captured_at進新RawPayload UTC，MarketBar.collected_at仍為ingestion now，adj_close既有fallback不代表還原真值。同 ingestion_run_id/source/endpoint/sha256 raw去重保留原path/time，不是每次capture都新增persisted time receipt。C007 strict store、firstavailability、PIT、完整collector gate及正式DB修復仍未完成。D021-B提案已主review，D021-C現僅收斂SOURCE_REGISTRY／OPERATIONS／ROADMAP／ROADMAP_EXECUTION，完成freeze後才I058索引。

D021-C 四文件已主完整 diff／source／SHA review 接受：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION。已修正三個 STOCK env 在 import 前指向專案外 Temp 的操作範例；精確區分 loader 全體 container/code/date 驗證與 fetch_bars 呼叫 capture.select 的 selected numeric 驗證，補回其餘內容／時間 strict evidence 待辦；未將 1367 rows 寫成1367單值，也未把 unsigned receipt 說成全面防偽。D021-C完整備份在stock-r19-docs-d021-c-20260913，SOURCE的pre-B原件另在stock-r19-docs-d021-b-20260913-034603。作者相對連結targets／空白檢查通過；主final-docs.diff另對輪初原件逐段複核。

四docs最終SHA：SOURCE_REGISTRY 8DAF2AD2A6889AA6AFC80AD0C7F3EDEB5D5B446FB44C7FCE7A48F1C83954582D；OPERATIONS FF1B33372F0E667678F25390B775F8D60CDDF4527E74EA40BC11C452C5CCF621；ROADMAP 8952F8AFC6E9601D985667791FDBB26C817E1BE767D9171BF7079AFBD600976F；ROADMAP_EXECUTION 00092445B158C541B24C9AE84C50C9CEA343B94274E4B57E2B63FE8A23381676。

現在三code/test、四docs與本協作紀錄共8source共同freeze；另兩DB及根README共11paths保護。I058輪末只更新worker/tests/docs，確認兩新檔由not_tracked納入、load/select/Decimal/expecteddate/history排除及具名integration tests／5docs可查，保留metadata_changed/best_effort、既有SQL partial與root README/AGENTS無index限制。索引與最終交接receipt存專案外/task，不反覆改來源造成刷新循環。主獨立複核接受後才建立R20四個新local task，下一位統籌核四ID並確認接手後派工；R20先按ROADMAP／依賴選一個最小既有consumer domain，不預先指定四域或再造無消費者foundation。本輪沒有stage/commit、正式DB寫入、新live、依賴安裝或服務啟停。

## Round 18 來源 runtime／collector 接線（2026-09-13，已接手；程式／文件已有限 review 並 freeze；輪末索引另核）

R18 統籌逐一 read_thread 核對四個既有 local task ID、title、cwd 與待命狀態，已向 R17 確認接手；R17 停止派工及來源寫入，只補交接。不重建、fork 或改用 worktree。

| 角色 | Task ID | 模型／Reasoning | 寫入範圍 |
| --- | --- | --- | --- |
| 統籌／review | 01a096fb-5d7a-7970-b5cf-563d5b8b8a26 | gpt-6-astra／high | TASK_COORDINATION、必要 HANDOFF／AGENTS；獨立 review 證據存 Temp。 |
| C018 程式 | 01a096fb-944d-7ae2-9ac2-fd384c93a44f | gpt-6-astra／medium | 先唯讀定界；實作限主後續指定 worker 與 tests。 |
| D020 文件 | 01a096fb-d30f-7052-8937-8ea4005906a1 | gpt-5.6-sol／xhigh | 先唯讀定界；SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION 待契約核定後寫入。 |
| I057 索引 | 01a096fc-0f53-7542-8b6f-3f93cfa5f0ec | gpt-5.6-luna／medium | 輪末 review／freeze 後統一更新涉及分區及 coverage；目前待命，不做輪初 baseline。 |

承接 R17 C017-C／D019-D／I056 的有限驗收：主 full backend 481 passed／5066 warnings／49.91 秒，actual parsers→本地 fixtures→collect 11checks、SQLite caller rollback probe 通過。I056 worker354/1575、tests560/2544、docs394/393；9path tracked/no_recorded_issue，metadata_changed/best_effort 限制保留。根 README 外部改動保留，不列 R17 或 R18 成果；兩正式保護 DB 禁寫。完整 R17 最終 receipt 與 R18 四 ID 存 stock-r17-coordinator-review。

R18 主先查 App codebase list/status/coverage，通道可用；worker/docs ready，相關來源 metadata_changed，故核對原檔並集中輪末刷新。stock-r18-coordinator-review/round-baseline.json 與 before/ 保存 138 個來源完整備份；guards.json 保存 data/stock.db、.local/data/stock.db 與根 README 的 SHA/size/mtime，三者吻合 R17 交接。每個角色修改既有檔前仍須完整外部備份。先盤點 R1-A1 runtime conditions／collector opt-in 的最小可操作工程；正式分類修復、PIT、付費／帳戶／交易／部署不在授權內。C018-A／D020-A 目前只讀，角色須回報交付、實際證據、限制及 freeze，由主 review 後授權下一步。

C018-A 唯讀 review 已接受。C018-B 僅新增 worker/source_runtime.py 與 tests/test_source_runtime.py，提供獨立明確 opt-in 的單來源 capture 命令；四個 R09 exact GET allowlist，manifest/profile/source/version+digest/output 必填。兩用途 local_fetch/raw_store 與全部 condition 前置檢查；一次 GET、無 retry／redirect／warmup、有界 timeout／response bytes，429／503 即停並保存 Retry-After。respect_endpoint_limits 是本地保守操作策略，數字官方配額仍 unknown／rate_limit_verified=false；不宣稱跨 process 限流或完整 legacy collector gate。保存實際 response bytes、aware UTC、hash 與 manifest-derived attribution 到專案外新／空目錄，無 DB／summary／PIT 接線。D020-B 先撰 SOURCE_REGISTRY 契約，主程式驗收後才收斂其餘三文件；根 README 與現有 registry／sources／pipeline／cli 不改。

C018-B 兩新增來源已主有限接受並 freeze。主完整 backend：519 passed、1 skipped、5066 warnings、pytest57.36秒（process58.75秒）、exit0，Python3.12.14／Alembic1.19.2；all backend/app/worker/tests/alembic、frontend/src 來源與兩 DB 前後 SHA/size/mtime 一致。作者 final full 為519／1skip／5066／57.75秒，targeted54passed／1skip／2.21秒，分列。Windows symlink 因權限不足 skip，junction 實際 pass。主獨立 33checks 全過，涵蓋四 exact GET/bytes/ZIP/hash/attribution、pin/profile/source/URL/conditions/quota 前置拒絕、限流/redirect/invalidJSON/oversize 停止及競爭保留。

主另以新 CLI 對 STOCK_DAY_ALL 做一次真實公開 GET：HTTP200、319396 bytes、1379列，body SHA256 0b1aff71084982ae31d719b47fff2c975205c6173ccb6d083232b4f5eeb23cbe，ZIP body/receipt 一致，沒有 legacy data/raw/DB 建立。僅此 endpoint 當次 transport/capture 證據，不外推四來源 live truth、歷史/PIT或權利新查證。artifact 在 stock-r18-live-izyrjlk3/capture/capture.zip；主報告/runner在 stock-r18-coordinator-review（full-backend-review.json、independent-runtime-review.json、live-capture-review.json）。作者完整交付在 stock-r18-program-308a8c751d534e729c955442e8888a41。

新source_runtime.py SHA4E80D8D4977BBF317892F31593853F42E368240EA7E5C12FC2E47CEF74FA927D；test_source_runtime.py SHA7164630ABABD255B430BD76385DCB0BFE9B58462FB4F82A684CB46FF55BA38C2。數值官方配額仍unknown，失敗receipt保留known/prohibited原證據；只支援identity entity body、5MiB cap、15秒per-operation timeout與30秒cooperative chunk deadline（非hard total）、hardlink FS exclusive ZIP publication。兩新檔輪初not_tracked須由I057輪末納入。D020-C正在四文件收斂，完成主review/freeze後才開索引gate。

D020-C 四文件 final 已主 source/diff/SHA review 接受：SOURCE_REGISTRY、OPERATIONS、ROADMAP、ROADMAP_EXECUTION。初稿退修精確區分 receipt 頂層與 attribution 欄位、33 independent checks 與完整 pytest 的證據歸屬、full測試guard僅程式／測試來源及兩DB、不含docs；R19改為由新統籌先唯讀盤點再選單一domain，不預授權四域或新增正式分類修復前置。文件完整備份在 stock-r18-d020-final-docs-d0b093dbe8f242ef91df789f3609b549，原始pre-D020 SOURCE_REGISTRY另在 stock-r18-d020-source-registry-c20cbbc2dd3b470ab515f1d262f7538b；主round before備份可作整輪可信diff。作者85個本地link file targets無missing，主已核實最終欄位、命令與具名限制。

現在兩新code/test、四docs與本協作紀錄共7source共同freeze，兩DB與根README另列guards，共10paths。I057僅在本輪末更新worker/tests/docs，須將兩個not_tracked新檔纳入、核capture/_publish/_output_path/CLI及新測試、五docs可查；root README/AGENTS仍無rootindex，未改app/frontend分區保留舊generation，既有SQL partial限制如實保留。索引結果由主另核並存專案外/task receipt，不回寫造成刷新循環。主複核接受後才建立R19四新local task交新統籌；此前三R19角色不存在，不得重複派工。

## Round 17 ETF／新上市期間（2026-09-13，程式／文件已有限 review 並 freeze；輪末索引另核）

R17 統籌已逐一 read_thread 核對四個既有 local task，並向 R16 確認接手。R16 停止派工，只補交接；不 fork 或重建角色。

| 角色 | Task ID | 模型／Reasoning | 寫入範圍 |
| --- | --- | --- | --- |
| 統籌／review | 01a096d6-bba3-7482-bd5a-2438cfd33d3e | gpt-6-astra／high | AGENTS、TASK_COORDINATION、HANDOFF；驗收證據存專案外。 |
| C017 程式 | 01a096d7-304b-7730-a13d-883d6a5380f6 | gpt-6-astra／medium | 定界後僅 pipeline.py 與必要 tests；其他來源擴張先交主 review。 |
| D019 文件 | 01a096d7-3936-7db1-80fc-cb2d86537835 | gpt-5.6-sol／xhigh | INDUSTRY_CLASSIFICATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS；不改程式或協作紀錄。 |
| I056 索引 | 01a096d7-45be-74e1-8361-1387ae71272c | gpt-5.6-luna／medium | 僅輪末 freeze 後索引及 coverage；不改來源。 |

索引角色誤建額外 task 01a096d7-a98f-79c3-b037-2dbaebd0adce，主已通知額外 task 停止動作、僅待命，並重申原索引角色責任；保留歷史，不刪除或封存，額外 task 不列入本輪派工。

輪初 App codebase-memory 可用；worker ready 353 nodes／1561 edges，pipeline/sources 與三份初查文件皆 tracked/no_recorded_issue，但 freshness=metadata_changed，故直接核來源並集中輪末刷新。專案外 stock-r17-coordinator-review/round-baseline.json 保存139個來源／設定／資料庫檔基線，正式與 .local DB 禁寫。先唯讀盤點 ETF 類別觀測、上市日期與新上市60日窗口、同日／未来／closed期間及domain隔離，再定界最小可驗工程；不把上市日當ETF分類真值，不撤前端guard。每角色須回報交付檔案、實際驗證、限制及freeze，由主接受或同task退修。

R16 最後接受版本為 C016-D：主 full backend 412 passed／4902 warnings／31.67秒，actual universe parsers→collect 11checks及aware UTC probe通過。I055最終外部receipt與主複核已關閉輪末gate：worker353/1561、tests522/2253，generation=recorded_at=2026-09-12T18:12:53Z；docs384/383，generation17:31:13Z、recorded_at18:12:51Z。9paths tracked/no_recorded_issue/metadata_changed/best_effort，新test已tracked；既有SQL partial、app舊generation及root無index限制保留。證據根 stock-r16-coordinator-review；以下R16 pre-index文字保留為歷史freeze，不重開已接受工作。

C017-A／D019-A 唯讀盤點後，主已在外部記憶體SQLite重現四個舊缺口：ETF回填上市日、空category留open、D晚於score仍新增、IPO第61天仍hot。baseline-reproductions.json及reproduce_baseline.py保存在stock-r17-coordinator-review；WindowsApps python alias首次exit1無輸出，不列驗證，改bundled Python實跑exit0。作者唯讀targeted41 passed是修改前證據。

C017-B定界只改pipeline及必要tests：ETF有限category從唯一可信capture台北觀測日D向前採用，明示本地推定；newlisting新列從D至上市日+60（inclusive），future listing不預建、missing listing unresolved。bounded同expiry重跑no-op；legacy open在窗口內保留原from而cap expiry，已過期僅close D-1，不回寫過去錯期間。ETF／新上市僅各自exact provenance及canonical domain轉換，missing/ambiguous category拒絕，same-day／future／overlap／identity衝突拒絕；manual、其他hot、industry、缺席及無權威universe的synthetic index保留。移除廣泛legacy deactivation副作用；helper savepoint及collect rollback保障失敗原子性。各domain receipt置於原industry receipt內獨立節點，舊industry scope/count不變；force history／reused成功／failed attempt需保留。D019先寫分類契約，主驗後才收斂其他三文件。ETF mapper品質、industry/type lifecycle、legacy歷史、PIT與正式修復仍未完成。

C017-B主完整backend477 passed／5044 warnings／pytest54.31秒（process56.047秒）、Alembic1.19.2，測試前後來源與兩DB不變；actual兩market universe parsers→本地fixture→collect11checks亦通過。初始獨立harness曾把failed force應保留的「最近成功repeat receipt」錯比成前一次transition receipt，已改為最近成功並重跑；保留初始失敗log，不宣稱receipt action在成功重跑間不變。

主另以既有instrument、新Session僅SELECT且無pending DML的file SQLite實證：helper savepoint RELEASE可在沒有physical BEGIN時提前提交，caller rollback後仍留1membership。因此B未接受，已退同task C017-C保證外層真實transaction，再驗caller rollback／commit、savepoint失敗保留caller先前DML、collect後段失敗回滾。B477與作者B477均為中途證據，不能當C最終。

範圍audit另見根README在輪初後被本輪角色以外修改，新增索引commit文字；R17角色未修改或回退，來源與授權尚未核實，單獨保留，不算R17交付。正式與.local DB仍與輪初一致。D019-B僅append分類文件§7，主用原長度切prefix核SHA與輪初完全一致並另存原件；兩既有tests未由作者改前另備份，主已用R16 final diff重建原件且逐一核R17輪初SHA完全一致，用於可信diff review。

C017-C最終程式已主有限接受，四來源freeze：pipeline.py、新test_etf_listing_membership_collection.py、test_official_membership_collection.py、test_pipeline_integration.py。主完整backend **481 passed／5066 warnings／pytest49.91秒（process51.328秒）／exit0**，Python3.12.14及既有Alembic1.19.2；作者C同481／5066／51.55秒分列。主file SQLite rollback probe由false轉true，rollback後group/member均0；actual parsers→collect11checks在C再次通過。作者新增4個transaction cases已red→green，主逐一讀測試並在final full重跑；四来源及兩DB before/after hash/size/mtime均一致。未安裝依賴，作者早期venv缺tzdata collection失敗與中途B結果保留、不混作final。

最終主證據根stock-r17-coordinator-review：full-backend-review.json、full-backend.log、independent-collector-review.json（C版runtime r17-independent-hqhk1dp1）、savepoint-rollback-probe-before.json／savepoint-rollback-probe.json、scope-review.json及各before備份；作者C證據根r17-c017c-8f72f6f4f1064b73b19175e72b18ffe3，B證據另存r17-c017b-9372bb233c0a45ce907fcd7cf25dafff。這只接受ETF本地heuristic觀測期間／newlisting有界窗口與具名交易保障，正式DB、legacy前史、真正來源truth/PIT、其他domain lifecycle及guard解除仍未完成。D019四文件收斂後再freeze交I056輪末worker/tests/docs索引；索引成功另由主核，不替代功能驗收。

D019-D四文件已主逐段source/diff review並核final SHA接受：INDUSTRY_CLASSIFICATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS。精確區分事件窗口L..L+60與新membership=[D,L+60]、future capture拒絕與D>score跳過、ordinary及兩子scope狀態、SQLite caller transaction，保留所有未完成邊界。主D019-final.diff／D019-final-review.json保存對照；三文件作者備份在stock-r17-doc-backup-876dcea4cd524fdcbe34efce11327e91。現在四code／test來源、四docs及本協作紀錄共9來源共同freeze；兩DB與外部README另列保護檔，round-source-freeze.json共12paths。139輪初目標130未變、8既有授權檔變更及1外部README變更，新專用test另核，不把外部修改計入本輪成果。

I056只更新worker/tests/docs涉及分區，核新helper、SQLite BEGIN與新測試符號／coverage；新專用test刷新前not_tracked須確認刷新後tracked。root AGENTS／README沒有root index，app與其他無source變動分區保留舊generation限制。最終index receipt與下一輪四ID存task交接／專案外證據，由主複核後關gate，避免回寫來源導致刷新循環。下一輪先在source registry runtime／collector opt-in及正式分類修復前置間唯讀定界，不為罕見type switch延長foundation。現有正式庫禁寫／guard及既有服務仍保護。

## Round 16 分類收集期間接線（2026-09-13，程式／文件已 review 並 freeze；輪末索引另核）

R16 統籌已用 read_thread 核對以下四個既有 local task ID，並向 R15 統籌確認接手；不重建角色。R15 停止派工，只補交接。

| 角色 | Task ID | 模型／Reasoning | 寫入範圍 |
| --- | --- | --- | --- |
| 統籌／review | 01a096af-3383-7fe0-91cc-d2c749458d6d | gpt-6-astra／high | AGENTS、TASK_COORDINATION、HANDOFF；驗收證據存專案外。 |
| C016 程式 | 01a096af-b152-73a0-a519-ca7611b14ed7 | gpt-6-astra／medium | pipeline.py、新 test_official_membership_collection.py、必要 test_pipeline_integration.py/test_backfill.py fixtures。 |
| D018 文件 | 01a096af-b83d-7771-8182-26b1c6673b47 | gpt-5.6-sol／xhigh | INDUSTRY_CLASSIFICATION.md 契約；主驗後 ROADMAP、ROADMAP_EXECUTION、OPERATIONS 狀態收斂；不改程式與協作紀錄。 |
| I055 索引 | 01a096af-bf6d-74b0-8180-c5f3033b272b | gpt-5.6-luna／medium | 僅輪末 freeze 後更新涉及分區及 coverage；不改來源。 |

候選範圍是日常 collector unknown／special 舊關聯、same-day／future period 與 backfill 時間口徑。先依來源能力定界，不以 listing_date 或行情 score_date 補造歷史分類真值。正式 data/stock.db 與 .local/data/stock.db 禁寫，輪初 SHA256 與 R15 交接一致；保留前端 guard 與既有服務。各角色須回報交付檔案、實際證據、限制及 freeze，由本輪統籌接受或同 task 退修。

C016-A／D018-A 唯讀盤點後，定界為 stock／ipo 的 ordinary-industry domain：以唯一匹配 exchange/source/authoritative listed endpoint/digest 的 capture 觀測日向前更新，D 晚於行情 score_date 時只跳過 industry 並留獨立 partial receipt，行情可繼續。非空 ASCII numeric unknown／special／unsupported 才能形成可信空集合；缺欄、空白、非 numeric 或證據衝突拒絕 normalization。TWSE new-listing-only IPO 限定為 unresolved skip，不升格 ordinary evidence。ETF/new-listing 保留既有日期行為，domain 不再互關；其時間風險尚未解決。

統籌已以修改前 pipeline 備份與記憶體 SQLite 重現上市日回填、special91 留舊關聯、同日錯分類兩 open 三個缺口，證據在專案外 stock-r16-coordinator-review/baseline-reproductions.json。C016-B 作者最後完整 backend 407 passed 僅屬中途交付；主 source review 發現 invalid collected_at 導致失敗 handler 二次例外、run 卡 running，退回 C016-C。C版須拒絕 DB default now 補造 capture 時間；有效 raw 可保存，無效 metadata 無法入庫時仍保存原始檔指向／digest／null 或 invalid marker／入庫失敗原因，可靠記錄 run.failed。成功 receipt 與失敗 attempts 分開保留，強制重跑不刪除先前成功證據。最終功能驗收與 freeze 尚待主確認。

C016-C 已經主逐檔 diff／source review 並有限接受，四來源 freeze：pipeline.py、新 test_official_membership_collection.py、test_pipeline_integration.py、test_backfill.py。主最後版本完整 backend **410 passed、4834 warnings、pytest 33.94 秒、exit 0**（process35.454秒），沿用既存 Temp Alembic1.19.2，未安裝依賴；測試來源與兩DB before/after hash、size、mtime一致。作者最後 C版同為410 passed／34.93秒，與主證據分列，不沿用 B版407宣稱最終。

主獨立以 actual TWSE／TPEx universe parsers 處理本地官方形狀 fixture，再走 collect：cross-market canonical 共群、上市日不回填、產業切換與 TPEx80關舊、同觀測重跑group/member/score不變、same-day與missing失敗rollback（含全instrument/bar欄位）、manual及9/8歷史score保留、D晚於score skip、integrity ok／FK0 共11項通過。這不是新官方網路證據或歷史PIT。初始主 harness 將正常重抓的 bar.collected_at 也要求不變而失敗，已按正確範圍修正；final C版重新執行通過，未藉此宣稱整個正常收集所有表不變。證據：stock-r16-coordinator-review/full-backend-review.json、full-backend.log、independent-collector-review.json；119檔 baseline 比較僅授權來源／docs有變更，新專用test另核hash。文件 final及輪末I055尚待接受。

主在輪末核對 aware timestamp，另以記憶體 SQLite 實證 `2026-09-11T01:00+08:00` 被直接存成 naive 01:00，重讀 receipt 誤標為 UTC，較正確9/10T17:00Z差8小時。C016-C 接受因此暫撤、退修同task C016-D；限新raw入庫前aware→UTC naive，不改legacy DB/schema，補真正collect與forced重讀時區測試。C版410與上述11checks仍是C版證據，D版最終結果另核；不得沿用舊freeze結案。實證為 stock-r16-coordinator-review/aware_timestamp_probe.py、aware-timestamp-probe.json。

C016-D 主最終有限接受：新raw aware timestamp入庫前正規化UTC-naive，既有naive依原capture UTC契約，舊row不辨識或改寫。主完整 backend **412 passed、4902 warnings、pytest31.67秒（process33.031秒）、exit0**；作者同D版本412／32.97秒。主同一時區probe由false轉true，actual parsers→collect11checks在D版重跑通過；所有程式／保護DB before/after一致。final reports沿用 full-backend-review.json、full-backend.log、independent-collector-review.json；中途C證據另存檔名c016c，aware-timestamp-probe-before.json保留錯誤重現。四來源最終freeze，文件及I055索引gate仍待主接受。

D018 四文件（INDUSTRY_CLASSIFICATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS）已主逐段對齊 final source／證據並接受，與本協作紀錄共同 freeze。明列 run 行情 success 與 industry partial、observations/history/failed attempts、invalid raw 僅檔案／失敗metadata可能保留、aware新raw UTC-naive與legacy不回寫、domain不變範圍及歷史PIT限制。根AGENTS、API/frontend/schema/sources.py/taxonomy.py與兩DB不改。下一輪先唯讀定界 ETF/new-listing 期間與domain lifecycle，正式DB實寫仍須具體授權；不為已接受R15/R16重跑大型診斷。

R16 輪初 App codebase-memory 可用，輪末再次查 coverage 時出現 Transport closed；主依AGENTS改用相同引擎CLI驗證 docs coverage成功，未重啟App/MCP或變更全域設定。I055依此使用可用通道統一更新 worker/tests/docs 涉及分區並核9個freeze來源路徑；app無source修正而保留R15舊generation限制，root AGENTS無索引。最終index receipt與下一輪四task IDs在外部證據／task交接回覆，由主另核，避免寫入snapshot後無限刷新。

R15 輪末索引 gate 已由前任主複核關閉：外部 stock-r15-coordinator-review/I054-index-receipt.json、coordinator-final-coverage.json、coordinator-final-index-status.json、coordinator-index-final.json。app 786/3714（舊 generation 2026-09-12T01:41:10Z、recorded_at17:30:58Z）、worker352/1538（17:31:03Z）、tests494/2025（17:31:08Z）、docs376/375（17:31:13Z），日期均為2026-09-12 UTC。ready／best_effort／metadata_changed 限制保留，tests synthetic_prehead SQL partial、root AGENTS 無索引亦保留；以下 R15 pre-index freeze 文字為歷史記錄，不重跑已接受副本。R16 初查 App MCP 可用，相關來源 metadata_changed 故直接核對，待刷新路径集中輪末交 I055。

## Round 15 市場別分類修正（2026-09-13，程式／文件已 review並freeze；輪末索引另核）

R14 統籌 `01a0935c-c1da-7411-ace2-eb84f8fb5b62` 已正式交接；R15 統籌逐一核對以下四個現有 local task ID 後確認接手。舊統籌停止派工，僅補充交接；不重建本輪角色。

| 角色 | Task ID | 模型／Reasoning | 寫入範圍 |
| --- | --- | --- | --- |
| 統籌／review | 01a09693-1a49-70b2-86a9-c717f5af117b | gpt-6-astra／high | AGENTS、TASK_COORDINATION、HANDOFF；獨立驗收證據存專案外。 |
| C015 程式 | 01a09693-59ca-7ce0-afad-b69c54e2a74a | gpt-6-astra／medium | app/taxonomy.py、必要分類測試及隔離修復工具；pipeline/API 擴範圍先交主 review。 |
| D017 文件 | 01a09693-93db-7dd0-82d2-356c2718ffd3 | gpt-5.6-sol／xhigh | docs/INDUSTRY_CLASSIFICATION.md、UX_REVIEW、ROADMAP、ROADMAP_EXECUTION、OPERATIONS；不改程式或協作紀錄。 |
| I054 索引 | 01a09693-d03d-7031-b914-d604ffa14275 | gpt-5.6-luna／medium | 原 local 目錄輪末索引與 coverage；不改來源、不另建 task/worktree。 |

本輪先核 TWSE／TPEx 官方完整代碼表，修正市場別 mapping，驗 collision、unknown、unsupported，再以新隔離副本核 memberships 有效期間、scores、候選及衍生輸出、重跑與追溯。正式 data/stock.db 與 .local DB 禁寫，既有前端分類待核實警示保留。coverage API exit1 原因未確定，由統籌另在新隔離環境診斷，不中斷既有服務。角色交付檔案、實際驗證、限制及 freeze 給本統籌，由主接受或退修，不能自行結案。

R14 有限 UX 已接受，輪末索引 gate 由舊統籌專案外 `stock-r14-coordinator-review/R14-index-receipt-20260913.json`、`coordinator-index-final.json` 關閉；pre-index 文件中的待複核字樣為歷史 freeze。frontend-src/full generation 為 2026-09-12T16:59:24Z、docs 為16:59:35Z；coverage 仍 best_effort／metadata_changed，app/worker 舊 generation 限制保留，不把索引當功能驗收。R15 App MCP 此刻可用，不抹除 R14 Transport closed 歷史。

### C015 有限 review 與後續界線

官方 shared codes 的當期意義相同，舊 TWSE22＝油電的註解本身錯誤；依 TWSE 基表與2023變更、TPEx當期表修正 TWSE18/19/20–31，移除 TPEx停用18，保留市場專屬與特殊80/91的 fail-closed。六檔交付為 taxonomy、隔離 industry_repair 工具、三個測試檔及官方 code-set fixture。統籌逐檔 review，退修既有 canonical group identity／inactive 邊界後，獨立完整 backend **372 passed、4625 warnings、22.41秒、exit0**；使用既有外部 Alembic1.19.2，沒有安裝套件。六檔 freeze 與正式／.local DB 的 hash、size、mtime在測試前後一致。

統籌獨立 SQL 驗收新副本：1,974 supported active stock/ipo 各恰一預期產業關聯；35 unknown／special各0；關閉TWSE845＋TPEx706＝1,551筆，新增1,541筆，原2,403 membership列保留且只改必要valid_to。current副本切界9/13，舊9/8 scores與原signals／追蹤等表不變；另一組9/8 counterfactual共用同一價格、籌碼、features snapshot。主逐表核原始輸入／研究歷史、各score成員數與1/5/20日均值、null score無候選及integrity／FK。baseline41／corrected52 score rows，45列差異含新增；各4,616診斷訊號，3,048 rationale差異、18 evidence差異，只有8筆status與quality變更（9103、9105、912000、9136各兩策略：observation→data_incomplete），不能稱3,048個決策變更。

作者final副本與報告在 `C:/Users/YiCheng/AppData/Local/Temp/stock-taxonomy-diagnostic-dbv_xvgb/`；主驗收在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r15-coordinator-review/` 的 `full-backend-review.json`、`independent-final-db-review.json`、`final-scope-review.json`。fallback migration於副本完成、markers0001–0006、alembic_head空；未宣稱正式 migration。當期table只解讀legacy raw，不證明fresh公司分類或歷史PIT，正式DB仍錯、前端guard保留。

coverage診斷：新readonly副本四種TestClient請求HTTP200；新動態port的uvicorn單次coverage與後續2330個股HTTP200且服務仍存活，測後只停止該自建PID31812。default coverage約19.5秒／2.78MB，TestClient程序峰值約584MB；本次未重現退出，R14 exit1原因仍未知，未驗併發／長時穩定性。來源修正不包含API或backfill效能。

C015六檔、D017五文件均已freeze，主接受上述有限範圍並核final hashes；模型第二次重跑由作者執行、主review程式及final report，未冒稱主再次獨立重跑整套模型。本協作紀錄亦freeze，交I054統一更新app／worker／tests／docs；輪末receipt及下一輪四ID交接留task，不為寫receipt反覆修改snapshot，索引成功不替代功能驗收。後續可獨立工程包括既有collector unknown不關舊關聯／同日衝突的period接線、來源時間與正式操作前置；正式庫實寫仍須另有具體授權。

## Round 14 全站 UX 修正（2026-09-12，使用者實察回饋優先）

使用者指出各頁排版擁擠、卡片內容過多、未分區、未知資料、非台灣用語，以及股票數量應以張顯示（1張=1000股）。R13 的功能驗證不等於整體 UX 合格；本輪先修正主實際逐頁看到的問題，不推進新後端 foundation。

| 角色 | 新 Task ID | 模型／Reasoning | 寫入與責任 |
| --- | --- | --- | --- |
| C014 程式 | 01a0943c-c492-7100-8382-44f3953fd734 | gpt-5.6-luna／xhigh | 僅 frontend/src 必要組件、樣式與對應測試；清楚列表／詳情、個股分頁、台灣文案與張数。 |
| D016 文件／邏輯 | 01a0943c-c845-7db2-8ae3-f592b7c23903 | gpt-5.6-sol／high | 核來源單位、unknown／未評估语意；只修改產品／ROADMAP／執行／操作／個股契約，必要時一份短 UX_REVIEW。 |
| I051–I053 索引 | 01a0943c-cca7-79f0-8f20-69717c3c8e2e | gpt-5.6-luna／medium | 外部 baseline，主接受後再更新 frontend 兩區及 docs；不改來源。 |

I051 外部基線 `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-research-R14-I051-20260912-141137/` 的 MANIFEST.json 共90檔，包含21個 frontend source 原文、套件／lock、backend source、文件與兩DB。主核21/21 source hash一致後授權C014開始。保護backend/worker/migrations/package/lock/正式及.local DB與既有服務；主獨占AGENTS/TASK_COORDINATION/HANDOFF。需要單位證據時只讀來源，不因顯示張數改寫儲存值。

主已實看首頁上下、新聞列表與長標題詳情、族群列表／詳情、個股列表／詳情全段、行動中心與研究／系統頁。確認新聞時間壓住標題、巨大頁標、複雜行動卡、族群重複指標、個股圖表在第二屏、左右研究卡被20列籌碼撐成大片空白。修正方向：精簡報價與卡片、點入詳細、技術／籌碼／新聞／研究／資料說明分頁；已知缺口保留短提示，未提供／未評估不冒充不足或填0。下一批改下一頁，保存持倉改儲存庫存，紅漲綠跌。股數依來源轉張（可含3位小數與負流量），原已是張的欄位不重複除1000，報價與金額不轉張。參考 WantGoo 官方App介紹的報價列與分類資訊層級，不複製素材或新增其未有資料的功能。

每角色交付给主，主實際逐頁與手機操作、單位手算、關鍵互動及前端驗證後才接受或退回；不得自行結案或啟動下一輪。文件／索引收尾保持精簡，不能以測試全過替代使用者體驗驗收。

### 2026-09-13 單次 heartbeat 接續與 review

沿用 C014、D016、I051–I053，未重建角色、未變更 automation 週期。前次 C014/D016 因平台用量限制中斷；本次已收到 C014 退修交付及 D016 唯讀核查，並恢復同輪修正。現行四角色／輪末索引規則不回寫既有 R14 task 模型。

主重跑外部 `stock-r14-coordinator-review/verify_frontend.ps1`：六個 self-test 檔、32 項獨立資料轉換／邊界檢查、typecheck、production build 全 exit 0。這是目前修正版證據，最後分類警示補丁尚待交付後複核，不能據此先標整輪通過。真實隔離 API/瀏覽器已核台積電成交量 28,931.697 張、法人 +5,496.736／+1,204.619／-397.962 張、融資 +60 張，以及 +10（+0.41%）；320px 新聞頁 clientWidth/scrollWidth 同為305，已消除捲軸造成的橫溢出。前次新聞第1→2頁無重複、上一頁還原相同20筆；最後一頁真18筆的固定20筆標示已退修。

D016 發現正式舊庫 TPEx 有效產業 membership 890 筆中706筆不符官方代碼，code22的98檔皆仍放Shipping；3176基亞為具體重現。當前TPEx映射已修，但TWSE對照另有錯位；不得直接全市場重跑正式庫。C014只增加「既有族群關聯待重新核實」與原值追溯，不能把警示或中文alias宣稱為分類修復。下一個優先工程為官方市場別對照修正、測試及隔離副本重建驗證，正式庫授權邊界維持。

App codebase-memory仍回報Transport closed；同引擎CLI exact coverage可用，相關來源metadata_changed，累積至輪末刷新。主對I051基線核對：backend/package/lock/兩DB未變；原保護清單內docs/README.md另有2026-09-13協作規則更新，已辨明並保留，不能歸因於C014或回復它。最終程式／文件freeze、逐頁review及輪末索引尚待本輪收斂，不建立下一輪空轉task。

### R14 最終前端 review 與 freeze（2026-09-13；輪末索引另核）

主已接受本轮有限前端 UX：精簡卡片、分區與個股五分頁、日 K／成交量張數、法人正負張數、融資不重複換算、台灣操作文案、新聞末頁真實筆數、來源／原值展開，以及既有產業分類待核實的明確提示。不是正式資料修復或整站資料完整性通過。C014 最後 App.tsx SHA256 為 `E5B40AA5382123DE15A68181C29F90FFDD1F2DBAF1F194EEA7D9078E34EC0E21`；其餘最終來源與文件 hashes、主逐頁核查及完整限制見專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r14-coordinator-review/FINAL_REVIEW.md` 與 `final-source-hashes.json`。

主獨立重跑六個 selftest、32 independent、typecheck/build 全 exit 0；最後 ErrorBox 中文文案的小修由主讀 source，C014 同 runner 全通過。瀏覽器核新聞 20/20/18 筆與最後 next disabled、回第一頁；鍵盤 Enter 啟用研究 tab；390px 日 K 與張數軸、320px 無行情提示、768px 族群分區、籌碼原值展開。研究條件前先告知分類待核實，族群中文標題加「（既有分類）」，不冒稱 mapping 修好。

本輪有一項明確未通過的資料頁複驗：最後開啟 `/research/coverage` 期間，隔離唯讀 API 8133 意外 exit 1，無捕獲 traceback，原因尚未確認；主只恢復自身已退出的測試服務，個股／資料品質頁恢復正常。覆蓋頁真資料複驗保留下一輪隔離診斷，未停止使用者其他服務或寫正式庫。庫存只驗表單／純單位換算，未對唯讀庫做寫入驗收。所有測試行情仍是 2026/09/08 snapshot。

C014、D016 交付維持 freeze，由同輪 I051–I053 做一次輪末合併刷新，主核 coverage 後才整輪接受。CLI 索引最終 receipt 留在 task 回覆；不為寫 receipt 反覆改來源。下一輪按現行四角色規則交接，首要範圍為市場別產業 mapping、隔離副本重建與衍生結果驗證；新 task ID／接棒確認於交接訊息記錄，未確認接手前本主仍負責本輪。

## Round 13 重新定界（2026-09-12，程式與文件已 review）

使用者在新統籌檢討 R01–R12 的可用成果後，同意先交付可操作的個股研究流程，並詢問個股 K 線圖。原本 C013 的 signal comparison／store readonly 工作延後，原 B2／B7 驗收與既有成果保留；不以本輪頁面成果宣稱那些缺口完成。以下新分派取代交接時的 R13 範圍與白名單。

| 角色 | Task ID | 模型／Reasoning | 本輪責任 |
| --- | --- | --- | --- |
| C013 程式 | 01a09353-7608-7b90-a0d6-cd8c02ca6743 | gpt-5.6-luna／xhigh | 沿用已存在 task；恢復其 archived 狀態後送新分派。個股頁日 K／成交量／MA20、MA60 及現有研究資訊整合。 |
| D015 文件 | 01a093f5-5a40-7643-8e4c-c974b850f6b8 | gpt-5.6-sol／high | 產品驗收契約、API/畫面交叉核對、路線狀態；未獨立驗收不標完成。 |
| I048–I050 索引 | 01a093f5-fd23-7780-8fc2-0a3134d7565e | gpt-5.6-luna／medium | 外部變更基線、七區健康；主 freeze 後才分段刷新涉及分區。 |

產品驗收：在 `/stocks/:exchange/:symbol` 使用既有 API 真實 OHLCV，提供日 K、成交量（股）、足夠資料才顯示的 MA20/MA60、日期/OHLCV 提示、縮放／區間與資料來源時間。整理已有族群、籌碼、新聞／事件及策略行動資訊；不新增無來源的評分、AI 判斷或交易價位。價格 basis 未證明時必須明說；空值／無效 OHLC／重複日期不能補造有效 K 線。現有 API 最多 120 筆並非完整歷史。主需獨立檢查資料邊界、前端回歸／build及隔離真實資料的瀏覽器操作，不能只依 screenshot 或 mock 宣稱產品接線完成。

互斥寫入：C013 可改 `frontend/src/App.tsx`、`styles.css`、`types.ts`、`api.ts`，可新增 `StockPriceChart.tsx`、`stockChart.ts`、`stockChart.test.ts`、`StockResearchPanel.tsx`、`stockResearch.ts`、`stockResearch.test.ts`。D015 只改 `docs/PRODUCT_SPEC.md`、`ROADMAP.md`、`ROADMAP_EXECUTION.md`、`OPERATIONS.md`，可新增 `STOCK_RESEARCH_PAGE.md`。主獨占本紀錄、HANDOFF及根 AGENTS；I048 不改來源。backend／worker／migrations／既有 stores／package與lockfiles／正式及.local資料庫與現存服務均保護；需擴範圍先經主review。原 R13 baseline 保留，新授權另立外部 baseline；C013 收到 baseline ready 才寫入。

本輪按「使用者可操作的結果 → 必要程式 → 獨立驗收 → 精簡文件 → 索引」收斂；保留三角色但不為增加輪次持續拆出未接線模組。ROADMAP 整體、AI、PIT、策略有效性與新 ATR 預設接線仍未完成。

I048 已保存新外部基線 `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-research-I048-I050-20260912-0152`：`frontend-src-source` 為原始 source 複本，`baseline-sha256-source.json` 17 筆，另有含 backend/data 保護目標的 `baseline-sha256.json` 195 筆。主已核 App.tsx／styles.css／types.ts／api.ts 四檔與原始複本 SHA256 一致，已通知 C013「baseline ready，開始寫入」。I048 七區 ready/graph 可用；tests 既有 SQL partial 範圍保留，coverage best_effort，尚未刷新，不作程式驗收。文件角色可能合法修改其白名單，不能混入 protected claims。

`roadmap` heartbeat 在方向討論期間曾 PAUSED；使用者同意繼續後已更新 prompt 為新 R13 scope與三 task IDs，恢復 ACTIVE／每30分鐘。定時接續必須尊重後來使用者的討論／暫停要求，不重建角色、不恢復已延後的 comparison。這次啟動記錄尚非 R13 交付或驗收完成。

D015 五文件首稿已由主實讀契約／R13變更並核對更正後 SHA256 5/5，接受作本輪驗收契約，不是產品驗收。唯一價格標示為「原始 API 價格；還原方式未提供」；不能把 unknown 寫成已確認未還原。歷史 MA 不使用單筆最新 feature；已知缺口只取 payload 可證明資訊，不猜週末／假日為缺 bar。C013 已收到契約與開始寫入指令，尚待程式交付。主本次 App coverage 呼叫回報 Transport closed；同引擎 CLI coverage 成功，五檔 metadata_changed／新文件 not_tracked，索引限制明列，未停止程序或修改全域設定。

### C013 最終 review（接受有限產品範圍）

主已接受目前實際交付的個股研究頁：日 K／成交量／MA20、MA60、30／60／120／全部區間、滑鼠與滑桿縮放同步、重設、OHLCV 提示與表格，以及現有族群／籌碼／新聞／事件／策略條件整合。只改 App.tsx、styles.css 並新增六個白名單檔；api.ts／types.ts 未變。先前缺口跨算均線、縮放不同步、unknown 時間被 raw 值覆蓋、來源與必要條件誤導、空陣列更新迴圈及手機圖表太窄等問題均經主退回修正、複验後才接受。

- 最終主驗證：六個前端 self-test 檔、獨立 17 項邊界檢查、TypeScript typecheck、Vite production build 全 exit 0；10 檔 final hash 在驗證前後一致。建置 666 modules／6.88 秒，JS 1369.33 kB、gzip 447.82 kB，大 chunk 警告保留。
- 隔離真資料瀏覽器：2330 真 65 筆、近30日／滑鼠及滑桿／重設；8105 真59根與6個已知缺口；009829 真13根且不畫不足期均線；4804 真0根仍顯示籌碼族群；1788 真2新聞2事件及 /news/2 連結。末日 2330 tooltip O2465/H2505/L2460/C2470/V28931697 與原 API 一致。MA 色圖例、成交量軸縮寫及390像素手機布局通過，新頁面控制與空態操作 error logs 為空；初版舊 tab 的更新深度錯誤留作退修歷史。
- 主證據保存在專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r13-coordinator-review/`：FINAL_REVIEW.md、final-source-hashes.json、frontend-results.json、final-js-independent.json、scope-review.json、real-data-backup.json。原正式庫唯讀備份用於獨立 API 8133／前端5183；不執行 migration 或重啟既有服務。86/86 protected 與105/105 runtime cache 基線未變。
- C013 App 多次顯示 completed／idle，但 assistant/tool 輸出為 null，正式回覆取回受限；主已下達停止寫入，按實際檔案交付、独立驗證及穩定 hash 判定接受，不捏造作者的自測或 freeze 回覆。這個 App 可見性問題不以重做程式或重建角色處理。
- 本段只接受本輪頁面能力。完整歷史、還原 basis、AI／PIT、新 ATR 預設接線、B2／B7、正式庫遷移與策略有效性仍未完成。D015 已收到五文件最小 final 更新指令；I049 已收到 frontend-full/src 正式刷新，I050 等文件與本紀錄 freeze 後進行。下一輪由主 review 與索引複核後決定，不由角色自行啟動。

I049 程式索引已由主獨立 CLI exact coverage 複核並接受：frontend-full 373 nodes／1244 edges，generation/indexed/recorded `2026-09-12T05:55:34Z`；frontend-src 319／1178，時間 `2026-09-12T05:55:47Z`。兩者 full+persistence、skipped=0／parse_partial=0，八個改動路徑均 no_recorded_issue，10 檔 source hash 前後一致。coverage 仍 best_effort／metadata_changed，不以索引成功替代功能驗收。App MCP 兩次 Transport closed 與 CLI 更新成功分開記錄；未為修復 App 終止程序或修改全域設定。

D015 五文件 final 已正式交付並 freeze；主實讀狀態、契約與證據，退回兩處時態修正後核 SHA256 5/5 相符，接受文件。完整值見主外部證據的 final-doc-hashes.json。只標有限個股頁已 review，保留 B2/B7/PIT/AI/正式庫遷移等缺口。

I050 以本次文件凍結為輸入，僅刷新既有 docs 分區七路徑：上述五份＋TASK_COORDINATION＋COORDINATOR_HANDOFF。主收到其結果後獨立複核 coverage、時間及七檔 hash，才判定本輪收尾；最終 receipt 保存在主外部證據的 I050-docs-coverage.json 與本轮索引 task 回覆，避免為把索引時間寫回已索引文件而循環重建。既有正式與 .local 資料庫、服務及其他分區維持本輪保護邊界。下一輪需由主依最新 ROADMAP 與使用者方向另立新三角色，不能自行恢復已延後的 comparison。

## 統籌交接與 Round 13（歷史斷點，範圍已由上節取代）

使用者要求「整理一下所有做過的部分，然後幫我開啟一個新對話」。已整理 [全部完成盤點與交接](COORDINATOR_HANDOFF_2026-09-12.md)，由新統籌 `01a0935c-c1da-7411-ace2-eb84f8fb5b62` 接替 `01a09112-1254-7452-8eaf-25ef706aa5e1`。舊 task 保留歷史，不封存、不刪除。新主接手未完成當輪，持續免費公開資料與本地測試、獨立 review→文件→索引流程。

| 角色／批次 | Task ID | 模型／Reasoning | 交接狀態 |
| --- | --- | --- | --- |
| 程式 C013 | 01a09353-7608-7b90-a0d6-cd8c02ca6743 | gpt-5.6-luna／xhigh | 已建立；使用者中斷前只查索引，未修改程式；新主在同 task follow-up。 |
| 文件 D015 | 尚未建立 | gpt-5.6-sol／high | 新主補建，不重用 D014。 |
| 索引 I048–I050 | 尚未建立 | gpt-5.6-luna／medium | 新主補建；先 baseline 與交接文件分段索引，再依 freeze 更新程式、最終文件。 |

本輪範圍為 legacy/new signal 離線 exact 唯讀比較與 artifact store 真正 readonly reader；詳細白名單、驗收及外部 baseline 見交接文件 §6。Round13 未實作、未驗收，ROADMAP 整體未完成。本次主統籌只修改 AGENTS、本紀錄及新增交接文件；新交接文件尚待當輪索引角色刷新，不宣稱已涵蓋於 I047。

## Round 12（2026-09-12，有限review與索引完成）

I047 最終已由主 CLI coverage 與文件 hash 複核：docs 313 nodes／312 edges、full+persistence、skipped=0、partial=0；六路徑 no_recorded_issue／metadata_changed／best_effort，generation/indexed/recorded 均 `2026-09-12T01:52:40Z`。當時 TASK_COORDINATION SHA256 `9D228D8D5C8ADFC850418D2C981436CD06911B4CAC19ACC6FDC1B01ED26DFF54`（本次交接追加後自然不同）。本輪角色均已 freeze；後面的「待 I047」敘述保留為歷史過程，不代表目前仍待辦。

Round11 I044 docs收尾已由統籌CLI及TASK_COORDINATION hash核對：292 nodes／291 edges、full+persistence、skipped=0、partial=0；六路徑no_recorded_issue／metadata_changed，generation/indexed仍2026-09-11T23:41:42Z，recorded=2026-09-12T00:50:26Z。當時協作紀錄SHA256 `871E377C8003A0B6E24BFD6BA5CFEAEE5AED38311473A27FE4B7249C201223B4`。程式、文件review及索引收斂後才建立本輪三個新task。

| 角色／批次 | 新 Task ID | 模型 | Reasoning | 寫入範圍 |
| --- | --- | --- | --- | --- |
| 程式 C012 | 01a09319-bfdf-7ff1-bcfd-6be833003bb1 | gpt-5.6-luna | xhigh | 僅新app/signal_artifact.py、signal_artifact_store.py、兩對應tests及可选fixtures/signals JSON |
| 文件 D014 | 01a09319-c389-7280-8fc9-0eefe1a07dba | gpt-5.6-sol | high | R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS，可新SIGNAL_ARTIFACTS |
| 索引 I045–I047 | 01a09319-c7b6-75d0-896f-67c5467e5825 | gpt-5.6-luna | medium | 七區唯讀baseline；主review/freeze後更新app/tests，再docs，不改來源 |

範圍：依R0 §5.4推進R0-B2/B2-persist獨立signal artifact本地foundation。純契約與明確opt-in、独立owner/schema的immutable SQLite store，identity/versionbinding、revision/supersedes、firstgenerated保留、retry/attempt/runrelation分離、collision/故障/concurrency整筆rollback、exactread與lineage。新rule-only confidence固定null/non-probability，source/implementation證據caller_provided_only；本段earliest_execution_at只允許null+reason，不冒充PIT/session gate。保護legacy Signal/0.75、worker/ATR/API/UI、models/migrations、正式/.local DB及既有stores。B2整體仍須後續legacy/new comparison、API/list/detail/action/UI及B7，foundation不取代原驗收。

輪前外部基線 `C:/Users/YiCheng/AppData/Local/Temp/stock-r12-baseline-bfc3729300f64f6e80d99dc900952da4/baseline.json`，45檔＝41protected＋4editable docs；四docs已備份。新檔不改既有來源、主獨占本紀錄。每角色親自執行，禁止create/fork/轉派；只有本輪index角色收到主指令後能刷新，程式與文件task不可自行index_repository。每段持續主review→修正→docs→index；未完成當輪不重建角色。

C012已回報純契約/獨立owner store設計，主接受方向並明確：本段earliest_execution_at一律null+reason；artifactkey需由完整canonicalidentity含revision導出；lineage固定subject/strategy/semantics，revision變更規則不得掩蓋sameidentity collision；先線性append，同parent concurrency最多一child。固定versionbinding key不含instrument/date/asof/snapshot，避免以不同subject迴避settings/implementation版本衝突；不同instrument/time仍可共用同binding。firstgenerated不可被retry候選替换，attempt/runrelation單獨保存。D014正在契約crossreview；I045需用CLI exact tools `check_index_coverage`、`search_graph`、`index_status`（CLI `project_name`），不能用錯tool名`coverage`/`graph`推論能力不存在。

I045修正版正式CLI七區index_status ready、graph可查、coverage best_effort；維持各metadata_changed、docs舊generation及tests既有SQLpartial，不以artifact commit=HEAD或timestamp推論新鮮。index角色核45hash/size；主另核41protected hash/size/mtime全一致，見stock-r12-coordinator-review/initial-protected-review.json；I045接受後freeze等I046，未刷新。

D014短契約已接受並分派先寫SIGNAL_ARTIFACTS。主再固定subject group與research chain區別：不同snapshot/asof/basis/dependency可以有獨立root，完整research-core identity（排除revision）決定chain；child不得改核心輸入、rule outcome/quality/config/impl，必須新core/root，config/impl另需新version。不可變rule status與lifecycle state分開，本段最小線性active→withdrawn、reason+awaretime且終態，不擴成交易/成交lifecycle。D014待新source唯讀crossreview，所有修正經主退派。

契約初稿review後再澄清上一段：research-core **input identity** 與research **result payload digest** 必須分離。core/chain/root key不得包含rule outcome/status/evidence/levels/quality結果；相同輸入identity算出不同結果應collision，不是新root。新root只因輸入identity真變化；child的inputidentity及researchpayloadseal皆須同parent。D014原稿將結果加入core hash會繞collision，主已退修文件與C012設計。SIGNAL_ARTIFACTS仍提案，未通過程式review。

C012 signal_artifact.py初稿已出現，store尚待；主集中退修pure contract的canonical confidence/semantics、嚴格版本與alias衝突拒絕、manifest型別/unknownreason、derived artifactkey不得加入researchpayload等問題。D014負責具體type/negativefixture與dataclass/mapping一致性crossreview。所有新source未凍結，未跑本輪finalfull，勿由設計/contract檔存在宣告B2完成。

D014已實跑反例證實初稿接受不合法semantics、None/scalar manifests、boguscontract、aliases矛盾、非法lifecycle與suppliedkey污染payload。主已核既有domain.py常數，confidence semantics固定signal-confidence/v2、kind=not_calibrated、boolean false/false及「未校準；非預測勝率」；主早先kind=rule_only建議已更正，rule_only只用於output semantics。本slice output semantics亦限定該v2 canonical shape，缺省可canonical填入，caller提供不符或boolean0拒絕。basis/dependency/implementation最低objectshape及caller-provided/not-officially-verified、unknownreason要求已由主接受并派C012落實。

時間契約再固定：root首次create generated>=decision；withdraw lifecycle>=decision且>=root持久firstgenerated，child首次generated>=lifecycle。retry只要求候選generated是合法aware instant，不以新候選改寫或重新限制舊artifact/withdraw時間；首次creation與重放順序在store分開處理。D014更新契約，C012測同root/child不同retry候選generated皆保留原值，非法首次create整筆rollback。

Store 初稿 review 再要求：實際 resolved workspace 路徑在 SQLite connect／建立檔案前拒絕，existing DB 先唯讀驗 owner/schema；new 與 replay 共用提交前 gate，包含 attempt/run 關聯與 child ancestor 完整性。合法同 artifact＋同 run 的不同 attempt 應另記，不可因 run/artifact 唯一鍵誤判；同 attempt 換綁則拒絕。subject list 必須明確 filter，不提供無參數全庫預設。D014 反例證實 Python `0 == False` 可繞 dict equality，故 semantics 布林需嚴格型別；保留的 aliases 必須 canonical 等值，lineage_subject 本 slice 固定 signal。主已準備專案外 `stock-r12-coordinator-review/independent.py`，等凍結後跑獨立矩陣，尚未接受 C012。

主先行獨立 full backend 284 passed／4625 warnings／16.95 秒，四來源前後 hash/size/mtime 與 41 protected 全一致；D014 25 targeted、strict 11 negative、WAL/journal拒絕指紋、detached snapshot及parent/runrelation破損檢查通過。但該版尚未接受：no-replace trigger補PK時移除了rowid保護，主以改所有declared keys但保留rowid的SQL實測仍能替換attempt。已要求rowid與全部PK/UNIQUE一起阻擋、runrelation加UNIQUE(attempt_id)，reader驗同attempt最多一run。主外部矩陣現45case，另含hardlink及未知schema拒絕；等C012最後修正freeze後重新full/independent/protected，D014再final交叉驗證。先前42/42不冒充涵蓋後增案例，I046仍未派刷新。

### C012 final review（有限 foundation 已接受）

最終只新增四檔：`backend/app/signal_artifact.py`、`signal_artifact_store.py`及兩對應tests；沒有新fixture。直接rowid及所有實際PK/UNIQUE guards、lineage/revision/supersedes unique indexes、attempt_id UNIQUE、strict relation/ancestor reader已實作；沒有shadow rowid JSON機制。專案tests保存外部connection預設foreign_keys=0／recursive_triggers=0的root＋withdrawn child、無rowid／顯式rowid／alternateunique REPLACE回歸與rows不變斷言。

- 主final：完整backend **285 passed／4625 warnings／16.95秒／exit0**；外部獨立 **45／45**；四source在full與獨立驗證前後hash/size/mtime一致。作者26 targeted／1.56秒、285 full／17.29秒；D014 latest26 targeted／1.57秒及strict11negative、computed digest、detached snapshot、WAL/journal拒絕、parent/runrelation破損crossreview通過。
- 主證據：`C:/Users/YiCheng/AppData/Local/Temp/stock-r12-coordinator-review/`的final-review.json、final-source-hashes.json、independent-review.json、protected-review.json及local-db-readonly.json。D014獨立證據在`stock-r12-d014-review/crossreview.py`及crossreview.json；WAL/DELETE journal的DB/WAL/journal hash/size/mtime已驗，SHM因Windows lock只驗size/mtime，不冒稱其hash。
- 四final SHA256依序：`F8B6B56853E08FF263498E96E12A402AEBB1500F5CC5847C9DDFAECEEF14A2D9`、`DD3CF18C64A5B848F43110B32FA51CDA7517304E0D785DEA6B1876D2F635E620`、`A821EDD0F0FF50204F6F38DA889A0DEF2F18C683A03905BA4AE1CDC4ADBC77E7`、`C8EF20AB672AC7CF4896A1F902E627FB38C950B43D958C051FD57CD70E2BE319`。
- 本段只接受signal-artifact/v1 rule-only caller-provided本地foundation；earliest_execution_at固定null，legacy/new comparison、API/UI、worker、官方truth、PIT及B7仍未完成。文件與索引成功亦不擴大此邊界。

**保護檔外部變更例外：40／41與原輪前基線一致，不能寫41全不變。** 唯一差異是`.local/data/stock.db`。另一task「執行前後端專案」`01a0913c-797b-7863-a5a6-5f47f469bc9b`於turn `01a09339-967d-7363-9730-34e22b68193a`依其使用者「幫我執行前後端」要求，09:27以原.local環境啟動Uvicorn；該task回報startup lifespan的init_db執行0005→0006 migration log。主另外用mode=ro／query_only核.local當前head=0006與兩JSON SQL `[]` defaults，讀前後shared-read SHA／size／mtime穩定。原基線425984 bytes／SHA `306D9D8116E8E906826393290F74BA8B269CE7D9E9F91B842656581725DE39A9`保留；新值438272 bytes／mtime `2026-09-12T01:27:28.7179604Z`／SHA `87453D7B29954B6D506F8020B8987F321AA6749CE9BC24FBEF695DD3874B8D02`。這是另一使用者授權啟動造成的並行變更，不是C012寫入／migration驗收，也不證明.local所有歷史rows未變。正式`data/stock.db`仍與原SHA `74A34389DBFA65429D27EA41BC9DECA2A132808F10093E2FFDE98665D96232D6`、296054784 bytes及原mtime一致；主未停止、重啟或改寫服務。

I046已完成，主CLI複核四source exact coverage及新增SQL回歸符號：app 786 nodes／3714 edges、tests 449／1822，full+persistence、skipped=0；app無partial，tests只保留既有SQL ranges 4、50–51、70、105。兩區coverage generation/indexed/recorded均`2026-09-12T01:41:10Z`，四檔no_recorded_issue但仍metadata_changed／best_effort；artifact檔app indexed_at另顯示01:41:11Z，不混成coverage generation。四source hash/size/mtime仍一致。本輪索引全走同引擎CLI，未調codebase App MCP，所以不捏造本輪有新Transport closed事件。

D014五文件已final/freeze並經主review；主SHA256核對5/5一致、58個relative link targets存在，D014另核Markdown table pipe一致。完整hash/size保存在同證據目錄final-doc-hashes.json。文件精準區分contract缺省、nullable as_of_at、含revision的identity_hash與research-core lineage、無獨立levels欄、actual SignalArtifactCollisionError；保留B2後續comparison/API/UI/worker/PIT/B7及.local外部例外。現在I047只刷新既有docs分區的五docs＋本紀錄六路徑，source與其他docs freeze；主核對後才開始Round13。

## Round 11（2026-09-12，有限review與索引完成）

Round10 I041-final 已由統籌 CLI 與 hash 核對：五份 docs coverage no_recorded_issue／metadata_changed，288 nodes／287 edges，recorded=2026-09-12T00:11:50Z；generation仍舊值，未冒稱完全新鮮。TASK_COORDINATION當時SHA256 `6BB48064224E4329FD385588C7C15B9AA2460460661C0BD75037CE88AB409439`。前輪程式／文件review與索引均收斂後，建立以下三個新task。

| 角色／批次 | 新 Task ID | 模型 | Reasoning | 寫入範圍 |
| --- | --- | --- | --- | --- |
| 程式 C011 | 01a092f6-0deb-71e3-94ef-bdbe3af0c7a0 | gpt-5.6-luna | xhigh | NewsItem兩JSON defaults、app/migrations.py、新news_json_defaults.py、新0006_news_json_defaults.py、test_schema/test_migration_recovery及新test_news_json_defaults與old_fresh_0005 fixtures |
| 文件 D013 | 01a092f6-119d-7641-9ed7-0301c290d0f7 | gpt-5.6-sol | high | R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS、DATA_SOURCES |
| 索引 I042–I044 | 01a092f6-1596-7980-8ab8-95b75c6e3bc5 | gpt-5.6-luna | medium | 七區唯讀baseline；統籌freeze後更新app/alembic/tests及docs，不改來源 |

本輪修正已獨立重現的JSON server defaults gap：fresh及既有0005資料庫需透過明確新revision與fallback收斂到同一`[]` SQL default。保護既有0001–0005歷史與R10 synthetic SQL/JSON；舊fixture測試可明確pin005，新驗收另到006。驗收涵蓋真Alembic及強制fallback、fresh／oldfresh005／0004 upgrade、SQL省略欄位、既有非空JSON與全common rows保留、PK/FK/unique/indexes、custom schema保留或事前拒絕、故障rollback/retry、冪等及FK設定恢復。正式／.local資料库及服務不動，所有執行只在外部Temp。

輪前基線 `C:/Users/YiCheng/AppData/Local/Temp/stock-r11-baseline-538df47e03bd407b9a4eacdc58b2091e/baseline.json`，42檔＝33protected＋9editable，editable原文已備份。主統籌獨占本紀錄、派工與review；角色禁止create/fork/轉派，文件完成不自行指揮索引。沿用免費公開資料與本地測試，R0-A2／ROADMAP完成狀態須等實際驗收。

I042七既有分區ready，33protected current hash／size／mtime全部核對一致，包含兩DB；tests已知SQL partial與各區metadata_changed仍保留，未刷新索引。D013已提交§8.4嚴格驗收矩陣，未提前改head或完成狀態。

初稿review：統籌指出helper的SAVEPOINT若無driver外層transaction，RELEASE可能在marker寫入前提交；self-FK重建及custom view也需實測。D013獨立重現known005兩列self-FK於FK ON的DROP失敗、helper成功後marker failure仍已提交defaults、custom view導致rename失敗。相關外Temp evidence prefixes為stock-r11-d013-self-fk、stock-r11-d013-cross、stock-r11-d013-view；證據由D013回報，尚非final驗收。

因此統籌擴C011白名單至`backend/alembic/env.py`，只限必要SQLite migration transaction／FK邊界；原SHA256 `6CFA5C981E15BC33734F9AF5A4D040A3BC1621DC80E28F3C66374E2B980EF979`及原文已備份，scope-extension.json記錄。baseline原檔保留，後續有效32protected＋10editable，42總數不變。0001–0005仍保護。要求真正外層driver transaction包DDL與版本marker、FK0/1原值恢復、外部已active transaction不得私自commit、fresh失敗無半套DDL、既有失敗完整rollback再retry。主獨立驗收script已準備，使用R10真正缺default的005隔離DB副本，不以新model冒充old。

統籌preliminary independent.py已73項通過：Alembic/fallback的fresh、真old005及帶非空JSON/self-FK/extra欄/expression index/trigger副本成功；inbound FK/custom view的副本事前拒絕且完整schema/rows不變。atomic.py另做24組engine/externalConnection/fallback×fresh/old005×FK0/1×marker SQL前後故障，初稿4組externalConnection殘留autobegin已退修，修後24/24通過rollback/retry與原FK值；證據位於`C:/Users/YiCheng/AppData/Local/Temp/stock-r11-coordinator-review/`。這些是變動中程式的先行檢查，不取代final凍結hash/fullbackend。

D013又重現AUTOINCREMENT高水位遺失；writer已改事前拒絕此unsupported schema，D013核對sqlite_sequence/DDL不變。最後兩項待writer修正：extra欄literal `REFERENCES news_items(id)`被全SQL regex誤改，及其他表trigger引用news_items未事前偵測。需精準保留或事前明確拒絕並加回歸；不得靜默改schema。接手時先收C011 final、D013 crossreview，再由主重跑適用獨立驗證/full，通過後I043程式索引、D013五docs final、主review、I044docs索引；本輪未結束，不重複建立角色。

### C011 final review（已接受有限範圍）

上述初稿缺口已修：literal保持原文、外部trigger/不支援custom schema在重建前拒絕、SQLite入口真正外層transaction與FK0/1原值恢復、active caller事前拒絕、返回無autobegin、repair release前fresh inspector校驗兩defaults。回歸資產納入真marker SQL故障、fresh無半套DDL、externalconnection重用、AUTOINCREMENT high-water及ownedtrigger/literal保留；0001–0005與R10SQL/JSON不變。

- 統籌 final：`python -m pytest backend -q --disable-warnings`，259 passed／4625 warnings／14.12秒／exit0。真Alembic1.19.2、bundled Python3.12.14及SQLAlchemy2.0.52，所有STOCK路徑在專案外Temp。
- 凍結八檔在full與獨立重跑前後hash/size/mtime一致；final-source-hashes.json列完整值。independent.py 73/73與atomic.py 24/24皆重跑通過，32protected hash/size/mtime不變。final-review.json記有限驗收與限制。
- 作者 final targeted `pytest -q backend/tests/test_news_json_defaults.py backend/tests/test_schema.py backend/tests/test_migration_recovery.py`：26 passed／26 warnings／2.39秒／exit0；作者 full `pytest -q backend/tests`：259 passed／4625 warnings／13.44秒／exit0。
- 新程式head為0006_news_json_defaults，fallback新增第六marker；只驗隔離庫，不改正式庫五fallback/noAlembic的歷史實際狀態。R0-A2明列的Newsdefaults parity/atomic regression缺口已結清，不等於全歷史schema、正式restore/deploy或整體R0完成。R10測試明確pin005/currentmetadata；C011固定DDL是old005-like slice，統籌另外使用R10真oldfresh005全Temp副本验证。非SQLite未實測。
- C011在主review後續指令前誤自行fast刷新app/alembic/tests三區，主已停止；其fast結果不作本輪正式索引驗收。I043已正式下派本輪index角色，核八hash後以既有name/full+persistence刷新三區；D013更新五docs，之後主review才I044。

I043已由本輪索引task完成，統籌CLI核對exact coverage：app 686 nodes／3149 edges，generation/indexed/recorded=2026-09-12T00:39:08Z；alembic 82／220，00:41:39Z；tests 423／1682，00:39:15Z。三區均full+persistence，skipped=0；只有歷史SQLfixture保留partial 4、50–51、70、105，其他八程式與歷史JSON均no_recorded_issue。全部仍metadata_changed／best_effort，不宣稱graph完整。8code及32protected hash/size/mtime一致，歷史SQL/JSONhash不變。App MCP三次Transport closed，索引task依AGENTS改同引擎CLI成功，未終止程序或改全域設定；CLI成功與App連線故障分開記錄。D013五docs final後再I044。

D013五文件已final/freeze並經統籌review、SHA256 5/5核對一致，詳同證據目錄final-doc-hashes.json。61個relative links存在、Markdown table pipe issues=0；source8hash再核對一致。文件精準區分0004成功升級與fresh/old005的24組fault矩陣，成功fallback重跑的operational applied_at可更新、不包含在research idempotence比較，失敗rollback則含全部markers；R10 current-metadata pin005與C011 fixed小slice不是完整歷史snapshot，統籌另用真R10 full005 Temp copy補證。I044正式派本輪索引task更新五docs＋本紀錄六路徑，之後才建立Round12三個新task。

## Round 10（2026-09-12，有限 review 與索引完成）

Round09 I038 已完成並由統籌 CLI 核對：docs full 284 nodes／283 edges，generation/indexed_at=2026-09-11T23:41:42Z、recorded_at=23:44:30Z；六個 final docs hash 全一致、coverage no_recorded_issue／metadata_changed，新 SOURCE_REGISTRY 已追蹤。前輪程式、文件及索引全部收斂後才建立本輪三個新 task。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a092dd-b57c-7662-a1c9-c995c412e1f9 | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a092dd-b927-7722-a4ea-4989b0409184 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a092dd-bc9a-76f3-83f5-25a4c9d3cae2 | gpt-5.6-luna | medium |

| 批次 | 責任／寫入範圍 | 狀態 |
| --- | --- | --- |
| C010 | 新 tests/test_migration_recovery.py、tests/fixtures/migrations/ 合成 SQL／JSON fixture | 有限 review 通過並 freeze；schema parity=false 的已知 gap 留待下輪 |
| D012 | R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS | final/freeze；統籌四份 hash 核對一致並接受有限狀態 |
| I039–I041 | 七區 baseline、tests 與 docs 段落刷新 | I040 通過；I041 四文件已刷新，協作紀錄補入後再收尾 |

本輪補齊原 R0-A2／B6 尚待的可重跑 migration 資產與實際 restore 演練。使用獨立於當前 Base.metadata 的明示 synthetic pre-head schema，升級前確認真正缺少目標欄位；真 Alembic upgrade、fresh schema／constraint parity、既有 row 預期保留／轉換及內容 fingerprint、FK／integrity、冪等。SQLite backup API 建立一致備份，再對隔離故障副本實際還原到新的 Temp 路徑，驗完整性及來源／備份不變。Minimal fixture 僅代表明列範圍，不能冒稱全歷史正式 schema 或正式還原。0001 用 current Base.metadata 的已知限制仍須明示，fresh 成功不代替 pre-head upgrade。

不改既有 test_schema、production app／worker／alembic／frontend、正式／.local DB；不使用正式資料作 fixture。正式庫無 alembic_version、五個 fallback marker 的歷史查驗仍保留；此輪不升級正式庫。輪前外部備份 `C:/Users/YiCheng/AppData/Local/Temp/stock-r10-baseline-bbfe9e4afac34747bf10b06cca1a9df5/baseline.json` 共 38 筆＝34 protected＋4 editable docs；主統籌維護本紀錄。沿用共用 local 目錄、每輪三個新 task 與免費公開資料／本地測試規則。

I039 App MCP 唯讀 baseline 已回報七區 ready、parse_partial／skipped=0；38 筆 hash／size／mtime 一致（mtime 以 UTC ticks 比對）。新 test_migration_recovery.py／fixtures/migrations 尚 missing，既有 exact source paths metadata_changed；分區查詢必須用各 subproject-root 相對路徑。未刷新索引，後續只按統籌 freeze 指令更新。

C010 起步時誤轉派建立重複 task `01a092de-91b9-7ae3-8a82-e995ed3d43be`；統籌已要求停止，並直接 wait 確認該 task idle、未改來源／未執行 C010 寫入，僅做唯讀 coverage。保留作歷史，不刪除／封存；它不是本輪 writer 或額外角色。唯一程式 writer 仍為原 C010 `01a092dd-b57c-7662-a1c9-c995c412e1f9`，已要求恢復親自實作且不得再 create／fork／轉派。D012 短契約已接受，等待 C010 fixture／測試交付。

### C010 初稿 review 與已確認缺口

統籌在專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r10-coordinator-review/default-drift.json` 獨立重現 semantic schema drift：current Base.metadata 的 fresh→0005，news_items.symbols_json/theme_ids_json 無 server default，省略兩欄的 raw SQL INSERT 會 NOT NULL failure；實際 0004 建立 News table 再升0005則兩欄 server default='[]'、相同INSERT成功。這不是額外 index 名稱的差異，不得 normalize 後宣稱 full parity。R0-A2 全部完成仍待後續修正；本輪保持 production 原檔不動，驗收可先接受 migration／restore regression assets 的有限範圍。

現有 synthetic SQL（SHA256 `BC5198C14BA2547D30529D3D335E79DE363022159B48D6C9442CFD643E3C42C1`）已由統籌用獨立 sqlite_master SQL／全表全列比較完成 22 項升級、資料保留、冪等、同筆數內容變動、刪列、SQLite backup→新路徑 restore、來源／備份 bytes 不變及真正 FK／PK／unique 拒絕檢查；見同目錄 recovery-review.json。尚待作者 final 測試檔修正（fingerprint 納入 PK、same-count mutation 與 row loss 分開）及統籌 full suite，不能把這份先行驗證當整輪已完成。

### C010 統籌 final review（有限範圍）

PK 描述／必要 constraint、fresh PK 對照、保持筆數的內容破壞、獨立 row loss、去除 constraint 的錯誤副本拒絕已補齊。Fixed SQL 真正缺五個 0005 target columns；真 Alembic 從0004到0005、新欄 defaults、五個既有資料表所有 common values 保留、head 冪等、完整六表 schema／rows restore 都有測試與獨立證據。Known-default-drift 測試明確要求兩個已知差異並實跑 omission INSERT，沒有宣稱 parity 通過。

- 統籌 final full：Python3.12.14＋真 Alembic1.19.2，`python -m pytest backend -q --disable-warnings`，241 passed／4613 warnings／31.69 秒／exit0。獨立22／22與 default-drift.json重現通過，SQL hash 與先行獨立驗證相同。34 protected hash／size／mtime 全不變。最終報告同目錄 final-review.json。
- Final SHA256：test_migration_recovery.py `CFD344807B0E9644E4C14E904342FD1CE36BC9781BD3254236D4F33C92C2175C`；SQL `BC5198C14BA2547D30529D3D335E79DE363022159B48D6C9442CFD643E3C42C1`；JSON `09DD1075D0EA1DB1B474639D6ECECDA5E710057EE439ADABE83C197EE64BC019`，完整path／size／mtime見 final-source-hashes.json。
- 只接受 synthetic migration regression／隔離 SQLite restore mechanics；schema parity=false，R0-A2 整體仍未完成。下輪修正兩個 JSON server default 的 fresh／upgrade 差異，維持明確新版本與隔離驗證，不回寫正式庫。本輪不改 production migrations／models／frontend，也不把 R03 當時未跑 restore 改寫成已做正式 restore。

I040 App MCP 已完成既有 backend-tests full+persistence：405 nodes／1605 edges，generation/indexed/recorded=2026-09-12T00:04:13Z；skipped=0、not_indexed_files=0，SQL fixture parse_partial 範圍4、50–51、70、105，測試與 JSON 無 recorded issue。三檔及34 protected hash／size／mtime一致，統籌 CLI 再核對。SQL部分解析不代表無效，SQLite實際執行與來源 hash 為補充證據；coverage仍 metadata_changed／best_effort。索引 task 初次建立的同root重複索引已刪除並改用既有 project name，未改來源。

D012 四文件已 freeze，統籌直接讀取與 hash 4/4 一致；完整 hash／size／mtime 見同證據目錄 final-doc-hashes.json。D012 最終獨立 targeted 為4 passed／10 warnings／1.44秒／exit0；四文件連結與表格檢查通過。R0-A2未完成、兩個JSON defaults差異、僅synthetic restore及歷史正式庫未upgrade等限制均保留。D012 在統籌最終收尾前先行請索引 task 執行 I041；這不取代統籌 review，後續所有角色派工仍由主統籌集中進行。

I041 四份 docs 已 full+persistence 更新為288 nodes／287 edges，ready、skipped=0、parse_partial=0、not_indexed_files=0。Coverage no_recorded_issue／metadata_changed；generation/indexed仍2026-09-11T23:41:42Z，recorded=2026-09-12T00:08:51Z，保留舊generation限制。統籌CLI確認並補入本紀錄，請同輪索引task對五份文件做最終收尾，之後才開下一輪三個新task。

## Round 09（2026-09-12，review 與索引完成）

R08 I035 已完成並由統籌 CLI 獨立確認：docs full 265 nodes／264 edges，六檔 no_recorded_issue／metadata_changed，generation/indexed_at=2026-09-11T17:02:31Z、recorded_at=23:13:04Z。五份 final docs hash 全一致；原程式與文件 review／索引收斂後才開本輪。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a092c1-c2d5-78f0-80cc-754819ffe22f | gpt-5.6-luna | xhigh |
| 文件與來源核對 | 01a092c1-c5f0-7661-961b-721609384242 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a092c1-c998-7253-a3c2-301e3b467bcc | gpt-5.6-luna | medium |

| 批次 | 寫入範圍／責任 | 狀態 |
| --- | --- | --- |
| C009 | 新 worker/source_registry.py、source_registry.json、tests/test_source_registry.py；純來源登錄、用途判定、readonly inspect/validate | 已通過統籌有限 review，三檔 freeze；I037 程式分區索引進行中 |
| D011 | 新 docs/SOURCE_REGISTRY.md；DATA_SOURCES、ROADMAP、ROADMAP_EXECUTION、OPERATIONS | 五檔 final review 通過並 freeze；I038 文件索引收尾 |
| I036 | 七分區 baseline/coverage；段落 freeze 後才按統籌通知刷新 | App MCP 唯讀 baseline 已 review；27 筆基線一致，尚未刷新 |

本輪選 R1-A1／G-SOURCE 可獨立前進的首批來源登錄，為 B3-wire／B5b 後續提供來源依據。已有 sources.py 的 EndpointSpec／OFFICIAL_ENDPOINT_CATALOG 只含有限目錄資訊，保留其行為。本輪先核對四個現有端點：TWSE STOCK_DAY_ALL、holidaySchedule、TWT48U_ALL、TPEx tpex_spendi_history。來源 owner、endpoint/method、免費條件、保存／摘要範圍、rate limit、延遲、history、revision、停用／政策版本均須有來源或 unknown reason；HTTP 成功不是歷史可得／完整 coverage 證據。用途分開 local fetch、raw store、摘要、historical PIT，不從單一公開可讀推定所有用途通過。

程式不改既有 sources/cli/pipeline、app/frontend、migration 或 DB；新 module/readonly CLI 不發 HTTP，也不 import 會建立預設資料目錄的 config。文件角色可查官方公開資料並做每端點至多一次的小量 read-only probe，證據保存在外部 Temp，不大量抓取、付費、登入、繞過限制或啟動既有 collector。unknown/未審來源不標已准入；fixture 的正向 policy 不冒充真來源。既有 collect 不由本輪自動加 gate，R1-A1 整體、官方 availability truth／PIT／worker 接線仍按原驗收逐批處理。

輪前基線：`C:/Users/YiCheng/AppData/Local/Temp/stock-r09-baseline-be6a705b23f743009fce4e56c3439724/baseline.json`；四可改既有 docs 原檔備份、23 protected hash／size／mtime（含兩 DB）。TASK_COORDINATION 由統籌維護；當輪三角色可互傳契約／facts，跨輪與額外 task 只由統籌建立。先完成當輪 review／文件／索引，不重複建立 R09。

I036 更正後實際 baseline 為 27 筆（23 protected＋4 editable），hash／size／mtime 核對一致；七區 ready、無 parse_partial／skipped。實際 channel 為該角色 App MCP，未遇 Transport closed；不能與統籌先前 App channel 故障混用。四個新 registry／test／docs 路徑輪初 missing，包含 source_registry.json；JSON 尚無 parser coverage，後續須另列原檔 hash，不冒稱 graph 理解。既有指定來源 metadata_changed。docs generation=17:02:31Z、recorded_at=23:13:04Z，worker generation=15:51:32Z、recorded_at=15:51:33Z，均為 2026-09-11 UTC；其餘沿用 I034／既有分區實測。

統籌已對齊 C009／D011 的四個用途名稱：local_fetch、raw_store、summarize、historical_pit；機器判定 allow／restricted／unsupported，來源 unknown 與明文禁止分開。只以該用途必要證據作 gate，PIT 缺漏不自動否定已明確允許的本地用途。版本 drift 驗證須有外部 expected version＋digest／pinned baseline，不能只重算 manifest 自報 hash 就宣稱同版本歷史未變。

### C009／D011 初稿 review（尚未結案）

統籌獨立查阅四個政府資料集頁（11549、11761、89748、48665），核對免費、OGL 1.0、更新頻率及資料集／Swagger 對照。D011 每端點各一次 GET 的外部 Temp 證據僅為當次 liveness／shape；不證明完整歷史、first availability、修訂版本或權利。文件仍維持候選狀態。

程式初稿已退回修正：version-only 不得標成 content pinned、public decision 必須驗證 manifest、null／錯誤型別不得通過、來源啟用與下架通知政策未知分開、CLI manifest 顯式指定。統籌外部 `stock-r09-coordinator-review/independent.py` 首次 47 項檢查只有 33 項通過：12 個 allow 缺機器可讀 conditions、known free_public=null 與 profile.version=null 仍通過；另讀碼確認 required evidence 只驗 status 會忽略免費／auth／retention 的布林語意。C009 回報的 234 passed／4603 warnings／25.21 秒與 13 focused passed 是上述修正前的中間證據，不接受為 final。待新交付後重新獨立 review、文件對齊、再通知 I036 更新索引。

本輪統籌 App MCP 仍回 Transport closed；同引擎 CLI graph／coverage 可用，新 registry 路徑 not_tracked、相關 docs metadata_changed，故直接來源 review 有依據。這與 I036 自己的 App MCP 成功分開記錄，未改全域設定或終止服務。

### C009 統籌 final review

前述初稿問題已修正。`source-policy/v1` 固定每用途最低 required evidence／conditions；已知值按欄位驗證（free_public=true、auth=false、retention=true、enabled=true），null、錯誤布林型別與空最低集合拒絕。`PolicyDecision.conditions` 明列尚需履行的操作／顯名條件，`allowed=true` 只表示政策 eligibility，不證明 runtime 已履行。四個實際來源 local_fetch／raw_store／summarize 有條件 allow，historical_pit 保持 unsupported。Registry 並未驗證官方歷史真值或自動套用既有 collector。

- 統籌獨立 final：61／61 項（四來源×四用途、12 項 conditions、完整 pin／version-only、同版本重新 seal 後 drift、錯誤 selector、null／非法 URL／錯型別、語意布林與空最低集合）；CLI 明確 manifest＋version＋digest 為 valid/pinned，四個 PIT unsupported。
- 統籌 full backend：bundled Python 3.12.14＋外部 Alembic 1.19.2，`python -m pytest backend -q --disable-warnings`，237 passed／4603 warnings／25.31 秒／exit 0。作者 focused 16 passed，final full 237 passed／24.63 秒另列。23 protected hash／size／mtime 一致；本輪未改或重測 frontend，未寫正式／.local DB。
- 證據目錄：`C:/Users/YiCheng/AppData/Local/Temp/stock-r09-coordinator-review`，包含 independent-review.json、backend-final.txt、protected-review.json、cli-pit.json、final-source-hashes.json。Manifest version `r1-a1-c009-2026-09-12.1`，canonical digest `sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`。
- Final SHA256：source_registry.py `FA2894ECC2C355A3EED295A9E2E8C6A7064DF3A38CD8615C6E135810E830AA08`；source_registry.json `104301791A38A01345D513D1913305C03613228A4FA7111C6C80A4AC4C5671C4`；test_source_registry.py `D4BE7E9AC20850CB2103CC2B20D113AB9769DA8AD2043E83373B3BA22AF8B658`。

本段只完成 R1-A1／G-SOURCE 的 versioned readonly registry 與首批四來源人工查證；source registry 沒有 immutable persistence，也不代表 R1 全來源准入、runtime collector enforce、官方 availability/PIT、B3-wire 或整體 ROADMAP 完成。D011 final 文件及 I037／I038 索引收斂後才開下一輪。

I037 已完成並由統籌 CLI 獨立核對：索引角色使用 App MCP，worker full ready 335 nodes／1445 edges，generation/indexed/recorded_at=2026-09-11T23:39:09Z；tests 333／1411，23:39:12Z。三檔 no_recorded_issue／metadata_changed，無 parse_partial／skipped，代表 registry／test symbols 可查。JSON 的 coverage=[] 不證明完整語意解析，保留原檔 hash／size／mtime 證據；23 protected hash 亦由索引角色複核一致。

D011 五份 final 文件已由統籌 review；最後校正 source row／manifest 的版本欄位歸屬、必要 evidence unknown 與非必要 notice unknown 的不同處理，以及 auth 條件只屬 local_fetch。SOURCE_REGISTRY SHA256 `A95255703C26D3014168BDA392BC9F79E20F37727AC1CD355FA7398EE6F56847`；DATA_SOURCES `29565FB4BCBFE5B3C3CB1EDA4D1B6E51B3B17F5D4369B4779C86F602D6729B57`；ROADMAP `FE20CEEA458C78C77D9974D4A0F048ABC5976B911F1EB8D4CB752D9D042DCB84`；ROADMAP_EXECUTION `4AE6A544A1947E5E3D4E72EA78860A96B36C13E369CE4358B48953E20831A482`；OPERATIONS `0AC2D0B94E69BD89656D99AB504FBD86CA312E5AD09B338B8BC2811FE7CBF941`。I038 更新此五檔加本協作紀錄；最終工具結果保留在本輪索引 task，下一輪先確認再分派，避免回寫 snapshot 造成循環刷新。

## Round 08（2026-09-12，review 與索引完成）

統籌確認 R07 I031 task 已完成 docs full 261 nodes／260 edges，五檔coverage與四文件hash核對通過。I031回報 generation/recorded_at=2026-09-11T22:03:48Z；本輪統籌 App MCP仍Transport closed，CLI讀到 docs generation17:02:31Z／recorded_at21:56:59Z，不能把兩者當同一實測值。四docs現況hash與D009 final一致，freshness仍metadata_changed；由I032核實兩channel metadata差異，不以此冒稱來源/索引完整新鮮。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a09298-0ba9-7821-9173-cfa27e2f6522 | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a09298-0ecc-75a0-ba09-abf41b999af8 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a09298-1189-7581-9ea2-bedf2e7e354c | gpt-5.6-luna | medium |

| 批次 | 寫入範圍／責任 | 狀態 |
| --- | --- | --- |
| C008 | api/decision、新product_time、必要backend tests；App/presentation/types/presentationtest。既有News/signal/action/stock/tracking時間read-time projection與UI | 有限產品 read-time 輸出已通過統籌 review；九個變動來源 freeze |
| D010 | R0_IMPLEMENTATION、ROADMAP、ROADMAP_EXECUTION、OPERATIONS、NEWS_SPEC；先契約入口矩陣、再final證據/狀態 | 五文件 final 已 review／hash 核對，停止修改 |
| I032 | 七分區status/coverage/symbol baseline及App/CLI metadata差異；收到freeze後才刷新各段 | 唯讀 baseline 已更正並 review；CLI check_index_coverage 七區完成，尚未刷新 |

本輪新增產品時間語意（預定product-time/v1），與strict time-evidence/v1分開。legacy cutoff/date-only/naive不可當可靠instant或availability；response生成時間與歷史決策/生成時間分開；News conflict不提升為已驗時間。保留API舊欄位/strategy數值/選取/keyset排序，UI標明資料/事件/發布/決策/規則最早執行日。禁止讀取無明確關聯的strict store或以任意evidence marker冒稱已驗證；strict持久化關聯、worker、B5b/PIT及來源truth仍後續。程式不改schema/DB/C007/ATR/worker/news來源投影，文件不改程式，索引不改來源；TASK_COORDINATION由統籌維護。

輪前備份/hash基線：`C:/Users/YiCheng/AppData/Local/Temp/stock-r08-baseline-e09e4d5c34f84962a8326943daa7cf5d/baseline.json`。13個可能修改的既有檔另有原檔副本，15保護檔含兩研究DB僅hash/size/mtime。測試用外部Temp與bundledPython/Node，不重啟或占用使用者既有服務。前輪已收斂後才開本輪三task；本輪修正仍使用相同角色task。
I032 更正後已由統籌核對：CLI 正確工具為 `check_index_coverage`，不能用 graph File-node 計數代替 coverage。七區皆有 complete coverage v3、hash_records_complete／generation_matches=true；scope known_gaps 只列明確排除的快取／依賴／build 目錄。既有指定來源 metadata_changed，新 product_time/test 路徑輪初 missing；後續建立後需刷新。docs CLI generation/indexed_at=2026-09-11T17:02:31Z、recorded_at=21:56:59Z，與前輪 App 回報22:03:48Z分開保留，本輪不冒稱已在 App 重測。I032 未改來源或索引。

統籌隔離驗收準備於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r08-coordinator-ui`：以前輪外部 fixture 的 SQLite consistent copy 建立 review.db，新增五筆明示 LOCAL_FIXTURE 的時間案例；14 組原版 API response 已存 baseline-api.json。正式及 .local DB 未用作服務／測試寫入目標。early review 已要求 C008 修正 News basis/precision、execution-at 與規則日期分離，以及 run finished 不等於 collected 的語意；目前尚未驗收。
### C008 統籌 final review

本輪完成 `product-time/v1` 產品 read-time 時間輸出：News、signal、action、stock、dashboard compact 與 tracking nested 角色保持一致，缺證據為 unknown。日期、帶時區 instant 與 response generation 分開；規則 `earliest_execution_date` 不冒充 `earliest_execution_at`。News basis/precision、conflict、非法前端日期／instant、unknown 不回退 legacy、技術區 collected formatter 均經退回修正。資料擷取 run 完成時間僅保留於 legacy.run_finished_at，不宣稱為每筆資料收錄時間。

- 統籌 final full backend：bundled Python 3.12.14＋外部真 Alembic 1.19.2，`python -m pytest backend -q --disable-warnings`：221 passed、4603 warnings、24.55 秒、exit 0。23.60 秒是 compact-news metadata 補漏前的測試，不能當 final。作者 final full 221 passed／24.11 秒另列。
- 統籌四個 frontend selftests 編譯／執行通過；presentation 額外以 UTC 與 America/Los_Angeles 執行皆通過。`tsc -b` 與 Vite production build 通過（82 modules、1.08 秒）。
- 獨立 16 項時間案例、18 組 API 新舊相容比對、17 個入口 query counts 相同；三個 signal／五個 news 的八組 subject projection 跨 detail／nested／compact 一致（只排除本次 response 時間）。同一組 fixture 的排序、keyset、舊欄位、策略數值無變動。非空 tracking 由新增 integration test 覆蓋；統籌 tracking list fixture 為空，不誇大其覆蓋。
- CUA 本地 accessibility tree 驗證新聞 naive 待核實、UTC 轉台灣時間、date-only 顯示發布日期而非午夜、衝突詳情時間待核實；action/stock 顯示資料日、未知決策時間與規則執行日，保留 102／101–103／99／106.8 價位。沒有宣稱 pixel-layout 或技術 details 展開驗收；collected formatter 以讀碼與純函式測試驗證。UI backend 啟動早於 final compact-news 欄位補漏，該差異另由 final API 檢查覆蓋。測試服務 18008／15178 已結束，使用者既有服務未動。
- `C:/Users/YiCheng/AppData/Local/Temp/stock-r08-coordinator-ui/final-review.json` 為彙整報告；同目錄 `final-source-hashes.json` 記錄 final 九個變動來源及未改 test_api.py 的十筆 hash／size／mtime，與作者一致。`protected-review.json` 的十五個既有程式／DB 目標 hash、size、mtime 全不變。此為隔離工程 fixture，不是官方 source truth／PIT／策略績效。

I033 初次在 api.py hash 不同時正確暫停，未用舊 snapshot 更新。C008 整體 freeze 及 final review 後，I033／I034 以 CLI full 更新四分區：app 662 nodes／3059 edges、tests 311／1334、frontend-full 287／918、frontend-src 233／854；generation／recorded_at 分別 2026-09-11T23:02:43Z、23:02:49Z、23:02:54Z、23:03:00Z。四區 ready，無 skip／partial，指定 paths no_recorded_issue；metadata_changed 與 best-effort 限制保留。統籌另用 CLI 核對 app／frontend-full timestamps 與 coverage。文件 final review／I035 尚待本輪收尾。

完成邊界：只接受 B5a 產品 read-time 輸出子項；strict time-evidence store 與產品／worker 的持久化關聯、官方 availability truth、B5b PIT、B2、B3-wire、B4b、B7 及整體 R0／ROADMAP 仍依原驗收逐批處理。下一輪依原流程各開三個新 task，不重用本輪角色；前輪來源與歷史證據保留。

D010 final 五文件已由統籌核對實際介面、完成範圍、歷史時點及證據；六個協作／規格檔共 47 個本地連結的目標存在。五 docs SHA256：R0_IMPLEMENTATION `AB14053E92103166F334B7100419A724E0B9D84ABBFA9DA590512DDF35D8C59C`；ROADMAP `AB2117A4134A628C573F2EF7BA6115FFE0F931ACCB4A878962CAFA6FE4EDE9E3`；ROADMAP_EXECUTION `B7B4F1E5CA006B45CFD73CFF5071A12E541F1DA8261822DA0D848CD5E1516FB3`；OPERATIONS `CDE4284C0C1080F0F80F9A3FEF02008AD392CF53C35D932A6E1D4461F924D17A`；NEWS_SPEC `171E8DDF5C8ED6F107BEE7E34E0C7759EAE54DD2562FC5AF23292F5C267FDD07`。I035 更新這五檔及本協作紀錄；結果保存在本輪索引 task，下一輪先確認成功再分派，避免回寫結果造成循環刷新。

## Round 07（2026-09-12，review 與索引完成）

Round06 I027 已由統籌確認：docs full 257 nodes／256 edges，recorded_at 2026-09-11T20:52:02Z，五檔 no_recorded_issue；metadata_changed 限制保留。此次 App MCP check_index_coverage/search_graph 實際回報 Transport closed，同引擎 CLI 查驗成功，未更動 App 程序或全域設定。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a0925b-cb7c-7b70-aafb-484fdf574fad | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a0925b-ce95-7d70-bc75-284969b90fb4 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a0925b-d154-7371-84a9-62fcc334ce0e | gpt-5.6-luna | medium |

| 批次 | 寫入範圍／責任 | 狀態 |
| --- | --- | --- |
| C007 | 新 time_evidence.py、time_evidence_store.py 及兩個對應 tests；R0-C3/B5a 本地 time-evidence/v1 角色、UTC／date-only／unknown、immutable revisions 與 exact 讀取／JSON 輸出 | 統籌有限 B5a 本地核心／保存範圍 review 通過，四來源 freeze |
| D009 | R0_IMPLEMENTATION、ROADMAP_EXECUTION、ROADMAP、OPERATIONS 的契約、驗收及狀態 | 四檔 final 已由統籌 review，介面／完成範圍／證據路徑與 hash 已核對，停止寫入 |
| I028 | 七分區 baseline／coverage；各段 freeze 後依統籌通知刷新 | 七區 ready、無 skip/partial；App MCP 正常（與統籌 channel 故障分開記錄）；新四檔 missing，五 docs metadata_changed |

I029 已完成 docs full 260 nodes／259 edges，recorded_at 2026-09-11T21:29:28Z，五檔 no_recorded_issue、無 skip/partial，metadata_changed 限制保留。草稿 hash 已由統籌核對，timestamp role、same-lineage revision、root-only not_applicable、strict-new/legacy-safe 區別及原 B5a 產品輸出驗收保留均通過文件 review；不等於程式已通過。

本輪僅新增明確 opt-in 本地時間證據模組與專用 SQLite；不改既有 ATR/store、Base/models/migrations/startup、worker/API/UI 或正式／.local DB。HTTP/UI 輸出接線仍屬 B5a 後續；不能以本地契約與保存通過宣稱 B5a 整體或 B5b PIT gate 已完成。修訂新列與 supersedes 必須保留歷史，unknown／date-only 不得猜造時間；caller-provided 結構不等於來源 truth。程式／文件／索引互不競寫，TASK_COORDINATION 由統籌維護。

輪前 15 個保護檔 hash/size/mtime 基線：`C:/Users/YiCheng/AppData/Local/Temp/stock-r07-baseline-73b8f84796034fd0b228f237364156b0/protected.json`，含兩研究 DB（僅 hash，未複製／寫入）。測試用外部 Temp、bundled Python 3.12.14 與外部真 Alembic 1.19.2。每段實作／文件 review 後通知本輪索引 task；前輪 task 保留歷史、不續派新輪。
### C007 統籌 review 與範圍

`time-evidence/v1` caller-provided 本地核心、獨立 schema 1 SQLite、exact 查詢與 JSON 匯出已 review。B5a 的 News/API/UI 產品輸出接線仍未完成；B5b PIT gate、官方 source truth、worker/B3-wire、B7 與整體 R0 未完成。根 identity 是 version＋subject＋source lineage，每 lineage 單一 root；snapshot 可隨修訂變，revision identity 不同才能 append。top source identity 表示 caller 選定 lineage，各 role.source 明示其 evidence provider，可不同；不從這些聲明推導官方同源驗證。

統籌逐段讀碼並退回 strict 新輸入隱式預設、空／矛盾 provenance、known precision=none、revision unknown availability 被拒、首版 not_applicable 混同 unknown、commit 後驗證、row_id REPLACE 可覆舊、supersedes key/id 不一致、同 lineage 多 root、祖先遺失與 JSON 匯出競態等。最終 writer/reader 對齊，unknown/unavailable 修訂可保存但不宣稱可供歷史決策；legacy-safe 保留原時間文字，不賦予缺失時區。

- 統籌 final 完整 backend：bundled Python3.12.14，PYTHONPATH prepend 外部真 Alembic1.19.2（Round03 Temp deps），`python -m pytest backend -q --disable-warnings`：215 passed、4592 warnings、24.03秒、exit0。作者 final targeted 15 passed／0.32秒。作者214 passed／23.12秒與統籌targeted14 passed／0.25秒是修前證據，不當final。
- 獨立22項檢查全通過，報告：`C:/Users/YiCheng/AppData/Local/Temp/stock-r07-final-review-80ea2c0ab3bd4f9ea7f4eab4187a76aa/review.json`。包含 UTC equivalent identity、date-only 無午夜、unknown／naive／alias／空來源反例、legacy JSON、不變 retry/collision、修訂同lineage、故障注入 new/retry precommit rollback、SQL rowid replace、foreign/empty DB 不變、單root與missing grandparent拒絕、hardlink atomic export 在競態新檔出現時不覆蓋。隔離測試不是官方 truth/PIT/replay 證據。
- 同目錄 `protected-review.json`：15保護檔 hash/size/mtime 全不變，含既有 ATR/store/provenance/comparison、models/news/db/migrations/API/decision/domain/pipeline/App.tsx、正式及.local DB。本輪未改前端、未重跑 frontend/build/browser。
- 四檔 final SHA256：time_evidence.py `799D9B9BD51C284321059AC908AB1079A2E0D12E875861E0FA9CA4B54E4245E7`；time_evidence_store.py `A454FA7A354DDE4E65A6F17D85188414A9930A6B3D4E1846E72FC6A547E92FC4`；test_time_evidence.py `5CFD4AD8160B207ACDD850BCA3BB37087F594F7A0B03BAF90BFDA6775D4E4067`；test_time_evidence_store.py `9FFF228814CAE8708D33B00C51369C6E68B3812D14D93FB49CF53DA51DE717EE`。統籌獨立報告與作者 freeze hash 一致。

I030 已由 App MCP full 刷新 app/tests：643 nodes／2981 edges、302 nodes／1307 edges，ready，generation/recorded_at 分別2026-09-11T21:48:38Z／21:48:42Z，無skip/partial，四path no_recorded_issue／metadata_changed、四hash一致，新symbols及tests可查。D009 final 四docs 已完成統籌 review/freeze。I031 刷新這四檔與本協作紀錄；成功結果保存在本輪索引 task 的 I031 回覆，下一輪先核對，避免為回寫索引結果再次改 snapshot。下一輪候選優先補 B5a 的明確 API／產品時間輸出，保留 legacy 無證據為 unknown，後續再依依賴接 B5b/B2/B3-wire；不得只做本地 helper 就結案整體 B5a。I031 成功後下一輪才各開三個新task。
D009 final SHA256：R0_IMPLEMENTATION.md `90E531481C70C96A7B9B5311E5DCD87C82F6788B0B7E4BA33C6E76E514C6B0BA`；ROADMAP_EXECUTION.md `F82C202C39201BC7A7F58BF0DFCDFF4DF64F7A1893A2CED740DF02BECC647E9D`；ROADMAP.md `EE0E94CAE1AF886B95BEC27F8AD9302C6CF906F1D8290830BEB7BC19B575CBCF`；OPERATIONS.md `55B596F9EEB6D19EFFD37A5EA0C98725E3CB7D8BE32E4B951CBC8DE1103D1B4C`。統籌已修正並核對報告路徑；實測 missing grandparent 與讀碼確認 ancestor seal 的證據分開陳述。
## Round 06（2026-09-12，review 與索引完成）

統籌以 CLI coverage 獨立確認 R05 I023：docs full 247 nodes／246 edges，recorded_at 2026-09-11T19:33:51Z，六文件 no_recorded_issue；metadata_changed 的 best-effort 限制保留。前輪review／索引收斂後才建立本輪三個新 task。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a09214-0bb9-7202-845b-5cdcf4c4d0c9 | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a09214-0e94-7542-90bb-fcee04232b03 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a09214-114a-7893-a569-78e70efada3c | gpt-5.6-luna | medium |

| 批次 | 範圍／責任 | 狀態 |
| --- | --- | --- |
| C006 | R0-B4/B3-persist：artifact_store、必要provenance/comparison模組與backend tests；完整caller-provided結構/缺漏政策、readonly legacy＋v2＋兩asof比較 | 統籌有限B3-persist範圍review通過，六來源freeze |
| D008 | R0_IMPLEMENTATION、ROADMAP_EXECUTION、ROADMAP、OPERATIONS；契約與驗收證據 | 四文件 final 已由統籌獨立 review；歷史待辦／ordinary writer 相容性文字已修正，hash 核對後停止寫入 |
| I024 | 七分區 baseline/coverage | CLI七區ready，無skip/partial，既有關鍵檔noissue/metadata_changed；新模組尚未索引。此task未嘗試App MCP，不虛稱Transport closed |

索引角色曾誤建 `01a09214-6cd6-7803-afb8-f5503b7fddb5`，統籌已確認停止，未再建task；此對話僅保留歷史、不承担工作。角色不得自行create/fork新task，跨輪分派由統籌負責。

I025 已由CLI full刷新docs：255 nodes／254 edges，recorded_at 2026-09-11T20:15:24Z，五檔no_recorded_issue、無skip/partial，metadata_changed保留。I026 已由 CLI full 刷新 final app/tests：538 nodes／2475 edges、280 nodes／1191 edges，兩區 ready、無 skip/partial，recorded_at 2026-09-11T20:44:01Z；新增模組與測試 symbols 可查，六個 final hash 全一致。指定檔 no_recorded_issue，metadata_changed 限制仍保留。D008 final 文件已由統籌 review 並停止寫入。I027 刷新 final 四文件與本協作紀錄；成功結果保留於本輪索引 task 的 I027 回覆，下一輪先核對，避免為回寫結果再次變動 snapshot。

統籌維護TASK_COORDINATION；程式不改docs/ATR core/worker/API/decision/domain/models/migrations/frontend；文件不改程式；索引不改任何來源。新契約須版本化，C004舊schema1 artifacts保留可讀及原hash，不自動提升為strict。compare必須顯式指定legacy snapshot和artifact版本/asof/key，禁止implicit latest，跨DB按exchange+symbol核對；正式及.local DB不寫入。只驗caller-supplied結構與isolated storage/comparison，source truth/PIT execution gate/worker wire仍後續，不反向阻塞B3-persist。

輪前備份與hash/size/mtime：`C:/Users/YiCheng/AppData/Local/Temp/stock-r06-baseline-ec3f0021217243e4a0011b5a508cc640/baseline.json`；DB僅hash，無裸複製。測試使用外部Temp與bundledPython，完整backend驗證包含Round03外部真Alembic1.19.2。

### C006 統籌 review 與範圍

C004＋C006 的 B3-persist 有限儲存／caller-provided 結構完整性／離線比較已通過review。schema仍1，新增明確 `atr-provenance/v2` strict入口與read-time重驗；舊minimal資料不升格。官方truth、PIT execution gate、worker/API接線與B7不在本輪驗收，B3-wire／B5及整體R0未完成。

- 最終完整backend：bundledPython3.12.14＋Round03外部真Alembic1.19.2，`python -m pytest backend -q --disable-warnings`＝200 passed、4592 warnings、25.72秒、exit0。作者同源另一輪200 passed／25.75秒；199 passed／23.54秒是最後交易邊界修正前，不當final。前端未改，本輪沒有重跑frontend或瀏覽器。
- 已退回並獨立驗證：市場日期Asia/Taipei、normalize可重入、adapter模式一致、row/halts/availability/來源引用衝突、digest算法與合法形狀、manifest/config/basis重算、多selected前收與current/predecessor對齊、ordinary writer偽裝strict的欄位矛盾、exactselector/readonly/snapshot mismatch。外部hash仍只是caller聲明，不驗來源truth。
- final独立報告：`C:/Users/YiCheng/AppData/Local/Temp/stock-r06-final-review-dg6tjhm9/review.json`。注入strict validator失敗，new及retry四表counts完全不變；same snapshot兩asof並存/可比delta0，differentsettings不可比且delta null；legacy對照一律保留caller-declared/incomparable；含空格/#的隔離DB正常只讀，legacy bytes/mtime不變。
- 原C004基準由輪前原始module建立：`C:/Users/YiCheng/AppData/Local/Temp/stock-r06-coordinator-p5raawt4/c004-original.db`，原key `ad49a3272b5a566c69d659adc324056765399f741353b528808fc55771470e05`／payload seal／首次generated_at／bytes／mtime保持，final strict reader拒絕將old升格。
- 八個反例獨立報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r06-negative-review-j8lsx8pw/report.json`：非法hash/algorithm、unknown row＋有效ATR、halted矛盾、wrongexpectedhash、缺檔不創建、liveWAL拒絕、duplicateinstrument只有一feature仍拒絕。此報告保留中間來源hash；final回歸另驗相應行為，不能冒稱中間報告為finalhash。
- `C:/Users/YiCheng/AppData/Local/Temp/stock-r06-coordinator-p5raawt4/protected-review.json`：ATR、models、db、migrations、API、decision、domain、pipeline、App.tsx、正式DB、.localDB共11檔hash/size/mtime全不變；test_artifact_store.py也保持hash。六個修改來源實際hash在同目錄 `fulltest-source-hashes.json`，統籌確認完整測試後到freeze無變動。

六個final來源SHA256：artifact_store.py `0C0907289B66D3979C55232F46024DEB7B7EE7EFAC7FBF91EEC5FD020B849ED4`；artifact_provenance.py `B28109D7218BD8FA2127DD9C6AAEFB60E210BE3C0A3B253744267EE97F3695D8`；artifact_comparison.py `08BA9301FDFD73F91C571D1DA08697A1F8D720D7AF16D7593E4FC15D5D6441FA`；test_artifact_provenance.py `B940280A0C5846B037CE68DF5E908CC4CBAFB2C8CEB6BCA9557B6B42C38CFC2C`；test_artifact_comparison.py `48B9025EC86DF8379BBB7BCA2F091A15EE12FA3C5E6A7B33F45AEF4273F711EE`；strict_artifact_fixture.py `3D495A4EBF0B06AEAB6C8F18E794BF6BC972E07E0D059212EFD9B155E453D24B`。

D008 final SHA256：R0_IMPLEMENTATION.md `B06F09C2337555F9A9F2DCD9B03091EE8B27C7D90E46284CCBE05EAD0C1DD499`；ROADMAP_EXECUTION.md `683F72E08B5017ABB78A4B760E26852A225CCEF6E4D6554AA630C0BCAD722E33`；ROADMAP.md `BA95DAA6A8D979138D48C94217E30DD1643BA5B1B464BBC9FED806B76C449A56`；OPERATIONS.md `FF7AE00DBDD5A58E9A44E6564F8E1394E9716E39C4757AF5CB971EE3B14A661D`。

下一輪候選優先 R0-C3/B5a 明確時間證據的保存/輸出，再依依賴接B2/B3-wire；不自動啟用新策略或正式migration。I027 final docs成功前不開Round07；後續仍每輪三個新task，不重用本輪角色。

## Round 05（2026-09-12，review 與索引完成）

統籌已确认 Round04 I-019 完成：docs full 240 nodes／239 edges，recorded_at 2026-09-11T18:30:31Z，五文件 no_recorded_issue，metadata_changed 限制保留。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a091d9-cf45-7fd3-96e9-5492d63ea81a | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a091da-4c23-7a40-8d54-455848cc89c4 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a091da-4eae-7c61-b8d9-a6e81c3ab85d | gpt-5.6-luna | medium |

| 批次 | 範圍／寫入責任 | 狀態 |
| --- | --- | --- |
| C-005 | R0-C1/B4a：API/domain/decision、前端 App/presentation/types 與必要測試；統一規則參考價語意，保留原公式/數值 | 統籌 B4a read-time 範圍 review 通過；來源停止寫入 |
| D-007 | R0_IMPLEMENTATION、ROADMAP_EXECUTION、ROADMAP、STRATEGIES、OPERATIONS；契約矩陣、真實狀態與證據整合 | 五文件 final 已由統籌 review，hash 已核對並停止寫入；只結案 B4a read-time 語意 |
| I-020 | 七分區 baseline／coverage | App MCP 正常，七區 ready，無 parse_partial；保留 freshness best-effort 限制 |
| I-021 | D007 契約與本輪三 task ID 段落 | docs full 245 nodes／244 edges，recorded_at 2026-09-11T19:14:24Z；六文件 no_recorded_issue，metadata_changed 保留 |
| I-022 | C005 final app／tests／frontend-full／frontend-src | full 完成：445/1937、238/934、276/872、222/808 nodes/edges；19:25:57／19:26:01／19:26:05／19:26:09Z。指定檔 no_recorded_issue、無 skip/partial，metadata_changed 保留 |
| I-023 | D007 final 五文件與協作紀錄停止寫入後刷新 docs | 已通知刷新 final 六文件；成功結果以本輪索引 task 的 I-023 回覆為準，下一輪先確認 |

本輪不寫正式或 .local 研究 DB，不修改 worker/ATR/artifact store/models/migrations；不把實際持倉成本或成交價改稱規則參考價。未知 strategy/version、basis、成本或時間無證據時明示 unknown/null，不由 legacy cutoff/date-only/naive timestamp 猜造精確 decision time。B4b 新交易計畫與 B5 時間 gate 保留待後續。

統籌輪前備份與 hash/size/mtime：`C:/Users/YiCheng/AppData/Local/Temp/stock-r05-baseline-c7d4e7fd1b3b40b0a8c811600476afbe/baseline.json`；同目錄依相對路徑備份可能修改的原程式（DB 僅 hash，未裸複製）。共用 local 寫入按角色隔離，TASK_COORDINATION 由統籌維護。

### C-005 統籌 review 證據

本輪只完成 R0-C1／B4a 的 read-time 規則價位語意。`signal-level-semantics/v1` 依實際 StrategyVersion allowlist 描述 `legacy-risk-levels/v1`；未知 identity 明示 unknown，歷史 basis／decision_at／generated_at 不猜造。action 的 response generated_at 改為含 UTC offset，與 nested historical time 分開。持倉 stop 的來源與規則 invalid fallback 分開；數值、公式、選擇優先序及歷史資料保持原狀。

- 統籌使用 bundled Python 3.12.14、外部真 Alembic 1.19.2，執行 `python -m pytest backend -q --disable-warnings`：180 passed、4592 warnings、25.94 秒、exit 0。作者原 fallback 環境的 179 passed／1 skipped 是不同執行，不混稱真 Alembic 驗證。
- frontend presentation／routes／search／units 四組 self-executing assertions 由統籌編譯 CommonJS 至外部 Temp 後 Node 執行，全 pass；作者 final production tsc＋Vite build exit 0。新增 unknown／spoofed／不支援版本／stop origin／回踩整段標籤回歸。
- 統籌發現並退回新增 N+1 query；修正為 context 批次保留 StrategyVersion。外部 fixture 1 檔與 5 檔股票均 13 queries，單獨 `FROM strategy_versions` 查詢 0，非僅依作者回覆判斷。
- 瀏覽器實驗使用外部 fixture copy、API 18005／Vite 15175。/actions 持倉平均成本100、10股；共享 stock-detail 的 /actions/TWSE/AAA 顯示使用者風險101。僅修改隔離 copy，移除持倉後 known breakout 顯示規則觸發21.05／失效20.47／目標一21.98；pullback 案例為規則計算參考102、整段觀察區101～103、失效99、目標106.8；改為未知版本9.9.9後安全 unknown 標籤且值不變。這是 UI fixture 行為，不是真市場或策略績效證據。
- /signals、/tracking 的 UI 是 redirect；本輪未冒稱獨立頁面測試。各自 API full／compact／detail／tracking 由後端測試驗證。已關閉統籌自己的測試頁面與兩個程序。
- 統籌另將輪前備份的 decision.py 動態載入，用獨立 Session 比較 original held-known 與 modified unknown-pullback 兩組 fixture；只排除新增 semantics 與 response generated_at 後，完整 action payload 相等。報告同目錄 `behavior-comparison.json`；不宣稱全量市場 replay。
- 證據與十個最終來源 SHA256：`C:/Users/YiCheng/AppData/Local/Temp/stock-r05-coordinator-ui/review.json`。保護檔案報告同目錄 `protected-review.json`：domain、models、db、migrations、worker pipeline、ATR、artifact store、正式 DB、.local DB，九檔 hash／size／mtime 全不變。

D007 final 五文件 hash已由統籌核對：R0_IMPLEMENTATION.md `87DF59841BC5DB90AFDAC580E2A6D345C18FFD38A9E5079C5D627861744C9027`；ROADMAP.md `D5816554C0778B9CA25BDD4F344226BA7BFC1A5994D41F87B3800CF8FEFB2F49`；ROADMAP_EXECUTION.md `8DB4630F20A9E4215D3695302B82603017B1DE2E4D84C7B32658E0A35E1FBB4B`；STRATEGIES.md `45C58E57E46C6E937CE3317A68903C05BAE42F5842FF296C993AEE4AF4A00771`；OPERATIONS.md `4148139444716ED6A69BFE989CA44DE08EE20905BB4F20581CC61593AD6ED6FD`。

下一輪候選優先完成 B3-persist 剩餘的 caller-provided provenance 結構／缺漏政策與唯讀 legacy、Wilder v2、兩 as-of 查詢／比較。官方 truth、PIT execution gate、worker/API 切換仍屬後續，不能反向阻塞純儲存驗收。B4b、B5、整體 R0 與 ROADMAP 尚未完成。

## Round 04（2026-09-12，review 與索引完成）

統籌已確認 Round03 I-015 完成：docs full 235 nodes／234 edges，recorded_at 2026-09-11T17:21:46Z，六文件 no_recorded_issue；metadata_changed 的 best-effort 限制仍保留。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a0919d-ff53-79a0-aa9f-f250b77bfd48 | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a0919e-4bbd-7a33-94a9-21528a974d13 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a0919e-8aed-79b0-83bb-3e84b5c2e4d1 | gpt-5.6-luna | medium |

| 批次 | 範圍／寫入責任 | 狀態 |
| --- | --- | --- |
| C-004 | R0-B4/B3-persist 第一段：新增 artifact_store 模組與測試；ATR feature artifact 獨立 SQLite 儲存、不可覆寫 identity、重試與明確版本查詢 | 統籌有限儲存範圍 review 通過；程式停止寫入 |
| D-006 | R0_IMPLEMENTATION、ROADMAP_EXECUTION、ROADMAP、OPERATIONS；契約與證據整合 | 四文件已由統籌核對實作、證據與依賴，review 通過並停止寫入；README 未改 |
| I-016 | 七分區 baseline／coverage | 七區 ready；metadata_changed 限制保留 |
| I-017 | D006 契約草稿與三角色 ID 段落 | docs full 238 nodes／237 edges，recorded_at 2026-09-11T18:05:10Z；App MCP 在索引角色可用，統籌通道仍 Transport closed；五文件 metadata_changed |
| I-018 | C004 final 後刷新 app／tests | App MCP full 成功：app 430 nodes／1877 edges，generation/recorded_at 2026-09-11T18:20:40Z；tests 232／908，18:20:44Z。兩新檔 no_recorded_issue、metadata_changed；無 skip/partial |
| I-019 | D006 final 四文件與本協作紀錄停止寫入後刷新 docs | 最終 generation／搜尋／coverage 結果保存在本輪索引 task 的 I-019 回覆；下一輪先確認成功，避免回寫索引結果再改 snapshot |

本輪採明確 opt-in 的獨立 artifact DB/schema，無預設 DB 路徑，拒絕既存非 artifact DB；不註冊 legacy Base 或自動啟動 migration。既有 data/stock.db 與 .local/data/stock.db 均不写入。這是儲存基礎，尚非官方來源接線、worker/API 切換、完整 B3/B2 或 paired replay。各角色限定互不衝突的寫入範圍；TASK_COORDINATION 由統籌維護。

### C-004 review 證據

統籌已退回並重現修正：既存空／view-only DB 所有權、特殊字元 URI、parent/child 的 REPLACE 與新增 child 防護、locked transaction rollback、同 attempt 重送、null reason 與負 ATR/TR 拒絕。首次封存 generated_at 保留；同 identity 不同研究 payload 拒絕，attempt/run 關係不污染研究 identity。單次 save 的整個 ATRArtifact、observations、dependencies 與 attempt 共用一個 transaction；不宣稱多次 save 的通用批次原子性。

- 最終僅新增 backend/app/artifact_store.py（SHA256 `40CEC8F0304E26456EC41C9C23DE03AE7ABE0F1B1145068508450430435DAC66`）與 backend/tests/test_artifact_store.py（`B519CF4FED6B45D46FAB8EA1590633F443630C9B7190ADFD7FFE3DE1D745CC7A`）。
- 統籌使用 bundled Python 3.12.14，PYTHONPATH 包含 Round03 外部 Alembic 1.19.2 依賴、backend、backend/.deps，執行 `python -m pytest backend -q --disable-warnings`：176 passed、4486 warnings、26.84 秒、exit 0。測試由 conftest 隔離外部 Temp DB；程式 task 最終 ATR＋store targeted 為 47 passed、exit 0。
- 統籌獨立手建 fixture 報告：`C:/Users/YiCheng/AppData/Local/Temp/stock-r04-coordinator-5hv5_brl/review.json`。驗既存空／legacy／view DB bytes/mtime 不變、首次 seal／offset 等價重播、collision 四表不變、REPLACE／新增 child 拒絕、含 # 路徑重開、真正同時雙連線冪等。此報告對應 null policy 小修前 store hash 7593836D…，不冒稱該舊報告為 final hash。
- 最終小修獨立報告：`C:/Users/YiCheng/AppData/Local/Temp/stock-r04-final-review-c2_iri8g/review.json`；驗 null ATR 無原因、負 TR/ATR 拒絕及合法 ATR 保留。作者回歸另驗未知 schema version 拒絕且 bytes/mtime 不變、attempt timestamp 錯誤令已插入的四表資料整筆回滾。
- `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-baseline-4fb9f0579d6141d295c3c0bcc9bc9e57.json` 的八個 baseline 檔案（atr、models、db、migrations、api、pipeline、正式 data/stock.db、.local/data/stock.db）hash、size、mtime 均不變。

儲存層只驗 caller-supplied 結構、必填欄位與不可變存取；完整來源 manifest 對齊、官方真實性、所有 availability/decision 時間先後仍未驗證，不能因此通過 source/PIT gate。schema version 1 與 legacy Alembic 0005 分開；未接 worker/API 或改預設策略，B3-wire、B2、B7 與整體 R0 仍待後續輪次。

D006 最終 review 已修正 SHA seal／SQLite 約束的描述、獨立報告與作者測試的證據界線，以及 B4/B5 循環依賴。B3-persist 的剩餘 gate 是同日唯讀 legacy、Wilder v2、兩 as-of 查詢／比較及完整 caller-provided provenance 結構／缺漏政策；官方 truth、PIT execution gate、worker 接線屬後續 B3-wire/B5，不能反過來阻塞純儲存驗收。

最終四文件 SHA256：R0_IMPLEMENTATION `487F3735C00A6261EAFCFDBBB908B3E0DECF988EBB128EF693EF0A4A70292685`；ROADMAP_EXECUTION `1BF611823AB555EAA65018AE0975B57359A0A8F3B07B99868D0AE69BEAEB540A`；ROADMAP `685F022F9DD26764BE1B9FC0CE6A83E728FFC20D92FF47F36921C3DA2391B5BD`；OPERATIONS `F3B3551A37D322B9958FEC2A2EFE344A9190164A7FDA305852E978B7299873B5`。

下一輪候選優先處理 R0-C1／B4a：API 與 list/detail/action/tracking 畫面的規則參考價語意一致化，沿用既有 v1 算式、保留歷史資料；同時保留 B3-persist 剩餘驗收與 B2-persist 待辦。I-019 成功前不建立 Round05；成功後每角色再開新 task，沿用固定模型與 reasoning。

## Round 03（2026-09-12，review 與索引完成）

使用者授權從本輪起持續以相同步驟逐輪推進直到 ROADMAP 完成，並已確認僅使用「免費公開資料與本地測試」。統籌不需每轮詢問是否繼續；需要外部來源、個人決策或前瞻觀測的項目保留真實待決／待驗證狀態。定時喚醒先處理未完成當輪，避免重複分派。

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a09163-fbe7-7e60-9f67-a7e5db749b14 | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a09164-895b-7d43-9d4f-29cf1bf1c6c8 | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a09164-8da6-7860-b6ca-7844178aace9 | gpt-5.6-luna | medium |

| 批次 | 範圍／寫入責任 | 狀態 |
| --- | --- | --- |
| C-003 | R0-5/B6：正式 SQLite current 唯讀查驗、一致副本與空 DB migration、資料保存驗證；修正 test_schema.py 的 Alembic／fallback 測試契約 | 統籌 review 通過；正式 DB 未 upgrade；程式停止修改 |
| D-005 | ROADMAP_EXECUTION 全 R0-R3 可驗收清單、B6/後續持久化契約；取得 C003 證據後同步 R0_IMPLEMENTATION/ROADMAP/OPERATIONS/README | 統籌逐項核對依賴、契約、final 證據與五文件狀態，review 通過；已停止寫入 |
| I-011 | 七分區唯讀 baseline 與 Round02 符號覆蓋 | 七區 ready；best-effort freshness 限制保留 |
| I-012 | Round03 新角色 ID／持續授權與免費範圍治理段落 | docs full 215 nodes／214 edges；中間 snapshot |
| I-013 | D005 執行清單與 B6/B2/B3 契約 review 段落 | docs full 232 nodes／231 edges；generation 2026-09-11T17:02:31Z；metadata_changed 限制保留 |
| I-014 | C003 review 後只刷新 backend-tests | App MCP Transport closed；使用同引擎 CLI 替代通道 full 刷新成功，203 nodes／744 edges，generation 2026-09-11T17:16:24Z；metadata_changed 限制保留 |
| I-015 | D005 final 五文件與本協作紀錄停止寫入後刷新 docs | 最終 generation／搜尋／coverage 結果保存在本輪索引 task 的 I-015 回覆；後續統籌先查此回覆確認成功，再開始 Round04，避免回寫索引結果改變 snapshot |

本輪先完成資料庫版本與隔離驗證，作為 B2/B3 新舊 artifact 儲存隔離的前置。後續清單由文件 task 拆解、統籌 review。Git 仍無 HEAD，共用 local 目錄；來源修改前保留專案外備份，不自行建立未授權的版本歷史或清理既有檔案。

本統籌已建立 heartbeat 自動化 `roadmap`（台股 ROADMAP 持續統籌），每 30 分鐘接續尚未完成工作；無變化保持安靜，有實質段落完成、失敗或必要決策才通知。全部驗收完成即停止；剩餘工作均需外部變化／使用者決策時列清楚阻礙並暫停，避免空轉。此為開發統籌接續，不是資料收集或交易排程。

### C-003 review 證據

正式 DB 依環境／config 規則解析為 `C:\Users\YiCheng\Desktop\taiwan-stock-research\data\stock.db`，查驗使用 SQLite `mode=ro` 與 `query_only=ON`。它没有 `alembic_version`，只有 fallback `schema_migrations` 五筆，不能稱為正式 Alembic 0005。正式檔 size 296054784、mtime 與 SHA256 `74A34389DBFA65429D27EA41BC9DECA2A132808F10093E2FFDE98665D96232D6` 在查驗前後一致。

統籌於 UTC 2026-09-11T17:13:34（台北 2026-09-12）另建立全新 SQLite 一致副本與空 DB，兩者真正執行 Alembic upgrade 到單一 head `0005_news_temporal_contract`；20 個既有表、622399 筆資料逐表內容 fingerprint 與 row count 保持一致，副本只新增 alembic_version；fresh／copy 業務表欄位集合相同，完整性 ok、外鍵錯誤 0。正式 DB 沒有 upgrade、stamp 或資料寫入。復原策略為重建一致副本；未實際執行 downgrade／restore，不宣稱此項已測。

- 統籌獨立：有 Alembic 的 schema＋API targeted 12 passed、55 warnings、4.01 秒；原 bundled 環境的 schema-only 3 passed、1 skipped、1.19 秒；均 exit 0。skip 明確只因缺 Alembic。
- 程式 task：有 Alembic 的完整 backend 157 passed、4486 warnings、24.34 秒；schema＋API 12 passed；原 bundled schema＋API 11 passed、1 skipped；隔離 API startup 與 health HTTP 200。完整證據區分環境，不混用結果。
- 僅修改 `backend/tests/test_schema.py`：明確驗真 Alembic revision 與強制 fallback 五個 markers，保留 legacy identity／資料驗證；不為測試新增 production marker table。SHA256 `32BA427EA86E5E6905785CEF01848DE0E8B364214F48C5C19F1BDD3D27BE08B9`。
- 輪前測試備份：`C:\Users\YiCheng\AppData\Local\Temp\stock-r03-c003-test-schema-original-20260911-170800.py`，SHA256 `26C886B6EABD64C5303610930CA510A9F345B091083133F1C0106751C4C1F3D2`。
- 程式 task 驗證腳本：`C:\Users\YiCheng\AppData\Local\Temp\stock-r03-c003-verification-20260911-171200.py`；報告：`C:\Users\YiCheng\AppData\Local\Temp\stock-r03-c003-report-20260911-171200\r03-c003-verification.json`，報告 SHA256 `677286E560E14AE88F96414D4B2068DA768D9F91A981C6A37C6C8444F2E9F4A8`。
- 統籌獨立報告：`C:\Users\YiCheng\AppData\Local\Temp\stock-r03-coordinator-1gcowt5o\coordinator-review.json`，同目錄有 `copy.db` 與 `fresh.db`。
- Alembic 1.19.2 安裝於專案外 `C:\Users\YiCheng\AppData\Local\Temp\stock-r03-c003-alembic-deps-20260911-170100`；bundled backend/.deps 本身仍無 Alembic。臨時腳本未保留於 repository。

後續首要批次是 B2/B3 不可變 artifact 儲存；免費來源 registry 可行性可並行，不讓條件式分點來源阻塞無關功能。新模型改動需特別驗證 pre-head DB，因現有 0001 migration 引用當前 Base.metadata；fresh DB 測試不能單獨證明後續 revision 的實際升級。

本輪索引通道恢復：App 內 MCP 仍回報 Transport closed，改用設定中同一 executable `C:\Program Files\nodejs\node_modules\codebase-memory-mcp\bin\codebase-memory-mcp.exe` 的 `cli --json <tool_name> <json_args>` 一次性呼叫。此為同一 codebase-memory 引擎，不是用 rg 冒充索引；未重啟／終止既有 App 或 MCP、未改全域設定。後續先查正常 MCP，失效時可使用這條已驗證的 CLI 通道。

## Round 02（2026-09-12，已收斂）

| 角色 | 新 Task ID | 模型 | Reasoning |
| --- | --- | --- | --- |
| 程式實作 | 01a09146-2594-7753-93a3-47215d497dd9 | gpt-5.6-luna | xhigh |
| 文件與邏輯整合 | 01a09146-abcd-7210-aff0-35a2ddee5cdd | gpt-5.6-sol | high |
| Codebase 索引維護 | 01a09146-ae5b-7810-9bc4-44e33fa139a8 | gpt-5.6-luna | medium |

| 批次 | 範圍／寫入責任 | 狀態 |
| --- | --- | --- |
| C-002 | 新增 backend/app/atr.py 與 backend/tests/test_atr.py：獨立、無 I/O 的 versioned ATR14 Wilder 純計算核心；修正 frontend/src/presentation.test.ts 過時文案期待 | 統籌最終 review 通過；獨立 ATR 28 passed、完整 presentation test exit 0；程式停止寫入 |
| D-003 | docs/R0_IMPLEMENTATION.md 的 B3 第一段邊界、手算驗收矩陣；必要 docs/README.md 指引 | 文件契約與 C-002 純核心實作對照已 review |
| D-004a／b | 唯讀交叉 review；收斂 R0_IMPLEMENTATION、ROADMAP、STRATEGIES、README 的實際介面、證據與未完成邊界 | 統籌已讀取最終四文件並核對狀態／時間／前收契約及測試證據，review 通過；文件停止寫入 |
| I-006 | 上輪分區健康／關鍵符號唯讀 baseline；各段完成後由統籌通知刷新 | 7 區 ready，前輪關鍵符號可查；freshness 限制保留 |
| I-007 | 每輪新對話規則與 Round02 ID 的段落索引 | docs full 211 nodes／210 edges；已查新規則與三 ID |
| I-008 | D-003 契約 review 後刷新 docs | full 212 nodes／211 edges；契約、手算矩陣與每輪新對話規則可查 |
| I-009 | C-002 review 後刷新 app／tests／frontend-full／frontend-src | 四區 full 完成，新 ATR 與測試可查；generation 2026-09-11T16:46:25Z～16:46:35Z；freshness 限制保留 |
| I-010 | D-004b 與本協作紀錄停止寫入後，最終刷新 docs 五文件 | 最終 generation／搜尋／coverage 結果保存在本輪索引 task 的 I-010 回覆，避免為回寫結果再改 snapshot |

本輪選用 TR 納入前收盤、14 有效 TR seed、其後 Wilder recurrence，僅生效於新版本純計算核心。正常資料、首根／截窗、缺 session、停牌、OHLC、價格基礎及資料可得時間必須有可重現驗收。公司行動調整後價格與 provenance 由上游明確提供；純核心驗證契約，不冒稱已驗證官方來源真實性。

本輪不將新 ATR 接入 worker／API／候選／回測，不改舊 features_json.atr14、策略 gate、schema 或正式 DB。完整來源接線、新舊持久化 artifact 與 paired replay 留待後續批次；純核心通過不等於 R0-1 全部完成。

D-003 review：統籌已閱讀 §4 完整矩陣，核對 TR=1…16 的 seed=15/2、Wilder=225/28、3373/392，與 rolling SMA 17/2、19/2 不同；缺 S21 後 S22 僅建立前收錨點、S23 才恢復第一個 TR、S36 出第一個恢復 ATR；確認停牌案例為 29/7。文件 task 以 Fraction 獨立重算並檢查 Markdown 連結通過。這是公式與文件契約 review，尚不宣稱程式已通過。

根 AGENTS.md 與本紀錄由統籌寫入。程式與文件寫入範圍分開；review 通過並停止該段寫入後，再通知本輪索引 task 更新並驗證。全部段落的結果由本輪統籌收斂。

### C-002 最終 review 證據

統籌逐段讀碼並退回修正必要時間／coverage 證據、前收來源、真正序列起點、大數 seed、全 artifact 公司行動依賴、停牌價格矛盾與首筆 row-level 前收優先序。最後版本只接受 caller-supplied metadata 的一致性，並不驗證外部來源真實性。新核心未接入正式流程。

- 統籌獨立執行：bundled Python 3.12.14，`PYTHONPATH=backend;backend/.deps`，隔離 Temp 資料環境，`python -m pytest backend/tests/test_atr.py -q`：28 passed，0.26 秒，exit 0。
- 統籌使用獨立對稱 OHLC fixture 與 Fraction 核對 seed 15/2、Wilder 225/28、3373/392（tolerance 1e-14），另重現全 basis late-action 拒絕、較晚 as-of 重算且舊記憶體 artifact 不變、calculator／row 前收優先序、無效前收不能被 IPO fallback 掩蓋；均通過。
- 統籌獨立以 `tsc --module commonjs --target es2020 --skipLibCheck` 將完整 `frontend/src/presentation.test.ts` 編譯到外部 Temp，再以 Node 執行，兩步 exit 0。與輪前備份比較，唯一文字差異為「回踩研究條件：已成立」改成「回踩條件：已成立」；實際產品文字未改。未執行全 frontend suite 或瀏覽器 UI 驗收。
- 程式 task 曾執行完整 backend：153 passed、4417 warnings、23.92 秒。此證據早於最後的全域 action、停牌衝突與前收優先序修正；最後版本重跑的是上述 targeted 與 presentation，不能將 153 passed 冒稱最後版本全套結果。
- worker/pipeline.py、app/domain.py、app/models.py、app/api.py、frontend/src/presentation.ts 的 SHA256 均與輪前相同；沒有正式 DB 操作或策略接線。

| 最終交付檔 | SHA256 |
| --- | --- |
| backend/app/atr.py | B74769A9C76AC30F9EA437B4124A8A0C964E32454129868B8EF756BDA523BD78 |
| backend/tests/test_atr.py | E42099291783E4E324955B8F1BC2621C7451F50FACF58BDB8E23A1B442FF9722 |
| frontend/src/presentation.test.ts | 2ADD00B2A15F51FE29691BB321D67D103B1262B628CCF35BF34DCEDA37FF0E89 |

I-009 的四區 nodes／edges 分別為 app 376／1585、tests 201／739、frontend-full 265／847、frontend-src 211／783；四個交付路徑 coverage 為 no_recorded_issue、recording_status=complete，但仍為 metadata_changed。統籌另以 MCP 查到 calculate_atr14 的 suspension_price_conflict，並重查 atr.py coverage；不宣稱全域新鮮度已證明。根目錄 AGENTS.md 無 MCP coverage 的既有限制仍保留。

## Round 01 角色（歷史，不再分派新輪工作）

| 角色 | Task ID | 模型 | Reasoning | 寫入責任 |
| --- | --- | --- | --- | --- |
| 統籌／review | 01a09112-1254-7452-8eaf-25ef706aa5e1 | 沿用統籌設定 | 沿用統籌設定 | 分派、驗收、此紀錄與根 AGENTS.md |
| 程式實作 | 01a09119-881c-70a0-a38c-c0b59b64a430 | gpt-5.6-luna | xhigh | 指定程式及必要測試 |
| 文件與邏輯整合 | 01a09119-3e44-7c41-a59a-ca45e7f6f34d | gpt-5.6-sol | high | 指定文件、契約、驗收證據整合 |
| Codebase 索引維護 | 01a09119-cd73-72f2-9a13-fd8420a8a115 | gpt-5.6-luna | medium | MCP 索引及其覆蓋驗證 |

來源：task `01a090f6-a2a8-7bf0-a1ee-9ed51988d672` 的文件整理，以及第一輪使用者指定的固定分工。當時沿用上述 task 發送 follow-up；此方式已被 2026-09-12 的每輪新對話規則取代。

## 第一批

| 批次 | 負責人 | 交付與邊界 | 狀態 |
| --- | --- | --- | --- |
| D-001 | 文件 | R0-1～R0-5 的實作與驗收契約；僅 R0_IMPLEMENTATION.md 與 docs/README.md | 2026-09-11 統籌文件 review 通過；不代表程式驗收 |
| C-001 | 程式 | R0-2 最小相容修正：未校準 confidence 的產生／呈現，保留既有值；完整雙版本 replay 留待 B2 | 統籌 review 接受；backend 128 passed；既存前端文案測試失敗另記 |
| I-001 | 索引 | 更新上一輪已完成文件；檢查既有分區健康及 README／ROADMAP／STRATEGIES coverage | 已完成 docs refresh 與搜尋；freshness 異常仍保留 |
| I-002 | 索引 | 固定分工文件更新與根 AGENTS.md 覆蓋查驗 | docs 已刷新；root pipeline failed，AGENTS.md 尚無 MCP coverage |
| I-003 | 索引 | D-001 review 後刷新 R0 契約、文件索引與協作紀錄 | 2026-09-11 23:41:27 docs full，208 nodes／207 edges，三檔可搜尋；freshness 異常保留 |
| D-002 | 文件 | 將 C-001 實作、驗收、B2 未完成邊界整合至現行文件 | 統籌已對照實作／測試證據 review 通過 |
| I-004 | 索引 | C-001 review 後更新 app／worker／tests／frontend 分區 | 五區 full／ready；generation 15:51:29～15:51:43Z；統籌已驗證新增 backend test 與前端 helper 可查 |
| I-005 | 索引 | 本批停止檔案寫入後，刷新 D-002 五文件與本協作紀錄 | 最終工具 generation／結果保存在固定索引 task 的 I-005 回覆，避免為回寫索引結果而再改 snapshot |

### D-001 review 紀錄

統籌於 2026-09-11 直接閱讀完整契約並核對修改，要求且確認：legacy 常數判定需匹配已知策略／版本和數值 0.75；純輸出語意可獨立版本化，規則改變才必須新策略版本；需要同日新舊並存時仍須真正隔離 artifact/key；Wilder 為提案，尚未生效。文件小批順序、時間可得性、歷史保留與驗收邊界可作後續實作依據。文件 task 回報本地連結與 Markdown 靜態檢查通過；此 review 未聲稱程式測試、正式 DB revision 或策略有效性已通過。

### C-001 review 紀錄

統籌逐檔對照專案外原檔備份 `C:\Users\YiCheng\Desktop\taiwan-stock-research-C001-original-20260911`，要求修正同 key 重跑保留 legacy 值、嚴格策略／版本／0.75 判斷，以及不信任 evidence marker 的機率旗標或顯示文字。修正後以固定 canonical semantics 輸出；gate、ATR、價位與 cutoff 未改。這是最小語意修正，並未建立新舊 artifact 並存或完整歷史 replay。

- 統籌獨立驗證：bundled Python 3.12.14，`PYTHONPATH=backend;backend/.deps`，`python -m pytest backend/tests -q`，128 passed，4417 deprecation warnings，22.85 秒，exit 0。
- 隔離資料目錄：`C:\Users\YiCheng\AppData\Local\Temp\stock-c001-review-c8a5806917ae49bfa563696f3897d31b`；正式資料庫未操作。
- 程式 task 回報 targeted backend 4 passed、compileall 通過、前端 build 與新增 confidence assertions 通過。
- 統籌另以備份原版及目前版編譯／執行完整 `presentation.test.ts`，二者皆在 `passed pullback result must be shown as established` 失敗（exit 1）。原期待「回踩研究條件：已成立」，實作為「回踩條件：已成立」；此為確認的既存失敗，不能宣稱前端整套測試通過。
- 前端對照產物：`C:\Users\YiCheng\AppData\Local\Temp\stock-c001-frontend-review-c99f472566834ffe8eb062920a03ed17`。新增三項 assertions 先於既存失敗且均通過；未進行瀏覽器視覺驗收。
- 交付時 10 個修改檔 SHA256 與統籌完整 backend 驗證後一致；版本／測試證據在本統籌 task 的工具結果可查。

後續候選批次：釐清並修復既存前端文案測試契約；再依 R0 契約進行 ATR 版本隔離及時間口徑工作。本次未將它們宣稱為完成。

### 索引限制

初始 2026-09-11 23:35:03（Asia/Taipei）的 docs full snapshot 為 ready、184 nodes／183 edges，後續已由 I-003 刷新 D-001；D-002 與本紀錄的最終來源 snapshot 由 I-005 處理。各區 coverage freshness 持續 metadata_changed，故不能宣稱已證明全域最新。根目錄 index_repository 回報 Pipeline failed，原因未確認；AGENTS.md 仍須直接讀取。I-004 以 full 模式納入先前 fast-pattern 排除的 frontend 測試，新測試已可查；不可沿用舊 snapshot 代表後續修改。

先處理 R0-2 的理由：此缺口可以與 ATR／時間版本契約的整理並行，且可隔離驗證。ATR、規則價位與時間口徑仍保留 R0 優先級，本批未授權其大規模實作。

## 統籌驗收與每輪結束（2026-09-13 更新）

1. 以實際修改前後差異對照契約；目前 Git 沒有 HEAD，程式 task 需保留專案外的原檔備份供 review。
2. 核對新／舊 confidence、版本標記、API 與 UI 語意及歷史資料不被覆寫，檢查針對性測試。
3. 有錯誤時退回相同 task 修正，交付不直接算完成。
4. review 通過後，請文件 task 更新 ROADMAP 及對應領域文件，只記錄有證據的能力與限制。
5. 每輪結束前，全部程式／文件 review 且 freeze 後，通知當輪索引 task 統一更新本輪變更涉及的分區，回報索引時間、project/root、coverage 與缺口；根目錄文件亦需納入覆蓋評估。不再安排輪初 baseline 或每段刷新。
6. 索引是該時點的 snapshot；索引後若再修改來源，結案前須補刷受影響分區。尚有缺口就明確記錄，不能宣稱全部已索引。最終索引 receipt 可保存在 task 回覆，避免反覆回寫文件造成刷新循環。
7. 當輪統籌複核並接受後，建立下一輪四個新 task，交付範圍、證據、限制、freeze 及索引結果；新統籌確認接手後負責分派與 review，舊統籌停止派工。

R1～R3 依 ROADMAP 逐段拆解；涉及來源預算、模型方案或個人風險參數的未決事項另行取得必要資訊。
