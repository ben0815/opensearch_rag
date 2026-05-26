"""Admin-Endpunkte: Systemstatus."""
import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, User
from app.db.session import get_db
from app.dependencies import get_config, get_redis
from app.loader.config import LoaderConfig
from app.services.config_service import invalidate_maintenance_cache
from app.routes.admin._shared import _audit, _now, _require_admin

router = APIRouter()


@router.get("")
async def system_status(
    admin=Depends(_require_admin),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    import httpx
    status: dict = {}

    try:
        auth = None
        verify = True
        if config.opensearch_url.startswith("https://"):
            auth = (config.opensearch_username, config.opensearch_password)
            verify = False
        async with httpx.AsyncClient(timeout=3.0, auth=auth, verify=verify) as client:
            r_health, r_stats = await asyncio.gather(
                client.get(f"{config.opensearch_url}/_cluster/health"),
                client.get(f"{config.opensearch_url}/_cluster/stats"),
            )
        health = r_health.json()
        stats = r_stats.json()
        status["opensearch"] = {
            "ok": True,
            "color": health.get("status", "?"),
            "data_nodes": health.get("number_of_data_nodes"),
            "index_count": stats.get("indices", {}).get("count", "?"),
        }
    except Exception as e:
        status["opensearch"] = {"ok": False, "error": str(e)}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{config.ollama_host}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
        status["ollama"] = {
            "ok": True, "models": models,
            "active_model": config.llm_model,
            "model_available": config.llm_model in models,
        }
    except Exception as e:
        status["ollama"] = {"ok": False, "error": str(e)}

    try:
        info = await redis.info("memory")
        used = int(info.get("used_memory", 0))
        max_mem_str = await redis.config_get("maxmemory")
        max_mem = int(max_mem_str.get("maxmemory", 0))
        status["redis"] = {
            "ok": True,
            "used_mb": round(used / 1024 / 1024, 1),
            "max_mb": round(max_mem / 1024 / 1024, 1) if max_mem else None,
        }
    except Exception as e:
        status["redis"] = {"ok": False, "error": str(e)}

    try:
        from app.db.session import get_session_factory
        async with get_session_factory()() as db_check:
            pg_count = (await db_check.execute(select(func.count()).select_from(User))).scalar_one()
        status["postgres"] = {"ok": True, "user_count": pg_count}
    except Exception as e:
        status["postgres"] = {"ok": False, "error": str(e)}

    from app import __version__
    status["app_version"] = __version__
    return status


