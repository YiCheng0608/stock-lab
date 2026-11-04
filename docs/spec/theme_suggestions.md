<!-- owns: 新聞題材建議彙整 -->
# 新聞題材建議

新聞 AI 判讀（[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)）的 `theme_candidates` 彙整成題材建議。建議是 LLM 推論（畫面標「AI 推論」，不寫「待核實」，[UI_COPY_SPEC §8.6](../UI_COPY_SPEC.md#86-新聞題材建議)）：不計分、不排名、不寫 `theme_groups`／`group_memberships`／題材表，也不作為候選或行動的理由；人工核實與納入流程見[題材表](../INDUSTRY_CLASSIFICATION.md#7-題材表)。實作在 `backend/worker/theme_suggestions.py`，彙整規則版本 `theme_suggestions_v2`（`app.theme_suggestions.AGGREGATION_VERSION`；[#413](https://github.com/YiCheng0608/stock-lab/issues/413) 起只取目前提示版本，`theme_suggestions_v1` 取所有提示版本），規則改變要升版。

- **來源**：`news_llm_results` 中目前提示版本（`worker.news_llm.PROMPT_VERSION`）、`llm_status=done` 且 `ai_unsupported` 不為 true 的列，對應的 `news_items.status=active`；`pending`、`skipped_stale`、`rejected` 與資訊不足（unsupported）的判讀不取。只有目前版本的題材候選通過[題材核對](../NEWS_SPEC.md#5-ai-摘要與推論)（沒通過的不寫進結果，所以不進建議），舊版本的結果也不在任何頁面顯示；提示升版後，舊版本的建議在下一次彙整時刪除。
- **合併**：以題材名的 NFKC 正規化、去除所有空白、casefold 後的字串為鍵（`theme_key`），例如「AI 伺服器」「AI伺服器」「ＡＩ 伺服器」同一鍵；不做同義詞或模糊比對。列以提示版本 × 鍵區分。同一則新聞重複提同一鍵只算一次，保留第一個寫法與理由。
- **欄位**（`theme_suggestions`，每個提示版本 × 鍵一列）：`display_name` 取該鍵出現最多的原始寫法（同票取新聞日最早者）；`news_count` 為不重複新聞則數；`first_news_date`／`last_news_date` 為新聞台北日期（`published_at`，缺則 `collected_at`）；`llm_models_json` 為參與判讀的模型去重清單；`prompt_version`、`aggregation_version`；`matched_group_id`：鍵與 active 的題材表題材或官方產業的 `display_name_zh`／`name` 鍵完全相同時記該群組（題材優先），代表不是新題材；`status` 固定 `pending_verification`；`computed_at` 為內容最後變動時間（UTC）。`theme_suggestion_news` 每個建議 × 新聞一列，記 `news_llm_result_id`、模型的題材寫法 `theme_text`、理由 `reason` 與新聞日期。
- **模型把握**：`news_v1`～`news_v3` 的題材候選沒有把握欄位，建議不帶把握值，API 回 `confidence=not_provided`；不挪用個股候選的把握。
- **冪等**：每次由全部來源列重算，只寫有差異的列；內容不變不改 `computed_at`。來源不再出現的鍵與連結刪除（例如判讀改為 unsupported 或新聞失效）。
- **執行**：`daily` 最後一步 `theme_suggestions`（collect 成功即跑，不依賴 analyze），或 `python -m worker.cli theme-suggestions`（[現有 worker CLI](../ops/CLI.md#現有-worker-cli)）。
- **API**：`GET /api/theme-suggestions?limit=&include_matched=`（`limit` 1～50，預設 20）依 `news_count` 由多到少、`last_news_date` 由新到舊排序；預設只列 `matched_group_id` 為空者，`include_matched=true` 才含與既有族群同名者（附 `matched_group`）。每項有 `status`、`inference=true`、則數、首末日期、`confidence`、版本欄位與最近 5 則關聯新聞（標題、來源、日期、題材寫法、理由）；`meta` 有 `total`、`matched_total` 與 `updated_at`。`GET /api/theme-suggestions/{id}` 回傳單一建議與全部關聯新聞。文案見 [UI_COPY_SPEC §8.6](../UI_COPY_SPEC.md#86-新聞題材建議)。
