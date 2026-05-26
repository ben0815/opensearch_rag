"""Admin-Endpunkte: Benutzerverwaltung."""
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, nullsfirst, nullslast, or_, select
from sqlalchemy import delete as _delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import create_session, SESSION_LIFETIME_HOURS
from app.db.models import Group, GroupMember, Instance, InstanceMember, Session, User
from app.db.session import get_db
from app.schemas import (
    AdminUserCreateRequest,
    AdminUserOut,
    AdminUserPatchRequest,
    AssignInstanceRequest,
    AssignUserGroupRequest,
    PaginatedAdminUsers,
    user_out,
)
from app.services.config_service import get_app_setting
from app.routes.admin._shared import (
    _PAGE_SIZE_USERS, _audit, _like, _now, _require_admin,
)

router = APIRouter()


async def _count_remaining_admins(db: AsyncSession, exclude_id: int, also_active: bool = False) -> int:
    stmt = select(func.count()).select_from(User).where(
        User.is_global_admin == True, User.id != exclude_id,  # noqa: E712
    )
    if also_active:
        stmt = stmt.where(User.is_active == True)  # noqa: E712
    return (await db.execute(stmt)).scalar_one()


@router.get("")
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=_PAGE_SIZE_USERS, ge=1, le=100),
    q: str = Query(default=""),
    sort: str = Query(default="ldap_uid"),
    order: str = Query(default="asc"),
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


@router.post("", status_code=201)
async def create_user(
    body: AdminUserCreateRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
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


@router.patch("/{user_id}")
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
        if body.is_active is False:
            await db.execute(_delete(Session).where(Session.user_id == target.id))
        target.is_active = body.is_active
        detail["is_active"] = body.is_active

    _audit(db, admin.id, "user_patch", "user", user_id, detail)
    await db.commit()
    await db.refresh(target)
    return user_out(target).model_dump(mode="json")


@router.delete("/{user_id}", status_code=204)
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
        return
    if target.is_global_admin:
        remaining = await _count_remaining_admins(db, user_id)
        if remaining == 0:
            raise HTTPException(status_code=409, detail="Letzten Admin nicht löschbar")
    _audit(db, admin.id, "user_delete", "user", user_id, {"ldap_uid": target.ldap_uid})
    db.delete(target)
    await db.commit()


@router.post("/{user_id}/impersonate")
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

    if target.is_global_admin:
        raise HTTPException(status_code=403, detail="Admins können nicht impersoniert werden")

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


@router.post("/{user_id}/instances")
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


@router.delete("/{user_id}/instances/{instance_id}", status_code=204)
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


@router.post("/{user_id}/groups")
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


@router.delete("/{user_id}/groups/{group_id}", status_code=204)
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
