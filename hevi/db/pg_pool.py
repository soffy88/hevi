import hashlib
import json

import asyncpg  # type: ignore[import-untyped]
from obase.persistence import PgPool

from hevi.core.config import settings


async def init_hevi_db_codecs(conn: asyncpg.Connection) -> None:
    """Register JSONB and other necessary codecs for hevi."""
    await conn.set_type_codec(
        'jsonb',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )
    await conn.set_type_codec(
        'json',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )

async def get_hevi_pg_pool() -> PgPool:
    """Get or create a PgPool instance with hevi-specific initialization."""
    name = f"_auto_{hashlib.sha1(settings.database_url.encode()).hexdigest()[:12]}"
    try:
        return PgPool.get(name)
    except KeyError:
        # Manually create asyncpg pool with init
        pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            init=init_hevi_db_codecs,
            min_size=2,
            max_size=20
        )
        instance = PgPool(name=name, _pool=pool)
        PgPool._registry[name] = instance
        return instance
