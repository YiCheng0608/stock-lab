"""A research history starts each source on its first day (Issue #692).

- Unset, the history starts are the production ones exactly (2024-09-30 and
  2023-09-01); a research database may only move them earlier.
- A historical collect does not ask a website report for a day before the
  first one it answers (T86 2012-05-02, TPEx dailyQuotes 2007-04-23, TPEx
  insti/dailyTrade 2014-12-01, TWT49U 2003-05-05): the feed is recorded as
  ``not_published``, with no warning, and TPEx's empty table before 2007-04-23
  is not a closed day.  On and after the first day nothing changes.
- The backfill commands keep at least 3 seconds per host; the daily keeps the
  per-host intervals.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

import app.coverage as coverage
import worker.cli as cli
import worker.index_bars as index_bars
import worker.sources as sources
from app import history_settings as settings

BACKEND = Path(__file__).resolve().parents[1]


# ---- the starts --------------------------------------------------------------


def test_unset_starts_are_the_production_values():
    assert settings.session_basis_start({}) == date(2024, 9, 30)
    assert settings.index_history_start({}) == date(2023, 9, 1)
    assert settings.session_basis_start(
        {settings.SESSION_BASIS_START_ENV: " "}
    ) == date(2024, 9, 30)
    assert settings.create_unmatched_instruments({}) is False
    # This process sets none of them: the module constants are the old literals.
    assert coverage.SESSION_BASIS_START == date(2024, 9, 30)
    assert index_bars.HISTORY_START == date(2023, 9, 1)
    assert index_bars.DEFAULT_FIRST_MONTH == "2023-09"


def test_a_research_history_may_only_start_earlier():
    environ = {
        settings.SESSION_BASIS_START_ENV: "2004-02-11",
        settings.INDEX_HISTORY_START_ENV: "2004-02-01",
        settings.CREATE_UNMATCHED_ENV: "1",
    }
    assert settings.session_basis_start(environ) == date(2004, 2, 11)
    assert settings.index_history_start(environ) == date(2004, 2, 1)
    assert settings.create_unmatched_instruments(environ) is True
    with pytest.raises(ValueError, match="only start earlier"):
        settings.session_basis_start({settings.SESSION_BASIS_START_ENV: "2024-10-01"})
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        settings.session_basis_start({settings.SESSION_BASIS_START_ENV: "20040211"})
    with pytest.raises(ValueError, match="after the stock history start"):
        settings.index_history_start(
            {
                settings.SESSION_BASIS_START_ENV: "2004-02-11",
                settings.INDEX_HISTORY_START_ENV: "2010-01-01",
            }
        )
    with pytest.raises(ValueError, match="0 or 1"):
        settings.create_unmatched_instruments({settings.CREATE_UNMATCHED_ENV: "yes"})


def test_the_environment_moves_the_module_constants(tmp_path):
    env = {
        **os.environ,
        "STOCK_DATA_DIR": str(tmp_path / "data"),
        settings.SESSION_BASIS_START_ENV: "2004-02-11",
        settings.INDEX_HISTORY_START_ENV: "2004-02-01",
    }
    out = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import app.coverage as c, worker.index_bars as i;"
            "print(c.SESSION_BASIS_START, i.HISTORY_START, i.DEFAULT_FIRST_MONTH)",
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.split() == ["2004-02-11", "2004-02-01", "2004-02"]


# ---- the first days of the website reports ----------------------------------


def _empty_tpex_table(day: date) -> dict:
    return {"stat": "ok", "date": day.strftime("%Y%m%d"), "tables": []}


def test_twse_does_not_ask_t86_before_its_first_day(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    asked: list[str] = []

    def fetcher(url: str, **_kwargs):
        asked.append(url)
        raise sources.OfficialDataError(f"fixture outage {url}")

    adapter = sources.TwseAdapter(fetcher)
    _chips, _payloads, warnings = adapter.fetch_chips(
        [date(2012, 4, 30), date(2012, 5, 2)], {"1101"}
    )

    t86 = [url for url in asked if url.startswith(sources.TWSE_CHIP_ENDPOINT)]
    margin = [
        url for url in asked if url.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT)
    ]
    assert t86 == [url for url in t86 if "date=20120502" in url] and len(t86) == 1
    assert len(margin) == 2  # the margin file is asked on both days
    assert adapter.not_published == {"institutional": [date(2012, 4, 30)]}
    assert not [w for w in warnings if "institutional" in w and "2012-04-30" in w]
    assert [w for w in warnings if "institutional" in w and "2012-05-02" in w]


def test_tpex_quotes_before_the_first_day_are_not_asked_nor_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    asked: list[str] = []

    def fetcher(url: str, **kwargs):
        asked.append((kwargs.get("data") or {}).get("date"))
        return _empty_tpex_table(date(2007, 4, 23))

    adapter = sources.TpexAdapter(fetcher)
    bars, _payloads = adapter.fetch_bars(["7001"], date(2007, 4, 16), date(2007, 4, 20))
    assert bars == [] and asked == [] and adapter.no_data_dates == []
    assert adapter.not_published == {
        "quotes": [date(2007, 4, d) for d in (16, 17, 18, 19, 20)]
    }

    adapter = sources.TpexAdapter(fetcher)
    adapter.fetch_bars(["7001"], date(2007, 4, 20), date(2007, 4, 23))
    assert asked == ["2007/04/23"]
    # The empty table of the first day is still read as a closed day, as before.
    assert adapter.no_data_dates == [date(2007, 4, 23)]
    assert adapter.not_published == {"quotes": [date(2007, 4, 20)]}


def test_tpex_does_not_ask_the_institutional_file_before_its_first_day(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    asked: list[str] = []

    def fetcher(url: str, **kwargs):
        asked.append(url)
        raise sources.OfficialDataError("fixture outage")

    adapter = sources.TpexAdapter(fetcher)
    _chips, _payloads, warnings = adapter.fetch_chips(
        [date(2014, 11, 28), date(2014, 12, 1)], {"7001"}
    )
    assert asked.count(sources.TPEX_CHIP_HISTORY_ENDPOINT) == 1
    assert asked.count(sources.TPEX_MARGIN_HISTORY_ENDPOINT) == 2
    assert adapter.not_published == {"institutional": [date(2014, 11, 28)]}
    assert not [w for w in warnings if "institutional" in w and "2014-11-28" in w]


def test_the_not_published_record_is_absent_after_the_first_days():
    assert sources._not_published_record("TWSE", {}) == {}
    assert sources._not_published_record("TPEx", {"quotes": []}) == {}
    assert sources._not_published_record(
        "TPEx", {"institutional": [date(2014, 11, 28), date(2014, 11, 27)]}
    ) == {
        "TPEx": {
            "not_published": {
                "institutional": {
                    "first_date": "2014-12-01",
                    "dates": ["2014-11-27", "2014-11-28"],
                }
            }
        }
    }


def test_twt49u_months_start_on_its_first_day(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    asked: list[str] = []

    def fetcher(url: str, **_kwargs):
        asked.append(url)
        return {"stat": "很抱歉，沒有符合條件的資料!"}

    adapter = sources.TwseAdapter(fetcher)
    adapter.fetch_action_history(date(2003, 3, 1), date(2003, 5, 31))
    assert len(asked) == 1 and "startDate=20030505" in asked[0]
    asked.clear()
    assert adapter.fetch_action_history(date(2003, 1, 1), date(2003, 4, 30)) == (
        [],
        [],
        [],
    )
    assert asked == []


# ---- the backfill commands' interval ---------------------------------------


def test_the_backfill_commands_keep_three_seconds_per_host(monkeypatch):
    slept: list[float] = []
    clock = iter([100.0, 100.0, 100.5, 100.5, 200.0, 200.0, 200.5, 200.5])
    monkeypatch.setattr(sources.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sources.time, "sleep", slept.append)
    monkeypatch.setattr(sources, "_host_last_request", {})
    monkeypatch.setattr(sources, "_minimum_host_interval", 0.0)
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
    sources._throttle_official_host(url)
    sources._throttle_official_host(url)
    assert slept == [0.5]  # the daily's 1 second for www.tpex.org.tw
    sources.set_minimum_host_interval(3.0)
    sources._throttle_official_host(url)
    sources._throttle_official_host(url)
    assert slept == [0.5, 2.5]


@pytest.mark.parametrize(
    ("argv", "name"),
    [
        (
            ["backfill", "--start-date", "2012-04-25", "--end-date", "2012-05-08"],
            "backfill",
        ),
        (["trading-halts", "--start", "2011-01-01"], "trading-halts"),
        (
            [
                "corporate-actions",
                "sync",
                "--start-date",
                "2004-01-01",
                "--end-date",
                "2004-01-31",
            ],
            "corporate-actions sync",
        ),
        (["revenue", "backfill"], "revenue backfill"),
        (["fundamentals", "backfill"], "fundamentals backfill"),
        (
            [
                "events",
                "backfill",
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-01-02",
            ],
            "events backfill",
        ),
        (["index-bars", "backfill"], "index-bars backfill"),
        (["daily", "--date", "2026-11-13"], None),
        (["collect", "--date", "2026-11-13"], None),
        (["corporate-actions", "check"], None),
    ],
)
def test_which_commands_are_backfills(argv, name, monkeypatch):
    captured = {}
    monkeypatch.setattr(sys, "argv", ["worker.cli", *argv])
    monkeypatch.setattr(
        cli, "run_command", lambda args, parser: captured.setdefault("args", args)
    )
    monkeypatch.setattr(cli, "maintenance_guarded", lambda args: None)
    cli.main()
    assert cli.backfill_command(captured["args"]) == name


def test_backfill_refuses_a_start_before_mi_index(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker.cli",
            "backfill",
            "--start-date",
            "2004-02-10",
            "--end-date",
            "2004-02-20",
        ],
    )
    monkeypatch.setattr(cli, "run_command", lambda *_: pytest.fail("ran"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 2
    assert "2004-02-11" in capsys.readouterr().err


# ---- a research history creates the instruments of codes that left -------


from sqlalchemy import func, select  # noqa: E402

import test_unmatched_backfill as unmatched  # noqa: E402
import worker.pipeline as pipeline  # noqa: E402
from app.models import DataQuality, Instrument, MarketBar  # noqa: E402

env = unmatched.env


def _rows(db, model, **where):
    query = select(func.count()).select_from(model)
    for name, value in where.items():
        query = query.where(getattr(model, name) == value)
    return db.scalar(query)


def test_unset_records_unmatched_bars_as_before(env):
    unmatched._first_session()
    with env() as db:
        assert _rows(db, DataQuality, entity_type="unmatched_bar") == 2
        assert db.scalar(select(Instrument).where(Instrument.symbol == "7710")) is None


def test_a_research_history_creates_the_instrument_and_writes_its_bars(
    env, monkeypatch
):
    monkeypatch.setattr(pipeline, "create_unmatched_instruments", lambda: True)
    with env() as db:
        # 6938 is a TWSE instrument already: its TPEx history is of a code that moved.
        db.add(
            Instrument(
                market="TW",
                exchange="TWSE",
                symbol="6938",
                name="藍新資訊",
                instrument_type="stock",
                status="active",
            )
        )
        db.commit()
    result, _payloads = unmatched._first_session()

    created = {
        (item["exchange"], item["symbol"]): item
        for item in result["history_instruments_created"]
    }
    assert set(created) == {("TWSE", "7710"), ("TPEx", "6938")}
    with env() as db:
        assert _rows(db, DataQuality, entity_type="unmatched_bar") == 0
        twse = db.scalar(
            select(Instrument).where(
                Instrument.exchange == "TWSE", Instrument.symbol == "7710"
            )
        )
        tpex = db.scalar(
            select(Instrument).where(
                Instrument.exchange == "TPEx", Instrument.symbol == "6938"
            )
        )
        assert (twse.name, twse.instrument_type, twse.status) == (
            "東擎科技",
            "stock",
            "delisted",
        )
        assert (tpex.name, tpex.status) == ("藍新資訊", "transferred")
        assert _rows(db, MarketBar, instrument_id=twse.id) == 1
        assert _rows(db, MarketBar, instrument_id=tpex.id) == 1
        evidence = db.scalars(
            select(DataQuality).where(DataQuality.entity_type == "instrument_status")
        ).all()
        assert {row.entity_key for row in evidence} == {"TWSE:7710", "TPEx:6938"}


def test_t86_before_2014_12_reads_the_foreign_column_of_its_own_layout():
    """The 2012 layout had no foreign-dealer column (the #692 probe of 2012-05-02)."""

    legacy = {
        "stat": "OK",
        "date": "20120502",
        "fields": [
            "證券代號",
            "證券名稱",
            "外資買進股數",
            "外資賣出股數",
            "外資買賣超股數",
            "投信買進股數",
            "投信賣出股數",
            "投信買賣超股數",
            "自營商買賣超股數",
            "自營商買進股數",
            "自營商賣出股數",
            "三大法人買賣超股數",
        ],
        "data": [
            [
                "1101",
                "測試",
                "3,000",
                "1,000",
                "2,000",
                "500",
                "0",
                "500",
                "-100",
                "50",
                "150",
                "2,400",
            ]
        ],
    }
    (row,) = sources.parse_twse_institutional_rows(
        legacy, trading_date=date(2012, 5, 2)
    )
    assert (row.foreign_buy, row.trust_buy, row.dealer_buy) == (2000, 500, -100)

    current = {
        "stat": "OK",
        "date": "20261113",
        "fields": [
            "證券代號",
            "證券名稱",
            "外陸資買賣超股數(不含外資自營商)",
            "外資自營商買賣超股數",
            "投信買賣超股數",
            "自營商買賣超股數",
        ],
        "data": [["1101", "測試", "", "7,000", "500", "-100"]],
    }
    (row,) = sources.parse_twse_institutional_rows(
        current, trading_date=date(2026, 11, 13)
    )
    # The current layout never falls back to another column: an empty cell stays empty.
    assert row.foreign_buy is None


def test_taiex_before_2009_comes_from_the_month_report(tmp_path, monkeypatch):
    """MI_INDEX before 2009-01-05 has no 價格指數 table (#692 probes)."""

    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    asked: list[str] = []
    quotes_fields = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額"] + [
        "開盤價",
        "最高價",
        "最低價",
        "收盤價",
        "漲跌(+/-)",
        "漲跌價差",
        "最後揭示買價",
        "最後揭示買量",
        "最後揭示賣價",
        "最後揭示賣量",
        "本益比",
    ]

    def fetcher(url: str, **_kwargs):
        asked.append(url)
        if url.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT):
            return {
                "stat": "OK",
                "date": "20070401",
                "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
                "data": [
                    [" 96/04/16", "7,900.00", "7,950.00", "7,880.00", "7,930.12"],
                    [" 96/04/17", "7,930.00", "7,990.00", "7,900.00", "7,960.34"],
                ],
            }
        day = url.split("date=")[1][:8]
        return {
            "stat": "OK",
            "date": day,
            "tables": [
                {
                    "title": f"096年04月{day[6:]}日 每日收盤行情",
                    "fields": quotes_fields,
                    "data": [
                        ["1101", "台泥", "1,000", "1", "30,000", "30", "30", "30", "30"]
                        + ["", "0", "30", "1", "30", "1", "10"]
                    ],
                }
            ],
        }

    adapter = sources.TwseAdapter(fetcher, snapshot_feeds=False)
    bars, payloads = adapter.fetch_bars(["1101"], date(2007, 4, 16), date(2007, 4, 17))
    taiex = {bar.trading_date: bar for bar in bars if bar.symbol == "TAIEX"}
    assert {day: bar.close for day, bar in taiex.items()} == {
        date(2007, 4, 16): 7930.12,
        date(2007, 4, 17): 7960.34,
    }
    assert {bar.source for bar in taiex.values()} == {"twse_index"}
    month = [
        p
        for p in payloads
        if p.endpoint.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT)
    ]
    assert month and month[0].data_as_of == "2007-04-17"
    assert {bar.payload_sha256 for bar in taiex.values()} == {month[0].sha256}
    # One request for the month, not one a day.
    assert sum(u.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT) for u in asked) == 1

    # From 2009-01-05 a missing price index still fails the day, as before.
    def later(url: str, **kwargs):
        if url.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT):
            raise AssertionError("asked the month report")
        payload = fetcher(url.replace("20090105", "20070416"))
        payload["date"] = "20090105"
        return payload

    with pytest.raises(sources.OfficialDataError, match="price-index TAIEX"):
        sources.TwseAdapter(later, snapshot_feeds=False).fetch_bars(
            ["1101"], date(2009, 1, 5), date(2009, 1, 5)
        )


def test_tpex_institutional_file_of_2014_reads_its_16_column_layout():
    """The 2014-12-01 answer: an empty table first, then the 16-column detail."""

    fields = list(sources.TPEX_INSTITUTIONAL_LEGACY_FIELDS)
    payload = {
        "stat": "ok",
        "date": "20141201",
        "tables": [
            {"title": "", "fields": [], "data": []},
            {
                "title": "三大法人買賣明細資訊",
                "fields": fields,
                "data": [
                    ["7001", "測試", "3,000", "1,000", "2,000", "500", "0", "500"]
                    + ["-100", "0", "0", "0", "0", "100", "-100", "2,400"]
                ],
            },
        ],
    }
    (row,) = sources.parse_tpex_institutional_rows(
        payload, trading_date=date(2014, 12, 1)
    )
    assert (row.foreign_buy, row.trust_buy, row.dealer_buy, row.total_buy_sell) == (
        2000,
        500,
        -100,
        2400,
    )
    # Another 16-column header is not guessed at.
    payload["tables"][1]["fields"] = [*fields[:-1], "合計"]
    assert all(
        record.foreign_buy is None
        for record in sources.parse_tpex_institutional_rows(
            payload, trading_date=date(2014, 12, 1)
        )
    )


def test_a_frozen_hypothesis_takes_no_segment(capsys):
    import importlib.util as util

    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "research"
        / "portfolio_research.py"
    )
    spec = util.spec_from_file_location("portfolio_research_692", path)
    module = util.module_from_spec(spec)
    sys.modules["portfolio_research_692"] = module
    spec.loader.exec_module(module)
    hypothesis = next(iter(module.HYPOTHESES))
    with pytest.raises(SystemExit) as exit_info:
        module.main(
            [
                "--db",
                "x.db",
                "--out",
                "out",
                "--hypothesis",
                hypothesis,
                "--segment",
                "exploration:2004-02-11:2018-12-31",
                "--segment",
                "validation:2019-01-01:",
            ]
        )
    assert exit_info.value.code == 2
    assert "--hypothesis takes no --segment" in capsys.readouterr().err
