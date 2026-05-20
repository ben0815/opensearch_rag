from typing import Literal
from fastapi import APIRouter, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.db.session import get_db
from app.db.models import User, Instance, Group, InstanceMember, GroupMember, GroupInstanceRole
from app.services.instance_service import create_instance, delete_instance
from app.loader.config import LoaderConfig
from app.dependencies import get_config, get_redis

from app.utils.templates import templates

_PAGE_SIZE_USERS = 25
_PAGE_SIZE_GROUPS = 10

router = APIRouter(prefix="/admin")

_SETTINGS_SPEC = [
    {"key": "llm_model",              "label": "LLM-Modell",          "type": "text",   "min": None, "max": None, "step": None, "hint": "Muss in Ollama gepullt sein (ollama pull <name>)"},
    {"key": "llm_temperature",        "label": "Temperature",          "type": "number", "min": 0.0,  "max": 2.0,  "step": 0.1,  "hint": "0.0 = deterministisch, 2.0 = sehr kreativ"},
    {"key": "llm_num_ctx",            "label": "Kontext-Tokens (num_ctx)", "type": "number", "min": 1024, "max": 131072, "step": 1024, "hint": "Kontextfenster für Ollama"},
    {"key": "llm_timeout_seconds",    "label": "LLM-Timeout (s)",     "type": "number", "min": 10,   "max": 600,  "step": 10,   "hint": "Max. Wartezeit auf LLM-Antwort; Browser-Timeout = Wert + 30s"},
    {"key": "hybrid_bm25_weight",     "label": "BM25-Gewicht",        "type": "number", "min": 0.0,  "max": 1.0,  "step": 0.05, "hint": "Lexikalische Suche; kNN-Gewicht = 1 - BM25"},
    {"key": "hybrid_k",               "label": "hybrid_k (Chunks)",   "type": "number", "min": 1,    "max": 100,  "step": 1,    "hint": "Anzahl Kandidaten aus OpenSearch vor Deduplizierung"},
    {"key": "hybrid_score_threshold", "label": "Score-Threshold",     "type": "number", "min": 0.0,  "max": 1.0,  "step": 0.01, "hint": "Mindest-Score (0.0 = deaktiviert)"},
]


def require_admin(request: Request):
    if not hasattr(request.state, "user") or not request.state.user.is_global_admin:
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    return request.state.user


# ─── Einstieg ────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request, user=Depends(require_admin)):
    return RedirectResponse(url="/admin/instances")


# ─── Instanzen ───────────────────────────────────────────────────────────────

@router.get("/instances", response_class=HTMLResponse)
async def admin_instances(
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    instances = (await db.execute(select(Instance))).scalars().all()
    return templates.TemplateResponse(request, "admin/instances.html", {
        "user": user, "instances": instances,
    })


@router.post("/instances/create")
async def create_instance_route(
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    opensearch_analyzer: str = Form(default="german"),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    await create_instance(db, config, name, description, analyzer=opensearch_analyzer)
    return RedirectResponse(url="/admin/instances", status_code=303)


@router.get("/instances/{instance_id}", response_class=HTMLResponse)
async def admin_instance_detail(
    instance_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    member_count = (await db.execute(
        select(func.count()).select_from(InstanceMember).where(InstanceMember.instance_id == instance_id)
    )).scalar_one()
    group_count = (await db.execute(
        select(func.count()).select_from(GroupInstanceRole).where(GroupInstanceRole.instance_id == instance_id)
    )).scalar_one()

    from app.services.document_service import list_documents
    doc_list = await list_documents(redis, instance.slug)
    doc_count = len(doc_list)

    return templates.TemplateResponse(request, "admin/instance_detail.html", {
        "user": user,
        "instance": instance,
        "member_count": member_count,
        "group_count": group_count,
        "doc_count": doc_count,
        "error": request.query_params.get("error"),
    })


@router.post("/instances/{instance_id}/edit")
async def admin_instance_edit(
    instance_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")
    instance.name = name.strip()
    instance.description = description.strip()
    from datetime import datetime, timezone
    instance.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return RedirectResponse(url=f"/admin/instances/{instance_id}", status_code=303)


@router.post("/instances/{instance_id}/settings")
async def admin_instance_settings(
    instance_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    form = await request.form()
    if form.get("reset") == "1":
        instance.settings = None
    else:
        _castmap = {
            "llm_model": str, "llm_temperature": float,
            "llm_num_ctx": int, "hybrid_k": int, "hybrid_score_threshold": float,
        }
        overrides = {}
        for key, cast in _castmap.items():
            val = form.get(key, "").strip()
            if val:
                try:
                    overrides[key] = cast(val)
                except (ValueError, TypeError):
                    pass
        instance.settings = overrides or None

    from datetime import datetime, timezone
    instance.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    from app.loader.vector_store import invalidate_instance_cache
    invalidate_instance_cache(instance.slug)
    await db.commit()
    return RedirectResponse(url=f"/admin/instances/{instance_id}", status_code=303)


@router.post("/instances/delete/{instance_id}")
async def delete_instance_route(
    instance_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    await delete_instance(db, config, instance_id, redis)
    return RedirectResponse(url="/admin/instances", status_code=303)


# ─── Gruppen ─────────────────────────────────────────────────────────────────

@router.get("/groups", response_class=HTMLResponse)
async def admin_groups(
    request: Request,
    page: int = Query(default=1, ge=1),
    q: str = Query(default=""),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * _PAGE_SIZE_GROUPS

    base_stmt = select(Group)
    if q:
        base_stmt = base_stmt.where(Group.name.ilike(f"%{q}%"))

    total: int = (await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )).scalar_one()
    total_pages = max(1, (total + _PAGE_SIZE_GROUPS - 1) // _PAGE_SIZE_GROUPS)

    groups = (await db.execute(
        base_stmt.order_by(Group.name).offset(offset).limit(_PAGE_SIZE_GROUPS)
    )).scalars().all()

    instances = (await db.execute(select(Instance))).scalars().all()
    users = (await db.execute(select(User).order_by(User.ldap_uid))).scalars().all()

    group_ids = [g.id for g in groups]
    gir_by_group: dict[int, list] = {}
    members_by_group: dict[int, list[int]] = {}
    if group_ids:
        gir_rows = (await db.execute(
            select(GroupInstanceRole, Instance)
            .join(Instance, GroupInstanceRole.instance_id == Instance.id)
            .where(GroupInstanceRole.group_id.in_(group_ids))
        )).all()
        for gir, inst in gir_rows:
            gir_by_group.setdefault(gir.group_id, []).append({"instance": inst, "role": gir.role})

        gm_rows = (await db.execute(
            select(GroupMember).where(GroupMember.group_id.in_(group_ids))
        )).scalars().all()
        for gm in gm_rows:
            members_by_group.setdefault(gm.group_id, []).append(gm.user_id)

    user_map = {u.id: u.display_name or u.ldap_uid for u in users}

    return templates.TemplateResponse(request, "admin/groups.html", {
        "user": user,
        "groups": groups, "instances": instances, "users": users,
        "user_map": user_map,
        "gir_by_group": gir_by_group,
        "members_by_group": members_by_group,
        "page": page, "total_pages": total_pages, "q": q,
    })


@router.post("/groups/create")
async def create_group(
    request: Request,
    name: str = Form(...),
    ldap_group_dn: str = Form(default=""),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.exc import IntegrityError
    db.add(Group(name=name, ldap_group_dn=ldap_group_dn or None))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(url="/admin/groups?error=name_exists", status_code=303)
    return RedirectResponse(url="/admin/groups", status_code=303)


@router.post("/groups/{group_id}/delete")
async def delete_group(
    group_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    group = (await db.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if group:
        db.delete(group)
        await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=303)


@router.post("/groups/{group_id}/assign")
async def assign_group_to_instance(
    group_id: int,
    request: Request,
    instance_id: int = Form(...),
    role: Literal["viewer", "manager"] = Form(...),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(GroupInstanceRole).where(
            GroupInstanceRole.group_id == group_id,
            GroupInstanceRole.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.role = role
    else:
        db.add(GroupInstanceRole(group_id=group_id, instance_id=instance_id, role=role))
    await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=303)


@router.post("/groups/{group_id}/remove-instance/{instance_id}")
async def remove_instance_from_group(
    group_id: int,
    instance_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    gir = (await db.execute(
        select(GroupInstanceRole).where(
            GroupInstanceRole.group_id == group_id,
            GroupInstanceRole.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if gir:
        db.delete(gir)
        await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=303)


@router.post("/groups/{group_id}/add-user")
async def add_user_to_group(
    group_id: int,
    request: Request,
    user_id: int = Form(...),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(GroupMember(group_id=group_id, user_id=user_id))
        await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=303)


@router.post("/groups/{group_id}/remove-user/{user_id}")
async def remove_user_from_group(
    group_id: int,
    user_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    member = (await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if member:
        db.delete(member)
        await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=303)


# ─── Benutzer ────────────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    q: str = Query(default=""),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * _PAGE_SIZE_USERS

    base_stmt = select(User)
    if q:
        base_stmt = base_stmt.where(
            or_(User.ldap_uid.ilike(f"%{q}%"), User.display_name.ilike(f"%{q}%"))
        )

    total: int = (await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )).scalar_one()
    total_pages = max(1, (total + _PAGE_SIZE_USERS - 1) // _PAGE_SIZE_USERS)

    users = (await db.execute(
        base_stmt.order_by(User.ldap_uid).offset(offset).limit(_PAGE_SIZE_USERS)
    )).scalars().all()

    instances = (await db.execute(select(Instance))).scalars().all()
    groups = (await db.execute(select(Group))).scalars().all()

    # Nur Zuweisungen für die angezeigten Benutzer laden
    user_ids = [u.id for u in users]
    members_by_user: dict[int, list] = {}
    groups_by_user: dict[int, list[str]] = {}
    if user_ids:
        memberships = (await db.execute(
            select(InstanceMember, Instance)
            .join(Instance, InstanceMember.instance_id == Instance.id)
            .where(InstanceMember.user_id.in_(user_ids))
        )).all()
        for mem, inst in memberships:
            members_by_user.setdefault(mem.user_id, []).append({"instance": inst, "role": mem.role})

        gm_rows = (await db.execute(
            select(GroupMember).where(GroupMember.user_id.in_(user_ids))
        )).scalars().all()
        group_map = {g.id: g.name for g in groups}
        for gm in gm_rows:
            gname = group_map.get(gm.group_id)
            if gname:
                groups_by_user.setdefault(gm.user_id, []).append(gname)

    return templates.TemplateResponse(request, "admin/users.html", {
        "user": user,
        "users": users, "instances": instances, "groups": groups,
        "members_by_user": members_by_user,
        "groups_by_user": groups_by_user,
        "page": page, "total_pages": total_pages, "q": q,
    })


async def _count_remaining_admins(db: AsyncSession, exclude_user_id: int, also_active: bool = False) -> int:
    """Count active global admins excluding the given user_id."""
    stmt = select(func.count()).select_from(User).where(
        User.is_global_admin == True,
        User.id != exclude_user_id,
    )
    if also_active:
        stmt = stmt.where(User.is_active == True)
    return (await db.execute(stmt)).scalar_one()


@router.post("/users/{user_id}/set-admin")
async def set_admin(
    user_id: int,
    request: Request,
    is_admin: bool = Form(...),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == user.id:
        return RedirectResponse(url="/admin/users?error=self_modify", status_code=303)
    if not is_admin:
        remaining = await _count_remaining_admins(db, user_id)
        if remaining == 0:
            return RedirectResponse(url="/admin/users?error=last_admin", status_code=303)
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target:
        target.is_global_admin = is_admin
        await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/set-active")
async def set_user_active(
    user_id: int,
    request: Request,
    is_active: bool = Form(...),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == user.id:
        return RedirectResponse(url="/admin/users?error=self_modify", status_code=303)
    if not is_active:
        # Letzten aktiven Admin nicht deaktivieren
        target_check = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if target_check and target_check.is_global_admin:
            remaining = await _count_remaining_admins(db, user_id, also_active=True)
            if remaining == 0:
                return RedirectResponse(url="/admin/users?error=last_admin", status_code=303)
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target:
        target.is_active = is_active
        await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/assign-instance")
async def assign_user_to_instance(
    user_id: int,
    request: Request,
    instance_id: int = Form(...),
    role: Literal["viewer", "manager"] = Form(...),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == user_id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.role = role
    else:
        db.add(InstanceMember(
            user_id=user_id,
            instance_id=instance_id,
            role=role,
            added_by=current_user.id,
        ))
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == user.id:
        return RedirectResponse(url="/admin/users", status_code=303)
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target and target.is_global_admin:
        remaining = await _count_remaining_admins(db, user_id)
        if remaining == 0:
            return RedirectResponse(url="/admin/users?error=last_admin", status_code=303)
    if target:
        db.delete(target)
        await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/remove-instance/{instance_id}")
async def remove_user_from_instance(
    user_id: int,
    instance_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    member = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == user_id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if member:
        db.delete(member)
        await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


# ─── Globale Einstellungen ────────────────────────────────────────────────────

@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    from app.db.models import AppSetting
    db_keys: set[str] = set()
    try:
        rows = (await db.execute(select(AppSetting))).scalars().all()
        db_keys = {r.key for r in rows}
    except Exception:
        pass

    return templates.TemplateResponse(request, "admin/settings.html", {
        "user": user,
        "config": config,
        "settings_spec": _SETTINGS_SPEC,
        "db_keys": db_keys,
        "saved": request.query_params.get("saved"),
        "error": request.query_params.get("error"),
    })


@router.post("/settings")
async def admin_settings_save(
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    import copy
    from app.db.models import AppSetting
    from datetime import datetime, timezone

    form = await request.form()

    _castmap: dict[str, type] = {
        "llm_model": str, "llm_temperature": float, "llm_num_ctx": int,
        "llm_timeout_seconds": int, "hybrid_bm25_weight": float,
        "hybrid_k": int, "hybrid_score_threshold": float,
    }

    new_values: dict = {}
    errors: list[str] = []

    for spec in _SETTINGS_SPEC:
        key = spec["key"]
        raw = form.get(key, "").strip()
        if not raw:
            continue
        cast = _castmap.get(key, str)
        try:
            val = cast(raw)
        except (ValueError, TypeError):
            errors.append(f"Ungültiger Wert für {spec['label']}: {raw!r}")
            continue

        # BM25-Gewicht: kNN wird automatisch berechnet
        if key == "hybrid_bm25_weight":
            knn = round(1.0 - float(val), 6)
            new_values["hybrid_bm25_weight"] = val
            new_values["hybrid_knn_weight"] = knn
            continue

        new_values[key] = val

    if errors:
        return RedirectResponse(url=f"/admin/settings?error={'|'.join(errors)}", status_code=303)

    # LLM-Modell-Check (nur wenn Modell sich ändert)
    if "llm_model" in new_values and new_values["llm_model"] != config.llm_model:
        ok, msg = await _check_ollama_model(config.ollama_host, new_values["llm_model"])
        if not ok:
            return RedirectResponse(url=f"/admin/settings?error={msg}", status_code=303)

    # Reihenfolge: 1) DB, 2) In-Memory, 3) Cache-Invalidierung
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        for key, val in new_values.items():
            existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
            if existing:
                existing.value = str(val)
                existing.updated_at = now
                existing.updated_by = user.id
            else:
                db.add(AppSetting(key=key, value=str(val), updated_at=now, updated_by=user.id))
        await db.commit()
    except Exception as e:
        await db.rollback()
        return RedirectResponse(url=f"/admin/settings?error=DB-Fehler: {e}", status_code=303)

    # Atomares Config-Objekt-Replacement (thread-safe via GIL)
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
        # OpenSearch-Pipeline für alle laufenden Instanzen aktualisieren
        try:
            instances = (await db.execute(select(Instance))).scalars().all()
            import asyncio
            for inst in instances:
                try:
                    store = await asyncio.to_thread(VectorStore.for_instance, new_config, inst.slug)
                    await asyncio.to_thread(store._ensure_search_pipeline)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Pipeline-Update für %s fehlgeschlagen: %s", inst.slug, e)
        except Exception:
            pass

    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


async def _check_ollama_model(ollama_host: str, model_name: str) -> tuple[bool, str]:
    """Prüft ob ein Modell in Ollama verfügbar ist. Gibt (ok, error_message) zurück."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            if model_name not in models:
                available = ", ".join(models[:10]) or "keine"
                return False, f"Modell '{model_name}' nicht in Ollama. Verfügbar: {available}"
            return True, ""
    except httpx.TimeoutException:
        return True, f"Ollama nicht erreichbar — Modell konnte nicht geprüft werden."
    except Exception as e:
        return True, f"Ollama-Check fehlgeschlagen: {e}"


# ─── System-Status ────────────────────────────────────────────────────────────

@router.get("/status", response_class=HTMLResponse)
async def admin_status_page(
    request: Request,
    user=Depends(require_admin),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    import httpx
    status: dict = {}

    # OpenSearch
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{config.opensearch_url}/_cluster/health")
            data = r.json()
            status["opensearch"] = {"ok": True, "color": data.get("status", "?"), "indices": data.get("number_of_data_nodes")}
    except Exception as e:
        status["opensearch"] = {"ok": False, "error": str(e)}

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{config.ollama_host}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            status["ollama"] = {"ok": True, "models": models, "active_model": config.llm_model, "model_available": config.llm_model in models}
    except Exception as e:
        status["ollama"] = {"ok": False, "error": str(e)}

    # Redis
    try:
        info = await redis.info("memory")
        used = int(info.get("used_memory", 0))
        max_mem_str = await redis.config_get("maxmemory")
        max_mem = int(max_mem_str.get("maxmemory", 0))
        status["redis"] = {"ok": True, "used_mb": round(used / 1024 / 1024, 1), "max_mb": round(max_mem / 1024 / 1024, 1) if max_mem else None}
    except Exception as e:
        status["redis"] = {"ok": False, "error": str(e)}

    # PostgreSQL
    try:
        user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one() if False else None
        # Einfache DB-Verfügbarkeitsprüfung via Session
        from app.db.session import get_session_factory
        async with get_session_factory()() as db_check:
            pg_count = (await db_check.execute(select(func.count()).select_from(User))).scalar_one()
        status["postgres"] = {"ok": True, "user_count": pg_count}
    except Exception as e:
        status["postgres"] = {"ok": False, "error": str(e)}

    from app import __version__
    return templates.TemplateResponse(request, "admin/status.html", {
        "user": user, "status": status, "config": config, "app_version": __version__,
    })


# ─── Redis-Rebuild ────────────────────────────────────────────────────────────

@router.post("/instances/{instance_id}/rebuild-redis")
async def admin_rebuild_redis(
    instance_id: int,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    import asyncio
    from app.loader.vector_store import VectorStore
    from app.metadata.redis_service import RedisMetadataService, DocumentMetadata

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404)

    try:
        store = await asyncio.to_thread(VectorStore.for_instance, config, instance.slug)
        client = store._get_raw_client()

        # Alle Chunks aggregieren nach file_hash
        agg_body = {
            "size": 0,
            "aggs": {
                "by_hash": {
                    "terms": {"field": "metadata.file_hash", "size": 10000},
                    "aggs": {
                        "filename":   {"terms": {"field": "metadata.filename", "size": 1}},
                        "max_page":   {"max": {"field": "metadata.page"}},
                        "chunk_count": {"value_count": {"field": "metadata.chunk_index"}},
                    },
                }
            },
        }
        resp = await asyncio.to_thread(client.search, index=store._index_name, body=agg_body)
        buckets = resp.get("aggregations", {}).get("by_hash", {}).get("buckets", [])

        service = RedisMetadataService(redis, instance.slug)
        rebuilt = 0
        for bucket in buckets:
            file_hash = bucket["key"]
            filename_buckets = bucket.get("filename", {}).get("buckets", [])
            filename = filename_buckets[0]["key"] if filename_buckets else file_hash
            page_count = int(bucket.get("max_page", {}).get("value") or 1)
            chunk_count = int(bucket.get("chunk_count", {}).get("value") or 0)
            existing = await service.get_document_metadata(file_hash)
            if not existing:
                from datetime import datetime, timezone
                await service.save_document_metadata(
                    file_hash,
                    DocumentMetadata(
                        title=filename,
                        file_size=0,
                        page_count=page_count,
                        chunk_count=chunk_count,
                        source_path="",
                        indexed_date=datetime.now(timezone.utc).isoformat(),
                        file_hash=file_hash,
                        additional_metadata={"rebuilt": True},
                    ),
                )
                rebuilt += 1
        import logging
        logging.getLogger(__name__).info("Redis-Rebuild für %s: %d Einträge angelegt", instance.slug, rebuilt)
        return RedirectResponse(url=f"/admin/instances/{instance_id}?error=rebuild_ok", status_code=303)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Redis-Rebuild fehlgeschlagen: %s", e, exc_info=True)
        return RedirectResponse(url=f"/admin/instances/{instance_id}?error=rebuild_failed", status_code=303)
