from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import User, InstanceMember, GroupMember, GroupInstanceRole, Instance


async def get_user_instances(db: AsyncSession, user: User) -> list[dict]:
    """
    Gibt alle Instanzen zurück, auf die der Benutzer Zugriff hat,
    mit effektiver Rolle (maximum aus direkter + Gruppen-Rolle).
    Format: [{"instance": Instance, "role": "viewer"|"manager"}, ...]
    """
    if user.is_global_admin:
        result = await db.execute(select(Instance))
        return [{"instance": i, "role": "manager"} for i in result.scalars().all()]

    # Direkte Zuweisungen
    direct = await db.execute(
        select(InstanceMember, Instance)
        .join(Instance, InstanceMember.instance_id == Instance.id)
        .where(InstanceMember.user_id == user.id)
    )
    access: dict[int, dict] = {}
    for member, instance in direct:
        access[instance.id] = {"instance": instance, "role": member.role}

    # Gruppen-Zuweisungen
    group_result = await db.execute(
        select(GroupInstanceRole, Instance)
        .join(Instance, GroupInstanceRole.instance_id == Instance.id)
        .join(GroupMember, GroupMember.group_id == GroupInstanceRole.group_id)
        .where(GroupMember.user_id == user.id)
    )
    for gir, instance in group_result:
        if instance.id not in access:
            access[instance.id] = {"instance": instance, "role": gir.role}
        elif gir.role == "manager":
            access[instance.id]["role"] = "manager"  # manager schlägt viewer

    return list(access.values())


async def get_effective_role(db: AsyncSession, user: User, instance_id: int) -> str | None:
    """
    Gibt die effektive Rolle für genau eine Instanz zurück.
    2 gezielte Queries statt get_user_instances() aufzurufen (das lädt ALLE Instanzen).
    """
    if user.is_global_admin:
        return "manager"

    direct = (await db.execute(
        select(InstanceMember.role).where(
            InstanceMember.user_id == user.id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()

    group_roles = (await db.execute(
        select(GroupInstanceRole.role)
        .join(GroupMember, GroupMember.group_id == GroupInstanceRole.group_id)
        .where(GroupMember.user_id == user.id, GroupInstanceRole.instance_id == instance_id)
    )).scalars().all()

    all_roles = ([direct] if direct else []) + list(group_roles)
    if not all_roles:
        return None
    return "manager" if "manager" in all_roles else "viewer"
