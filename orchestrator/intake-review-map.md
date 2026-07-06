# Intake 風險 / 成本地圖：stock-lab 第一期 Ingestion Pipeline

intake（spec-1）本身為高槓桿規劃站，由 orchestrator 固定先過 full reviewer，不列於下表。所有下游任務皆 `machine` 可驗，故 review depth 用於「machine test 之上的主觀風險」而非有無裁判。

| task | risk | review_depth | split_reason | upgrade_triggers | reason |
|---|---|---|---|---|---|
| spec-2 | low-med | focused | infra 設定 ownership 獨立、為全體根依賴 | outputs 越界；smoke fail；碰到未預期的 env/port/安全面；last_failure 非空 | 有客觀 boot/compose smoke，但為地基且含 env/port 面，聚焦抽查 diff |
| spec-12 | low | focused | 依賴清單寫入權集中 ownership、補 spec-8/9 平行節點無合法路徑加依賴的缺口 | 增列以外動到 spec-2 已寫的既有依賴/build/metadata 區段（越界）；三套件任一未增列；破壞既有依賴解析致安裝失敗；outputs 越界；last_failure 非空 | 風險與粒度都低、有客觀 machine test，但關鍵風險正是「是否只增列、未擾動 spec-2 已審過的 pyproject 其他內容」，聚焦抽查 diff 邊界即足 |
| spec-3 | high | full | 資料模型地基 ownership 獨立、失敗成本高 | migration 無法套用；分區/索引/雙價欄位/user FK 任一缺；outputs 越界；last_failure 非空 | 分區＋雙價＋user FK＋索引一次到位、下游全依賴，設計錯代價高 |
| spec-4 | med | full | 四 adapter＋排程共同依賴的介面縫（含 FinMind 替換點） | 介面無法涵蓋任一 adapter 需求；BrokerBranchSource 未能讓來源可換；registry 改用手動清單而非 `@register`＋`discover()` 掃描（會與 adapter 脫鉤永遠為空）；`discover()` 掃不到已註冊 adapter；outputs 越界；下游實作時發現契約不足 | design 明列的高槓桿抽象縫，設計缺陷會擴散全下游，需完整審 |
| spec-5 | low | defer-until-signal | 獨立通知模組 ownership、僅排程消費、低風險且有 unit test | Notifier 介面無法容納未來 LINE/email；stub 會拋例外或誤發網路；spec-11/整合測試因通知介面 fail；outputs 越界；last_failure 非空 | 低風險、ownership 清楚、有可靠 unit test，produce 前免審、失敗訊號再升 full |
| spec-6 | med | focused | 獨立 adapter 模組與目標欄位、可平行 | 解析 fixture 測試 fail；只做上市漏上櫃（Q10 定案兩市場）；未用 `@register` 自註冊；碰到多來源端點/金鑰等未預期依賴；outputs 越界；last_failure 非空 | 有解析單元測試，但真實政府格式易誤讀，聚焦抽查解析 diff 與 fixture 代表性（含兩市場） |
| spec-7 | med | focused | 獨立 adapter 模組與目標表、可平行 | 解析 fixture 測試 fail；三類籌碼欄位對應錯或漏做某類；只做上市漏上櫃；未用 `@register` 自註冊；碰到未預期端點/金鑰；outputs 越界；last_failure 非空 | 有解析單元測試，聚焦抽查三類籌碼×兩市場欄位映射正確性 |
| spec-8 | high | full | 全案最高維運風險與最複雜實作（驗證碼/節流/改版/FinMind 縫），風險隔離 | 解析或節流測試 fail；BrokerBranchSource 未能整段替換；節流/驗證碼策略偏離 Q1/Q5 決議；只做上市漏上櫃；universe 誤用不存在的自選股表（應為成交量前 N）；ddddocr 未由 spec-12 就緒致 import 失敗；碰到未預期反爬手段；outputs 越界；last_failure 非空 | design §11 點名維運熱點，驗證碼/節流/未來替換皆高風險，須完整審 |
| spec-9 | med | focused | 獨立 adapter 模組與目標表、與還原計算失敗根因不同 | 解析 fixture 測試 fail；三套頁面（除權息/股本/基本資料）漏做某套；除權息欄位不足以支撐 spec-10 還原計算；只做上市漏上櫃導致 securities 覆蓋不全（下游 FK 插入失敗）；HTML/XML 解析套件未由 spec-12 就緒致 import 失敗；outputs 越界；last_failure 非空 | 有解析單元測試，聚焦確認三套頁面齊備、除權息欄位對 spec-10 的充分性、securities 兩市場覆蓋 |
| spec-10 | high | full | 與除權息抓取（spec-9）失敗根因不同（數學 vs 解析），correctness 熱點 | 數學測試 fail；連乘/除息除權混合情境不符預期；碰模型定義需改（越界）；outputs 越界；last_failure 非空 | design §7 點名除息旺季不還原會假訊號淹沒，還原係數算錯汙染日後全部指標/回測 |
| spec-11 | high | full | 依賴全部下游、承載高風險重試語意，ownership 獨立 | 重試邏輯測試 fail；成功源被重抓或未成功源未重試；未先跑 securities 源致 FK 插入失敗；還原價只算當日新列未整段重算；時區非 Asia/Taipei 或無當日重試截止；失敗未觸發通知；改到 compose（越界）；碰到比預期多的模組；last_failure 非空 | 「每小時重試直到成功」記帳錯誤會造成永久缺洞或重複灌資料，須完整審 |
| test-integration | med-high | focused | 端到端驗收節點，覆蓋跨全部 spec | 整合測試 fail 或無法起 PG（無 docker daemon 見 Q11）；未驗 securities 先落地/FK 順序；覆蓋不足（某表未斷言、重試/通知路徑未驗）；打到外網 | 本身即 e2e 裁判，聚焦審其覆蓋是否足夠且確未依賴外網 |

> 收斂進 manifest `planning.review_map` 時取 `{task, risk, review_depth, split_reason, upgrade_triggers, reason}`。任一 test fail / evidence 不足會由 test 回寫失敗，使重做下一輪升級為 full。`defer-until-signal` 僅用於 spec-5（低風險、ownership 清楚、有可靠 machine test）。
