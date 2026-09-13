"""Precise TPEx cash selection; saved future-dated rows are not PIT evidence."""
import copy
import hashlib
import json
import socket
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import CorporateAction, Instrument, MarketBar, RawPayload, Signal, SignalEvaluation
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher
from test_tpex_corporate_action_mapping import DAY, SAVED, actions, database


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in cash precision tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.parametrize("fields,expected", [
    ({"CashDivdend": "0.26618165", "CashDividend": "0.266182", "現金股利": "8", "息值": "9"}, .26618165),
    ({"CashDivdend": "0", "CashDividend": "2"}, 0),
    ({"CashDivdend": 0, "CashDividend": "2"}, 0),
    ({"CashDivdend": "", "CashDividend": "2"}, 2),
    ({"CashDivdend": " \t", "CashDividend": "2"}, 2),
    ({"CashDivdend": None, "CashDividend": "2"}, 2),
    ({"CashDividend": "2", "現金股利": "3"}, 2),
    ({"CashDivdend": "bad", "CashDividend": "2"}, None),
    ({"CashDivdend": "--", "CashDividend": "2"}, None),
    ({"CashDivdend": "NaN", "CashDividend": "2"}, None),
    ({"CashDivdend": "-1", "CashDividend": "2"}, -1),
    ({"CashDivdend": "", "CashDividend": "bad", "現金股利": "3"}, None),
    ({"CashDividend": "", "現金股利": "3", "息值": "4"}, 3),
    ({"現金股利": "3", "息值": "4"}, 3),
    ({"現金股利": "0", "息值": "4"}, 0),
    ({"現金股利": " ", "息值": "4"}, 4),
    ({"現金股利": "bad", "息值": "4"}, None),
    ({"息值": "4"}, 4),
    ({}, None),
])
def test_first_nonblank_cash_selection_and_unrelated_fields(fields, expected):
    # Synthetic conflicting fields exercise selection, not observed market rows.
    row = dict(Date="1150914", SecuritiesCompanyCode="5278", ExRightsDiviend="除息",
               StockDivdendThousandShares="100", ClosePriceBeforeExRightsDiviend="23.90", **fields)
    before = copy.deepcopy(row)
    record = actions([row])[0][0]
    assert record.cash_dividend == expected
    assert record.stock_dividend_ratio == .1 and record.reference_price == 23.9
    assert record.action_type == "ex_dividend" and record.action_date == DAY
    assert record.symbol == "5278" and record.exchange == "TPEx"
    assert record.split_ratio is None and record.details == row == before


@pytest.mark.parametrize("reverse", [False, True])
def test_full_saved_body_cutoff_precision_rational_factor_and_raw(reverse):
    rows = copy.deepcopy(SAVED[::-1] if reverse else SAVED)
    assert actions(rows, date(2026, 9, 13))[0] == []
    records, payloads = actions(rows)
    assert len(records) == 3
    assert [r.symbol for r in records] == [r["SecuritiesCompanyCode"] for r in rows]
    for record, row in zip(records, rows):
        assert record.cash_dividend == float(row["CashDivdend"])
        assert record.details == row
        price, cash = Fraction(row["ClosePriceBeforeExRightsDiviend"]), Fraction(row["CashDivdend"])
        action = CorporateAction(action_date=record.action_date, action_type=record.action_type,
                                 cash_dividend=record.cash_dividend, reference_price=record.reference_price,
                                 stock_dividend_ratio=record.stock_dividend_ratio, details_json=record.details)
        factor, applied = pipeline._corporate_action_factor([action])
        assert applied and factor == pytest.approx(float((price-cash)/price), rel=0, abs=1e-12)
    raw = payloads[0]
    assert json.loads(raw.payload_path.read_text(encoding="utf-8")) == rows
    assert hashlib.sha256(raw.payload_path.read_bytes()).hexdigest() == raw.sha256
    assert all(r.payload_sha256 == raw.sha256 for r in records)


class PrecisionFetcher(FixtureFetcher):
    def __call__(self, url, **kwargs):
        if url == sources.TPEX_ACTION_ENDPOINT:
            self.calls.append(url)
            return SAVED
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
                    return "5278"
                return value.replace("2026-09-04", "2026-09-14").replace("20260904", "20260914").replace("1150904", "1150914")
            return value
        return remap(payload)


def observe_precision(factory, key, oracle):
    pre = float(Fraction("23.90"))
    post = float(Fraction("23.90") - Fraction("0.26618165"))
    with factory() as db:
        instrument = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == "5278"))
        # Entire price series is synthetic; action date and saved cash are unchanged.
        for day, price in [(DAY-timedelta(days=1), pre), (DAY, post)]:
            bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument.id, MarketBar.trading_date == day))
            if bar is None:
                bar = MarketBar(instrument_id=instrument.id, trading_date=day, source="synthetic precision OHLC")
                db.add(bar)
            bar.open = bar.high = bar.low = bar.close = bar.adj_close = price
            bar.volume = 1000
            bar.turnover = price*1000
        signal = Signal(signal_key=key, instrument_id=instrument.id, signal_date=DAY-timedelta(days=1),
                        status="conditional", entry_type="breakout", breakout_price=pre,
                        invalid_price=pre*.5, target_1=pre*2, data_quality="complete")
        db.add(signal)
        db.commit()
        _, normalized, factor = pipeline._normalized_history_for_score_date(db, instrument.id, DAY)
        pipeline._evaluate_signal_tracking(db, signal, evaluation_cutoff=DAY)
        db.commit()
        evaluation = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id))
        assert factor == pytest.approx(oracle, rel=0, abs=1e-12)
        assert evaluation.adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(oracle, rel=0, abs=1e-12)
        assert normalized[DAY-timedelta(days=1)]["close"] == pytest.approx(pre*oracle, rel=0, abs=1e-12)
        # Tracking stores prices rounded to eight decimals; factors remain unrounded.
        assert evaluation.adjusted_ohlc_json["close"] == pytest.approx(round(post/oracle, 8), rel=0, abs=1e-12)
        return evaluation.id


def test_actual_parser_collect_reuse_force_same_identity_and_two_consumers(database, monkeypatch):
    actual = sources.TpexAdapter.fetch_actions

    def old_cash_slot(self, as_of):
        records, payloads = actual(self, as_of)
        return [replace(r, cash_dividend=sources.parse_number(sources._text(r.details, "CashDividend", "CashDivdend", "息值", "現金股利")))
                for r in records], payloads

    fetcher = PrecisionFetcher()
    adapter = sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher))
    price = Fraction("23.90")
    old = float((price-Fraction("0.266182"))/price)
    new = float((price-Fraction("0.26618165"))/price)
    assert new-old > 1e-8
    with monkeypatch.context() as context:
        context.setattr(sources.TpexAdapter, "fetch_actions", old_cash_slot)
        assert pipeline.collect(DAY, adapter=adapter)["status"] == "success"
    old_eval = observe_precision(database, "cash-old", old)
    with database() as db:
        action = db.scalar(select(CorporateAction))
        action_id, raw_id = action.id, action.raw_payload_id
        assert action.cash_dividend == .266182
        raw = db.get(RawPayload, raw_id)
        original_raw = Path(raw.payload_path).read_bytes()
        assert json.loads(original_raw) == SAVED
        assert hashlib.sha256(original_raw).hexdigest() == raw.sha256
    calls = len(fetcher.calls)
    assert pipeline.collect(DAY, adapter=adapter, force=False)["idempotent_reuse"]
    assert len(fetcher.calls) == calls
    observe_precision(database, "cash-reuse", old)
    assert pipeline.collect(DAY, adapter=adapter, force=True)["status"] == "success"
    assert len(fetcher.calls) > calls
    with database() as db:
        all_actions = list(db.scalars(select(CorporateAction)))
        assert len(all_actions) == 1
        updated = all_actions[0]
        assert updated.id == action_id and updated.raw_payload_id == raw_id
        assert updated.cash_dividend == .26618165 and updated.details_json == SAVED[0]
        assert updated.action_type == "ex_dividend" and updated.action_date == DAY
        raw = db.get(RawPayload, raw_id)
        assert Path(raw.payload_path).read_bytes() == original_raw
        assert hashlib.sha256(original_raw).hexdigest() == raw.sha256
        assert db.get(SignalEvaluation, old_eval).adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(old, rel=0, abs=1e-12)
    observe_precision(database, "cash-new", new)
    with database() as db:
        # collect/new-signal evaluation does not rewrite the old evaluation;
        # an explicit evaluate of that same signal may still upsert it.
        assert db.get(SignalEvaluation, old_eval).adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(old, rel=0, abs=1e-12)
