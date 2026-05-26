"""
Shared pytest fixtures for the opensearch_rag test suite.

Import order is critical: env vars and module patches must happen
BEFORE any app module is imported.
"""
import os

# --- MUST be first — app_fastapi.py calls _validate_secrets() at import time ---
os.environ["APP_SECRET_KEY"] = "pytest_secret_key_minimum_32_characters_long"
os.environ["DEV_MODE"] = "true"
os.environ["SECURE_COOKIES"] = "false"
os.environ["CSRF_ENFORCE"] = "false"  # Skip CSRF checks in tests

import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# 1. Patch DB session module with SQLite BEFORE any app route modules are imported.
#    The middleware and all routes use get_session_factory() from this module.
import app.db.session as _db_session_mod

_TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TEST_SESSION_FACTORY = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False)
_db_session_mod._engine = _TEST_ENGINE
_db_session_mod._session_factory = _TEST_SESSION_FACTORY

# 2. Replace rate limiter with in-memory storage BEFORE route modules capture it.
#    Routes do `from app.dependencies import limiter` at import time.
from slowapi import Limiter
from slowapi.util import get_remote_address
import app.dependencies as _deps_mod

_deps_mod.limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

# 3. NOW import app modules (they will use the patched limiter and DB session).
import fakeredis
from app.app_fastapi import app
from app.db.models import Base, Instance, InstanceMember, User
from app.dependencies import get_config, get_redis
from app.loader.config import LoaderConfig
from app.auth.session import create_session

# Ensure app.state.limiter uses our in-memory limiter (set at module level in app_fastapi).
app.state.limiter = _deps_mod.limiter


# ---------------------------------------------------------------------------
# Session-scoped: create tables once, drop at the end.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", autouse=True)
async def _db_tables():
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis_instance():
    r = fakeredis.FakeRedis()
    yield r
    r.flushall()


@pytest_asyncio.fixture
async def client(fake_redis_instance):
    """AsyncClient backed by SQLite DB and fakeredis. CSRF disabled."""
    config = LoaderConfig()

    app.state.config = config
    app.state.redis = fake_redis_instance

    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_redis] = lambda: fake_redis_instance

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    app.dependency_overrides.clear()
    if hasattr(app.state, "config"):
        del app.state.config
    if hasattr(app.state, "redis"):
        del app.state.redis


# ---------------------------------------------------------------------------
# Test-data helpers (commit to shared in-memory DB, visible across sessions
# because StaticPool shares one connection).
# ---------------------------------------------------------------------------

async def create_test_user(
    ldap_uid: str | None = None,
    *,
    is_admin: bool = False,
) -> User:
    if ldap_uid is None:
        ldap_uid = f"test_user_{uuid.uuid4().hex[:8]}"
    async with _TEST_SESSION_FACTORY() as db:
        user = User(
            ldap_uid=ldap_uid,
            display_name=ldap_uid,
            is_global_admin=is_admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def create_test_instance(slug: str | None = None) -> Instance:
    if slug is None:
        slug = f"inst_{uuid.uuid4().hex[:8]}"
    async with _TEST_SESSION_FACTORY() as db:
        inst = Instance(name=slug, slug=slug)
        db.add(inst)
        await db.commit()
        await db.refresh(inst)
        return inst


async def grant_instance_access(user_id: int, instance_id: int, role: str = "viewer") -> None:
    async with _TEST_SESSION_FACTORY() as db:
        db.add(InstanceMember(user_id=user_id, instance_id=instance_id, role=role))
        await db.commit()


async def create_session_token(user_id: int) -> str:
    """Creates a session in the test DB and returns the raw cookie token."""
    async with _TEST_SESSION_FACTORY() as db:
        return await create_session(db, user_id, lifetime_hours=1)
