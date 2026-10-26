"""Theme member table columns and sorts (#280, UI_COPY_SPEC §8.5)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import candidate_view
from app.api import get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_VERSION
from app.models import (
    CandidateRun,
    DailyCandidate,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    Signal,
    ThemeGroup,
)
from worker import pipeline


def _weekdays(end: date, count: int) -> list[date]:
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


T = date(2026, 9, 4)
DAYS = _weekdays(T, 3)
PREVIOUS = DAYS[-2]
GROUP = "ind-cement"
NEW_KEYS = {
    "change",
    "change_pct",
    "change_status",
    "turnover",
    "turnover_status",
    "excess_return_5d",
    "excess_return_20d",
    "candidate_rank",
    "conditional",
}
# The fields every member row carried before #280.
OLD_KEYS = {
    "id",
    "market",
    "exchange",
    "symbol",
    "name",
    "industry",
    "instrument_type",
    "etf_category",
    "listing_date",
    "is_watchlisted",
    "status",
    "role",
    "confidence",
    "valid_from",
    "valid_to",
    "theme_evidence",
    "latest_bar",
}


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info["strategies"] = pipeline._ensure_strategies(session)
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def _instrument(db, symbol, *, exchange="TWSE", instrument_type="stock"):
    instrument = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=f"名{symbol}",
        instrument_type=instrument_type,
        status="active",
    )
    db.add(instrument)
    db.flush()
    return instrument


def _bar(
    db,
    instrument,
    day,
    close,
    *,
    turnover=None,
    status="available",
    source="fixture-bars",
):
    db.add(
        MarketBar(
            instrument_id=instrument.id,
            trading_date=day,
            open=close,
            high=close,
            low=close,
            close=close,
            adj_close=close,
            volume=1000,
            turnover=0 if turnover is None else turnover,
            turnover_status=status,
            source=source,
        )
    )


def _signal(db, instrument, *, status="conditional", quality="complete"):
    version = db.info["strategies"]["breakout_v1"]
    row = Signal(
        signal_key=f"analysis-{instrument.symbol}-{T.isoformat()}-breakout",
        signal_date=T,
        instrument_id=instrument.id,
        strategy_version_id=version.id,
        status=status,
        data_quality=quality,
        entry_type="breakout",
        breakout_price=100.0,
        invalid_price=95.0,
        target_1=110.0,
        source_report="fixture-bars",
        rule_evidence_json={"inputs": {}, "actionable": status == "conditional"},
    )
    db.add(row)
    db.flush()
    return row


def _member_return(instrument, five, twenty):
    return {
        "instrument_id": instrument.id,
        "exchange": instrument.exchange,
        "symbol": instrument.symbol,
        "excess_return_5d": five,
        "excess_return_20d": twenty,
    }


def _seed(db, *, score_date=T):
    """Five cement members, each exercising one blank rule.

    1100 E: change known (-1%), turnover 10 億 (ties D), conditional, not a candidate.
    1101 A: change known (+2%), turnover 50 億, candidate #1.
    1102 B: previous bar from another source (unverified), turnover unavailable.
    1103 C: no bar on T (latest is the previous session): stale.
    1104 D: no bar on the previous session (gap), not in member_returns.
    """

    # TAIEX sessions; a ``twse_fixture`` source counts as verified.
    index = _instrument(db, "TAIEX", instrument_type="index")
    for day in DAYS:
        db.add(
            MarketBar(
                instrument_id=index.id,
                trading_date=day,
                open=20000.0,
                high=20000.0,
                low=20000.0,
                close=20000.0,
                adj_close=20000.0,
                source="twse_fixture",
            )
        )
    db.add(
        IngestionRun(
            run_type="collect",
            source="official",
            run_date=T,
            status="success",
            data_as_of=T.isoformat(),
        )
    )
    e, a, b, c, d = (
        _instrument(db, symbol) for symbol in ("1100", "1101", "1102", "1103", "1104")
    )
    _bar(db, e, PREVIOUS, 100.0, turnover=8e8)
    _bar(db, e, T, 99.0, turnover=1e9)
    _bar(db, a, PREVIOUS, 100.0, turnover=4e9)
    _bar(db, a, T, 102.0, turnover=5e9)
    _bar(db, b, PREVIOUS, 50.0, turnover=1e8, source="tpex")
    _bar(db, b, T, 50.0, turnover=0, status="unavailable")
    _bar(db, c, DAYS[0], 81.0, turnover=3e8)
    _bar(db, c, PREVIOUS, 80.0, turnover=2e8)
    _bar(db, d, DAYS[0], 72.0, turnover=6e8)
    _bar(db, d, T, 70.0, turnover=1e9)
    db.add(
        ThemeGroup(
            id=GROUP, name=GROUP, display_name_zh="水泥", group_type="official_industry"
        )
    )
    db.flush()
    for instrument in (e, a, b, c, d):
        db.add(
            GroupMembership(
                group_id=GROUP, instrument_id=instrument.id, valid_from=DAYS[0]
            )
        )
    db.add(
        GroupDailyScore(
            group_id=GROUP,
            trading_date=score_date,
            score=70.0,
            rank=1,
            data_quality="complete",
            eligible_members=4,
            details_json={
                "board": "industry",
                "member_return_identity_version": "instrument-id-v1",
                "member_returns": [
                    _member_return(e, 0.0, 0.05),
                    _member_return(a, 0.03, 0.1),
                    _member_return(b, -0.01, None),
                    _member_return(c, 0.01, 0.2),
                ],
            },
        )
    )
    _signal(db, e)
    candidate_signal = _signal(db, a)
    _signal(db, d, status="observation")
    run = CandidateRun(
        trading_date=T, score_version=CANDIDATE_SCORE_VERSION, candidate_count=1
    )
    db.add(run)
    db.flush()
    db.add(
        DailyCandidate(
            candidate_run_id=run.id,
            trading_date=T,
            instrument_id=a.id,
            signal_id=candidate_signal.id,
            strategy="breakout_v1",
            score_version=CANDIDATE_SCORE_VERSION,
            total_score=0.8,
            weight_coverage=1.0,
            rank=1,
            data_as_of=T,
        )
    )
    db.commit()


def _members(client, **params):
    response = client.get(
        f"/api/themes/{GROUP}/members", params={"page_size": 30, **params}
    )
    assert response.status_code == 200
    return response.json()


def _by_symbol(body):
    return {item["symbol"]: item for item in body["items"]}


@pytest.mark.parametrize(
    ("sort", "order"),
    [
        # null last, equal values by symbol (E and D both have 10 億).
        ("turnover", ["1101", "1100", "1104", "1102", "1103"]),
        ("change_pct", ["1101", "1100", "1102", "1103", "1104"]),
        ("return_5d", ["1101", "1103", "1100", "1102", "1104"]),
        ("return_20d", ["1103", "1101", "1100", "1102", "1104"]),
        ("price", ["1101", "1100", "1103", "1104", "1102"]),
        ("name", ["1100", "1101", "1102", "1103", "1104"]),
        ("symbol", ["1100", "1101", "1102", "1103", "1104"]),
    ],
)
def test_every_sort_puts_null_last_and_breaks_ties_by_symbol(db, client, sort, order):
    _seed(db)
    body = _members(client, sort=sort)
    assert [item["symbol"] for item in body["items"]] == order
    assert body["meta"]["sort"] == sort


def test_a_sorted_page_continues_the_same_order(db, client):
    _seed(db)
    second = _members(client, sort="turnover", page=2, page_size=2)
    assert [item["symbol"] for item in second["items"]] == ["1104", "1102"]
    assert second["meta"]["total"] == 5


def test_change_turnover_and_relative_returns_of_each_member(db, client):
    _seed(db)
    body = _members(client, sort="symbol")
    rows = _by_symbol(body)
    assert body["members_as_of"] == T.isoformat()
    a = rows["1101"]
    assert a["change"] == pytest.approx(2.0)
    assert a["change_pct"] == pytest.approx(0.02)
    assert a["change_status"] == "known"
    assert (a["turnover"], a["turnover_status"]) == (5e9, "available")
    assert (a["excess_return_5d"], a["excess_return_20d"]) == (0.03, 0.1)
    assert (a["candidate_rank"], a["conditional"]) == (1, True)
    e = rows["1100"]
    assert e["change_pct"] == pytest.approx(-0.01)
    assert (e["candidate_rank"], e["conditional"]) == (None, True)
    assert rows["1104"]["conditional"] is False  # an observation is not a condition


def test_previous_bar_from_another_source_or_not_adjacent_is_unverified(db, client):
    _seed(db)
    rows = _by_symbol(_members(client))
    for symbol in ("1102", "1104"):  # other source; gap on the previous session
        row = rows[symbol]
        assert row["latest_bar"]["date"] == T.isoformat()
        assert (row["change"], row["change_pct"], row["change_status"]) == (
            None,
            None,
            "unverified",
        )


def test_unavailable_turnover_is_null_even_when_stored_as_zero(db, client):
    _seed(db)
    b = _by_symbol(_members(client))["1102"]
    assert b["latest_bar"]["turnover"] == 0
    assert (b["turnover"], b["turnover_status"]) == (None, "unavailable")


def test_a_member_whose_latest_bar_is_older_than_members_as_of(db, client):
    _seed(db)
    c = _by_symbol(_members(client))["1103"]
    assert c["latest_bar"]["date"] == PREVIOUS.isoformat()  # the bar's own date
    assert c["latest_bar"]["close"] == 80.0
    assert (c["change"], c["change_pct"], c["change_status"]) == (None, None, "missing")
    assert (c["turnover"], c["turnover_status"]) == (None, "missing")
    # Relative returns come from the day's group score, not the bar.
    assert (c["excess_return_5d"], c["excess_return_20d"]) == (0.01, 0.2)


def test_a_member_outside_member_returns_has_no_relative_return(db, client):
    _seed(db)
    rows = _by_symbol(_members(client))
    assert (rows["1104"]["excess_return_5d"], rows["1104"]["excess_return_20d"]) == (
        None,
        None,
    )
    assert rows["1102"]["excess_return_20d"] is None


def test_relative_returns_only_come_from_the_score_of_members_as_of(db, client):
    _seed(db, score_date=PREVIOUS)
    rows = _by_symbol(_members(client))
    assert {
        (row["excess_return_5d"], row["excess_return_20d"]) for row in rows.values()
    } == {(None, None)}


def test_existing_member_fields_are_kept(db, client):
    _seed(db)
    items = _members(client)["items"]
    assert all(set(item) == OLD_KEYS | NEW_KEYS for item in items)


def test_candidates_and_members_share_one_adjacent_change_rule(db, client):
    _seed(db)
    member = _by_symbol(_members(client))["1101"]
    market = client.get("/api/candidates").json()["items"][0]["market"]
    assert {key: market[key] for key in ("change", "change_pct", "change_status")} == {
        key: member[key] for key in ("change", "change_pct", "change_status")
    }
    from app import market_change

    assert candidate_view.adjacent_change is market_change.adjacent_change
