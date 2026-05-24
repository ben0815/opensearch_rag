import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse
from app.auth.session import get_user_and_session_by_token
from app.db.session import get_session_factory

PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/health",
    "/favicon.ico",
}
PUBLIC_PREFIXES = ("/assets/", "/static/")

_MAINTENANCE_CACHE: dict = {"value": False, "ts": 0.0}
_MAINTENANCE_TTL: float = 60.0


async def _check_maintenance() -> bool:
    now = time.monotonic()
    if now - _MAINTENANCE_CACHE["ts"] < _MAINTENANCE_TTL:
        return _MAINTENANCE_CACHE["value"]
    try:
        from app.db.models import AppSetting
        from sqlalchemy import select
        async with get_session_factory()() as db:
            row = (await db.execute(
                select(AppSetting).where(AppSetting.key == "maintenance_mode")
            )).scalar_one_or_none()
            val = row is not None and row.value.lower() in ("1", "true", "on")
    except Exception:
        val = False
    _MAINTENANCE_CACHE["value"] = val
    _MAINTENANCE_CACHE["ts"] = now
    return val


def invalidate_maintenance_cache() -> None:
    _MAINTENANCE_CACHE["ts"] = 0.0


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get("session_token")
        if not token:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        async with get_session_factory()() as db:
            user, session = await get_user_and_session_by_token(db, token)

            if not user or not user.is_active:
                response = JSONResponse({"detail": "Session expired or account disabled"}, status_code=401)
                response.delete_cookie("session_token")
                return response

            # Maintenance mode: block non-admins with 503
            in_maintenance = await _check_maintenance()
            if in_maintenance and not user.is_global_admin:
                return JSONResponse(
                    {"detail": "Service temporarily unavailable (Wartungsmodus)"},
                    status_code=503,
                )

            # Resolve impersonated_by username for UserOut
            impersonated_by = None
            is_impersonation = bool(session and getattr(session, "is_impersonation", False))
            if is_impersonation and session and session.impersonated_by_id:
                from app.db.models import User as UserModel
                from sqlalchemy import select as _select
                admin = (await db.execute(
                    _select(UserModel).where(UserModel.id == session.impersonated_by_id)
                )).scalar_one_or_none()
                impersonated_by = admin.ldap_uid if admin else None

        request.state.user = user
        request.state.session_token = token
        request.state.is_impersonation = is_impersonation
        request.state.impersonated_by = impersonated_by
        return await call_next(request)
