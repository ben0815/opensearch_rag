"""Admin-Endpunkte: Audit-Log."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.db.session import get_db
from app.schemas import AuditLogOut, PaginatedAuditLog
from app.routes.admin._shared import _PAGE_SIZE_AUDIT, _require_admin

router = APIRouter()


@router.get("")
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
