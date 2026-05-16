"""CLI tool for bulk ingestion of PDF files into the vector store."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# In Docker: ENV_FILE points to /app/secrets/.env (override values only).
# Locally: fall back to infra/.env relative to the project root.
_env_file = os.getenv('ENV_FILE') or str(Path(__file__).resolve().parents[2] / 'infra' / '.env')
load_dotenv(_env_file, override=False)

from app.loader import DocumentProcessor, LoaderConfig, VectorStore  # noqa: E402
from app.utils.logging_config import setup_logger  # noqa: E402

logger = setup_logger(__name__)


def _collect_pdfs(paths: list[Path], recursive: bool) -> list[Path]:
    """Collect all PDF files from the given paths."""
    collected = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() == '.pdf':
                collected.append(path)
            else:
                print(f'Skipping non-PDF file: {path}')
        elif path.is_dir():
            pattern = '**/*.pdf' if recursive else '*.pdf'
            found = sorted(path.glob(pattern))
            if not found:
                print(f'No PDF files found in: {path}')
            collected.extend(found)
        else:
            print(f'Path not found, skipping: {path}')
    return collected


async def ingest(files: list[Path], processor: DocumentProcessor) -> tuple[int, int]:
    """Ingest a list of PDF files. Returns (success_count, failure_count)."""
    success, failure = 0, 0
    total = len(files)

    for idx, file in enumerate(files, start=1):
        prefix = f'[{idx}/{total}] {file.name}'
        try:
            last_progress = 0.0
            async for progress in processor.load_documents(file):
                # Print progress on the same line
                bar_len = 30
                filled = int(bar_len * progress / 100)
                bar = '█' * filled + '░' * (bar_len - filled)
                print(f'\r{prefix}  [{bar}] {progress:5.1f}%', end='', flush=True)
                last_progress = progress
            print(f'\r{prefix}  [{"█" * 30}] 100.0%  ✓')
            success += 1
        except Exception as e:
            print(f'\r{prefix}  ✗ {e}')
            logger.error(f'Failed to ingest {file}: {e}', exc_info=True)
            failure += 1

    return success, failure


async def main(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths]
    files = _collect_pdfs(paths, recursive=args.recursive)

    if not files:
        print('No PDF files to process. Exiting.')
        return 1

    print(f'Found {len(files)} PDF file(s) to ingest.\n')

    config = LoaderConfig()
    vector_store = VectorStore(config)
    processor = DocumentProcessor(config, vector_store)

    success, failure = await ingest(files, processor)

    print(f'\n{"─" * 40}')
    print(f'Done: {success} succeeded, {failure} failed.')
    return 0 if failure == 0 else 1


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog='python -m app.ingest',
        description='Bulk-ingest PDF files into the OpenSearch RAG vector store.',
    )
    parser.add_argument(
        'paths',
        nargs='+',
        metavar='PATH',
        help='PDF file(s) or director(y/ies) to ingest.',
    )
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Recurse into subdirectories when a directory is given.',
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))


if __name__ == '__main__':
    cli()
