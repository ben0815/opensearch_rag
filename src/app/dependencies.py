from fastapi import Request
from slowapi import Limiter
from app.loader.config import LoaderConfig


def _get_client_ip(request: Request) -> str:
    """Echte Client-IP hinter Caddy.
    Caddy hängt an das XFF-Feld — der erste Eintrag ist vom Client fälschbar.
    Der letzte Eintrag ist der von Caddy gesetzte (nicht spoofbar).
    Fallback auf TCP-Remote-Address für direkte Verbindungen (Dev).
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host or "unknown"


def _get_user_or_ip(request: Request) -> str:
    """Rate-Limit per User-ID für authentifizierte Endpoints.
    Proxy-unabhängig und präziser als IP-Basis.
    """
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user.id}"
    return _get_client_ip(request)


# Singleton — wird in app_fastapi.py an app.state gebunden und in Routen als
# Dekorator genutzt. In-Memory-Speicher: reicht für Single-Process-Deployment.
limiter = Limiter(key_func=_get_client_ip)


def get_config(request: Request) -> LoaderConfig:
    """Dependency: App-weiter LoaderConfig-Singleton."""
    return request.app.state.config


def get_redis(request: Request):
    """Dependency: App-weite Redis-Verbindung."""
    return request.app.state.redis
