import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Session, User

SESSION_LIFETIME_HOURS = int(os.getenv("SESSION_LIFETIME_HOURS", "8"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(token: str) -> str:
    # SHA-256 des Klartext-Tokens — nur der Hash wird in der DB gespeichert.
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    db: AsyncSession,
    user_id: int,
    lifetime_hours: int | None = None,
    is_impersonation: bool = False,
    impersonated_by_id: int | None = None,
) -> str:
    if lifetime_hours is None:
        lifetime_hours = SESSION_LIFETIME_HOURS
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = _utcnow() + timedelta(hours=lifetime_hours)
    db.add(Session(
        token=token_hash,
        user_id=user_id,
        expires_at=expires_at,
        is_impersonation=is_impersonation,
        impersonated_by_id=impersonated_by_id,
    ))
    await db.commit()
    return token


async def get_user_by_token(db: AsyncSession, token: str) -> User | None:
    user, _ = await get_user_and_session_by_token(db, token)
    return user


async def get_user_and_session_by_token(
    db: AsyncSession, token: str
) -> tuple[User | None, Session | None]:
    session = (await db.execute(
        select(Session).where(
            Session.token == _hash_token(token),
            Session.expires_at > _utcnow(),
        )
    )).scalar_one_or_none()

    if not session:
        return None, None

    user = (await db.execute(select(User).where(User.id == session.user_id))).scalar_one_or_none()
    return user, session


async def delete_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token == _hash_token(token)))
    await db.commit()


async def purge_expired_sessions(db: AsyncSession) -> None:
    await db.execute(delete(Session).where(Session.expires_at <= _utcnow()))
    await db.commit()
