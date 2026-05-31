"""Configuration for document loading and processing."""

from __future__ import annotations

import os
from pathlib import Path


class LoaderConfig:
    """Configuration for document loading."""

    def __init__(self):
        """Initialize configuration from environment variables."""
        # Ollama settings
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        self.embeddings_model = os.getenv('EMBEDDINGS_MODEL', 'bge-m3')
        self.llm_model = os.getenv('LLM_MODEL', 'qwen3.5:35b')

        # General settings
        # CHUNK_SIZE and CHUNK_OVERLAP are now in tokens (not chars) — HuggingFace tokenizer is used
        self.chunk_size = int(os.getenv('CHUNK_SIZE', '400'))
        self.chunk_overlap = int(os.getenv('CHUNK_OVERLAP', '60'))
        self.supported_extensions = os.getenv(
            'SUPPORTED_EXTENSIONS',
            '.txt,.md,.pdf,.docx,.xlsx,.csv',
        ).split(',')
        self.max_csv_rows = int(os.getenv('MAX_CSV_ROWS', '10000'))
        self.max_xlsx_rows = int(os.getenv('MAX_XLSX_ROWS', '10000'))
        _xlsx_cap = os.getenv('XLSX_MAX_ROWS_PER_BLOCK')
        self.xlsx_max_rows_per_block: int | None = int(_xlsx_cap) if _xlsx_cap else None
        _csv_cap = os.getenv('CSV_MAX_ROWS_PER_BLOCK')
        self.csv_max_rows_per_block: int | None = int(_csv_cap) if _csv_cap else None
        # Chunks unter diesem Token-Schwellwert werden verworfen (Seiten-/Kapitelzahlen, leere Zeilen etc.)
        self.min_chunk_size = int(os.getenv('MIN_CHUNK_SIZE', '30'))
        # bge-m3 produces 1024-dimensional vectors (up to 8192 token input)
        self.embedding_size = int(os.getenv('EMBEDDING_SIZE', '1024'))
        # Max tokens per chunk before embedding; 600 leaves room for ~100 token neighbor context on each side
        self.embedding_max_tokens = int(os.getenv('EMBEDDING_MAX_TOKENS', '600'))
        # HuggingFace tokenizer ID — must match the embedding model's tokenizer
        self.tokenizer_model_id = os.getenv('TOKENIZER_MODEL_ID', 'BAAI/bge-m3')
        # OpenSearch analyzer for BM25 text field ('german', 'standard', 'english')
        self.opensearch_analyzer = os.getenv('OPENSEARCH_ANALYZER', 'german')
        self.opensearch_url = os.getenv('OPENSEARCH_URL', 'http://localhost:9200')
        self.opensearch_username = os.getenv('OPENSEARCH_USERNAME', 'admin')
        self.opensearch_password = os.getenv('OPENSEARCH_PASSWORD', 'admin')
        self.opensearch_index_name = os.getenv('OPENSEARCH_INDEX_NAME', 'documents')
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', '6379'))
        self.redis_password = os.getenv('REDIS_PASSWORD', '') or None

        # Hybrid search settings
        self.hybrid_search_pipeline_name = os.getenv('HYBRID_SEARCH_PIPELINE_NAME', 'hybrid-rag-pipeline')
        self.hybrid_bm25_weight = float(os.getenv('HYBRID_BM25_WEIGHT', '0.4'))
        self.hybrid_knn_weight = float(os.getenv('HYBRID_KNN_WEIGHT', '0.6'))
        self.hybrid_k = int(os.getenv('HYBRID_K', '10'))
        # Minimum combined score for a retrieved chunk to be included in context (0.0 = disabled)
        self.hybrid_score_threshold = float(os.getenv('HYBRID_SCORE_THRESHOLD', '0.1'))
        # LLM parameters passed to Ollama
        self.llm_num_ctx = int(os.getenv('LLM_NUM_CTX', '16384'))
        self.llm_temperature = float(os.getenv('LLM_TEMPERATURE', '0.0'))
        self.llm_timeout_seconds = int(os.getenv('LLM_TIMEOUT_SECONDS', '240'))
        # Custom system prompt — empty string = use built-in default in rag.py
        self.llm_system_prompt: str = ""
