"""Document processing functionality."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import fitz

from app.loader.chunk_splitter import ChunkSplitter, _load_tokenizer, _truncate_to_tokens
from app.loader.config import LoaderConfig
from app.metadata.redis_service import DocumentMetadata, RedisMetadataService
from app.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from langchain_core.documents import Document
    from app.loader.vector_store import VectorStore

logger = setup_logger(__name__)


class DocumentProcessor:
    """Process and store documents."""

    def __init__(
        self,
        config: LoaderConfig | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.config = config or LoaderConfig()
        if vector_store is None:
            raise ValueError('vector_store is required for DocumentProcessor')
        self.vector_store = vector_store
        self.metadata_service = RedisMetadataService(
            host=self.config.redis_host,
            port=self.config.redis_port,
        )
        self._tokenizer = _load_tokenizer(self.config.tokenizer_model_id)
        self._chunk_splitter = ChunkSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            embedding_max_tokens=self.config.embedding_max_tokens,
            tokenizer_model_id=self.config.tokenizer_model_id,
        )

    async def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file."""
        def _hash():
            sha256_hash = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for byte_block in iter(lambda: f.read(4096), b''):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()

        return await asyncio.to_thread(_hash)

    async def process_chunk(self, chunk: Document) -> None:
        """Embed and store a single document chunk.

        Content is truncated to embedding_max_tokens before the first attempt.
        Retries with half the token count on context-length errors — a safety
        net for tokenizer edge cases (e.g. very long numeric or special-char sequences).
        """
        store = self.vector_store.get_store()
        content = _truncate_to_tokens(chunk.page_content, self.config.embedding_max_tokens, self._tokenizer)

        while content:
            try:
                return await asyncio.to_thread(
                    store.add_texts,
                    texts=[content],
                    metadatas=[chunk.metadata],
                )
            except Exception as e:
                msg = str(e).lower()
                if 'input length' in msg or 'context length' in msg:
                    ids = self._tokenizer.encode(content, add_special_tokens=False)
                    reduced_token_count = len(ids) // 2
                    if reduced_token_count < 10:
                        logger.error('Chunk too dense to embed even at minimal token count, skipping')
                        return
                    content = self._tokenizer.decode(
                        ids[:reduced_token_count],
                        skip_special_tokens=True,
                        clean_up_tokenization_spaces=True,
                    )
                    logger.warning(
                        f'Embedding context exceeded, retrying with {reduced_token_count} tokens'
                    )
                else:
                    raise

    async def _embed_chunks(self, chunks: list[Document], page_metadata: dict):
        """Embed and store pre-split chunks. Yields progress percentage (0–100)."""
        total = len(chunks)
        if total == 0:
            return

        tasks: list = []
        processed = 0
        batch_size = 3

        for chunk in chunks:
            tasks.append(asyncio.create_task(self.process_chunk(chunk)))
            processed += 1

            if len(tasks) >= batch_size:
                await asyncio.gather(*tasks)
                tasks = []

            progress = (processed / total) * 100
            if processed % 10 == 0 or processed == total:
                logger.info(
                    f'Page {page_metadata["page"]}: {processed}/{total} chunks ({progress:.0f}%)'
                )
            yield progress

        if tasks:
            await asyncio.gather(*tasks)

    async def load_documents(self, file_path: Path | str):
        """
        Load a document and store it in the vector database.

        Yields:
            Progress percentage (float 0–100)
        """
        try:
            file_path = Path(file_path)
            file_size = os.path.getsize(file_path)
            file_hash = await self._calculate_file_hash(file_path)

            existing = await self.metadata_service.get_document_metadata(file_hash)
            if existing:
                logger.info(f'Skipping already-indexed document: {file_path.name}')
                yield 100.0
                return

            chunk_count = 0
            with fitz.open(str(file_path)) as doc:
                total_pages = len(doc)
                if total_pages == 0:
                    raise ValueError('Document contains no pages')

                for i, page in enumerate(doc):
                    metadata = {
                        'source': str(file_path),
                        'page': i + 1,
                        'total_pages': total_pages,
                    }

                    chunks = self._chunk_splitter.split_into_chunks(page.get_text(), metadata)
                    enhanced = self._chunk_splitter.add_neighbouring_content(chunks)
                    non_empty = [c for c in enhanced if c.page_content]
                    chunk_count += len(non_empty)

                    page_progress = 0.0
                    async for progress in self._embed_chunks(non_empty, metadata):
                        page_progress = progress
                        yield ((i * 100) + page_progress) / total_pages

                    if page_progress < 100:
                        yield ((i + 1) * 100) / total_pages

            await self.metadata_service.save_document_metadata(
                file_hash,
                DocumentMetadata(
                    title=file_path.name,
                    file_size=file_size,
                    page_count=total_pages,
                    chunk_count=chunk_count,
                    source_path=str(file_path),
                    indexed_date=datetime.now().isoformat(),
                    file_hash=file_hash,
                    additional_metadata={'processor_version': '1.0'},
                ),
            )

        except Exception as e:
            logger.error(f'Error processing document {file_path}: {e}', exc_info=True)
            raise ValueError(f'Error processing document: {str(e)}') from e

    async def get_indexed_documents(self):
        """Get list of indexed documents from metadata service."""
        try:
            documents = await self.metadata_service.get_all_documents()
            return [{'title': doc.title, 'id': doc.file_hash} for doc in documents]
        except Exception as e:
            logger.error(f'Error fetching indexed documents: {e}')
            return []

    async def get_document_metadata(self, doc_id: str) -> dict | None:
        """Get document metadata by ID."""
        try:
            metadata = await self.metadata_service.get_document_metadata(doc_id)
            return metadata.model_dump() if metadata else None
        except Exception as e:
            logger.error(f'Error fetching document metadata: {e}')
            return None
