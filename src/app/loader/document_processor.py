"""Document processing functionality."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document

    from app.loader.vector_store import VectorStore

import asyncio
import traceback
from datetime import datetime
from pathlib import Path

import fitz

from app.loader.chunk_splitter import ChunkSplitter
from app.loader.config import LoaderConfig
from app.metadata.redis_service import DocumentMetadata, RedisMetadataService
from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


class DocumentProcessor:
    """Process and store documents."""

    def __init__(
        self,
        config: LoaderConfig | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        """
        Initialize document processor.

        Args:
            config: Optional loader configuration
            vector_store: VectorStore instance (required for ingestion)
        """
        self.config = config or LoaderConfig()
        if vector_store is None:
            raise ValueError('vector_store is required for DocumentProcessor')
        self.vector_store = vector_store
        self.metadata_service = RedisMetadataService(
            host=self.config.redis_host,
            port=self.config.redis_port,
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

    async def process_chunk(
        self,
        chunk: Document,
    ) -> None:
        """Embed and store a single document chunk."""
        # Hard truncation: mxbai-embed-large has 512 token context.
        # 450 chars ≈ 300 tokens worst-case (German/dense text), safe for all languages.
        content = chunk.page_content[:450]
        store = self.vector_store.get_store()
        return await asyncio.to_thread(
            store.add_texts,
            texts=[content],
            metadatas=[chunk.metadata],
        )

    async def process_page_parallel(
        self,
        text: str,
        metadata: dict,
    ):
        """
        Process document text in parallel with chunking and embedding.

        Args:
            text: Document text to process
            metadata: Document metadata

        Yields:
            Progress percentage
        """
        chunk_splitter = ChunkSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        chunks = chunk_splitter.split_into_chunks(text, metadata)
        enhanced_chunks = chunk_splitter.add_neighbouring_content(chunks)

        total_chunks = len(enhanced_chunks)
        tasks = []
        processed = 0
        batch_size = 3  # Reduced batch size for better reliability

        # Process enhanced chunks in parallel with controlled batching
        for _, chunk in enumerate(enhanced_chunks):
            # Skip empty chunks
            if not chunk.page_content:
                continue

            task = asyncio.create_task(
                self.process_chunk(chunk),
            )
            tasks.append(task)
            processed += 1

            # Process in smaller batches
            if len(tasks) >= batch_size:
                await asyncio.gather(*tasks)
                tasks = []

            progress = (processed / total_chunks) * 100
            if processed % 10 == 0 or processed == total_chunks:
                logger.info(f'Page {metadata["page"]}: {processed}/{total_chunks} chunks ({progress:.0f}%)')
            yield progress

        # Process any remaining tasks
        if tasks:
            await asyncio.gather(*tasks)

        # Ensure we yield 100% at completion
        if processed > 0:
            yield 100.0

    async def load_documents(self, file_path: Path | str):
        """
        Load documents and store in vector database.

        Args:
            file_path: Path to document file

        Yields:
            Progress percentage (float between 0 and 100)
        """
        try:
            file_path = Path(file_path)
            # Get total pages and file info
            total_pages = 0
            chunk_count = 0
            file_size = os.path.getsize(file_path)
            file_hash = await self._calculate_file_hash(file_path)

            # Skip if already indexed
            existing = await self.metadata_service.get_document_metadata(file_hash)
            if existing:
                logger.info(f'Skipping already-indexed document: {file_path.name}')
                yield 100.0
                return

            with fitz.open(str(file_path)) as doc:
                total_pages = len(doc)
                if total_pages == 0:
                    raise ValueError('Document contains no pages')

                for i, page in enumerate(doc):
                    text = page.get_text()
                    metadata = {
                        'source': str(file_path),
                        'page': i + 1,
                        'total_pages': total_pages,
                    }

                    # Process page in parallel
                    page_progress = 0
                    async for progress in self.process_page_parallel(
                        text=text,
                        metadata=metadata,
                    ):
                        # Calculate overall progress including page progress
                        page_progress = progress
                        overall_progress = ((i * 100) + page_progress) / total_pages
                        chunk_count += 1
                        yield overall_progress

                    # Ensure we yield 100% for each page
                    if page_progress < 100:
                        overall_progress = ((i + 1) * 100) / total_pages
                        yield overall_progress

            # Save document metadata
            doc_metadata = DocumentMetadata(
                title=Path(file_path).name,
                file_size=file_size,
                page_count=total_pages,
                chunk_count=chunk_count,
                source_path=str(file_path),
                indexed_date=datetime.now().isoformat(),
                file_hash=file_hash,
                additional_metadata={'processor_version': '1.0'},
            )

            await self.metadata_service.save_document_metadata(file_hash, doc_metadata)

        except Exception as e:
            traceback.print_exc()
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
        """
        Get document metadata by ID.

        Args:
            doc_id: Document identifier

        Returns:
            Document metadata if found
        """
        try:
            metadata = await self.metadata_service.get_document_metadata(doc_id)
            if metadata:
                return metadata.model_dump()
            return None
        except Exception as e:
            logger.error(f'Error fetching document metadata: {e}')
            return None
