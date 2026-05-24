import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import iterate_in_threadpool

from app.db.models import AuditLog, ChatHistory, Instance
from app.db.session import get_db
from app.dependencies import get_config, limiter, _get_user_or_ip
from app.loader.config import LoaderConfig
from app.schemas import (
    ChatHistoryOut,
    ChatHistoryPatchRequest,
    ChatRequest,
    PaginatedChatHistory,
)
from app.services.chat_service import _DONE_SENTINEL_KEY, stream_answer
from app.services.config_service import get_effective_config
from app.services.user_service import get_effective_role, get_user_instances

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")

_PAGE_SIZE = 50


def _like(q: str) -> str:
    parts = q.split("*")
    escaped = [p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for p in parts]
    return "%" + "%".join(escaped) + "%"


@router.post("/stream")
@limiter.limit("30/minute", key_func=_get_user_or_ip)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    user = request.state.user
    instance_id = body.instance_id

    if not user.is_global_admin:
        role = await get_effective_role(db, user, instance_id)
        if role is None:
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Instanz")

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    history_stmt = (
        select(ChatHistory)
        .where(ChatHistory.user_id == user.id, ChatHistory.instance_id == instance_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(3)
    )
    recent_history = list(reversed((await db.execute(history_stmt)).scalars().all()))

    effective_config = get_effective_config(config, instance.settings)
    question = body.question
    user_id = user.id

    def _generator():
        try:
            yield from stream_answer(question, instance.slug, effective_config, recent_history)
        except Exception as e:
            logger.error("Stream-Fehler für Instanz %s: %s", instance.slug, e, exc_info=True)
            yield {"__error__": True, "message": str(e)}

    async def _wrapped():
        async for chunk in iterate_in_threadpool(_generator()):
            if isinstance(chunk, dict):
                if chunk.get(_DONE_SENTINEL_KEY):
                    # Save history, then emit done event
                    try:
                        entry = ChatHistory(
                            user_id=user_id,
                            instance_id=instance_id,
                            question=question,
                            answer=chunk["answer"],
                            context_docs=chunk["sources"],
                            response_metadata={
                                "retrieval_ms": chunk["retrieval_ms"],
                                "llm_generation_s": chunk["llm_generation_s"],
                            },
                        )
                        db.add(entry)
                        await db.commit()
                        await db.refresh(entry)
                        history_id = entry.id
                    except Exception as e:
                        logger.error("History-Speicherung fehlgeschlagen: %s", e)
                        history_id = None

                    done_payload = {
                        "history_id": history_id,
                        "answer": chunk["answer"],
                        "sources": chunk["sources"],
                        "llm_generation_s": chunk["llm_generation_s"],
                    }
                    yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

                elif chunk.get("__error__"):
                    payload = json.dumps({"message": chunk["message"]})
                    yield f"event: error\ndata: {payload}\n\n"
            else:
                yield chunk

    return StreamingResponse(
        _wrapped(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def get_history(
    request: Request,
    instance_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    user_instances = await get_user_instances(db, user)
    accessible_ids = [e["instance"].id for e in user_instances]
    instance_name_map = {e["instance"].id: e["instance"].name for e in user_instances}

    count_stmt = select(func.count(ChatHistory.id)).where(ChatHistory.user_id == user.id)
    if not user.is_global_admin:
        count_stmt = count_stmt.where(ChatHistory.instance_id.in_(accessible_ids))
    if instance_id:
        count_stmt = count_stmt.where(ChatHistory.instance_id == instance_id)
    if q:
        pattern = _like(q)
        count_stmt = count_stmt.where(or_(
            ChatHistory.question.ilike(pattern, escape="\\"),
            ChatHistory.answer.ilike(pattern, escape="\\"),
        ))
    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(page, total_pages)

    stmt = (
        select(ChatHistory, Instance)
        .join(Instance, ChatHistory.instance_id == Instance.id)
        .where(ChatHistory.user_id == user.id)
    )
    if not user.is_global_admin:
        stmt = stmt.where(ChatHistory.instance_id.in_(accessible_ids))
    if instance_id:
        stmt = stmt.where(ChatHistory.instance_id == instance_id)
    if q:
        pattern = _like(q)
        stmt = stmt.where(or_(
            ChatHistory.question.ilike(pattern, escape="\\"),
            ChatHistory.answer.ilike(pattern, escape="\\"),
        ))
    sort_col = ChatHistory.created_at.asc() if order == "asc" else ChatHistory.created_at.desc()
    stmt = stmt.order_by(sort_col).offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)

    rows = (await db.execute(stmt)).all()
    items = [
        ChatHistoryOut(
            id=row[0].id,
            question=row[0].question,
            answer=row[0].answer,
            context_docs=row[0].context_docs,
            created_at=row[0].created_at,
            instance_id=row[0].instance_id,
            instance_name=row[1].name,
            response_metadata=row[0].response_metadata,
        )
        for row in rows
    ]
    return PaginatedChatHistory(
        items=items, total=total, page=page, total_pages=total_pages,
    ).model_dump(mode="json")


@router.patch("/history/{entry_id}")
async def patch_history(
    entry_id: int,
    body: ChatHistoryPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update timing metadata on a history entry (client-side measurements)."""
    user = request.state.user
    entry = (await db.execute(
        select(ChatHistory).where(
            ChatHistory.id == entry_id,
            ChatHistory.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Verlaufseintrag nicht gefunden")

    meta = entry.response_metadata or {}
    if body.duration_s is not None:
        meta["duration_s"] = body.duration_s
    if body.ttft_s is not None:
        meta["ttft_s"] = body.ttft_s
    entry.response_metadata = meta
    await db.commit()
    return {"ok": True}


@router.delete("/history/{entry_id}", status_code=204)
async def delete_history_entry(
    entry_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    entry = (await db.execute(
        select(ChatHistory).where(
            ChatHistory.id == entry_id,
            ChatHistory.user_id == user.id,
        )
    )).scalar_one_or_none()
    if entry:
        db.delete(entry)
        await db.commit()


@router.delete("/history", status_code=204)
async def clear_history(
    request: Request,
    instance_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    stmt = delete(ChatHistory).where(ChatHistory.user_id == user.id)
    if instance_id:
        stmt = stmt.where(ChatHistory.instance_id == instance_id)
    await db.execute(stmt)
    await db.commit()
