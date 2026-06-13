from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "hevi"
    app_version: str = "6.0.0"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://hevi:hevi@localhost:5432/hevi"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["*"]

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7


settings = Settings()
