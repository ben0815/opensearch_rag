import json
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Instance

logger = logging.getLogger(__name__)
from app.db.session import get_db
from app.dependencies import get_config, get_redis, limiter, _get_user_or_ip
from app.loader.config import LoaderConfig
from app.schemas import DocumentOut
from app.services.config_service import get_app_setting
from app.services.document_service import delete_document, get_document_processor, list_documents
from app.services.user_service import get_effective_role

router = APIRouter(prefix="/api/documents")

_DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",  # .docx/.xlsx auf libmagic < 5.39
}


def _sanitize_filename(name: str) -> str:
    """Entfernt pfad-traversal-gefährliche Elemente und HTML-Injection-Zeichen.
    Umlaute und sonstige Unicode-Zeichen bleiben erhalten (kein re.sub mit \\w).
    """
    name = name.replace("\\", "/").split("/")[-1]  # Pfad-Traversal entfernen
    name = name.replace("\x00", "")                # Null-Bytes
    name = name.replace("<", "").replace(">", "").replace("&", "")
    name = name.replace('"', "").replace("'", "")
    return name[:255] or "unnamed"


def _sanitize_text(text: str, max_len: int) -> str:
    """XSS-Bereinigung für nutzergesteuerte Freitextfelder (display_name, description).
    Sanitisierung beim Schreiben — ungefilterte Daten dürfen nicht in Redis landen.
    """
    text = (text or "")[:max_len]
    text = text.replace("<", "").replace(">", "").replace("&", "")
    text = text.replace('"', "").replace("'", "")
    return text


async def _validate_mime(upload: UploadFile) -> None:
    """Prüft Magic Bytes der Datei. Wirft ValueError bei unerlaubtem Typ."""
    try:
        import magic as _magic
        header = await upload.read(512)
        await upload.seek(0)
        detected = _magic.from_buffer(header, mime=True)
        # application/octet-stream ist ein generischer Fallback — libmagic kennt den Typ nicht.
        # In dem Fall greift der bereits erfolgte Extension-Check als alleinige Validierung.
        if detected == "application/octet-stream":
            return
        if detected not in _ALLOWED_MIME_TYPES:
            raise ValueError(f"Ungültiger Dateityp: {detected}")
    except ImportError:
        # python-magic nicht installiert — nur Extension-Check greift
        pass


@router.get("/{instance_id}")
async def get_documents(
    instance_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    user = request.state.user
    if not user.is_global_admin:
        role = await get_effective_role(db, user, instance_id)
        if role is None:
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Instanz")

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    docs = await list_documents(redis, instance.slug)
    return [
        DocumentOut(
            sha256=d.get("file_hash", ""),
            title=d.get("title", ""),
            display_name=d.get("display_name", ""),
            description=d.get("description", ""),
            valid_until=d.get("valid_until"),
            file_size=d.get("file_size", 0),
            page_count=d.get("page_count", 0),
            chunk_count=d.get("chunk_count", 0),
            indexed_date=d.get("indexed_date", ""),
        ).model_dump()
        for d in docs
    ]


@router.post("/{instance_id}/check")
@limiter.limit("10/minute", key_func=_get_user_or_ip)
async def check_document_names(
    instance_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    """Prüft ob Dokumente mit diesen Namen bereits in der Instanz existieren.
    Gibt für jede Übereinstimmung name + hash zurück — Client nutzt hash für Replace-Flow.
    """
    user = request.state.user
    role = await get_effective_role(db, user, instance_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Instanz")
    if role != "manager" and not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    try:
        body = await request.json()
        names = body.get("names", [])
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiges Format — names muss eine Liste von Strings sein")

    if len(names) > 200:
        raise HTTPException(status_code=400, detail="Maximal 200 Namen pro Anfrage")

    all_docs = await list_documents(redis, instance.slug)
    conflicts = []
    for name in names:
        for d in all_docs:
            if d.get("display_name") == name or d.get("title") == name:
                conflicts.append({"name": name, "hash": d.get("file_hash", "")})
                break

    return {"conflicts": conflicts}


@router.post("/{instance_id}/upload")
@limiter.limit("10/minute", key_func=_get_user_or_ip)
async def upload_documents(
    instance_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    metadata: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    user = request.state.user
    role = await get_effective_role(db, user, instance_id)
    if role != "manager" and not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    # Metadaten-JSON vor _stream parsen — HTTP 400 bei ungültigem Format, nicht 500
    try:
        meta_list = json.loads(metadata)
        if not isinstance(meta_list, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Ungültiges metadata-Format")

    # Dynamic upload size limit from app_settings
    limit_str = await get_app_setting(db, "max_upload_mb")
    max_bytes = int(limit_str) * 1024 * 1024 if limit_str else _DEFAULT_MAX_UPLOAD_BYTES

    processor = await get_document_processor(config, redis, instance.slug)
    supported_exts = {e.strip().lower() for e in config.supported_extensions}

    async def _stream():
        total = len(files)
        for i, upload in enumerate(files, 1):
            raw_fname = upload.filename or ""
            fname = _sanitize_filename(raw_fname)
            ext = os.path.splitext(fname)[1].lower()

            if ext not in supported_exts:
                ext_display = ext or "?"
                err_payload = json.dumps({'file': fname, 'index': i, 'total': total, 'status': 'error', 'error': f'Dateiformat nicht unterstützt: {ext_display}'})
                yield f"data: {err_payload}\n\n"
                continue

            # MIME-Typ prüfen (Magic Bytes)
            try:
                await _validate_mime(upload)
            except ValueError as mime_err:
                logger.warning("MIME-Validierung fehlgeschlagen für %s: %s", fname, mime_err)
                err_payload = json.dumps({'file': fname, 'index': i, 'total': total, 'status': 'error', 'error': 'Dateityp nicht erlaubt'})
                yield f"data: {err_payload}\n\n"
                continue

            # Per-Datei-Metadaten aus dem JSON-Array (0-indiziert, i ist 1-indiziert)
            meta = meta_list[i - 1] if i - 1 < len(meta_list) else {}

            dname = _sanitize_text(meta.get("display_name") or "", 255)
            desc = _sanitize_text(meta.get("description") or "", 500)

            sheets_raw = meta.get("sheets")
            sheet_list = [str(s) for s in sheets_raw] if isinstance(sheets_raw, list) else None

            # existing_hash für Replace-Flow: muss gültiger SHA-256-Hex-String sein
            existing_hash = meta.get("existing_hash") or ""
            if existing_hash and not re.match(r'^[a-f0-9]{64}$', existing_hash):
                existing_hash = ""

            # valid_until: ISO-8601 Datum (YYYY-MM-DD) oder None
            valid_until: str | None = None
            valid_until_raw = (meta.get("valid_until") or "").strip()
            if valid_until_raw:
                try:
                    datetime.fromisoformat(valid_until_raw[:10])
                    valid_until = valid_until_raw[:10]
                except ValueError:
                    pass

            yield f"data: {json.dumps({'file': fname, 'index': i, 'total': total, 'progress': 0})}\n\n"

            total_bytes = 0
            size_exceeded = False
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp_path = tmp.name
                    while chunk := await upload.read(1024 * 1024):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            size_exceeded = True
                            break
                        tmp.write(chunk)

                if size_exceeded:
                    raise ValueError(f'Datei zu groß (max. {max_bytes // (1024 * 1024)} MB).')

                async for progress in processor.load_documents(
                    tmp_path,
                    original_filename=fname,
                    description=desc,
                    display_name=dname,
                    sheets=sheet_list,
                    valid_until=valid_until,
                ):
                    if isinstance(progress, dict):
                        if progress.get("already_indexed"):
                            yield f"data: {json.dumps({'file': fname, 'index': i, 'total': total, 'status': 'already_indexed', 'progress': 100})}\n\n"
                        elif progress.get("status") == "ok":
                            # Upload-then-delete: altes Dokument erst nach erfolgreicher Indexierung löschen
                            if existing_hash:
                                try:
                                    await delete_document(config, redis, instance.slug, existing_hash)
                                except Exception as del_exc:
                                    logger.warning("Replace-Delete fehlgeschlagen für %s: %s", existing_hash, del_exc)
                            yield f"data: {json.dumps({'file': fname, 'index': i, 'total': total, 'status': 'ok', 'progress': 100, 'chunk_count': progress['chunk_count'], 'warnings': progress['warnings']})}\n\n"
                    else:
                        payload = {
                            'file': fname,
                            'index': i,
                            'total': total,
                            'progress': round(float(progress)),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                # Audit log
                try:
                    db.add(AuditLog(
                        user_id=user.id,
                        action="doc_upload",
                        target_type="instance",
                        target_id=str(instance_id),
                        detail={"filename": fname, "size_bytes": total_bytes, "display_name": dname},
                    ))
                    await db.commit()
                except Exception:
                    logger.warning("Audit-Log doc_upload fehlgeschlagen", exc_info=True)

            except Exception as exc:
                logger.error("Upload-Fehler für Datei %s: %s", fname, exc, exc_info=True)
                yield f"data: {json.dumps({'file': fname, 'index': i, 'total': total, 'status': 'error', 'error': 'Verarbeitung fehlgeschlagen'})}\n\n"
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{instance_id}/{file_hash}", status_code=204)
async def delete_document_route(
    instance_id: int,
    file_hash: Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")],
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    user = request.state.user
    role = await get_effective_role(db, user, instance_id)
    if role != "manager" and not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    await delete_document(config, redis, instance.slug, file_hash)

    # Audit log
    try:
        db.add(AuditLog(
            user_id=user.id,
            action="doc_delete",
            target_type="instance",
            target_id=str(instance_id),
            detail={"file_hash": file_hash},
        ))
        await db.commit()
    except Exception:
        pass
