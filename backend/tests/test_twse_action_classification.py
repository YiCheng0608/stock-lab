"""Local details classification never changes persisted corporate-action identity."""
import copy
import hashlib
import json
import socket
from collections import UserDict
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app.api import _source_action_classification, instrument_detail
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import CorporateAction, Instrument, MarketBar, RawPayload, Signal, SignalEvaluation
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher

DAY = date(2026, 9, 4)
ROW = {"Code": "1101", "Date": "1150904", "Exdividend": "息"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in classification tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def classify(details, source="twse", exchange="TWSE", day=DAY, action_type="corporate_action"):
    instrument = Instrument(exchange=exchange, symbol="1101", name="synthetic")
    item = CorporateAction(action_date=day, action_type=action_type, source=source, details_json=details)
    before = copy.deepcopy(details)
    result = _source_action_classification(item, instrument)
    assert details == before and item.action_type == action_type
    return result


@pytest.mark.parametrize("raw,kind,label", [
    ("息", "ex_dividend", "除息"), ("權", "ex_right", "除權"),
    ("權息", "ex_right_and_dividend", "除權息"),
    (" \t息\n", "ex_dividend", "除息"),
])
@pytest.mark.parametrize("action_type", ["corporate_action", "ex_dividend", "split"])
def test_exact_enum_and_raw_string_preserved(raw, kind, label, action_type):
    result = classify(dict(ROW, Exdividend=raw, unrelated={"not": "evidence"}), action_type=action_type)
    assert result == {"kind": kind, "label": label, "raw": {"field": "Exdividend", "value": raw},
                      "reason": "trusted_twse_exact_fields"}


@pytest.mark.parametrize("details,source,exchange,reason", [
    (None, "unknown", "TWSE", "unsupported_source"),
    (ROW, "TWSE", "TWSE", "unsupported_source"),
    (ROW, "twse", "TPEx", "unsupported_source"),
    (None, "twse", "TWSE", "invalid_details"),
    ([], "twse", "TWSE", "invalid_details"),
    ([ROW], "twse", "TWSE", "invalid_details"),
    ("text", "twse", "TWSE", "invalid_details"),
    ({}, "twse", "TWSE", "invalid_details"),
    ({"股票代號": "1101", "除權息日期": "1150904", "除權息": "息"}, "twse", "TWSE", "missing_official_field"),
    (dict(ROW, Code="", 證券代號="wrong"), "twse", "TWSE", "missing_official_field"),
    (dict(ROW, Code="9999", 證券代號="1101"), "twse", "TWSE", "alias_conflict"),
    (dict(ROW, Code="9999", Exdividend="unknown"), "twse", "TWSE", "identity_mismatch"),
    (dict(ROW, Exdividend="除息"), "twse", "TWSE", "unknown_raw_value"),
    (dict(ROW, Exdividend="除權息"), "twse", "TWSE", "unknown_raw_value"),
    (dict(ROW, Exdividend="未知"), "twse", "TWSE", "unknown_raw_value"),
])
def test_reason_precedence_and_unknown_shape(details, source, exchange, reason):
    result = classify(details, source, exchange)
    assert result["kind"] == "unknown" and result["label"] == "未知"
    assert result["reason"] == reason
    raw = details.get("Exdividend") if isinstance(details, dict) else None
    assert result["raw"] == {"field": "Exdividend", "value": raw if isinstance(raw, str) else None}


@pytest.mark.parametrize("key", ["Code", "Date", "Exdividend"])
@pytest.mark.parametrize("value", [None, "", " \t", 0, False, [], {}])
def test_official_fields_must_be_nonblank_strings(key, value):
    assert classify(dict(ROW, **{key: value}))["reason"] == "missing_official_field"


@pytest.mark.parametrize("alias", ["股票代號", "證券代號", "除權息日期", "除權息"])
@pytest.mark.parametrize("value,reason", [
    (None, "trusted_twse_exact_fields"), (" ", "trusted_twse_exact_fields"),
    (0, "alias_conflict"), (False, "alias_conflict"), ([], "alias_conflict"), ({}, "alias_conflict"),
])
def test_blank_alias_ignored_other_nonstring_conflicts(alias, value, reason):
    assert classify(dict(ROW, **{alias: value}))["reason"] == reason


@pytest.mark.parametrize("alias,value,reason", [
    ("股票代號", " 1101 ", "trusted_twse_exact_fields"),
    ("證券代號", "1102", "alias_conflict"),
    ("除權息日期", " 1150904 ", "trusted_twse_exact_fields"),
    ("除權息日期", "2026-09-04", "alias_conflict"),
    ("除權息日期", "115/09/04", "alias_conflict"),
    ("除權息日期", "１１５０９０４", "alias_conflict"),
    ("除權息日期", "1150905", "alias_conflict"),
    ("除權息", " 息 ", "trusted_twse_exact_fields"),
    ("除權息", "除息", "alias_conflict"),
    ("除權息", "權", "alias_conflict"),
])
def test_alias_canonical_comparison(alias, value, reason):
    assert classify(dict(ROW, **{alias: value}))["reason"] == reason


@pytest.mark.parametrize("raw,day,known", [
    ("1150904", DAY, True), (" 1150904 ", DAY, True),
    ("1130229", date(2024, 2, 29), True), ("1150229", DAY, False),
    ("0000101", date(1911, 1, 1), True), ("9991231", date(2910, 12, 31), True),
    ("1150001", DAY, False), ("1151301", DAY, False),
    ("1150900", DAY, False), ("1150931", DAY, False),
    ("1150905", DAY, False), ("115090", DAY, False), ("01150904", DAY, False),
    ("2026-09-04", DAY, False), ("115/09/04", DAY, False),
    ("１１５０９０４", DAY, False), ("١١٥٠٩٠٤", DAY, False),
    ("11509０4", DAY, False), ("+150904", DAY, False),
])
def test_strict_ascii_roc_date_boundaries(raw, day, known):
    result = classify(dict(ROW, Date=raw), day=day)
    assert result["reason"] == ("trusted_twse_exact_fields" if known else "identity_mismatch")


def test_invalid_date_alias_precedence_and_mapping():
    assert classify(dict(ROW, Date="invalid", 除權息日期="1150904"))["reason"] == "alias_conflict"
    assert classify(dict(ROW, Date="invalid", 除權息日期="invalid"))["reason"] == "alias_conflict"
    assert classify(dict(ROW, Exdividend="unknown", 除權息="unknown"))["reason"] == "alias_conflict"
    assert classify(dict(ROW, Date="invalid", 除權息日期=None))["reason"] == "identity_mismatch"
    assert classify(dict(ROW, Date="invalid", Exdividend=None, 除權息日期="bad"))["reason"] == "missing_official_field"
    assert classify(UserDict(ROW))["kind"] == "ex_dividend"


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'classification.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def test_actual_api_additive_projection_isolated_readonly_constant_queries(database):
    with database() as db:
        instruments = [Instrument(exchange=e, symbol=s, name="synthetic")
                       for e, s in [("TWSE", "1101"), ("TPEx", "1101"), ("TWSE", "1102")]]
        db.add_all(instruments)
        db.flush()
        for inst in instruments:
            for kind in ("corporate_action", "ex_dividend", "split"):
                db.add(CorporateAction(instrument_id=inst.id, action_date=DAY, action_type=kind,
                                       cash_dividend=.125, reference_price=100, source="twse",
                                       details_json=dict(ROW, Code=inst.symbol)))
        db.commit()
        rows = list(db.scalars(select(CorporateAction).order_by(CorporateAction.id)))
        before = [(r.id, r.action_type, r.cash_dividend, copy.deepcopy(r.details_json), r.raw_payload_id) for r in rows]
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            for inst in instruments:
                result = instrument_detail(inst.symbol, exchange=inst.exchange, db=db)
                projected = result["corporate_actions"]
                assert len(projected) == 3
                for output in projected:
                    classification = output.pop("source_action_classification")
                    assert classification["kind"] == ("ex_dividend" if inst.exchange == "TWSE" else "unknown")
                    assert output == {"date": DAY.isoformat(), "type": output["type"], "cash_dividend": .125,
                                      "stock_dividend_ratio": None, "split_ratio": None, "reference_price": 100,
                                      "source": "twse", "data_as_of": None}
                assert {r["type"] for r in projected} == {"corporate_action", "ex_dividend", "split"}
            statements.clear()
            with database() as fresh:
                instrument_detail("1101", exchange="TWSE", db=fresh)
            query_count = len(statements)
            for offset in range(1, 20):
                db.add(CorporateAction(instrument_id=instruments[0].id, action_date=DAY-timedelta(days=offset),
                                       action_type="corporate_action", source="unknown", details_json=None))
            db.commit()
            statements.clear()
            with database() as fresh:
                many = instrument_detail("1101", exchange="TWSE", db=fresh)["corporate_actions"]
                assert not fresh.new and not fresh.dirty and not fresh.deleted
            assert len(many) == 22 and len(statements) == query_count
            assert all(r["source_action_classification"]["reason"] == "unsupported_source" for r in many[3:])
            assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
            assert not db.new and not db.dirty and not db.deleted
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert before == [(r.id, r.action_type, r.cash_dividend, r.details_json, r.raw_payload_id) for r in rows]


class ActionFetcher(FixtureFetcher):
    """Synthetic exact-field action and other feeds, not observed market evidence."""
    def __call__(self, url, **kwargs):
        if url == sources.TWSE_ACTION_ENDPOINT:
            self.calls.append(url)
            return [dict(ROW, CashDividend="0.125")]
        if url in (sources.TPEX_ACTION_ENDPOINT, sources.TPEX_SUSPEND_ENDPOINT):
            self.calls.append(url)
            return []
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [dict(r, Industry="01" if r["Code"] == "1101" else "24") for r in payload]
        return payload


def test_wholecollect_refetch_retains_identity_raw_and_two_consumers(database, monkeypatch):
    monkeypatch.setattr(pipeline, "SessionLocal", database)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    fetcher = ActionFetcher()
    adapter = sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher))
    assert pipeline.collect(DAY, adapter=adapter)["status"] == "success"

    def observe(key):
        with database() as db:
            inst = db.scalar(select(Instrument).where(Instrument.exchange == "TWSE", Instrument.symbol == "1101"))
            for day, price in [(DAY-timedelta(days=1), 100), (DAY, 99.875)]:
                bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == inst.id, MarketBar.trading_date == day))
                if bar is None:
                    bar = MarketBar(instrument_id=inst.id, trading_date=day, source="synthetic")
                    db.add(bar)
                bar.open = bar.high = bar.low = bar.close = bar.adj_close = price
                bar.volume = 1000
                bar.turnover = price*1000
            signal = Signal(signal_key=key, instrument_id=inst.id, signal_date=DAY-timedelta(days=1),
                            status="conditional", entry_type="breakout", breakout_price=100,
                            invalid_price=50, target_1=200, data_quality="complete")
            db.add(signal)
            db.commit()
            _, normalized, factor = pipeline._normalized_history_for_score_date(db, inst.id, DAY)
            pipeline._evaluate_signal_tracking(db, signal, evaluation_cutoff=DAY)
            db.commit()
            ev = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id))
            assert factor == pytest.approx(.99875, rel=0, abs=1e-12)
            assert ev.adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(.99875, rel=0, abs=1e-12)
            assert normalized[DAY-timedelta(days=1)]["close"] == pytest.approx(99.875)
            actions = list(db.scalars(select(CorporateAction).where(CorporateAction.instrument_id == inst.id)))
            assert len(actions) == 1 and actions[0].action_type == "corporate_action"
            output = instrument_detail("1101", exchange="TWSE", db=db)["corporate_actions"][0]
            assert output["type"] == "corporate_action"
            assert output["source_action_classification"]["kind"] == "ex_dividend"
            raw = db.get(RawPayload, actions[0].raw_payload_id)
            raw_bytes = Path(raw.payload_path).read_bytes()
            assert hashlib.sha256(raw_bytes).hexdigest() == raw.sha256
            assert json.loads(raw_bytes) == [dict(ROW, CashDividend="0.125")]
            return actions[0].id, raw.id, raw_bytes, ev.id, copy.deepcopy(ev.adjusted_ohlc_json)

    before = observe("before")
    calls = len(fetcher.calls)
    assert pipeline.collect(DAY, adapter=adapter)["idempotent_reuse"]
    assert len(fetcher.calls) == calls
    assert observe("reuse")[:3] == before[:3]
    assert pipeline.collect(DAY, adapter=adapter, force=True)["status"] == "success"
    assert observe("force")[:3] == before[:3]
    with database() as db:
        assert db.get(SignalEvaluation, before[3]).adjusted_ohlc_json == before[4]
        assert db.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
