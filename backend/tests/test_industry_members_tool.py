"""tools/research/industry_members.py: per-industry close quotes as monthly members (#779)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app import config, taxonomy

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "industry_members"


def _tool():
    path = ROOT / "tools" / "research" / "industry_members.py"
    spec = importlib.util.spec_from_file_location("industry_members", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["industry_members"] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()
# The tool's own names, before the fixture below swaps in the test's.
CONFIRMED_NAMES = tool.CATEGORY_NAMES
CONFIRMED_PERIODS = tool.CODE_PERIODS

PERIODS = (
    ("2014-12", "2015-01", tool.TWSE, ("01", "26")),
    ("2014-12", "2015-01", tool.TPEX, ("26", "31")),
)
NAMES = {
    tool.TWSE: {"01": frozenset({"水泥工業"}), "26": frozenset({"光電業"})},
    tool.TPEX: {"26": frozenset({"光電類"}), "31": frozenset({"其他電子類"})},
}


@pytest.fixture(autouse=True)
def _definitions(monkeypatch):
    monkeypatch.setattr(tool, "CODE_PERIODS", PERIODS)
    monkeypatch.setattr(tool, "CATEGORY_NAMES", NAMES)
    monkeypatch.setattr(tool, "PACE", {})


def _roc(day: date) -> str:
    return f"{day.year - 1911}年{day.month:02d}月{day.day:02d}日"


def twse(day: date, category: str, rows: list[tuple[str, str]]) -> bytes:
    title = f"{_roc(day)} 每日收盤行情({category})"
    table = {
        "title": title,
        "fields": ["證券代號", "證券名稱", "成交股數"],
        "data": [[symbol, name, "0"] for symbol, name in rows],
    }
    payload = {"stat": "OK", "date": day.strftime("%Y%m%d"), "tables": [{}, table]}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def twse_closed() -> bytes:
    return json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}).encode("utf-8")


def tpex(day: date, category: str, rows: list[tuple[str, str]]) -> bytes:
    table = {
        "title": "上櫃股票每日收盤行情(不含定價)",
        "date": tool.roc_slash(day),
        "category": category,
        "totalCount": len(rows),
        "fields": ["代號", "名稱", "收盤 "],
        "data": [[symbol, name, "1.00"] for symbol, name in rows],
    }
    return json.dumps({"tables": [table], "stat": "ok"}, ensure_ascii=False).encode()


# 2014-12-31 and 2015-01-30 are the last weekdays; 2015-01-30 answers no data
# here, so January's snapshot is 2015-01-29.
DEC, JAN_CLOSED, JAN = date(2014, 12, 31), date(2015, 1, 30), date(2015, 1, 29)


def answers() -> dict[str, bytes]:
    result = {}
    for day, members in (
        (DEC, {"tw01": [("1101", "台泥")], "tw26": [("2475", "華映")]}),
        (
            JAN,
            {
                "tw01": [("1101", "台泥")],
                "tw26": [("2475", "華映"), ("3008", "大立光")],
            },
        ),
    ):
        result[tool.url_for(tool.TWSE, day, "01")] = twse(
            day, "水泥工業", members["tw01"]
        )
        result[tool.url_for(tool.TWSE, day, "26")] = twse(
            day, "光電業", members["tw26"]
        )
        result[tool.url_for(tool.TPEX, day, "26")] = tpex(
            day, "光電類", [("3105", "穩懋")]
        )
        result[tool.url_for(tool.TPEX, day, "31")] = tpex(
            day, "其他電子類", [("8183", "精星"), ("3093", "港建")]
        )
    result[tool.url_for(tool.TWSE, JAN_CLOSED, "01")] = twse_closed()
    return result


class FakeSource:
    """Answers from ``table``; URLs containing ``failing`` get ``status``."""

    def __init__(
        self, table: dict[str, bytes], status: int = 200, failing: str = ""
    ) -> None:
        self.table = table
        self.status = status
        self.failing = failing
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        if self.status != 200 and self.failing in url:
            return tool.Fetched(self.status, b"")
        return tool.Fetched(200, self.table[url])


def _daytime():
    return datetime(2026, 11, 16, 2, 0, tzinfo=timezone.utc)  # 10:00 Taipei


def _fetch(out: Path, source: FakeSource, sleeps: list[float] | None = None):
    return tool.fetch(
        "2014-12",
        "2015-01",
        out,
        get=source,
        now=_daytime,
        sleep=(sleeps.append if sleeps is not None else lambda seconds: None),
    )


def test_the_stored_answers_parse():
    day = date(2015, 1, 5)
    answer = tool.parse_twse(
        (FIXTURES / "twse_20150105_26.json").read_bytes(), day, "26"
    )
    assert answer.category == "光電業"
    assert answer.rows == (("2409", "友達"), ("2475", "華映"), ("3008", "大立光"))
    answer = tool.parse_tpex(
        (FIXTURES / "tpex_20150105_31.json").read_bytes(), day, "31"
    )
    assert answer.category == "其他電子類"
    assert answer.rows == (("3093", "港建"), ("3131", "弘塑"), ("8183", "精星"))


def test_only_codes_named_empty_may_answer_no_category(monkeypatch):
    # TPEx 2023-06-30 se=33 (農業科技) answers its rows with category "".
    content = (FIXTURES / "tpex_20230630_33.json").read_bytes()
    day = date(2023, 6, 30)
    with pytest.raises(tool.AnswerError, match="has no category"):
        tool.parse_tpex(content, day, "33")
    names = {**NAMES, tool.TPEX: {**NAMES[tool.TPEX], "33": frozenset({""})}}
    monkeypatch.setattr(tool, "CATEGORY_NAMES", names)
    answer = tool.parse_tpex(content, day, "33")
    assert answer.category is None
    assert [symbol for symbol, _ in answer.rows] == ["1240", "4171", "6508", "6578"]
    # Another code answering an empty category still fails.
    with pytest.raises(tool.AnswerError, match="has no category"):
        tool.parse_tpex(content, day, "31")


def test_the_confirmed_names_let_only_tpex_33_and_34_be_empty():
    empty = {
        (exchange, code)
        for exchange, table in CONFIRMED_NAMES.items()
        for code, names in table.items()
        if "" in names
    }
    assert empty == {(tool.TPEX, "33"), (tool.TPEX, "34")}
    for exchange, table in CONFIRMED_NAMES.items():
        assert set(table) <= set(tool.GROUP_LABELS[exchange])


def test_a_sweep_may_ask_only_some_codes(tmp_path):
    source = FakeSource(answers())
    summary = tool.sweep(
        ["2014-12"],
        tmp_path,
        only=[(tool.TPEX, "31")],
        get=source,
        now=_daytime,
        sleep=lambda seconds: None,
    )
    # The day probe, then TPEx 31 only.
    assert summary["sent"] == {tool.TWSE: 1, tool.TPEX: 1}
    assert source.urls[-1] == tool.url_for(tool.TPEX, DEC, "31")
    with pytest.raises(ValueError, match="not a known code"):
        tool.sweep(["2014-12"], tmp_path, only=[(tool.TWSE, "99")], get=source)


def test_an_answer_for_another_day_is_refused():
    day = date(2015, 1, 6)
    with pytest.raises(tool.AnswerError, match="reports date"):
        tool.parse_twse((FIXTURES / "twse_20150105_26.json").read_bytes(), day, "26")
    with pytest.raises(tool.AnswerError, match="reports date"):
        tool.parse_tpex((FIXTURES / "tpex_20150105_31.json").read_bytes(), day, "31")


def test_a_refusal_or_an_empty_body_is_an_error():
    day = date(2015, 1, 5)
    for content in (b"", b"<html>THE PAGE CANNOT BE ACCESSED</html>", b"not json"):
        with pytest.raises(tool.AnswerError):
            tool.parse_twse(content, day, "26")


MAINTENANCE = (
    '<!DOCTYPE html><html lang="zh-Hant-tw"><head><meta charset="utf-8">'
    "<title>網站維護中 - 臺灣證券交易所</title></head><body></body></html>"
).encode()


def test_a_maintenance_page_is_one_failure_not_a_block():
    with pytest.raises(tool.AnswerError, match="maintenance") as caught:
        tool.parse_twse(MAINTENANCE, date(2016, 12, 30), "01")
    assert not isinstance(caught.value, tool.Blocked)
    with pytest.raises(tool.Blocked):
        tool.parse_twse("<p>查詢過於頻繁</p>".encode(), date(2016, 12, 30), "01")


@pytest.mark.parametrize("answer", ["status", "page"])
def test_the_first_refusal_stops_the_run(tmp_path, answer):
    table = answers()
    url = tool.url_for(tool.TPEX, DEC, "26")
    table[url] = "<html>查詢過於頻繁</html>".encode()

    class Refusing(FakeSource):
        def __call__(self, asked):
            if answer == "status" and asked == url:
                self.urls.append(asked)
                return tool.Fetched(429, b"")
            return super().__call__(asked)

    source = Refusing(table)
    summary = _fetch(tmp_path, source)
    assert summary["stopped"] and "TPEx: blocked" in summary["stopped"]
    assert summary["failed"] == 1
    # TPEx asks 26 first: nothing after the refusal.
    assert [asked for asked in source.urls if "tpex" in asked] == [url]


def test_a_maintenance_page_does_not_stop_the_run(tmp_path):
    table = answers()
    table[tool.url_for(tool.TPEX, DEC, "26")] = MAINTENANCE
    summary = _fetch(tmp_path, FakeSource(table))
    assert summary["stopped"] is None and summary["failed"] == 1
    assert summary["sent"][tool.TPEX] == 4


def test_the_confirmed_code_periods_cover_every_month():
    periods = CONFIRMED_PERIODS
    for exchange in tool.EXCHANGES:
        covered = [
            month
            for first, last, market, _ in periods
            if market == exchange
            for month in tool.months(first, last)
        ]
        assert covered == tool.months("2013-01", "2024-09")
    by_month = {
        (month, market): set(codes)
        for first, last, market, codes in periods
        for month in tool.months(first, last)
    }
    assert "19" not in by_month[("2013-01", tool.TWSE)]
    assert len(by_month[("2013-01", tool.TWSE)]) == 32
    assert "08" not in by_month[("2013-01", tool.TPEX)]

    def added(month, before):
        return by_month[(month, tool.TPEX)] - by_month[(before, tool.TPEX)]

    assert added("2014-01", "2013-12") == {"32"}
    assert added("2016-09", "2016-08") == {"33"}
    assert added("2018-03", "2018-02") == {"34"}
    assert added("2022-06", "2022-07") == {"11"}
    assert added("2023-06", "2023-07") == {"18", "34"}
    assert added("2023-07", "2023-06") == {"35", "36", "37", "38"}
    for (month, market), codes in by_month.items():
        assert codes <= set(CONFIRMED_NAMES[market]), (month, market)


def test_labels_and_ids_are_the_products():
    product = taxonomy.INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE
    assert tool.GROUP_LABELS[tool.TWSE] == dict(product["TWSE"])
    # TPEx 18 and 34 ended on 2023-07-03; the product no longer has them.
    tpex_labels = dict(tool.GROUP_LABELS[tool.TPEX])
    assert tpex_labels.pop("18") == "Wholesale and Retail"
    assert tpex_labels.pop("34") == "E-commerce"
    assert tpex_labels == dict(product["TPEX"])
    for table in tool.GROUP_LABELS.values():
        for label in table.values():
            assert tool.group_id(label) == taxonomy.canonical_group_id(
                "industry", label
            )


def test_depositary_receipts_and_management_stocks_are_no_group():
    for table in tool.GROUP_LABELS.values():
        assert not {"80", "91", "9299"} & set(table)


def test_fetch_then_build_gives_members_merged_across_markets(tmp_path):
    source = FakeSource(answers())
    summary = _fetch(tmp_path, source)
    assert summary["stopped"] is None and summary["failed"] == 0
    assert summary["snapshot_days"] == 2
    # Three day probes (Dec 31, Jan 30 closed, Jan 29), one more TWSE code and
    # two TPEx codes on each of the two days.
    assert summary["sent"] == {tool.TWSE: 5, tool.TPEX: 4}
    result = tool.build(tmp_path, "2014-12", "2015-01", ["build"])
    rows = json.loads((tmp_path / tool.TABLE_NAME).read_text(encoding="utf-8"))["rows"]
    assert (
        len(rows) == result["yearly"]["2014"]["rows"] + result["yearly"]["2015"]["rows"]
    )
    january = tool.members_on(rows, JAN)
    assert {row[0] for row in january} == {"2015-01-29"}
    optoelectronics = {row[6] for row in january if row[4] == "Optoelectronics"}
    assert optoelectronics == {"2475", "3008", "3105"}
    ids = {row[5] for row in january if row[4] == "Optoelectronics"}
    assert ids == {taxonomy.canonical_group_id("industry", "Optoelectronics")}
    # A stock later delisted, and one with no trade that day, are members.
    assert ["2015-01-29", "TPEx", "31", "其他電子類", "Other Electronics"] == january[
        [row[6] for row in january].index("8183")
    ][:5]
    assert "3093" in {row[6] for row in january}
    manifest = json.loads((tmp_path / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert (
        manifest["sha256"]
        == hashlib.sha256((tmp_path / tool.TABLE_NAME).read_bytes()).hexdigest()
    )
    assert manifest["definitions_sha256"] == tool.definitions_sha256()
    assert len(manifest["answers"]) == 8


def test_twse_35_to_38_before_2023_07_03_are_flagged_retroactive():
    assert tool.retroactive(tool.TWSE, "37", "2013-01-31")
    assert tool.retroactive(tool.TWSE, "35", "2023-06-30")
    assert not tool.retroactive(tool.TWSE, "35", "2023-07-31")
    assert not tool.retroactive(tool.TWSE, "20", "2013-01-31")
    assert not tool.retroactive(tool.TPEX, "35", "2013-01-31")


def test_the_table_flags_retroactive_rows(tmp_path, monkeypatch):
    # The fixture's TWSE 26 stands in for 35-38; the flag ends before January.
    monkeypatch.setattr(tool, "RETROACTIVE_CODES", {tool.TWSE: frozenset({"26"})})
    monkeypatch.setattr(tool, "RETROACTIVE_BEFORE", "2015-01-01")
    _fetch(tmp_path, FakeSource(answers()))
    result = tool.build(tmp_path, "2014-12", "2015-01", ["build"])
    document = json.loads((tmp_path / tool.TABLE_NAME).read_text(encoding="utf-8"))
    assert document["fields"][-1] == "retroactive_category"
    flagged = [row for row in document["rows"] if row[8]]
    assert [(row[0], row[1], row[2], row[6]) for row in flagged] == [
        ("2014-12-31", tool.TWSE, "26", "2475")
    ]
    assert result["retroactive_rows"] == 1
    manifest = json.loads((tmp_path / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["retroactive_rows"] == 1
    assert manifest["definitions"]["retroactive_codes"] == {tool.TWSE: ["26"]}


def test_an_empty_cement_table_is_a_day_without_trading(tmp_path):
    # 2014-02-28 (a holiday) answered stat OK with an empty cement table.
    table = answers()
    table[tool.url_for(tool.TWSE, JAN_CLOSED, "01")] = twse(JAN_CLOSED, "水泥工業", [])
    summary = _fetch(tmp_path, FakeSource(table))
    assert summary["days"]["2015-01"] == JAN.isoformat()
    tool.build(tmp_path, "2014-12", "2015-01", ["build"])
    # An empty table of another category is not a closed day.
    assert not tool.closed(tool.Answer("光電業", ()))
    assert tool.closed(tool.Answer(None, (), no_data=True))


def test_a_snapshot_is_used_from_its_own_day():
    rows = [
        ["2014-12-31", "TWSE", "26", "光電業", "Optoelectronics", "x", "2475", "華映"],
        [
            "2015-01-29",
            "TWSE",
            "26",
            "光電業",
            "Optoelectronics",
            "x",
            "3008",
            "大立光",
        ],
    ]
    assert tool.members_on(rows, date(2014, 12, 30)) == []
    assert [row[6] for row in tool.members_on(rows, date(2014, 12, 31))] == ["2475"]
    assert [row[6] for row in tool.members_on(rows, date(2015, 1, 28))] == ["2475"]
    assert [row[6] for row in tool.members_on(rows, date(2015, 1, 29))] == ["3008"]


def test_a_rerun_sends_nothing_and_builds_the_same_bytes(tmp_path):
    _fetch(tmp_path, FakeSource(answers()))
    first = tool.build(tmp_path, "2014-12", "2015-01", ["build"])["sha256"]
    again = FakeSource(answers())
    summary = _fetch(tmp_path, again)
    assert again.urls == [] and summary["sent"] == {tool.TWSE: 0, tool.TPEX: 0}
    assert tool.build(tmp_path, "2014-12", "2015-01", ["build"])["sha256"] == first
    assert (
        first == hashlib.sha256((tmp_path / tool.TABLE_NAME).read_bytes()).hexdigest()
    )


def test_each_host_waits_five_seconds_between_requests(tmp_path):
    sleeps: list[float] = []
    summary = _fetch(tmp_path, FakeSource(answers()), sleeps)
    sent = sum(summary["sent"].values())
    # The first request to each host does not wait.
    assert len(sleeps) == sent - 2
    assert min(sleeps) > tool.MIN_INTERVAL_SECONDS - 0.5


def test_three_failures_in_a_row_stop_the_run(tmp_path):
    source = FakeSource(answers(), status=503, failing="tpex.org.tw")
    summary = _fetch(tmp_path, source)
    assert summary["stopped"] and "TPEx: 3 failed answers" in summary["stopped"]
    assert sum("tpex.org.tw" in url for url in source.urls) == 3
    assert not (tmp_path / tool.RAW_DIR / tool.TPEX).exists()
    log = (tmp_path / tool.REQUESTS_NAME).read_text(encoding="utf-8").splitlines()
    assert sum(json.loads(line).get("outcome") == "failed" for line in log) == 3
    assert summary["failed"] == 3
    assert (
        tool.main(
            ["build", "--start", "2014-12", "--end", "2015-01", "--out", str(tmp_path)]
        )
        == 1
    )


def test_a_failed_answer_keeps_its_body_and_is_counted(tmp_path):
    # TPEx 2023-06-30 se=33/34 answered 200 with rows but no category.
    table = answers()
    nameless = json.loads(table[tool.url_for(tool.TPEX, DEC, "31")])
    nameless["tables"][0]["category"] = ""
    body = json.dumps(nameless, ensure_ascii=False).encode()
    table[tool.url_for(tool.TPEX, DEC, "31")] = body
    summary = _fetch(tmp_path, FakeSource(table))
    assert summary["stopped"] is None and summary["failed"] == 1
    assert not tool.raw_path(tmp_path, tool.TPEX, DEC, "31").exists()
    kept = tmp_path / tool.FAILED_DIR / tool.TPEX / "20141231" / "31.1.body"
    assert kept.read_bytes() == body
    log = [
        json.loads(line)
        for line in (tmp_path / tool.REQUESTS_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    failed = [entry for entry in log if entry.get("outcome") == "failed"]
    assert len(failed) == 1 and "has no category" in failed[0]["error"]
    assert failed[0]["body"] == "failed/TPEx/20141231/31.1.body"
    assert failed[0]["sha256"] == hashlib.sha256(body).hexdigest()
    assert log[-1]["event"] == "summary" and log[-1]["failed"] == 1
    # A second failure of the same answer keeps the first body.
    _fetch(tmp_path, FakeSource(table))
    assert kept.read_bytes() == body
    assert (kept.parent / "31.2.body").read_bytes() == body


@pytest.mark.parametrize(
    ("taipei", "wait"),
    [
        ("2026-11-16T20:29:59", 0),
        ("2026-11-16T20:30:00", 3 * 3600),
        ("2026-11-16T23:29:00", 60),
        ("2026-11-16T23:30:00", 0),
        ("2026-11-16T07:59:59", 0),
        ("2026-11-16T08:15:00", 45 * 60),
        ("2026-11-16T09:00:00", 0),
    ],
)
def test_no_request_in_the_blackouts(taipei, wait):
    now = datetime.fromisoformat(taipei).replace(tzinfo=tool.TAIPEI)
    assert tool.blackout_seconds(now) == wait


def test_a_request_in_a_blackout_waits_for_its_end(tmp_path):
    clock = [datetime(2026, 11, 16, 12, 45, tzinfo=timezone.utc)]  # 20:45 Taipei
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] = datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc)

    source = FakeSource(answers())
    tool.fetch(
        "2014-12", "2015-01", tmp_path, get=source, now=lambda: clock[0], sleep=sleep
    )
    assert sleeps[0] == 2 * 3600 + 45 * 60


def _build_error(tmp_path, match):
    with pytest.raises(tool.BuildError, match=match):
        tool.build_rows(tmp_path, "2014-12", "2015-01")


def test_a_category_name_not_confirmed_fails_the_build(tmp_path, monkeypatch):
    _fetch(tmp_path, FakeSource(answers()))
    monkeypatch.setattr(
        tool,
        "CATEGORY_NAMES",
        {**NAMES, tool.TPEX: {**NAMES[tool.TPEX], "31": frozenset({"其他電子業"})}},
    )
    _build_error(tmp_path, "其他電子類")


def test_a_listed_code_without_rows_fails_the_build(tmp_path):
    # fetch no longer stores it, but a raw stored by a sweep or an older fetch
    # still has to fail the build.
    _fetch(tmp_path, FakeSource(answers()))
    path = tool.raw_path(tmp_path, tool.TPEX, JAN, "31")
    path.write_bytes(tpex(JAN, "其他電子類", []))
    _build_error(tmp_path, "answered no rows")


def test_a_missing_answer_fails_the_build(tmp_path):
    _fetch(tmp_path, FakeSource(answers()))
    tool.raw_path(tmp_path, tool.TPEX, DEC, "26").unlink()
    _build_error(tmp_path, "TPEx 2014-12-31 26 is not in the raw")
    _fetch(tmp_path, FakeSource(answers()))
    tool.raw_path(tmp_path, tool.TWSE, JAN_CLOSED, "01").unlink()
    _build_error(tmp_path, "2015-01-30 type 01 is not in the raw")


def test_a_month_no_period_covers_is_refused_before_any_request(tmp_path):
    source = FakeSource(answers())
    with pytest.raises(ValueError, match="code periods cover"):
        tool.fetch(
            "2014-11",
            "2015-01",
            tmp_path,
            get=source,
            now=_daytime,
            sleep=lambda s: None,
        )
    assert source.urls == []


def test_a_code_missing_for_a_month_in_the_middle_fails_the_build(
    tmp_path, monkeypatch
):
    nov = date(2014, 11, 28)
    table = answers()
    table[tool.url_for(tool.TWSE, nov, "01")] = twse(
        nov, "水泥工業", [("1101", "台泥")]
    )
    table[tool.url_for(tool.TWSE, nov, "26")] = twse(nov, "光電業", [("2475", "華映")])
    table[tool.url_for(tool.TPEX, nov, "26")] = tpex(nov, "光電類", [("3105", "穩懋")])
    table[tool.url_for(tool.TPEX, nov, "31")] = tpex(
        nov, "其他電子類", [("8183", "精星")]
    )
    monkeypatch.setattr(
        tool,
        "CODE_PERIODS",
        (
            ("2014-11", "2015-01", tool.TWSE, ("01", "26")),
            ("2014-11", "2014-11", tool.TPEX, ("26", "31")),
            ("2014-12", "2014-12", tool.TPEX, ("26",)),
            ("2015-01", "2015-01", tool.TPEX, ("26", "31")),
        ),
    )
    tool.fetch(
        "2014-11",
        "2015-01",
        tmp_path,
        get=FakeSource(table),
        now=_daytime,
        sleep=lambda seconds: None,
    )
    with pytest.raises(tool.BuildError, match=r"TPEx 31 has a gap: \['2014-12'\]"):
        tool.build_rows(tmp_path, "2014-11", "2015-01")


def test_a_sweep_asks_every_known_code_and_the_report_lists_them(tmp_path):
    table = answers()
    for exchange in tool.EXCHANGES:
        for code in tool.GROUP_LABELS[exchange]:
            url = tool.url_for(exchange, DEC, code)
            if url not in table:
                table[url] = (
                    json.dumps(
                        {"stat": "OK", "date": "20141231", "tables": []}
                    ).encode()
                    if exchange == tool.TWSE
                    else tpex(DEC, "", [])
                )
    source = FakeSource(table)
    summary = tool.sweep(
        ["2014-12"], tmp_path, get=source, now=_daytime, sleep=lambda s: None
    )
    assert summary["sent"] == {
        tool.TWSE: len(tool.GROUP_LABELS[tool.TWSE]),
        tool.TPEX: len(tool.GROUP_LABELS[tool.TPEX]),
    }
    entries = {(e["exchange"], e["code"]): e for e in tool.report(tmp_path)}
    assert entries[(tool.TWSE, "26")]["category"] == "光電業"
    assert entries[(tool.TWSE, "35")] == {
        "exchange": tool.TWSE,
        "date": "2014-12-31",
        "code": "35",
        "category": None,
        "rows": 0,
        "no_data": False,
    }
    assert entries[(tool.TPEX, "31")]["rows"] == 2


def _monthly(first: str, last: str, rows_from: str | None, rows_until: str | None):
    """Answers for TWSE 01 and TPEx 34 on each month's last weekday."""

    table = {}
    for month in tool.months(first, last):
        day = tool.weekdays_back(month)[0]
        table[tool.url_for(tool.TWSE, day, "01")] = twse(
            day, "水泥工業", [("1101", "台泥")]
        )
        present = (rows_from is None or month >= rows_from) and (
            rows_until is None or month <= rows_until
        )
        rows = [("8477", "創業家")] if present else []
        table[tool.url_for(tool.TPEX, day, "34")] = tpex(day, "電子商務", rows)
    return table


@pytest.mark.parametrize(
    ("present", "absent", "rows_from", "rows_until", "expected"),
    [
        ("2013-01", "2024-09", None, "2023-06", {"last_with_rows": "2023-06"}),
        ("2024-09", "2013-01", "2016-05", None, {"first_with_rows": "2016-05"}),
    ],
)
def test_bisect_finds_the_boundary_month(
    tmp_path, present, absent, rows_from, rows_until, expected
):
    source = FakeSource(_monthly("2013-01", "2024-09", rows_from, rows_until))
    result = tool.bisect(
        tool.TPEX,
        "34",
        present,
        absent,
        tmp_path,
        get=source,
        now=_daytime,
        sleep=lambda s: None,
    )
    assert result["stopped"] is False
    assert {key: result[key] for key in expected} == expected
    # 141 months: at most eight steps, two requests each, after both ends.
    assert len(result["steps"]) <= 8
    assert len(source.urls) <= 2 * (len(result["steps"]) + 2)


def test_bisect_refuses_ends_that_do_not_differ(tmp_path):
    source = FakeSource(_monthly("2013-01", "2024-09", None, None))
    with pytest.raises(tool.AnswerError, match="rows=True"):
        tool.bisect(
            tool.TPEX,
            "34",
            "2013-01",
            "2024-09",
            tmp_path,
            get=source,
            now=_daytime,
            sleep=lambda s: None,
        )


def _research_db(path: Path, entries: list[tuple[str, str, str, bytes]]) -> None:
    """A research DB with only ``raw_payloads``: (endpoint, data_as_of, path, bytes)."""

    import sqlite3

    connection = sqlite3.connect(path)
    connection.execute(
        "create table raw_payloads (id integer primary key, ingestion_run_id integer, "
        "source text, endpoint text, payload_path text, sha256 text, "
        "data_as_of text, collected_at text)"
    )
    for endpoint, as_of, payload_path, content in entries:
        connection.execute(
            "insert into raw_payloads (source, endpoint, payload_path, sha256, "
            "data_as_of) values ('x', ?, ?, ?, ?)",
            (endpoint, payload_path, hashlib.sha256(content).hexdigest(), as_of),
        )
    connection.commit()
    connection.close()


def test_completeness_lists_common_stocks_in_no_industry(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _fetch(out, FakeSource(answers()))
    root = tmp_path / "raw"
    # The TPEx row keeps its old Windows path: payload_file maps it here.
    monkeypatch.setattr(config, "RAW_DIR", root)
    twse_all = json.dumps(
        {
            "tables": [
                {
                    "title": f"{_roc(JAN)} 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
                    "data": [
                        ["1101", "台泥"],
                        ["2475", "華映"],
                        ["3008", "大立光"],
                        ["2330", "台積電"],
                        ["0050", "元大台灣50"],
                        ["9105", "泰金寶-DR"],
                        ["2881A", "富邦特"],
                    ],
                }
            ]
        },
        ensure_ascii=False,
    ).encode()
    tpex_all = json.dumps(
        {
            "tables": [
                {
                    "title": "上櫃股票行情",
                    "data": [["8183", "精星"], ["3093", "港建"], ["3105", "穩懋"]],
                }
            ]
        },
        ensure_ascii=False,
    ).encode()
    (root / "twse" / "2026" / "11" / "15").mkdir(parents=True)
    (root / "twse" / "2026" / "11" / "15" / "a.json").write_bytes(twse_all)
    (root / "tpex").mkdir()
    (root / "tpex" / "b.json").write_bytes(tpex_all)
    db = tmp_path / "stock.db"
    _research_db(
        db,
        [
            (
                tool.TWSE_ALL_URL.format(yyyymmdd="20150129"),
                "2015-01-29",
                str(root / "twse" / "2026" / "11" / "15" / "a.json"),
                twse_all,
            ),
            (
                tool.TPEX_ALL_URL,
                "2015-01-29",
                "C:\\Users\\YiCheng\\stock-lab-data\\raw\\tpex\\b.json",
                tpex_all,
            ),
        ],
    )
    result = tool.build(out, "2014-12", "2015-01", ["build"], research_db=db)
    assert result["completeness"] == {
        "checked": 2,
        "no_stored_answer": 2,
        "raw_missing": 0,
        "unchecked": 2,
        "days_with_missing": 1,
    }
    manifest = json.loads((out / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
    days = {(d["exchange"], d["date"]): d for d in manifest["completeness"]["days"]}
    # 2330 is in no table fetched here; ETFs, DRs and preferred shares are not counted.
    assert days[(tool.TWSE, "2015-01-29")]["missing"] == ["2330"]
    assert days[(tool.TPEX, "2015-01-29")]["missing"] == []
    assert days[(tool.TWSE, "2014-12-31")] == {
        "exchange": tool.TWSE,
        "date": "2014-12-31",
        "checked": False,
        "reason": "no_stored_answer",
    }
    # The table itself does not depend on the check.
    plain = tmp_path / "plain"
    _fetch(plain, FakeSource(answers()))
    assert (
        tool.build(plain, "2014-12", "2015-01", ["build"])["sha256"] == result["sha256"]
    )


def test_a_stored_answer_whose_file_is_not_found_fails_the_build(tmp_path):
    # The research DB's paths are /data/raw/...: mounted elsewhere, no file is
    # found, and every day used to count as unchecked with nothing missing.
    out = tmp_path / "out"
    _fetch(out, FakeSource(answers()))
    content = b"{}"
    db = tmp_path / "stock.db"
    _research_db(
        db,
        [
            (
                tool.TWSE_ALL_URL.format(yyyymmdd="20150129"),
                "2015-01-29",
                "/data/raw/twse/2026/11/16/not-here.json",
                content,
            )
        ],
    )
    with pytest.raises(tool.BuildError, match="1 days have a stored answer"):
        tool.build(out, "2014-12", "2015-01", ["build"], research_db=db)
    assert not (out / tool.TABLE_NAME).exists()
    assert not (out / tool.MANIFEST_NAME).exists()
    args = ["build", "--start", "2014-12", "--end", "2015-01", "--out", str(out)]
    assert tool.main([*args, "--research-db", str(db)]) == 1
    result = tool.build(
        out, "2014-12", "2015-01", ["build"], research_db=db, allow_raw_missing=True
    )
    assert result["completeness"]["raw_missing"] == 1
    assert result["completeness"]["no_stored_answer"] == 3
    assert result["completeness"]["checked"] == 0
    manifest = json.loads((out / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
    day = next(
        d for d in manifest["completeness"]["days"] if d.get("reason") == "raw_missing"
    )
    assert day["payload_path"] == "/data/raw/twse/2026/11/16/not-here.json"


def test_a_research_db_that_is_not_there_writes_nothing(tmp_path):
    out = tmp_path / "out"
    _fetch(out, FakeSource(answers()))
    with pytest.raises(tool.BuildError, match="is not a file"):
        tool.build(
            out, "2014-12", "2015-01", ["build"], research_db=tmp_path / "none.db"
        )
    assert not (out / tool.TABLE_NAME).exists()


def test_an_empty_category_is_an_empty_string_in_the_table(tmp_path, monkeypatch):
    names = {**NAMES, tool.TPEX: {**NAMES[tool.TPEX], "31": frozenset({""})}}
    monkeypatch.setattr(tool, "CATEGORY_NAMES", names)
    table = answers()
    for day in (DEC, JAN):
        url = tool.url_for(tool.TPEX, day, "31")
        table[url] = tpex(day, "", [("8183", "精星"), ("3093", "港建")])
    _fetch(tmp_path, FakeSource(table))
    tool.build(tmp_path, "2014-12", "2015-01", ["build"])
    document = json.loads((tmp_path / tool.TABLE_NAME).read_text(encoding="utf-8"))
    categories = {row[3] for row in document["rows"] if row[2] == "31"}
    assert categories == {""}
    assert all(isinstance(row[3], str) for row in document["rows"])


def test_fetch_fails_a_listed_code_that_answers_no_rows(tmp_path):
    table = answers()
    url = tool.url_for(tool.TWSE, DEC, "26")
    table[url] = twse(DEC, "光電業", [])
    summary = _fetch(tmp_path, FakeSource(table))
    assert summary["failed"] == 1 and summary["stopped"] is None
    assert not tool.raw_path(tmp_path, tool.TWSE, DEC, "26").exists()
    kept = tmp_path / tool.FAILED_DIR / tool.TWSE / "20141231" / "26.1.body"
    assert kept.read_bytes() == table[url]
    # sweep and bisect still store an answer without rows.
    other = tmp_path / "sweep"
    tool.sweep(
        ["2014-12"],
        other,
        only=[(tool.TWSE, "26")],
        get=FakeSource(table),
        now=_daytime,
        sleep=lambda seconds: None,
    )
    assert tool.raw_path(other, tool.TWSE, DEC, "26").is_file()


def test_twse_no_data_for_a_listed_code_fails_the_build(tmp_path):
    _fetch(tmp_path, FakeSource(answers()))
    tool.raw_path(tmp_path, tool.TWSE, DEC, "26").write_bytes(twse_closed())
    with pytest.raises(tool.BuildError, match="answered no rows"):
        tool.build(tmp_path, "2014-12", "2015-01", ["build"])


def test_a_raw_file_with_another_sha256_is_not_used(tmp_path):
    path = tmp_path / "a.json"
    path.write_bytes(b"{}")
    assert tool._raw_file(str(path), "0" * 64) is None
    assert tool._raw_file(str(path), hashlib.sha256(b"{}").hexdigest()) == path
    assert tool._raw_file(str(tmp_path / "missing.json"), "0" * 64) is None
