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
    # Selbst bei vollem DB-Dump sind aktive Sessions nicht hijackbar.
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db: AsyncSession, user_id: int) -> str:
    token = secrets.token_urlsafe(32)          # Geht ins Cookie
    token_hash = _hash_token(token)             # Wird in DB gespeichert
    expires_at = _utcnow() + timedelta(hours=SESSION_LIFETIME_HOURS)
    db.add(Session(token=token_hash, user_id=user_id, expires_at=expires_at))
    await db.commit()
    return token


async def get_user_by_token(db: AsyncSession, token: str) -> User | None:
    result = await db.execute(
        select(Session).where(
            Session.token == _hash_token(token),
            Session.expires_at > _utcnow(),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    result = await db.execute(select(User).where(User.id == session.user_id))
    return result.scalar_one_or_none()


async def delete_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token == _hash_token(token)))
    await db.commit()


async def purge_expired_sessions(db: AsyncSession) -> None:
    await db.execute(delete(Session).where(Session.expires_at <= _utcnow()))
    await db.commit()
