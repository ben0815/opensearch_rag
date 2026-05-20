from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.loader.config import LoaderConfig

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import OpenSearchVectorSearch
from opensearchpy import OpenSearch, RequestsHttpConnection

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)

# Module-level cache keyed by instance_slug — allows instance_service.delete_instance()
# to invalidate a specific entry without importing the class itself.
_store_cache: dict[str, "VectorStore"] = {}
_store_cache_lock = threading.Lock()


def invalidate_instance_cache(slug: str) -> None:
    """Remove a single VectorStore from the cache. Call when instance settings change."""
    with _store_cache_lock:
        _store_cache.pop(slug, None)


def clear_vector_store_cache() -> None:
    """Remove all VectorStores from the cache. Call after global search pipeline changes."""
    with _store_cache_lock:
        _store_cache.clear()


class VectorStore:
    def __init__(self, config: LoaderConfig, instance_slug: str = "default"):
        self.config = config
        self._instance_slug = instance_slug
        self._index_name = f"documents_{instance_slug}"
        self.embedder_type = config.embedder_type
        self.embeddings = self.get_embeddings()
        self._index_mapping = self._get_index_mapping()
        self._raw_client: OpenSearch | None = None
        self._ensure_index()
        self._ensure_search_pipeline()
        self._store: OpenSearchVectorSearch | None = None

    @classmethod
    def for_instance(cls, config: "LoaderConfig", instance_slug: str) -> "VectorStore":
        """Factory: gibt gecachten VectorStore für einen Instanz-Slug zurück.
        Bewusst NICHT get_store() — die bestehende Instance-Methode get_store()
        gibt OpenSearchVectorSearch zurück und wird von document_processor.py genutzt.
        Ein Namenskonflikt würde diese leise überschreiben.

        Double-Checked Lock: äußere Prüfung vermeidet Lock-Overhead im Normalfall,
        innere Prüfung schließt die Race Condition zwischen mehreren Threads aus,
        die gleichzeitig einen Cache-Miss sehen."""
        if instance_slug in _store_cache:
            return _store_cache[instance_slug]
        with _store_cache_lock:
            if instance_slug not in _store_cache:
                _store_cache[instance_slug] = cls(config, instance_slug)
            return _store_cache[instance_slug]

    def get_embeddings(self):
        if self.embedder_type == 'bedrock':
            from langchain_aws import BedrockEmbeddings
            return BedrockEmbeddings(
                model_id=self.config.bedrock_model_id,
            )
        elif self.embedder_type == 'ollama':
            try:
                return OllamaEmbeddings(
                    base_url=self.config.ollama_host,
                    model=self.config.embeddings_model,
                )
            except Exception as e:
                raise ValueError(f'Error initializing Ollama embeddings: {e}') from e
        else:
            raise ValueError(f'Unsupported embedder type: {self.embedder_type}')

    def _get_raw_client(self) -> OpenSearch:
        """Return a cached raw OpenSearch client for direct API access."""
        if self._raw_client is None:
            self._raw_client = OpenSearch(
                hosts=[self.config.opensearch_url],
                connection_class=RequestsHttpConnection,
                timeout=300,
            )
        return self._raw_client

    def _ensure_index(self):
        """Ensure the OpenSearch index exists with proper configuration."""
        try:
            client = self._get_raw_client()
            if not client.indices.exists(index=self._index_name):
                logger.info(f'Creating index {self._index_name} with optimized settings')
                client.indices.create(
                    index=self._index_name,
                    body=self._index_mapping,
                )
        except Exception as e:
            logger.error(f'Error ensuring index: {e}')
            raise

    def _ensure_search_pipeline(self) -> None:
        """Create or update the hybrid search pipeline in OpenSearch."""
        pipeline_name = self.config.hybrid_search_pipeline_name
        pipeline_body = {
            'description': 'Hybrid RAG pipeline: min_max normalization, BM25 + kNN',
            'phase_results_processors': [
                {
                    'normalization-processor': {
                        'normalization': {'technique': 'min_max'},
                        'combination': {
                            'technique': 'arithmetic_mean',
                            'parameters': {
                                'weights': [
                                    self.config.hybrid_bm25_weight,
                                    self.config.hybrid_knn_weight,
                                ],
                            },
                        },
                    },
                },
            ],
        }
        try:
            self._get_raw_client().transport.perform_request(
                'PUT',
                f'/_search/pipeline/{pipeline_name}',
                body=pipeline_body,
            )
            logger.info(f'Search pipeline "{pipeline_name}" created/updated')
        except Exception as e:
            logger.error(f'Failed to create search pipeline "{pipeline_name}": {e}')
            raise

    def hybrid_search(self, query: str, k: int | None = None) -> list[tuple[Document, float]]:
        """
        Execute hybrid search combining BM25 (lexical) and kNN (semantic).

        Scores are normalized via the OpenSearch normalization-processor pipeline
        and combined as: score = bm25_weight * bm25_score + knn_weight * knn_score.

        Returns:
            List of (Document, score) tuples, ordered by combined score descending.
        """
        if k is None:
            k = self.config.hybrid_k

        query_embedding = self.embeddings.embed_query(query)

        search_body = {
            '_source': {'excludes': ['vector_field']},
            'size': k,
            'query': {
                'hybrid': {
                    'queries': [
                        {'match': {'text': {'query': query}}},
                        {'knn': {'vector_field': {'vector': query_embedding, 'k': k}}},
                    ],
                },
            },
        }

        try:
            response = self._get_raw_client().search(
                body=search_body,
                index=self._index_name,
                params={'search_pipeline': self.config.hybrid_search_pipeline_name},
            )
        except Exception as e:
            logger.error(f'Hybrid search failed: {e}')
            raise

        results: list[tuple[Document, float]] = []
        for hit in response['hits']['hits']:
            source = hit['_source']
            score = round(float(hit['_score']), 4)
            content = source.get('text', '')
            nested = source.get('metadata')
            metadata = dict(nested) if isinstance(nested, dict) else {k: v for k, v in source.items() if k != 'text'}
            metadata['score'] = score
            results.append((Document(page_content=content, metadata=metadata), score))

        return results

    def _get_index_mapping(self):
        """Get optimized index mapping for better search results."""
        embedding_dimension = self.config.embedding_size

        return {
            'settings': {
                'index': {
                    'knn': True,
                    'number_of_shards': 1,
                    'number_of_replicas': 0,
                    'refresh_interval': '1s',
                    'analysis': {
                        'analyzer': {
                            'default': {
                                'type': self.config.opensearch_analyzer,
                            },
                        },
                    },
                },
            },
            'mappings': {
                'properties': {
                    'vector_field': {
                        'type': 'knn_vector',
                        'dimension': embedding_dimension,
                        'method': {
                            'name': 'hnsw',
                            'engine': 'lucene',
                            'space_type': 'l2',
                            'parameters': {
                                'ef_construction': 512,
                                'm': 48,
                            },
                        },
                    },
                    'text': {
                        'type': 'text',
                        'term_vector': 'with_positions_offsets',
                        'fields': {
                            'keyword': {
                                'type': 'keyword',
                                'ignore_above': 256,
                            },
                        },
                    },
                    'metadata': {
                        'type': 'object',
                        'properties': {
                            'source': {'type': 'keyword'},
                            'filename': {'type': 'keyword'},
                            'file_hash': {'type': 'keyword'},
                            'page': {'type': 'integer'},
                            'chunk_index': {'type': 'integer'},
                            'total_chunks': {'type': 'integer'},
                            'chunk_size': {'type': 'integer'},
                            'chunk_overlap': {'type': 'integer'},
                            'total_pages': {'type': 'integer'},
                            'processing_timestamp': {'type': 'date'},
                        },
                    },
                },
            },
        }

    def get_store(self) -> OpenSearchVectorSearch:
        """Get configured vector store (cached singleton)."""
        if self._store is None:
            self._store = OpenSearchVectorSearch(
                embedding_function=self.embeddings,
                opensearch_url=self.config.opensearch_url,
                index_name=self._index_name,
                engine='lucene',
                timeout=300,
                connection_class=RequestsHttpConnection,
                is_aoss=False,
                vector_field='vector_field',
                text_field='text',
                method='hnsw',
                space_type='l2',
                index_mapping=self._index_mapping,
            )
        return self._store
