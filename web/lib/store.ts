"use client";

import type { Session, User } from "@marketingos/api-client";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  workspaceId: string | null;
  hydrated: boolean;
  setSession: (s: Session) => void;
  setUser: (u: User) => void;
  setWorkspace: (id: string) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      workspaceId: null,
      hydrated: false,
      setSession: (s) => {
        const current = get().workspaceId;
        const keep = s.user.workspaces.some((w) => w.id === current);
        set({
          accessToken: s.access_token,
          refreshToken: s.refresh_token,
          user: s.user,
          workspaceId: keep ? current : s.user.workspaces[0]?.id ?? null,
        });
      },
      setUser: (u) => set({ user: u }),
      setWorkspace: (id) => set({ workspaceId: id }),
      clear: () => set({ accessToken: null, refreshToken: null, user: null, workspaceId: null }),
    }),
    {
      name: "marketingos-session",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ accessToken: s.accessToken, refreshToken: s.refreshToken, user: s.user, workspaceId: s.workspaceId }),
      onRehydrateStorage: () => () => useAuth.setState({ hydrated: true }),
    },
  ),
);
