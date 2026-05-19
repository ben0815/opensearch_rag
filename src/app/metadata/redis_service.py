"""Redis service for document metadata storage."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


class DocumentMetadata(BaseModel):
    """Document metadata model."""

    title: str
    file_size: int
    page_count: int
    chunk_count: int
    source_path: str
    indexed_date: str
    file_hash: str
    additional_metadata: dict[str, Any] = {}


class RedisMetadataService:
    """Redis service for document metadata management.

    Key schema: doc:<instance_slug>:<sha256>
    No separate index set — SCAN doc:<slug>:* is used for listing.
    """

    def __init__(self, redis_client, instance_slug: str) -> None:
        self._redis = redis_client      # Injected — keine eigene Verbindung verwalten
        self._slug = instance_slug

    @classmethod
    def from_config(cls, config, instance_slug: str) -> "RedisMetadataService":
        """Für CLI-Nutzung: erstellt eigene Redis-Verbindung aus Config."""
        import redis.asyncio as aioredis
        kwargs = dict(host=config.redis_host, port=config.redis_port, decode_responses=True)
        if config.redis_password:
            kwargs["password"] = config.redis_password
        return cls(aioredis.Redis(**kwargs), instance_slug)

    def _key(self, file_hash: str) -> str:
        return f"doc:{self._slug}:{file_hash}"

    async def save_document_metadata(self, doc_id: str, metadata: DocumentMetadata) -> bool:
        try:
            await self._redis.set(self._key(doc_id), metadata.model_dump_json())
            logger.info(f'Saved metadata for document {doc_id} (instance={self._slug})')
            return True
        except Exception as e:
            logger.error(f'Error saving document metadata: {e}')
            return False

    async def get_document_metadata(self, doc_id: str) -> DocumentMetadata | None:
        try:
            data = await self._redis.get(self._key(doc_id))
            if data:
                return DocumentMetadata.model_validate_json(data)
            return None
        except Exception as e:
            logger.error(f'Error retrieving document metadata: {e}')
            return None

    async def get_all_documents(self) -> list[DocumentMetadata]:
        """Gibt alle Dokument-Metadaten als Pydantic-Modelle zurück (für DocumentProcessor).
        Verwendet SCAN statt KEYS — blockiert Redis nicht bei vielen Keys."""
        pattern = f"doc:{self._slug}:*"
        docs = []
        cursor = 0
        try:
            while True:
                cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    values = await self._redis.mget(*keys)
                    for v in values:
                        if v is not None:
                            docs.append(DocumentMetadata.model_validate_json(v))
                if cursor == 0:
                    break
        except Exception as e:
            logger.error(f'Error retrieving all documents: {e}')
        return docs

    async def list_all_documents(self) -> list[dict]:
        """Gibt alle Dokument-Metadaten als Dicts zurück (für die Web-UI)."""
        return [doc.model_dump() for doc in await self.get_all_documents()]

    async def delete_all_documents(self) -> int:
        """Löscht alle Redis-Keys für diese Instanz. Gibt Anzahl gelöschter Keys zurück."""
        pattern = f"doc:{self._slug}:*"
        deleted = 0
        cursor = 0
        try:
            while True:
                cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.error(f'Error deleting all documents for instance {self._slug}: {e}')
        return deleted

    async def delete_document_metadata(self, doc_id: str) -> bool:
        try:
            await self._redis.delete(self._key(doc_id))
            logger.info(f'Deleted metadata for document {doc_id} (instance={self._slug})')
            return True
        except Exception as e:
            logger.error(f'Error deleting document metadata: {e}')
            return False
