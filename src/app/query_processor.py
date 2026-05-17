from pathlib import Path

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


class QueryProcessor:
    def __init__(self, rag_system, config, vector_store):
        """
        Initialize QueryProcessor with a RAG system.

        Args:
            rag_system: The RAG system instance used for searching
            vector_store: The vector store instance used for semantic search
        """
        self.rag = rag_system
        self.vector_store = vector_store
        self.config = config

    def process_query(self, question):
        """
        Streaming generator for a user query.

        Yields:
            Tuples of (chat_history, semantic_table).
            - First yield: semantic results are shown immediately after retrieval;
              no assistant message yet.
            - Subsequent yields: assistant message grows token by token.
        """
        try:
            docs, _ = self.rag.retrieve(
                question=question,
                config=self.config,
                vector_store=self.vector_store,
            )
        except Exception as e:
            logger.error(f'Error in retrieve: {e}')
            yield [
                {'role': 'user', 'content': question},
                {'role': 'assistant', 'content': f'Fehler bei der Suche: {e}'},
            ], ''
            return

        semantic_table = self._format_semantic_results(docs)
        history = [{'role': 'user', 'content': question}]

        # Show semantic results immediately while the LLM starts generating
        yield history, semantic_table

        accumulated = ''
        try:
            for token in self.rag.generate_stream(question, docs, self.config):
                accumulated += token
                yield history + [{'role': 'assistant', 'content': accumulated}], semantic_table
        except Exception as e:
            logger.error(f'Error during streaming: {e}')
            accumulated += f'\n\n[Fehler: {e}]'

        if not accumulated:
            accumulated = 'Keine Antwort vom Modell erhalten.'

        yield history + [{'role': 'assistant', 'content': accumulated}], semantic_table

    def _format_semantic_results(self, semantic_results):
        """
        Format semantic search results into a readable table.

        Args:
            semantic_results (list): List of semantic search results

        Returns:
            str: Formatted semantic results table
        """
        semantic_table = ''
        processed_results = set()
        for result in semantic_results:
            if result.page_content not in processed_results:
                processed_results.add(result.page_content)
                source = result.metadata.get('source', '')
                document = Path(source).name if source else 'N/A'
                semantic_table += (
                    f"- Score: {result.metadata.get('score', 'N/A')} <br>"
                    f"  Document: {document} <br>"
                    f"  Page: {result.metadata.get('page', 'N/A')} <br>"
                    f"  Text: {result.page_content} <br> <br>"
                )
        return semantic_table
