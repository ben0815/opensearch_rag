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
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    await create_instance(db, config, name, description)
    return RedirectResponse(url="/admin/instances", status_code=303)


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
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * _PAGE_SIZE_GROUPS

    total: int = (await db.execute(select(func.count()).select_from(Group))).scalar_one()
    total_pages = max(1, (total + _PAGE_SIZE_GROUPS - 1) // _PAGE_SIZE_GROUPS)

    groups = (await db.execute(
        select(Group).order_by(Group.name).offset(offset).limit(_PAGE_SIZE_GROUPS)
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

    return templates.TemplateResponse(request, "admin/groups.html", {
        "user": user,
        "groups": groups, "instances": instances, "users": users,
        "gir_by_group": gir_by_group,
        "members_by_group": members_by_group,
        "page": page, "total_pages": total_pages,
    })


@router.post("/groups/create")
async def create_group(
    request: Request,
    name: str = Form(...),
    ldap_group_dn: str = Form(default=""),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    db.add(Group(name=name, ldap_group_dn=ldap_group_dn or None))
    await db.commit()
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
    role: str = Form(...),
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


@router.post("/users/{user_id}/set-admin")
async def set_admin(
    user_id: int,
    request: Request,
    is_admin: bool = Form(...),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target:
        target.is_global_admin = is_admin
        await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/assign-instance")
async def assign_user_to_instance(
    user_id: int,
    request: Request,
    instance_id: int = Form(...),
    role: str = Form(...),
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
        # Selbst-Löschung verhindern — würde laufende Session sofort invalidieren
        return RedirectResponse(url="/admin/users", status_code=303)
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
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
