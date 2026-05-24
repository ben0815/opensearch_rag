"""Main app package initialization."""

from app.loader import DocumentProcessor, LoaderConfig, VectorStore
from app.utils.logging_config import setup_logger

__all__ = [
    'DocumentProcessor',
    'LoaderConfig',
    'VectorStore',
    'setup_logger',
]

__version__ = '0.9.1'
__package_name__ = 'opensearch-rag'
