# Caller-provided pure-rule replay 契約

更新：2026-09-14。`backend/app/rule_replay.py` 的有限 current pure-rule library 已 review；Round34 的 opt-in [worker analysis capture](WORKER_ANALYSIS_CAPTURE.md) 是明確 caller。本文是 API、格式、binding、錯誤與限制的權威。

Library 只在 strict native JSON 輸入域內保存兩個 evaluator 的 caller arguments，並以固定 source／config／runtime 重算 `passed`、`state` 與 ordered `reasons`。它不讀歷史資料、SignalArtifact、worker 或正式 DB，也不證明來源、subject、market time、availability 或 PIT。

## 1. 能做與不能做的事

只支援 `breakout_v1@1.0.0` 與 `pullback_v1@1.0.0`。成功 capture 保存完整 arguments、selected config、implementation identity、規則結果與三個 SHA-256 digest；replay 在 fresh private module 執行相同 evaluator 並 exact 比較結果。

不保證：歷史輸入找回、來源／簽章／authentication、instrument identity、market／decision／as-of time、官方 availability／revision／PIT、完整 signal reconstruction、legacy/new paired replay、SignalArtifact persistence、worker／API／UI 接線或 hostile host sandbox。它只回答「caller 提供的合法參數，在本機受 pin 的 evaluator bytes/config/runtime 下是否重現 bundle claim」。

## 2. Public API

~~~python
from app.rule_replay import (
    RuleReplayBindingError,
    RuleReplayContractError,
    RuleReplayExecutionError,
    capture_rule_inputs,
    replay_rule_inputs,
    rule_replay_json,
)
~~~

- `capture_rule_inputs(*, evaluator: str, arguments: dict) -> dict`：strict 驗證，以 fresh private module 評估一次，回 detached sealed bundle。
- `rule_replay_json(bundle: dict | str) -> str`：驗 bundle 與本機 binding，回 canonical JSON；不呼叫 evaluator，但會 compile／exec 固定 source 核對 config。
- `replay_rule_inputs(bundle: dict | str) -> dict`：strict 驗證、fresh private evaluation，回 detached report。

API 不接受 source／DB path 或 implicit latest；persistence 由 caller 管理。執行環境為 repository 的 backend import path 與第 6 節固定 runtime。

## 3. Arguments contract

兩個 evaluator 的 key set 必須 exact；缺 key、多 key或錯型別以 `argument_keys` 等 code 拒絕。數值只接受 exact built-in `int`／`float`／`null`，不接受 bool、numeric subclass 或 string。

| Evaluator | Exact arguments |
| --- | --- |
| `breakout_v1` | `close`, `volume`, `prior_volumes`, `prior_highs`, `group_excess_return_20d`, `institutional_flow_to_turnover_ratio_5d`, `margin_balance_change_ratio_5d` |
| `pullback_v1` | `close`, `volume`, `prior_volumes`, `bar_count`, `ma20`, `ma60`, `group_excess_return_20d`, `institutional_flow_to_turnover_ratio_5d`, `margin_balance_change_ratio_5d` |

History 只接受 null 或原生 list；元素只可為原生 int／float／null，最多 10,000 筆。Evaluator 只使用 trailing 20，但 caller 的完整 prefix 仍保存且影響 digest。`bar_count` 只接受原生 int／null。null、空、短、完整 history 是不同輸入；規則結果由固定 evaluator 決定。輸入須 finite；由 finite input 產生的中間 floating-point infinity 沿用 v1 行為。

## 4. `rule-replay-bundle/v1`

Bundle 只有十個頂層 key：

~~~json
{
  "schema_version": "rule-replay-bundle/v1",
  "evaluator": "breakout_v1",
  "strategy_version": "1.0.0",
  "implementation": {
    "id": "domain-rules/v1",
    "source_sha256": "sha256:db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028",
    "runtime": {"implementation": "cpython", "version": "3.12.14"}
  },
  "config_snapshot": {},
  "config_digest": "sha256:<64 lowercase hex>",
  "arguments": {},
  "arguments_digest": "sha256:<64 lowercase hex>",
  "recorded_result": {"passed": true, "state": "passed", "reasons": []},
  "bundle_digest": "sha256:<64 lowercase hex>"
}
~~~

空 config／arguments 只示意位置，不是合法 bundle。`recorded_result` 只含 `passed`（原生 bool）、`state`（passed／rejected／data_incomplete）與 ordered nonempty-string `reasons`。passed 時 reasons 必須空；其他 state 必須非空。Reason vocabulary 不由本契約封閉列舉。

## 5. Canonical JSON 與 digest identity

Canonical JSON 使用 `sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False`、`allow_nan=False`；strict prewalk 後 encode/decode 形成 detached snapshot。回傳 dict 可修改，但修改 caller 原 input 或另一次回傳不影響已產生 bundle／後續操作。

~~~text
arguments_digest = SHA-256(canonical JSON of {evaluator, arguments})
config_digest    = SHA-256(canonical JSON of config_snapshot)
bundle_digest    = SHA-256(canonical JSON of every bundle field except bundle_digest)
~~~

Digest 格式為 `sha256:` 加 64 lowercase hex。arguments digest 不含 subject、market time、availability 或完整 artifact；bundle digest 覆蓋 binding、arguments 與 recorded claim。它們是 deterministic identity／integrity，不是簽章。Caller 可改 claim 並重算 digest；replay 仍只以實算結果判定 exact match。

## 6. Source、config 與 runtime binding

| 項目 | Frozen value |
| --- | --- |
| Source path | library sibling `backend/app/domain.py`；caller 不可選 |
| Source SHA-256 | `db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028` |
| breakout config digest | `sha256:a68f4f98f319e387e4de71c37e4fc16c225b4406c20a189f7bfdc1515e84b7cd` |
| pullback config digest | `sha256:03998a93820a3c132110d41e2496f5a94a8a7f556774cb80be23e549d4788eff` |
| Runtime | CPython `3.12.14`；binary64 radix 2、mantissa 53、max_exp 1024 |

每次 capture／serialize／replay 先驗 caller shape 與 identity，再驗 runtime；fixed source 最多讀 1 MiB＋overflow sentinel，核 hash 後把同一批 bytes compile／exec 到 UUID-named fresh private module，再核兩個完整 config digests。不使用 shared `app.domain` callable/config 或 cached pyc。

Private module 正常與 exception path 都以 identity guard 移除自己註冊的 object。Host 替換 registry object、interpreter 或 filesystem 的惡意操控不在保證內。Whole-file binding 也表示 domain.py 的無關區域變更仍可能使舊 bundle unsupported。

## 7. `rule-replay-report/v1`

Report 保存 schema／scope／input mode、bundle 與 arguments digest、implementation／config binding、`local_source_binding_verified=true`、recorded／replayed result 及 `exact_match`。下列宣稱固定為 false：

- `historical_inputs_verified`
- `subject_identity_present`
- `market_time_present`
- `availability_verified`
- `pit_verified`
- `signal_reconstructed`

Exact match 只比較 `passed`、`state` 與 ordered `reasons`，不表示價格、來源、時間、subject 或 artifact linkage 相同。

## 8. Strict JSON 與資源上限

| 限制 | 值／行為 |
| --- | --- |
| Raw／canonical JSON UTF-8 | 各最多 1,048,576 bytes；raw 字元數先作同量級限制 |
| Container depth | 最多 16 層，root 算第 1 層 |
| History | 每個最多 10,000 elements |
| Integer | `-(2^53-1)` 到 `2^53-1`，含端點 |
| Float | input finite；NaN／Infinity／overflow exponent 拒絕 |
| Keys／containers | 原生 string keys 與原生 dict/list；cycle、surrogate Unicode、duplicate JSON key 拒絕 |

Depth check 在標準 parser 建值後執行；parser recursion error 轉為 contract error。此 API 不是通用 untrusted-host sandbox。

## 9. Error families

Caller 應先按 exception class，再按穩定 `.code` 分支；不要解析 message。Execution error 另有 nullable `.exception_type`。

| Family | Stable codes |
| --- | --- |
| `RuleReplayContractError` | `json_depth_limit`, `json_cycle`, `json_size_limit`, `json_key_type`, `invalid_unicode`, `integer_out_of_range`, `nonfinite_number`, `json_native_type_required`, `json_encoding_error`, `duplicate_json_key`, `invalid_json`, `native_dict_required`, `unsupported_evaluator`, `argument_keys`, `history_type`, `history_length_limit`, `history_element_type`, `bar_count_type`, `argument_number_type`, `result_keys`, `result_passed_type`, `result_state`, `result_reasons`, `result_coherence`, `bundle_keys`, `unsupported_schema_version`, `implementation_keys`, `runtime_keys`, `invalid_digest`, `config_snapshot_type`, `config_digest_mismatch`, `arguments_digest_mismatch`, `bundle_digest_mismatch` |
| `RuleReplayBindingError` | `unsupported_strategy_version`, `unsupported_implementation_binding`, `unsupported_config_binding`, `unsupported_local_runtime`, `local_source_unreadable`, `local_source_size_limit`, `local_source_hash_mismatch`, `local_config_digest_mismatch`, `local_implementation_load_failed` |
| `RuleReplayExecutionError` | `implementation_execution_failed`, `evaluator_failed` |

## 10. Round33 final review 證據與完成邊界

Round33 對有限 pure library、binding、fault、concurrency 與 audit contract 完成 review；frozen files 為 `backend/app/rule_replay.py`、`backend/tests/test_rule_replay.py` 與受 pin 的 domain.py。完整歷史命令、測試數、失敗修正與檔案 hash 可查 `git show 69f62cf:docs/RULE_REPLAY.md`。

尚未完成：可證的歷史輸入、SignalArtifact bridge／persistence、同 subject/time 的 legacy-v2 paired replay、API／UI／DecisionSummary、官方 availability／PIT、B7 與 default adoption。相關狀態見 [SIGNAL_ARTIFACTS](SIGNAL_ARTIFACTS.md)、[R0_IMPLEMENTATION](R0_IMPLEMENTATION.md) 及 [ROADMAP](ROADMAP.md)。

## 11. Round34 worker caller：有限 actual/private binding

Round34 未改上述 library 或 pins。Opt-in worker caller 在 shared evaluator 前 detach 實際 kwargs，再以本 library private 重算；shared actual result、private recorded result、實際 StrategyVersion config 與 pinned config 皆用 canonical JSON identity，比較時 `false` 不等於 `0`、`1.0` 不等於 `1`。成功 call 同時保存 actual result 與完整 bundle。

這只證本次 owned research analysis 的 shared arguments 與 pinned replay 綁定，不證 historical availability 或官方 truth，也不建立 SignalArtifact、paired output、B5b／B7、API／UI 或 default capture。操作、schema、outcome 與 error 見 [WORKER_ANALYSIS_CAPTURE](WORKER_ANALYSIS_CAPTURE.md)。
