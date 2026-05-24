"""Admin REST API — all endpoints require global-admin role."""
import asyncio
import copy
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, nullslast, nullsfirst, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting, AuditLog, Group, GroupInstanceRole, GroupMember,
    Instance, InstanceMember, Session, User,
)
from app.db.session import get_db
from app.dependencies import get_config, get_redis
from app.loader.config import LoaderConfig
from app.schemas import (
    AddGroupMemberRequest,
    AdminUserCreateRequest,
    AdminUserOut,
    AdminUserPatchRequest,
    AssignGroupInstanceRequest,
    AssignInstanceRequest,
    AssignUserGroupRequest,
    AuditLogOut,
    GroupCreateRequest,
    GroupOut,
    GroupInstanceRoleOut,
    AddInstanceMemberRequest,
    InstanceAdminOut,
    InstanceCreateRequest,
    InstanceMemberOut,
    InstancePatchRequest,
    LDAPConfigIn,
    LDAPConfigOut,
    LDAPSearchResult,
    PaginatedAdminUsers,
    PaginatedAuditLog,
    PaginatedGroups,
    SettingOut,
    SettingSpec,
    SettingsPatchRequest,
    SettingsResponse,
    StatusOut,
    user_out,
)
from app.services.config_service import (
    get_app_setting,
    get_ldap_config,
    invalidate_ldap_config_cache,
    invalidate_maintenance_cache,
    save_ldap_config,
    set_app_setting,
)
from app.services.instance_service import create_instance, delete_instance

router = APIRouter(prefix="/api/admin")

_PAGE_SIZE_USERS = 25
_PAGE_SIZE_GROUPS = 10
_PAGE_SIZE_AUDIT = 50

_SYSTEM_PROMPT_DESCRIPTION = (
    "Der Prompt steuert Tonalität, Sprache und Verhalten des LLM.\n\n"
    "Pflicht-Platzhalter (müssen enthalten sein):\n"
    "  {context}  — gefundene Dokumentenabschnitte\n"
    "  {question} — Frage des Benutzers\n"
    "  {history}  — bisheriger Gesprächsverlauf\n\n"
    "Fehlt ein Platzhalter, wird beim Speichern ein Fehler gemeldet.\n\n"
    "Hinweis für Qwen3-Modelle: /no_think am Anfang des Prompts deaktiviert "
    "den internen Thinking-Modus. Ohne dieses Präfix werden Antworten deutlich "
    "langsamer und beginnen mit langen internen Überlegungen.\n\n"
    "Kontext-Budget: Der Prompt selbst belegt Tokens im LLM-Kontext (num_ctx). "
    "Ein sehr langer Prompt reduziert den verfügbaren Platz für Dokumentenabschnitte.\n\n"
    "Leer lassen = eingebauter Standardprompt wird verwendet."
)

_SETTINGS_SPEC: list[dict] = [
    {
        "key": "llm_model", "label": "LLM-Modell", "type": "text",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": "Muss in Ollama gepullt sein", "description": None,
    },
    {
        "key": "llm_temperature", "label": "Temperature", "type": "text",
        "inputmode": "decimal", "min": 0.0, "max": 2.0, "step": 0.1,
        "hint": "0.0 = deterministisch, 2.0 = kreativ", "description": None,
    },
    {
        "key": "llm_num_ctx", "label": "Kontext-Tokens (num_ctx)", "type": "number",
        "inputmode": None, "min": 1024, "max": 131072, "step": 1024,
        "hint": "Kontextfenster für Ollama",
        "description": (
            "Wie viele Tokens das LLM gleichzeitig im Blick behalten kann. "
            "Das Fenster enthält: System-Prompt (~150 T) + Gesprächsverlauf (~500 T) "
            "+ gefundene Dokumenten-Chunks (~6.000 T bei 10 Chunks) + Frage (~50 T).\n\n"
            "Standard 16.384 bietet ausreichend Puffer für die Standardkonfiguration. "
            "Erhöhen wenn das LLM Antworten abschneidet oder Kontext verliert. "
            "Senken wenn der GPU-VRAM knapp wird — jeder Token kostet ca. 0,5–2 MB VRAM."
        ),
    },
    {
        "key": "llm_timeout_seconds", "label": "LLM-Timeout (s)", "type": "number",
        "inputmode": None, "min": 10, "max": 600, "step": 10,
        "hint": "Max. Wartezeit auf LLM-Antwort", "description": None,
    },
    {
        "key": "llm_system_prompt", "label": "System-Prompt (LLM)", "type": "textarea",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": None, "description": _SYSTEM_PROMPT_DESCRIPTION,
    },
    {
        "key": "hybrid_bm25_weight", "label": "BM25-Gewicht", "type": "text",
        "inputmode": "decimal", "min": 0.0, "max": 1.0, "step": 0.05,
        "hint": "kNN-Gewicht = 1.0 − BM25",
        "description": (
            "Die Suche kombiniert zwei Verfahren: BM25 (Volltextsuche — findet exakte Wörter) "
            "und kNN (Vektorsuche — findet ähnliche Bedeutungen). Dieses Gewicht steuert das Verhältnis.\n\n"
            "Empfehlungen:\n"
            "• 0.3 / kNN 0.7 — allgemeine Texte, Berichte, freier Wortschatz\n"
            "• 0.4 / kNN 0.6 — Standard, gute Balance (Voreinstellung)\n"
            "• 0.5 / kNN 0.5 — technische Handbücher, Gesetze, Fachbegriffe sind kritisch\n\n"
            "Das kNN-Gewicht wird automatisch als 1.0 − BM25-Gewicht berechnet."
        ),
    },
    {
        "key": "hybrid_k", "label": "Anzahl Treffer (hybrid_k)", "type": "number",
        "inputmode": None, "min": 1, "max": 100, "step": 1,
        "hint": "Dokumenten-Chunks pro Anfrage",
        "description": (
            "Wie viele Dokumentenabschnitte (Chunks) pro Suchanfrage an das LLM übergeben werden.\n\n"
            "• Zu wenig (< 5): Relevante Stellen können fehlen, besonders bei breiten Fragen.\n"
            "• Zu viel (> 20): Das LLM bekommt mehr Kontext, aber irrelevante Abschnitte "
            "können die Antwort verwässern — und es werden mehr Tokens im Kontextfenster verbraucht.\n\n"
            "Standard 10 ist ein guter Ausgangspunkt. Bei sehr spezifischen Fragen genügen 5–7, "
            "bei Zusammenfassungsaufgaben können 15–20 sinnvoll sein."
        ),
    },
    {
        "key": "hybrid_score_threshold", "label": "Score-Schwelle", "type": "text",
        "inputmode": "decimal", "min": 0.0, "max": 1.0, "step": 0.01,
        "hint": "Mindest-Relevanz (0.0 = deaktiviert)",
        "description": (
            "Chunks mit einem Relevanz-Score unter diesem Wert werden verworfen, "
            "bevor sie ans LLM übergeben werden.\n\n"
            "• 0.0 — deaktiviert, alle Treffer werden verwendet\n"
            "• 0.05–0.1 — Standard, filtert nur klar irrelevante Treffer\n"
            "• 0.15–0.25 — streng, für homogene Dokumentensammlungen\n\n"
            "Symptom für zu hohen Wert: LLM antwortet häufig 'Information nicht gefunden', "
            "obwohl passende Dokumente vorhanden sind → Wert senken.\n"
            "Symptom für zu niedrigen Wert: LLM zieht thematisch falsche Stellen heran → Wert erhöhen."
        ),
    },
    {
        "key": "session_lifetime_hours", "label": "Session-Dauer (h)", "type": "number",
        "inputmode": None, "min": 1, "max": 720, "step": 1,
        "hint": "Standard: 8h", "description": None,
    },
    {
        "key": "max_upload_mb", "label": "Max. Upload-Größe (MB)", "type": "number",
        "inputmode": None, "min": 1, "max": 500, "step": 1,
        "hint": "Standard: 50 MB", "description": None,
    },
    {
        "key": "maintenance_mode", "label": "Wartungsmodus", "type": "text",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": "true | false",
        "description": (
            "Gültige Werte: true oder false.\n\n"
            "Im Wartungsmodus erhalten alle Nicht-Admins einen HTTP 503 auf alle Anfragen. "
            "Admins können weiterhin auf die Oberfläche zugreifen.\n\n"
            "Der Wartungsmodus kann bequemer über die Seite 'Wartung' in der Navigation "
            "ein- und ausgeschaltet werden."
        ),
    },
    {
        "key": "audit_retention_days", "label": "Audit-Retention (Tage)", "type": "number",
        "inputmode": None, "min": 7, "max": 3650, "step": 1,
        "hint": "Standard: 90 Tage", "description": None,
    },
]

_CASTMAP: dict[str, type] = {
    "llm_model": str, "llm_temperature": float, "llm_num_ctx": int,
    "llm_timeout_seconds": int, "llm_system_prompt": str,
    "hybrid_bm25_weight": float, "hybrid_k": int, "hybrid_score_threshold": float,
    "session_lifetime_hours": int, "max_upload_mb": int,
    "maintenance_mode": str, "audit_retention_days": int,
}


def _require_admin(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not user or not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    return user


def _like(q: str) -> str:
    parts = q.split("*")
    escaped = [p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for p in parts]
    return "%" + "%".join(escaped) + "%"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(db, user_id, action, target_type=None, target_id=None, detail=None):
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
    ))


# ─── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=_PAGE_SIZE_USERS, ge=1, le=100),
    q: str = Query(default=""),
    sort: Literal["ldap_uid", "display_name", "last_login", "created_at"] = Query(default="ldap_uid"),
    order: Literal["asc", "desc"] = Query(default="asc"),
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    base_stmt = select(User)
    if q:
        base_stmt = base_stmt.where(or_(
            User.ldap_uid.ilike(_like(q), escape="\\"),
            User.display_name.ilike(_like(q), escape="\\"),
        ))

    total = (await db.execute(select(func.count()).select_from(base_stmt.subquery()))).scalar_one()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    _col_map = {
        "ldap_uid": User.ldap_uid, "display_name": User.display_name,
        "last_login": User.last_login, "created_at": User.created_at,
    }
    col = _col_map.get(sort, User.ldap_uid)
    ordered = nullslast(col.asc()) if order == "asc" else nullsfirst(col.desc())
    users = (await db.execute(base_stmt.order_by(ordered).offset(offset).limit(per_page))).scalars().all()

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
            members_by_user.setdefault(mem.user_id, []).append({
                "instance_id": inst.id, "instance_name": inst.name, "role": mem.role,
            })

        groups = (await db.execute(select(Group))).scalars().all()
        group_map = {g.id: g.name for g in groups}
        gm_rows = (await db.execute(
            select(GroupMember).where(GroupMember.user_id.in_(user_ids))
        )).scalars().all()
        for gm in gm_rows:
            gname = group_map.get(gm.group_id)
            if gname:
                groups_by_user.setdefault(gm.user_id, []).append(gname)

    items = [
        AdminUserOut(
            id=u.id, ldap_uid=u.ldap_uid, display_name=u.display_name,
            email=u.email, is_global_admin=u.is_global_admin, is_active=u.is_active,
            created_at=u.created_at, last_login=u.last_login,
            instance_memberships=members_by_user.get(u.id, []),
            group_names=groups_by_user.get(u.id, []),
        )
        for u in users
    ]
    return PaginatedAdminUsers(items=items, total=total, page=page, total_pages=total_pages).model_dump(mode="json")


@router.post("/users", status_code=201)
async def create_user(
    body: AdminUserCreateRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pre-create a user so they can log in when auto-registration is disabled."""
    ldap_uid = body.ldap_uid.strip()
    if not ldap_uid:
        raise HTTPException(status_code=400, detail="ldap_uid darf nicht leer sein")

    existing = (await db.execute(select(User).where(User.ldap_uid == ldap_uid))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Benutzer mit dieser UID existiert bereits")

    now = _now()
    new_user = User(
        ldap_uid=ldap_uid,
        display_name=body.display_name,
        email=body.email,
        is_global_admin=body.is_global_admin,
        is_active=True,
        created_at=now,
    )
    db.add(new_user)
    _audit(db, admin.id, "user_pre_create", "user", None, {"ldap_uid": ldap_uid})
    await db.commit()
    await db.refresh(new_user)
    return user_out(new_user).model_dump(mode="json")


async def _count_remaining_admins(db: AsyncSession, exclude_id: int, also_active: bool = False) -> int:
    stmt = select(func.count()).select_from(User).where(
        User.is_global_admin == True, User.id != exclude_id,
    )
    if also_active:
        stmt = stmt.where(User.is_active == True)
    return (await db.execute(stmt)).scalar_one()


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: AdminUserPatchRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Eigenen Account nicht veränderbar")

    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    detail = {}
    if body.is_global_admin is not None:
        if not body.is_global_admin:
            remaining = await _count_remaining_admins(db, user_id)
            if remaining == 0:
                raise HTTPException(status_code=409, detail="Letzten Admin nicht entziehen")
        target.is_global_admin = body.is_global_admin
        detail["is_global_admin"] = body.is_global_admin

    if body.is_active is not None:
        if not body.is_active and target.is_global_admin:
            remaining = await _count_remaining_admins(db, user_id, also_active=True)
            if remaining == 0:
                raise HTTPException(status_code=409, detail="Letzten aktiven Admin nicht deaktivieren")
        target.is_active = body.is_active
        detail["is_active"] = body.is_active

    _audit(db, admin.id, "user_patch", "user", user_id, detail)
    await db.commit()
    await db.refresh(target)
    return user_out(target).model_dump(mode="json")


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Eigenen Account nicht löschbar")
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        return  # 204 even if not found
    if target.is_global_admin:
        remaining = await _count_remaining_admins(db, user_id)
        if remaining == 0:
            raise HTTPException(status_code=409, detail="Letzten Admin nicht löschbar")
    _audit(db, admin.id, "user_delete", "user", user_id, {"ldap_uid": target.ldap_uid})
    db.delete(target)
    await db.commit()


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(
    user_id: int,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Start impersonating another user. Returns new session cookie."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Eigenen Account nicht impersonierbar")

    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    from app.auth.session import create_session, SESSION_LIFETIME_HOURS
    lifetime_str = await get_app_setting(db, "session_lifetime_hours")
    lifetime_hours = int(lifetime_str) if lifetime_str else SESSION_LIFETIME_HOURS

    _secure = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    token = await create_session(
        db, user_id,
        lifetime_hours=lifetime_hours,
        is_impersonation=True,
        impersonated_by_id=admin.id,
    )
    _audit(db, admin.id, "impersonation_start", "user", user_id, {"target_uid": target.ldap_uid})
    await db.commit()

    response = JSONResponse(user_out(
        target,
        is_impersonation=True,
        impersonated_by=admin.ldap_uid,
    ).model_dump(mode="json"))
    response.set_cookie(
        "session_token", token,
        httponly=True, samesite="strict", secure=_secure, max_age=lifetime_hours * 3600,
    )
    return response


@router.post("/impersonation/stop")
async def stop_impersonation(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop active impersonation and restore admin session."""
    user = request.state.user
    is_impersonation = getattr(request.state, "is_impersonation", False)
    if not is_impersonation:
        raise HTTPException(status_code=400, detail="Keine aktive Impersonation")

    # Find current impersonation session to get impersonated_by_id
    token = request.cookies.get("session_token")
    import hashlib
    token_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
    session = (await db.execute(select(Session).where(Session.token == token_hash))).scalar_one_or_none()
    if not session or not session.impersonated_by_id:
        raise HTTPException(status_code=400, detail="Ungültige Impersonations-Session")

    admin_id = session.impersonated_by_id
    admin_user = (await db.execute(select(User).where(User.id == admin_id))).scalar_one_or_none()
    if not admin_user:
        raise HTTPException(status_code=404, detail="Admin-Benutzer nicht gefunden")

    from app.auth.session import create_session, delete_session, SESSION_LIFETIME_HOURS
    lifetime_str = await get_app_setting(db, "session_lifetime_hours")
    lifetime_hours = int(lifetime_str) if lifetime_str else SESSION_LIFETIME_HOURS
    _secure = os.getenv("SECURE_COOKIES", "false").lower() == "true"

    if token:
        await delete_session(db, token)
    new_token = await create_session(db, admin_id, lifetime_hours=lifetime_hours)

    _audit(db, admin_id, "impersonation_stop", "user", user.id, {"target_uid": user.ldap_uid})
    await db.commit()

    response = JSONResponse(user_out(admin_user).model_dump(mode="json"))
    response.set_cookie(
        "session_token", new_token,
        httponly=True, samesite="strict", secure=_secure, max_age=lifetime_hours * 3600,
    )
    return response


@router.post("/users/{user_id}/instances")
async def assign_user_instance(
    user_id: int,
    body: AssignInstanceRequest,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == user_id,
            InstanceMember.instance_id == body.instance_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.role = body.role
    else:
        db.add(InstanceMember(user_id=user_id, instance_id=body.instance_id, role=body.role, added_by=admin.id))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/instances/{instance_id}", status_code=204)
async def remove_user_instance(
    user_id: int, instance_id: int,
    admin=Depends(_require_admin),
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


@router.post("/users/{user_id}/groups")
async def add_user_to_group(
    user_id: int,
    body: AssignUserGroupRequest,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == body.group_id,
            GroupMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(GroupMember(group_id=body.group_id, user_id=user_id))
        await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/groups/{group_id}", status_code=204)
async def remove_user_from_group(
    user_id: int, group_id: int,
    admin=Depends(_require_admin),
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


# ─── Instances ────────────────────────────────────────────────────────────────

async def _build_instance_admin_out(db: AsyncSession, instance: Instance, redis=None) -> InstanceAdminOut:
    member_count = (await db.execute(
        select(func.count()).select_from(InstanceMember).where(InstanceMember.instance_id == instance.id)
    )).scalar_one()
    group_count = (await db.execute(
        select(func.count()).select_from(GroupInstanceRole).where(GroupInstanceRole.instance_id == instance.id)
    )).scalar_one()
    doc_count = 0
    if redis is not None:
        from app.services.document_service import list_documents
        docs = await list_documents(redis, instance.slug)
        doc_count = len(docs)
    return InstanceAdminOut(
        id=instance.id, name=instance.name, slug=instance.slug,
        description=instance.description, settings=instance.settings,
        created_at=instance.created_at, updated_at=instance.updated_at,
        member_count=member_count, group_count=group_count, doc_count=doc_count,
    )


@router.get("/instances")
async def list_admin_instances(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    instances = (await db.execute(select(Instance))).scalars().all()
    return [
        (await _build_instance_admin_out(db, inst, redis)).model_dump(mode="json")
        for inst in instances
    ]


@router.post("/instances", status_code=201)
async def create_admin_instance(
    body: InstanceCreateRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    instance = await create_instance(db, config, body.name, body.description, analyzer=body.analyzer)
    _audit(db, admin.id, "instance_create", "instance", instance.id, {"name": instance.name, "slug": instance.slug})
    await db.commit()
    return (await _build_instance_admin_out(db, instance)).model_dump(mode="json")


@router.get("/instances/{instance_id}")
async def get_admin_instance(
    instance_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")
    return (await _build_instance_admin_out(db, instance, redis)).model_dump(mode="json")


@router.patch("/instances/{instance_id}")
async def patch_admin_instance(
    instance_id: int,
    body: InstancePatchRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    if body.name is not None:
        instance.name = body.name.strip()
    if body.description is not None:
        instance.description = body.description.strip()
    _SYSTEM_KEYS = {"opensearch_analyzer"}
    _VISUAL_KEYS = ("icon", "color")
    existing = instance.settings or {}
    preserved_system = {k: v for k, v in existing.items() if k in _SYSTEM_KEYS}
    preserved_visual = {k: v for k, v in existing.items() if k in _VISUAL_KEYS}

    if body.clear_settings:
        instance.settings = {**preserved_system, **preserved_visual} or None
    elif body.settings is not None:
        _castmap = {
            "llm_model": str, "llm_temperature": float,
            "llm_num_ctx": int, "hybrid_k": int, "hybrid_score_threshold": float,
        }
        overrides = {**preserved_system, **preserved_visual}
        for k in _VISUAL_KEYS:
            raw = body.settings.get(k)
            if raw is not None:
                if raw == "":
                    overrides.pop(k, None)
                else:
                    overrides[k] = str(raw)
        for key, cast in _castmap.items():
            raw = body.settings.get(key)
            if raw is not None and raw != "":
                try:
                    overrides[key] = cast(str(raw).replace(",", "."))
                except (ValueError, TypeError):
                    pass

        # System-Prompt: empty string = clear override; non-empty = validate + store
        raw_prompt = body.settings.get("llm_system_prompt")
        if raw_prompt is not None:
            prompt_str = str(raw_prompt).strip()
            if not prompt_str:
                overrides.pop("llm_system_prompt", None)
            else:
                from app.rag import validate_system_prompt
                missing = validate_system_prompt(prompt_str)
                if missing:
                    raise HTTPException(
                        status_code=422,
                        detail=f"System-Prompt: fehlende Platzhalter {missing}. Erforderlich: {{context}}, {{question}}, {{history}}",
                    )
                overrides["llm_system_prompt"] = prompt_str

        instance.settings = overrides or None

    _audit(db, admin.id, "instance_patch", "instance", instance.id, {"name": instance.name})
    instance.updated_at = _now()
    from app.loader.vector_store import invalidate_instance_cache
    invalidate_instance_cache(instance.slug)
    await db.commit()
    await db.refresh(instance)
    return (await _build_instance_admin_out(db, instance)).model_dump(mode="json")


@router.delete("/instances/{instance_id}", status_code=204)
async def delete_admin_instance(
    instance_id: int,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        return
    slug = instance.slug
    await delete_instance(db, config, instance_id, redis)
    _audit(db, admin.id, "instance_delete", "instance", instance_id, {"slug": slug})
    await db.commit()


@router.get("/instances/{instance_id}/members")
async def list_instance_members(
    instance_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(InstanceMember, User)
        .join(User, InstanceMember.user_id == User.id)
        .where(InstanceMember.instance_id == instance_id)
        .order_by(User.ldap_uid)
    )).all()
    return [
        InstanceMemberOut(
            user_id=user.id, ldap_uid=user.ldap_uid,
            display_name=user.display_name, role=mem.role,
        ).model_dump()
        for mem, user in rows
    ]


@router.post("/instances/{instance_id}/members", status_code=201)
async def add_instance_member(
    instance_id: int,
    body: AddInstanceMemberRequest,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")
    user = (await db.execute(select(User).where(User.id == body.user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    existing = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == body.user_id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.role = body.role
    else:
        db.add(InstanceMember(user_id=body.user_id, instance_id=instance_id, role=body.role, added_by=admin.id))
    _audit(db, admin.id, "instance_member_add", "instance", instance_id, {"user_id": body.user_id, "role": body.role})
    await db.commit()
    return {"ok": True}


@router.delete("/instances/{instance_id}/members/{user_id}", status_code=204)
async def remove_instance_member(
    instance_id: int, user_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    mem = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == user_id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if mem:
        db.delete(mem)
        _audit(db, admin.id, "instance_member_remove", "instance", instance_id, {"user_id": user_id})
        await db.commit()


@router.post("/instances/{instance_id}/rebuild-redis")
async def rebuild_redis(
    instance_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    from app.loader.vector_store import VectorStore
    from app.metadata.redis_service import RedisMetadataService, DocumentMetadata

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    store = await asyncio.to_thread(VectorStore.for_instance, config, instance.slug)
    client = store._get_raw_client()
    agg_body = {
        "size": 0,
        "aggs": {"by_hash": {
            "terms": {"field": "metadata.file_hash", "size": 10000},
            "aggs": {
                "filename":    {"terms": {"field": "metadata.filename", "size": 1}},
                "max_page":    {"max": {"field": "metadata.page"}},
                "chunk_count": {"value_count": {"field": "metadata.chunk_index"}},
            },
        }},
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
        if not await service.get_document_metadata(file_hash):
            await service.save_document_metadata(
                file_hash,
                DocumentMetadata(
                    title=filename, file_size=0, page_count=page_count,
                    chunk_count=chunk_count, source_path="",
                    indexed_date=datetime.now(timezone.utc).isoformat(),
                    file_hash=file_hash, additional_metadata={"rebuilt": True},
                ),
            )
            rebuilt += 1
    return {"rebuilt": rebuilt}


# ─── Groups ───────────────────────────────────────────────────────────────────

@router.get("/groups")
async def list_groups(
    page: int = Query(default=1, ge=1),
    q: str = Query(default=""),
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    base_stmt = select(Group)
    if q:
        base_stmt = base_stmt.where(Group.name.ilike(_like(q), escape="\\"))

    total = (await db.execute(select(func.count()).select_from(base_stmt.subquery()))).scalar_one()
    total_pages = max(1, (total + _PAGE_SIZE_GROUPS - 1) // _PAGE_SIZE_GROUPS)
    page = min(page, total_pages)
    offset = (page - 1) * _PAGE_SIZE_GROUPS

    groups = (await db.execute(base_stmt.order_by(Group.name).offset(offset).limit(_PAGE_SIZE_GROUPS))).scalars().all()
    group_ids = [g.id for g in groups]

    gir_by_group: dict[int, list] = {}
    member_ids_by_group: dict[int, list[int]] = {}
    if group_ids:
        gir_rows = (await db.execute(
            select(GroupInstanceRole, Instance)
            .join(Instance, GroupInstanceRole.instance_id == Instance.id)
            .where(GroupInstanceRole.group_id.in_(group_ids))
        )).all()
        for gir, inst in gir_rows:
            gir_by_group.setdefault(gir.group_id, []).append(
                GroupInstanceRoleOut(instance_id=inst.id, instance_name=inst.name, role=gir.role)
            )

        gm_rows = (await db.execute(
            select(GroupMember).where(GroupMember.group_id.in_(group_ids))
        )).scalars().all()
        for gm in gm_rows:
            member_ids_by_group.setdefault(gm.group_id, []).append(gm.user_id)

    items = [
        GroupOut(
            id=g.id, name=g.name, ldap_group_dn=g.ldap_group_dn, created_at=g.created_at,
            member_ids=member_ids_by_group.get(g.id, []),
            instance_roles=gir_by_group.get(g.id, []),
        )
        for g in groups
    ]
    return PaginatedGroups(items=items, total=total, page=page, total_pages=total_pages).model_dump(mode="json")


@router.post("/groups", status_code=201)
async def create_group(
    body: GroupCreateRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.exc import IntegrityError
    db.add(Group(name=body.name, ldap_group_dn=body.ldap_group_dn or None))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Gruppenname bereits vergeben")
    group = (await db.execute(select(Group).where(Group.name == body.name))).scalar_one()
    _audit(db, admin.id, "group_create", "group", group.id, {"name": group.name})
    await db.commit()
    return GroupOut(id=group.id, name=group.name, ldap_group_dn=group.ldap_group_dn, created_at=group.created_at).model_dump(mode="json")


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    group = (await db.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if group:
        _audit(db, admin.id, "group_delete", "group", group_id, {"name": group.name})
        db.delete(group)
        await db.commit()


@router.post("/groups/{group_id}/instances")
async def assign_group_instance(
    group_id: int,
    body: AssignGroupInstanceRequest,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(GroupInstanceRole).where(
            GroupInstanceRole.group_id == group_id,
            GroupInstanceRole.instance_id == body.instance_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.role = body.role
    else:
        db.add(GroupInstanceRole(group_id=group_id, instance_id=body.instance_id, role=body.role))
    await db.commit()
    return {"ok": True}


@router.delete("/groups/{group_id}/instances/{instance_id}", status_code=204)
async def remove_group_instance(
    group_id: int, instance_id: int,
    admin=Depends(_require_admin),
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


@router.post("/groups/{group_id}/members")
async def add_group_member(
    group_id: int,
    body: AddGroupMemberRequest,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == body.user_id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(GroupMember(group_id=group_id, user_id=body.user_id))
        await db.commit()
    return {"ok": True}


@router.delete("/groups/{group_id}/members/{user_id}", status_code=204)
async def remove_group_member(
    group_id: int, user_id: int,
    admin=Depends(_require_admin),
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


# ─── Settings ─────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    rows = (await db.execute(select(AppSetting))).scalars().all()
    settings = [SettingOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]
    spec = [SettingSpec(**s) for s in _SETTINGS_SPEC]
    return SettingsResponse(settings=settings, spec=spec, config_snapshot={}).model_dump(mode="json")


@router.patch("/settings")
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
        # System-Prompt: no comma-stripping; empty string = delete (revert to built-in default)
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

    # LLM model availability check
    if "llm_model" in new_values and new_values["llm_model"] != config.llm_model:
        ok, msg = await _check_ollama_model(config.ollama_host, new_values["llm_model"])
        if not ok:
            raise HTTPException(status_code=422, detail=msg)

    now = _now()
    # Delete cleared settings (e.g. system prompt reset to built-in default)
    for key in delete_keys:
        existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if existing:
            await db.delete(existing)
        if hasattr(config, key):
            new_values[key] = ""  # reflect in-memory reset

    for key, val in new_values.items():
        existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if existing:
            existing.value = str(val)
            existing.updated_at = now
            existing.updated_by = admin.id
        else:
            db.add(AppSetting(key=key, value=str(val), updated_at=now, updated_by=admin.id))
    await db.commit()

    # Update in-memory config
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

    rows = (await db.execute(select(AppSetting))).scalars().all()
    return [SettingOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]


# ─── LDAP config ──────────────────────────────────────────────────────────────

@router.get("/ldap")
async def get_ldap(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    cfg = await get_ldap_config(db)
    return LDAPConfigOut(
        ldap_url=cfg.get("ldap_url", ""),
        ldap_user_search_base=cfg.get("ldap_user_search_base", ""),
        ldap_uid_attr=cfg.get("ldap_uid_attr", "uid"),
        ldap_display_name_attr=cfg.get("ldap_display_name_attr", "displayName"),
        ldap_mail_attr=cfg.get("ldap_mail_attr", "mail"),
        ldap_user_filter=cfg.get("ldap_user_filter", "(objectClass=inetOrgPerson)"),
        ldap_admin_group_dn=cfg.get("ldap_admin_group_dn", ""),
        ldap_bind_dn=cfg.get("ldap_bind_dn", ""),
        ldap_bind_password_set=bool(cfg.get("ldap_bind_password")),
        ldap_enabled=cfg.get("ldap_enabled", "true").lower() not in ("false", "0", "off"),
        ldap_allow_auto_registration=cfg.get("ldap_allow_auto_registration", "true").lower() not in ("false", "0", "off"),
    ).model_dump()


@router.put("/ldap")
async def update_ldap(
    body: LDAPConfigIn,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    data = body.model_dump(exclude={"ldap_bind_password"})
    data["ldap_enabled"] = "true" if body.ldap_enabled else "false"
    data["ldap_allow_auto_registration"] = "true" if body.ldap_allow_auto_registration else "false"
    if body.ldap_bind_password is not None:
        data["ldap_bind_password"] = body.ldap_bind_password
    await save_ldap_config(db, data, updated_by=admin.id)

    _audit(db, admin.id, "ldap_config_change", detail={"url": body.ldap_url})
    await db.commit()

    cfg = await get_ldap_config(db)
    return LDAPConfigOut(
        ldap_url=cfg.get("ldap_url", ""),
        ldap_user_search_base=cfg.get("ldap_user_search_base", ""),
        ldap_uid_attr=cfg.get("ldap_uid_attr", "uid"),
        ldap_display_name_attr=cfg.get("ldap_display_name_attr", "displayName"),
        ldap_mail_attr=cfg.get("ldap_mail_attr", "mail"),
        ldap_user_filter=cfg.get("ldap_user_filter", "(objectClass=inetOrgPerson)"),
        ldap_admin_group_dn=cfg.get("ldap_admin_group_dn", ""),
        ldap_bind_dn=cfg.get("ldap_bind_dn", ""),
        ldap_bind_password_set=bool(cfg.get("ldap_bind_password")),
        ldap_enabled=cfg.get("ldap_enabled", "true").lower() not in ("false", "0", "off"),
        ldap_allow_auto_registration=cfg.get("ldap_allow_auto_registration", "true").lower() not in ("false", "0", "off"),
    ).model_dump()


@router.post("/ldap/test")
async def test_ldap(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Test LDAP connectivity using the stored bind credentials."""
    import asyncio as _asyncio
    from ldap3 import Server, Connection, ALL
    from ldap3.core.exceptions import LDAPException

    cfg = await get_ldap_config(db)
    ldap_url = cfg.get("ldap_url", "")
    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_pw = cfg.get("ldap_bind_password", "")

    def _do_test():
        try:
            server = Server(ldap_url, get_info=ALL, connect_timeout=5)
            conn = Connection(
                server,
                user=bind_dn or None,
                password=bind_pw or None,
                auto_bind=True,
            )
            conn.unbind()
            return {"ok": True, "error": None}
        except LDAPException as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return await _asyncio.to_thread(_do_test)


@router.post("/ldap/search")
async def search_ldap_users(
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Search LDAP for users matching a query string. Requires Bind DN to be configured."""
    import asyncio as _asyncio
    from ldap3 import Server, Connection, ALL, SUBTREE
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    body = await request.json()
    query = str(body.get("query", "")).strip()

    cfg = await get_ldap_config(db)
    ldap_url = cfg.get("ldap_url", "")
    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_pw = cfg.get("ldap_bind_password", "")
    search_base = cfg.get("ldap_user_search_base", "")
    uid_attr = cfg.get("ldap_uid_attr", "uid")
    dn_attr = cfg.get("ldap_display_name_attr", "displayName")
    mail_attr = cfg.get("ldap_mail_attr", "mail")
    user_filter = cfg.get("ldap_user_filter", "(objectClass=inetOrgPerson)")

    if not bind_dn:
        raise HTTPException(status_code=400, detail="Kein Bind-DN konfiguriert. LDAP-Suche erfordert einen Service-Account.")

    def _do_search():
        try:
            server = Server(ldap_url, get_info=ALL, connect_timeout=5)
            conn = Connection(server, user=bind_dn, password=bind_pw or None, auto_bind=True)

            if query:
                escaped = escape_filter_chars(query)
                search_filter = f"(&{user_filter}(|({uid_attr}=*{escaped}*)({dn_attr}=*{escaped}*)({mail_attr}=*{escaped}*)))"
            else:
                search_filter = user_filter

            conn.search(
                search_base=search_base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=[uid_attr, dn_attr, mail_attr],
                size_limit=50,
            )

            results = []
            for entry in conn.entries:
                uid_val = getattr(entry, uid_attr, None)
                if not uid_val or not uid_val.value:
                    continue
                results.append({
                    "ldap_uid": str(uid_val.value),
                    "display_name": str(getattr(entry, dn_attr).value) if getattr(entry, dn_attr, None) and getattr(entry, dn_attr).value else None,
                    "email": str(getattr(entry, mail_attr).value) if getattr(entry, mail_attr, None) and getattr(entry, mail_attr).value else None,
                })
            conn.unbind()
            return results
        except LDAPException as exc:
            raise RuntimeError(str(exc)) from exc

    try:
        results = await _asyncio.to_thread(_do_search)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"LDAP-Fehler: {exc}") from exc

    existing_uids = {
        row[0] for row in (await db.execute(select(User.ldap_uid))).all()
    }
    return [
        LDAPSearchResult(
            ldap_uid=r["ldap_uid"],
            display_name=r["display_name"],
            email=r["email"],
        ).model_dump()
        for r in results
        if r["ldap_uid"] not in existing_uids
    ]


@router.post("/ldap/sync")
async def sync_ldap(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Sync display_name, email and admin-group membership for all active users via LDAP bind-dn search."""
    import asyncio as _asyncio
    from ldap3 import Server, Connection, ALL
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    cfg = await get_ldap_config(db)
    ldap_url = cfg.get("ldap_url", "")
    search_base = cfg.get("ldap_user_search_base", "")
    uid_attr = cfg.get("ldap_uid_attr", "uid")
    dn_attr = cfg.get("ldap_display_name_attr", "displayName")
    mail_attr = cfg.get("ldap_mail_attr", "mail")
    admin_group_dn = cfg.get("ldap_admin_group_dn", "")
    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_pw = cfg.get("ldap_bind_password", "")

    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712

    synced = 0
    errors = 0

    def _sync_user(ldap_uid: str):
        try:
            server = Server(ldap_url, get_info=ALL, connect_timeout=5)
            conn = Connection(server, user=bind_dn or None, password=bind_pw or None, auto_bind=True)
            conn.search(
                search_base=search_base,
                search_filter=f"({uid_attr}={escape_filter_chars(ldap_uid)})",
                attributes=[uid_attr, dn_attr, mail_attr],
            )
            if not conn.entries:
                conn.unbind()
                return None
            entry = conn.entries[0]
            result = {
                "display_name": str(getattr(entry, dn_attr, ldap_uid) or ldap_uid),
                "email": str(getattr(entry, mail_attr, "") or ""),
                "is_global_admin": False,
            }
            if admin_group_dn:
                user_dn = f"{uid_attr}={ldap_uid},{search_base}"
                conn.search(
                    search_base=admin_group_dn,
                    search_filter=f"(member={escape_filter_chars(user_dn)})",
                    attributes=["cn"],
                )
                result["is_global_admin"] = len(conn.entries) > 0
            conn.unbind()
            return result
        except LDAPException:
            return None
        except Exception:
            return None

    for user in users:
        if not user.ldap_uid or user.local_password_hash:
            continue
        try:
            ldap_data = await _asyncio.to_thread(_sync_user, user.ldap_uid)
            if ldap_data:
                user.display_name = ldap_data["display_name"]
                user.email = ldap_data["email"]
                if admin_group_dn:
                    user.is_global_admin = ldap_data["is_global_admin"]
                synced += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    if synced:
        await db.commit()

    _audit(db, admin.id, "ldap_sync", detail={"synced": synced, "errors": errors})
    await db.commit()

    return {"synced": synced, "errors": errors}


# ─── System status ────────────────────────────────────────────────────────────

@router.get("/status")
async def system_status(
    admin=Depends(_require_admin),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    import httpx
    status: dict = {}

    # OpenSearch
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
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

    # Ollama
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

    # Redis
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

    # PostgreSQL
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


# ─── Maintenance mode ─────────────────────────────────────────────────────────

@router.get("/maintenance")
async def get_maintenance(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(AppSetting).where(AppSetting.key == "maintenance_mode")
    )).scalar_one_or_none()
    active = row is not None and row.value.lower() in ("1", "true", "on")
    return {"maintenance_mode": active}


@router.post("/maintenance")
async def set_maintenance(
    body: dict,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    enabled = bool(body.get("enabled", False))
    value = "true" if enabled else "false"
    now = _now()
    existing = (await db.execute(
        select(AppSetting).where(AppSetting.key == "maintenance_mode")
    )).scalar_one_or_none()
    if existing:
        existing.value = value
        existing.updated_at = now
        existing.updated_by = admin.id
    else:
        db.add(AppSetting(key="maintenance_mode", value=value, updated_at=now, updated_by=admin.id))
    _audit(db, admin.id, "maintenance_mode_change", detail={"enabled": enabled})
    await db.commit()
    invalidate_maintenance_cache()
    return {"maintenance_mode": enabled}


# ─── Audit log ────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_log(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=_PAGE_SIZE_AUDIT, le=200),
    action: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    count_stmt = select(func.count(AuditLog.id))
    stmt = select(AuditLog)
    if action:
        count_stmt = count_stmt.where(AuditLog.action == action)
        stmt = stmt.where(AuditLog.action == action)
    if user_id is not None:
        count_stmt = count_stmt.where(AuditLog.user_id == user_id)
        stmt = stmt.where(AuditLog.user_id == user_id)

    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages)

    rows = (await db.execute(
        stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )).scalars().all()

    items = [
        AuditLogOut(
            id=r.id, user_id=r.user_id, action=r.action,
            target_type=r.target_type, target_id=r.target_id,
            detail=r.detail, ip_address=r.ip_address, created_at=r.created_at,
        )
        for r in rows
    ]
    return PaginatedAuditLog(items=items, total=total, page=page, total_pages=total_pages).model_dump(mode="json")


# ─── Helpers ──────────────────────────────────────────────────────────────────

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
        return True, ""  # Don't block if Ollama unreachable
