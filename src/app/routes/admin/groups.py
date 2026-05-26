"""Admin-Endpunkte: Gruppenverwaltung."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, GroupInstanceRole, GroupMember, Instance
from app.db.session import get_db
from app.schemas import (
    AddGroupMemberRequest,
    AssignGroupInstanceRequest,
    GroupCreateRequest,
    GroupInstanceRoleOut,
    GroupOut,
    PaginatedGroups,
)
from app.routes.admin._shared import _PAGE_SIZE_GROUPS, _audit, _like, _require_admin

router = APIRouter()


@router.get("")
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


@router.post("", status_code=201)
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


@router.delete("/{group_id}", status_code=204)
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


@router.post("/{group_id}/instances")
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


@router.delete("/{group_id}/instances/{instance_id}", status_code=204)
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


@router.post("/{group_id}/members")
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


@router.delete("/{group_id}/members/{user_id}", status_code=204)
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
