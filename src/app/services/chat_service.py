import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ChatHistory
from app.loader.config import LoaderConfig
from app.loader.vector_store import VectorStore
from app import rag


def stream_answer(question: str, instance_slug: str, config: LoaderConfig, history=None):
    """
    Sync-Generator: liefert SSE-formatierte Strings.
    Läuft via iterate_in_threadpool() im Thread-Pool — blockiert den Event Loop nicht.

    Ablauf:
    1. event: sources  — Quell-Chunks als JSON (kommt sofort nach Retrieval)
    2. data: <token>   — LLM-Token für Token (JSON-kodiert, schützt gegen \\n im SSE-Format)
    3. event: done     — vollständige Antwort + Quellen für History-Speicherung
    """
    store = VectorStore.for_instance(config, instance_slug)
    docs, _ = rag.retrieve(question, config, store)

    context_data = [
        {
            "source": d.metadata.get("source", ""),
            "filename": (
                d.metadata.get("filename")
                or d.metadata.get("source", "").split("/")[-1]
            ),
            "page": d.metadata.get("page"),
            "score": d.metadata.get("score", 0),
            "excerpt": d.page_content[:300],
        }
        for d in docs
    ]
    yield f"event: sources\ndata: {json.dumps(context_data, ensure_ascii=False)}\n\n"

    # json.dumps() kodiert \n in Tokens — verhindert SSE-Protokoll-Bruch
    accumulated = []
    for token in rag.generate_stream(question, docs, config, history):
        accumulated.append(token)
        yield f"data: {json.dumps(token, ensure_ascii=False)}\n\n"

    full_answer = "".join(accumulated)
    payload = json.dumps({"answer": full_answer, "sources": context_data}, ensure_ascii=False)
    yield f"event: done\ndata: {payload}\n\n"


async def save_to_history(
    db: AsyncSession,
    user_id: int,
    instance_id: int,
    question: str,
    answer: str,
    context_docs: list,
) -> None:
    entry = ChatHistory(
        user_id=user_id,
        instance_id=instance_id,
        question=question,
        answer=answer,
        context_docs=context_docs,
    )
    db.add(entry)
    await db.commit()
