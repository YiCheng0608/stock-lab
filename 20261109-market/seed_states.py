"""Temporary rows in the task volume's DB copy (never the production DB) for the #564 state screenshots.

TX: 70 near-month sessions on the TAIEX dates through 2026-11-06 (latest, with MA60).
SPX: 40 closes through 2026-11-04 (the expected US session is 11-05: stale, too few closes).
IXIC: 70 closes through 2026-11-05 (latest, with MA60). DJI and SOX stay without data.
Run inside task-564-api-1; tag every row's source with a _shot suffix so it can be removed.
"""
from datetime import date, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Instrument, MarketBar
from worker.indicator_batch import compute_market_indicators

assert str(SessionLocal.kw["bind"].url).endswith("/data/stock.db")

with SessionLocal() as db:
    taiex = db.scalar(select(Instrument).where(Instrument.symbol == "TAIEX"))
    taiex_bars = list(db.scalars(select(MarketBar).where(MarketBar.instrument_id == taiex.id).order_by(MarketBar.trading_date.desc()).limit(70)))[::-1]

    def instrument(exchange, symbol, name, kind):
        item = db.scalar(select(Instrument).where(Instrument.exchange == exchange, Instrument.symbol == symbol))
        if item is None:
            item = Instrument(exchange=exchange, symbol=symbol, name=name, instrument_type=kind, status="active")
            db.add(item)
            db.flush()
        return item

    tx = instrument("TAIFEX", "TX", "臺股期貨近月", "futures")
    for i, ref in enumerate(taiex_bars):
        close = round(ref.close + 35 - (i % 5) * 7)
        db.add(MarketBar(
            instrument_id=tx.id, trading_date=ref.trading_date, open=close - 40, high=close + 120, low=close - 150, close=close,
            adj_close=close, volume=90000 + 500 * i, turnover=None, turnover_status="unavailable", turnover_reason="not_published",
            source="taifex_daily_futures_shot", contract_month="202611", open_interest=110000 + 150 * i, settlement_price=close - 3,
        ))

    def weekdays(end, count):
        days, day = [], end
        while len(days) < count:
            if day.weekday() < 5:
                days.append(day)
            day -= timedelta(days=1)
        return days[::-1]

    for symbol, name, end, count, base, step in (("SPX", "S&P 500", date(2026, 11, 4), 40, 6650.0, 4.5), ("IXIC", "NASDAQ Composite", date(2026, 11, 5), 70, 22400.0, 21.0)):
        item = instrument("US", symbol, name, "index")
        for i, day in enumerate(weekdays(end, count)):
            close = round(base + step * i + (-25 if i % 3 == 0 else 12), 2)
            db.add(MarketBar(
                instrument_id=item.id, trading_date=day, open=None, high=None, low=None, close=close, adj_close=close,
                volume=None, turnover=None, turnover_status="unavailable", turnover_reason="source_missing_ohlc",
                source="fred_close_shot", price_reason="source_missing_ohlc",
            ))
    db.flush()
    ids = [tx.id] + [db.scalar(select(Instrument.id).where(Instrument.exchange == "US", Instrument.symbol == s)) for s in ("SPX", "IXIC")]
    print(compute_market_indicators(db, as_of=date(2026, 11, 6), instrument_ids=ids))
    db.commit()
