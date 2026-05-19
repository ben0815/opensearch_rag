import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", "postgresql+asyncpg://raguser:changeme@localhost:5432/ragdb")
        _engine = create_async_engine(url, pool_size=10, max_overflow=20)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncSession:
    async with get_session_factory()() as session:
        yield session
