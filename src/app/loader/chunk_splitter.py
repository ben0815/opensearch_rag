import re
from datetime import datetime
from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)

_DEFAULT_TOKENIZER_MODEL = 'BAAI/bge-m3'


@lru_cache(maxsize=4)
def _load_tokenizer(model_id: str):
    """Load and cache a HuggingFace tokenizer (one instance per model ID)."""
    from transformers import AutoTokenizer
    logger.info(f'Loading HuggingFace tokenizer: {model_id}')
    return AutoTokenizer.from_pretrained(model_id)


def _truncate_to_tokens(text: str, max_tokens: int, tokenizer) -> str:
    """Truncate text so that its token count does not exceed max_tokens.

    Decodes the sliced token IDs back to text so that word boundaries are
    respected rather than cutting in the middle of a word.
    """
    ids = tokenizer.encode(text, add_special_tokens=False)
    if len(ids) <= max_tokens:
        return text
    return tokenizer.decode(ids[:max_tokens], skip_special_tokens=True, clean_up_tokenization_spaces=True)


class ChunkSplitter:
    """Strategy for splitting a document into processable parts with enhanced context."""

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        embedding_max_tokens: int = 600,
        tokenizer_model_id: str = _DEFAULT_TOKENIZER_MODEL,
        min_chunk_size: int = 30,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_max_tokens = embedding_max_tokens
        self.min_chunk_size = min_chunk_size
        self.tokenizer = _load_tokenizer(tokenizer_model_id)
        self.text_splitter = self.get_splitter()

    def get_splitter(self) -> RecursiveCharacterTextSplitter:
        """
        Get text splitter using the tokenizer's token count as the length function.

        chunk_size and chunk_overlap are now measured in tokens, not characters.
        """
        tokenizer = self.tokenizer
        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=lambda text: len(tokenizer.encode(text, add_special_tokens=False)),
            separators=[
                '\n# ',   # Markdown H1
                '\n## ',  # Markdown H2
                '\n### ', # Markdown H3
                '\n\n',  # Paragraphs
                '\n',  # Lines
                '. ',  # Sentences with space
                '? ',  # Questions with space
                '! ',  # Exclamations with space
                ';',  # Semicolons
                ':',  # Colons
                ',',  # Commas
                ' ',  # Words
                '',  # Characters
            ],
            keep_separator=True,
        )

    def clean_text(self, text: str) -> str:
        """
        Clean and normalize text for better splitting.

        Args:
            text: Raw text to clean

        Returns:
            Cleaned and normalized text
        """
        # Replace multiple newlines and whitespace
        text = re.sub(r'\n{2,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        # Normalize sentence endings
        text = re.sub(r'([.!?])([A-Z])', r'\1 \2', text)

        # Remove excessive whitespace while preserving paragraph breaks
        text = '\n\n'.join(line.strip() for line in text.split('\n\n'))

        return text.strip()

    def split_into_chunks(self, text: str, metadata: dict[str, Any]) -> list[Document]:
        """
        Split text into chunks with enhanced metadata.

        Args:
            text: Text to split
            metadata: Base metadata for chunks

        Returns:
            List of Document objects with enhanced metadata
        """
        # Clean and normalize text
        text = self.clean_text(text)

        # Add processing metadata
        enhanced_metadata = {
            **metadata,
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap,
            'total_length': len(text),
            'processing_timestamp': datetime.now().isoformat(),
        }

        # Create initial chunks
        chunks = self.text_splitter.create_documents(
            texts=[text],
            metadatas=[enhanced_metadata],
        )

        # Kurze Chunks verwerfen (Seitenzahlen, Überschriften ohne Inhalt, leere Zeilen)
        chunks = [
            c for c in chunks
            if len(self.tokenizer.encode(c.page_content, add_special_tokens=False)) >= self.min_chunk_size
        ]

        # Add chunk-specific metadata
        for i, chunk in enumerate(chunks):
            chunk.metadata.update(
                {
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    'chunk_length': len(chunk.page_content),
                    'is_first_chunk': i == 0,
                    'is_last_chunk': i == len(chunks) - 1,
                },
            )

        return chunks

    def add_neighbouring_content(self, chunks: list[Document]) -> list[Document]:
        """
        Enhance chunks with context from neighboring chunks.

        Args:
            chunks: List of document chunks

        Returns:
            List of enhanced Document objects with context
        """
        enhanced_chunks = []

        for i, chunk in enumerate(chunks):
            # Get context chunks
            prev_chunk = chunks[i - 1] if i > 0 else None
            next_chunk = chunks[i + 1] if i < len(chunks) - 1 else None

            # Build enhanced content sections
            content_sections = []

            # Add previous context if available
            if prev_chunk:
                prev_text = self._extract_relevant_context(
                    prev_chunk.page_content,
                    is_previous=True,
                )
                if prev_text:
                    content_sections.append(f'Previous Context: {prev_text}')

            # Add current content
            current_text = chunk.page_content.strip()
            if current_text:
                content_sections.append(f'Current Content: {current_text}')

            # Add next context if available
            if next_chunk:
                next_text = self._extract_relevant_context(
                    next_chunk.page_content,
                    is_previous=False,
                )
                if next_text:
                    content_sections.append(f'Next Context: {next_text}')

            # Create enhanced metadata
            enhanced_metadata = {
                **chunk.metadata,
                'has_previous': bool(prev_chunk),
                'has_next': bool(next_chunk),
                'context_length': len('\n'.join(content_sections)),
            }

            full_content = '\n'.join(content_sections)
            full_content = _truncate_to_tokens(full_content, self.embedding_max_tokens, self.tokenizer)

            # Create enhanced chunk
            enhanced_chunk = Document(
                page_content=full_content,
                metadata=enhanced_metadata,
            )
            enhanced_chunks.append(enhanced_chunk)

        return enhanced_chunks

    def _extract_relevant_context(
        self,
        text: str,
        is_previous: bool,
        max_length: int = 600,
    ) -> str:
        """
        Extract most relevant context from neighboring chunk.

        Args:
            text: Text to extract context from
            is_previous: Whether this is previous context
            max_length: Maximum length of context to extract (chars — a pre-filter
                before the final token-based truncation in add_neighbouring_content)

        Returns:
            Extracted context string
        """
        text = text.strip()
        if not text:
            return ''

        # For previous context, prefer end of text
        if is_previous:
            # Try to find last complete sentence
            sentences = re.split(r'[.!?]+\s+', text)
            if len(sentences) > 1:
                context = sentences[-2:] if len(sentences) > 2 else sentences
                return ' '.join(context)[:max_length].strip()
            return text[-max_length:].strip()

        # For next context, prefer start of text
        else:
            # Try to find first complete sentences
            sentences = re.split(r'[.!?]+\s+', text)
            if len(sentences) > 1:
                context = sentences[:2]
                return ' '.join(context)[:max_length].strip()
            return text[:max_length].strip()
