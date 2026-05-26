"""Admin-Endpunkte: App-Einstellungen."""
import asyncio
import copy

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, Instance
from app.db.session import get_db
from app.dependencies import get_config
from app.loader.config import LoaderConfig
from app.schemas import SettingOut, SettingSpec, SettingsPatchRequest, SettingsResponse
from app.services.config_service import (
    bump_config_version,
    get_app_setting,
    invalidate_maintenance_cache,
    set_app_setting,
)
from app.routes.admin._shared import _CASTMAP, _SETTINGS_SPEC, _audit, _now, _require_admin

router = APIRouter()


async def _check_ollama_model(ollama_host: str, model_name: str) -> tuple[bool, str]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            if model_name not in models:
                available = ", ".join(models[:10]) or "keine"
                return False, f"Modell '{model_name}' nicht in Ollama. Verfügbar: {available}"
            return True, ""
    except Exception:
        return True, ""


@router.get("")
async def get_settings(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    rows = (await db.execute(select(AppSetting))).scalars().all()
    settings = [SettingOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]
    spec = [SettingSpec(**s) for s in _SETTINGS_SPEC]
    return SettingsResponse(settings=settings, spec=spec, config_snapshot={}).model_dump(mode="json")


@router.patch("")
async def update_settings(
    body: SettingsPatchRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    new_values: dict = {}
    delete_keys: list[str] = []
    errors: list[str] = []

    from app.rag import validate_system_prompt

    for key, raw in body.values.items():
        if key == "llm_system_prompt":
            raw_str = str(raw)
            if not raw_str.strip():
                delete_keys.append(key)
                continue
            missing = validate_system_prompt(raw_str)
            if missing:
                errors.append(
                    f"System-Prompt: fehlende Platzhalter {missing}. "
                    "Erforderlich: {context}, {question}, {history}"
                )
                continue
            new_values[key] = raw_str
            continue

        cast = _CASTMAP.get(key, str)
        raw_str = str(raw).strip().replace(",", ".")
        if not raw_str:
            continue
        try:
            val = cast(raw_str)
        except (ValueError, TypeError):
            errors.append(f"Ungültiger Wert für {key!r}: {raw!r}")
            continue
        if key == "hybrid_bm25_weight":
            new_values["hybrid_bm25_weight"] = val
            new_values["hybrid_knn_weight"] = round(1.0 - float(val), 6)
            continue
        new_values[key] = val

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    if "llm_model" in new_values and new_values["llm_model"] != config.llm_model:
        ok, msg = await _check_ollama_model(config.ollama_host, new_values["llm_model"])
        if not ok:
            raise HTTPException(status_code=422, detail=msg)

    now = _now()
    for key in delete_keys:
        existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if existing:
            await db.delete(existing)
        if hasattr(config, key):
            new_values[key] = ""

    for key, val in new_values.items():
        existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if existing:
            existing.value = str(val)
            existing.updated_at = now
            existing.updated_by = admin.id
        else:
            db.add(AppSetting(key=key, value=str(val), updated_at=now, updated_by=admin.id))
    await db.commit()

    new_config = copy.deepcopy(config)
    llm_changed = any(k in new_values for k in ("llm_model", "llm_temperature", "llm_num_ctx", "llm_timeout_seconds"))
    search_changed = any(k in new_values for k in ("hybrid_bm25_weight", "hybrid_knn_weight", "hybrid_k", "hybrid_score_threshold"))
    for key, val in new_values.items():
        if hasattr(new_config, key):
            setattr(new_config, key, val)
    request.app.state.config = new_config

    from app.rag import clear_llm_cache
    from app.loader.vector_store import clear_vector_store_cache, VectorStore
    if llm_changed:
        clear_llm_cache()
    if search_changed:
        clear_vector_store_cache()
        try:
            instances = (await db.execute(select(Instance))).scalars().all()
            for inst in instances:
                try:
                    store = await asyncio.to_thread(VectorStore.for_instance, new_config, inst.slug)
                    await asyncio.to_thread(store._ensure_search_pipeline)
                except Exception:
                    pass
        except Exception:
            pass

    if "maintenance_mode" in new_values:
        invalidate_maintenance_cache()

    _audit(db, admin.id, "settings_change", detail={"keys": list(new_values.keys())})
    await db.commit()

    await bump_config_version(request.app.state.redis)

    rows = (await db.execute(select(AppSetting))).scalars().all()
    return [SettingOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]
