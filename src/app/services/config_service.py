import copy
from app.loader.config import LoaderConfig

_INSTANCE_OVERRIDABLE = {
    "llm_model": str,
    "llm_temperature": float,
    "llm_num_ctx": int,
    "hybrid_k": int,
    "hybrid_score_threshold": float,
}


def get_effective_config(global_config: LoaderConfig, instance_settings: dict | None) -> LoaderConfig:
    """Return a config with instance-specific overrides applied on top of the global config.

    Returns the global config object directly when no overrides exist (no copy).
    Only keys listed in _INSTANCE_OVERRIDABLE are applied — all others are ignored.
    """
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
