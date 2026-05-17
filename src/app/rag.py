from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generator

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_ollama import OllamaLLM

if TYPE_CHECKING:
    from langchain_aws import BedrockLLM
    from langchain_core.documents import Document
    from app.loader import LoaderConfig, VectorStore

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)

_llm_cache: dict[str, OllamaLLM | Any] = {}

_PROMPT_TEMPLATE = PromptTemplate(
    template="""
        Use the following pieces of context to answer the question.
        If you don't know the answer, just say that you don't know, don't try to make up an answer.
        Try to be as detailed as possible while remaining accurate.
        Always consider the full context including any previous or next sections provided.

        Context: {context}

        Question: {question}

        Answer: Let me help you with that.
    """,
    input_variables=['context', 'question'],
)


def get_llm(config: LoaderConfig) -> BedrockLLM | OllamaLLM:
    """
    Get the LLM based on configuration (cached per model key).

    Returns:
        LLM instance
    """
    llm_type = config.llm_type
    cache_key = f'{llm_type}:{config.llm_model}'

    if cache_key not in _llm_cache:
        if llm_type.lower() == 'bedrock':
            from langchain_aws import BedrockLLM
            _llm_cache[cache_key] = BedrockLLM(
                credentials_profile_name='default',
                region_name=config.region_name,
                endpoint_url=config.endpoint_url,
                model_id=config.model_id,
                model_kwargs={'temperature': 0.7, 'max_tokens_to_sample': 4096},
            )
        elif llm_type.lower() == 'ollama':
            _llm_cache[cache_key] = OllamaLLM(
                base_url=config.ollama_host,
                model=config.llm_model,
                temperature=0.7,
            )
        else:
            raise ValueError(f'Unsupported LLM type: {llm_type}')

    return _llm_cache[cache_key]


def retrieve(
    question: str,
    config: LoaderConfig,
    vector_store: VectorStore,
) -> tuple[list[Document], dict]:
    """
    Perform hybrid search (BM25 + kNN) and return deduplicated docs.

    Returns:
        Tuple of (unique_docs, search_metadata)
    """
    cleaned_question = question.strip()
    results_with_scores = vector_store.hybrid_search(cleaned_question)

    seen: set[str] = set()
    unique_results: list = []
    for doc, _ in results_with_scores:
        if doc.page_content not in seen:
            seen.add(doc.page_content)
            unique_results.append(doc)

    search_metadata = {
        'total_results_found': len(results_with_scores),
        'unique_results_used': len(unique_results),
        'search_strategies_used': ['hybrid_bm25_knn'],
        'top_result_score': unique_results[0].metadata.get('score', 0) if unique_results else 0,
    }
    return unique_results, search_metadata


def generate_stream(
    question: str,
    docs: list[Document],
    config: LoaderConfig,
) -> Generator[str, None, None]:
    """
    Stream LLM tokens for the given question and retrieved context docs.

    Returns:
        Generator yielding token strings
    """
    context = '\n\n'.join([doc.page_content for doc in docs[:5]])
    chain = (
        {
            'context': lambda x: context,
            'question': RunnablePassthrough(),
        }
        | _PROMPT_TEMPLATE
        | get_llm(config)
        | StrOutputParser()
    )
    return chain.stream(question.strip())


def search(question: str, config: LoaderConfig, vector_store: VectorStore):
    """
    Blocking search — retrieves docs and generates a complete answer.

    Returns:
        Tuple of (retrieved_docs, rag_result_dict)
    """
    try:
        unique_results, search_metadata = retrieve(question, config, vector_store)
        rag_result = ''.join(generate_stream(question, unique_results, config))
        return unique_results, {
            'result': rag_result,
            'search_metadata': search_metadata,
        }
    except Exception as e:
        logger.error(f'Error in search: {str(e)}')
        raise
