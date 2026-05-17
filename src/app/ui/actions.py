from pathlib import Path
from typing import Any

import gradio as gr

from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


async def handle_file_upload(files: list[str], document_processor: Any):
    """
    Handle file upload and processing.

    Async generator — yields live status messages so the UI can display progress
    without waiting for the full processing to complete.

    Args:
        files: List of file paths
        document_processor: Document processor instance

    Yields:
        Status strings shown in the upload status textbox
    """
    if not files:
        logger.warning('No files provided for upload')
        yield 'Keine Dateien ausgewählt.'
        return

    total = len(files)
    try:
        for i, file in enumerate(files, 1):
            name = Path(file).name
            logger.info(f'Processing file {i}/{total}: {name}')
            yield f'[{i}/{total}] Verarbeite: {name} …'

            last_milestone = -1
            async for progress in document_processor.load_documents(file):
                milestone = int(progress) // 10 * 10
                if milestone > last_milestone or progress >= 100:
                    last_milestone = milestone
                    yield f'[{i}/{total}] {name}: {progress:.0f}%'

        yield f'Fertig — {total} Datei(en) verarbeitet.'
    except Exception as e:
        logger.error(f'Fehler beim Verarbeiten: {e}', exc_info=True)
        yield f'Fehler: {str(e)}'


def clear_chat() -> tuple[list, str, str]:
    """
    Clear chat history and inputs.

    Returns:
        tuple of (chat history, question input, semantic output)
    """
    logger.debug('Clearing chat history and inputs')
    return [], '', ''


async def update_documents_list(document_processor: Any):
    """Get list of indexed documents from OpenSearch."""
    try:
        docs = await document_processor.get_indexed_documents()
        logger.info(f'Indexed documents: {docs}')
        return [[f'{doc["title"]}({doc["id"]})'] for doc in docs]
    except Exception as e:
        logger.error(f'Error fetching indexed documents: {e}', exc_info=True)
        return []


async def show_document_details(evt: gr.SelectData, document_processor: Any):
    """Show document metadata when clicked."""
    try:
        doc_id = evt.value.split('(')[1].split(')')[0]
        doc_info = await document_processor.get_document_metadata(doc_id)
        logger.info(f'Document info: {doc_info}')
        if doc_info:
            # Prepare statistics
            stats = [
                ['File Name', doc_info.get('title', 'N/A')],
                ['File Size', f"{doc_info.get('file_size', 0) / 1024:.2f} KB"],
                ['Pages', str(doc_info.get('page_count', 0))],
                ['Indexed Date', doc_info.get('indexed_date', 'N/A')],
                ['Chunks', str(doc_info.get('chunk_count', 0))],
            ]
            return (
                f"### Document Details: {doc_info.get('title', 'Unknown')}",
                gr.update(visible=True),
                gr.update(visible=True),
                doc_info,
                stats,
            )
        return (
            '### Document Not Found',
            gr.update(visible=False),
            gr.update(visible=False),
            {},
            [],
        )
    except Exception as e:
        logger.error(f'Error fetching document details: {e}', exc_info=True)
        return (
            '### Error Loading Document',
            gr.update(visible=False),
            gr.update(visible=False),
            {'error': str(e)},
            [],
        )
