import json
import logging
from fastapi import APIRouter, Request, Query, Form, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from starlette.concurrency import iterate_in_threadpool
from app.db.session import get_db
from app.db.models import ChatHistory, Instance
from app.loader.config import LoaderConfig
from app.dependencies import get_config, limiter
from app.services.user_service import get_user_instances, get_effective_role
from app.services.chat_service import stream_answer, save_to_history
from app.services.config_service import get_effective_config

from app.utils.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()

_PAGE_SIZE_HISTORY = 50


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    instance_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    user = request.state.user
    user_instances = await get_user_instances(db, user)

    if not user_instances:
        if user.is_global_admin:
            error_msg = (
                "Es sind noch keine Instanzen vorhanden. "
                "Als Administrator können Sie unter "
                "<a href='/admin/instances'>Verwaltung → Instanzen</a> "
                "eine neue Instanz anlegen."
            )
        else:
            error_msg = "Sie haben keinen Zugriff auf eine Instanz. Bitte wenden Sie sich an einen Administrator."
        return templates.TemplateResponse(request, "chat.html", {
            "user": user,
            "instances": [],
            "active_instance": None,
            "error": error_msg,
            "stream_timeout_ms": (config.llm_timeout_seconds + 30) * 1000,
        })

    active = None
    if instance_id:
        active = next((e for e in user_instances if e["instance"].id == instance_id), None)
    if not active:
        active = user_instances[0]

    return templates.TemplateResponse(request, "chat.html", {
        "user": user,
        "instances": user_instances,
        "active_instance": active,
        "error": None,
        "stream_timeout_ms": (config.llm_timeout_seconds + 30) * 1000,
    })


@router.post("/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(
    request: Request,
    question: str = Form(...),
    instance_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    user = request.state.user

    # Berechtigungs-Check
    if not user.is_global_admin:
        role = await get_effective_role(db, user, instance_id)
        if role is None:
            return StreamingResponse(
                iter([f'data: {json.dumps("Kein Zugriff auf diese Instanz.")}\n\n']),
                media_type="text/event-stream",
            )

    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        return StreamingResponse(
            iter([f'data: {json.dumps("Instanz nicht gefunden.")}\n\n']),
            media_type="text/event-stream",
        )

    history_stmt = (
        select(ChatHistory)
        .where(ChatHistory.user_id == user.id, ChatHistory.instance_id == instance_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(3)
    )
    history_result = await db.execute(history_stmt)
    recent_history = list(reversed(history_result.scalars().all()))

    effective_config = get_effective_config(config, instance.settings)

    def _generator():
        try:
            yield from stream_answer(question, instance.slug, effective_config, recent_history)
        except Exception as e:
            logger.error("Stream-Fehler für Instanz %s: %s", instance.slug, e, exc_info=True)
            payload = json.dumps({"message": "Interner Fehler beim Generieren der Antwort."})
            yield f"event: error\ndata: {payload}\n\n"

    # iterate_in_threadpool: läuft jeden next()-Aufruf im Thread-Pool.
    # Ohne das blockiert der sync-Generator (OpenSearch + Ollama) den Event Loop —
    # kein anderer Request kann bearbeitet werden, solange das LLM generiert.
    return StreamingResponse(
        iterate_in_threadpool(_generator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/save-history")
async def save_history_route(
    request: Request,
    question: str = Form(...),
    answer: str = Form(...),
    instance_id: int = Form(...),
    context_docs: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    if not user.is_global_admin:
        role = await get_effective_role(db, user, instance_id)
        if role is None:
            return {"status": "ok"}  # Silent reject — kein Hinweis auf Instanz-Existenz
    try:
        docs = json.loads(context_docs)
    except (json.JSONDecodeError, ValueError):
        docs = []
    await save_to_history(db, user.id, instance_id, question, answer, docs)
    return {"status": "ok"}


@router.get("/chat/history", response_class=HTMLResponse)
async def chat_history(
    request: Request,
    instance_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    user_instances = await get_user_instances(db, user)

    # Nur Instanzen anzeigen, auf die der Nutzer aktuell Zugriff hat —
    # verhindert, dass Dokument-Auszüge nach Zugriffsentzug noch sichtbar sind.
    accessible_ids = [e["instance"].id for e in user_instances]

    count_stmt = select(func.count(ChatHistory.id)).where(ChatHistory.user_id == user.id)
    if not user.is_global_admin:
        count_stmt = count_stmt.where(ChatHistory.instance_id.in_(accessible_ids))
    if instance_id:
        count_stmt = count_stmt.where(ChatHistory.instance_id == instance_id)
    if q:
        count_stmt = count_stmt.where(ChatHistory.question.ilike(f"%{q}%"))
    total: int = (await db.execute(count_stmt)).scalar_one()
    total_pages = max(1, (total + _PAGE_SIZE_HISTORY - 1) // _PAGE_SIZE_HISTORY)

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
        stmt = stmt.where(ChatHistory.question.ilike(f"%{q}%"))
    stmt = stmt.order_by(ChatHistory.created_at.desc()).offset((page - 1) * _PAGE_SIZE_HISTORY).limit(_PAGE_SIZE_HISTORY)

    result = await db.execute(stmt)
    history = [{"entry": row[0], "instance": row[1]} for row in result]

    extra_params: dict = {}
    if instance_id:
        extra_params["instance_id"] = instance_id
    if q:
        extra_params["q"] = q

    return templates.TemplateResponse(request, "chat_history.html", {
        "user": user,
        "history": history,
        "instances": user_instances,
        "active_instance_id": instance_id,
        "q": q or "",
        "page": page,
        "total_pages": total_pages,
        "extra_params": extra_params,
    })


@router.post("/chat/history/clear")
async def delete_all_history(
    request: Request,
    instance_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    stmt = delete(ChatHistory).where(ChatHistory.user_id == user.id)
    if instance_id:
        stmt = stmt.where(ChatHistory.instance_id == instance_id)
    await db.execute(stmt)
    await db.commit()
    return RedirectResponse(url="/chat/history", status_code=303)


@router.post("/chat/history/{entry_id}/delete")
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
    return RedirectResponse(url="/chat/history", status_code=303)
