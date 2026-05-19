import asyncio
import hashlib
import os
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware
from app.auth.middleware import AuthMiddleware
from app.auth.session import purge_expired_sessions
from app.db.session import get_db, get_session_factory
from app.db.models import Instance
from app.loader.config import LoaderConfig
from app.dependencies import get_config, get_redis, limiter  # noqa: F401 — kein Zirkel
from app.routes import auth as auth_router
from app.routes import chat as chat_router
from app.routes import documents as documents_router
from app.routes import admin as admin_router
from app.utils.logging_config import setup_logger

_env_file = os.getenv("ENV_FILE") or str(Path(__file__).resolve().parents[2] / "infra" / ".env")
load_dotenv(_env_file, override=False)
logger = setup_logger(__name__)

_SESSION_CLEANUP_INTERVAL = int(os.getenv("SESSION_CLEANUP_INTERVAL_SECONDS", "3600"))


def _check_ollama(host: str) -> None:
    url = host.rstrip("/") + "/api/version"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            logger.info("Ollama erreichbar: %s — HTTP %s", url, resp.status)
    except urllib.error.URLError as e:
        logger.warning("Ollama NICHT erreichbar (%s): %s — LLM-Anfragen werden fehlschlagen.", url, e)
    except Exception as e:
        logger.warning("Ollama-Check fehlgeschlagen (%s): %s", url, e)


def _compute_js_version() -> str:
    js_dir = Path("src/resources/js")
    if not js_dir.exists():
        return "dev"
    h = hashlib.md5()
    for f in sorted(js_dir.glob("*.js")):
        h.update(f.read_bytes())
    return h.hexdigest()[:8]
_SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

_SECURITY_HEADERS = {
    # frame-ancestors ersetzt X-Frame-Options in modernen Browsern
    "Content-Security-Policy": (
        "default-src 'self' cdn.jsdelivr.net; "
        "script-src 'self' cdn.jsdelivr.net; "
        "style-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "   # Clickjacking-Schutz
        "base-uri 'self'; "          # Base-Tag-Injection verhindern
        "form-action 'self'"         # Formulare nur an eigene Domain
    ),
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers[k] = v
        return response


async def _session_cleanup_loop() -> None:
    """Löscht stündlich abgelaufene Sessions aus der Datenbank."""
    factory = get_session_factory()
    while True:
        await asyncio.sleep(_SESSION_CLEANUP_INTERVAL)
        try:
            async with factory() as db:
                await purge_expired_sessions(db)
            logger.info("Expired sessions purged")
        except Exception as e:
            logger.error(f"Session cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: Singletons einmalig anlegen. Shutdown: Verbindungen sauber schließen."""
    from app.utils.templates import templates as jinja_templates
    jinja_templates.env.globals["js_version"] = _compute_js_version()
    config = LoaderConfig()
    _check_ollama(config.ollama_host)
    app.state.config = config
    redis_kwargs = dict(host=config.redis_host, port=config.redis_port, decode_responses=True)
    if config.redis_password:
        redis_kwargs["password"] = config.redis_password
    app.state.redis = aioredis.Redis(**redis_kwargs)
    await app.state.redis.ping()
    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    yield
    cleanup_task.cancel()
    await app.state.redis.aclose()


app = FastAPI(title="RAG Multi-Tenant", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # HTTPException und RequestValidationError haben eigene Handler in FastAPI —
    # hier re-raisen, damit der Starlette-Dispatcher sie korrekt weiterleitet.
    if isinstance(exc, (HTTPException, RequestValidationError)):
        raise exc
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Interner Fehler."})


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory="src/resources"), name="static")
app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(documents_router.router)
app.include_router(admin_router.router)


@app.get("/")
async def root(request: Request, db: AsyncSession = Depends(get_db)):
    """Smarter Redirect: Admin ohne Instanzen → direkt zur Instanz-Verwaltung."""
    user = getattr(request.state, "user", None)
    if user and user.is_global_admin:
        count = (await db.execute(select(func.count()).select_from(Instance))).scalar()
        if count == 0:
            return RedirectResponse(url="/admin/instances")
    return RedirectResponse(url="/chat")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
