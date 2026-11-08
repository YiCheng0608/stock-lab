"""Remove the rows seed_states.py added to the task volume's DB copy (sources ending in _shot)."""
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Instrument, MarketBar, TechnicalIndicator

assert str(SessionLocal.kw["bind"].url).endswith("/data/stock.db")
with SessionLocal() as db:
    ids = list(db.scalars(select(MarketBar.instrument_id).where(MarketBar.source.like("%_shot")).distinct()))
    others = db.scalar(select(MarketBar.id).where(MarketBar.instrument_id.in_(ids), ~MarketBar.source.like("%_shot")).limit(1))
    assert others is None, "an instrument with real bars"
    print("indicators", db.execute(delete(TechnicalIndicator).where(TechnicalIndicator.instrument_id.in_(ids))).rowcount)
    print("bars", db.execute(delete(MarketBar).where(MarketBar.source.like("%_shot"))).rowcount)
    print("instruments", db.execute(delete(Instrument).where(Instrument.id.in_(ids))).rowcount)
    db.commit()
