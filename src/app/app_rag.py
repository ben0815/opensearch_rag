"""Main application entry point."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app import rag
from app.loader import DocumentProcessor, LoaderConfig, VectorStore
from app.query_processor import QueryProcessor
from app.ui.main import create_interface
from app.utils.logging_config import setup_logger

# In Docker: ENV_FILE points to /app/secrets/.env (override values only).
# Locally: fall back to infra/.env relative to the project root.
_env_file = os.getenv('ENV_FILE') or str(Path(__file__).resolve().parents[2] / 'infra' / '.env')
load_dotenv(_env_file, override=False)
logger = setup_logger(__name__)


def main(host: str | None = None, port: int | None = None) -> None:
    """
    Run the main application.

    Args:
        host: Optional host address
        port: Optional port number
    """
    config = LoaderConfig()
    config.validate()
    vector_store = VectorStore(config)
    processor = QueryProcessor(rag, config, vector_store)
    document_processor = DocumentProcessor(config, vector_store)
    demo, css = create_interface(config, processor, document_processor, vector_store)

    logger.info('Starting Gradio server...')
    try:
        app_host = host or os.getenv('APP_HOST', '127.0.0.1')
        app_port = port or int(os.getenv('APP_PORT', '8081'))
        demo.launch(
            server_name=app_host,
            server_port=app_port,
            share=False,
            show_error=True,
            css=css,
        )
    except Exception as e:
        logger.error(f'Error starting Gradio server: {e}')
        raise


if __name__ == '__main__':
    main()
