import asyncio
import os
from datetime import datetime, timezone

import bcrypt as _bcrypt_mod
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

# Generiert einmal beim Start — verhindert Timing-Oracle für nicht-existierende User
_DUMMY_HASH = _bcrypt_mod.hashpw(b"dummy_constant_timing_placeholder", _bcrypt_mod.gensalt(rounds=12)).decode()

_MAX_LOGIN_FAILURES = 5
_LOCKOUT_SECONDS = 900  # 15 Minuten

router = APIRouter(prefix="/api/auth")


async def _is_locked(redis, username: str) -> bool:
    """Gibt True zurück wenn Account gesperrt ist (ohne Zähler zu verändern)."""
    val = await redis.get(f"login_failures:{username}")
    return int(val or 0) >= _MAX_LOGIN_FAILURES


async def _record_failure(redis, username: str) -> None:
    """Fehlversuch erfassen. Setzt TTL beim ersten Eintrag."""
    key = f"login_failures:{username}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _LOCKOUT_SECONDS)


async def _clear_login_failures(redis, username: str) -> None:
    await redis.delete(f"login_failures:{username}")


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    from ldap3.core.exceptions import LDAPBindError

    username = body.username.strip()
    password = body.password

    error = None
    user = None

    redis = request.app.state.redis

    # Per-User-Lockout: prüfen ohne Zähler zu erhöhen — korrektes PW darf nie gesperrt werden
    if await _is_locked(redis, username):
        # Fehlertext bewusst identisch — kein Information-Leak ob gesperrt oder falsches PW
        return JSONResponse({"detail": "Ungültige Anmeldedaten."}, status_code=401)

    result = await db.execute(select(User).where(User.ldap_uid == username))
    db_user = result.scalar_one_or_none()

    # 1. Local fallback: bootstrap admin with local_password_hash
    if db_user and db_user.local_password_hash:
        if not db_user.is_active:
            error = "Ihr Account wurde deaktiviert."
        elif _bcrypt_mod.checkpw(password.encode(), db_user.local_password_hash.encode()):
            db_user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            user = db_user
        else:
            error = "Ungültige Anmeldedaten."
    else:
        # Timing angleichen: auch für nicht-existierende User bcrypt laufen lassen
        if db_user is None:
            _bcrypt_mod.checkpw(password.encode(), _DUMMY_HASH.encode())
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
        # Fehlversuch zählen — erst nach gescheiterter Auth, nie bei korrekten Credentials
        await _record_failure(redis, username)
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
            logger.warning("Audit-Log login_failed fehlgeschlagen", exc_info=True)
        return JSONResponse({"detail": error or "Ungültige Anmeldedaten."}, status_code=401)

    # Erfolgreicher Login — Fehlerzähler zurücksetzen
    await _clear_login_failures(redis, username)

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
        logger.warning("Audit-Log login fehlgeschlagen", exc_info=True)

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
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return getattr(request.client, "host", "unknown") or "unknown"
