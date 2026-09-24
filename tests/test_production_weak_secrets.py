"""P1-B: production weak-default secrets fail closed; secrets never echoed."""

from pathlib import Path

import pytest

from hevi.core.config import Settings
from hevi.core.exceptions import ConfigurationError
from hevi.creative.layer4.usage_ledger import redact_secrets
from hevi.observability.redaction import RedactionFilter

REPO_ROOT = Path(__file__).resolve().parents[1]

STRONG_JWT = "unit-test-jwt-not-for-production-reuse-0123456789abcdef"
STRONG_DB = "postgresql+asyncpg://hevi:Zx9!strongPass_notDefault@localhost:5432/hevi"
STRONG_VAULT_DB = "postgresql://hevi:Zx9!strongPass_notDefault@localhost:5441/hevi_vault"
STRONG_MINIO = "Minio$ecret_NotDefault_9f3a"
STRONG_VAULT_USER = "vaultaccess_9f3a"


def _prod_settings(**overrides: str) -> Settings:
    fields: dict[str, str] = {
        "app_env": "production",
        "jwt_secret": STRONG_JWT,
        "database_url": STRONG_DB,
        "vault_database_url": STRONG_VAULT_DB,
        "minio_secret_key": STRONG_MINIO,
        "vault_minio_secret_key": STRONG_MINIO,
        "vault_minio_access_key": STRONG_VAULT_USER,
    }
    fields.update(overrides)
    return Settings(**fields)  # type: ignore[arg-type]


def test_development_allows_weak_defaults() -> None:
    s = Settings(app_env="development", jwt_secret=STRONG_JWT)
    assert s.app_env == "development"
    assert s.vault_minio_secret_key == "hevi1234"


def test_empty_jwt_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        Settings(app_env="development", jwt_secret="")
    assert "JWT_SECRET" in str(exc_info.value)


def test_production_rejects_weak_defaults_without_echoing_values() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        Settings(app_env="production", jwt_secret=STRONG_JWT)
    err = str(exc_info.value)
    assert "PRODUCTION_WEAK_SECRET" in err
    assert "DATABASE_URL" in err
    assert "VAULT_MINIO_SECRET_KEY" in err
    assert "hevi:hevi" not in err
    assert "hevi1234" not in err
    assert STRONG_JWT not in err


def test_production_rejects_weak_database_url_password() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        _prod_settings(database_url="postgresql+asyncpg://hevi:hevi@localhost:5432/hevi")
    err = str(exc_info.value)
    assert "PRODUCTION_WEAK_SECRET" in err
    assert "DATABASE_URL" in err
    assert "hevi:hevi" not in err


def test_production_rejects_weak_jwt() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        _prod_settings(jwt_secret="live-test-secret")
    err = str(exc_info.value)
    assert "PRODUCTION_WEAK_SECRET" in err
    assert "JWT_SECRET" in err
    assert "live-test-secret" not in err


def test_production_accepts_strong_secrets() -> None:
    s = _prod_settings()
    assert s.app_env == "production"
    assert s.vault_minio_secret_key == STRONG_MINIO


def test_redact_secrets_masks_password_assignments_and_url_credentials() -> None:
    assigned = redact_secrets(f"password={STRONG_MINIO}")
    assert STRONG_MINIO not in assigned
    assert "[REDACTED]" in assigned
    url = redact_secrets(STRONG_DB)
    assert "Zx9!strongPass_notDefault" not in url
    assert "[REDACTED]" in url


def test_redaction_filter_stops_secret_from_log_output() -> None:
    import logging
    from io import StringIO

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("hevi.tests.production_secret_log")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactionFilter())
    logger.addHandler(handler)
    try:
        logger.info("connecting with password=%s", STRONG_MINIO)
        logger.info("dsn=%s", STRONG_DB)
    finally:
        logger.removeHandler(handler)
        logger.handlers.clear()
    out = stream.getvalue()
    assert STRONG_MINIO not in out
    assert "Zx9!strongPass_notDefault" not in out
    assert "[REDACTED]" in out


def test_prod_compose_has_no_weak_secret_defaults() -> None:
    prod = (REPO_ROOT / "hevi/deploy/docker-compose-prod.yml").read_text()
    assert "${POSTGRES_PASSWORD:-hevi}" not in prod
    assert "${MINIO_SECRET_KEY:-minio12345}" not in prod
    assert "${MINIO_ACCESS_KEY:-minio}" not in prod
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required for production}" in prod
    assert "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required for production}" in prod
    assert "APP_ENV: production" in prod


def test_cftunnel_compose_has_no_weak_secret_defaults() -> None:
    cft = (REPO_ROOT / "deploy/docker-compose-cftunnel.yml").read_text()
    assert "${MINIO_SECRET_KEY:-hevi1234}" not in cft
    assert "${MINIO_ACCESS_KEY:-hevi}" not in cft
    assert "hevi:hevi@host.docker.internal" not in cft
    assert "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required for production}" in cft
    assert "APP_ENV: production" in cft


def test_env_example_documents_app_env_fail_closed() -> None:
    example = (REPO_ROOT / ".env.example").read_text()
    assert "APP_ENV=development" in example
    assert "PRODUCTION_WEAK_SECRET" in example
