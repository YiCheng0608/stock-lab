"""FastAPI 應用進入點。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 啟動時先觸發一次設定載入，設定錯誤（如必填 env 缺漏）能在 boot 階段就爆炸。
    get_settings()
    yield


app = FastAPI(title="stock-lab API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Boot smoke 用的健康檢查端點。"""
    return {"status": "ok"}
