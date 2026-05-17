from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.loader.config import LoaderConfig

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import OpenSearchVectorSearch
from opensearchpy import OpenSearch, RequestsHttpConnection

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


class VectorStore:
    def __init__(self, config: LoaderConfig):
        self.config = config
        self.embedder_type = config.embedder_type
        self.embeddings = self.get_embeddings()
        self._index_mapping = self._get_index_mapping()
        self._raw_client: OpenSearch | None = None
        self._ensure_index()
        self._ensure_search_pipeline()
        self._store: OpenSearchVectorSearch | None = None

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
            index_name = self.config.opensearch_index_name
            if not client.indices.exists(index=index_name):
                logger.info(f'Creating index {index_name} with optimized settings')
                client.indices.create(
                    index=index_name,
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
                index=self.config.opensearch_index_name,
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
            # LangChain's add_texts stores document metadata nested under a 'metadata' key.
            # Fall back to the flat source dict for forward compatibility.
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
                index_name=self.config.opensearch_index_name,
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
