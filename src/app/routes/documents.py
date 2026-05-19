import json
import os
import tempfile
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import Instance
from app.loader.config import LoaderConfig
from app.dependencies import get_config, get_redis, limiter
from app.services.user_service import get_user_instances, get_effective_role
from app.services.document_service import list_documents, delete_document, get_document_processor

from app.utils.templates import templates

router = APIRouter()

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    user = request.state.user
    user_instances = await get_user_instances(db, user)

    instance_id = request.query_params.get("instance_id")
    active = None
    if instance_id:
        active = next((e for e in user_instances if str(e["instance"].id) == instance_id), None)
    if not active and user_instances:
        active = user_instances[0]

    docs = []
    can_manage = False
    if active:
        docs = await list_documents(redis, active["instance"].slug)
        can_manage = active["role"] == "manager" or user.is_global_admin

    return templates.TemplateResponse(request, "documents.html", {
        "user": user,
        "instances": user_instances,
        "active_instance": active,
        "documents": docs,
        "can_manage": can_manage,
    })


@router.post("/documents/upload")
@limiter.limit("10/minute")
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    instance_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    user = request.state.user
    role = await get_effective_role(db, user, instance_id)
    if role != "manager" and not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404)

    # Processor hier anlegen (einmalig pro Request, nicht pro Datei)
    processor = await get_document_processor(config, redis, instance.slug)

    supported_exts = {e.strip().lower() for e in config.supported_extensions}

    async def _stream():
        total = len(files)
        for i, upload in enumerate(files, 1):
            ext = os.path.splitext(upload.filename or "")[1].lower()
            if ext not in supported_exts:
                ext_display = ext or "?"
                yield f"data: {json.dumps({'error': f'Dateiformat nicht unterstützt: {ext_display}', 'file': upload.filename})}\n\n"
                continue

            yield f"data: {json.dumps({'file': upload.filename, 'index': i, 'total': total, 'progress': 0})}\n\n"

            total_bytes = 0
            size_exceeded = False
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    # Datei in 1-MB-Chunks schreiben statt komplett in den RAM laden
                    while chunk := await upload.read(1024 * 1024):
                        total_bytes += len(chunk)
                        if total_bytes > _MAX_UPLOAD_BYTES:
                            size_exceeded = True
                            break
                        tmp.write(chunk)
                    tmp_path = tmp.name
                if size_exceeded:
                    raise ValueError(f'Datei zu groß (max. {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB).')
                async for progress in processor.load_documents(tmp_path, original_filename=upload.filename):
                    payload = {
                        'file': upload.filename,
                        'index': i,
                        'total': total,
                        'progress': round(progress),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc), 'file': upload.filename})}\n\n"
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/documents/delete/{file_hash}")
async def delete_document_route(
    file_hash: str,
    request: Request,
    instance_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    user = request.state.user
    role = await get_effective_role(db, user, instance_id)
    if role != "manager" and not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404)

    await delete_document(config, redis, instance.slug, file_hash)
    return RedirectResponse(url=f"/documents?instance_id={instance_id}", status_code=303)
