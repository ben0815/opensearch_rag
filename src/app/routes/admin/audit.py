"""Admin-Endpunkte: Audit-Log."""
from datetime import date as _date, datetime, time as _time
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User
from app.db.session import get_db
from app.schemas import AuditLogOut, PaginatedAuditLog
from app.routes.admin._shared import _PAGE_SIZE_AUDIT, _require_admin

router = APIRouter()

_SORT_COLS = {
    "created_at": AuditLog.created_at,
    "ip_address": AuditLog.ip_address,
    "action": AuditLog.action,
    "user_id": AuditLog.user_id,
}


@router.get("")
async def get_audit_log(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=_PAGE_SIZE_AUDIT, le=200),
    action: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    username: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    order_by: Literal["created_at", "ip_address", "action", "user_id"] = Query(default="created_at"),
    order_dir: Literal["asc", "desc"] = Query(default="desc"),
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    sort_col = _SORT_COLS[order_by]
    sort_expr = sort_col.asc() if order_dir == "asc" else sort_col.desc()

    # Build WHERE conditions list — applied to both count and data queries.
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if username:
        conditions.append(User.ldap_uid.ilike(f"%{username}%"))
    if ip:
        conditions.append(AuditLog.ip_address.ilike(f"%{ip}%"))
    if date_from:
        try:
            conditions.append(AuditLog.created_at >= datetime.combine(_date.fromisoformat(date_from), _time.min))
        except ValueError:
            pass
    if date_to:
        try:
            conditions.append(AuditLog.created_at <= datetime.combine(_date.fromisoformat(date_to), _time.max))
        except ValueError:
            pass

    count_stmt = (
        select(func.count(AuditLog.id))
        .select_from(AuditLog)
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages)

    data_stmt = (
        select(AuditLog, User.ldap_uid)
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(*conditions)
        .order_by(sort_expr)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(data_stmt)).all()

    items = [
        AuditLogOut(
            id=r.AuditLog.id,
            user_id=r.AuditLog.user_id,
            action=r.AuditLog.action,
            target_type=r.AuditLog.target_type,
            target_id=r.AuditLog.target_id,
            detail=r.AuditLog.detail,
            ip_address=r.AuditLog.ip_address,
            created_at=r.AuditLog.created_at,
            ldap_uid=r.ldap_uid,
        )
        for r in rows
    ]
    return PaginatedAuditLog(items=items, total=total, page=page, total_pages=total_pages).model_dump(mode="json")
