from __future__ import annotations

import threading
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
_llm_cache_lock = threading.Lock()

_PROMPT_TEMPLATE = PromptTemplate(
    template="""/no_think Du bist ein präziser Assistent. Beantworte die Frage ausschließlich \
auf Basis der folgenden Kontext-Abschnitte aus den Dokumenten. Antworte ausschließlich auf Deutsch.

Wenn die Antwort nicht im Kontext enthalten ist, antworte exakt:
"Die gesuchte Information wurde in den verfügbaren Dokumenten nicht gefunden."

Erfinde keine Informationen und ergänze nichts aus eigenem Wissen.
{history}
Kontext:
{context}

Frage: {question}

Antwort:""",
    input_variables=["context", "question", "history"],
)


def _format_history(history) -> str:
    """Format chat history entries for the prompt."""
    if not history:
        return ""
    parts = ["Bisheriges Gespräch:"]
    for entry in history:
        parts.append(f"Frage: {entry.question}\nAntwort: {entry.answer}")
    return "\n\n".join(parts) + "\n\n"


def clear_llm_cache() -> None:
    """Invalidate the entire LLM cache. Call after changing LLM parameters at runtime."""
    with _llm_cache_lock:
        _llm_cache.clear()


def get_llm(config: LoaderConfig) -> BedrockLLM | OllamaLLM:
    """Get the LLM based on configuration (cached per model+params key)."""
    llm_type = config.llm_type
    cache_key = f'{llm_type}:{config.llm_model}:{config.llm_temperature}:{config.llm_num_ctx}:{config.llm_timeout_seconds}'

    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    with _llm_cache_lock:
        if cache_key in _llm_cache:
            return _llm_cache[cache_key]
        if llm_type.lower() == 'bedrock':
            from langchain_aws import BedrockLLM
            llm = BedrockLLM(
                credentials_profile_name='default',
                region_name=config.region_name,
                endpoint_url=config.endpoint_url,
                model_id=config.model_id,
                model_kwargs={'temperature': 0.0, 'max_tokens_to_sample': 4096},
            )
        elif llm_type.lower() == 'ollama':
            llm = OllamaLLM(
                base_url=config.ollama_host,
                model=config.llm_model,
                temperature=config.llm_temperature,
                timeout=config.llm_timeout_seconds,
                num_ctx=config.llm_num_ctx,
            )
        else:
            raise ValueError(f'Unsupported LLM type: {llm_type}')
        _llm_cache[cache_key] = llm

    return _llm_cache[cache_key]


def retrieve(
    question: str,
    config: LoaderConfig,
    vector_store: VectorStore,
) -> tuple[list[Document], dict]:
    """Perform hybrid search (BM25 + kNN) and return deduplicated docs."""
    cleaned_question = question.strip()
    results_with_scores = vector_store.hybrid_search(cleaned_question, k=config.hybrid_k)

    seen: set[str] = set()
    unique_results: list = []
    threshold = config.hybrid_score_threshold
    for doc, score in results_with_scores:
        if doc.page_content not in seen and score >= threshold:
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
    history=None,
) -> Generator[str, None, None]:
    """Stream LLM tokens. Returns a generator yielding token strings."""
    if not docs:
        def _empty():
            yield "Zu dieser Frage wurden keine relevanten Dokumente gefunden."
        return _empty()

    context = '\n\n'.join([doc.page_content for doc in docs])
    history_text = _format_history(history)
    chain = (
        {
            'context': lambda x: context,
            'question': RunnablePassthrough(),
            'history': lambda x: history_text,
        }
        | _PROMPT_TEMPLATE
        | get_llm(config)
        | StrOutputParser()
    )
    return chain.stream(question.strip())


def search(question: str, config: LoaderConfig, vector_store: VectorStore):
    """Blocking search — retrieves docs and generates a complete answer."""
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
