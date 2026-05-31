import { create } from "zustand";
import type { SourceChunk } from "@/types/api";

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

interface ChatState {
  messages: ChatMessage[];
  streaming: boolean;
  error: string | null;
  instanceId: number | null;
  controller: AbortController | null;
  generation: number;
}

interface ChatActions {
  setMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  setStreaming: (v: boolean) => void;
  setError: (e: string | null) => void;
  setController: (c: AbortController | null) => void;
  setInstanceId: (id: number | null) => void;
  clearChat: () => void;
}

export const useChatStore = create<ChatState & ChatActions>((set, get) => ({
  messages: [],
  streaming: false,
  error: null,
  instanceId: null,
  controller: null,
  generation: 0,

  setMessages: (updater) => set((s) => ({ messages: updater(s.messages) })),
  setStreaming: (v) => set({ streaming: v }),
  setError: (e) => set({ error: e }),
  setController: (c) => set({ controller: c }),
  setInstanceId: (id) => set({ instanceId: id }),

  clearChat: () => {
    get().controller?.abort("aborted");
    set((s) => ({
      messages: [],
      streaming: false,
      error: null,
      controller: null,
      generation: s.generation + 1,
      // instanceId wird bewusst NICHT zurückgesetzt — Verantwortung liegt beim
      // useEffect in useChat.ts. clearChat() räumt nur Chat-Inhalt auf, nicht
      // den Navigations-Kontext. Ein Reset hier würde sendMessage nach
      // "Neuer Chat" blockieren (Guard: if (!instanceId) return).
    }));
  },
}));
