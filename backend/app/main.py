from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import configure_cors, router
from .browser_gate import BrowserGate
from .config import allowed_origins, public_hosts
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
# Read here so a malformed STOCK_API_PUBLIC_HOSTS / STOCK_API_ALLOWED_ORIGINS stops the API at import, naming the value.
ALLOWED_ORIGINS, PUBLIC_HOSTS = allowed_origins(), public_hosts()
# Added before CORS so CORS stays outermost: preflights are answered there, and a refusal for an allowed origin stays readable.
app.add_middleware(
    BrowserGate, allowed_origins=ALLOWED_ORIGINS, public_hosts=PUBLIC_HOSTS
)
configure_cors(app, ALLOWED_ORIGINS)
app.include_router(router)
