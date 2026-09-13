from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import configure_cors, router
from .database_readiness import check_database_readiness


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_database_readiness()
    yield


app = FastAPI(
    title="台股研究工具 API",
    description="提供台股、ETF、新上市標的的資料、族群排名、條件式訊號與追蹤紀錄。",
    version="0.1.0",
    lifespan=lifespan,
)
configure_cors(app)
app.include_router(router)
