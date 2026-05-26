"""Admin-Router-Paket — aggregiert alle Sub-Router unter /api/admin."""
import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, Session, User
from app.db.session import get_db
from app.auth.session import create_session, delete_session, SESSION_LIFETIME_HOURS
from app.schemas import user_out
from app.services.config_service import get_app_setting, invalidate_maintenance_cache

from .users import router as users_router
from .instances import router as instances_router
from .groups import router as groups_router
from .settings import router as settings_router
from .ldap import router as ldap_router
from .status import router as status_router
from .audit import router as audit_router
from ._shared import _audit, _now, _require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

router.include_router(users_router, prefix="/users")
router.include_router(instances_router, prefix="/instances")
router.include_router(groups_router, prefix="/groups")
router.include_router(settings_router, prefix="/settings")
router.include_router(ldap_router, prefix="/ldap")
router.include_router(status_router, prefix="/status")
router.include_router(audit_router, prefix="/audit")


# Impersonation-Stop direkt auf /api/admin/impersonation/stop (kein /users-Präfix)
@router.post("/impersonation/stop")
async def stop_impersonation(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop active impersonation and restore admin session."""
    user = request.state.user
    is_impersonation = getattr(request.state, "is_impersonation", False)
    if not is_impersonation:
        raise HTTPException(status_code=400, detail="Keine aktive Impersonation")

    token = request.cookies.get("session_token")
    token_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
    session = (await db.execute(select(Session).where(Session.token == token_hash))).scalar_one_or_none()
    if not session or not session.impersonated_by_id:
        raise HTTPException(status_code=400, detail="Ungültige Impersonations-Session")

    admin_id = session.impersonated_by_id
    admin_user = (await db.execute(select(User).where(User.id == admin_id))).scalar_one_or_none()
    if not admin_user:
        raise HTTPException(status_code=404, detail="Admin-Benutzer nicht gefunden")

    lifetime_str = await get_app_setting(db, "session_lifetime_hours")
    lifetime_hours = int(lifetime_str) if lifetime_str else SESSION_LIFETIME_HOURS
    _secure = os.getenv("SECURE_COOKIES", "false").lower() == "true"

    if token:
        await delete_session(db, token)
    new_token = await create_session(db, admin_id, lifetime_hours=lifetime_hours)

    _audit(db, admin_id, "impersonation_stop", "user", user.id, {"target_uid": user.ldap_uid})
    await db.commit()

    response = JSONResponse(user_out(admin_user).model_dump(mode="json"))
    response.set_cookie(
        "session_token", new_token,
        httponly=True, samesite="strict", secure=_secure, max_age=lifetime_hours * 3600,
    )
    return response


# Maintenance-Endpunkte direkt auf /api/admin/maintenance
@router.get("/maintenance")
async def get_maintenance(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(AppSetting).where(AppSetting.key == "maintenance_mode")
    )).scalar_one_or_none()
    active = row is not None and row.value.lower() in ("1", "true", "on")
    return {"maintenance_mode": active}


@router.post("/maintenance")
async def set_maintenance(
    body: dict,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    enabled = bool(body.get("enabled", False))
    value = "true" if enabled else "false"
    now = _now()
    existing = (await db.execute(
        select(AppSetting).where(AppSetting.key == "maintenance_mode")
    )).scalar_one_or_none()
    if existing:
        existing.value = value
        existing.updated_at = now
        existing.updated_by = admin.id
    else:
        db.add(AppSetting(key="maintenance_mode", value=value, updated_at=now, updated_by=admin.id))
    _audit(db, admin.id, "maintenance_mode_change", detail={"enabled": enabled})
    await db.commit()
    invalidate_maintenance_cache()
    return {"maintenance_mode": enabled}
