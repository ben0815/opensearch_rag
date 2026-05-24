import { useCallback, useRef, useState } from "react";
import type { ChatDoneEvent, SourceChunk } from "@/types/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceChunk[];
  historyId?: number;
  retrieval_ms?: number;
  llm_generation_s?: number;
  pending?: boolean;
}

interface UseChatOptions {
  instanceId: number | null;
  onDone?: (historyId: number, durationS: number) => void;
}

const LLM_TIMEOUT_MS = 120_000;

export function useChat({ instanceId, onDone }: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startRef = useRef<number>(0);

  const sendMessage = useCallback(
    async (question: string) => {
      if (!instanceId || streaming) return;
      setError(null);

      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: question };
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        pending: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setStreaming(true);
      startRef.current = Date.now();

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      // LLM timeout
      const timer = setTimeout(() => ctrl.abort("timeout"), LLM_TIMEOUT_MS);

      let ttftReported = false;
      let firstTokenTime = 0;

      try {
        const resp = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() },
          credentials: "include",
          signal: ctrl.signal,
          body: JSON.stringify({ question, instance_id: instanceId }),
        });

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }

        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let sources: SourceChunk[] = [];
        let fullAnswer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";

          let eventType = "message";
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              const raw = line.slice(5).trim();
              if (!raw) continue;

              if (eventType === "sources") {
                try {
                  sources = JSON.parse(raw) as SourceChunk[];
                } catch {
                  /* ignore */
                }
                eventType = "message";
              } else if (eventType === "done") {
                try {
                  const doneData = JSON.parse(raw) as ChatDoneEvent;
                  const durationS = (Date.now() - startRef.current) / 1000;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMsg.id
                        ? {
                            ...m,
                            content: doneData.answer || fullAnswer,
                            sources,
                            pending: false,
                            historyId: doneData.history_id,
                            retrieval_ms: doneData.retrieval_ms,
                            llm_generation_s: doneData.llm_generation_s,
                          }
                        : m,
                    ),
                  );
                  // PATCH timing data
                  if (doneData.history_id) {
                    const ttftS = firstTokenTime
                      ? (firstTokenTime - startRef.current) / 1000
                      : undefined;
                    fetch(`/api/chat/history/${doneData.history_id}`, {
                      method: "PATCH",
                      headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": getCsrf(),
                      },
                      credentials: "include",
                      body: JSON.stringify({ duration_s: durationS, ttft_s: ttftS }),
                    }).catch(() => {});
                    onDone?.(doneData.history_id, durationS);
                  }
                } catch {
                  /* ignore */
                }
                eventType = "message";
              } else {
                // Regular token
                try {
                  const token = JSON.parse(raw) as string;
                  if (!ttftReported) {
                    ttftReported = true;
                    firstTokenTime = Date.now();
                  }
                  fullAnswer += token;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMsg.id
                        ? { ...m, content: fullAnswer, pending: false }
                        : m,
                    ),
                  );
                } catch {
                  /* ignore */
                }
              }
            } else if (line === "") {
              eventType = "message";
            }
          }
        }
      } catch (err) {
        const reason = (err as { message?: string })?.message ?? String(err);
        const aborted = reason === "timeout" || reason.includes("abort");
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: "", pending: false, sources: [] }
              : m,
          ),
        );
        setError(aborted ? "aborted" : reason);
      } finally {
        clearTimeout(timer);
        abortRef.current = null;
        setStreaming(false);
      }
    },
    [instanceId, streaming, onDone],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort("aborted");
  }, []);

  const clearMessages = useCallback(() => setMessages([]), []);

  return { messages, streaming, error, sendMessage, abort, clearMessages };
}

function getCsrf(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}
