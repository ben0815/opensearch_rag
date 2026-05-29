"""Admin-Endpunkte: Instanzverwaltung."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, GroupInstanceRole, Instance, InstanceMember
from app.db.session import get_db
from app.dependencies import get_config, get_redis
from app.loader.config import LoaderConfig
from app.schemas import (
    AddInstanceMemberRequest,
    GroupInstanceRoleOut,
    InstanceAdminOut,
    InstanceCreateRequest,
    InstanceMemberOut,
    InstancePatchRequest,
)
from app.services.instance_service import create_instance, delete_instance
from app.routes.admin._shared import _audit, _now, _require_admin

router = APIRouter()


async def _build_instance_admin_out(db: AsyncSession, instance: Instance, redis=None) -> InstanceAdminOut:
    member_count = (await db.execute(
        select(func.count()).select_from(InstanceMember).where(InstanceMember.instance_id == instance.id)
    )).scalar_one()
    group_count = (await db.execute(
        select(func.count()).select_from(GroupInstanceRole).where(GroupInstanceRole.instance_id == instance.id)
    )).scalar_one()
    doc_count = 0
    if redis is not None:
        from app.services.document_service import list_documents
        docs = await list_documents(redis, instance.slug)
        doc_count = len(docs)
    return InstanceAdminOut(
        id=instance.id, name=instance.name, slug=instance.slug,
        description=instance.description, settings=instance.settings,
        created_at=instance.created_at, updated_at=instance.updated_at,
        member_count=member_count, group_count=group_count, doc_count=doc_count,
    )


@router.get("")
async def list_admin_instances(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    instances = (await db.execute(select(Instance))).scalars().all()
    return [
        (await _build_instance_admin_out(db, inst, redis)).model_dump(mode="json")
        for inst in instances
    ]


@router.post("", status_code=201)
async def create_admin_instance(
    body: InstanceCreateRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
):
    instance = await create_instance(db, config, body.name, body.description, analyzer=body.analyzer)
    _audit(db, admin.id, "instance_create", "instance", instance.id, {"name": instance.name, "slug": instance.slug})
    await db.commit()
    return (await _build_instance_admin_out(db, instance)).model_dump(mode="json")


@router.get("/{instance_id}")
async def get_admin_instance(
    instance_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")
    return (await _build_instance_admin_out(db, instance, redis)).model_dump(mode="json")


@router.patch("/{instance_id}")
async def patch_admin_instance(
    instance_id: int,
    body: InstancePatchRequest,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    if body.name is not None:
        instance.name = body.name.strip()
    if body.description is not None:
        instance.description = body.description.strip()
    _SYSTEM_KEYS = {"opensearch_analyzer"}
    _VISUAL_KEYS = ("icon", "color")
    existing = instance.settings or {}
    preserved_system = {k: v for k, v in existing.items() if k in _SYSTEM_KEYS}
    preserved_visual = {k: v for k, v in existing.items() if k in _VISUAL_KEYS}

    if body.clear_settings:
        instance.settings = {**preserved_system, **preserved_visual} or None
    elif body.settings is not None:
        _castmap = {
            "llm_model": str, "llm_temperature": float,
            "llm_num_ctx": int, "hybrid_k": int, "hybrid_score_threshold": float,
        }
        overrides = {**preserved_system, **preserved_visual}
        for k in _VISUAL_KEYS:
            raw = body.settings.get(k)
            if raw is not None:
                if raw == "":
                    overrides.pop(k, None)
                else:
                    overrides[k] = str(raw)
        for key, cast in _castmap.items():
            raw = body.settings.get(key)
            if raw is not None and raw != "":
                try:
                    overrides[key] = cast(str(raw).replace(",", "."))
                except (ValueError, TypeError):
                    pass

        # BM25-Gewicht: kNN-Gewicht wird automatisch als Komplement berechnet
        raw_bm25 = body.settings.get("hybrid_bm25_weight")
        if raw_bm25 is not None:
            if raw_bm25 == "":
                overrides.pop("hybrid_bm25_weight", None)
                overrides.pop("hybrid_knn_weight", None)
            else:
                try:
                    bm25 = float(str(raw_bm25).replace(",", "."))
                    if 0.0 <= bm25 <= 1.0:
                        overrides["hybrid_bm25_weight"] = bm25
                        overrides["hybrid_knn_weight"] = round(1.0 - bm25, 6)
                except (ValueError, TypeError):
                    pass

        raw_prompt = body.settings.get("llm_system_prompt")
        if raw_prompt is not None:
            prompt_str = str(raw_prompt).strip()
            if not prompt_str:
                overrides.pop("llm_system_prompt", None)
            else:
                from app.rag import validate_system_prompt
                missing = validate_system_prompt(prompt_str)
                if missing:
                    raise HTTPException(
                        status_code=422,
                        detail=f"System-Prompt: fehlende Platzhalter {missing}. Erforderlich: {{context}}, {{question}}, {{history}}",
                    )
                overrides["llm_system_prompt"] = prompt_str

        instance.settings = overrides or None

    _audit(db, admin.id, "instance_patch", "instance", instance.id, {"name": instance.name})
    instance.updated_at = _now()
    from app.loader.vector_store import invalidate_instance_cache
    invalidate_instance_cache(instance.slug)
    await db.commit()
    await db.refresh(instance)
    return (await _build_instance_admin_out(db, instance)).model_dump(mode="json")


@router.delete("/{instance_id}", status_code=204)
async def delete_admin_instance(
    instance_id: int,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        return
    slug = instance.slug
    await delete_instance(db, config, instance_id, redis)
    _audit(db, admin.id, "instance_delete", "instance", instance_id, {"slug": slug})
    await db.commit()


@router.get("/{instance_id}/members")
async def list_instance_members(
    instance_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.db.models import User as _User
    rows = (await db.execute(
        select(InstanceMember, _User)
        .join(_User, InstanceMember.user_id == _User.id)
        .where(InstanceMember.instance_id == instance_id)
        .order_by(_User.ldap_uid)
    )).all()
    return [
        InstanceMemberOut(
            user_id=user.id, ldap_uid=user.ldap_uid,
            display_name=user.display_name, role=mem.role,
        ).model_dump()
        for mem, user in rows
    ]


@router.post("/{instance_id}/members", status_code=201)
async def add_instance_member(
    instance_id: int,
    body: AddInstanceMemberRequest,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.db.models import User as _User
    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")
    user = (await db.execute(select(_User).where(_User.id == body.user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    existing = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == body.user_id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.role = body.role
    else:
        db.add(InstanceMember(user_id=body.user_id, instance_id=instance_id, role=body.role, added_by=admin.id))
    _audit(db, admin.id, "instance_member_add", "instance", instance_id, {"user_id": body.user_id, "role": body.role})
    await db.commit()
    return {"ok": True}


@router.delete("/{instance_id}/members/{user_id}", status_code=204)
async def remove_instance_member(
    instance_id: int, user_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    mem = (await db.execute(
        select(InstanceMember).where(
            InstanceMember.user_id == user_id,
            InstanceMember.instance_id == instance_id,
        )
    )).scalar_one_or_none()
    if mem:
        db.delete(mem)
        _audit(db, admin.id, "instance_member_remove", "instance", instance_id, {"user_id": user_id})
        await db.commit()


@router.post("/{instance_id}/rebuild-redis")
async def rebuild_redis(
    instance_id: int,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    config: LoaderConfig = Depends(get_config),
    redis=Depends(get_redis),
):
    from datetime import datetime, timezone
    from app.loader.vector_store import VectorStore
    from app.metadata.redis_service import RedisMetadataService, DocumentMetadata

    instance = (await db.execute(select(Instance).where(Instance.id == instance_id))).scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instanz nicht gefunden")

    store = await asyncio.to_thread(VectorStore.for_instance, config, instance.slug)
    client = store._get_raw_client()
    agg_body = {
        "size": 0,
        "aggs": {"by_hash": {
            "terms": {"field": "metadata.file_hash", "size": 10000},
            "aggs": {
                "filename":    {"terms": {"field": "metadata.filename", "size": 1}},
                "max_page":    {"max": {"field": "metadata.page"}},
                "chunk_count": {"value_count": {"field": "metadata.chunk_index"}},
            },
        }},
    }
    resp = await asyncio.to_thread(client.search, index=store._index_name, body=agg_body)
    buckets = resp.get("aggregations", {}).get("by_hash", {}).get("buckets", [])

    service = RedisMetadataService(redis, instance.slug)
    rebuilt = 0
    for bucket in buckets:
        file_hash = bucket["key"]
        filename_buckets = bucket.get("filename", {}).get("buckets", [])
        filename = filename_buckets[0]["key"] if filename_buckets else file_hash
        page_count = int(bucket.get("max_page", {}).get("value") or 1)
        chunk_count = int(bucket.get("chunk_count", {}).get("value") or 0)
        if not await service.get_document_metadata(file_hash):
            await service.save_document_metadata(
                file_hash,
                DocumentMetadata(
                    title=filename, file_size=0, page_count=page_count,
                    chunk_count=chunk_count, source_path="",
                    indexed_date=datetime.now(timezone.utc).isoformat(),
                    file_hash=file_hash, additional_metadata={"rebuilt": True},
                ),
            )
            rebuilt += 1
    return {"rebuilt": rebuilt}


