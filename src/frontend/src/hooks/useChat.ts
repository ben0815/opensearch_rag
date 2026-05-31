import { useCallback, useEffect, useRef } from "react";
import type { ChatDoneEvent, SourceChunk } from "@/types/api";
import { useChatStore } from "@/stores/chatStore";

export type { ChatMessage } from "@/stores/chatStore";

interface UseChatOptions {
  instanceId: number | null;
  onDone?: (historyId: number, durationS: number) => void;
}

export function useChat({ instanceId, onDone }: UseChatOptions) {
  const messages  = useChatStore((s) => s.messages);
  const streaming = useChatStore((s) => s.streaming);
  const error     = useChatStore((s) => s.error);

  const startRef  = useRef<number>(0);
  const onDoneRef = useRef(onDone);
  useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  // Instanz-Wechsel erkennen: Store leeren wenn instanceId sich ändert
  useEffect(() => {
    const store = useChatStore.getState();
    if (store.instanceId !== null && store.instanceId !== instanceId) {
      store.clearChat();
    }
    if (instanceId !== null) {
      useChatStore.getState().setInstanceId(instanceId);
    }
  }, [instanceId]);

  const sendMessage = useCallback(async (question: string) => {
    // Alle Guards lesen imperativ aus dem Store — keine Closure-Abhängigkeiten
    const instanceId = useChatStore.getState().instanceId;
    if (!instanceId || useChatStore.getState().streaming) return;

    // gen + genIsStale vor dem ersten await capturen bzw. definieren
    const gen = useChatStore.getState().generation;
    const genIsStale = () => useChatStore.getState().generation !== gen;

    // Synchrone Writes vor dem ersten await — kein gen-Guard nötig
    useChatStore.getState().setError(null);

    const userMsg = { id: uid(), role: "user" as const, content: question };
    const assistantMsg = { id: uid(), role: "assistant" as const, content: "", pending: true };

    useChatStore.getState().setMessages((prev) => [...prev, userMsg, assistantMsg]);
    useChatStore.getState().setStreaming(true);
    startRef.current = Date.now();

    const ctrl = new AbortController();
    useChatStore.getState().setController(ctrl);

    let ttftReported = false;
    let firstTokenTime = 0;

    try {
      // ── Erster await — ab hier genIsStale() vor jedem Store-Write ──
      const resp = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() },
        credentials: "include",
        signal: ctrl.signal,
        body: JSON.stringify({ question, instance_id: instanceId }),
      });

      if (genIsStale()) return;

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      let sources: SourceChunk[] = [];
      let retrievalMs: number | undefined;
      let fullAnswer = "";

      for await (const { eventType, data } of readSSEStream(resp.body!.getReader())) {
        if (genIsStale()) return;

        if (eventType === "sources") {
          try {
            const payload = JSON.parse(data) as { docs: SourceChunk[]; retrieval_ms?: number };
            sources = payload.docs ?? [];
            retrievalMs = payload.retrieval_ms;
            if (genIsStale()) return;
            useChatStore.getState().setMessages((prev) =>
              prev.map((m) => m.id === assistantMsg.id ? { ...m, sources } : m)
            );
          } catch { /* ignore */ }

        } else if (eventType === "done") {
          try {
            const doneData = JSON.parse(data) as ChatDoneEvent;
            const durationS = (Date.now() - startRef.current) / 1000;
            if (genIsStale()) return;
            useChatStore.getState().setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsg.id
                  ? {
                      ...m,
                      content: doneData.answer || fullAnswer,
                      sources,
                      pending: false,
                      historyId: doneData.history_id,
                      retrieval_ms: retrievalMs,
                      llm_generation_s: doneData.llm_generation_s,
                    }
                  : m
              )
            );
            if (doneData.history_id) {
              const ttftS = firstTokenTime
                ? (firstTokenTime - startRef.current) / 1000
                : undefined;
              fetch(`/api/chat/history/${doneData.history_id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() },
                credentials: "include",
                body: JSON.stringify({ duration_s: durationS, ttft_s: ttftS }),
              }).catch(() => {});
              onDoneRef.current?.(doneData.history_id, durationS);
            }
          } catch { /* ignore */ }

        } else if (eventType === "error") {
          try {
            const errData = JSON.parse(data) as { message: string };
            const errorMessage = errData.message ?? "Server error";
            if (genIsStale()) return;
            useChatStore.getState().setError(errorMessage);
            useChatStore.getState().setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsg.id
                  ? { ...m, content: "", pending: false, sources: [] }
                  : m
              )
            );
            const currentInstanceId = useChatStore.getState().instanceId;
            if (currentInstanceId) {
              reportFailedHistory(
                question,
                currentInstanceId,
                errorMessage,
                (Date.now() - startRef.current) / 1000,
              );
            }
          } catch { /* ignore */ }

        } else {
          // Reguläres Token
          try {
            const token = JSON.parse(data) as string;
            if (typeof token === "string") {
              if (!ttftReported) {
                ttftReported = true;
                firstTokenTime = Date.now();
              }
              fullAnswer += token;
              if (genIsStale()) return;
              useChatStore.getState().setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, content: fullAnswer } : m
                )
              );
            }
          } catch { /* ignore */ }
        }
      }
    } catch (err) {
      const reason = (err as { message?: string })?.message ?? String(err);
      const isUserAbort = err instanceof DOMException && err.name === "AbortError";
      if (genIsStale()) return;
      useChatStore.getState().setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id
            ? { ...m, content: "", pending: false, sources: [] }
            : m
        )
      );
      useChatStore.getState().setError(isUserAbort ? "aborted" : reason);

      if (!isUserAbort) {
        const currentInstanceId = useChatStore.getState().instanceId;
        if (currentInstanceId) {
          reportFailedHistory(
            question,
            currentInstanceId,
            reason,
            (Date.now() - startRef.current) / 1000,
          );
        }
      }
    } finally {
      if (!genIsStale()) {
        useChatStore.getState().setController(null);
        useChatStore.getState().setStreaming(false);
        // Sicherheitsnetz: pending bereinigen falls Stream ohne event:done/error schloss
        useChatStore.getState().setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id && m.pending ? { ...m, pending: false } : m
          )
        );
      }
    }
  }, []); // Leere Deps — alle Werte werden imperativ aus dem Store gelesen

  const abort = useCallback(() => {
    useChatStore.getState().controller?.abort("aborted");
  }, []);

  const clearMessages = useCallback(() => {
    useChatStore.getState().clearChat();
  }, []);

  return { messages, streaming, error, sendMessage, abort, clearMessages };
}

// ── SSE helpers ───────────────────────────────────────────────────────────────

// Liest einen ReadableStream als SSE und liefert normalisierte { eventType, data }-Paare.
// eventType wird nach jeder data:-Zeile auf "message" zurückgesetzt (SSE-Standard).
async function* readSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
): AsyncGenerator<{ eventType: string; data: string }> {
  const decoder = new TextDecoder();
  let buf = "";
  // eventType AUSSERHALB der while-Schleife — überlebt Chunk-Grenzen
  let eventType = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const raw = line.slice(5).trim();
        if (raw) {
          yield { eventType, data: raw };
          eventType = "message";
        }
      } else if (line === "") {
        eventType = "message";
      }
    }
  }
}

function reportFailedHistory(
  question: string,
  instanceId: number,
  errorMessage: string,
  durationS: number,
): void {
  fetch("/api/chat/history/failed", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() },
    credentials: "include",
    body: JSON.stringify({
      question,
      instance_id: instanceId,
      error_type: "server_error",
      error_message: errorMessage,
      duration_s: durationS,
    }),
  }).catch(() => {});
}

function getCsrf(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

// uid() requires HTTPS; getRandomValues works everywhere
function uid(): string {
  return crypto.getRandomValues(new Uint32Array(3)).join("-");
}
