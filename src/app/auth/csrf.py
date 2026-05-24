import hashlib
import hmac
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_COOKIE_NAME = "csrftoken"
_HEADER_NAME = "X-CSRF-Token"
_FORM_FIELD = "csrf_token"


def _sign(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:16]


def generate_token(secret: str) -> str:
    rand = secrets.token_urlsafe(16)
    return f"{rand}.{_sign(rand, secret)}"


def verify_token(submitted: str, cookie_value: str, secret: str) -> bool:
    if not submitted or not cookie_value:
        return False
    if not hmac.compare_digest(submitted, cookie_value):
        return False
    try:
        rand, sig = cookie_value.rsplit(".", 1)
        return hmac.compare_digest(_sign(rand, secret), sig)
    except ValueError:
        return False


def _cookie_is_valid(cookie: str, secret: str) -> bool:
    try:
        rand, sig = cookie.rsplit(".", 1)
        return hmac.compare_digest(_sign(rand, secret), sig)
    except (ValueError, AttributeError):
        return False


class CsrfMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str, enforce: bool = True, secure: bool = False):
        super().__init__(app)
        self._secret = secret
        self._enforce = enforce
        self._secure = secure

    async def dispatch(self, request: Request, call_next) -> Response:
        existing = request.cookies.get(_COOKIE_NAME, "")
        valid_existing = bool(existing) and _cookie_is_valid(existing, self._secret)
        token = existing if valid_existing else generate_token(self._secret)
        request.state.csrf_token = token

        if request.method in _UNSAFE_METHODS:
            submitted = request.headers.get(_HEADER_NAME)
            if not submitted:
                content_type = request.headers.get("content-type", "")
                if "multipart/form-data" not in content_type:
                    try:
                        # request.body() liest den ASGI-receive-Stream und cached ihn in
                        # request._body. Danach nutzt request.form() ausschließlich diesen
                        # Cache (via request.stream() → yield _body). Der receive-Stream
                        # selbst ist danach erschöpft — request._receive muss ersetzt werden,
                        # damit der innere Handler (FastAPI-Route) den Body nochmals lesen kann.
                        body_bytes = await request.body()
                        form = await request.form()
                        submitted = form.get(_FORM_FIELD)
                        _replayed = False

                        async def _replay_receive():
                            nonlocal _replayed
                            if not _replayed:
                                _replayed = True
                                return {"type": "http.request", "body": body_bytes, "more_body": False}
                            return {"type": "http.disconnect"}

                        request._receive = _replay_receive
                    except Exception:
                        submitted = None

            if not verify_token(submitted, token, self._secret):
                logger.warning(
                    "CSRF-Validierung fehlgeschlagen: %s %s (enforce=%s)",
                    request.method, request.url.path, self._enforce,
                )
                if self._enforce:
                    return Response("CSRF-Token ungültig.", status_code=403)

        response = await call_next(request)

        if not valid_existing:
            response.set_cookie(
                _COOKIE_NAME,
                token,
                httponly=False,
                samesite="strict",
                secure=self._secure,
            )

        return response
