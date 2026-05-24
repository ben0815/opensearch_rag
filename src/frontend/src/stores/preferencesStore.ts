import { create } from "zustand";
import { persist } from "zustand/middleware";
import i18n from "@/i18n";

type Theme = "auto" | "light" | "dark";

interface PreferencesState {
  language: "de" | "en";
  theme: Theme;
  setLanguage: (lang: "de" | "en") => void;
  setTheme: (theme: Theme) => void;
  applyTheme: () => void;
}

function resolveTheme(theme: Theme): "light" | "dark" {
  if (theme !== "auto") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set, get) => ({
      language: "de",
      theme: "auto",
      setLanguage: (language) => {
        set({ language });
        i18n.changeLanguage(language);
      },
      setTheme: (theme) => {
        set({ theme });
        get().applyTheme();
      },
      applyTheme: () => {
        const resolved = resolveTheme(get().theme);
        document.documentElement.setAttribute("data-bs-theme", resolved);
      },
    }),
    { name: "rag-preferences", partialize: (s) => ({ language: s.language, theme: s.theme }) },
  ),
);
