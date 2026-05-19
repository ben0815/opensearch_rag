from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.loader.config import LoaderConfig

# Singleton — wird in app_fastapi.py an app.state gebunden und in Routen als
# Dekorator genutzt. In-Memory-Speicher: reicht für Single-Process-Deployment.
limiter = Limiter(key_func=get_remote_address)


def get_config(request: Request) -> LoaderConfig:
    """Dependency: App-weiter LoaderConfig-Singleton."""
    return request.app.state.config


def get_redis(request: Request):
    """Dependency: App-weite Redis-Verbindung."""
    return request.app.state.redis
