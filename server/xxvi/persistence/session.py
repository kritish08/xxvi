from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from xxvi.settings import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        # Hold connections open. Neon's direct endpoint drops idle ones, so
        # every checkout was paying a fresh TLS+auth handshake: measured
        # 0.33s for a query on an open connection versus 2.08s for the same
        # query with a checkout. GET /api/run opens three of them, which is
        # the 6s response the run was actually made of.
        pool_size=10,
        max_overflow=5,
        pool_recycle=1800,
        connect_args={
            # REQUIRED on the -pooler host: PgBouncer runs transaction
            # pooling, where asyncpg's prepared-statement cache breaks
            # because a statement prepared on one server connection is not
            # there on the next. 0 disables the cache.
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
