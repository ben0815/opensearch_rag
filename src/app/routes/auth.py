import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ldap_service import LDAPAccountExpiredError, LDAPAccountLockedError, authenticate
from app.auth.session import create_session, delete_session, SESSION_LIFETIME_HOURS
from app.db.models import User
from app.db.session import get_db
from app.dependencies import limiter
from app.schemas import LoginRequest, LoginResponse, user_out
from app.services.config_service import get_app_setting, get_ldap_config
from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)

_SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

router = APIRouter(prefix="/api/auth")


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    import bcrypt as _bcrypt

    from ldap3.core.exceptions import LDAPBindError

    username = body.username.strip()
    password = body.password

    error = None
    user = None

    result = await db.execute(select(User).where(User.ldap_uid == username))
    db_user = result.scalar_one_or_none()

    # 1. Local fallback: bootstrap admin with local_password_hash
    if db_user and db_user.local_password_hash:
        if not db_user.is_active:
            error = "Ihr Account wurde deaktiviert."
        elif _bcrypt.checkpw(password.encode(), db_user.local_password_hash.encode()):
            db_user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            user = db_user
        else:
            error = "Ungültige Anmeldedaten."
    else:
        # 2. LDAP authentication
        ldap_cfg = await get_ldap_config(db)
        ldap_enabled = ldap_cfg.get("ldap_enabled", "true").lower() not in ("false", "0", "off")
        ldap_data = None
        if not ldap_enabled:
            error = "Anmeldung nicht möglich: LDAP ist deaktiviert."
        else:
            try:
                ldap_data = await asyncio.to_thread(authenticate, username, password, ldap_cfg)
            except LDAPAccountLockedError:
                error = "Ihr Account ist gesperrt."
            except LDAPAccountExpiredError:
                error = "Ihr Account ist abgelaufen."
            except LDAPBindError:
                error = "Ungültige Anmeldedaten."
            except Exception:
                logger.exception("LDAP-Authentifizierung fehlgeschlagen für Benutzer '%s'", username)
                error = "Anmeldung fehlgeschlagen. Bitte versuchen Sie es erneut."

        if ldap_data and not error:
            if db_user is None:
                allow_auto = ldap_cfg.get("ldap_allow_auto_registration", "true").lower() not in ("false", "0", "off")
                if not allow_auto:
                    error = "Ihr Account wurde noch nicht durch einen Administrator angelegt."
                else:
                    db_user = User(
                        ldap_uid=ldap_data["uid"],
                        display_name=ldap_data["display_name"],
                        email=ldap_data["email"],
                        is_global_admin=ldap_data["ldap_is_admin"],
                        is_active=True,
                    )
                    db.add(db_user)
            else:
                if not db_user.is_active:
                    error = "Ihr Account wurde deaktiviert."
                else:
                    db_user.display_name = ldap_data["display_name"]
                    db_user.email = ldap_data["email"]
                    if ldap_cfg.get("ldap_admin_group_dn"):
                        db_user.is_global_admin = ldap_data["ldap_is_admin"]
                    db_user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            if not error:
                await db.commit()
                await db.refresh(db_user)
                user = db_user

    if error or not user:
        try:
            from app.db.models import AuditLog
            db.add(AuditLog(
                user_id=db_user.id if db_user else None,
                action="login_failed",
                ip_address=_get_ip(request),
                detail={"username": username},
            ))
            await db.commit()
        except Exception:
            pass
        return JSONResponse({"detail": error or "Ungültige Anmeldedaten."}, status_code=401)

    # Audit log
    try:
        from app.db.models import AuditLog
        db.add(AuditLog(
            user_id=user.id,
            action="login",
            ip_address=_get_ip(request),
        ))
        await db.commit()
    except Exception:
        pass

    # Dynamic session lifetime
    lifetime_str = await get_app_setting(db, "session_lifetime_hours")
    lifetime_hours = int(lifetime_str) if lifetime_str else SESSION_LIFETIME_HOURS

    token = await create_session(db, user.id, lifetime_hours=lifetime_hours)
    response = JSONResponse(LoginResponse(
        user=user_out(user),
        session_lifetime_hours=lifetime_hours,
    ).model_dump(mode="json"))
    response.set_cookie(
        "session_token", token,
        httponly=True,
        samesite="strict",
        secure=_SECURE_COOKIES,
        max_age=lifetime_hours * 3600,
    )
    return response


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        # Audit log
        user = getattr(request.state, "user", None)
        try:
            from app.db.models import AuditLog
            db.add(AuditLog(
                user_id=user.id if user else None,
                action="logout",
                ip_address=_get_ip(request),
            ))
            await db.commit()
        except Exception:
            pass
        await delete_session(db, token)
    response = JSONResponse({"ok": True})
    response.delete_cookie("session_token")
    return response


@router.get("/me")
async def me(request: Request):
    u = request.state.user
    return user_out(
        u,
        is_impersonation=getattr(request.state, "is_impersonation", False),
        impersonated_by=getattr(request.state, "impersonated_by", None),
    ).model_dump(mode="json")


def _get_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[-1].strip()
    return getattr(request.client, "host", "unknown") or "unknown"
