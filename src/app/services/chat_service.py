import json
import time
from app.loader.config import LoaderConfig
from app.loader.vector_store import VectorStore
from app import rag

# Sentinel emitted at end of sync generator — route handler does DB save then emits event: done
_DONE_SENTINEL_KEY = "__chat_done__"


def stream_answer(question: str, instance_slug: str, config: LoaderConfig, history=None):
    """
    Sync-Generator: liefert SSE-formatierte Strings + abschließendes Sentinel-Dict.
    Läuft via iterate_in_threadpool() im Thread-Pool.

    Yielded sequence:
      1. "event: sources\\ndata: {...}\\n\\n"   — nach Retrieval
      2. "data: <token>\\n\\n"                  — LLM-Token für Token
      3. dict({"__chat_done__": True, ...})     — Sentinel für route handler (nicht gesendet)
    """
    store = VectorStore.for_instance(config, instance_slug)

    t_retrieval = time.monotonic()
    docs, _ = rag.retrieve(question, config, store)
    retrieval_ms = int((time.monotonic() - t_retrieval) * 1000)

    scores = [d.metadata.get("score", 0) for d in docs]
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

    sources_payload = {
        "docs": context_data,
        "retrieval_ms": retrieval_ms,
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
    }
    yield f"event: sources\ndata: {json.dumps(sources_payload, ensure_ascii=False)}\n\n"

    t_llm = time.monotonic()
    accumulated = []
    for token in rag.generate_stream(question, docs, config, history):
        accumulated.append(token)
        yield f"data: {json.dumps(token, ensure_ascii=False)}\n\n"

    llm_generation_s = round(time.monotonic() - t_llm, 2)
    full_answer = "".join(accumulated)

    # Sentinel — not sent to client; consumed by route handler for DB save
    yield {
        _DONE_SENTINEL_KEY: True,
        "answer": full_answer,
        "sources": context_data,
        "retrieval_ms": retrieval_ms,
        "llm_generation_s": llm_generation_s,
    }
