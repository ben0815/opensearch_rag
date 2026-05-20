from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.auth.session import get_user_by_token
from app.db.session import get_session_factory

PUBLIC_PATHS = {"/login", "/logout", "/favicon.ico", "/health"}
STATIC_PREFIX = "/static"


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(STATIC_PREFIX):
            return await call_next(request)

        token = request.cookies.get("session_token")
        if not token:
            return RedirectResponse(url="/login", status_code=302)

        async with get_session_factory()() as db:
            user = await get_user_by_token(db, token)

        if not user or not getattr(user, "is_active", True):
            response = RedirectResponse(url="/login", status_code=302)
            response.delete_cookie("session_token")
            return response

        request.state.user = user
        request.state.session_token = token
        return await call_next(request)
