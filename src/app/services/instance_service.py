import asyncio
import copy
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Instance
from app.loader.config import LoaderConfig
from app.loader.vector_store import VectorStore
from app.utils.logging_config import setup_logger

import re as _re
_ANALYZER_RE = _re.compile(r'^[a-z][a-z0-9_-]{0,63}$')

logger = setup_logger(__name__)


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug[:64].strip("_")


async def create_instance(
    db: AsyncSession,
    config: LoaderConfig,
    name: str,
    description: str = "",
    analyzer: str = "german",
) -> Instance:
    if not analyzer or not _ANALYZER_RE.match(analyzer):
        analyzer = "standard"

    slug = _slugify(name)

    # Slug-Kollision vermeiden
    base_slug = slug
    i = 1
    while (await db.execute(select(Instance).where(Instance.slug == slug))).scalar_one_or_none():
        slug = f"{base_slug}_{i}"
        i += 1

    instance = Instance(name=name, slug=slug, description=description, settings={"opensearch_analyzer": analyzer})
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    # OpenSearch-Index mit instanzspezifischem Analyzer anlegen.
    # Der Analyzer ist im Index-Mapping einmalig festgelegt und kann nachträglich nicht geändert werden.
    instance_config = copy.copy(config)
    instance_config.opensearch_analyzer = analyzer
    await asyncio.to_thread(VectorStore.for_instance, instance_config, slug)

    return instance


async def delete_instance(
    db: AsyncSession,
    config: LoaderConfig,
    instance_id: int,
    redis=None,
) -> None:
    from opensearchpy import OpenSearch, RequestsHttpConnection

    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        return

    # OpenSearch-Index direkt löschen — kein VectorStore erstellen (kein _ensure_index-Overhead)
    index_name = f"documents_{instance.slug}"
    use_ssl = config.opensearch_url.startswith("https://")
    ssl_kwargs: dict = {}
    if use_ssl:
        ssl_kwargs.update(use_ssl=True, verify_certs=False, ssl_show_warn=False)
    if config.opensearch_username and config.opensearch_password:
        ssl_kwargs["http_auth"] = (config.opensearch_username, config.opensearch_password)
    client = OpenSearch(
        hosts=[config.opensearch_url],
        connection_class=RequestsHttpConnection,
        timeout=30,
        **ssl_kwargs,
    )
    try:
        await asyncio.to_thread(client.indices.delete, index=index_name, ignore_unavailable=True)
    except Exception as e:
        logger.warning(f"Index {index_name} konnte nicht gelöscht werden: {e}")

    # VectorStore-Cache für diesen Slug invalidieren
    from app.loader.vector_store import invalidate_instance_cache
    invalidate_instance_cache(instance.slug)

    # Redis-Metadaten für alle Dokumente der Instanz löschen
    if redis is not None:
        from app.metadata.redis_service import RedisMetadataService
        deleted = await RedisMetadataService(redis, instance.slug).delete_all_documents()
        logger.info(f"Deleted {deleted} Redis keys for instance {instance.slug}")

    await db.delete(instance)
    await db.commit()
