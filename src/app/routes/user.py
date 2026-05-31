"""User self-service routes: profile, preferences, accessible instances, presence."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session, User
from app.auth.session import _utcnow
from app.db.session import get_db
from app.dependencies import limiter, _get_user_or_ip
from app.schemas import InstanceOut, UserPatchRequest, UserPresenceOut, user_out
from app.services.config_service import get_app_setting
from app.services.user_service import get_user_instances

router = APIRouter(prefix="/api")


@router.get("/users/presence")
@limiter.limit("120/minute", key_func=_get_user_or_ip)
async def get_presence(request: Request, db: AsyncSession = Depends(get_db)):
    """Liefert alle aktuell angemeldeten Nutzer (außer dem anfragenden selbst)."""
    presence_enabled = await get_app_setting(db, "presence_enabled")
    if presence_enabled == "false":
        return []

    current_user_id = request.state.user.id
    # Subquery returns distinct user_ids with active non-impersonation sessions.
    # Avoids SELECT DISTINCT on users.preferences (JSON has no equality operator in PG).
    active_user_ids = (
        select(Session.user_id)
        .where(
            Session.expires_at > _utcnow(),
            Session.is_impersonation == False,
            Session.user_id != current_user_id,
        )
        .distinct()
        .scalar_subquery()
    )
    stmt = select(User).where(
        User.id.in_(active_user_ids),
        User.is_active == True,
    )
    online_users = (await db.execute(stmt)).scalars().all()

    querying_ids: set[int] = set()
    if online_users:
        redis = request.app.state.redis
        user_ids = [u.id for u in online_users]
        keys = [f"presence:querying:{uid}" for uid in user_ids]
        try:
            values = await redis.mget(*keys)
            querying_ids = {uid for uid, v in zip(user_ids, values) if v is not None}
        except Exception:
            pass

    return [
        UserPresenceOut(
            id=u.id,
            display_name=u.display_name,
            ldap_uid=u.ldap_uid,
            is_querying=u.id in querying_ids,
        ).model_dump(mode="json")
        for u in online_users
    ]


@router.get("/instances")
async def list_instances(request: Request, db: AsyncSession = Depends(get_db)):
    """Return all instances accessible to the current user with effective role."""
    user = request.state.user
    entries = await get_user_instances(db, user)
    return [
        InstanceOut(
            id=e["instance"].id,
            name=e["instance"].name,
            slug=e["instance"].slug,
            description=e["instance"].description,
            settings=e["instance"].settings,
            role=e["role"],
            created_at=e["instance"].created_at,
            updated_at=e["instance"].updated_at,
        ).model_dump(mode="json")
        for e in entries
    ]


@router.patch("/users/me")
async def update_me(
    request: Request,
    body: UserPatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update user's own profile (default instance, preferences)."""
    # Re-fetch user in this session — request.state.user is detached (loaded by AuthMiddleware).
    db_user = (await db.execute(select(User).where(User.id == request.state.user.id))).scalar_one()

    if body.default_instance_id is not None:
        entries = await get_user_instances(db, db_user)
        accessible_ids = {e["instance"].id for e in entries}
        if body.default_instance_id not in accessible_ids and body.default_instance_id != -1:
            return JSONResponse({"detail": "Kein Zugriff auf diese Instanz"}, status_code=403)
        db_user.default_instance_id = body.default_instance_id if body.default_instance_id != -1 else None

    if body.preferences is not None:
        current = db_user.preferences or {}
        current.update(body.preferences.model_dump(exclude_none=True))
        db_user.preferences = current

    await db.commit()
    await db.refresh(db_user)
    return user_out(
        db_user,
        is_impersonation=getattr(request.state, "is_impersonation", False),
        impersonated_by=getattr(request.state, "impersonated_by", None),
    ).model_dump(mode="json")
