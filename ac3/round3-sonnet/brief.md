# 新聞 AI 判讀的獨立判讀（stock-lab #262 AC-3）

你是獨立判讀者。只讀下列兩個檔案，不讀 repo 其他檔案、不讀 GitHub、不執行程式、不改任何檔案，只寫一個輸出檔。

- 輸入：`.local/ac/review3/judge_input.json`（30 則）。每則有 `source`（模型拿到的全部原文：`title`、`summary`、`source_name`、`published_at`）與 `ai`（模型輸出：`summary`、`symbol_candidates`（`name` 是代號在股票主檔的名稱，null 表示主檔查不到）、`theme_candidates`、`impact_direction`、`impact_scope`、`impact_rationale`、`unsupported`）。
- 原文就是 `source.title` 與 `source.summary`；模型沒有看到其他內容，所以原文沒有的事實都算原文沒有。

## 判準（照 verify-stock-lab features `news.md` 的 N7、N8 原文）

- **N7 AI 摘要忠於原文**：每則 `ai.summary` 的主體、數字、時間與事件都能在 `title`／`summary` 找到，沒有原文沒有的事實或結論；原文只有標題、無從核對的那則記無法判定。一則不符即失敗，證據寫 id、摘要原句與原文。特別注意：不同主體的事實不能接在一起（例如原文把甲的成果寫在甲身上，摘要不能移到乙）。
- **N8 AI 方向與關聯有原文依據**：每則 `ai.impact_direction` 與 `ai.impact_rationale` 能由原文推得（`ai.unsupported` 為 true 時方向應是 `unknown`）；`ai.symbol_candidates`、`ai.theme_candidates` 的每一項在原文有提及或可直接推得。一則不符即失敗，證據寫 id、AI 的方向或候選與原文。

只寫「漏寫原文某件事」不算不符；寫了原文沒有的、或把事實接錯主體才算。

## 輸出

寫 `.local/ac/review3/verdict.md`（UTF-8），內容：

1. 開頭兩行：`N7：通過／失敗（不符 X 則、無法判定 Y 則）`、`N8：通過／失敗（不符 X 則）`。
2. 一張表，30 則每則一列：`id`｜N7（符合／不符／無法判定）｜N8（符合／不符）｜理由（不符時寫摘要或候選原句與對應原文；符合寫一句依據）。
3. 結尾一行寫你的模型名稱。

寫完就停，不做其他事。
