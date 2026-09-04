import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from xxvi.persistence.models import Account, Base


@pytest.fixture
async def sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def account(sessionmaker):
    async with sessionmaker() as session:
        row = Account(username="him", password_hash="x", role="player")
        session.add(row)
        await session.commit()
        return row


@pytest.fixture
async def account2(sessionmaker):
    async with sessionmaker() as session:
        row = Account(username="her", password_hash="x", role="player")
        session.add(row)
        await session.commit()
        return row
