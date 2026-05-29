import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.csrf import CsrfMiddleware
from app.auth.middleware import AuthMiddleware
from app.auth.session import purge_expired_sessions
from app.db.session import get_db, get_session_factory
from app.loader.config import LoaderConfig
from app.dependencies import get_config, get_redis, limiter  # noqa: F401
from app.routes import auth as auth_router
from app.routes import chat as chat_router
from app.routes import documents as documents_router
from app.routes import admin as admin_router
from app.routes import user as user_router
from app.utils.logging_config import setup_logger

_env_file = os.getenv("ENV_FILE") or str(Path(__file__).resolve().parents[2] / "infra" / ".env")
load_dotenv(_env_file, override=False)
logger = setup_logger(__name__)

_SESSION_CLEANUP_INTERVAL = int(os.getenv("SESSION_CLEANUP_INTERVAL_SECONDS", "3600"))
_AUDIT_CLEANUP_INTERVAL = 86400  # daily
_CONFIG_SYNC_INTERVAL = int(os.getenv("CONFIG_SYNC_INTERVAL_SECONDS", "30"))

_SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"
_DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
_APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")

_FORBIDDEN_SECRETS = {
    "change_me_generate_a_random_key", "changeme", "change_me",
    "secret", "password", "test", "dev", "admin",
}


def _validate_secrets() -> None:
    secret = os.getenv("APP_SECRET_KEY", "")
    if not secret or secret in _FORBIDDEN_SECRETS or len(secret) < 32:
        print(
            "FEHLER: APP_SECRET_KEY ist nicht gesetzt, zu kurz (< 32 Zeichen) "
            "oder ein bekannter Platzhalter.\n"
            "Generieren: python -c \"import secrets; print(secrets.token_hex(32))\"",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _DEV_MODE and os.getenv("SECURE_COOKIES", "false").lower() != "true":
        print(
            "WARNUNG: SECURE_COOKIES=false in Produktion (DEV_MODE=false) — "
            "Session-Tokens werden unverschlüsselt übertragen!",
            file=sys.stderr,
        )

    ldap_enabled = os.getenv("LDAP_ENABLED", "false").lower() not in ("false", "0", "off", "")
    ldap_url = os.getenv("LDAP_URL", "")
    if ldap_enabled and ldap_url and not os.getenv("ENCRYPTION_KEY", ""):
        print(
            "WARNUNG: LDAP_ENABLED=true aber ENCRYPTION_KEY ist nicht gesetzt — "
            "das LDAP-Bind-Passwort wird unverschlüsselt in der Datenbank gespeichert!",
            file=sys.stderr,
        )


_validate_secrets()

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none';"
    + (" upgrade-insecure-requests;" if _SECURE_COOKIES else "")
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
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
    factory = get_session_factory()
    while True:
        await asyncio.sleep(_SESSION_CLEANUP_INTERVAL)
        try:
            async with factory() as db:
                await purge_expired_sessions(db)
            logger.info("Expired sessions purged")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Session cleanup failed: {e}")


async def _audit_cleanup_loop() -> None:
    factory = get_session_factory()
    while True:
        await asyncio.sleep(_AUDIT_CLEANUP_INTERVAL)
        try:
            from app.db.models import AuditLog, AppSetting
            from sqlalchemy import delete
            import datetime as _dt
            async with factory() as db:
                retention_row = (await db.execute(
                    select(AppSetting).where(AppSetting.key == "audit_retention_days")
                )).scalar_one_or_none()
                days = int(retention_row.value) if retention_row else 90
                cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=days)
                await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
                await db.commit()
            logger.info("Audit log cleanup done (retention=%d days)", days)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Audit cleanup failed: {e}")


_LLM_KEYS = {"llm_model", "llm_temperature", "llm_num_ctx", "llm_timeout_seconds"}
_SEARCH_KEYS = {"hybrid_bm25_weight", "hybrid_knn_weight", "hybrid_k", "hybrid_score_threshold"}

_TUNABLE_SETTINGS = {
    "llm_model", "llm_temperature", "llm_num_ctx", "llm_timeout_seconds",
    "hybrid_bm25_weight", "hybrid_knn_weight", "hybrid_k", "hybrid_score_threshold",
    "llm_system_prompt",
}

_SETTING_TYPES: dict[str, type] = {
    "llm_temperature": float, "llm_num_ctx": int, "llm_timeout_seconds": int,
    "hybrid_bm25_weight": float, "hybrid_knn_weight": float,
    "hybrid_k": int, "hybrid_score_threshold": float,
    "llm_model": str, "llm_system_prompt": str,
}


async def _config_sync_loop(app) -> None:
    """Periodisch Redis-Versionszähler prüfen und bei Änderung Config aus DB neu laden.

    Läuft in jedem uvicorn-Worker. Wenn Worker A admin-Einstellungen ändert und
    config:version inkrementiert, erkennen Worker B/C/D beim nächsten Tick die
    Abweichung und synchronisieren ihren Zustand ohne Neustart.
    """
    from app.services.config_service import get_config_version
    from app.db.models import AppSetting

    try:
        local_version = await get_config_version(app.state.redis)
    except Exception as e:
        logger.error("Config-Sync: Startwert nicht lesbar: %s", e)
        local_version = 0

    while True:
        await asyncio.sleep(_CONFIG_SYNC_INTERVAL)
        try:
            remote = await get_config_version(app.state.redis)
            if remote == local_version:
                continue

            async with get_session_factory()() as db:
                rows = (await db.execute(select(AppSetting))).scalars().all()

            # Env-Var-Defaults als Basis: gelöschte DB-Einträge (z.B. geleerte
            # llm_system_prompt) werden so korrekt auf den Default zurückgesetzt.
            new_config = LoaderConfig()
            for row in rows:
                if row.key not in _TUNABLE_SETTINGS or not hasattr(new_config, row.key):
                    continue
                cast = _SETTING_TYPES.get(row.key, str)
                try:
                    setattr(new_config, row.key, cast(row.value))
                except (ValueError, TypeError):
                    pass

            current = app.state.config
            llm_changed = any(
                getattr(new_config, k) != getattr(current, k) for k in _LLM_KEYS
            )
            search_changed = any(
                getattr(new_config, k) != getattr(current, k) for k in _SEARCH_KEYS
            )
            app.state.config = new_config

            if llm_changed:
                from app.rag import clear_llm_cache
                clear_llm_cache()
            if search_changed:
                from app.loader.vector_store import clear_vector_store_cache
                clear_vector_store_cache()

            local_version = remote
            logger.info(
                "Config-Sync: Version %d übernommen (llm_changed=%s, search_changed=%s)",
                remote, llm_changed, search_changed,
            )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Config-Sync fehlgeschlagen: %s", e)


async def _load_db_settings(config: LoaderConfig, db_factory) -> None:
    from app.db.models import AppSetting
    try:
        async with db_factory()() as db:
            rows = (await db.execute(select(AppSetting))).scalars().all()
            for row in rows:
                if row.key in _TUNABLE_SETTINGS and hasattr(config, row.key):
                    cast = _SETTING_TYPES.get(row.key, str)
                    try:
                        setattr(config, row.key, cast(row.value))
                    except (ValueError, TypeError) as e:
                        logger.warning("app_settings: skipping invalid value for %s: %s", row.key, e)
    except Exception as e:
        logger.warning("app_settings table not yet available, using env defaults: %s", e)


async def _seed_app_settings(db_factory) -> None:
    """Seed app_settings with env-var defaults on first startup."""
    try:
        from app.services.config_service import seed_ldap_config
        from app.db.models import AppSetting
        async with db_factory()() as db:
            await seed_ldap_config(db)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            _defaults = {
                "session_lifetime_hours": os.getenv("SESSION_LIFETIME_HOURS", "8"),
                "max_upload_mb": "50",
                "maintenance_mode": "false",
                "audit_retention_days": "90",
            }
            for key, default in _defaults.items():
                exists = (await db.execute(
                    select(AppSetting).where(AppSetting.key == key)
                )).scalar_one_or_none()
                if exists is None:
                    db.add(AppSetting(key=key, value=default, updated_at=now))
            await db.commit()
    except Exception as e:
        logger.warning("app_settings seed failed (table may not exist yet): %s", e)


def _check_ollama(host: str) -> None:
    import urllib.request, urllib.error
    url = host.rstrip("/") + "/api/version"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            logger.info("Ollama erreichbar: %s — HTTP %s", url, resp.status)
    except urllib.error.URLError as e:
        logger.warning("Ollama NICHT erreichbar (%s): %s", url, e)
    except Exception as e:
        logger.warning("Ollama-Check fehlgeschlagen (%s): %s", url, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not _SECURE_COOKIES:
        logger.warning("SECURE_COOKIES=false — Session-Cookies ohne Secure-Flag.")
    config = LoaderConfig()
    _check_ollama(config.ollama_host)
    app.state.config = config

    redis_kwargs = dict(host=config.redis_host, port=config.redis_port, decode_responses=True)
    if config.redis_password:
        redis_kwargs["password"] = config.redis_password
    app.state.redis = aioredis.Redis(**redis_kwargs)
    await app.state.redis.ping()

    await _load_db_settings(config, get_session_factory)
    await _seed_app_settings(get_session_factory)

    session_task = asyncio.create_task(_session_cleanup_loop())
    audit_task = asyncio.create_task(_audit_cleanup_loop())
    config_sync_task = asyncio.create_task(_config_sync_loop(app))
    yield
    session_task.cancel()
    audit_task.cancel()
    config_sync_task.cancel()
    await app.state.redis.aclose()


app = FastAPI(
    title="RAG Multi-Tenant",
    lifespan=lifespan,
    docs_url="/docs" if _DEV_MODE else None,
    redoc_url="/redoc" if _DEV_MODE else None,
    openapi_url="/openapi.json" if _DEV_MODE else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# DEV_MODE CORS: only active when Vite dev server proxies requests (port 5173).
# In production, Vite build output is served from the same origin — no CORS needed.
if os.getenv("DEV_MODE", "false").lower() == "true":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(404)
async def _not_found_handler(request: Request, exc):
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.exception_handler(403)
async def _forbidden_handler(request: Request, exc):
    return JSONResponse({"detail": "Forbidden"}, status_code=403)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (HTTPException, RequestValidationError)):
        raise exc
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


_CSRF_ENFORCE = os.getenv("CSRF_ENFORCE", "true").lower() == "true"

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CsrfMiddleware, secret=_APP_SECRET_KEY, enforce=_CSRF_ENFORCE, secure=_SECURE_COOKIES)
app.add_middleware(AuthMiddleware)

app.include_router(auth_router.router)
app.include_router(user_router.router)
app.include_router(chat_router.router)
app.include_router(documents_router.router)
app.include_router(admin_router.router)


@app.get("/health")
async def health():
    if _DEV_MODE:
        from app import __version__
        return JSONResponse({"status": "ok", "version": __version__})
    return JSONResponse({"status": "ok"})


# Serve React SPA — must come AFTER API routes so catch-all doesn't shadow them.
# The dist path is relative to where uvicorn is started (the repo root).
_frontend_dist = Path(__file__).resolve().parents[2] / "src" / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def _spa_catchall(request: Request, full_path: str):
        from fastapi.responses import FileResponse
        return FileResponse(
            str(_frontend_dist / "index.html"),
            headers={"Cache-Control": "no-store"},
        )
