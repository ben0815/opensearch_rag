import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import type { ChatMessage } from "@/hooks/useChat";
import SourcesPanel from "./SourcesPanel";
import ThinkingIndicator from "./ThinkingIndicator";

marked.setOptions({ breaks: true });

interface Props {
  message: ChatMessage;
}

export default function MessageBubble({ message }: Props) {
  const html = useMemo(() => {
    if (message.role !== "assistant" || !message.content) return "";
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

  return (
    <div className="d-flex justify-content-start mb-3">
      <div className="chat-bubble assistant" style={{ maxWidth: "85%" }}>
        {message.pending && !message.content ? (
          <ThinkingIndicator />
        ) : (
          <>
            <div
              className="markdown-body"
              dangerouslySetInnerHTML={{ __html: html }}
            />
            {message.sources && message.sources.length > 0 && (
              <SourcesPanel sources={message.sources} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
