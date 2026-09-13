# Caller-provided pure-rule replay 契約

更新：2026-09-13。狀態：**已 review（Round33 C033-B 有限 current pure-rule library）**。

本文件是 `backend/app/rule_replay.py` 的 API、資料格式、binding、錯誤與限制權威。這個 library 能在本契約有限的 native JSON 輸入域內，完整保存兩個現行規則 evaluator 所接受的 caller arguments，並在固定的本地 source／config／runtime 下重新計算 `passed`、`state` 與 ordered `reasons`。它不讀歷史資料、signal artifact、worker 或正式 DB，也不證明 caller inputs 的來源、subject、市場時間、可得性或 point-in-time 正確性。

## 1. 能做與不能做的事

支援的 evaluator 只有：

- `breakout_v1`，strategy version `1.0.0`；
- `pullback_v1`，strategy version `1.0.0`。

一次成功 capture 會保存完整 admitted arguments、完整 selected strategy config、implementation identity、原始規則結果，以及三個用途不同的 SHA-256 digest。一次 replay 會在新的私有 module 中執行相同 evaluator，並比較 recorded／replayed result 是否完全相同。

這個有限能力不是下列任何一項：

- 歷史輸入找回、來源證明、簽章、authentication 或 code signing；
- instrument／subject identity、`market_date`、`decision_at` 或 `as_of_at` 證據；
- official availability、revision、PIT、完整 signal reconstruction 或 paired legacy/new replay；
- `SignalArtifactStore`、`signal-comparison/v1`、worker、API、UI、`DecisionSummary` 或預設版本接線；
- hostile Python interpreter／OS／stdlib／filesystem／registry 的隔離 sandbox。

因此，只要 caller 提供本契約內結構合法的完整參數，這個 API 就能回答「在目前明確綁定的 evaluator bytes/config/runtime 下，規則結果是否仍與 bundle 中的 claim 相同」。參數是否源自可信資料、是否在歷史決策時已可得，仍須由 caller 另行證明。

## 2. Public API 與可執行範例

Public exports：

```python
from app.rule_replay import (
    RuleReplayBindingError,
    RuleReplayContractError,
    RuleReplayExecutionError,
    capture_rule_inputs,
    replay_rule_inputs,
    rule_replay_json,
)
```

- `capture_rule_inputs(*, evaluator: str, arguments: dict) -> dict`：strict 驗證、以 fresh private module 評估一次，回傳 detached sealed bundle。
- `rule_replay_json(bundle: dict | str) -> str`：strict 驗證 bundle 與本機 binding，回傳 canonical JSON。它**不呼叫 evaluator**，但會讀取、compile／exec 固定 source，才能核對完整 config binding。
- `replay_rule_inputs(bundle: dict | str) -> dict`：strict 驗證後，以 fresh private module 評估一次並回傳 detached report。

在專案根目錄，以 CPython 3.12.14 且 `PYTHONPATH` 包含 `<repo>/backend` 的環境可執行：

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from app.rule_replay import capture_rule_inputs, replay_rule_inputs, rule_replay_json

arguments = {
    "close": 101.0,
    "volume": 120.0,
    "prior_volumes": [100.0] * 20,
    "prior_highs": [100.0] * 20,
    "group_excess_return_20d": 0.01,
    "institutional_flow_to_turnover_ratio_5d": -0.003,
    "margin_balance_change_ratio_5d": 0.05,
}

bundle = capture_rule_inputs(evaluator="breakout_v1", arguments=arguments)
canonical_text = rule_replay_json(bundle)

# Persistence is caller-owned. This example writes only to an external temporary path.
with TemporaryDirectory(prefix="rule-replay-") as temporary_directory:
    bundle_path = Path(temporary_directory) / "bundle.json"
    bundle_path.write_text(canonical_text, encoding="utf-8")
    report = replay_rule_inputs(bundle_path.read_text(encoding="utf-8"))

assert report["exact_match"] is True
assert report["recorded_result"] == report["replayed_result"]
assert report["input_source_mode"] == "caller_provided_only"
```

API 不接收 source path、DB path 或 implicit latest selector；source selection 完全由 library 的 fixed registry 決定。

## 3. Arguments contract

兩個 evaluator 的 key set 都是 exact；缺 key 或多 key 都以 `argument_keys` 拒絕。數值可為 exact built-in `int`／`float` 或 `null`；`bool`、numeric subclass、numeric string 與自訂 mapping/list 不會被當成原生數值或容器。

| Evaluator | Exact arguments |
| --- | --- |
| `breakout_v1` | `close`, `volume`, `prior_volumes`, `prior_highs`, `group_excess_return_20d`, `institutional_flow_to_turnover_ratio_5d`, `margin_balance_change_ratio_5d` |
| `pullback_v1` | `close`, `volume`, `prior_volumes`, `bar_count`, `ma20`, `ma60`, `group_excess_return_20d`, `institutional_flow_to_turnover_ratio_5d`, `margin_balance_change_ratio_5d` |

`prior_volumes`／`prior_highs` 只能是 `null` 或 exact built-in list；每個 element 只能是原生 `int`／`float`／`null`。Evaluator 只使用 trailing 20 items；caller 若傳更長 list，前面的 prefix 仍會完整保存在 bundle，且會影響 `arguments_digest`，不會先裁掉。`bar_count` 只能是原生 `int`／`null`；它仍受通用整數範圍限制。

`null`、空 history、短 history 與完整 history 是不同 canonical inputs；規則如何回傳 `data_incomplete`／`rejected`／`passed` 仍由固定 evaluator 決定。輸入必須 finite，但 finite inputs 在 evaluator 中造成 intermediate floating-point infinity 時，保留現行 v1 行為，不另改公式或結果。

## 4. `rule-replay-bundle/v1`

Bundle 頂層只能有下列十個 exact keys：

```json
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
```

上例的空 `config_snapshot`／`arguments` 只展示欄位位置，不是合法的完整 `breakout_v1` bundle；可用 `capture_rule_inputs` 產生合法範例，但讀端不證明 bundle 一定由該函式建立。

`recorded_result` 只有 exact keys `passed`、`state`、`reasons`：

- `passed` 是原生 boolean；
- `state` 只能是 `passed`、`rejected`、`data_incomplete`；
- `reasons` 是 ordered non-empty strings list；`passed` 時必須為空，另外兩個 state 必須非空；
- reason string 的 vocabulary 不在本契約中另設 allowlist，不能把 shape validation 說成所有 reason code 已封閉列舉。

## 5. Canonical JSON 與 digest identity

Canonical JSON 使用 `sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False`、`allow_nan=False`。Native mapping 先經 strict prewalk，再透過 canonical encode/decode 形成 detached transfer snapshot。回傳值仍是 mutable dict，不是 deep-immutable object：修改原 input 不影響已產生的 bundle；修改某次回傳不影響其他 detached 回傳物件或後續另行執行，但直接修改手上的 bundle 本身當然會改變其內容，且未一致重算時會破壞 seal。

Digest 定義：

```text
arguments_digest = SHA-256(canonical JSON of {evaluator, arguments})
config_digest    = SHA-256(canonical JSON of config_snapshot)
bundle_digest    = SHA-256(canonical JSON of every bundle field except bundle_digest)
```

所有 digest 欄位都以 `sha256:` 加 64 個 lowercase hex 表示。`arguments_digest` 只識別 evaluator＋caller arguments；它不含 instrument、market time、source availability 或完整 signal artifact，因此**不是 historical input snapshot hash**。`bundle_digest` 才同時覆蓋 implementation/config binding、arguments identity 與 recorded-result claim。

這些 digest 是 deterministic content identity／integrity check，不是簽章或 authentication。若 caller 修改 `recorded_result` 並一致重算外層 digest，資料可通過 shape/integrity；replay 仍會重新計算，只有該 claim 與實算結果不同時才得到 `exact_match=false`。Bundle 內的 recorded result 始終是一項 caller-carried claim。

## 6. Source、config 與 runtime binding

本版本固定：

| 項目 | Frozen value |
| --- | --- |
| Source path policy | library sibling `backend/app/domain.py`；caller 不可選 path |
| 完整 source bytes SHA-256 | `db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028` |
| `breakout_v1` 完整 config digest | `sha256:a68f4f98f319e387e4de71c37e4fc16c225b4406c20a189f7bfdc1515e84b7cd` |
| `pullback_v1` 完整 config digest | `sha256:03998a93820a3c132110d41e2496f5a94a8a7f556774cb80be23e549d4788eff` |
| Runtime | CPython `3.12.14` |
| Float model | radix 2、mantissa 53 bits、`max_exp=1024` |

每次 capture／serialize／replay 都在完成 caller 結構／identity 檢查後、讀 fixed source 前驗 runtime；接著對 fixed path 讀取最多 1 MiB 加一個 overflow sentinel，核對 hash，compile／exec **同一批已驗 bytes** 到 UUID-named fresh private module，再核對兩個完整 config digests。它不使用 shared `app.domain` config/callable 或 cached `.pyc`。

Private module 只在執行期間註冊，正常與 exception path 都以 identity guard 移除自己註冊的 object。若 hostile host 把該名稱替換為 unrelated object，implementation 不會刪除別人的 object；host/interpreter/registry manipulation 原本就不在保證內。Whole-file binding 是保守政策：即使 `domain.py` 的其他區域變更，舊 bundle 也可能因 source hash 不同而不再受支援。

## 7. `rule-replay-report/v1`

成功 replay 的 report exact fields 包含：

- identity：`schema_version=rule-replay-report/v1`、`scope=pure_rule_only`、`input_source_mode=caller_provided_only`、`bundle_digest`、`arguments_digest`；
- local binding：`implementation`、`config_digest`、`local_source_binding_verified=true`；
- result：`recorded_result`、`replayed_result`、`exact_match`；
- 六個必為 false 的非宣稱旗標：`historical_inputs_verified`、`subject_identity_present`、`market_time_present`、`availability_verified`、`pit_verified`、`signal_reconstructed`。

`exact_match` 只比較兩個 result object 的 `passed`、`state` 與 ordered `reasons`。它不表示價格、來源、時間、instrument、artifact linkage 或其他 signal 欄位相同。

## 8. Strict JSON 與資源上限

| 限制 | 行為 |
| --- | --- |
| Raw JSON UTF-8 | 最多 1,048,576 bytes；字元數也先做同量級拒絕 |
| Canonical JSON UTF-8 | 最多 1,048,576 bytes |
| Container depth | 最多 16 層，root container 算第 1 層 |
| History length | 每個 history 最多 10,000 elements |
| Integer | `-(2^53-1)` 到 `2^53-1`，含端點 |
| Float | input 必須 finite；JSON `NaN`／`Infinity`／overflow exponent 拒絕 |
| Keys／containers | 只接受原生 string keys 與原生 dict/list；cycle、surrogate Unicode、duplicate JSON keys 拒絕 |

Raw JSON 的 depth check 在標準 parser 建出 value 後進行；1 MiB raw cap 仍提供有限界線，parser recursion error 會轉成 contract error。本 API 不是通用 untrusted-host sandbox。

## 9. Error families

所有 caller 應先按 exception family 處理，再使用穩定的 `.code`；不要依賴 exception message。Execution error 另提供 nullable `.exception_type`，只保存底層 exception 類名。

| Family | 意義 | Stable codes |
| --- | --- | --- |
| `RuleReplayContractError` (`ValueError`) | Caller data／JSON／shape／digest 自洽性錯誤 | `json_depth_limit`, `json_cycle`, `json_size_limit`, `json_key_type`, `invalid_unicode`, `integer_out_of_range`, `nonfinite_number`, `json_native_type_required`, `json_encoding_error`, `duplicate_json_key`, `invalid_json`, `native_dict_required`, `unsupported_evaluator`, `argument_keys`, `history_type`, `history_length_limit`, `history_element_type`, `bar_count_type`, `argument_number_type`, `result_keys`, `result_passed_type`, `result_state`, `result_reasons`, `result_coherence`, `bundle_keys`, `unsupported_schema_version`, `implementation_keys`, `runtime_keys`, `invalid_digest`, `config_snapshot_type`, `config_digest_mismatch`, `arguments_digest_mismatch`, `bundle_digest_mismatch` |
| `RuleReplayBindingError` (`RuntimeError`) | 這個 bundle 不符合受支援的本地 strategy/source/config/runtime binding | `unsupported_strategy_version`, `unsupported_implementation_binding`, `unsupported_config_binding`, `unsupported_local_runtime`, `local_source_unreadable`, `local_source_size_limit`, `local_source_hash_mismatch`, `local_config_digest_mismatch`, `local_implementation_load_failed` |
| `RuleReplayExecutionError` (`RuntimeError`) | 已選 implementation 在載入或 evaluator 執行時失敗，不虛構 rule state | `implementation_execution_failed`, `evaluator_failed` |

## 10. Round33 final review 證據與完成邊界

Frozen source：

- `backend/app/rule_replay.py` SHA-256 `1f0e7dbd535bd4818e56eccfd08cd919e2e2bc4ce72bb64c352c22cec5e9602c`；
- `backend/tests/test_rule_replay.py` SHA-256 `2127c1d1d255f0773709f129a89742b19e4732de8085102179bf186770727cac`；
- bound `backend/app/domain.py` SHA-256 `db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028`，本輪未修改。

分開的 final runs，不相加：

- C033 author targeted：151 passed，實際為 141 個 new replay tests 加 10 個既有 non-parameterized domain tests；pytest 2.38 秒、process 2.925512899993919 秒、exit 0，165 guards unchanged。早期 `139+12` 是作者訊息的拆分錯誤，不作 final 數字。
- C033 author full：2405 passed、2 skipped、12414 warnings；pytest 355.05 秒、process 357.94884170001023 秒、exit 0，165 guards unchanged。Skipped cases 不算 passed；本輪未另要求 `-rs`。
- 統籌 caller-contract matrix：82／82，exit 0；binding/fault/concurrency/audit matrix：25／25，含 12 次一般並行 capture，exit 0。
- D035 只做 source review 與小型 edge probe，沒有重跑作者 suites／統籌 matrices；修正兩次 D035 harness expectation 後，第三次 probe exit 0 且 source 未變。D035 最終 review 結論為 no in-scope blocker。

前置可行性只作調查、不加進 pytest 計數：統籌有 37 個 original-evaluator assertions＋3 次 private-load prototype，D035 Phase A 有 14 個 observations＋3 次 private load；共同結論是 mutable legacy evidence/refs 不足以證明完整歷史輸入或 executed code。D035 Phase A 第一個 pure probe 的 config alias restore 失敗後才修正，統籌第一次核對 D035-A manifest 也因把 `artifact_files` 誤讀為 `files` 而 `KeyError`，之後才驗完 8 rows。

其餘保留的 failure／deviation history 包含：統籌第一個 binding matrix 因同名 helper shadow module 而 24 pass／1 harness error，修正 harness 後 25／25；D035 Phase B edge probe 01 使用錯誤 report keys、02 使用錯誤 expected error codes，03 才是 passing run；codebase-memory App 後期回 `Transport closed`，依專案規則改用同引擎 CLI coverage fallback，未重啟服務、啟動永久 daemon 或修改全域設定。CLI 仍會輸出 temporary-engine startup／raw-JSON deprecation 診斷；這不是 index 或永久 daemon。上述 failure 沒有被 final success 改寫成 passing product runs。

本批只新增 pure library 與 tests，不修改既有 evaluator、schema、store、migration、worker、API、UI、預設版本或正式／`.local` DB。它使「caller-provided current pure-rule complete-argument capture/replay」這個有限機械能力成為已 review；R0-B2 的完整保存歷史輸入、SignalArtifact bridge／persistence、same-subject/time legacy-v2 paired replay、API／UI／DecisionSummary、worker、官方 availability／PIT，以及 B7/default adoption 全部仍未完成。相關整體邊界見 [Signal artifact 契約](SIGNAL_ARTIFACTS.md)、[R0 實作契約](R0_IMPLEMENTATION.md)、[ROADMAP](ROADMAP.md) 與 [執行清單](ROADMAP_EXECUTION.md)。
