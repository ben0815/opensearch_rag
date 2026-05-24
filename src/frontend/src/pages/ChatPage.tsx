import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Alert, Form } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { useInstanceStore } from "@/stores/instanceStore";
import { useChat } from "@/hooks/useChat";
import MessageBubble from "@/components/MessageBubble";

export default function ChatPage() {
  const { t } = useTranslation();
  const selectedInstance = useInstanceStore((s) => s.selectedInstance());
  const [question, setQuestion] = useState("");
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // false = user has scrolled up; auto-scroll is paused
  const autoScrollEnabled = useRef(true);

  const { messages, streaming, error, sendMessage, abort, clearMessages } = useChat({
    instanceId: selectedInstance?.id ?? null,
  });

  // Auto-scroll with rAF deferral:
  //   - rAF fires after the browser has processed any queued user input (scroll, click)
  //   - effect cleanup cancels the pending rAF when the next token arrives,
  //     so rapid token bursts collapse into one scroll per animation frame
  //   - double-checks autoScrollEnabled inside the rAF callback (may have changed
  //     if user scrolled between the effect firing and the next frame)
  useEffect(() => {
    if (!autoScrollEnabled.current) return;
    const id = requestAnimationFrame(() => {
      if (!autoScrollEnabled.current) return;
      const el = chatContainerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
  }, [messages]);

  // Track user scroll intent: near the bottom → keep auto-scrolling; scrolled up → pause
  const handleChatScroll = useCallback(() => {
    const el = chatContainerRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    autoScrollEnabled.current = distFromBottom < 100;
  }, []);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [question]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setQuestion("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    autoScrollEnabled.current = true;
    try {
      await sendMessage(q);
    } catch {
      /* sendMessage handles its own errors; this catches unexpected throws */
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSubmit(e as unknown as React.FormEvent);
    }
  }

  if (!selectedInstance) {
    return (
      <div className="d-flex h-100 align-items-center justify-content-center text-body-secondary">
        <div className="text-center">
          <i className="bi bi-collection fs-1 mb-3 d-block" />
          <p>{t("chat.selectInstance")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="d-flex flex-column h-100">
      {/* Header */}
      <div className="d-flex align-items-center justify-content-between p-3 border-bottom">
        <h5 className="mb-0">
          <i className="bi bi-chat-dots me-2" />
          {selectedInstance.name}
        </h5>
        {messages.length > 0 && (
          <Button variant="outline-secondary" size="sm" onClick={clearMessages}>
            <i className="bi bi-plus-circle me-1" />
            {t("chat.newChat")}
          </Button>
        )}
      </div>

      {/* Messages */}
      <div
        className="chat-messages"
        ref={chatContainerRef}
        onScroll={handleChatScroll}
      >
        {messages.length === 0 && (
          <div className="d-flex h-100 align-items-center justify-content-center text-body-secondary">
            <div className="text-center">
              <i className="bi bi-chat-left-dots fs-1 mb-3 d-block" />
              <p>{t("chat.placeholder")}</p>
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {error && (
          <Alert variant="warning" className="mx-auto" style={{ maxWidth: 500 }}>
            {error === "aborted" ? t("chat.aborted") : error}
          </Alert>
        )}
      </div>

      {/* Input */}
      <div className="p-3 border-top">
        <Form onSubmit={handleSubmit} className="d-flex gap-2 align-items-end">
          <div className="flex-grow-1">
            <textarea
              ref={textareaRef}
              className="form-control"
              placeholder={t("chat.placeholder")}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={streaming}
              style={{ resize: "none", minHeight: "60px", maxHeight: "200px", overflowY: "auto" }}
            />
            <div className="text-body-secondary mt-1" style={{ fontSize: "0.75rem" }}>
              {t("chat.sendHint")}
            </div>
          </div>
          {streaming ? (
            <Button variant="danger" onClick={abort} style={{ minWidth: 44 }}>
              <i className="bi bi-stop-fill" />
            </Button>
          ) : (
            <Button type="submit" disabled={!question.trim()} style={{ minWidth: 44 }}>
              <i className="bi bi-send-fill" />
            </Button>
          )}
        </Form>
      </div>
    </div>
  );
}
