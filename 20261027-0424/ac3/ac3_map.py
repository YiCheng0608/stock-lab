from collections import Counter
from sqlalchemy import select
from app.db import SessionLocal
from app.models import NewsItem
from app.api import news_ai_map
with SessionLocal() as db:
    items = db.scalars(select(NewsItem)).all()
    ai = news_ai_map(db, items)
    print("news_items", len(items), "with ai", len(ai), Counter(v["prompt_version"] for v in ai.values()))
