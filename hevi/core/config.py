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

    # HEVI-SPEC-03 资产库(hevi-vault docker-compose 项目,独立于上面的主库/主 MinIO)
    vault_database_url: str = "postgresql://hevi:hevi@localhost:5441/hevi_vault"
    vault_minio_endpoint: str = "localhost:9000"
    vault_minio_access_key: str = "hevi"
    vault_minio_secret_key: str = "hevi1234"
    vault_minio_secure: bool = False

    # HEVI-EXEC-01 §0:「智伯索地」C-P0 单 run 预算熔断线(soffy 选定区间 $5-10 的上限)
    tongjian_run_budget_usd: float = 10.0

    # Stored as str; parsed to list[str] by _cors_list() in main.py.
    # Accepts: "*", "https://a.com", "https://a.com,https://b.com", or JSON '["https://a.com"]'
    cors_origins: str = "*"

    # CosyVoice TTS (local GPU) configuration
    cosyvoice_model_dir: str = "/opt/cosyvoice/model"
    cosyvoice_use_watermark: bool = False

    # L5 角色卡参考图(SDXL 本地文生图,tongjian §5.1 步骤3-4)。权重 ~7GB,
    # 根分区(/)只剩 20G 空闲,故缓存目录放 /data 而非默认 ~/.cache/huggingface。
    sdxl_model_dir: str = "/data/models/huggingface"

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

    # L3 体检闭环(§7-4):确定性体检/评分卡不及格 → 定向返工的封顶轮数(0=关,只 log 不返工)。
    # 只在不合格时触发,合格片零额外开销;可用 task config_json["auto_rework_rounds"] 覆盖。
    auto_rework_max_rounds: int = 1
    rework_consistency_floor: float = 0.75

    # Paddle
    paddle_api_key: str | None = None
    paddle_webhook_secret: str | None = None
    paddle_environment: str = "sandbox"


settings = Settings()
