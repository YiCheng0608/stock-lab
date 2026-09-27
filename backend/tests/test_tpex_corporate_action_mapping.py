"""TPEx action input units; paid subscriptions remain outside the legacy factor."""
import copy
import hashlib
import json
import socket
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import CorporateAction, Instrument, MarketBar, RawPayload, Signal, SignalEvaluation
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher

DAY = date(2026, 9, 14)
# Exact response rows from https://www.tpex.org.tw/openapi/v1/tpex_exright_daily,
# captured 2026-09-13: HTTP SHA256
# db1f6e359e2bf39dd2d202e35da147c6d44c5b3585ae5d41dbcbe80ceb190975.
# Sep14 is a synthetic future as-of for replay, NOT historical availability.
SAVED = json.loads(r'''[
  {
    "Date": "1150914",
    "SecuritiesCompanyCode": "5278",
    "CompanyName": "尚凡*",
    "ClosePriceBeforeExRightsDiviend": "23.90",
    "ExRightsDiviendQuote": "23.63",
    "StockDividend": "0.000000",
    "CashDividend": "0.266182",
    "StockDividendPlusCashDividend": "0.266182",
    "ExRightsDiviend": "除息",
    "LimitUp": "25.95",
    "LimitDown": "21.30",
    "OpeningReferencePrice": "23.65",
    "DividendDeductedQuote": "23.63",
    "CashDivdend": "0.26618165",
    "StockDivdendThousandShares": "0.00000000",
    "CashCapitalIncreaseShares": "0",
    "SubscriptionPricePerShare": "0.00",
    "AllocatedForPublicUnderwriting": "0",
    "SubscribedByEmployees": "0",
    "SubscribedByExistingShareholders": "0",
    "SubscribedProRataThousandShares": "0.00000000"
  },
  {
    "Date": "1150914",
    "SecuritiesCompanyCode": "6204",
    "CompanyName": "艾華",
    "ClosePriceBeforeExRightsDiviend": "88.80",
    "ExRightsDiviendQuote": "88.30",
    "StockDividend": "0.000000",
    "CashDividend": "0.500000",
    "StockDividendPlusCashDividend": "0.500000",
    "ExRightsDiviend": "除息",
    "LimitUp": "97.10",
    "LimitDown": "79.50",
    "OpeningReferencePrice": "88.30",
    "DividendDeductedQuote": "88.30",
    "CashDivdend": "0.50000000",
    "StockDivdendThousandShares": "0.00000000",
    "CashCapitalIncreaseShares": "0",
    "SubscriptionPricePerShare": "0.00",
    "AllocatedForPublicUnderwriting": "0",
    "SubscribedByEmployees": "0",
    "SubscribedByExistingShareholders": "0",
    "SubscribedProRataThousandShares": "0.00000000"
  },
  {
    "Date": "1150914",
    "SecuritiesCompanyCode": "8423",
    "CompanyName": "保綠-KY",
    "ClosePriceBeforeExRightsDiviend": "18.35",
    "ExRightsDiviendQuote": "17.65",
    "StockDividend": "0.000000",
    "CashDividend": "0.700000",
    "StockDividendPlusCashDividend": "0.700000",
    "ExRightsDiviend": "除息",
    "LimitUp": "19.40",
    "LimitDown": "15.90",
    "OpeningReferencePrice": "17.65",
    "DividendDeductedQuote": "17.65",
    "CashDivdend": "0.70000000",
    "StockDivdendThousandShares": "0.00000000",
    "CashCapitalIncreaseShares": "0",
    "SubscriptionPricePerShare": "0.00",
    "AllocatedForPublicUnderwriting": "0",
    "SubscribedByEmployees": "0",
    "SubscribedByExistingShareholders": "0",
    "SubscribedProRataThousandShares": "0.00000000"
  }
]''')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in corporate-action mapping tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def actions(rows, as_of=DAY):
    return sources.TpexAdapter(lambda *args, **kwargs: rows).fetch_actions(as_of)


@pytest.mark.parametrize("fields,ratio,reference", [
    ({"StockDivdendThousandShares": "100", "ClosePriceBeforeExRightsDiviend": "100"}, .1, 100),
    ({"每仟股無償配股": "25.5", "除權息前收盤價": "88.80"}, .0255, 88.8),
    ({"StockDividend": "10", "權值": "10", "無償配股率": ".1",
      "OpeningReferencePrice": "90", "開始交易基準價": "90"}, None, None),
    ({}, None, None),
    ({"StockDivdendThousandShares": "", "ClosePriceBeforeExRightsDiviend": ""}, None, None),
    ({"StockDivdendThousandShares": "bad", "ClosePriceBeforeExRightsDiviend": "bad"}, None, None),
    ({"StockDivdendThousandShares": "0", "ClosePriceBeforeExRightsDiviend": "0"}, 0, 0),
    ({"StockDivdendThousandShares": "1.25", "ClosePriceBeforeExRightsDiviend": "23.90"}, .00125, 23.9),
    ({"StockDivdendThousandShares": "100", "每仟股無償配股": "200",
      "ClosePriceBeforeExRightsDiviend": "100", "除權息前收盤價": "200"}, .1, 100),
    ({"StockDivdendThousandShares": " ", "每仟股無償配股": "200",
      "ClosePriceBeforeExRightsDiviend": None, "除權息前收盤價": "200"}, .2, 200),
    ({"StockDivdendThousandShares": "bad", "每仟股無償配股": "200",
      "ClosePriceBeforeExRightsDiviend": "bad", "除權息前收盤價": "200"}, None, None),
])
def test_exact_units_alias_priority_and_wrong_alias_exclusion(fields, ratio, reference):
    row = {"Date": "1150914", "SecuritiesCompanyCode": "6204", **fields}
    record = actions([row])[0][0]
    assert record.stock_dividend_ratio == ratio
    assert record.reference_price == reference
    assert record.details == row


@pytest.mark.parametrize("value", [None, "", " ", "--", "---", "N/A", "bad", "1,000", "2.5", "0", "-1", "1e2", 25, 0.25])
def test_existing_number_parser_semantics_are_not_redefined(value):
    row = {"Date": "1150914", "SecuritiesCompanyCode": "6204",
           "StockDivdendThousandShares": value, "ClosePriceBeforeExRightsDiviend": value}
    record = actions([row])[0][0]
    existing = sources.parse_number(sources._text(row, "StockDivdendThousandShares"))
    assert record.stock_dividend_ratio == (existing / 1000 if existing is not None else None)
    assert record.reference_price == existing


def test_saved_rows_cutoff_cash_raw_order_and_provenance():
    before = copy.deepcopy(SAVED)
    assert actions(SAVED, date(2026, 9, 13))[0] == []
    records, payloads = actions(SAVED)
    assert [r.symbol for r in records] == ["5278", "6204", "8423"]
    assert [r.cash_dividend for r in records] == [.26618165, .5, .7]
    assert [r.reference_price for r in records] == [23.9, 88.8, 18.35]
    assert all(r.stock_dividend_ratio == 0 and r.action_type == "ex_dividend" for r in records)
    assert all(r.action_date == DAY and r.exchange == "TPEx" for r in records)
    assert [r.details for r in records] == SAVED == before
    raw = payloads[0]
    assert json.loads(raw.payload_path.read_text(encoding="utf-8")) == SAVED
    assert hashlib.sha256(raw.payload_path.read_bytes()).hexdigest() == raw.sha256
    assert all(r.payload_sha256 == raw.sha256 for r in records)
    # Prefer the precise per-share cash field over the displayed interest value.
    assert records[0].cash_dividend == float(SAVED[0]["CashDivdend"])


@pytest.mark.parametrize("row", [
    {"SecuritiesCompanyCode": "6204"},
    {"Date": "bad", "SecuritiesCompanyCode": "6204"},
    {"Date": "1150914"},
    {"Date": "1150915", "SecuritiesCompanyCode": "6204"},
])
def test_existing_identity_date_and_future_filters(row):
    assert actions([row])[0] == []


class ActionFetcher(FixtureFetcher):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def __call__(self, url, **kwargs):
        if url == sources.TPEX_ACTION_ENDPOINT:
            self.calls.append(url)
            return self.rows
        if url in (sources.TWSE_ACTION_ENDPOINT, sources.TPEX_SUSPEND_ENDPOINT):
            self.calls.append(url)
            return []
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            payload = [dict(r, Industry="01" if r["Code"] == "1101" else "24") for r in payload]

        def remap(value):
            if isinstance(value, list):
                return [remap(v) for v in value]
            if isinstance(value, dict):
                return {k: remap(v) for k, v in value.items()}
            if isinstance(value, str):
                if value == "7001":
                    return "6204"
                return value.replace("2026-09-04", "2026-09-14").replace("20260904", "20260914").replace("1150904", "1150914")
            return value
        return remap(payload)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'actions.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "0007_turnover_availability"
    engine.dispose()


def observe(factory, key, preclose, postclose):
    with factory() as db:
        instrument = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == "6204"))
        for day, price in [(DAY - timedelta(days=1), preclose), (DAY, postclose)]:
            bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument.id, MarketBar.trading_date == day))
            if bar is None:
                bar = MarketBar(instrument_id=instrument.id, trading_date=day, source="synthetic OHLC")
                db.add(bar)
            bar.open = bar.high = bar.low = bar.close = bar.adj_close = price
            bar.volume = 1000
            bar.turnover = price * 1000
        signal = Signal(signal_key=key, instrument_id=instrument.id, signal_date=DAY-timedelta(days=1),
                        status="conditional", entry_type="breakout", breakout_price=preclose,
                        invalid_price=preclose*.5, target_1=preclose*2, data_quality="complete")
        db.add(signal)
        db.commit()
        _, normalized, factor = pipeline._normalized_history_for_score_date(db, instrument.id, DAY)
        assert pipeline._evaluate_signal_tracking(db, signal, evaluation_cutoff=DAY) == (1, 2)
        db.commit()
        evaluation = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id))
        assert evaluation.adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(factor)
        assert normalized[DAY-timedelta(days=1)]["close"] == pytest.approx(preclose * factor)
        return evaluation.id, factor, evaluation.status


SCHEMA = {"Date": "1150914", "SecuritiesCompanyCode": "6204", "CashDividend": "5",
          "StockDividend": "8.636363636", "StockDivdendThousandShares": "100",
          "ClosePriceBeforeExRightsDiviend": "100", "OpeningReferencePrice": "86.36"}


@pytest.mark.parametrize("rows,preclose,oracle", [
    (SAVED, 88.8, (88.8-.5)/88.8),
    ([SCHEMA], 100, 95/110),
    ([{k: v for k, v in SCHEMA.items() if k != "ClosePriceBeforeExRightsDiviend"}], 100, 95/110),
], ids=["saved-full-body-selected-6204", "schema-free-plus-cash", "missing-preclose-bar-fallback"])
def test_collect_force_reuse_raw_fk_and_both_consumers(database, monkeypatch, rows, preclose, oracle):
    actual = sources.TpexAdapter.fetch_actions

    def old_mapping(self, as_of):
        records, payloads = actual(self, as_of)
        return [replace(r, stock_dividend_ratio=sources.parse_number(sources._text(r.details, "StockDividend", "權值", "無償配股率")),
                        reference_price=sources.parse_number(sources._text(r.details, "OpeningReferencePrice", "開始交易基準價")))
                for r in records], payloads

    fetcher = ActionFetcher(rows)
    adapter = sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher))
    with monkeypatch.context() as context:
        context.setattr(sources.TpexAdapter, "fetch_actions", old_mapping)
        assert pipeline.collect(DAY, adapter=adapter)["status"] == "success"
    old_id, old_factor, _ = observe(database, "old", preclose, preclose*oracle)
    with database() as db:
        action = db.scalar(select(CorporateAction))
        action_id, raw_id = action.id, action.raw_payload_id
        raw = db.get(RawPayload, raw_id)
        assert json.loads(Path(raw.payload_path).read_text(encoding="utf-8")) == rows
        assert hashlib.sha256(Path(raw.payload_path).read_bytes()).hexdigest() == raw.sha256
    calls = len(fetcher.calls)
    assert pipeline.collect(DAY, adapter=adapter, force=False)["idempotent_reuse"]
    assert len(fetcher.calls) == calls
    assert observe(database, "reused", preclose, preclose*oracle)[1] == old_factor
    assert pipeline.collect(DAY, adapter=adapter, force=True)["status"] == "success"
    assert len(fetcher.calls) > calls
    with database() as db:
        updated = db.get(CorporateAction, action_id)
        assert updated.raw_payload_id == raw_id
        assert updated.details_json == next(r for r in rows if r["SecuritiesCompanyCode"] == "6204")
        assert db.get(SignalEvaluation, old_id).adjusted_ohlc_json["factor_signal_to_raw"] == old_factor
    _, new_factor, new_status = observe(database, "new", preclose, preclose*oracle)
    assert new_factor == pytest.approx(oracle)
    assert new_factor != old_factor
    assert new_status == "active"
    # collect preserved old evaluation; explicitly evaluating its same signal can still upsert it.
    with database() as db:
        assert db.get(SignalEvaluation, old_id).adjusted_ohlc_json["factor_signal_to_raw"] == old_factor


def test_paid_subscription_remains_unhandled_without_new_factor_policy():
    row = dict(SCHEMA, SubscribedProRataThousandShares="100", SubscriptionPricePerShare="50")
    record = actions([row])[0][0]
    action = CorporateAction(action_date=DAY, action_type=record.action_type,
                             stock_dividend_ratio=record.stock_dividend_ratio,
                             cash_dividend=record.cash_dividend, reference_price=record.reference_price,
                             details_json=record.details)
    factor, applied = pipeline._corporate_action_factor([action])
    assert applied and factor == pytest.approx(95/110)
    assert factor != pytest.approx((100-5+.1*50)/(1+.1+.1)/100)
    assert action.details_json == row and "price_factor" not in action.details_json
