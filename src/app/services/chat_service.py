import json
import queue
import threading
import time
from app.loader.config import LoaderConfig
from app.loader.vector_store import VectorStore
from app import rag

# Sentinel emitted at end of sync generator — route handler does DB save then emits event: done
_DONE_SENTINEL_KEY = "__chat_done__"


def _generate_with_deadline(question, docs, config, history, timeout_s):
    """Yield LLM tokens from a daemon thread, enforcing a hard wall-clock deadline.

    The LLM runs in a background thread; the main generator polls a Queue every
    0.5 s and raises TimeoutError as soon as the deadline passes — regardless of
    whether tokens are still arriving.  This is necessary because the per-chunk
    httpx read timeout only fires when *no* bytes arrive for timeout_s seconds;
    a slow-but-continuous stream bypasses it entirely.
    """
    q: "queue.Queue[tuple[str, object]]" = queue.Queue()

    def _run() -> None:
        try:
            for token in rag.generate_stream(question, docs, config, history):
                q.put(("tok", token))
        except Exception as exc:
            q.put(("err", exc))
        finally:
            q.put(("end", None))

    threading.Thread(target=_run, daemon=True).start()

    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"LLM-Timeout nach {timeout_s}s — Antwortgenerierung abgebrochen"
            )
        try:
            kind, val = q.get(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue
        if kind == "tok":
            yield val
        elif kind == "err":
            raise val  # type: ignore[misc]
        else:  # "end"
            return


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
            "search_source": d.metadata.get("search_source"),
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
    for token in _generate_with_deadline(question, docs, config, history, config.llm_timeout_seconds):
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
