"""SQLAlchemy declarative base，所有 model 共用。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM model 的共同基底，供 Alembic env.py 抓 target_metadata。"""
