import asyncio
from app.loader.config import LoaderConfig
from app.loader.vector_store import VectorStore
from app.loader.document_processor import DocumentProcessor
from app.metadata.redis_service import RedisMetadataService


async def get_document_processor(
    config: LoaderConfig,
    redis_client,
    instance_slug: str,
) -> DocumentProcessor:
    # asyncio.to_thread: VectorStore.for_instance() ruft bei Cache-Miss _ensure_index() auf
    # (synchroner HTTP-Call zu OpenSearch) — darf den Event Loop nicht blockieren.
    store = await asyncio.to_thread(VectorStore.for_instance, config, instance_slug)
    service = RedisMetadataService(redis_client, instance_slug)
    # DocumentProcessor.__init__ lädt den HuggingFace-Tokenizer (synchroner Netzwerkaufruf
    # bei Cache-Miss) — muss im Thread-Pool laufen, darf den Event Loop nicht blockieren.
    return await asyncio.to_thread(DocumentProcessor, config, store, instance_slug, service)


async def list_documents(redis_client, instance_slug: str) -> list[dict]:
    """Lädt alle Dokument-Metadaten für eine Instanz aus Redis (SCAN, keine eigene Verbindung)."""
    service = RedisMetadataService(redis_client, instance_slug)
    return await service.list_all_documents()


async def delete_document(
    config: LoaderConfig,
    redis_client,
    instance_slug: str,
    file_hash: str,
) -> None:
    """Löscht ein Dokument aus OpenSearch (delete_by_query) und aus Redis."""
    store = await asyncio.to_thread(VectorStore.for_instance, config, instance_slug)
    service = RedisMetadataService(redis_client, instance_slug)
    metadata = await service.get_document_metadata(file_hash)

    # metadata ist ein DocumentMetadata-Pydantic-Modell — Attribut-Zugriff, kein dict.get()
    if metadata and metadata.source_path:
        await asyncio.to_thread(
            store._get_raw_client().delete_by_query,
            index=store._index_name,
            body={"query": {"term": {"metadata.source": metadata.source_path}}},
        )

    await service.delete_document_metadata(file_hash)
