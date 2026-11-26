"""tools/research/premarket_errors.py: the month's wrong pre-market AI calls (#1069).

Made-up readings, stock rows and ``premarket_score_v1`` rows on a small file
copy: the rules are docs/spec/premarket_ai.md 判錯清單與改版提案 (#1069 決定
7203530697).  Nothing is scored here; the tool only reads written rows.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import premarket_score as score
from app.db import Base
from app.models import (
    Instrument,
    PremarketAiReading,
    PremarketAiScore,
    PremarketAiStock,
)
from test_candidate_pool_score import _tool

pe = _tool("premarket_errors")
MONTH = "2026-12"
POPULATION = 0.01
NOW = datetime(2026, 12, 31, 7, 0)


def weekdays(start: date, count: int) -> list[date]:
    days, cursor = [], start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


DAYS = weekdays(date(2026, 12, 1), 23)  # Dec 1 .. Dec 31


def levels(kind="breakout"):
    return {
        "entry_type": kind,
        "entry_zone": {"low": 100, "high": 100},
        "invalid_price": 95,
        "target_1": 110,
    }


def hold(excess, exit_date, *, status="comparable"):
    return {
        "status": status,
        "reason": None if status == "comparable" else "missing_bar",
        "return": None if status != "comparable" else POPULATION + excess,
        "exit_date": exit_date.isoformat(),
    }


class Copy:
    def __init__(self, path):
        self.path = path
        self.engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.instruments: dict[str, int] = {}

    def close(self):
        self.db.commit()
        self.db.close()
        self.engine.dispose()

    def instrument(self, symbol):
        if symbol not in self.instruments:
            row = Instrument(exchange="TWSE", symbol=symbol, name=f"名{symbol}")
            self.db.add(row)
            self.db.flush()
            self.instruments[symbol] = row.id
        return self.instruments[symbol]

    def reading(
        self,
        day,
        *,
        role="champion",
        version="premarket_v1",
        status="done",
        hit=True,
        stocks=(),
        sequence=1,
        market_written=True,
        reasons=None,
        population=POPULATION,
    ):
        """``stocks``: (symbol, action, levels, rows by horizon) each."""

        candidates = [
            {"symbol": symbol, "name": f"名{symbol}", "price": {"close": 100}}
            for symbol, *_ in stocks
        ]
        reading = PremarketAiReading(
            session_date=day,
            list_date=day - timedelta(days=1),
            role=role,
            sequence=sequence,
            trigger="scheduler",
            prompt_version=version,
            prompt_sha256="0" * 64,
            schema_sha256="0" * 64,
            model_alias="sonnet",
            llm_model="claude-sonnet-5-5",
            pool_phase="evening",
            cutoff_at=NOW,
            input_hash="0" * 64,
            input_json={
                "session_date": day.isoformat(),
                "taiex": {"close": 20000},
                "market_news": [{"id": 7, "title": "隔夜"}, {"id": 8, "title": "無關"}],
                "candidates": candidates,
            },
            output_json={
                "market": {
                    "stance": "bullish",
                    "confidence": "medium",
                    "reasons": reasons
                    or [{"text": "根據……，推論……", "refs": ["news:7", "us:SOX"]}],
                }
            },
            status=status,
            attempts=1,
            duration_ms=0,
            started_at=NOW,
            finished_at=NOW,
        )
        self.db.add(reading)
        self.db.flush()
        if status != "done":
            return reading
        if market_written:
            self.score(
                reading,
                score.MARKET,
                score.MARKET,
                "d0",
                {
                    "status": "scored",
                    "stance": "bullish",
                    "return": 0.01 if hit else -0.01,
                    "realized": "up" if hit else "down",
                    "hit": hit,
                    "close_date": day.isoformat(),
                },
            )
        for horizon in ("t5", "t20"):
            if any(horizon in rows for *_, rows in stocks):
                self.score(
                    reading,
                    score.OVERALL,
                    score.OVERALL,
                    horizon,
                    {"population": {"mean": population}},
                )
        for position, (symbol, action, level, rows) in enumerate(stocks, start=1):
            stock = PremarketAiStock(
                reading_id=reading.id,
                session_date=day,
                prompt_version=version,
                role=role,
                instrument_id=self.instrument(symbol),
                symbol=symbol,
                position=position,
                on_today_list=level is not None,
                levels_json=level,
                action=action,
                reasons_json=[
                    {"text": "根據……", "refs": [f"stock:{symbol}:chips", "taiex"]}
                ],
            )
            self.db.add(stock)
            self.db.flush()
            for horizon, outcome in rows.items():
                self.score(
                    reading, score.STOCK, symbol, horizon, outcome, stock_id=stock.id
                )
        return reading

    def score(self, reading, scope, subject, horizon, outcome, stock_id=None):
        self.db.add(
            PremarketAiScore(
                reading_id=reading.id,
                stock_id=stock_id,
                session_date=reading.session_date,
                prompt_version=reading.prompt_version,
                role=reading.role,
                scope=scope,
                subject=subject,
                horizon=horizon,
                score_version=score.SCORE_VERSION,
                outcome_json=outcome,
                computed_at=NOW,
            )
        )


@pytest.fixture
def copy(tmp_path):
    made = Copy(tmp_path / "copy.db")
    yield made
    made.engine.dispose()


def built(copy, month=MONTH):
    copy.close()
    return pe.build(copy.path, month)


def t5(action, excess, day, **extra):
    return {"t5": {"effective_action": action, "open_hold": hold(excess, day), **extra}}


def t20_levels(action, trigger, day, *, repriced=False):
    result = {
        "status": "comparable",
        "first_trigger": trigger,
        "return": -0.05 if trigger == "invalidated" else 0.05,
    }
    part = {"original": result, "repriced": None, "repriced_result": None}
    if repriced:
        part = {
            "original": {"status": "comparable", "first_trigger": None},
            "repriced_result": result,
        }
    return {
        "t20": {
            "effective_action": action,
            "open_hold": hold(-0.02, day),
            "levels": part,
        }
    }


def ids(result, kind=None):
    return [
        case["case_id"]
        for case in result["cases"]
        if kind is None or case["kind"] == kind
    ]


def test_each_kind_of_miss_on_both_sides_of_its_threshold(copy):
    d, out = DAYS[0], DAYS[5]
    copy.reading(
        d,
        hit=False,
        stocks=[
            ("D1", "defer", None, t5("defer", 0.03, out)),  # rose 3 pts: wrong
            ("D2", "defer", None, t5("defer", 0.0299, out)),  # between: neither
            ("D3", "defer", None, t5("defer", -0.03, out)),  # fell 3 pts: right
            ("R1", "reprice", levels(), t5("defer", 0.05, out)),  # re-price deferred
            ("K1", "keep", None, t5("keep", -0.03, out)),  # fell: wrong
            ("K2", "keep", None, t5("keep", -0.0299, out)),
            ("K3", "keep", None, t5("keep", 0.03, out)),  # rose: right
            ("L1", "keep", levels(), t20_levels("keep", "invalidated", DAYS[19])),
            ("L2", "keep", levels(), t20_levels("keep", "target_1_hit", DAYS[19])),
            ("L3", "keep", levels(), t20_levels("keep", None, DAYS[19])),
            (
                "L4",
                "reprice",
                levels(),
                t20_levels("reprice", "invalidated", DAYS[19], repriced=True),
            ),
        ],
    )
    result = built(copy)
    day = d.isoformat()
    assert set(ids(result, "error")) == {
        f"{day}:market:market",
        f"{day}:D1:defer",
        f"{day}:R1:defer",
        f"{day}:K1:no_levels_keep",
        f"{day}:L1:levels_stop",
        f"{day}:L4:levels_stop",
    }
    by_id = {case["case_id"]: case for case in result["cases"]}
    assert by_id[f"{day}:R1:defer"]["reprice_deferred"] is True
    assert by_id[f"{day}:D1:defer"]["reprice_deferred"] is False
    # the controls: as many right ones per category as there are wrong ones
    assert set(ids(result, "control")) == {
        f"{day}:D3:defer",
        f"{day}:K3:no_levels_keep",
        f"{day}:L2:levels_stop",
    }
    assert result["found"]["errors"] == 6
    assert result["found"]["controls"] == 3


# 8-place values 3 points apart whose plain difference is 0.02999999999999997
EDGE_POPULATION = 0.47054417
EDGE_UP, EDGE_DOWN = 0.50054417, 0.44054417


def edge_t5(action, value, day):
    return {
        "t5": {
            "effective_action": action,
            "open_hold": {
                "status": "comparable",
                "return": value,
                "exit_date": day.isoformat(),
            },
        }
    }


def test_exactly_three_points_is_on_the_threshold(copy):
    assert EDGE_UP - EDGE_POPULATION < pe.ERROR_EXCESS  # the float trap
    d, out = DAYS[0], DAYS[5]
    copy.reading(
        d,
        population=EDGE_POPULATION,
        stocks=[
            ("D1", "defer", None, edge_t5("defer", EDGE_UP, out)),  # rose 3: wrong
            ("D2", "defer", None, edge_t5("defer", EDGE_DOWN, out)),  # fell 3: right
            ("K1", "keep", None, edge_t5("keep", EDGE_DOWN, out)),  # fell 3: wrong
            ("K2", "keep", None, edge_t5("keep", EDGE_UP, out)),  # rose 3: right
        ],
    )
    result = built(copy)
    day = d.isoformat()
    assert set(ids(result, "error")) == {f"{day}:D1:defer", f"{day}:K1:no_levels_keep"}
    assert set(ids(result, "control")) == {
        f"{day}:D2:defer",
        f"{day}:K2:no_levels_keep",
    }


@pytest.mark.parametrize(
    ("days", "errors", "status"),
    [
        (14, 10, "insufficient_sample"),
        (15, 9, "insufficient_sample"),
        (15, 10, "ok"),
    ],
)
def test_the_gate_on_its_edges(days, errors, status):
    assert pe.proposal_gate(days, errors, None)["status"] == status
    assert pe.proposal_gate(days, errors, "premarket_v2")["status"] == "shadow_exists"


def test_a_levelled_keep_is_judged_by_its_stop_only(copy):
    # L3's D-open hold is −2 pts against the population (not −3), and L5's −4:
    # with levels only the stop counts, so L5 is not a case either
    rows = t20_levels("keep", None, DAYS[19])
    rows["t20"]["open_hold"] = hold(-0.04, DAYS[19])
    copy.reading(
        DAYS[0],
        stocks=[("L5", "keep", levels(), {**t5("keep", -0.04, DAYS[5]), **rows})],
    )
    assert ids(built(copy), "error") == []


def test_only_the_running_champion_version_is_read(copy):
    stocks = [("K1", "keep", None, t5("keep", -0.05, DAYS[6]))]
    copy.reading(DAYS[1], hit=False, stocks=stocks)
    copy.reading(
        DAYS[1], role="shadow", version="premarket_v2", hit=False, stocks=stocks
    )
    copy.reading(DAYS[2], version="premarket_v0", hit=False, stocks=stocks)
    copy.reading(DAYS[3], status="failed")
    copy.reading(DAYS[4], status="rejected")
    copy.reading(DAYS[4], status="done", sequence=2, hit=True)
    result = built(copy)
    assert ids(result, "error") == [
        f"{DAYS[1].isoformat()}:market:market",
        f"{DAYS[1].isoformat()}:K1:no_levels_keep",
    ]
    # day 4 was rejected, then done: a done day
    assert result["days"] == {"done": 2, "failed": 1, "rejected": 0}
    assert result["other_versions"] == [{"prompt_version": "premarket_v0", "days": 1}]


def test_at_most_thirty_with_the_market_first_and_the_stocks_by_excess(copy):
    for at, day in enumerate(DAYS[:3]):
        copy.reading(
            day,
            hit=False,
            stocks=[
                (
                    f"S{at}{n}",
                    "keep",
                    None,
                    t5("keep", -0.03 - 0.001 * (n + 10 * at), DAYS[at + 5]),
                )
                for n in range(12)
            ]
            + [(f"C{at}", "keep", None, t5("keep", 0.10 + at / 100, DAYS[at + 5]))],
        )
    result = built(copy)
    errors = [case for case in result["cases"] if case["kind"] == "error"]
    assert len(errors) == pe.MAX_CASES == 30
    assert [case["category"] for case in errors[:3]] == ["market"] * 3
    keys = [case["key"] for case in errors[3:]]
    assert keys == sorted(keys, reverse=True)
    assert errors[3]["symbol"] == "S211"  # the largest |excess|
    assert result["found"]["errors"] == 39
    controls = [case for case in result["cases"] if case["kind"] == "control"]
    # every market day was wrong, so no market control; the three right
    # stocks, the largest first
    assert [case["symbol"] for case in controls] == ["C2", "C1", "C0"]


def test_the_gate_wants_fifteen_market_days_and_ten_misses(copy):
    for day in DAYS[:15]:
        copy.reading(day, hit=day.day % 2 == 0)
    result = built(copy)
    assert result["month_stats"]["market_d0_days"] == 15
    misses = result["found"]["errors"]
    assert misses < 10
    assert result["proposal_gate"]["status"] == pe.INSUFFICIENT
    assert "樣本不足，不提案" in pe.markdown(result, "cmd")


def test_enough_misses_open_the_gate_and_a_shadow_closes_it(copy, monkeypatch):
    for day in DAYS[:15]:
        copy.reading(day, hit=False)
    copy.close()
    assert pe.build(copy.path, MONTH)["proposal_gate"]["status"] == pe.OK
    from worker import premarket_reading

    monkeypatch.setattr(premarket_reading, "SHADOW_PROMPT_VERSION", "premarket_v2")
    result = pe.build(copy.path, MONTH)
    assert result["proposal_gate"]["status"] == pe.SHADOW_EXISTS
    assert "已有 shadow，不提案" in pe.markdown(result, "cmd")


def test_a_case_belongs_to_the_month_its_result_came_out(copy, tmp_path):
    # Dec 31's reading: its T+5 ends in January
    last = DAYS[-1]
    january = weekdays(date(2027, 1, 1), 5)[-1]
    copy.reading(last, stocks=[("K1", "keep", None, {})])
    copy.close()
    december = pe.build(copy.path, MONTH)
    assert "K1" not in " ".join(ids(december))
    assert december["found"]["pending"] == 1
    assert december["found"]["later_month"] == 0
    # the January copy has the row: January lists it once, December never
    later = Copy(copy.path)
    reading = later.db.query(PremarketAiReading).one()
    stock = later.db.query(PremarketAiStock).one()
    later.score(
        reading,
        score.OVERALL,
        score.OVERALL,
        "t5",
        {"population": {"mean": POPULATION}},
    )
    later.score(
        reading,
        score.STOCK,
        "K1",
        "t5",
        t5("keep", -0.05, january)["t5"],
        stock_id=stock.id,
    )
    later.close()
    again = pe.build(copy.path, MONTH)
    assert "K1" not in " ".join(ids(again))
    # written now, its result in January: counted in December as later, not pending
    assert (again["found"]["pending"], again["found"]["later_month"]) == (0, 1)
    assert ids(pe.build(copy.path, "2027-01"), "error") == [
        f"{last.isoformat()}:K1:no_levels_keep"
    ]


def test_a_case_carries_the_input_the_call_and_the_outcome(copy):
    copy.reading(
        DAYS[0], hit=False, stocks=[("K1", "keep", None, t5("keep", -0.05, DAYS[5]))]
    )
    result = built(copy)
    [market, stock] = [case for case in result["cases"] if case["kind"] == "error"]
    assert stock["input"] == {"symbol": "K1", "name": "名K1", "price": {"close": 100}}
    assert (
        stock["action"] == "keep" and stock["reasons"][0]["refs"][0] == "stock:K1:chips"
    )
    assert stock["outcome"]["excess"] == pytest.approx(-0.05)
    session = result["sessions"][DAYS[0].isoformat()]
    # only the market news its reasons cited
    assert session["market_input"]["cited_market_news"] == [{"id": 7, "title": "隔夜"}]
    assert market["reasons"][0]["refs"] == ["news:7", "us:SOX"]


def test_incomparable_and_unwritten_calls_are_counted_not_cased(copy):
    copy.reading(
        DAYS[0],
        stocks=[
            (
                "K1",
                "keep",
                None,
                {
                    "t5": {
                        "effective_action": "keep",
                        "open_hold": hold(0, DAYS[5], status="incomparable"),
                    }
                },
            ),
            ("K2", "keep", None, {}),
        ],
    )
    result = built(copy)
    assert result["found"]["incomparable"] == 1
    assert result["found"]["pending"] == 1
    assert ids(result, "error") == []


def test_the_citations_table_reads_every_call_by_its_sign(copy):
    copy.reading(
        DAYS[0],
        hit=True,
        stocks=[
            ("K1", "keep", None, t5("keep", 0.001, DAYS[5])),
            ("D1", "defer", None, t5("defer", 0.001, DAYS[5])),
        ],
    )
    rows = {row["ref"]: row for row in built(copy)["refs"]}
    assert rows["news"] == {"ref": "news", "reasons": 1, "judged": 1, "right_rate": 1.0}
    assert rows["stock:chips"]["right_rate"] == 0.5  # K1 right, D1 wrong
    assert rows["taiex"]["reasons"] == 2
    assert pe.ref_kind("stock:2330:price.return_5d") == "stock:price.return_5d"


def test_the_command_writes_cases_json_and_md(copy, tmp_path, monkeypatch):
    copy.close()
    monkeypatch.setattr(pe.lib._load("exit_research"), "refusals", lambda db, gb: [])
    out = tmp_path / "out"
    assert pe.main(["--db", str(copy.path), "--month", MONTH, "--out", str(out)]) == 0
    cases = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    assert cases["proposal_gate"]["status"] == pe.INSUFFICIENT
    assert cases["synthetic"] is False
    assert (
        (out / "cases.md").read_text(encoding="utf-8").startswith("# 早盤 AI 判錯清單")
    )
