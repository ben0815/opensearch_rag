import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { InstanceOut } from "@/types/api";

interface InstanceState {
  instances: InstanceOut[];
  selectedId: number | null;
  setInstances: (instances: InstanceOut[]) => void;
  setSelectedId: (id: number | null) => void;
  selectedInstance: () => InstanceOut | null;
}

export const useInstanceStore = create<InstanceState>()(
  persist(
    (set, get) => ({
      instances: [],
      selectedId: null,
      setInstances: (instances) =>
        set((s) => {
          const ids = instances.map((i) => i.id);
          const selected = s.selectedId && ids.includes(s.selectedId) ? s.selectedId : (instances[0]?.id ?? null);
          return { instances, selectedId: selected };
        }),
      setSelectedId: (id) => set({ selectedId: id }),
      selectedInstance: () => {
        const { instances, selectedId } = get();
        return instances.find((i) => i.id === selectedId) ?? null;
      },
    }),
    { name: "rag-instance", partialize: (s) => ({ selectedId: s.selectedId }) },
  ),
);
