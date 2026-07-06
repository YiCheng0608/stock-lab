"""集中式設定：所有可變設定一律走環境變數（見 .env.example）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """應用程式設定，來源為環境變數 / `.env`。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 資料庫 ---
    database_url: str = "postgresql+psycopg://stocklab:stocklab@localhost:5432/stocklab"

    # --- 通知（Telegram，見 docs/design.md §8）---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- 應用一般設定 ---
    app_env: str = "development"
    timezone: str = "Asia/Taipei"


@lru_cache
def get_settings() -> Settings:
    """回傳快取過的 Settings 單例，供 FastAPI dependency 或直接呼叫使用。"""
    return Settings()
