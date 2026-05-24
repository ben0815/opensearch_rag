import { create } from "zustand";
import type { UserOut } from "@/types/api";

interface AuthState {
  user: UserOut | null;
  sessionLifetimeHours: number;
  setUser: (user: UserOut | null, sessionLifetimeHours?: number) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  sessionLifetimeHours: 8,
  setUser: (user, sessionLifetimeHours) =>
    set((s) => ({
      user,
      sessionLifetimeHours: sessionLifetimeHours ?? s.sessionLifetimeHours,
    })),
  clear: () => set({ user: null }),
}));
