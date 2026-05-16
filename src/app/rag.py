from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_ollama import OllamaLLM

if TYPE_CHECKING:
    from langchain_aws import BedrockLLM
    from app.loader import LoaderConfig, VectorStore

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)

_llm_cache: dict[str, OllamaLLM | Any] = {}


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


def search(question: str, config: LoaderConfig, vector_store: VectorStore):
    """
    Perform enhanced semantic search and RAG with improved retrieval strategies.

    Args:
        question: Query string
        config: Loader configuration
        vector_store: Vector store instance

    Returns:
        Tuple of (semantic_results, rag_result)
    """
    try:
        store = vector_store.get_store()

        # Clean and prepare the query
        cleaned_question = question.strip()

        # Strategy 1: Similarity search with scores
        scored_results = store.similarity_search_with_relevance_scores(
            cleaned_question,
            k=5,
            score_threshold=0.5,
        )
        semantic_results = []
        for doc, score in scored_results:
            doc.metadata['score'] = round(score, 4)
            semantic_results.append(doc)

        # Strategy 2: MMR search for diversity (no score available)
        mmr_results = store.max_marginal_relevance_search(
            cleaned_question,
            k=3,
            fetch_k=10,
            lambda_mult=0.7,
        )
        for doc in mmr_results:
            doc.metadata.setdefault('score', 'MMR')
        semantic_results.extend(mmr_results)

        # Remove duplicates while preserving order
        seen = set()
        unique_results = []
        for doc in semantic_results:
            if doc.page_content not in seen:
                seen.add(doc.page_content)
                unique_results.append(doc)

        # Sort by score; MMR-only results (no numeric score) go last
        unique_results.sort(
            key=lambda x: float(x.metadata['score']) if isinstance(x.metadata.get('score'), (int, float)) else -1,
            reverse=True,
        )

        context = '\n\n'.join([doc.page_content for doc in unique_results[:5]])

        # Define the prompt template
        prompt = PromptTemplate(
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

        # Get LLM
        llm = get_llm(config)

        # Create the chain using the new style
        retrieval_chain = (
            {
                'context': lambda x: context,
                'question': RunnablePassthrough(),
            }
            | prompt
            | llm
            | StrOutputParser()
        )

        # Get RAG result with enhanced context
        rag_result = retrieval_chain.invoke(cleaned_question)

        # Add metadata about search quality
        search_metadata = {
            'total_results_found': len(semantic_results),
            'unique_results_used': len(unique_results),
            'search_strategies_used': ['similarity', 'mmr'],
            'top_result_score': float(unique_results[0].metadata['score'])
            if unique_results and isinstance(unique_results[0].metadata.get('score'), (int, float))
            else 0,
        }

        return unique_results, {
            'result': rag_result,
            'search_metadata': search_metadata,
        }

    except Exception as e:
        logger.error(f'Error in search: {str(e)}')
        raise


