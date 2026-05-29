import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";
import type { ChatMessage } from "@/hooks/useChat";
import SourcesPanel from "./SourcesPanel";
import ThinkingIndicator from "./ThinkingIndicator";

marked.setOptions({ breaks: true });

interface Props {
  message: ChatMessage;
}

export default function MessageBubble({ message }: Props) {
  const { t } = useTranslation();

  const html = useMemo(() => {
    if (message.role !== "assistant" || !message.content.trim()) return "";
    const raw = marked.parse(message.content) as string;
    return DOMPurify.sanitize(raw);
  }, [message.content, message.role]);

  if (message.role === "user") {
    return (
      <div className="d-flex justify-content-end mb-3">
        <div className="chat-bubble user">
          <span style={{ whiteSpace: "pre-wrap" }}>{message.content}</span>
        </div>
      </div>
    );
  }

  const hasSources = (message.sources?.length ?? 0) > 0;
  // Treat leading whitespace / lone newlines as "not yet real text"
  const hasRealContent = message.content.trim().length > 0;
  // pending is false once the stream ends (done, error, or abort) — don't
  // show the spinner after an error cleared the content without adding text.
  const isWaiting = !hasRealContent && message.pending !== false;

  return (
    <div className="d-flex justify-content-start mb-3">
      <div className="chat-bubble assistant" style={{ maxWidth: "85%" }}>
        {isWaiting ? (
          <ThinkingIndicator
            label={hasSources ? t("chat.composing") : undefined}
          />
        ) : hasRealContent ? (
          <div
            className="markdown-body"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : null}
        {hasSources && (
          <SourcesPanel sources={message.sources!} />
        )}
      </div>
    </div>
  );
}
