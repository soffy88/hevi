import sys

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "hevi"
    app_version: str = "6.0.0"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://hevi:hevi@localhost:5432/hevi"
    redis_url: str = "redis://localhost:6379/0"

    # Stored as str; parsed to list[str] by _cors_list() in main.py.
    # Accepts: "*", "https://a.com", "https://a.com,https://b.com", or JSON '["https://a.com"]'
    cors_origins: str = "*"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_required(cls, v: str) -> str:
        if not v:
            print("FATAL: JWT_SECRET must be set in .env", file=sys.stderr)
            sys.exit(1)
        return v

    # Cost settings
    ltx2_price_usd: float = 0.04  # per second (legacy; 2D pricing in pricing_table.py)
    ltx2_default_tier: str = "fast"  # fal.ai tier: "fast" | "pro"
    # ¥0.24/s 720p ÷ 7.25 CNY/USD; source: Alibaba Cloud billing 2026-06
    wan_price_usd: float = 0.033  # per second
    cost_limit_per_task_usd: float = 50.0
    max_duration_per_task_s: float = 3600.0
    credits_per_usd: int = 100

    # Paddle
    paddle_api_key: str | None = None
    paddle_webhook_secret: str | None = None
    paddle_environment: str = "sandbox"


settings = Settings()
