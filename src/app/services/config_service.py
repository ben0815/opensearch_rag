"""Configuration service: effective instance config, LDAP config, app settings helpers."""
import copy
import os
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loader.config import LoaderConfig

# ─── Instance config overrides ────────────────────────────────────────────────

_INSTANCE_OVERRIDABLE = {
    "llm_model": str,
    "llm_temperature": float,
    "llm_num_ctx": int,
    "hybrid_k": int,
    "hybrid_score_threshold": float,
    "llm_system_prompt": str,
}


def get_effective_config(global_config: LoaderConfig, instance_settings: dict | None) -> LoaderConfig:
    """Return config with instance-specific overrides applied on top of global config."""
    if not instance_settings:
        return global_config

    overrides = {}
    for key, cast in _INSTANCE_OVERRIDABLE.items():
        raw = instance_settings.get(key)
        if raw is None or raw == "":
            continue
        try:
            overrides[key] = cast(raw)
        except (ValueError, TypeError):
            pass

    if not overrides:
        return global_config

    effective = copy.copy(global_config)
    for key, val in overrides.items():
        setattr(effective, key, val)
    return effective


# ─── App settings helpers ─────────────────────────────────────────────────────

async def get_app_setting(db: AsyncSession, key: str) -> str | None:
    from app.db.models import AppSetting
    row = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    return row.value if row else None


async def set_app_setting(
    db: AsyncSession,
    key: str,
    value: str,
    updated_by: int | None = None,
) -> None:
    from app.db.models import AppSetting
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    if existing:
        existing.value = value
        existing.updated_at = now
        existing.updated_by = updated_by
    else:
        db.add(AppSetting(key=key, value=value, updated_at=now, updated_by=updated_by))
    await db.commit()


# ─── LDAP config (runtime-editable, 30s TTL cache) ───────────────────────────

_LDAP_CACHE: dict | None = None
_LDAP_CACHE_TS: float = 0.0
_LDAP_CACHE_TTL: float = 30.0

_LDAP_SETTING_KEYS = (
    "ldap_url", "ldap_user_search_base", "ldap_uid_attr",
    "ldap_display_name_attr", "ldap_mail_attr", "ldap_user_filter",
    "ldap_admin_group_dn", "ldap_bind_dn", "ldap_bind_password",
    "ldap_enabled", "ldap_allow_auto_registration",
)


def _get_ldap_env_defaults() -> dict:
    return {
        "ldap_url": os.getenv("LDAP_URL", "ldap://localhost:389"),
        "ldap_user_search_base": os.getenv("LDAP_USER_SEARCH_BASE", "ou=users,dc=example,dc=com"),
        "ldap_uid_attr": os.getenv("LDAP_UID_ATTR", "uid"),
        "ldap_display_name_attr": os.getenv("LDAP_DISPLAY_NAME_ATTR", "displayName"),
        "ldap_mail_attr": os.getenv("LDAP_MAIL_ATTR", "mail"),
        "ldap_user_filter": os.getenv("LDAP_USER_FILTER", "(objectClass=inetOrgPerson)"),
        "ldap_admin_group_dn": os.getenv("LDAP_ADMIN_GROUP_DN", ""),
        "ldap_bind_dn": os.getenv("LDAP_BIND_DN", ""),
        "ldap_bind_password": os.getenv("LDAP_BIND_PASSWORD", ""),
        "ldap_enabled": os.getenv("LDAP_ENABLED", "true"),
        "ldap_allow_auto_registration": os.getenv("LDAP_ALLOW_AUTO_REGISTRATION", "true"),
    }


async def get_ldap_config(db: AsyncSession) -> dict:
    """Return LDAP config from app_settings with 30s TTL cache. Falls back to env vars."""
    global _LDAP_CACHE, _LDAP_CACHE_TS

    now = time.monotonic()
    if _LDAP_CACHE is not None and now - _LDAP_CACHE_TS < _LDAP_CACHE_TTL:
        return _LDAP_CACHE

    from app.db.models import AppSetting
    from app.utils.crypto import decrypt

    try:
        rows = (await db.execute(
            select(AppSetting).where(AppSetting.key.in_(_LDAP_SETTING_KEYS))
        )).scalars().all()

        cfg = _get_ldap_env_defaults()
        for row in rows:
            val = row.value
            if row.key == "ldap_bind_password":
                val = decrypt(val)
            cfg[row.key] = val
    except Exception:
        cfg = _get_ldap_env_defaults()

    _LDAP_CACHE = cfg
    _LDAP_CACHE_TS = now
    return cfg


def invalidate_ldap_config_cache() -> None:
    global _LDAP_CACHE, _LDAP_CACHE_TS
    _LDAP_CACHE = None
    _LDAP_CACHE_TS = 0.0


async def save_ldap_config(db: AsyncSession, data: dict, updated_by: int | None = None) -> None:
    """Persist LDAP config to app_settings and invalidate cache."""
    from app.db.models import AppSetting
    from app.utils.crypto import encrypt

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for key, val in data.items():
        if key not in _LDAP_SETTING_KEYS:
            continue
        if key == "ldap_bind_password":
            val = encrypt(val)
        existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if existing:
            existing.value = val
            existing.updated_at = now
            existing.updated_by = updated_by
        else:
            db.add(AppSetting(key=key, value=val, updated_at=now, updated_by=updated_by))
    await db.commit()
    invalidate_ldap_config_cache()


async def seed_ldap_config(db: AsyncSession) -> None:
    """Seed app_settings with env-var LDAP defaults on first startup (no-op if already set)."""
    from app.db.models import AppSetting
    existing = (await db.execute(
        select(AppSetting).where(AppSetting.key == "ldap_url")
    )).scalar_one_or_none()
    if existing is not None:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    defaults = _get_ldap_env_defaults()
    for key, val in defaults.items():
        if val:
            db.add(AppSetting(key=key, value=val, updated_at=now))
    await db.commit()


# ─── Maintenance mode cache ────────────────────────────────────────────────────

_MAINTENANCE_CACHE: dict = {"value": False, "ts": 0.0}
_MAINTENANCE_TTL: float = 60.0


async def is_maintenance_mode(db: AsyncSession) -> bool:
    now = time.monotonic()
    if now - _MAINTENANCE_CACHE["ts"] < _MAINTENANCE_TTL:
        return _MAINTENANCE_CACHE["value"]

    try:
        val_str = await get_app_setting(db, "maintenance_mode")
        val = val_str is not None and val_str.lower() in ("1", "true", "on")
    except Exception:
        val = False

    _MAINTENANCE_CACHE["value"] = val
    _MAINTENANCE_CACHE["ts"] = now
    return val


def invalidate_maintenance_cache() -> None:
    _MAINTENANCE_CACHE["ts"] = 0.0
