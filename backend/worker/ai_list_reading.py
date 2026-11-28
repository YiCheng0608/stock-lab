"""The AI list reading: prompt, ``claude -p``, checks and the stored rows (Issue #1145).

The call layer is ``worker.news_llm``'s, as for ``premarket_v1``
(``worker.premarket_reading``): the local Claude Code CLI in headless mode with
the user's subscription login, no API key, no tools, the prompt on stdin in an
empty directory; the model is ``sonnet``.  docs/spec/ai_list.md is the contract.

- **Prompt**: ``prompts/<version>.md`` with the input (``ai_list_input.build``)
  after it in an ``<input>`` block.  The text is pinned by its SHA-256
  (``PROMPTS``) and so is the output schema (``SCHEMA_SHA256``): changing either
  needs a new version.
- **Checks of the whole answer** (``check``, #1142 2/4): the schema (the CLI's
  ``--json-schema`` and ``validate_schema`` here: at most MAX_PICKS, the code
  table, no repeated ``basis``); then the list: only pool stocks, each once, ranks 1..n, an empty
  list with its ``empty_reason``; every ``news:<id>`` in the input and no order
  wording (``premarket_reading.directive_words``).  A schema failure is called
  once more, then ``rejected``; the others are ``rejected`` at once.
- **Checks of each pick's levels** (``check_levels``): not a rejection.  A pick
  whose levels fail keeps its rank, method and reasons and gets no display
  levels (#1142 2/4 Q2-5 A).  The levels are rounded to D's tick first
  (entry low and targets down, stop and entry high up; Q2-3 A), then checked:
  ``level_facts`` present, each price's ``refs[0]`` a price field of the stock,
  its ``atr_multiple`` one of ATR_MULTIPLES and the AI's price within
  max(TOL_TICKS ticks, TOL_PCT) of the base plus the multiple of ``atr14``; the
  rounded prices inside D's limits, in order stop < entry low <= entry high <
  target 1 < target 2, and the reward to risk the program computes at least
  MIN_RISK_REWARD (Q2-4 A).
- **Kept without a rejection** in ``checks_json``: prices in a pick's texts that
  are none of its numbers (``price_mentions``), reasons over 120 characters,
  sector ids not in the input.
- **Rows**: ``ai_list_readings`` gets one row per run; a done one also gets an
  ``ai_list_picks`` row per pick.  Both only added (``store``).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import AiListPick, AiListReading
from app.strategies import levels as lv

from . import sources
from .ai_list_input import FACT_PRICE_FIELDS, PRICE_FIELDS, facts_value
from .news_llm import (
    CALL_TIMEOUT_SECONDS,
    FATAL_REASONS,
    LlmBatchError,
    Runner,
    _usage,
    cli_arguments,
    parse_envelope,
)
from .premarket_input import Snapshot
from .premarket_reading import (
    Outcome,
    RawCapture,
    build_prompt,
    directive_words,
    payload_news_ids,
)
from .price_mentions import price_mentions

PROMPT_VERSION = "ai_list_v1"
PROMPT_DIR = Path(__file__).with_name("prompts")
# Pinned hashes of the prompt texts (LF line endings).
PROMPTS = {
    "ai_list_v1": "e95bb837aefcaa49be8980c99ccba98577f69e385b3939eec98ef8d99195e27a",
}
CHAMPION = "champion"
MODEL = "sonnet"
MAX_ATTEMPTS = 2
RETRY_REASONS = frozenset({"timeout", "invalid_json", "cli_error", "schema"})
RUN_TYPE = "ai_list"
RAW_SOURCE = "ai_list"
RAW_ENDPOINT = f"claude -p --model {MODEL}"
DONE = "done"
FAILED = "failed"
REJECTED = "rejected"
REASON_MAX_CHARS = 120
MAX_PICKS = 10
STANCES = ("bullish", "bearish", "neutral")
CONFIDENCES = ("high", "medium", "low")
DIRECTIONS = ("positive", "negative", "mixed")
# The method code table (#1142 2/4 Q2-2 A).
SETUPS = (
    "breakout",
    "pullback_support",
    "oversold_rebound",
    "theme_momentum",
    "news_catalyst",
    "chip_accumulation",
)
BASIS = ("news", "chips", "technical", "sector", "market")
MARKET_BASIS = ("us", "tx_night", "tx_day", "news", "taiex")
ENTRY_TYPES = ("breakout", "pullback")
VALID_SESSIONS = (1, 5)
# A level is its base plus one of these multiples of atr14 (#1142 2/4).
ATR_MULTIPLES = (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0, 3.0, -3.0)
TOL_TICKS = 2
TOL_PCT = 0.005
MIN_RISK_REWARD = 1.0
# Each level, in the order of the price order check, and how it is rounded.
LEVELS = ("stop", "entry.low", "entry.high", "target_1", "target_2")
ROUND_DOWN = frozenset({"entry.low", "target_1", "target_2"})
# The reasons a whole answer is rejected, in the order they are checked.
LIST_REASONS = (
    "not_in_pool",
    "duplicate_pick",
    "rank_not_contiguous",
    "empty_without_reason",
)
REJECT_REASONS = frozenset(
    {"schema", *LIST_REASONS, "unknown_news_ref", "directive_words"}
)

# --- the output schema ------------------------------------------------------------

_S = {"type": "string"}
_REFS = {"type": "array", "items": _S}


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


_REASON = _obj({"text": _S, "refs": _REFS})
_REASONS = {"type": "array", "items": {"$ref": "#/$defs/reason"}}
_PRICE = {"$ref": "#/$defs/price"}
OUTPUT_SCHEMA: dict[str, Any] = {
    **_obj(
        {
            "market": _obj(
                {
                    "stance": {"enum": list(STANCES)},
                    "confidence": {"enum": list(CONFIDENCES)},
                    "method": _obj(
                        {
                            "basis": {
                                "type": "array",
                                "items": {"enum": list(MARKET_BASIS)},
                                "minItems": 1,
                                "maxItems": len(MARKET_BASIS),
                            }
                        }
                    ),
                    "reasons": _REASONS,
                }
            ),
            "sectors": {
                "type": "array",
                "items": _obj(
                    {
                        "group_id": _S,
                        "name": _S,
                        "direction": {"enum": list(DIRECTIONS)},
                        "reasons": _REASONS,
                    }
                ),
            },
            "picks": {
                "type": "array",
                "maxItems": MAX_PICKS,
                "items": _obj(
                    {
                        "symbol": _S,
                        "rank": {"type": "integer"},
                        "method": _obj(
                            {
                                "setup": {"enum": list(SETUPS)},
                                "basis": {
                                    "type": "array",
                                    "items": {"enum": list(BASIS)},
                                    "minItems": 1,
                                    "maxItems": 3,
                                },
                                "confidence": {"enum": list(CONFIDENCES)},
                            }
                        ),
                        "reasons": _REASONS,
                        "levels": _obj(
                            {
                                "entry": _obj(
                                    {
                                        "type": {"enum": list(ENTRY_TYPES)},
                                        "low": _PRICE,
                                        "high": _PRICE,
                                        "condition": _S,
                                    }
                                ),
                                "stop": _PRICE,
                                "target_1": _PRICE,
                                "target_2": {"anyOf": [_PRICE, {"type": "null"}]},
                                "exit_conditions": {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/reason"},
                                    "maxItems": 2,
                                },
                                "valid_sessions": {
                                    "type": "integer",
                                    "minimum": VALID_SESSIONS[0],
                                    "maximum": VALID_SESSIONS[1],
                                },
                            }
                        ),
                    }
                ),
            },
            "empty_reason": {"anyOf": [_S, {"type": "null"}]},
            "data_gaps": _REASONS,
        }
    ),
    "$defs": {
        "reason": _REASON,
        "price": _obj(
            {
                "price": {"type": "number"},
                "refs": {"type": "array", "items": _S, "minItems": 1},
                "atr_multiple": {"type": "number"},
            }
        ),
    },
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SCHEMA_SHA256 = _sha256(
    json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
)


def prompt_text(version: str) -> str:
    return (
        (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate(value: Any, schema: dict[str, Any], where: str) -> None:
    """The subset of JSON Schema OUTPUT_SCHEMA uses; raise LlmBatchError on a miss."""

    if "$ref" in schema:
        schema = OUTPUT_SCHEMA["$defs"][schema["$ref"].rsplit("/", 1)[1]]
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _validate(value, option, where)
                return
            except LlmBatchError:
                continue
        raise LlmBatchError("schema_mismatch", f"{where} matches no option")
    if "enum" in schema:
        if value not in schema["enum"]:
            raise LlmBatchError("schema_mismatch", f"{where} not one of the codes")
        return
    kind = schema.get("type")
    if kind == "null":
        if value is not None:
            raise LlmBatchError("schema_mismatch", f"{where} must be null")
    elif kind == "string":
        if not isinstance(value, str):
            raise LlmBatchError("schema_mismatch", f"{where} must be a string")
    elif kind == "number":
        if not _is_number(value):
            raise LlmBatchError("schema_mismatch", f"{where} must be a number")
    elif kind == "integer":
        if not _is_number(value) or int(value) != value:
            raise LlmBatchError("schema_mismatch", f"{where} must be an integer")
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise LlmBatchError("schema_mismatch", f"{where} out of range")
    elif kind == "array":
        if not isinstance(value, list):
            raise LlmBatchError("schema_mismatch", f"{where} must be an array")
        if (
            not schema.get("minItems", 0)
            <= len(value)
            <= schema.get("maxItems", len(value))
        ):
            raise LlmBatchError("schema_mismatch", f"{where} has {len(value)} items")
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{where}[{index}]")
    elif kind == "object":
        if not isinstance(value, dict):
            raise LlmBatchError("schema_mismatch", f"{where} must be an object")
        missing = [key for key in schema["required"] if key not in value]
        extra = sorted(set(value) - set(schema["properties"]))
        if missing or extra:
            raise LlmBatchError(
                "schema_mismatch", f"{where} missing {missing} extra {extra}"
            )
        for key, sub in schema["properties"].items():
            _validate(value[key], sub, f"{where}.{key}")


def validate_schema(output: Any) -> None:
    """Raise LlmBatchError(schema_mismatch) unless OUTPUT matches OUTPUT_SCHEMA and
    no ``basis`` repeats a code (the order is the rank: a repeat has none)."""

    _validate(output, OUTPUT_SCHEMA, "output")
    basis = output["market"]["method"]["basis"]
    if len(set(basis)) != len(basis):
        raise LlmBatchError("schema_mismatch", "market.method.basis repeats a code")
    for index, pick in enumerate(output["picks"]):
        basis = pick["method"]["basis"]
        if len(set(basis)) != len(basis):
            raise LlmBatchError(
                "schema_mismatch", f"picks[{index}].method.basis repeats a code"
            )


# --- the levels of a pick ---------------------------------------------------------


def _level(levels: dict[str, Any], name: str) -> dict[str, Any] | None:
    if name.startswith("entry."):
        return levels["entry"][name.split(".", 1)[1]]
    return levels[name]


def _tick_at(price: float, kind: str, exchange: str | None, session: date) -> float:
    _upper, tick = lv._band(lv._price(price), lv._ladder(kind, exchange, session))
    return float(tick)


def rounded(
    name: str, price: float, kind: str, exchange: str | None, session: date
) -> float:
    """PRICE on D's tick: entry low and targets down, stop and entry high up."""

    if name in ROUND_DOWN:
        return lv.tick_floor(price, kind, exchange=exchange, session=session)
    return lv.tick_ceil(price, kind, exchange=exchange, session=session)


def reference_entry(entry_type: str, low: float, high: float) -> float:
    """The entry the reward to risk is measured from (``risk_reward_basis``)."""

    return low if entry_type == "breakout" else (low + high) / 2


def risk_reward(
    entry_type: str, low: float, high: float, stop: float, target_1: float
) -> float | None:
    """(target 1 − reference entry) ÷ (reference entry − stop); None without risk."""

    entry = reference_entry(entry_type, low, high)
    if entry <= stop:
        return None
    return (target_1 - entry) / (entry - stop)


_STOCK_REF = re.compile(r"^stock:([^:]+):(.+)$")


def check_levels(
    pick: dict[str, Any], item: dict[str, Any] | None, session_date: date
) -> dict[str, Any]:
    """The check of one pick's levels: ``{"status": "pass"|"fail", "problems",
    "prices", "rounded", "risk_reward", "display"}`` (display only on a pass)."""

    out: dict[str, Any] = {
        "status": "fail",
        "problems": [],
        "prices": {},
        "rounded": [],
        "risk_reward": None,
        "display": None,
    }
    problems = out["problems"]
    facts = (item or {}).get("level_facts") or {}
    if item is None or facts.get("status") == "missing" or "tick" not in facts:
        problems.append({"check": "no_level_facts"})
        return out
    symbol = pick["symbol"]
    kind = facts.get("instrument_type") or "stock"
    exchange = item.get("exchange")
    atr14 = facts.get("atr14")
    levels = pick["levels"]
    values: dict[str, float] = {}
    for name in LEVELS:
        level = _level(levels, name)
        if level is None:
            continue
        price = float(level["price"])
        multiple = float(level["atr_multiple"])
        record: dict[str, Any] = {
            "answer": price,
            "ref": level["refs"][0],
            "atr_multiple": multiple,
        }
        out["prices"][name] = record
        match = _STOCK_REF.match(level["refs"][0])
        field = match.group(2) if match and match.group(1) == symbol else None
        base = (
            facts_value(item, field)
            if field in PRICE_FIELDS or field in FACT_PRICE_FIELDS
            else None
        )
        if base is None:
            problems.append(
                {"check": "ref_not_price_field", "where": name, "ref": record["ref"]}
            )
        elif not any(abs(multiple - allowed) < 1e-9 for allowed in ATR_MULTIPLES):
            problems.append(
                {"check": "atr_multiple_not_allowed", "where": name, "value": multiple}
            )
        elif multiple != 0 and atr14 is None:
            problems.append({"check": "no_atr", "where": name})
        else:
            expected = base + multiple * (atr14 or 0)
            tolerance = max(
                TOL_TICKS * _tick_at(max(expected, 0.01), kind, exchange, session_date),
                TOL_PCT * abs(expected),
            )
            record.update(
                {
                    "base": base,
                    "expected": round(expected, 4),
                    "tolerance": round(tolerance, 4),
                }
            )
            if abs(price - expected) > tolerance + 1e-9:
                problems.append(
                    {
                        "check": "ref_mismatch",
                        "where": name,
                        "price": price,
                        "expected": round(expected, 4),
                        "tolerance": round(tolerance, 4),
                    }
                )
        on_tick = (
            rounded(name, price, kind, exchange, session_date) if price > 0 else price
        )
        record["price"] = on_tick
        if on_tick != price:
            out["rounded"].append(name)
        values[name] = on_tick
    low, high = facts.get("limit_down"), facts.get("limit_up")
    if low is not None and high is not None:
        outside = [name for name, value in values.items() if not low <= value <= high]
        if outside:
            problems.append(
                {"check": "outside_limits", "where": outside, "limits": [low, high]}
            )
    names = [name for name in LEVELS if name in values]
    if not all(
        values[a] <= values[b]
        if (a, b) == ("entry.low", "entry.high")
        else values[a] < values[b]
        for a, b in zip(names, names[1:])
    ):
        problems.append({"check": "order", "prices": [values[n] for n in names]})
    entry_type = levels["entry"]["type"]
    ratio = risk_reward(
        entry_type,
        values["entry.low"],
        values["entry.high"],
        values["stop"],
        values["target_1"],
    )
    out["risk_reward"] = None if ratio is None else round(ratio, 2)
    out["reference_entry"] = round(
        reference_entry(entry_type, values["entry.low"], values["entry.high"]), 4
    )
    if ratio is not None and ratio < MIN_RISK_REWARD - 1e-9:
        problems.append(
            {
                "check": "risk_reward_below_min",
                "risk_reward": round(ratio, 2),
                "minimum": MIN_RISK_REWARD,
            }
        )
    if not problems:
        out["status"] = "pass"
        out["display"] = {
            "entry": {
                "type": entry_type,
                "low": values["entry.low"],
                "high": values["entry.high"],
            },
            "stop": values["stop"],
            "target_1": values["target_1"],
            "target_2": values.get("target_2"),
            "risk_reward": out["risk_reward"],
            "valid_sessions": levels["valid_sessions"],
        }
    return out


# --- the checks of an answer --------------------------------------------------------


def _texts_and_refs(output: dict[str, Any]) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    refs: list[str] = []
    reasons = list(output["market"]["reasons"]) + list(output["data_gaps"])
    for sector in output["sectors"]:
        reasons += sector["reasons"]
    for pick in output["picks"]:
        reasons += pick["reasons"] + pick["levels"]["exit_conditions"]
        texts.append(pick["levels"]["entry"]["condition"])
        for name in LEVELS:
            level = _level(pick["levels"], name)
            if level is not None:
                refs += level["refs"]
    for reason in reasons:
        texts.append(reason["text"])
        refs += reason["refs"]
    if output["empty_reason"]:
        texts.append(output["empty_reason"])
    return texts, refs


_NEWS_REF = re.compile(r"^news:(\d+)$")
_DIGITS = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")


def _numbers(value: Any) -> set[float]:
    if _is_number(value):
        return {round(float(value), 4)}
    if isinstance(value, dict):
        return set().union(*(_numbers(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_numbers(item) for item in value)) if value else set()
    return set()


def unknown_prices(
    pick: dict[str, Any], item: dict[str, Any] | None, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """The price wordings of a pick's texts that are none of its input or level
    numbers (recorded only, #1142 2/4: e.g. 「折台股約2300元」)."""

    if item is None:
        return []
    known = (
        _numbers(item.get("price"))
        | _numbers(item.get("level_facts"))
        | _numbers(item.get("strategy_levels"))
        | _numbers(pick["levels"])
    )
    titles = {
        news["id"]: news.get("title") or ""
        for news in list(payload.get("market_news", [])) + list(item.get("news", []))
    }
    found = []
    texts = [("entry.condition", pick["levels"]["entry"]["condition"], [])]
    texts += [
        (f"reasons[{index}]", reason["text"], reason["refs"])
        for index, reason in enumerate(pick["reasons"])
    ]
    texts += [
        (f"exit_conditions[{index}]", reason["text"], reason["refs"])
        for index, reason in enumerate(pick["levels"]["exit_conditions"])
    ]
    for where, text, refs in texts:
        cited = [
            titles.get(int(match.group(1)), "")
            for ref in refs
            if (match := _NEWS_REF.match(ref))
        ]
        names = [(item["symbol"], item.get("name") or "")]
        for mention in price_mentions(text, cited, names):
            number = _DIGITS.search(mention)
            if number is None:
                continue
            value = round(float(number.group(0).replace(",", "")), 4)
            if value not in known:
                found.append(
                    {"symbol": pick["symbol"], "where": where, "price": mention}
                )
    return found


@dataclass
class Checked:
    reason: str | None
    detail: str
    checks: dict[str, Any]


def check(output: Any, payload: dict[str, Any]) -> Checked:
    """The checks of one answer, in order; the first failure is the reason.  A
    passed answer has each pick's level check in ``checks["picks"]``."""

    checks: dict[str, Any] = {}
    try:
        validate_schema(output)
    except LlmBatchError as exc:
        checks["schema"] = exc.detail
        return Checked("schema", exc.detail, checks)
    checks["schema"] = "pass"
    items = {item["symbol"]: item for item in payload["candidates"]}
    picks = output["picks"]
    symbols = [pick["symbol"] for pick in picks]
    seen: set[str] = set()
    found: dict[str, Any] = {
        "not_in_pool": sorted({s for s in symbols if s not in items}),
        "duplicate_pick": sorted({s for s in symbols if s in seen or seen.add(s)}),
        "rank_not_contiguous": (
            sorted(pick["rank"] for pick in picks)
            if sorted(pick["rank"] for pick in picks) != list(range(1, len(picks) + 1))
            else None
        ),
        "empty_without_reason": (
            True if not picks and not (output["empty_reason"] or "").strip() else None
        ),
    }
    checks["list"] = {key: value for key, value in found.items() if value}
    texts, refs = _texts_and_refs(output)
    ids = payload_news_ids(payload)
    unknown = sorted(
        {
            ref
            for ref in refs
            if ref.startswith("news")
            and (
                (match := _NEWS_REF.match(ref)) is None
                or int(match.group(1)) not in ids
            )
        }
    )
    checks["unknown_news_refs"] = unknown
    words = directive_words(texts)
    checks["directive_words"] = words
    reasons = list(output["market"]["reasons"]) + [
        reason
        for part in [sector["reasons"] for sector in output["sectors"]]
        + [pick["reasons"] for pick in picks]
        for reason in part
    ]
    checks["long_reasons"] = sum(
        1 for reason in reasons if len(reason["text"]) > REASON_MAX_CHARS
    )
    checks["unknown_group_ids"] = sorted(
        {sector["group_id"] for sector in output["sectors"]}
        - set(payload.get("groups", {}))
    )
    for key in LIST_REASONS:
        if found[key]:
            return Checked(key, json.dumps(found[key], ensure_ascii=False), checks)
    if unknown:
        return Checked("unknown_news_ref", ",".join(unknown), checks)
    if words:
        return Checked("directive_words", " | ".join(words)[:300], checks)
    session_date = date.fromisoformat(payload["session_date"])
    checks["picks"] = {
        pick["symbol"]: check_levels(pick, items.get(pick["symbol"]), session_date)
        for pick in picks
    }
    checks["picks_passed"] = sum(
        1 for result in checks["picks"].values() if result["status"] == "pass"
    )
    checks["price_mentions"] = [
        mention
        for pick in picks
        for mention in unknown_prices(pick, items.get(pick["symbol"]), payload)
    ]
    return Checked(None, "", checks)


# --- calls ------------------------------------------------------------------------


def _status_of(reason: str) -> str:
    """A content or schema failure is rejected; a call that gave no answer failed."""

    return REJECTED if reason in REJECT_REASONS else FAILED


class AiListCapture(RawCapture):
    """``premarket_reading.RawCapture`` under the ai_list raw source: each attempt's
    raw file is written at once, its row only with the reading."""

    def __call__(
        self, payload: dict[str, Any], run_at: datetime, attempt: dict[str, Any]
    ) -> None:
        raw = sources.capture_payload(
            RAW_SOURCE, RAW_ENDPOINT, payload, run_at.isoformat(), collected_at=run_at
        )
        self.pending.append((raw, attempt))


def read(
    snapshot: Snapshot,
    command: list[str],
    runner: Runner,
    *,
    version: str = PROMPT_VERSION,
    role: str = CHAMPION,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    capture: Callable[[dict[str, Any], datetime, dict[str, Any]], None] | None = None,
) -> Outcome:
    """Call the CLI on SNAPSHOT at most MAX_ATTEMPTS times (as
    ``premarket_reading.read``: no call starts with fewer than CALL_TIMEOUT_SECONDS
    left before ``deadline``)."""

    template = prompt_text(version)
    prompt = build_prompt(template, snapshot.payload)
    argv = [*command, *cli_arguments(MODEL, OUTPUT_SCHEMA)]
    outcome = Outcome(
        role=role,
        prompt_version=version,
        prompt_sha256=_sha256(template),
        status=FAILED,
        reason="not_called",
        error=None,
        output=None,
        checks={},
        started_at=utcnow(),
    )
    if PROMPTS.get(version) != outcome.prompt_sha256:
        outcome.reason = "prompt_hash_mismatch"
        outcome.error = (
            f"{version} sha256 {outcome.prompt_sha256} != {PROMPTS.get(version)}"
        )
        outcome.finished_at = utcnow()
        return outcome
    for number in range(1, MAX_ATTEMPTS + 1):
        if deadline is not None and deadline - clock() < CALL_TIMEOUT_SECONDS:
            if number == 1:
                outcome.reason = "no_time"
            else:
                outcome.checks["retry_skipped"] = "no_time"
            break
        started = clock()
        result = runner(prompt, argv)
        duration_ms = int((clock() - started) * 1000)
        run_at = utcnow()
        attempt: dict[str, Any] = {"number": number, "duration_ms": duration_ms}
        if capture is not None:
            capture(
                {
                    "prompt_version": version,
                    "role": role,
                    "attempt": number,
                    "argv": argv,
                    "prompt": prompt,
                    "returncode": result.returncode,
                    "timed_out": result.timed_out,
                    "error": result.error,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_ms": duration_ms,
                },
                run_at,
                attempt,
            )
        outcome.attempts.append(attempt)
        try:
            envelope = parse_envelope(result)
        except LlmBatchError as exc:
            attempt["reason"] = exc.reason
            outcome.status, outcome.reason = FAILED, exc.reason
            outcome.error = str(exc)[:500]
            if exc.reason in FATAL_REASONS or exc.reason not in RETRY_REASONS:
                break
            continue
        model, usage = _usage(envelope)
        attempt["model"], attempt["usage"] = model, usage
        outcome.llm_model = model or outcome.llm_model
        output = envelope.get("structured_output")
        checked = check(output, snapshot.payload)
        outcome.checks = checked.checks
        outcome.output = output if isinstance(output, dict) else None
        if checked.reason is None:
            attempt["reason"] = None
            outcome.status, outcome.reason, outcome.error = DONE, None, None
            break
        attempt["reason"] = checked.reason
        outcome.status = _status_of(checked.reason)
        outcome.reason = checked.reason
        outcome.error = checked.detail[:500]
        if checked.reason not in RETRY_REASONS:
            break
    outcome.finished_at = utcnow()
    return outcome


# --- rows -------------------------------------------------------------------------


def done_reading(
    db: Session,
    session_date: date,
    prompt_version: str = PROMPT_VERSION,
    role: str = CHAMPION,
) -> AiListReading | None:
    return db.scalar(
        select(AiListReading)
        .where(
            AiListReading.session_date == session_date,
            AiListReading.prompt_version == prompt_version,
            AiListReading.role == role,
            AiListReading.status == DONE,
        )
        .order_by(AiListReading.sequence)
        .limit(1)
    )


def next_sequence(
    db: Session, session_date: date, prompt_version: str, role: str
) -> int:
    latest = db.scalar(
        select(func.max(AiListReading.sequence)).where(
            AiListReading.session_date == session_date,
            AiListReading.prompt_version == prompt_version,
            AiListReading.role == role,
        )
    )
    return (latest or 0) + 1


def valid_until(db: Session, session_date: date, sessions: int) -> date:
    """The SESSIONS-th trading day from SESSION_DATE (itself the first) on the stored
    calendar (``notify.is_trading_day``: a day it does not mark closed trades)."""

    from .notify import is_trading_day

    day, count = session_date, 1
    while count < sessions:
        day += timedelta(days=1)
        if is_trading_day(db, day):
            count += 1
    return day


def store(
    db: Session,
    snapshot: Snapshot,
    outcome: Outcome,
    *,
    trigger: str,
    ingestion_run_id: int | None,
) -> AiListReading:
    """Add the run's row (and a done one's pick rows); nothing stored is changed."""

    output = outcome.output
    reading = AiListReading(
        session_date=snapshot.session_date,
        list_date=snapshot.list_date,
        role=outcome.role,
        sequence=next_sequence(
            db, snapshot.session_date, outcome.prompt_version, outcome.role
        ),
        trigger=trigger,
        prompt_version=outcome.prompt_version,
        prompt_sha256=outcome.prompt_sha256,
        schema_sha256=SCHEMA_SHA256,
        model_alias=MODEL,
        llm_model=outcome.llm_model,
        pool_phase=snapshot.pool_phase,
        cutoff_at=snapshot.cutoff_at,
        input_hash=snapshot.hash,
        input_json=snapshot.payload,
        status=outcome.status,
        reason=outcome.reason,
        error=outcome.error,
        output_json=output,
        market_method_json=(
            output["market"]["method"]["basis"]
            if outcome.status == DONE and output is not None
            else None
        ),
        checks_json=outcome.checks,
        attempts=len(outcome.attempts),
        attempts_json=outcome.attempts,
        duration_ms=outcome.duration_ms,
        usage_json=outcome.usage,
        ingestion_run_id=ingestion_run_id,
        started_at=outcome.started_at or utcnow(),
        finished_at=outcome.finished_at or utcnow(),
    )
    db.add(reading)
    db.flush()
    if outcome.status == DONE and output is not None:
        metas = {meta.symbol: meta for meta in snapshot.stocks}
        for pick in sorted(output["picks"], key=lambda item: item["rank"]):
            meta = metas[pick["symbol"]]
            result = outcome.checks["picks"][pick["symbol"]]
            sessions = pick["levels"]["valid_sessions"]
            display = result["display"]
            until = valid_until(db, snapshot.session_date, sessions)
            if display is not None:
                display = {**display, "valid_until": until.isoformat()}
            db.add(
                AiListPick(
                    reading_id=reading.id,
                    session_date=reading.session_date,
                    prompt_version=reading.prompt_version,
                    role=reading.role,
                    rank=pick["rank"],
                    instrument_id=meta.instrument_id,
                    symbol=meta.symbol,
                    pool_item_id=meta.pool_item_id,
                    pool_sources_json=list(meta.pool_sources),
                    on_rule_list=meta.on_today_list,
                    setup=pick["method"]["setup"],
                    basis_json=list(pick["method"]["basis"]),
                    basis_primary=pick["method"]["basis"][0],
                    confidence=pick["method"]["confidence"],
                    levels_json=pick["levels"],
                    levels_check_json={
                        key: value for key, value in result.items() if key != "display"
                    },
                    display_levels_json=display,
                    risk_reward=result["risk_reward"],
                    valid_sessions=sessions,
                    valid_until=until,
                    exit_conditions_json=pick["levels"]["exit_conditions"],
                    reasons_json=pick["reasons"],
                    rule_levels_json=meta.levels,
                )
            )
        db.flush()
    return reading
