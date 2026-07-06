# Review: spec-4 Adapter 契約（DataSource / BrokerBranchSource / CaptchaSolver ABC）

- 對抗式 reviewer，full depth。
- 審查對象：`backend/app/adapters/__init__.py`、`base.py`、`registry.py`（皆為 worktree 未提交新檔）。
- 忠實度基準：`orchestrator/requirement.md`、`docs/design.md §2/§3/§11`、intake spec-4/6/7/8/9。

## Verdict: **pass**

介面撐得住下游四個 adapter，registry 採裝飾器自註冊＋掃描觸發、機制正確，outputs 未越界。發現的問題皆為非阻斷的風險/毛邊（下記），不足以退回重做，也未歸咎上游 intake。

## 逐項 upgrade_triggers 檢查

| trigger | 結果 | 依據 |
|---|---|---|
| 介面無法涵蓋任一 adapter 需求（日價量/籌碼/券商分點/除權息-股本-基本資料） | **未命中** | spec-6/7/9 只需 `fetch`+`parse` 的一般 `DataSource`，已實測可實作；「同一 adapter 多個 parse 函式」（兩市場/三類籌碼/三套頁面）由 ABC 之外的額外方法表達，ABC 是最小契約、不禁止額外方法——實測 `parse_twse`/`parse_otc` 併存可用。spec-8 需要的 `BrokerBranchSource`＋注入式 `CaptchaSolver` 齊備、實測可實作。 |
| BrokerBranchSource 未能讓來源可換（FinMind 版整段替換不動下游） | **未命中** | 下游消費面是 `fetch`/`parse`，換 FinMind 子類別後此二者不變。實測寫了一個不需驗證碼的 `FinMindBroker` 子類別可正常建構與 parse。見風險 R1（建構子毛邊，非阻斷）。 |
| registry 改用手動清單而非 `@register`＋`discover()` 掃描 | **未命中** | `registry.py` 用 `@register` 裝飾器（裸用/具名兩式）＋`discover()` 以 `pkgutil.iter_modules`＋`importlib.import_module` 掃 `app.adapters` 套件觸發自註冊；`__init__.py` 特意不 import 任何具體 adapter。無任何手寫來源清單。 |
| `discover()` 掃不到已註冊 adapter | **未命中** | 實測：在套件內臨時放一個新模組 `_zz_probe_source.py`（帶 `@register("zz_probe")`），`discover()` 前 registry 無該來源，`discover()` 後即出現——確認掃描真的 import 新模組並觸發其 `@register`。 |
| outputs 越界 | **未命中** | `backend/app/adapters/` 僅有 `__init__.py`、`base.py`、`registry.py` 三檔，正是 allowed_outputs；未觸及任何 forbid_outputs（具體 adapter / models / notifications / 測試檔）。 |
| 下游實作時發現契約不足 | **未命中（含毛邊）** | 見風險 R1–R3；均可在不改本契約的前提下被下游吸收，非「契約不足以實作」。 |

## 我自己重跑的驗證（未照抄 worker 腳本）

腳本：`scratchpad/rv_spec4.py`，以 worktree 內 `backend/venv` 執行，結果 **10/11 為預期通過，1 項為刻意的觀察探針**：

- PASS `DataSource` / `CaptchaSolver` ABC 皆無法直接實體化。
- PASS 只實作 `fetch`、缺 `parse` 的子類別仍為抽象、無法實體化（確認兩個抽象方法都強制）。
- PASS 一般 `DataSource` 子類別可實作，且可在 ABC 之外並存多個 market-specific parse 函式（對應 spec-6/7/9 的「同一 adapter 多 parse」）。
- PASS `BrokerBranchSource` 子類別：建構子注入 `CaptchaSolver`、`isinstance(_, DataSource)` 為真、`fetch` 內可呼叫 `self.captcha_solver.solve(...)`。
- PASS FinMind 風格（不需驗證碼）子類別可建構、`parse` 可用。
- PASS `@register` 裸用以 `cls.__name__`、具名以字串註冊；對非 `DataSource` 拋 `TypeError`；同名重複註冊不同類別拋 `ValueError`。
- PASS `discover()` 對現有（尚無具體 adapter 的）套件不崩、回傳已註冊集合。
- PASS `discover()` 真的 import 新增模組以觸發其 `@register`（核心機制成立）。
- 觀察探針（非阻斷）：`discover()` 在某一 adapter 模組 import 時拋例外的情況下，**整個 discover() 連帶中止**（見風險 R4）。
- info：`DataSource.fetch` 簽名為 `(target, date)`、只吃單日（見風險 R2）。

## 風險點（皆非阻斷，供下游/往後注意）

- **R1（med-low，BrokerBranchSource 建構子毛邊）**：`BrokerBranchSource.__init__(self, captcha_solver: CaptchaSolver)` 把「驗證碼求解器」設為**必填位置參數**，但驗證碼是自爬版專屬、FinMind 付費版根本不需要。這把自爬專屬概念焊進了「可替換來源」的抽象基底。實測 FinMind 子類別仍可用（覆寫 `__init__`、`super().__init__(None)`），且下游資料契約（fetch/parse）不受影響、建構/wiring 本就依來源而異，故「換來源不動下游」不破。但若日後想在契約層更乾淨，宜把 solver 改為可選（`CaptchaSolver | None = None`）或移出基底建構子。
- **R2（low，fetch 簽名硬編單日）**：`fetch(target, date: dt.date)` 只表達單日抓取，spec-6 日價量需要「date range 十年回補」。範圍抓取需 spec-6 在自己 adapter 內另加方法（如 `fetch_range`），落在 ABC 契約之外。ABC 為最小契約可接受，但請 spec-6 worker 知悉範圍路徑非契約保證。
- **R3（low，NormalizedRow 無約束）**：`NormalizedRow = dict[str, Any]`，契約層不對欄位形狀作任何保證。對「來源中立的契約層」是合理取捨（各源形狀天差地遠、真 schema 在 `app.models`），代價是 parse 產出與 pipeline/DB 寫入的欄位對應延到 spec-11 逐源在執行期驗。可接受。
- **R4（med，但屬 spec-11 職責）**：`discover()` 逐一 import 套件內每個模組，**任一模組 import 期拋例外會使整個 discover() 中止**、連帶掃不到其他健康來源。考量 design §11「分點爬蟲維運熱點」與 §3「錯過一天即永久缺洞」，某一 adapter（例如 `broker_branch.py` import 期載入 ddddocr/onnx 失敗）掛掉不該連累其餘來源被發現。非 spec-4 的 upgrade_trigger、且「fail loud」也是一種立場，故不阻斷；但建議 spec-11 決定是否對 per-module import 失敗做隔離（try/except 逐模組）。
- **R5（low，_INFRASTRUCTURE_MODULES 白名單）**：worker 自點的風險。denylist `{"base","registry"}` 只是省去無謂 import；真正的事實來源是 `@register`（非來源模組不會註冊）。故白名單本身不脆弱；唯一連動是若日後在 `adapters/` 放會 import 出錯的非來源 helper，會撞上 R4。低風險。

## 結論

契約設計正確、機制實測成立、邊界乾淨，pass。R1/R4 建議記入下游注意事項（R1 給日後 FinMind 接手者、R4 給 spec-11），但都無須在本 spec 退回重做。

```json
{ "verdict": "pass" }
```
