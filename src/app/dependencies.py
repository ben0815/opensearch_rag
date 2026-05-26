import os

from fastapi import Request
from slowapi import Limiter
from app.loader.config import LoaderConfig


def _get_client_ip(request: Request) -> str:
    """Echte Client-IP hinter Caddy.
    X-Real-IP wird von Caddy auf die TCP-Verbindungsadresse gesetzt (nicht spoofbar).
    Fallback auf TCP-Remote-Address für direkte Verbindungen (Dev ohne Caddy).
    """
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return getattr(request.client, "host", None) or "unknown"


def _get_user_or_ip(request: Request) -> str:
    """Rate-Limit per User-ID für authentifizierte Endpoints.
    Proxy-unabhängig und präziser als IP-Basis.
    """
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user.id}"
    return _get_client_ip(request)


def _build_redis_uri() -> str:
    host = os.getenv("REDIS_HOST", "redis")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD", "")
    if password:
        return f"redis://:{password}@{host}:{port}"
    return f"redis://{host}:{port}"


# Redis-backed Rate-Limiter — gilt prozessübergreifend bei mehreren uvicorn-Workers.
limiter = Limiter(key_func=_get_client_ip, storage_uri=_build_redis_uri())


def get_config(request: Request) -> LoaderConfig:
    """Dependency: App-weiter LoaderConfig-Singleton."""
    return request.app.state.config


def get_redis(request: Request):
    """Dependency: App-weite Redis-Verbindung."""
    return request.app.state.redis
