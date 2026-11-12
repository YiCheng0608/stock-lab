# 11/11 新聞與候選說明的 LLM 判讀缺口（副本唯讀查詢，時間為 UTC）

## ingestion_runs（news_llm、candidate_notes，2026-11-10 08:00 UTC 起）

| id | run_type | status | started_at | error |
| --- | --- | --- | --- | --- |
| 2824 | news_llm | success | 2026-11-10 08:00:24.549330 |  |
| 2832 | news_llm | success | 2026-11-10 10:00:24.098959 |  |
| 2840 | news_llm | success | 2026-11-10 12:00:24.015400 |  |
| 2853 | news_llm | failed | 2026-11-11 14:00:26.017659 | batch 1: rate_limited: You've hit your 5-hour limit · resets 2:40am (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2855 | candidate_notes | failed | 2026-11-11 15:54:42.301335 | batch 1: rate_limited: You've hit your 5-hour limit · resets 2:40am (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2865 | news_llm | failed | 2026-11-11 16:00:26.633228 | batch 1: rate_limited: You've hit your 5-hour limit · resets 2:40am (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2873 | news_llm | failed | 2026-11-11 18:00:23.623894 | batch 1: rate_limited: You've hit your 5-hour limit · resets 2:40am (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2876 | candidate_notes | failed | 2026-11-11 19:49:01.480871 | batch 1: rate_limited: You've hit your 5-hour limit · resets 7:40am (Asia/Taipei); stopped_after_rate_limited: 1 batch(es) skipped |
| 2886 | news_llm | failed | 2026-11-11 20:00:24.311703 | batch 1: rate_limited: You've hit your 5-hour limit · resets 7:40am (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2894 | news_llm | failed | 2026-11-11 22:00:24.533448 | batch 1: rate_limited: You've hit your 5-hour limit · resets 7:40am (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2903 | news_llm | success | 2026-11-12 00:00:25.860666 |  |
| 2912 | news_llm | failed | 2026-11-12 02:00:23.119061 | batch 1: rate_limited: You've hit your 5-hour limit · resets 12:40pm (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2920 | news_llm | failed | 2026-11-12 04:00:24.012468 | batch 1: rate_limited: You've hit your 5-hour limit · resets 12:40pm (Asia/Taipei); stopped_after_rate_limited: 3 batch(es) skipped |
| 2928 | news_llm | success | 2026-11-12 06:00:24.168565 |  |

## 每個台北發布日的新聞與 LLM 結果

| 台北發布日 | 類別 | 新聞數 | 有結果列 | done |
| --- | --- | --- | --- | --- |
| 2026-11-08 | domestic | 96 | 95 | 95 |
| 2026-11-08 | international | 13 | 12 | 12 |
| 2026-11-09 | domestic | 550 | 546 | 542 |
| 2026-11-09 | international | 42 | 41 | 41 |
| 2026-11-10 | domestic | 577 | 283 | 282 |
| 2026-11-10 | international | 72 | 59 | 59 |
| 2026-11-11 | domestic | 170 | 18 | 0 |
| 2026-11-11 | international | 51 | 26 | 0 |
| 2026-11-12 | domestic | 233 | 142 | 86 |
| 2026-11-12 | international | 36 | 32 | 5 |

## candidate_llm_notes

| trading_date | llm_status | 筆數 |
| --- | --- | --- |
| 2026-11-06 | done | 4 |
| 2026-11-09 | done | 11 |
| 2026-11-10 | pending | 5 |
| 2026-11-11 | pending | 5 |
