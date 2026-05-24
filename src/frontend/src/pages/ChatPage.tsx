import { useEffect, useRef, useState } from "react";
import { Button, Alert, Form } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { useInstanceStore } from "@/stores/instanceStore";
import { useChat } from "@/hooks/useChat";
import MessageBubble from "@/components/MessageBubble";

export default function ChatPage() {
  const { t } = useTranslation();
  const selectedInstance = useInstanceStore((s) => s.selectedInstance());
  const [question, setQuestion] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { messages, streaming, error, sendMessage, abort, clearMessages } = useChat({
    instanceId: selectedInstance?.id ?? null,
  });

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setQuestion("");
    await sendMessage(q);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
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
      <div className="chat-messages">
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
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-top">
        <Form onSubmit={handleSubmit} className="d-flex gap-2 align-items-end">
          <Form.Control
            as="textarea"
            rows={2}
            placeholder={t("chat.placeholder")}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={streaming}
            style={{ resize: "none" }}
          />
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
